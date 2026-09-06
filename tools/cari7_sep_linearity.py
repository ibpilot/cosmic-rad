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

HALLAZGOS de los runs de T5 en CI (los tres hacen falta para que CARI lea un
MY_MODEL.OUT no-verbatim y devuelva dosis no-cero):
  1. Estructura: MY_MODEL.OUT debe tener la estructura del BO11_GCR.OUT (100
     filas por Z=1..28 con la malla de energia del propio BO11). Una malla
     propia de 53 puntos en Z=1 se lee mal.
  2. Formato de columnas: cada linea debe tener 26 chars con las columnas del
     BO11 (Z cols 0-3, E cols 6-14, F cols 17-25). El formato "%4d %10.3E
     %12.3E" (28 chars) desplaza las columnas y CARI lee el espectro mal.
  3. Escala: un espectro de prueba que diverge en baja energia (ley de potencia
     pura proyectada a la malla del BO11, que baja a 0.01 GeV, da ~1e11) satura
     el transporte y CARI devuelve dosis 0. El espectro base es la forma REAL
     del GLE73 (fixture de T2) reescalada al regimen del BO11 (max ~400).
La fecha de la reproduccion C7-vs-C2 debe ser 2002/01/00 (snapshot solar del
BO11); en otras fechas el camino nativo modula y el ratio deriva.

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

# Espectro base de las puertas: la FORMA del GLE73 medida por GOES (fixture de
# T2), reescalada a la magnitud del espectro GCR que CARI maneja. Una ley de
# potencia pura (F = A*E^-gamma) DIVERGE en baja energia: proyectada a la malla
# del BO11 (que baja a 0.01 GeV) da valores ~1e11 que saturan el transporte y
# CARI devuelve dosis 0 (destapado en CI). La forma real de un GLE tiene pico y
# no diverge; su escala absoluta no importa para la linealidad, asi que se
# reescala al orden del BO11 (max ~400) para que el transporte este en el
# regimen que CARI ya maneja (validado por el selftest y la reproduccion).
GLE_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "fixtures", "goes", "g16_2021-10-28.json")
REF_FMAX = 400.0            # escala objetivo: ~max del BO11 en Z=1


def _fixture_shape(n_bins):
    """Forma del GLE73 (exceso sobre el baseline del dia previo) en n_bins,
    reescalada para que su maximo sea ~REF_FMAX (regimen del BO11)."""
    rows = gle_rows_from_fixture(GLE_FIXTURE, n_bins)
    fmax = max(f for _, f in rows if f > 0)
    return [(e, f * REF_FMAX / fmax) for e, f in rows]


def power_law_rows(n_bins):
    """Espectro base de ancho completo en n_bins log: la forma del GLE73
    reescalada (ver REF_FMAX). No es una ley de potencia pura: la forma real no
    diverge en baja energia y no satura a CARI."""
    return _fixture_shape(n_bins)


def band_rows(e_lo, e_hi, n_bins=200, include_lo=True, include_hi=True):
    """Fraccion espectral A o B de la superposicion: el espectro base confinado
    a [e_lo, e_hi]. Fuera de la banda el espectro es cero (no se escribe).
    `include_lo=False` / `include_hi=False` excluyen el borde (para que A y B
    contiguas no dupliquen el borde compartido)."""
    full = power_law_rows(n_bins)      # forma fina de referencia
    out = []
    for e, f in full:
        if not include_lo and e <= e_lo:
            continue
        if not include_hi and e >= e_hi:
            continue
        if e_lo <= e <= e_hi:
            out.append((e, f))
    return out


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
    # Muestrear la forma interpolada en n_bins log entre E_MIN y E_MAX.
    flux_at = _interp_from_rows(rows)
    if n_bins <= 1:
        return [(math.sqrt(E_MIN_GEV * E_MAX_GEV),
                 flux_at(math.sqrt(E_MIN_GEV * E_MAX_GEV)))]
    lmin, lmax = math.log(E_MIN_GEV), math.log(E_MAX_GEV)
    return [(math.exp(lmin + (lmax - lmin) * i / (n_bins - 1)),
             flux_at(math.exp(lmin + (lmax - lmin) * i / (n_bins - 1))))
            for i in range(n_bins)]


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


