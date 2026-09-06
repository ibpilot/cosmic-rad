#!/usr/bin/env python3
"""Barrido y ensamblado del kernel SEP_RESPONSE_GRID (T6 del plan).

CARI-7A no exporta una respuesta monoenergetica documentada; el kernel se
construye con espectros base estrechos (un bin log por columna) y se acepta
porque T5 demostro que el transporte es LINEAL (escalado x10/x100,
superposicion A+B, binning 53 vs 106, reproduccion BO'11). Este script:

  1. `column --bin j`: escribe MY_MODEL.OUT con el espectro base del bin j
     (1 pfu * amp integrado en el bin, cero fuera) SUMADO al GCR de protones
     en Z=1 y conservando los iones Z>=2 del BO11 (CARI exige Z>=2 para dar
     dosis D2 no-cero, hallazgo T5), y corre CARI sobre la rejilla completa
     Rc 0:18:0.25 x alt 8.0:13.0:0.5.
  2. `bg`: el MISMO barrido con Z=1 = GCR del BO11 sin SEP: la dosis de fondo
     que se resta a cada columna. La columna mide (total - fondo) / amp: el
     fondo incluye los iones Z>=2 y el GCR de protones que MY_MODEL siempre
     lleva, asi que la resta aisla la dosis del espectro SEP puro. Con el SEP
     a escala amp >> GCR no hay cancelacion numerica al restar.
  3. `assemble`: junta los CSV de las 53 columnas + el fondo, resta, divide
     por amp y remuestrea a la rejilla exacta 53 E x 73 Rc x 11 alt -> el
     bloque JS `var SEP_RESPONSE_GRID = {...}` (Float32LE base64, Q92).

El bloque incluye `model_version` ("sep-1"), los ejes literales y la unidad de
T4 (Q88/Q93). El interprete (index.html, T8/T9) valida dimensiones y version al
arrancar; un desajuste deja el SEP desactivado, nunca fallback a DOSE_GRID.

La verificacion de T6 corre en el job `assemble`: dimensiones 53x73x11x1, sin
NaN/negativos y monotonia esperada (mas altitud -> mas dosis, mas Rc -> menos
dosis), via `tools/tests/check_sep_grid.py`. La puerta de reproduccion (tabla
vs CARI directo sobre un espectro real, criterio 2 de T14) corre en el
backtesting, donde compara el kernel contra la corrida directa de CARI.

Uso (CI, distro CARI-7A de setup-cari7a):
    # un job por columna del kernel (53 en paralelo) + un job de fondo:
    python3 tools/generate_sep_grid.py column --bin 12 --amp 1e5 \
        --cari-dir CARI_7A_DVD --binary "cari7a_4.2.0(intel_linux)" \
        --cutoffs CARI_7A_DVD/CUTOFFS --out rates_k12.csv
    python3 tools/generate_sep_grid.py bg \
        --cari-dir CARI_7A_DVD --binary "cari7a_4.2.0(intel_linux)" \
        --cutoffs CARI_7A_DVD/CUTOFFS --out rates_bg.csv
    # ensamblado (sin CARI):
    python3 tools/generate_sep_grid.py assemble --rates "rates_k*.csv" \
        --bg rates_bg.csv --amp 1e5 --out sep_grid.js
"""
import argparse, base64, math, os, struct, sys

# La logica pura (bins, proyeccion a la malla BO11, remuestreo) vive en
# sep_grid_common y aqui mismo como funciones sin dependencia del binario,
# para poder testearla en CI sin CARI (test_cari7_sep_grid.py).
import sep_grid_common as common


# --------------------------------------------------------------------------
# Logica pura: proyeccion de un bin a la malla del BO11 (Z=1)
# --------------------------------------------------------------------------

def read_bo11_z1_grid(bo11_path):
    """Malla de energia (GeV) de Z=1 del BO11_GCR.OUT distribuido: es la malla
    FIJA sobre la que CARI lee MY_MODEL.OUT (100 filas por Z)."""
    grid = []
    with open(bo11_path, errors="replace") as f:
        for line in f:
            t = line.split()
            if len(t) >= 3 and t[0] == "1":
                grid.append(float(t[1]))
    if len(grid) < 50:
        raise SystemExit("BO11 Z=1 con %d filas (esperaba ~100): %s"
                         % (len(grid), bo11_path))
    return grid


