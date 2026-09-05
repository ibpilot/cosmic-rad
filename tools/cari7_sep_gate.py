#!/usr/bin/env python3
"""Puerta de unidades cm²/m² (T4 del plan `sep-goes-model`).

Reproduce con `MY_MODEL.OUT` un espectro **incorporado** de CARI-7A y exige
coincidencia contra el resultado del camino nativo del mismo espectro. La
documentacion de la FAA es ambigua entre cm² y m²: un factor 10⁴ silencioso
convierte una dosis defendible en basura. Esta puerta no se resuelve
calibrando un offset: se resuelve corriendo, y el ratio medido se imprime.

Referencias de la puerta (ambas con el MISMO fichero distribuido copiado
literal a `GCR_MODELS/MY_MODEL.OUT`, campo LOC 7):
  1. BO'11 nativo (campo 2) contra MY_MODEL: mismo espectro y mismas unidades
     fisicas (nucleos/(m2-sr-s-GeV)) -> el ratio debe ser 1. Es la puerta dura.
  2. Feb56 SPE nativo (campo 5) contra MY_MODEL: diagnostico de la normalizacion
     fluencia<->flujo del camino SPE, sin tolerancia fija (se imprime el 10^x
     del ratio para leer de que orden es).

Uso (CI, con la distribucion CARI-7A ya descargada por setup-cari7a):
    python3 tools/cari7_sep_gate.py --cari-dir CARI_7A_DVD \
        --binary "cari7a_4.2.0(intel_linux)" \
        --cutoffs CARI_7A_DVD/CUTOFFS
Exit 0 si la puerta dura pasa; != 0 si el ratio se sale de la tolerancia.
"""
import argparse, glob, math, os, shutil, sys

import cari7_generate as cg
import cari7_sep_input as sep
from cari7_make_input import write_default_inp, patch_cari_ini
from cari7_cutoffs import points_for_rc_targets, load_cutoff_map, epoch_file_for_year
from cari7_parse_ans import parse_ans

DEFAULT_TOLERANCE = 0.05          # 5 %: arrastra el ruido del selftest existente
DEFAULT_DATE = "2002/01/00"       # epoca del BO11_GCR.OUT distribuido (baked)
GRID_STEP = 4                     # 19 Rc x 11 alt para la puerta rapida


def compare_rate_maps(a, b):
    """Compara dos resultados de CARI-7A `{ (rc_gv, alt_km): rate_usvh }`.

    Devuelve (n, max_dev, mean_dev, min_ratio, max_ratio, sameset):
      - n: claves en comun
      - max_dev/mean_dev: desviacion relativa maxima/media de a frente a b
      - min_ratio/max_ratio: rango del cociente a/b
      - sameset: True si los conjuntos de claves (rc, alt) coinciden exactamente
    Una discrepancia de unidades cm²/m² aparece como ratio ~1e4 o ~1e-4."""
    ka, kb = set(a), set(b)
    sameset = ka == kb
    keys = sorted(ka & kb)
    if not keys:
        return 0, float("inf"), float("inf"), 0.0, 0.0, sameset
    ratios = [a[k] / b[k] for k in keys]
    devs = [abs(r - 1.0) for r in ratios]
    return (len(keys), max(devs), sum(devs) / len(devs),
            min(ratios), max(ratios), sameset)


def _binpath(cari, binary, os_name, wine):
    b = os.path.join(cari, binary)
    if not os.path.exists(b):
        sys.exit("no existe el binario %s" % b)
    if os_name == "unix" and not wine:
        os.chmod(b, 0o755)
    return b