def _project_powerlaw(rows, grid):
    """Proyecta (E, F) sobre `grid` interpolando en log-log y extrapolando con
    la pendiente espectral local FUERA del rango (ley de potencia), no plano:
    una cola plana hasta 10 TeV (la malla del BO11 llega a 10000 GeV) daria una
    dosis absurda y romperia la convergencia."""
    import bisect
    pts = sorted((math.log(e), math.log(f)) for e, f in rows if e > 0 and f > 0)
    if not pts:
        raise SystemExit("espectro sin puntos positivos para proyectar")
    out = []
    for e in grid:
        x = math.log(e)
        if x <= pts[0][0]:
            x1, y1 = pts[0]
            x2, y2 = pts[min(1, len(pts) - 1)]
            m = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
            out.append((e, math.exp(y1 + m * (x - x1))))
        elif x >= pts[-1][0]:
            x1, y1 = pts[-2]
            x2, y2 = pts[-1]
            m = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
            out.append((e, math.exp(y2 + m * (x - x2))))
        else:
            i = bisect.bisect_right([p[0] for p in pts], x)
            x1, y1 = pts[i - 1]
            x2, y2 = pts[i]
            out.append((e, math.exp(y1 + (y2 - y1) * (x - x1) / (x2 - x1))))
    return out


def _write_my_model(cari, rows):
    """Escribe GCR_MODELS/MY_MODEL.OUT: el espectro GCR de fondo (BO11) MAS el
    espectro SEP `rows` SUMADO a la componente de protones (Z=1).

    MY_MODEL.OUT es el espectro primario TOTAL (el HELP.TXT: "is assumed to
    have GCR flux units"). Para modelar GCR + evento solar hay que SUMAR los
    flujos de protones: F_Z1(E) = F_GCR_Z1(E) + F_SEP(E). Reemplazar Z=1 por el
    SEP (como hacia antes) hace que la dosis neta (total - fondo) sea
    dosis(SEP) - dosis(GCR_Z1): el termino GCR fijo no escala y las puertas de
    linealidad fallan con ratios 1/k (medido en CI: x10 -> 0.1, x100 -> 0.01).

    Hallazgos previos que siguen vigentes:
      1. Estructura: 100 filas por Z=1..28 con la malla del BO11.
      2. Formato: lineas de 26 chars con las columnas del BO11.
      3. Iones: CARI exige Z>=2 (dosis 0/nan si van a cero); se conservan.
    """
    gcr = os.path.join(cari, "GCR_MODELS")
    dst = os.path.join(gcr, sep.MY_MODEL_NAME)
    grids = sep.load_ion_grids(cari)
    z1_grid = grids.get(1)
    if not z1_grid:
        raise SystemExit("no hay malla Z=1 en BO11_GCR.OUT (¿distro incompleta?)")
    # Espectro SEP proyectado sobre la malla fija de Z=1 del BO11.
    sep_proj = dict(_project_powerlaw(rows, z1_grid))
    with open(dst, "w") as f:
        f.write("2002.041096\n")           # epoca del BO11_GCR.OUT distribuido
        f.write("   Z       E            F\n")
        with open(os.path.join(gcr, sep.BO11_FILE)) as src:
            src_lines = src.read().splitlines()
        for l in src_lines[2:]:
            t = l.split()
            if len(t) < 3 or not t[0].isdigit():
                continue
            z = int(t[0])
            e = float(t[1])
            if z == 1:
                f.write("%4d  %9.3E  %9.3E\n" % (1, e,
                                                 float(t[2]) + sep_proj.get(e, 0.0)))
            else:
                f.write(l.rstrip("\n") + "\n")
    return dst