def _voronoi_log(grid):
    """Celda de Voronoi de cada nodo en log-E: devuelve (x, w_izq, w_der)
    donde el nodo 'representa' el intervalo [x - w_izq, x + w_der] en log E.
    La particion cubre [x0 - (x1-x0)/2, xN + (xN-xN-1)/2]."""
    xs = [math.log(e) for e in grid]
    out = []
    for i, x in enumerate(xs):
        lo = x - (x - xs[i - 1]) / 2.0 if i > 0 else x - (xs[1] - xs[0]) / 2.0
        hi = x + (xs[i + 1] - x) / 2.0 if i < len(xs) - 1 else x + (x - xs[-2]) / 2.0
        out.append((x, lo, hi))
    return out


def basis_weights(grid, n_bins=common.N_E_BINS,
                  e_min=common.E_MIN_GEV, e_max=common.E_MAX_GEV):
    """Matriz P[j][n]: fraccion del pfu del bin j que la cuadratura asigna al
    nodo n de la malla BO11 (particion de Voronoi en log-E sobre el bin).

    La malla del BO11 tiene ~43 nodos en [50 MeV, 20 GeV] frente a 53 bins
    (10 bins no contienen ningun nodo), asi que un bin NO se representa solo
    con los nodos que caen dentro: cada punto del continuo del bin pertenece a
    la celda de Voronoi de UN nodo, y P[j][n] = longitud log de (bin j ∩ celda
    n) / longitud log del bin j. Suma 1 por bin; la reconstruccion es una
    cuadratura consistente sobre la malla que CARI realmente lee.
    """
    edges = common.bin_edges(n_bins, e_min, e_max)
    cells = _voronoi_log(grid)
    P = []
    for j in range(n_bins):
        a, b = math.log(edges[j]), math.log(edges[j + 1])
        width = b - a
        row = []
        for (_x, lo, hi) in cells:
            ov = min(b, hi) - max(a, lo)
            row.append(max(0.0, ov) / width)
        P.append(row)
    return P


def z1_flux_for_bin(grid, P, j, amp=1.0):
    """Flujo diferencial por nodo de la base del bin j: el pfu del bin
    (integral = amp) repartido por Voronoi y convertido a F(E) tal que
    F(E_n) * E_n ~ densidad por log. CARI lee F en nuclei/(m2-sr-s-GeV) y
    una base localizada se resuelve si el flujo de sus nodos no es extremo.
    """
    out = []
    for n, e in enumerate(grid):
        w = P[j][n]
        out.append((e, amp * w / e if w > 0 else 0.0))
    return out


# --------------------------------------------------------------------------
# Escritura de MY_MODEL.OUT (Z=1 = espectro arbitrario, Z>=2 = BO11 literal)
# --------------------------------------------------------------------------

