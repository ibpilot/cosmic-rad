#!/usr/bin/env python3
"""Ensambla la rejilla de dosis DOSE_GRID para index.html a partir de un CSV de
tasas de dosis generadas fuera de línea (CARI-7A / toolkit Surrey / API).

Formato de entrada (CSV, una fila por punto):
    rc_gv,alt_km,hp_mv,rate_usvh
    0,8.0,300,1.50
    ...

Uso:
    python3 tools/generate_dose_grid.py --input rates.csv --axes "0:90:1,8.0:13.0:0.5,300:1200:100" --out dose_grid.js

O con puntos sueltos (el script reordena según los ejes y rellena huecos con error):
    python3 tools/generate_dose_grid.py --input rates.csv --axes "0:90:1,8.0:13.0:0.5,300:1200:100"

--out dose_grid.js  →  genera el bloque JS `DOSE_GRID = {...}` listo para pegar en
                      index.html (sustituyendo el bloque con data: null).

--validate refs.csv → compara la rejilla generada contra valores de referencia
                      (misma columna rate_usvh) e informa del error máximo.
"""
import argparse, base64, csv, struct, sys


def parse_axis(spec):
    lo, hi, step = (float(x) for x in spec.split(":"))
    vals = []
    v = lo
    while v <= hi + 1e-9:
        vals.append(round(v, 6))
        v += step
    return vals


def resample_to_axis(rows, rc_axis, alt_axis, hp_axis):
    """(rc, alt, hp, rate) irregulares -> lista de floats en orden rc-major.

    Por cada rebanada (alt, hp) se ordenan las muestras por Rc y se interpola
    linealmente sobre el eje. Por encima de la ultima muestra se mantiene el
    ultimo valor: el eje llega a 18 GV y el globo solo a 17.64, y extrapolar
    daria dosis irreales."""
    slices = {}
    for rc, alt, hp, rate in rows:
        slices.setdefault((round(alt, 6), round(hp, 6)), []).append((rc, rate))
    out = []
    for ai, alt in enumerate(alt_axis):
        for hi, hp in enumerate(hp_axis):
            pts = sorted(slices.get((round(alt, 6), round(hp, 6)), []))
            if len(pts) < 2:
                sys.stderr.write(
                    "ERROR: la rebanada alt=%s hp=%s tiene %d muestras (minimo 2)\n"
                    % (alt, hp, len(pts))
                )
                sys.exit(2)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            for rc in rc_axis:
                if rc <= xs[0]:
                    out.append(ys[0])
                    continue
                if rc >= xs[-1]:
                    out.append(ys[-1])
                    continue
                k = 0
                while k + 1 < len(xs) and xs[k + 1] < rc:
                    k += 1
                dx = xs[k + 1] - xs[k]
                out.append(ys[k] if dx == 0 else ys[k] + (ys[k + 1] - ys[k]) * (rc - xs[k]) / dx)
    # Reordenar de (alt, hp, rc) a rc-major -> alt -> hp.
    n_rc, n_alt, n_hp = len(rc_axis), len(alt_axis), len(hp_axis)
    ordered = [0.0] * (n_rc * n_alt * n_hp)
    idx = 0
    for ai in range(n_alt):
        for hi in range(n_hp):
            for ri in range(n_rc):
                ordered[(ri * n_alt + ai) * n_hp + hi] = out[idx]
                idx += 1
    return ordered


def build_grid(rows, axes):
    """(rc, alt, hp, rate) irregulares + spec de ejes -> (ejes, base64, bytes).
    A diferencia de la version por latitud, aqui las muestras NO caen en los
    nodos del eje: se remuestrean."""
    rc_axis, alt_axis, hp_axis = (parse_axis(a) for a in axes.split(","))
    floats = resample_to_axis(rows, rc_axis, alt_axis, hp_axis)
    packed = struct.pack("<%df" % len(floats), *floats)
    b64 = base64.b64encode(packed).decode("ascii")
    return rc_axis, alt_axis, hp_axis, b64, len(floats) * 4


RC_SCALE = 0.01  # GV por unidad del Int16


def build_rc_map(rcmap):
    """{(lat,lon): Rc} -> (lats, lons, base64 Int16LE) en orden lat-major.
    Rc se cuantiza a 0.01 GV: el maximo global (17.64 GV) da 1764, asi que
    cabe de sobra en Int16 y el error de cuantizacion es despreciable frente
    al paso del eje de la rejilla (0.25 GV)."""
    lats = sorted(set(k[0] for k in rcmap))
    lons = sorted(set(k[1] for k in rcmap))
    vals = []
    faltan = []
    for la in lats:
        for lo in lons:
            if (la, lo) not in rcmap:
                faltan.append((la, lo))
                vals.append(0)
                continue
            vals.append(int(round(rcmap[(la, lo)] / RC_SCALE)))
    if faltan:
        sys.stderr.write(
            "ERROR: al mapa de rigidez le faltan %d celdas (primeras 10: %s)\n"
            % (len(faltan), faltan[:10])
        )
        sys.exit(2)
    packed = struct.pack("<%dh" % len(vals), *vals)
    return lats, lons, base64.b64encode(packed).decode("ascii")


