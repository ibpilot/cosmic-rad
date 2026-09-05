#!/usr/bin/env python3
"""Cuatro puertas de linealidad del camino SEP (T5 del plan `sep-goes-model`).

CARI-7A acepta espectros personalizados via `MY_MODEL.OUT` (campo C7), pero NO
documenta una exportacion monoenergetica. Antes de aceptar un kernel construido
con espectros base estrechos hay que demostrar que el transporte es LINEAL:

  1. Escalado:   dosis(k*F) == k*dosis(F)           para k=10 y k=100 (tol 1 %)
  2. Superposicion: dosis(A+B) == dosis(A)+dosis(B)     (tol 1 %)
  3. Convergencia de binning: 53 bins vs 106 bins sobre un espectro GLE real
     (tol 1 %)
  4. Reproduccion: reconstruir con el kernel (MY_MODEL) un espectro incorporado
     y comparar contra la corrida directa de CARI (C2 nativo). Tol 5 %.

Fallar CUALQUIERA aborta el workflow y dispara el fallback AniMAIRE completo.
No hay kernel parcheado: un kernel no lineal miente mas cuanto mas duro es el
evento, que es justo el caso que importa.

La puerta 4 es la MISMA reproduccion que verifica `cari7_sep_gate.py` (T4);
este script la incluye para poder correrse autonomo, y el workflow puede
saltarla con `--skip-reproduction` cuando el gate de T4 ya corrio en el mismo
job (el plan T5 dice: "El ratio de T4 se reutiliza como primera puerta").

Uso (CI, con la distribucion CARI-7A ya descargada por setup-cari7a):
    python3 tools/cari7_sep_linearity.py --cari-dir CARI_7A_DVD \
        --binary "cari7a_4.2.0(intel_linux)" --cutoffs CARI_7A_DVD/CUTOFFS
Exit 0 si las puertas activas pasan; != 0 si alguna se sale de su tolerancia.
"""
import argparse, math, os, shutil, sys

import cari7_sep_input as sep
from cari7_sep_gate import (compare_rate_maps, run_spectrum, summarize)
from cari7_cutoffs import load_cutoff_map, epoch_file_for_year

# Tolerancias del plan T5.
TOL_SCALE = 0.01            # 1 %
TOL_SUPERPOSITION = 0.01    # 1 %
TOL_BINNING = 0.01          # 1 %
TOL_REPRODUCTION = 0.05     # 5 % (arrastra el ruido del selftest existente)

# Dominio del kernel (Q85/contexto): protones 50 MeV - 20 GeV.
E_MIN_GEV = 0.05
E_MAX_GEV = 20.0

# Ley de potencia de prueba: F(E) = A * E^-gamma (nucleos/(m2-sr-s-GeV), E GeV).
# A y gamma en el rango de un GLE real cerca del pico. El valor absoluto no
# importa: las puertas verifican la LINEALIDAD del transporte, no la dosis.
BASE_A = 1.0e4
BASE_GAMMA = 3.5


def log_rows(e_lo, e_hi, n_bins, flux_at, include_lo=True, include_hi=True):
    """Muestrea `flux_at(E)` en n_bins LOGARITMICOS entre e_lo y e_hi (GeV) ->
    filas (E, F) listas para MY_MODEL.OUT. Si n_bins == 1, un solo punto medio.

    `include_lo`/`include_hi` permiten excluir un extremo: util para concatenar
    dos bandas contiguas sin duplicar el borde compartido (superposicion)."""
    if n_bins <= 1:
        e = math.sqrt(e_lo * e_hi)
        return [(e, flux_at(e))]
    lmin, lmax = math.log(e_lo), math.log(e_hi)
    idxs = [i for i in range(n_bins)
            if (include_lo or i > 0) and (include_hi or i < n_bins - 1)]
    return [(math.exp(lmin + (lmax - lmin) * i / (n_bins - 1)),
             flux_at(math.exp(lmin + (lmax - lmin) * i / (n_bins - 1))))
            for i in idxs]


def power_law(e):
    return BASE_A * math.pow(e, -BASE_GAMMA)


def power_law_rows(n_bins):
    """Espectro de prueba de ancho completo (ley de potencia) en n_bins log."""
    return log_rows(E_MIN_GEV, E_MAX_GEV, n_bins, power_law)


