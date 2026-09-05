#!/usr/bin/env python3
"""Driver del camino SEP: genera un `MY_MODEL.OUT` con un espectro de protones
arbitrario y los inputs batch para correrlo sobre el eje `Rc 0:18:0.25` ×
`alt 8.0:13.0:0.5` de CARI-7A.

Reutiliza la aritmetica de indices de `cari7_make_input.py` (RC_TARGETS,
ALT_VALUES, rc_sample_targets, points_for_rc_targets) y `cari7_parse_ans.py`
para parsear la salida: la rejilla SEP comparte exactamente el mismo orden
(rc, alt) que la rejilla GCR.

Formato de `MY_MODEL.OUT`: identico al `BO11_GCR.OUT` distribuido --
    linea 1: epoca (p.ej. 1968.041096)
    linea 2: cabecera de columnas (se ignora)
    filas:   Z, E_GeV, F   (bloques por Z, cada Z con su propia malla)
Unidades documentadas (HELP.TXT de CARI-7A, seccion 3.D): nucleos/(m2-sr-s-GeV)
para Z=1..28. El campo 11 de cada linea .LOC selecciona el espectro por punto:
7 = MY_MODEL.OUT, 2 = BO'11 nativo, 5 = LaRC Feb56 SPE, 6 = LaRC Sep89 SPE.

La puerta de unidades cm2/m2 (T4 del plan sep-goes-model) vive en
`cari7_sep_gate.py`; este modulo solo escribe inputs reproducibles.
"""
import argparse, os, shutil

from cari7_make_input import (ALT_VALUES, rc_sample_targets)
from cari7_cutoffs import (load_cutoff_map, epoch_file_for_year,
                           points_for_rc_targets)

# nombres y codigos de espectro usados por CARI-7A (HELP.TXT seccion 3.D)
MY_MODEL_NAME = "MY_MODEL.OUT"
BO11_FILE = "BO11_GCR.OUT"
FEB56_FILE = "Feb56SPE.OUT"
SEP89_FILE = "Sep89SPE.OUT"

SP_MYMODEL = 7        # MY_MODEL.OUT (espectro definido por usuario)
SP_BO11 = 2           # Badhwar-O'Neill 2011
SP_FEB56 = 5          # LaRC Feb 1956 SPE (fluencia total del evento)
SP_SEP89 = 6          # LaRC Sep 1989 SPE (fluencia total del evento)

# Fecha mensual (DD=00) comun para los LOC SEP. Con un espectro dado (opcion 7)
# la fecha no modula el resultado; se fija una constante para conservar la
# aritmetica de la rejilla y poder comparar contra los espectros nativos.
SEP_DATE = "2000/01/00"

# Estructura minima del BO11_GCR.OUT distribuido.
Z_MAX = 28            # bloques H..Ni
Z1_GRID_N = 99        # filas del bloque Z=1; Z>=2 llevan 100


def sep_loc_line(lat, lon, alt, date, spectrum=SP_MYMODEL):
    """Linea LOC de un punto de la rejilla SEP (mismo formato y aritmetica que
    `loc_line` de cari7_make_input, pero con el campo de espectro parametrizado).

    El campo 11 de la linea es el espectro primario por punto (C2=BO'11,
    C5=Feb56SPE, C7=MY_MODEL.OUT); el campo 9 (D2) fija la dosis efectiva
    ICRP-103, que es la QUANTITY que lee cari7_parse_ans.py."""
    ns = "N" if lat >= 0 else "S"
    line = "{ns}, {lat:7.4f}, E, {lon:6.2f}, K, {alt:6.2f} , {date}, H0, D2, P0, C{sp}, S0".format(
        ns=ns, lat=abs(lat), lon=lon, alt=alt, date=date, sp=spectrum)
    assert len(line) <= 66, "linea LOC de %d chars: %s" % (len(line), line)
    return line


def write_sep_loc(work, cutoffs_dir, spectrum, date=SEP_DATE, chunk=150,
                  rcmap=None, tag=None):
    """Escribe los inputs batch de un barrido SEP: un fichero `.loc` por lote
    sobre la rejilla Rc_objetivo x ALT_VALUES (mismos ejes e indices que
    `cari7_make_input.write_loc`). Devuelve la lista de rutas de los .loc.

    Los puntos se eligen por rigidez objetivo con el mapa de la epoca de la
    fecha (igual que el GCR); si `rcmap` se pasa directamente, se usa ese
    (util para tests y para fijar la epoca en comparaciones cruzadas)."""
    if rcmap is None:
        epoch = epoch_file_for_year(int(date[:4]))
        rcmap = load_cutoff_map(os.path.join(cutoffs_dir, epoch))
    picks = points_for_rc_targets(rcmap, rc_sample_targets(), tol=0.13)
    points = [(la, lo, alt) for (la, lo, _rc) in picks for alt in ALT_VALUES]
    chunks = [points] if chunk <= 0 else [points[i:i + chunk]
                                          for i in range(0, len(points), chunk)]
    paths = []
    for k, pts in enumerate(chunks):
        name = "sep_s%d.loc" % spectrum if len(chunks) == 1 else "sep_s%d_p%d.loc" % (spectrum, k)
        if tag:
            name = "sep_%s_s%d.loc" % (tag, spectrum) if len(chunks) == 1 else \
                   "sep_%s_s%d_p%d.loc" % (tag, spectrum, k)
        path = os.path.join(work, name)
        with open(path, "w") as f:
            f.write("C, barrido espectral SEP CARI-7A: espectro=%d, fecha %s, D2 (ICRP-103)\n"
                    % (spectrum, date))
            f.write("START-------------------------------------------------\n")
            for la, lo, alt in pts:
                f.write(sep_loc_line(la, lo, alt, date, spectrum) + "\n")
            f.write("STOP--------------------------------------------------------\n")
        paths.append(path)
    return paths


