#!/usr/bin/env python3
"""Genera los inputs para ejecutar CARI-7A en modo batch (menú-less) y analizar
una rejilla de localizaciones (lat × alt) para un nivel de potencial
heliocéntrico (HP) dado.

Rejilla (constantes compartidas con cari7_generate.py):
    lat 0..90 paso 1° (91), alt 8.0..13.0 km paso 0.5 (11), lon 0°E (representativo)
    HP eje: [300,400,...,1200] MV, cada uno con una fecha real de MV-DATES.L99
    cuyo HP coincide con el objetivo (±6 MV).

Salidas en el directorio de trabajo (workdir):
    grid_hp{hp}.loc     fichero de localizaciones (D2 = dosis efectiva ICRP-103)
    DEFAULT.INP         línea 5 = nombre del .loc
    CARI.INI            copia del stock con MENUS=NO! (modo batch)

Uso:
    python3 tools/cari7_make_input.py --hp 300 --cari-ini CARI.INI --work .
"""
import argparse, os

# ---- constantes de la rejilla (no cambiar sin regenerar) ----
LAT_VALUES = [float(i) for i in range(0, 91)]          # 0..90 paso 1
ALT_VALUES = [8.0 + 0.5 * i for i in range(11)]        # 8.0..13.0 paso 0.5
HP_DATES = {                                            # objetivo HP -> fecha MV-DATES.L99
    300: "2007/06/00", 400: "1994/11/00", 500: "1963/03/00",
    600: "1992/11/00", 700: "1980/05/00", 800: "2003/09/00",
    900: "1969/06/00", 1000: "1958/09/00", 1100: "1960/01/00", 1200: "1990/07/00",
}
LON = 0.00  # meridiano representativo (Europa). Limitación documentada: |lat|-sólo.


def loc_line(lat, alt, date):
    # Formato estilo EXAMPLES.LOC, <= 66 caracteres.
    line = "N, {lat:7.4f}, E, {lon:6.2f}, K, {alt:6.2f} , {date}, H0, D2, P0, C4, S0".format(
        lat=lat, lon=LON, alt=alt, date=date)
    assert len(line) <= 66, "línea LOC de %d chars: %s" % (len(line), line)
    return line


def write_loc(hp, work, chunk=0):
    """Escribe el .LOC para un nivel de HP. Si chunk>0, parte la rejilla en
    ficheros grid_hp{hp}_p{k}.loc de `chunk` puntos cada uno (util si el
    tiempo por punto es alto y un fichero de 1001 líneas tardaría demasiado)."""
    date = HP_DATES[hp]
    points = [(lat, alt) for lat in LAT_VALUES for alt in ALT_VALUES]
    if chunk <= 0:
        chunks = [points]
    else:
        chunks = [points[i:i + chunk] for i in range(0, len(points), chunk)]
    paths = []
    for k, pts in enumerate(chunks):
        name = "grid_hp%d.loc" % hp if len(chunks) == 1 else "grid_hp%d_p%d.loc" % (hp, k)
        path = os.path.join(work, name)
        with open(path, "w") as f:
            f.write("C, Cosmic Radiation Flight Calculator - grid de dosis (lat x alt) para HP=%d MV\n" % hp)
            f.write("C, Fecha: %s (HP real ~%d MV, fuente MV-DATES.L99), lon=%g E, tally D2 (ICRP-103 eff. dose)\n"
                    % (date, hp, LON))
            f.write("START-------------------------------------------------\n")
            for lat, alt in pts:
                f.write(loc_line(lat, alt, date) + "\n")
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
    ap.add_argument("--cari-ini", required=True, help="CARI.INI stock de la distribución")
    ap.add_argument("--work", default=".", help="directorio de trabajo (debe contener el binario y los datos)")
    ap.add_argument("--os", default="unix", choices=["unix", "win"])
    args = ap.parse_args()
    loc = write_loc(args.hp, args.work)
    dinp = write_default_inp(args.hp, args.work)
    ini = patch_cari_ini(args.cari_ini, args.work, args.os)
    print("escritos:", loc, "|", dinp, "|", ini)
    print("puntos en %s: %d" % (loc, len(LAT_VALUES) * len(ALT_VALUES)))


if __name__ == "__main__":
    main()