def _run_current_my_model(cari, binary, date, cutoffs, os_name="unix",
                          wine=None, verbose=False, rc_targets=None, tag=None):
    """Corre CARI (campo C7 = MY_MODEL.OUT, en su estado actual) sobre un
    subconjunto reducido de Rc x las 11 altitudes. Devuelve
    { (rc_gv, alt_km): rate_usvh }.

    A diferencia de `run_spectrum` (que barre ~150 objetivos del eje, ~1350
    puntos), las puertas de linealidad usan una rejilla PEQUENA fija
    (`rc_targets`, por defecto 9 valores de Rc repartidos): la linealidad se
    verifica por punto, no hace falta barrer todo el eje."""
    if rc_targets is None:
        rc_targets = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0]
    from cari7_sep_gate import (_binpath, _run_cari, find_ans,
                                _diagnose_missing_ans)
    from cari7_make_input import write_default_inp, patch_cari_ini
    from cari7_cutoffs import points_for_rc_targets
    from cari7_parse_ans import parse_ans

    epoch = epoch_file_for_year(int(date[:4]))
    rcmap = load_cutoff_map(os.path.join(cutoffs, epoch))
    picks = points_for_rc_targets(rcmap, rc_targets, tol=0.5)
    if not picks:
        raise SystemExit("ningun punto del mapa de %s casa con las Rc %s"
                         % (epoch, rc_targets))
    points = [(la, lo, alt) for (la, lo, _rc) in picks
              for alt in sep.ALT_VALUES]

    binpath = _binpath(cari, binary, os_name, wine)
    env = None
    prefix = []
    if wine:
        prefix = [wine]
        env = dict(os.environ, WINEDEBUG="-all",
                   WINEPREFIX=os.path.expanduser("~/.wine-cari7a"))
    patch_cari_ini(os.path.join(cari, "CARI.INI"), cari, os_name)

    name = "sep_lin.loc" if not tag else "sep_%s.loc" % tag
    loc = os.path.join(cari, name)
    with open(loc, "w") as f:
        f.write("C, puertas de linealidad T5: C7 (MY_MODEL), fecha %s, D2\n"
                % date)
        f.write("START-------------------------------------------------\n")
        for la, lo, alt in points:
            f.write(sep.sep_loc_line(la, lo, alt, date, sep.SP_MYMODEL) + "\n")
        f.write("STOP--------------------------------------------------------\n")
    write_default_inp(0, cari, loc_name=os.path.basename(loc))
    _run_cari(prefix + [binpath], cari, env, verbose)
    stem = os.path.splitext(loc)[0]
    ans = find_ans(cari, stem)
    if ans is None:
        _diagnose_missing_ans(cari, loc, stem + ".ans")
        sys.exit("no se genero el .ANS del LOC %s (¿CARI fallo?)"
                 % os.path.basename(loc))
    rates = {}
    for rc, alt, _hp, rate in parse_ans(ans, 0):
        rates[(rc, alt)] = rate
    if verbose and rates:
        print("[diagnostico] %s: %d puntos; primeras tasas:"
              % (os.path.basename(ans), len(rates)))
        for k in sorted(rates)[:5]:
            print("    Rc=%.2f alt=%.1f -> %s" % (k[0], k[1], rates[k]))
    return rates


def run_rows(cari, binary, rows, date, cutoffs, os_name="unix", wine=None,
             verbose=False, rc_targets=None, tag=None):
    """Escribe MY_MODEL.OUT con `rows` y corre CARI (campo C7) sobre la rejilla
    reducida. Devuelve { (rc_gv, alt_km): rate_usvh }."""
    _write_my_model(cari, rows)
    return _run_current_my_model(cari, binary, date, cutoffs, os_name=os_name,
                                 wine=wine, verbose=verbose,
                                 rc_targets=rc_targets, tag=tag)