def write_rc_map_js(cutoff_path, out_path):
    from cari7_cutoffs import load_cutoff_map
    rcmap = load_cutoff_map(cutoff_path)
    lats, lons, b64 = build_rc_map(rcmap)
    lines = [
        "// Generado por tools/generate_dose_grid.py --rc-map — NO editar a mano.",
        "// Fuente: %s (%d celdas, %.1f KB Int16LE)." % (
            cutoff_path, len(lats) * len(lons), len(lats) * len(lons) * 2 / 1024),
        "var RC_MAP = {",
        "  lat0: %d, lat1: %d," % (lats[0], lats[-1]),
        "  lon0: %d, lon1: %d," % (lons[0], lons[-1]),
        "  scale: %s," % RC_SCALE,
        "  data: \"%s\"" % b64,
        "};",
    ]
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("Escrito %s (%d celdas, base64 %.1f KB)"
          % (out_path, len(lats) * len(lons), len(b64) / 1024))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", help="CSV con rc_gv,alt_km,hp_mv,rate_usvh")
    ap.add_argument("--axes",
                    help="Ejemplo: 0:18:0.25,8.0:13.0:0.5,300:1200:100 (Rc GV, alt km, HP MV)")
    ap.add_argument("--rc-map", help="fichero CUTOFFS/*.1X1; emite el bloque RC_MAP")
    ap.add_argument("--out", required=True, help="Fichero JS de salida")
    ap.add_argument("--validate", help="CSV de referencia (misma columna rate_usvh)")
    args = ap.parse_args()

    if args.rc_map:
        write_rc_map_js(args.rc_map, args.out)
        return
    if not args.input or not args.axes:
        ap.error("--input y --axes son obligatorios salvo con --rc-map")

    def read_csv(path):
        rows = []
        with open(path, newline="") as f:
            for r in csv.reader(f):
                if not r or r[0].startswith("#") or r[0].strip().lower() == "rc_gv":
                    continue
                rows.append((float(r[0]), float(r[1]), float(r[2]), float(r[3])))
        return rows

    rows = read_csv(args.input)
    rc_axis, alt_axis, hp_axis, b64, nbytes = build_grid(rows, args.axes)
    rc_js = "[" + ",".join(str(x) for x in rc_axis) + "]"
    alt_js = "[" + ",".join(str(x) for x in alt_axis) + "]"
    hp_js = "[" + ",".join(str(int(x)) for x in hp_axis) + "]"
    lines = [
        "// Generado por tools/generate_dose_grid.py - NO editar a mano.",
        "// Fuente: %s (%d muestras -> %d nodos, %.1f KB Float32LE)." % (
            args.input, len(rows), len(rc_axis) * len(alt_axis) * len(hp_axis), nbytes / 1024),
        "var DOSE_GRID = {",
        "  rc: %s," % rc_js,
        "  alt: %s," % alt_js,
        "  hp: %s," % hp_js,
        "  data: \"%s\"," % b64,
        "  epoch: \"IGRF2010\", version: 2",
        "};",
    ]
    out = "\n".join(lines) + "\n"
    with open(args.out, "w") as f:
        f.write(out)
    print("Escrito %s (%d puntos, %.1f KB, base64 %s KB)"
          % (args.out, len(rows), nbytes / 1024, len(b64) / 1024))

    if args.validate:
        refs = read_csv(args.validate)
        # decodificar la rejilla generada para interpolar-comparar
        raw = base64.b64decode(b64)
        floats = list(struct.unpack("<%df" % (len(raw) // 4), raw))
        n_rc, n_alt, n_hp = len(rc_axis), len(alt_axis), len(hp_axis)
        idx = {}
        for ri, rc in enumerate(rc_axis):
            for ai, alt in enumerate(alt_axis):
                for hi, hp in enumerate(hp_axis):
                    idx[(rc, alt, hp)] = floats[(ri * n_alt + ai) * n_hp + hi]
        worst, worst_pt = 0.0, None
        for rc, alt, hp, ref in refs:
            if (rc, alt, hp) not in idx:
                print("  ref fuera de rejilla, ignorada:", rc, alt, hp)
                continue
            err = abs(idx[(rc, alt, hp)] - ref)
            if err > worst:
                worst, worst_pt = err, (rc, alt, hp)
        print("Validación: %d puntos de referencia, error máximo %.4f µSv/h en Rc=%s"
              % (len(refs), worst, worst_pt))


if __name__ == "__main__":
    main()
