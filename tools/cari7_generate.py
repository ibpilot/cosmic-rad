#!/usr/bin/env python3
"""Orquestador del pipeline CARI-7A: genera inputs, ejecuta el binario en modo
batch (menú-less) para un nivel de HP y parsea la salida .ANS a CSV.

Se ejecuta en CI (Linux x86_64 o Windows). Uso en un job por nivel de HP:

    python3 tools/cari7_generate.py --hp 300 \
        --cari-dir CARI_7A_DVD --binary "cari7a_4.2.0(intel_linux)" \
        --out rates_hp300.csv

Firma del binario Linux: necesita chmod +x; dependencias típicas de Fortran:
libgfortran5 (instalar con apt en el runner).

Autocomprobación de fidelidad (job aparte en CI):
    python3 tools/cari7_generate.py --selftest-only \
        --cari-dir CARI_7A_DVD --binary "cari7a_4.2.0(intel_linux)"
Ejecuta el EXAMPLES.LOC distribuido y compara la salida con EXAMPLES.ANS
(tolerancia 5 %), probando que la configuración batch reproduce la referencia
oficial del programa.
"""
import argparse, csv, os, shutil, subprocess, sys
from cari7_make_input import write_loc, write_default_inp, patch_cari_ini
from cari7_parse_ans import parse_ans


def run(cmd, cwd, env=None):
    print(">", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if r.stdout:
        print(r.stdout[-3000:])
    if r.stderr:
        sys.stderr.write(r.stderr[-3000:])
    if r.returncode != 0:
        sys.stderr.write("ERROR: exit %d\n" % r.returncode)
        sys.exit(1)


def selftest(cari, binary, os_name, wine=None):
    """Corre el EXAMPLES.LOC distribuido y compara contra EXAMPLES.ANS."""
    binpath = os.path.join(cari, binary)
    if not os.path.exists(binpath):
        sys.exit("no existe el binario %s" % binpath)
    if os_name == "unix" and not wine:
        os.chmod(binpath, 0o755)
    shutil.copy(os.path.join(cari, "Examples", "EXAMPLES.LOC"), os.path.join(cari, "SELFTEST.LOC"))
    with open(os.path.join(cari, "DEFAULT.INP"), "w") as f:
        f.write("0000/00/00\n 0 \n 0 \n 2 \nSELFTEST.LOC\n")
    patch_cari_ini(os.path.join(cari, "CARI.INI"), cari, os_name)
    env = None
    prefix = []
    if wine:
        prefix = [wine]
        env = dict(os.environ, WINEDEBUG="-all", WINEPREFIX=os.path.expanduser("~/.wine-cari7a"))
    run(prefix + [binpath], cwd=cari, env=env)

    def key(lat, alt, unit, date, qty):
        return (abs(float(lat)), float(alt), unit, date, qty)

    ref = {}
    for line in open(os.path.join(cari, "Examples", "EXAMPLES.ANS"), errors="replace"):
        t = [x.strip() for x in line.split(",")]
        if len(t) < 11 or not t[0].replace(".", "").replace("-", "").isdigit():
            continue
        ref[key(t[0], t[2], t[3], t[4], t[11] if len(t) > 11 else t[10])] = float(t[8])

    got = {}
    for line in open(os.path.join(cari, "SELFTEST.ANS"), errors="replace"):
        t = [x.strip() for x in line.split(",")]
        if len(t) < 11 or not t[0].replace(".", "").replace("-", "").isdigit():
            continue
        got[key(t[0], t[2], t[3], t[4], t[11] if len(t) > 11 else t[10])] = float(t[8])

    common = set(ref) & set(got)
    if len(common) == 0:
        sys.exit("SELFTEST FALLÓ: ninguna fila coincide entre EXAMPLES.ANS y SELFTEST.ANS")
    worst = 0.0
    for k in common:
        err = abs(got[k] - ref[k]) / ref[k]
        worst = max(worst, err)
    print("SELFTEST: %d filas comparadas de %d referencia; error máx relativo %.4f"
          % (len(common), len(ref), worst))
    if worst > 0.05:
        sys.exit("SELFTEST FALLÓ: desviación > 5%% (%f)" % worst)
    print("SELFTEST OK (reproduce la referencia oficial dentro del 5 %%)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hp", type=int, help="nivel de HP (300..1200); opcional con --selftest-only")
    ap.add_argument("--cari-dir", required=True, help="directorio de la distribución CARI-7A")
    ap.add_argument("--binary", required=True, help="nombre del binario dentro de cari-dir")
    ap.add_argument("--cutoffs", required=True,
                    help="directorio CUTOFFS/ de la distribucion de CARI-7A")
    ap.add_argument("--out", help="CSV de salida (requerido sin --selftest-only)")
    ap.add_argument("--chunk", type=int, default=0,
                    help="partir el .LOC en lotes de N puntos (0 = un solo fichero)")
    ap.add_argument("--selftest-only", action="store_true")
    ap.add_argument("--os", default="unix", choices=["unix", "win"])
    ap.add_argument("--wine", help="ruta al binario de wine/wineloader (ejecuta el .exe bajo Wine)")
    args = ap.parse_args()

    cari = os.path.abspath(args.cari_dir)
    if args.selftest_only:
        selftest(cari, args.binary, args.os, args.wine)
        return
    if args.hp is None or not args.out:
        ap.error("--hp y --out son requeridos salvo con --selftest-only")

    env = None
    cmd_prefix = []
    if args.wine:
        cmd_prefix = [args.wine]
        env = dict(os.environ, WINEDEBUG="-all",
                   WINEPREFIX=os.path.expanduser("~/.wine-cari7a"))

    ini_src = os.path.join(cari, "CARI.INI")
    if not os.path.exists(ini_src):
        sys.exit("no existe CARI.INI en %s" % cari)
    binpath = os.path.join(cari, args.binary)
    if not os.path.exists(binpath):
        sys.exit("no existe el binario %s" % binpath)
    if args.os == "unix" and not args.wine:
        os.chmod(binpath, 0o755)

    loc_files = write_loc(args.hp, cari, args.cutoffs, chunk=args.chunk)
    patch_cari_ini(ini_src, cari, args.os)
    rows = []
    for loc in loc_files:
        write_default_inp(args.hp, cari, loc_name=os.path.basename(loc))
        run(cmd_prefix + [binpath], cwd=cari, env=env)
        ans = os.path.splitext(loc)[0] + ".ans"
        if not os.path.exists(ans):
            sys.exit("no se generó %s (¿CARI falló?)" % ans)
        rows.extend(parse_ans(ans, args.hp))
    n_written = 0
    for loc in loc_files:
        with open(loc) as f:
            n_written += sum(1 for line in f if line.startswith(("N,", "S,")))
    if len(rows) != n_written:
        sys.stderr.write("AVISO: %d puntos escritos, %d parseados\n" % (n_written, len(rows)))
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rc_gv", "alt_km", "hp_mv", "rate_usvh"])
        w.writerows(rows)
    print("OK %d puntos -> %s" % (len(rows), args.out))


if __name__ == "__main__":
    main()