def load_ion_grids(cari_dir):
    """Mallas de energia (GeV) por Z del `BO11_GCR.OUT` distribuido: es la
    estructura que debe replicar `MY_MODEL.OUT` para que el lector de CARI-7A
    encuentre todos los bloques. Devuelve {z: [E_GeV, ...]} en orden de fichero."""
    path = os.path.join(cari_dir, "GCR_MODELS", BO11_FILE)
    grids = {}
    with open(path, errors="replace") as f:
        for line in f:
            t = line.split()
            if len(t) < 3 or not t[0].isdigit():
                continue
            z = int(t[0])
            grids.setdefault(z, []).append(float(t[1]))
    if not grids:
        raise SystemExit("no se pudo leer %s (¿falta la distribucion CARI-7A?)" % path)
    return grids


def project_proton_flux(rows, grid):
    """Proyecta un espectro arbitrario (E_GeV, F) sobre una malla de energia
    con interpolacion lineal en log(E) y en log(F) cuando ambos extremos son
    positivos (lineal en F si alguno es cero). Fuera del rango, extrapolacion
    plana en F. Devuelve filas (E, F) listas para `write_my_model`."""
    import math
    pts = sorted((math.log(e), f) for e, f in rows if e > 0)
    out = []
    for e in grid:
        if len(pts) == 1:
            out.append((e, pts[0][1]))
            continue
        x = math.log(e)
        if x <= pts[0][0]:
            out.append((e, pts[0][1]))
        elif x >= pts[-1][0]:
            out.append((e, pts[-1][1]))
        else:
            lo, hi = 0, len(pts) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if pts[mid][0] <= x:
                    lo = mid
                else:
                    hi = mid
            x1, f1 = pts[lo]
            x2, f2 = pts[hi]
            if f1 > 0 and f2 > 0:
                f = f1 * (f2 / f1) ** ((x - x1) / (x2 - x1))
            else:
                f = f1 + (f2 - f1) * (x - x1) / (x2 - x1)
            out.append((e, f))
    return out


def write_my_model(path, z1_rows, epoch="1968.041096", grids=None):
    """Escribe `MY_MODEL.OUT` en el formato de `BO11_GCR.OUT`.

    `z1_rows` es una lista de (E_GeV, F) para protones (Z=1). Si se pasa
    `grids` (load_ion_grids), se anaden los bloques Z=2..28 con F=0 para
    conservar la estructura completa que distribuye el programa; sin grids se
    escribe solo el bloque Z=1 (mas simple, pero solo valido si el lector de
    CARI-7A acepta un unico bloque; lo decide la puerta de T5)."""
    with open(path, "w") as f:
        f.write(epoch + "\n")
        f.write("   Z       E            F\n")
        for e, fl in sorted(z1_rows):
            f.write("%4d %10.3E %12.3E\n" % (1, e, fl))
        if grids:
            for z in sorted(grids):
                if z == 1:
                    continue
                for e in grids[z]:
                    f.write("%4d %10.3E %12.3E\n" % (z, e, 0.0))
    return path


def write_my_model_from_file(cari_dir, src_name, dst_path):
    """Copia literal de un espectro distribuido (BO11_GCR.OUT, Feb56SPE.OUT,
    Sep89SPE.OUT) a MY_MODEL.OUT: la reproduccion de la puerta de unidades y
    las pruebas de linealidad de T5 se construyen sobre copias verbatim."""
    shutil.copy(os.path.join(cari_dir, "GCR_MODELS", src_name), dst_path)
    return dst_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    p_loc = sub.add_parser("loc", help="escribir los inputs batch LOC de un barrido")
    p_loc.add_argument("--spectrum", type=int, default=SP_MYMODEL,
                       help="codigo de espectro en el campo 11 (7=MY_MODEL)")
    p_loc.add_argument("--date", default=SEP_DATE)
    p_loc.add_argument("--cutoffs", required=True,
                       help="directorio CUTOFFS/ de la distribucion CARI-7A")
    p_loc.add_argument("--work", default=".")
    p_loc.add_argument("--tag", default=None, help="prefijo de nombre de fichero")

    p_mod = sub.add_parser("model", help="escribir MY_MODEL.OUT")
    p_mod.add_argument("--z1-file", required=True,
                       help="texto con filas 'E_GeV F' por linea (espectro de protones)")
    p_mod.add_argument("--epoch", default="1968.041096")
    p_mod.add_argument("--out", default=MY_MODEL_NAME)
    p_mod.add_argument("--cari-dir",
                       help="si se da, anade los bloques Z=2..28 a cero desde BO11_GCR.OUT")

    args = ap.parse_args()
    if args.mode == "loc":
        paths = write_sep_loc(args.work, args.cutoffs, args.spectrum,
                              date=args.date, tag=args.tag)
        print("escritos %d LOC en %s (espectro %d, fecha %s)"
              % (len(paths), args.work, args.spectrum, args.date))
        for p in paths:
            with open(p) as f:
                n = sum(1 for line in f if line.startswith(("N,", "S,")))
            print("  %s: %d puntos" % (p, n))
    elif args.mode == "model":
        rows = []
        with open(args.z1_file) as f:
            for line in f:
                t = line.split()
                if len(t) >= 2:
                    rows.append((float(t[0]), float(t[1])))
        grids = load_ion_grids(args.cari_dir) if args.cari_dir else None
        write_my_model(args.out, rows, epoch=args.epoch, grids=grids)
        print("escrito %s (%d filas Z=1%s)" % (
            args.out, len(rows), " + bloques Z=2..%d a cero" % Z_MAX if grids else ""))


if __name__ == "__main__":
    main()