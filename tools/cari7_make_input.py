#!/usr/bin/env python3
"""Genera los inputs para ejecutar CARI-7A en modo batch (menú-less) y analizar
una rejilla de localizaciones por rigidez de corte vertical (Rc) para un nivel
de potencial heliocéntrico (HP) dado.

Rejilla (constantes compartidas con cari7_generate.py):
    Rc eje 0..18 GV paso 0.25 (73 nodos), alt 8.0..13.0 km paso 0.5 (11).
    Los puntos (lat, lon) se eligen por rigidez objetivo usando el mapa de la
    epoca que CARI-7A usara para la fecha del HP.
    HP eje: [300,400,...,1200] MV, cada uno con una fecha real de MV-DATES.L99
    cuyo HP coincide con el objetivo (±6 MV).

Salidas en el directorio de trabajo (workdir):
    grid_hp{hp}.loc     fichero de localizaciones (D2 = dosis efectiva ICRP-103)
    DEFAULT.INP         línea 5 = nombre del .loc
    CARI.INI            copia del stock con MENUS=NO! (modo batch)

Uso:
    python3 tools/cari7_make_input.py --hp 300 --cutoffs CARI_7A_DVD/CUTOFFS \
        --cari-ini CARI_7A_DVD/CARI.INI --work .
"""
import argparse, os

# ---- constantes de la rejilla (no cambiar sin regenerar) ----
# Eje de rigidez de la rejilla: 0..18 GV paso 0.25 (73 nodos). El paso sale de
# medir el error de interpolacion con CARI-7A: 0.50 GV da 0.40 % maximo, 0.25
# lo deja despreciable. Uniforme para conservar la aritmetica de indices de
# doseRateGrid.
RC_TARGETS = [round(0.25 * i, 2) for i in range(73)]
ALT_VALUES = [8.0 + 0.5 * i for i in range(11)]   # sin cambios
HP_DATES = {                                            # objetivo HP -> fecha MV-DATES.L99
    300: "2007/06/00", 400: "1994/11/00", 500: "1963/03/00",
    600: "1992/11/00", 700: "1980/05/00", 800: "2003/09/00",
    900: "1969/06/00", 1000: "1958/09/00", 1100: "1960/01/00", 1200: "1990/07/00",
}


def rc_sample_targets(n=150):
    """Objetivos de Rc para el barrido. Sobremuestrea el eje: los puntos reales
    del mapa no caen exactamente en los nodos, asi que se corre de mas y luego
    se remuestrea. Incluye siempre los nodos del eje y llega al maximo global
    (17.64 GV en IGRF2010)."""
    hi = 17.64
    extra = [round(hi * i / (n - 1), 4) for i in range(n)]
    vals = sorted(set([t for t in RC_TARGETS if t <= hi] + extra))
    return vals


def loc_line(lat, lon, alt, date):
    """Formato estilo EXAMPLES.LOC, <= 66 caracteres.
    H0 = media diaria (es la HORA del dia, no el potencial heliocentrico).
    D2 = dosis efectiva ICRP-103."""
    ns = "N" if lat >= 0 else "S"
    line = "{ns}, {lat:7.4f}, E, {lon:6.2f}, K, {alt:6.2f} , {date}, H0, D2, P0, C4, S0".format(
        ns=ns, lat=abs(lat), lon=lon, alt=alt, date=date)
    assert len(line) <= 66, "línea LOC de %d chars: %s" % (len(line), line)
    return line


def write_loc(hp, work, cutoffs_dir, chunk=0):
    """Escribe el .LOC de un nivel de HP. Los puntos se eligen por rigidez
    objetivo usando el mapa de la epoca que CARI-7A usara para esa fecha: si se
    eligieran con otro mapa, las Rc reales caerian lejos de los objetivos."""
    import os as _os
    from cari7_cutoffs import load_cutoff_map, epoch_file_for_year, points_for_rc_targets
    date = HP_DATES[hp]
    epoch = epoch_file_for_year(int(date[:4]))
    rcmap = load_cutoff_map(_os.path.join(cutoffs_dir, epoch))
    picks = points_for_rc_targets(rcmap, rc_sample_targets(), tol=0.13)
    points = [(la, lo, alt) for (la, lo, _rc) in picks for alt in ALT_VALUES]
    chunks = [points] if chunk <= 0 else [points[i:i + chunk] for i in range(0, len(points), chunk)]
    paths = []
    for k, pts in enumerate(chunks):
        name = "grid_hp%d.loc" % hp if len(chunks) == 1 else "grid_hp%d_p%d.loc" % (hp, k)
        path = _os.path.join(work, name)
        with open(path, "w") as f:
            f.write("C, barrido de rigidez CARI-7A HP=%d MV\n" % hp)
            f.write("C, %s, epoca %s, D2 (ICRP-103)\n" % (date, epoch))
            f.write("START-------------------------------------------------\n")
            for la, lo, alt in pts:
                f.write(loc_line(la, lo, alt, date) + "\n")
            f.write("STOP--------------------------------------------------------\n")
        paths.append(path)
    return paths


def write_default_inp(hp, work, loc_name="grid_hp%d.loc"):
    path = os.path.join(work, "DEFAULT.INP")
    name = loc_name % hp if "%d" in loc_name else loc_name
    with open(path, "w") as f:
        f.write("0000/00/00\n 0 \n 0 \n 2 \n%s\n" % name)
        f.write("! generado por tools/cari7_make_input.py (las 4 primeras líneas se ignoran para .LOC)\n")
    return path


def patch_cari_ini(cari_ini_src, work, os_name):
    """Copia el CARI.INI stock y fuerza MENUS=NO! (batch) y el OS correcto."""
    with open(cari_ini_src, "r", errors="replace") as f:
        txt = f.read()
    txt = txt.replace("MENUS     = YES", "MENUS     = NO!")
    target = "UNIX" if os_name == "unix" else "WIN"
    txt = txt.replace("OS        = UNIX", "OS        = " + target)
    txt = txt.replace("OS        = WIN", "OS        = " + target)
    path = os.path.join(work, "CARI.INI")
    with open(path, "w") as f:
        f.write(txt)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hp", required=True, type=int, choices=sorted(HP_DATES))
    ap.add_argument("--cutoffs", required=True,
                    help="directorio CUTOFFS/ de la distribucion de CARI-7A")
    ap.add_argument("--cari-ini", required=True, help="CARI.INI stock de la distribución")
    ap.add_argument("--work", default=".", help="directorio de trabajo (debe contener el binario y los datos)")
    ap.add_argument("--os", default="unix", choices=["unix", "win"])
    args = ap.parse_args()
    loc = write_loc(args.hp, args.work, args.cutoffs)
    dinp = write_default_inp(args.hp, args.work)
    ini = patch_cari_ini(args.cari_ini, args.work, args.os)
    print("escritos:", loc, "|", dinp, "|", ini)


if __name__ == "__main__":
    main()