def control_bo11(cari, binary, date, args):
    """Sonda de diagnostico: corre por el MISMO camino que las puertas 1-3
    (run_rows / _run_current_my_model) un MY_MODEL.OUT = copia literal del
    BO11_GCR.OUT. La reproduccion (puerta 4) demuestra que ese espectro da
    dosis normales por `run_spectrum`; si este control diera 0, el bug estaria
    en el LOC/parseo de las puertas 1-3, no en el espectro arbitrario."""
    gcr = os.path.join(cari, "GCR_MODELS")
    my_model = os.path.join(gcr, sep.MY_MODEL_NAME)
    backup = None
    if os.path.exists(my_model):
        backup = my_model + ".bak_ctrl"
        shutil.copy(my_model, backup)
    try:
        shutil.copy(os.path.join(gcr, sep.BO11_FILE), my_model)
        rates = _run_current_my_model(cari, binary, date, args.cutoffs,
                                      os_name=args.os, wine=args.wine,
                                      verbose=args.verbose)
        nz = sum(1 for v in rates.values() if v and v == v)
        print("[control] MY_MODEL=BO11 literal por el camino de puertas 1-3: "
              "%d puntos, %d no-cero" % (len(rates), nz))
        if rates:
            k = sorted(rates)[0]
            print("[control] primera tasa: Rc=%.2f alt=%.1f -> %s"
                  % (k[0], k[1], rates[k]))
        return nz > 0
    finally:
        if backup:
            shutil.copy(backup, my_model)
            os.remove(backup)


def _write_bo11_iones_cero(cari, dst):
    """Escribe en `dst` el BO11_GCR.OUT literal pero con los bloques Z>=2 a
    cero (solo protones). Conserva formato, mallas y cabecera."""
    src = os.path.join(cari, "GCR_MODELS", sep.BO11_FILE)
    with open(src) as fh:
        lines = fh.read().splitlines()
    out = []
    for i, l in enumerate(lines):
        if i < 2:
            out.append(l)
            continue
        t = l.split()
        if len(t) >= 3 and t[0].isdigit():
            z = int(t[0])
            if z == 1:
                out.append(l)
            else:
                out.append("%4d  %9.3E  %9.3E" % (z, float(t[1]), 0.0))
        else:
            out.append(l)
    with open(dst, "w") as f:
        f.write("\n".join(out) + "\n")
    return dst


def control_solo_protones(cari, binary, date, args):
    """Sonda: MY_MODEL = BO11 literal con Z>=2 a cero (solo protones). Aisla si
    CARI necesita los iones Z>=2 para dar dosis D2 no-cero (hipotesis de por que
    los espectros arbitrarios, que solo tienen Z=1, dan tasas 0)."""
    gcr = os.path.join(cari, "GCR_MODELS")
    my_model = os.path.join(gcr, sep.MY_MODEL_NAME)
    backup = None
    if os.path.exists(my_model):
        backup = my_model + ".bak_ctrl2"
        shutil.copy(my_model, backup)
    try:
        _write_bo11_iones_cero(cari, my_model)
        rates = _run_current_my_model(cari, binary, date, args.cutoffs,
                                      os_name=args.os, wine=args.wine,
                                      verbose=args.verbose)
        nz = sum(1 for v in rates.values() if v and v == v)
        print("[control] MY_MODEL=BO11 con Z>=2 a cero (solo protones): "
              "%d puntos, %d no-cero" % (len(rates), nz))
        if rates:
            k = sorted(rates)[0]
            print("[control] primera tasa: Rc=%.2f alt=%.1f -> %s"
                  % (k[0], k[1], rates[k]))
        return nz > 0
    finally:
        if backup:
            shutil.copy(backup, my_model)
            os.remove(backup)