def band_rows(e_lo, e_hi, n_bins=8, include_lo=True, include_hi=True):
    """Ley de potencia confinada a [e_lo, e_hi]: la componente espectral A o B
    de la superposicion. Fuera de la banda el espectro es cero (no se escribe).
    `include_hi=False` excluye el borde superior (para que A no duplique el
    borde compartido con B)."""
    return log_rows(e_lo, e_hi, n_bins, power_law,
                    include_lo=include_lo, include_hi=include_hi)


def gle_rows_from_fixture(fixture_path, n_bins, baseline_path=None):
    """Espectro de prueba con la FORMA real del exceso SEP de un GLE.

    Lee el fixture GOES de T2 (GLE73: tools/fixtures/goes/g16_2021-10-28.json),
    toma la muestra de pico del canal integral >=500 MeV y construye el espectro
    diferencial del EVENTO (no del fondo): al flujo de la muestra de pico se le
    resta el baseline de un dia tranquilo (por defecto el 2021-10-27, el dia
    previo al GLE73, que viaja como fixture justo para esto).

    El exceso (E_medio_GeV, dF/dE) se proyecta luego sobre n_bins logaritmicos
    entre 50 MeV y 20 GeV. Los canales cuyo exceso no es positivo (fondo >=
    senal) se descartan: un flujo diferencial negativo no es fisico y ensuciaria
    la forma.

    La magnitud es arbitraria (la puerta verifica la CONVERGENCIA al duplicar
    los bins, no la dosis absoluta), pero la FORMA es la del evento real con su
    rodilla y su cola dura, que es justo donde una cuadratura de 53 bins podria
    no converger si el kernel no es lineal."""
    import json
    def _load(p):
        with open(p) as fh:
            return json.load(fh)
    fx = _load(fixture_path)
    integ = fx.get("integral_500_keV") or []
    if not integ:
        raise SystemExit("fixture GLE sin canal integral: %s" % fixture_path)
    peak = max(range(len(integ)), key=lambda i: integ[i] or 0.0)
    chans = fx.get("channels") or []
    diff = fx.get("diff") or []
    if not chans or len(diff) <= peak or len(diff[peak]) < len(chans):
        raise SystemExit("fixture GLE sin canales diferenciales en el pico: %s"
                         % fixture_path)

    # Baseline por defecto: el dia previo al GLE73 (mismo satelite, tranquilo).
    if baseline_path is None:
        baseline_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "fixtures", "goes", "g16_2021-10-27.json")
    bg = None
    if baseline_path and os.path.exists(baseline_path):
        bfx = _load(baseline_path)
        bdiff = bfx.get("diff") or []
        # Fondo medio del dia previo en la misma ventana horaria que el pico.
        lo = max(0, peak - 12)
        hi = min(len(bdiff), peak + 12)
        if bdiff and lo < hi:
            n = hi - lo
            bg = [sum(bdiff[i][j] for i in range(lo, hi)
                      if bdiff[i][j] is not None) / n for j in range(13)]

    rows = []
    for j, c in enumerate(chans):
        v = diff[peak][j]
        if v is None or v <= 0:
            continue
        if bg is not None:
            v -= bg[j]
            if v <= 0:
                continue
        e_gev = math.sqrt(c["lo_keV"] * c["hi_keV"]) * 1e-6   # keV -> GeV
        # Solo canales con senal SEP limpia (P8+ ~>80 MeV): por debajo, el
        # exceso del GLE73 es pequeno y el fondo residual ensucia la forma
        # (P7 a 54 MeV da una pendiente no fisica). El espectro de prueba se
        # define con la parte dura y limpia del evento; hacia 50 MeV (borde del
        # dominio) se extrapola plano.
        if e_gev < 0.08:
            continue
        rows.append((e_gev, float(v) * 1e-2))
    if len(rows) < 5:
        raise SystemExit("fixture GLE con muy pocos canales positivos en el pico")
    return log_rows(E_MIN_GEV, E_MAX_GEV, n_bins,
                    _interp_from_rows(rows))