def write_my_model_z1(bo11_path, dst_path, z1_values):
    """MY_MODEL.OUT con la estructura del BO11: epoca + cabecera + 100 filas
    por Z=1..28. Z=1 lleva `z1_values` (un float por nodo de la malla, en el
    orden de `read_bo11_z1_grid`) SUMADOS al flujo GCR del BO11 en Z=1; Z>=2 se
    copian LITERALES del BO11 (CARI exige los iones para dar dosis D2 no-cero;
    hallazgo T5).

    MY_MODEL.OUT es el espectro GCR COMPLETO ("assumed to have GCR flux
    units", HELP.TXT 3.D): un espectro SEP NO reemplaza Z=1, se SUMA al GCR de
    fondo. Reemplazar (como hacia el codigo antes del fix de T5) hace que la
    dosis neta (total - fondo) pierda el termino GCR fijo y no escale; la
    resta fondo-GCR se hace en el ensamblado (el fondo corre con Z=1 = GCR del
    BO11, sin SEP).

    Formato por fila: 26 chars con columnas fijas (Z cols 0-3, E cols 6-14,
    F cols 17-25), el que CARI lee de verdad (bug de 28 chars de T4/T5).
    """
    lines = []
    with open(bo11_path, errors="replace") as f:
        src = f.read().splitlines()
    if len(src) < 2:
        raise SystemExit("BO11_GCR.OUT ilegible (sin cabecera): %s" % bo11_path)
    lines.append(src[0])               # epoca
    lines.append(src[1])               # cabecera de columnas
    z1_idx = 0
    for l in src[2:]:
        t = l.split()
        if len(t) < 3 or not t[0].isdigit():
            continue
        z = int(t[0])
        if z == 1:
            e = float(t[1])
            # F_Z1 = F_GCR_BO11 + F_SEP (el SEP se SUMA, no reemplaza).
            f = float(t[2]) + z1_values[z1_idx]
            lines.append("%4d  %9.3E  %9.3E" % (1, e, f))
            z1_idx += 1
        else:
            lines.append(l.rstrip("\n"))
    if z1_idx != len(z1_values):
        raise SystemExit("malla Z=1 del BO11 (%d) no coincide con z1_values (%d)"
                         % (z1_idx, len(z1_values)))
    with open(dst_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return dst_path


# --------------------------------------------------------------------------
# Barrido (requiere el binario CARI-7A)
# --------------------------------------------------------------------------

def _run_grid(cari, binary, cutoffs, date, tag, verbose=False, probe=False):
    """Corre CARI (campo 7 = MY_MODEL.OUT, en su estado actual) sobre la
    rejilla Rc x alt y devuelve { (rc_gv, alt_km): rate_usvh }.

    Con `probe=True` se reduce la rejilla a ~10 Rc objetivo x 11 alt (la misma
    seleccion que las puertas de T5) para iterar rapido en CI; el ensamblado
    final usa SIEMPRE la rejilla completa."""
    import cari7_sep_input as sep
    from cari7_cutoffs import load_cutoff_map, epoch_file_for_year
    from cari7_sep_gate import run_spectrum

    epoch = epoch_file_for_year(int(date[:4]))
    rcmap = load_cutoff_map(os.path.join(cutoffs, epoch))
    if probe:
        from cari7_sep_linearity import _rcmap_gate
        rcmap = _rcmap_gate(cutoffs, date, 8)   # cada 8 pasos: ~10 Rc x 11 alt
    return run_spectrum(cari, binary, sep.SP_MYMODEL, date,
                        os_name="unix", wine=None, chunk=150, tag=tag,
                        rcmap=rcmap, cutoffs=cutoffs, verbose=verbose)


def _write_csv(path, rates):
    with open(path, "w") as f:
        f.write("rc_gv,alt_km,rate_usvh\n")
        for (rc, alt) in sorted(rates):
            f.write("%.6f,%.4f,%.9g\n" % (rc, alt, rates[(rc, alt)]))


# --------------------------------------------------------------------------
# Ensamblado (sin CARI): CSVs -> bloque JS
# --------------------------------------------------------------------------

def resample_rc_alt(rows, rc_axis, alt_axis, strict=False):
    """(rc_real, alt, rate) irregulares -> floats en orden **rc-major -> alt**
    (el mismo orden del DOSE_GRID GCR), interpolando linealmente por rebanada
    de altitud (los puntos del mapa no caen en los nodos del eje).

    Con `strict=True` (modo produccion) una rebanada de altitud sin muestras
    aborta: un hueco en la rejilla completa no puede quedarse en silencio como
    ceros (enmascararia un fallo del barrido). Con `strict=False` (probe)
    devuelve None para que el llamador pueda contar el hueco."""
    slices = {}
    for rc, alt, rate in rows:
        slices.setdefault(round(alt, 6), []).append((rc, rate))
    # Interpolar cada rebanada de altitud a los nodos Rc del eje.
    per_alt = []
    for alt in alt_axis:
        pts = sorted(slices.get(round(alt, 6), []))
        if len(pts) < 2:
            if strict:
                raise SystemExit("rebanada alt=%.1f sin suficientes muestras "
                                 "(%d) en la rejilla completa: el barrido "
                                 "fallo" % (alt, len(pts)))
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        interp = []
        for rc in rc_axis:
            if rc <= xs[0]:
                interp.append(ys[0])
            elif rc >= xs[-1]:
                interp.append(ys[-1])
            else:
                k = 0
                while k + 1 < len(xs) and xs[k + 1] < rc:
                    k += 1
                dx = xs[k + 1] - xs[k]
                interp.append(ys[k] if dx == 0
                              else ys[k] + (ys[k + 1] - ys[k]) * (rc - xs[k]) / dx)
        per_alt.append(interp)
    # Reordenar de (alt, rc) a rc-major -> alt.
    n_rc, n_alt = len(rc_axis), len(alt_axis)
    out = [0.0] * (n_rc * n_alt)
    for ai in range(n_alt):
        for ri in range(n_rc):
            out[ri * n_alt + ai] = per_alt[ai][ri]
    return out


def read_rates_csv(path):
    rows = []
    with open(path) as f:
        for line in f:
            t = line.split(",")
            if len(t) < 3 or t[0].strip().lower() == "rc_gv":
                continue
            try:
                rows.append((float(t[0]), float(t[1]), float(t[2])))
            except ValueError:
                continue
    return rows


def assemble_kernel(column_csvs, bg_rows, amp,
                    rc_axis=common.RC_TARGETS, alt_axis=common.ALT_VALUES,
                    n_bins=common.N_E_BINS, strict=True):
    """Construye el array Float32 del kernel: 53 x 73 x 11 en orden
    E-major -> Rc -> alt, en uSv/h por pfu.

    Cada columna j: (total_bin_j - fondo_iones) / amp, remuestreado a la
    rejilla exacta. Devuelve (floats, n_nulos) donde n_nulos cuenta los puntos
    donde ninguna columna midio (el kernel queda a 0: geomagneticamente
    excluido o no medido)."""
    if len(column_csvs) != n_bins:
        raise SystemExit("se esperaban %d columnas, hay %d"
                         % (n_bins, len(column_csvs)))
    bg = {}
    for rc, alt, rate in bg_rows:
        bg[(round(rc, 6), round(alt, 6))] = rate
    n_rc, n_alt = len(rc_axis), len(alt_axis)
    kernel = [0.0] * (n_bins * n_rc * n_alt)
    nulos = 0
    for j in range(n_bins):
        rows = []
        for rc, alt, rate in column_csvs[j]:
            b = bg.get((round(rc, 6), round(alt, 6)))
            if b is None:
                continue
            net = rate - b
            if net != net or net <= 0:
                net = 0.0
            rows.append((rc, alt, net / amp))
        floats = resample_rc_alt(rows, rc_axis, alt_axis, strict=strict)
        if floats is None:
            nulos += n_rc * n_alt
            continue
        base = j * n_rc * n_alt
        for i, v in enumerate(floats):
            kernel[base + i] = v
            if v <= 0:
                nulos += 1
    return kernel, nulos


def build_block(kernel, nulos, amp, rc_axis=common.RC_TARGETS,
                alt_axis=common.ALT_VALUES, e_centers=None):
    """Array Float32 + metadatos -> texto del bloque JS (var SEP_RESPONSE_GRID)."""
    if e_centers is None:
        e_centers = common.bin_centers()
    packed = struct.pack("<%df" % len(kernel), *kernel)
    b64 = base64.b64encode(packed).decode("ascii")
    n_rc, n_alt = len(rc_axis), len(alt_axis)
    lines = [
        "// Generado por tools/generate_sep_grid.py - NO editar a mano.",
        "// Kernel de respuesta SEP: uSv/h por pfu integrado en cada bin de energia.",
        "// %d bins E x %d Rc x %d alt, %s; %d puntos a cero (excluidos/no medidos)." % (
            len(e_centers), n_rc, n_alt,
            "%.1f KB Float32LE" % (len(kernel) * 4 / 1024), nulos),
        "var SEP_RESPONSE_GRID = {",
        "  model_version: \"%s\"," % common.MODEL_VERSION,
        "  e: %s," % ("[" + ",".join("%.6g" % x for x in e_centers) + "]"),
        "  rc: %s," % ("[" + ",".join("%g" % x for x in rc_axis) + "]"),
        "  alt: %s," % ("[" + ",".join("%g" % x for x in alt_axis) + "]"),
        "  q: [\"D2\"],",
        "  unit: \"%s\"," % common.RATE_UNIT,
        "  flux_unit: \"%s\"," % common.FLUX_UNIT,
        "  data: \"%s\"" % b64,
        "};",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    p_col = sub.add_parser("column", help="correr la columna del kernel de un bin")
    p_col.add_argument("--bin", type=int, required=True)
    p_col.add_argument("--amp", type=float, default=1e5,
                       help="pfu integrados del espectro base (escala de medida)")
    p_col.add_argument("--cari-dir", required=True)
    p_col.add_argument("--binary", required=True)
    p_col.add_argument("--cutoffs", required=True)
    p_col.add_argument("--date", default="2000/01/00")
    p_col.add_argument("--out", required=True)
    p_col.add_argument("--verbose", action="store_true")
    p_col.add_argument("--probe", action="store_true",
                       help="rejilla reducida (diagnostico rapido en CI)")

    p_bg = sub.add_parser("bg", help="fondo GCR: Z=1 del BO11 sin SEP")
    p_bg.add_argument("--cari-dir", required=True)
    p_bg.add_argument("--binary", required=True)
    p_bg.add_argument("--cutoffs", required=True)
    p_bg.add_argument("--date", default="2000/01/00")
    p_bg.add_argument("--out", required=True)
    p_bg.add_argument("--verbose", action="store_true")

    p_as = sub.add_parser("assemble", help="ensamblar el bloque JS (sin CARI)")
    p_as.add_argument("--rates", required=True,
                      help="patron glob de los CSV de columnas")
    p_as.add_argument("--bg", required=True, help="CSV del fondo GCR")
    p_as.add_argument("--amp", type=float, default=1e5)
    p_as.add_argument("--out", required=True)

    args = ap.parse_args()

    if args.mode == "column" or args.mode == "bg":
        bo11 = os.path.join(os.path.abspath(args.cari_dir),
                            "GCR_MODELS", "BO11_GCR.OUT")
        my_model = os.path.join(os.path.abspath(args.cari_dir),
                                "GCR_MODELS", "MY_MODEL.OUT")
        grid = read_bo11_z1_grid(bo11)
        P = basis_weights(grid)
        if args.mode == "column":
            if not (0 <= args.bin < common.N_E_BINS):
                sys.exit("--bin fuera de rango 0..%d" % (common.N_E_BINS - 1))
            z1 = [v for (_e, v) in z1_flux_for_bin(grid, P, args.bin, args.amp)]
            print("[column] bin %d/%d: base de %.3g pfu integrados repartida "
                  "en %d nodos, SUMADA al GCR de Z=1"
                  % (args.bin, common.N_E_BINS, args.amp,
                     sum(1 for v in z1 if v > 0)))
        else:
            # Fondo: sin SEP en Z=1 (solo el GCR del BO11). write_my_model_z1
            # SUMA z1_values al GCR, asi que un vector de ceros deja Z=1 = GCR
            # puro, la dosis de fondo que se resta a cada columna.
            z1 = [0.0] * len(grid)
            print("[bg] fondo: Z=1 = GCR del BO11 sin SEP en %d nodos" % len(grid))
        write_my_model_z1(bo11, my_model, z1)
        rates = _run_grid(os.path.abspath(args.cari_dir), args.binary,
                          os.path.abspath(args.cutoffs), args.date,
                          tag=("k%d" % args.bin) if args.mode == "column" else "bg",
                          verbose=args.verbose,
                          probe=getattr(args, "probe", False))
        _write_csv(args.out, rates)
        nz = sum(1 for v in rates.values() if v and v == v)
        print("[%s] %d puntos, %d no-cero -> %s" % (args.mode, len(rates), nz,
                                                     args.out))
        if nz == 0:
            sys.exit("ningun punto no-cero: CARI no dio dosis (¿espectro base "
                     "no resoluble o MY_MODEL.OUT mal formado?)")

    elif args.mode == "assemble":
        import glob, re as _re
        paths = sorted(glob.glob(args.rates))
        if len(paths) != common.N_E_BINS:
            sys.exit("se esperaban %d CSV de columna (%s), hay %d"
                     % (common.N_E_BINS, args.rates, len(paths)))
        # Ordenar por el numero de bin del nombre (rates_k10.csv < rates_k2.csv
        # lexicograficamente, pero el bin 10 va despues del 2).
        def bin_of(p):
            m = _re.search(r"k(\d+)\.csv$", p)
            return int(m.group(1)) if m else -1
        paths.sort(key=bin_of)
        if [bin_of(p) for p in paths] != list(range(common.N_E_BINS)):
            sys.exit("los CSV de columna no cubren los bins 0..%d (%s)"
                     % (common.N_E_BINS - 1, paths))
        col_csvs = [read_rates_csv(p) for p in paths]
        bg = read_rates_csv(args.bg)
        kernel, nulos = assemble_kernel(col_csvs, bg, args.amp)
        block = build_block(kernel, nulos, args.amp)
        with open(args.out, "w") as f:
            f.write(block)
        print("Escrito %s (%d bins x %d Rc x %d alt, %.1f KB, %d puntos a cero)"
              % (args.out, common.N_E_BINS, len(common.RC_TARGETS),
                 len(common.ALT_VALUES), len(kernel) * 4 / 1024, nulos))


if __name__ == "__main__":
    main()
