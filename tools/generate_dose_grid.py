#!/usr/bin/env python3
"""Ensambla la rejilla de dosis DOSE_GRID para index.html a partir de un CSV de
tasas de dosis generadas fuera de línea (CARI-7A / toolkit Surrey / API).

Formato de entrada (CSV, una fila por punto):
    lat,alt_km,hp_mv,rate_usvh
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


def build_grid(rows, axes):
    lat_axis, alt_axis, hp_axis = (parse_axis(a) for a in axes.split(","))
    n_lat, n_alt, n_hp = len(lat_axis), len(alt_axis), len(hp_axis)
    grid = {}
    for lat, alt, hp, rate in rows:
        grid[(round(lat, 6), round(alt, 6), round(hp, 6))] = rate
    missing = []
    floats = []
    for li, lat in enumerate(lat_axis):
        for ai, alt in enumerate(alt_axis):
            for hi, hp in enumerate(hp_axis):
                key = (lat, alt, hp)
                if key not in grid:
                    missing.append(key)
                    floats.append(0.0)
                else:
                    floats.append(float(grid[key]))
    if missing:
        sys.stderr.write(
            "ERROR: %d puntos faltan en la rejilla (primeros 10: %s)\n"
            % (len(missing), missing[:10])
        )
        sys.exit(2)
    packed = struct.pack("<%df" % len(floats), *floats)
    b64 = base64.b64encode(packed).decode("ascii")
    return lat_axis, alt_axis, hp_axis, b64, len(floats) * 4


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="CSV con lat,alt_km,hp_mv,rate_usvh")
    ap.add_argument("--axes", required=True,
                    help="Ejemplo: 0:90:1,8.0:13.0:0.5,300:1200:100 (lat, alt km, HP MV)")
    ap.add_argument("--out", required=True, help="Fichero JS de salida")
    ap.add_argument("--validate", help="CSV de referencia (misma columna rate_usvh)")
    args = ap.parse_args()

    def read_csv(path):
        rows = []
        with open(path, newline="") as f:
            for r in csv.reader(f):
                if not r or r[0].startswith("#") or r[0].strip().lower() == "lat":
                    continue
                rows.append((float(r[0]), float(r[1]), float(r[2]), float(r[3])))
        return rows

    rows = read_csv(args.input)
    lat_axis, alt_axis, hp_axis, b64, nbytes = build_grid(rows, args.axes)
    lat_js = "[" + ",".join(str(int(x)) if x == int(x) else str(x) for x in lat_axis) + "]"
    alt_js = "[" + ",".join(str(x) for x in alt_axis) + "]"
    hp_js = "[" + ",".join(str(int(x)) for x in hp_axis) + "]"
    lines = [
        "// Generado por tools/generate_dose_grid.py — NO editar a mano.",
        "// Fuente de datos: %s (%d puntos, %.1f KB Float32LE)." % (args.input, len(rows), nbytes / 1024),
        "var DOSE_GRID = {",
        "  lat: %s," % lat_js,
        "  alt: %s," % alt_js,
        "  hp: %s," % hp_js,
        "  data: \"%s\"" % b64,
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
        n_lat, n_alt, n_hp = len(lat_axis), len(alt_axis), len(hp_axis)
        idx = {}
        for li, lat in enumerate(lat_axis):
            for ai, alt in enumerate(alt_axis):
                for hi, hp in enumerate(hp_axis):
                    idx[(lat, alt, hp)] = floats[(li * n_alt + ai) * n_hp + hi]
        worst, worst_pt = 0.0, None
        for lat, alt, hp, ref in refs:
            if (lat, alt, hp) not in idx:
                print("  ref fuera de rejilla, ignorada:", lat, alt, hp)
                continue
            err = abs(idx[(lat, alt, hp)] - ref)
            if err > worst:
                worst, worst_pt = err, (lat, alt, hp)
        print("Validación: %d puntos de referencia, error máximo %.4f µSv/h en %s"
              % (len(refs), worst, worst_pt))


if __name__ == "__main__":
    main()