def _interp_from_rows(rows):
    """Devuelve flux_at(E) que interpola en log-log las filas (E, F) del
    espectro del fixture. Por ENCIMA del ultimo canal extrapola con la pendiente
    local (ley de potencia del ultimo tramo): una cola plana hasta 20 GeV no es
    fisica y dominaria la integral. Por DEBAJO del primer canal extrapola PLANO
    (el primer canal retenido esta cerca del borde inferior del dominio; la
    pendiente local ahi es ruido del fondo y extrapolarla produce subidas no
    fisicas)."""
    import bisect
    pts = sorted((math.log(e), math.log(f)) for e, f in rows if e > 0 and f > 0)
    if not pts:
        raise SystemExit("espectro GLE sin puntos positivos para interpolar")

    def flux_at(e):
        x = math.log(e)
        if x <= pts[0][0]:
            return math.exp(pts[0][1])
        if x >= pts[-1][0]:
            i = max(0, len(pts) - 2)
            x1, y1 = pts[i]
            x2, y2 = pts[-1]
            return math.exp(y2 + (y2 - y1) / (x2 - x1) * (x - x2))
        i = bisect.bisect_right([p[0] for p in pts], x)
        x1, y1 = pts[i - 1]
        x2, y2 = pts[i]
        if x2 == x1:
            return math.exp(y1)
        return math.exp(y1 + (y2 - y1) * (x - x1) / (x2 - x1))

    return flux_at


# --- metricas puras (testeables sin el binario CARI) -----------------------
# Cada gate reduce a comparar dos mapas de dosis y decidir con su tolerancia.
# Separar la metrica permite probar la logica con mapas sinteticos y hacer la
# prueba negativa del plan (inyectar un factor no lineal -> puerta roja) sin
# necesitar el binario.

def scale_metric(base, scaled, k):
    """Desviacion de dosis(k*F) frente a k*dosis(F), punto a punto.

    Devuelve (n, max_dev, mean_dev) como compare_rate_maps pero con la
    referencia ya escalada: la comparacion es scaled[k]/(k*base[k])."""
    expect = {pt: k * v for pt, v in base.items()}
    n, mx, mn, minr, maxr, same = compare_rate_maps(scaled, expect)
    return n, mx, mn, minr, maxr, same


def superposition_metric(a, b, ab):
    """Desviacion de dosis(A+B) frente a dosis(A)+dosis(B), punto a punto."""
    expect = {pt: a.get(pt, 0.0) + b.get(pt, 0.0) for pt in set(a) | set(b)}
    return compare_rate_maps(ab, expect)


# --- ejecucion sobre CARI-7A -------------------------------------------------

def _rcmap_gate(cutoffs, date, grid_step):
    """Mapa de rigidez restringido a los objetivos del eje muestreados."""
    epoch = epoch_file_for_year(int(date[:4]))
    rcmap = load_cutoff_map(os.path.join(cutoffs, epoch))
    targets = [round(0.25 * j, 2) for j in range(73) if j % grid_step == 0]
    return {k: v for k, v in rcmap.items()
            if any(abs(v - t) <= 0.25 for t in targets)}


def _write_my_model(cari, rows):
    """Escribe GCR_MODELS/MY_MODEL.OUT desde filas (E_GeV, F), conservando los
    bloques Z=2..28 a cero que espera el lector de CARI-7A."""
    gcr = os.path.join(cari, "GCR_MODELS")
    dst = os.path.join(gcr, sep.MY_MODEL_NAME)
    grids = sep.load_ion_grids(cari)
    sep.write_my_model(dst, rows, grids=grids)
    return dst


def run_rows(cari, binary, rows, date, cutoffs, os_name="unix", wine=None,
             verbose=False, grid_step=4, tag=None):
    """Escribe MY_MODEL.OUT con `rows` y corre el barrido C7 (espectro 7) sobre
    la rejilla reducida. Devuelve { (rc_gv, alt_km): rate_usvh }."""
    _write_my_model(cari, rows)
    rcmap_gate = _rcmap_gate(cutoffs, date, grid_step)
    return run_spectrum(cari, binary, sep.SP_MYMODEL, date, os_name=os_name,
                        wine=wine, rcmap=rcmap_gate, cutoffs=cutoffs,
                        tag=tag, verbose=verbose)