def run_sep_net(cari, binary, date, args, rows, tag=None, _gcr_cache=None):
    """Dosis SEP NETA de un espectro de protones: corre MY_MODEL (= GCR del BO11
    + SEP en Z=1) y le resta la dosis del fondo GCR puro (BO11 sin modificar).

    MY_MODEL.OUT es el espectro GCR COMPLETO (el HELP.TXT: "assumed to have GCR
    flux units"); CARI exige las especies Z>=2 y devuelve dosis 0/nan si se
    ponen a cero (sonda verificada en CI). Por eso el espectro SEP se SUMA al
    GCR de fondo en Z=1, y la dosis SEP neta es la diferencia contra el fondo.
    Sin restar, las puertas de linealidad medirian el fondo (que no escala) y
    fallarian aunque el transporte SEP sea lineal."""
    if _gcr_cache is None:
        _gcr_cache = {}
    if "gcr" not in _gcr_cache:
        gcr_file = os.path.join(cari, "GCR_MODELS", sep.MY_MODEL_NAME)
        backup = None
        if os.path.exists(gcr_file):
            backup = gcr_file + ".bak_gcr"
            shutil.copy(gcr_file, backup)
        try:
            shutil.copy(os.path.join(cari, "GCR_MODELS", sep.BO11_FILE),
                        gcr_file)
            _gcr_cache["gcr"] = _run_current_my_model(
                cari, binary, date, args.cutoffs, os_name=args.os,
                wine=args.wine, verbose=args.verbose, tag="gcr")
        finally:
            if backup:
                shutil.copy(backup, gcr_file)
                os.remove(backup)
    total = run_rows(cari, binary, rows, date, args.cutoffs, os_name=args.os,
                     wine=args.wine, verbose=args.verbose, tag=tag)
    gcr = _gcr_cache["gcr"]
    net = {}
    for k in total:
        if k not in gcr:
            continue
        t, g = total[k], gcr[k]
        if t != t or g != g:
            continue          # NaN: punto no medible
        n = t - g
        # El neto debe ser positivo y no despreciable frente al total: donde el
        # SEP aporta <1 % de la dosis, la resta pierde por cancelacion y el
        # punto no informa sobre la linealidad del SEP (lo descartamos, no es
        # "no lineal").
        if n > 0 and n > 0.01 * t:
            net[k] = n
    return net


def gate_scale(cari, binary, date, args, gcr_cache=None):
    """dosis(k*F) == k*dosis(F) para k=10 y k=100 (tol 1 %), sobre la dosis SEP
    NETA (espectro con fondo GCR restado)."""
    if gcr_cache is None:
        gcr_cache = {}
    rows = power_law_rows(53)
    base = run_sep_net(cari, binary, date, args, rows, tag="s1",
                       _gcr_cache=gcr_cache)
    ok = True
    for k in (10.0, 100.0):
        scaled = run_sep_net(cari, binary, date, args,
                             [(e, k * f) for (e, f) in rows], tag="s%d" % int(k),
                             _gcr_cache=gcr_cache)
        n, mx, mn, minr, maxr, same = scale_metric(base, scaled, k)
        passed = summarize("escalado x%d: dosis(kF)/k vs dosis(F)" % int(k),
                           n, mx, mn, minr, maxr, same, TOL_SCALE)
        rmed = math.sqrt(minr * maxr) if minr * maxr > 0 else 0.0
        print("SCALE_x%d_RATIO = %.6g  (desv max %.4f%%, umbral 1%%)"
              % (int(k), rmed, mx * 100))
        ok = ok and passed
    return ok


def gate_superposition(cari, binary, date, args, gcr_cache=None):
    """dosis(A+B) == dosis(A)+dosis(B) (tol 1 %), sobre la dosis SEP NETA. A y B
    son las dos mitades del dominio (baja y alta); juntas reconstruyen el
    espectro de ancho completo."""
    if gcr_cache is None:
        gcr_cache = {}
    mid = math.sqrt(E_MIN_GEV * E_MAX_GEV)
    # A cubre [E_MIN, mid], B cubre (mid, E_MAX]: sin duplicar el borde `mid`.
    band_a = band_rows(E_MIN_GEV, mid)
    band_b = band_rows(mid, E_MAX_GEV, include_lo=False)
    a = run_sep_net(cari, binary, date, args, band_a, tag="sa",
                    _gcr_cache=gcr_cache)
    b = run_sep_net(cari, binary, date, args, band_b, tag="sb",
                    _gcr_cache=gcr_cache)
    ab = run_sep_net(cari, binary, date, args, band_a + band_b, tag="sab",
                     _gcr_cache=gcr_cache)
    n, mx, mn, minr, maxr, same = superposition_metric(a, b, ab)
    passed = summarize("superposicion: dosis(A+B) vs dosis(A)+dosis(B)",
                       n, mx, mn, minr, maxr, same, TOL_SUPERPOSITION)
    rmed = math.sqrt(minr * maxr) if minr * maxr > 0 else 0.0
    print("SUPERPOSITION_RATIO = %.6g  (desv max %.4f%%, umbral 1%%)"
          % (rmed, mx * 100))
    return passed