def _run_cari(cmd, cwd, env, verbose):
    """Ejecuta el binario. Con --verbose muestra el stdout/stderr COMPLETO del
    binario (para diagnosticar en CI, donde el runner corta el log); sin
    verbose, comportamiento identico a cari7_generate.run (ultimos 3k)."""
    import subprocess
    if not verbose:
        cg.run(cmd, cwd=cwd, env=env)
        return
    print(">", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if r.stdout:
        print("--- stdout CARI (completo) ---")
        print(r.stdout)
    if r.stderr:
        print("--- stderr CARI (completo) ---")
        print(r.stderr)
    if r.returncode != 0:
        sys.exit("ERROR: exit %d" % r.returncode)


def _diagnose_missing_ans(work, loc, ans):
    """Cuando CARI termina sin escribir el .ANS, vuelca lo que pueda explicarlo:
    contenido de DEFAULT.INP, primeras lineas del .LOC y que ficheros de salida
    dejo el binario en el directorio de trabajo."""
    print("--- diagnostico: no existe %s ---" % ans)
    dinp = os.path.join(work, "DEFAULT.INP")
    if os.path.exists(dinp):
        print("DEFAULT.INP:")
        print(open(dinp).read())
    if os.path.exists(loc):
        lines = open(loc).read().splitlines()
        print("LOC (%d lineas):" % len(lines))
        for l in lines[:12]:
            print("  |%s|" % l.rstrip())
    print("ficheros generados por el binario en %s:" % work)
    for name in sorted(os.listdir(work)):
        low = name.lower()
        if low.endswith((".ans", ".out", ".rpt", ".sum", ".dat", ".log")):
            size = os.path.getsize(os.path.join(work, name))
            print("  %-28s %8d bytes" % (name, size))


def run_spectrum(cari, binary, spectrum, date, os_name="unix", wine=None,
                 chunk=150, tag=None, rcmap=None, cutoffs=None, verbose=False):
    """Corre CARI-7A sobre la rejilla SEP completa para un espectro (campo 11)
    y devuelve { (rc_gv, alt_km): rate_usvh }."""
    if rcmap is None:
        epoch = epoch_file_for_year(int(date[:4]))
        rcmap = load_cutoff_map(os.path.join(cutoffs, epoch))
    paths = sep.write_sep_loc(cari, cutoffs, spectrum, date=date, chunk=chunk,
                              rcmap=rcmap, tag=tag)
    binpath = _binpath(cari, binary, os_name, wine)
    env = None
    prefix = []
    if wine:
        prefix = [wine]
        env = dict(os.environ, WINEDEBUG="-all",
                   WINEPREFIX=os.path.expanduser("~/.wine-cari7a"))
    patch_cari_ini(os.path.join(cari, "CARI.INI"), cari, os_name)
    rates = {}
    for loc in paths:
        write_default_inp(0, cari, loc_name=os.path.basename(loc))
        _run_cari(prefix + [binpath], cari, env, verbose)
        ans = os.path.splitext(loc)[0] + ".ans"
        if not os.path.exists(ans):
            _diagnose_missing_ans(cari, loc, ans)
            hits = sorted(glob(os.path.join(cari, os.path.basename(ans)[:-4] + "*.ans")),
                          key=os.path.getmtime)
            if len(hits) == 1:
                print("AVISO: CARI escribio %s en vez de %s; se usa esa."
                      % (os.path.basename(hits[0]), os.path.basename(ans)))
                ans = hits[0]
            else:
                sys.exit("no se genero %s (¿CARI fallo?)" % ans)
        for rc, alt, _hp, rate in parse_ans(ans, 0):
            rates[(rc, alt)] = rate
    return rates


def run_points(cari, binary, spectrum, date, points, os_name="unix", wine=None,
               verbose=False):
    """Corre CARI-7A sobre una lista pequena de puntos (lat, lon, alt_km)."""
    tag = "probe_%d" % spectrum
    binpath = _binpath(cari, binary, os_name, wine)
    env = None
    prefix = []
    if wine:
        prefix = [wine]
        env = dict(os.environ, WINEDEBUG="-all",
                   WINEPREFIX=os.path.expanduser("~/.wine-cari7a"))
    patch_cari_ini(os.path.join(cari, "CARI.INI"), cari, os_name)
    loc = os.path.join(cari, tag + ".loc")
    with open(loc, "w") as f:
        f.write("C, probe SEP espectro=%d fecha %s D2\n" % (spectrum, date))
        f.write("START-------------------------------------------------\n")
        for la, lo, alt in points:
            f.write(sep.sep_loc_line(la, lo, alt, date, spectrum) + "\n")
        f.write("STOP--------------------------------------------------------\n")
    write_default_inp(0, cari, loc_name=tag + ".loc")
    _run_cari(prefix + [binpath], cari, env, verbose)
    ans = os.path.join(cari, tag + ".ans")
    if not os.path.exists(ans):
        _diagnose_missing_ans(cari, loc, ans)
        hits = sorted(glob(os.path.join(cari, tag + "*.ans")), key=os.path.getmtime)
        if len(hits) == 1:
            print("AVISO: CARI escribio %s en vez de %s; se usa esa."
                  % (os.path.basename(hits[0]), os.path.basename(ans)))
            ans = hits[0]
        else:
            sys.exit("no se genero %s (¿CARI fallo?)" % ans)
    return {(rc, alt): rate for rc, alt, _hp, rate in parse_ans(ans, 0)}


def probe_points(cari, rcmap, n_rc=3, alts=(8.0, 10.5, 13.0)):
    """Puntos representativos para el barrido de fechas: n_rc rigideces
    repartidas (polo, media, ecuador) x alts."""
    targets = [0.0, 8.0, 16.0][:n_rc]
    pts = []
    for t in targets:
        picks = points_for_rc_targets(rcmap, [t], tol=0.5)
        if not picks:
            continue
        la, lo, _ = picks[0]
        for alt in alts:
            pts.append((la, lo, alt))
    return pts


def summarize(label, n, max_dev, mean_dev, min_ratio, max_ratio, sameset,
              tol):
    rmed = math.sqrt(min_ratio * max_ratio)
    exp10 = round(math.log10(rmed)) if rmed > 0 else None
    print("[gate] %s" % label)
    print("        puntos=%d  mismo conjunto Rc/alt=%s" % (n, sameset))
    print("        ratio min/med/max = %.6g / %.6g / %.6g  (10^%s)"
          % (min_ratio, rmed, max_ratio, exp10 if exp10 is not None else "?"))
    print("        desviacion max rel = %.4f%%  media = %.4f%%  (umbral %.1f%%)"
          % (max_dev * 100, mean_dev * 100, tol * 100))
    return max_dev <= tol and n > 0 and sameset


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cari-dir", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--cutoffs", required=True)
    ap.add_argument("--date", default=DEFAULT_DATE,
                    help="fecha de la comparacion principal (mensual, DD=00)")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    ap.add_argument("--grid-step", type=int, default=GRID_STEP,
                    help="muestrear el eje Rc cada N pasos (1 = rejilla completa)")
    ap.add_argument("--os", default="unix", choices=["unix", "win"])
    ap.add_argument("--wine", help="ruta a wine para ejecutar el .exe")
    ap.add_argument("--probe-dates",
                    default="1998/01/00,2000/01/00,2002/01/00,2005/01/00,2007/01/00",
                    help="fechas del probe de sensibilidad solar")
    ap.add_argument("--no-probe", action="store_true",
                    help="saltar el probe de fechas (solo la puerta principal)")
    ap.add_argument("--verbose", action="store_true",
                    help="mostrar el stdout/stderr completo del binario CARI")
    args = ap.parse_args()

    cari = os.path.abspath(args.cari_dir)
    gcr = os.path.join(cari, "GCR_MODELS")
    for req in (os.path.join(gcr, sep.BO11_FILE),
                os.path.join(gcr, sep.FEB56_FILE),
                os.path.join(cari, "CARI.INI"),
                os.path.abspath(args.cutoffs)):
        if not os.path.exists(req):
            sys.exit("no existe %s (¿distribucion CARI-7A incompleta?)" % req)

    # Fecha principal y mapa de la epoca (compartido por todos los runs).
    epoch = epoch_file_for_year(int(args.date[:4]))
    rcmap = load_cutoff_map(os.path.join(args.cutoffs, epoch))
    targets = [t for i, t in enumerate(
        [round(0.25 * j, 2) for j in range(73)]) if i % args.grid_step == 0]

    # --- puerta dura: BO'11 nativo (C2) vs MY_MODEL (C7) ---
    my_model = os.path.join(gcr, sep.MY_MODEL_NAME)
    backup = None
    if os.path.exists(my_model):
        backup = my_model + ".bak_t4"
        shutil.copy(my_model, backup)
    try:
        shutil.copy(os.path.join(gcr, sep.BO11_FILE), my_model)
        print("### Puerta BO'11: MY_MODEL.OUT <- copia literal de %s ###"
              % sep.BO11_FILE)
        # rejilla reducida para la puerta; la rejilla completa la barre T6
        rcmap_gate = {k: v for k, v in rcmap.items()
                      if any(abs(v - t) <= 0.25 for t in targets)}
        r7 = run_spectrum(cari, args.binary, sep.SP_MYMODEL, args.date,
                          os_name=args.os, wine=args.wine, rcmap=rcmap_gate,
                          cutoffs=args.cutoffs, tag="gate",
                          verbose=args.verbose)
        r2 = run_spectrum(cari, args.binary, sep.SP_BO11, args.date,
                          os_name=args.os, wine=args.wine, rcmap=rcmap_gate,
                          cutoffs=args.cutoffs, tag="gate",
                          verbose=args.verbose)
        n, mx, mn, minr, maxr, same = compare_rate_maps(r7, r2)
        ok = summarize("BO'11 nativo (C2) vs MY_MODEL=BO11_GCR.OUT (C7) @ %s"
                       % args.date, n, mx, mn, minr, maxr, same,
                       args.tolerance)
        print("RATIO_BO11 = %.6g  (10^%s)"
              % (math.sqrt(minr * maxr),
                 round(math.log10(math.sqrt(minr * maxr))) if minr * maxr > 0 else "?"))
        hard_ok = ok

        if not args.no_probe:
            # --- diagnostico: sensibilidad de la fecha (modulacion solar) ---
            pts = probe_points(cari, rcmap)
            print("### Probe de fechas: %d puntos %s (BO'11 C2 vs C7) ###"
                  % (len(pts), [(la, lo, round(a, 1)) for la, lo, a in pts]))
            for date in args.probe_dates.split(","):
                r7p = run_points(cari, args.binary, sep.SP_MYMODEL, date, pts,
                                 os_name=args.os, wine=args.wine,
                                 verbose=args.verbose)
                r2p = run_points(cari, args.binary, sep.SP_BO11, date, pts,
                                 os_name=args.os, wine=args.wine,
                                 verbose=args.verbose)
                n, mx, mn, minr, maxr, same = compare_rate_maps(r7p, r2p)
                if n:
                    print("[probe] %s  n=%d  ratio %g..%g  desv max %.2f%%"
                          % (date, n, minr, maxr, mx * 100))

            # --- diagnostico: normalizacion fluencia<->flujo SPE ---
            shutil.copy(os.path.join(gcr, sep.FEB56_FILE), my_model)
            r7p = run_points(cari, args.binary, sep.SP_MYMODEL, args.date, pts,
                             os_name=args.os, wine=args.wine,
                             verbose=args.verbose)
            r5p = run_points(cari, args.binary, sep.SP_FEB56, args.date, pts,
                             os_name=args.os, wine=args.wine,
                             verbose=args.verbose)
            n, mx, mn, minr, maxr, same = compare_rate_maps(r7p, r5p)
            if n:
                rmed = math.sqrt(minr * maxr)
                print("RATIO_FEB56 = %.6g  (10^%s)  <- MY_MODEL=Feb56SPE.OUT (C7) / Feb56 nativo (C5); "
                      "1/dur-efectiva si la copia es fluencia (cm-2) leida como flujo (m-2-s-1)"
                      % (rmed, round(math.log10(rmed)) if rmed > 0 else "?"))
    finally:
        if backup:
            shutil.copy(backup, my_model)
            os.remove(backup)

    if not hard_ok:
        sys.exit("PUERTA DE UNIDADES FALLIDA: el camino MY_MODEL no reproduce un "
                 "espectro incorporado dentro del %.1f %% (ver RATIO_BO11 arriba)"
                 % (args.tolerance * 100))
    print("PUERTA DE UNIDADES OK: MY_MODEL.OUT reproduce un espectro incorporado "
          "dentro del %.1f %%" % (args.tolerance * 100))


if __name__ == "__main__":
    main()