def gate_scale(cari, binary, date, args):
    """dosis(k*F) == k*dosis(F) para k=10 y k=100 (tol 1 %)."""
    rows = power_law_rows(53)
    base = run_rows(cari, binary, rows, date, args.cutoffs, os_name=args.os,
                    wine=args.wine, verbose=args.verbose,
                    grid_step=args.grid_step)
    ok = True
    for k in (10.0, 100.0):
        scaled = run_rows(cari, binary, [(e, k * f) for (e, f) in rows], date,
                          args.cutoffs, os_name=args.os, wine=args.wine,
                          verbose=args.verbose, grid_step=args.grid_step)
        n, mx, mn, minr, maxr, same = scale_metric(base, scaled, k)
        passed = summarize("escalado x%d: dosis(kF)/k vs dosis(F)" % int(k),
                           n, mx, mn, minr, maxr, same, TOL_SCALE)
        rmed = math.sqrt(minr * maxr) if minr * maxr > 0 else 0.0
        print("SCALE_x%d_RATIO = %.6g  (desv max %.4f%%, umbral 1%%)"
              % (int(k), rmed, mx * 100))
        ok = ok and passed
    return ok


def gate_superposition(cari, binary, date, args):
    """dosis(A+B) == dosis(A)+dosis(B) (tol 1 %). A y B son las dos mitades del
    dominio (baja y alta); juntas reconstruyen el espectro de ancho completo."""
    mid = math.sqrt(E_MIN_GEV * E_MAX_GEV)
    # A cubre [E_MIN, mid], B cubre (mid, E_MAX]: sin duplicar el borde `mid`.
    band_a = band_rows(E_MIN_GEV, mid)
    band_b = band_rows(mid, E_MAX_GEV, include_lo=False)
    a = run_rows(cari, binary, band_a, date, args.cutoffs, os_name=args.os,
                 wine=args.wine, verbose=args.verbose,
                 grid_step=args.grid_step)
    b = run_rows(cari, binary, band_b, date, args.cutoffs, os_name=args.os,
                 wine=args.wine, verbose=args.verbose,
                 grid_step=args.grid_step)
    ab = run_rows(cari, binary, band_a + band_b, date, args.cutoffs,
                  os_name=args.os, wine=args.wine, verbose=args.verbose,
                  grid_step=args.grid_step)
    n, mx, mn, minr, maxr, same = superposition_metric(a, b, ab)
    passed = summarize("superposicion: dosis(A+B) vs dosis(A)+dosis(B)",
                       n, mx, mn, minr, maxr, same, TOL_SUPERPOSITION)
    rmed = math.sqrt(minr * maxr) if minr * maxr > 0 else 0.0
    print("SUPERPOSITION_RATIO = %.6g  (desv max %.4f%%, umbral 1%%)"
          % (rmed, mx * 100))
    return passed


def gate_binning(cari, binary, date, args):
    """dosis(53 bins) == dosis(106 bins) sobre un espectro GLE real (tol 1 %).

    El espectro es la FORMA del GLE73 medida por GOES (pico del fixture de T2):
    si la cuadratura en energia no convergiera al duplicar el numero de bins, el
    kernel de 53 bins estaria mintiendo justo en el caso que importa."""
    fixture = args.gle_fixture
    if fixture and not os.path.exists(fixture):
        sys.exit("no existe el fixture GLE %s" % fixture)
    rows_53 = (gle_rows_from_fixture(fixture, 53) if fixture
               else power_law_rows(53))
    rows_106 = (gle_rows_from_fixture(fixture, 106) if fixture
                else power_law_rows(106))
    d53 = run_rows(cari, binary, rows_53, date, args.cutoffs,
                   os_name=args.os, wine=args.wine, verbose=args.verbose,
                   grid_step=args.grid_step)
    d106 = run_rows(cari, binary, rows_106, date, args.cutoffs,
                    os_name=args.os, wine=args.wine, verbose=args.verbose,
                    grid_step=args.grid_step)
    n, mx, mn, minr, maxr, same = compare_rate_maps(d106, d53)
    passed = summarize("convergencia de binning: 106 bins vs 53 bins"
                       " (espectro %s)"
                       % ("GLE73 fixture" if fixture else "ley de potencia"),
                       n, mx, mn, minr, maxr, same, TOL_BINNING)
    rmed = math.sqrt(minr * maxr) if minr * maxr > 0 else 0.0
    print("BINNING_RATIO = %.6g  (desv max %.4f%%, umbral 1%%)"
          % (rmed, mx * 100))
    return passed