def gate_binning(cari, binary, date, args, gcr_cache=None):
    """dosis(53 bins) == dosis(106 bins) sobre un espectro GLE real (tol 1 %).

    El espectro es la FORMA del GLE73 medida por GOES (la misma que usan las
    otras puertas, reescalada al regimen del BO11): si representar el espectro
    con 53 muestras no bastara (frente a 106), el kernel de 53 bins estaria
    mintiendo justo en el caso que importa."""
    if gcr_cache is None:
        gcr_cache = {}
    d53 = run_sep_net(cari, binary, date, args, power_law_rows(53), tag="b53",
                      _gcr_cache=gcr_cache)
    d106 = run_sep_net(cari, binary, date, args, power_law_rows(106), tag="b106",
                       _gcr_cache=gcr_cache)
    n, mx, mn, minr, maxr, same = compare_rate_maps(d106, d53)
    passed = summarize("convergencia de binning: 106 bins vs 53 bins"
                       " (espectro GLE73)",
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
    ap.add_argument("--date", default="2002/01/00",
                    help="fecha comun de los LOC. La reproduccion C7-vs-C2 solo "
                         "da ratio 1 en 2002/01/00 (condicion solar del snapshot "
                         "del BO11_GCR.OUT distribuido; hallazgo de T4); con "
                         "MY_MODEL la fecha no modula, pero la comparacion "
                         "contra el camino nativo exige esa fecha.")
    ap.add_argument("--grid-step", type=int, default=4,
                    help="muestrear el eje Rc cada N pasos en la puerta de "
                         "reproduccion (1 = rejilla completa); las puertas 1-3 "
                         "usan una rejilla fija pequena")
    ap.add_argument("--os", default="unix", choices=["unix", "win"])
    ap.add_argument("--wine", help="ruta a wine para ejecutar el .exe")
    ap.add_argument("--skip-reproduction", action="store_true",
                    help="saltar la puerta 4 (ya la corrio cari7_sep_gate.py "
                         "en el mismo job)")
    ap.add_argument("--skip-control", action="store_true",
                    help="saltar la sonda de diagnostico (MY_MODEL=BO11 por el "
                         "camino de las puertas 1-3)")
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

    print("### T5: puertas de linealidad (date=%s, repro grid_step=%d) ###"
          % (args.date, args.grid_step))
    # Sondas de diagnostico (resueltas; se dejan detras de --skip-control para
    # no pagar su coste en el run normal del workflow).
    if not args.skip_control:
        try:
            control_bo11(cari, args.binary, args.date, args)
        except SystemExit as e:
            print("[control] fallo: %s" % e)
        try:
            control_solo_protones(cari, args.binary, args.date, args)
        except SystemExit as e:
            print("[control solo-protones] fallo: %s" % e)
    gcr_cache = {}       # fondo GCR compartido por las puertas 1-3
    results = {}
    results["escalado"] = gate_scale(cari, args.binary, args.date, args,
                                     gcr_cache)
    results["superposicion"] = gate_superposition(cari, args.binary, args.date,
                                                  args, gcr_cache)
    results["convergencia de binning"] = gate_binning(cari, args.binary,
                                                      args.date, args,
                                                      gcr_cache)
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