def gate_reproduction(cari, binary, date, args):
    """Reproducir con MY_MODEL (= copia literal de BO'11) el espectro incorporado
    contra el camino nativo C2. La MISMA reproduccion que la puerta de T4: si el
    kernel no puede reconstruir un espectro incorporado, no hay kernel que valga.
    Tol 5 %."""
    gcr = os.path.join(cari, "GCR_MODELS")
    my_model = os.path.join(gcr, sep.MY_MODEL_NAME)
    backup = None
    if os.path.exists(my_model):
        backup = my_model + ".bak_t5"
        shutil.copy(my_model, backup)
    try:
        shutil.copy(os.path.join(gcr, sep.BO11_FILE), my_model)
        rcmap_gate = _rcmap_gate(args.cutoffs, date, args.grid_step)
        r7 = run_spectrum(cari, args.binary, sep.SP_MYMODEL, date,
                          os_name=args.os, wine=args.wine,
                          rcmap=rcmap_gate, cutoffs=args.cutoffs,
                          tag="repro", verbose=args.verbose)
        r2 = run_spectrum(cari, args.binary, sep.SP_BO11, date,
                          os_name=args.os, wine=args.wine,
                          rcmap=rcmap_gate, cutoffs=args.cutoffs,
                          tag="repro", verbose=args.verbose)
        n, mx, mn, minr, maxr, same = compare_rate_maps(r7, r2)
        passed = summarize("reproduccion: MY_MODEL=BO'11 vs C2 nativo @ %s"
                           % date, n, mx, mn, minr, maxr, same,
                           TOL_REPRODUCTION)
        rmed = math.sqrt(minr * maxr) if minr * maxr > 0 else 0.0
        print("REPRODUCTION_RATIO = %.6g  (desv max %.4f%%, umbral 5%%)"
              % (rmed, mx * 100))
        return passed
    finally:
        if backup:
            shutil.copy(backup, my_model)
            os.remove(backup)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cari-dir", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--cutoffs", required=True)
    ap.add_argument("--date", default="2000/01/00",
                    help="fecha comun de los LOC (con MY_MODEL no modula)")
    ap.add_argument("--grid-step", type=int, default=4,
                    help="muestrear el eje Rc cada N pasos (1 = rejilla completa)")
    ap.add_argument("--os", default="unix", choices=["unix", "win"])
    ap.add_argument("--wine", help="ruta a wine para ejecutar el .exe")
    ap.add_argument("--gle-fixture",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "fixtures", "goes",
                                         "g16_2021-10-28.json"),
                    help="fixture GOES del GLE73 (T2) para la forma espectral "
                         "de la puerta de binning; vacio para usar la ley de "
                         "potencia sintetica")
    ap.add_argument("--skip-reproduction", action="store_true",
                    help="saltar la puerta 4 (ya la corrio cari7_sep_gate.py "
                         "en el mismo job)")
    ap.add_argument("--verbose", action="store_true",
                    help="mostrar el stdout/stderr completo del binario CARI")
    args = ap.parse_args()

    cari = os.path.abspath(args.cari_dir)
    gcr = os.path.join(cari, "GCR_MODELS")
    for req in (os.path.join(gcr, sep.BO11_FILE),
                os.path.join(cari, "CARI.INI"),
                os.path.abspath(args.cutoffs)):
        if not os.path.exists(req):
            sys.exit("no existe %s (¿distribucion CARI-7A incompleta?)" % req)

    print("### T5: puertas de linealidad (grid_step=%d, date=%s) ###"
          % (args.grid_step, args.date))
    results = {}
    results["escalado"] = gate_scale(cari, args.binary, args.date, args)
    results["superposicion"] = gate_superposition(cari, args.binary, args.date,
                                                  args)
    results["convergencia de binning"] = gate_binning(cari, args.binary,
                                                      args.date, args)
    if not args.skip_reproduction:
        results["reproduccion"] = gate_reproduction(cari, args.binary,
                                                    args.date, args)
    else:
        print("  [SKIP] reproduccion (la corrio cari7_sep_gate.py)")

    print()
    for name, ok in results.items():
        print("  [%s] %s" % ("OK" if ok else "FAIL", name))
    if not all(results.values()):
        sys.exit("LINEARITY GATE FALLIDA: un kernel no lineal miente mas cuanto "
                 "mas duro es el evento -> fallback AniMAIRE completo")
    print("LINEARITY GATE OK: CARI-7A es lineal en escalado, superposicion y "
          "binning, y reproduce el espectro incorporado")


if __name__ == "__main__":
    main()
