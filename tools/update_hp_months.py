#!/usr/bin/env python3
"""Regenera el bloque HP_MONTHS de index.html desde el fichero oficial
MV-DATES.L99 (FAA, descargable como MV-DATES.zip). Clave "YYYY-MM" -> MV.

Solo incluye meses desde --since (por defecto 2011, suficiente para el histórico
de la app). La fila anual (00/YYYY) se excluye.

Uso:
    python3 tools/update_hp_months.py --mv-dates MV-DATES.L99 --index index.html --since 2011
"""
import argparse, re, sys


def read_hp(path, since):
    out = {}
    for line in open(path, errors="replace"):
        m = re.match(r"\s*(\d\d)/(\d{4}),\s*(\d+)", line)
        if not m:
            continue
        mm, yy, hp = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if mm == 0 or yy < since:
            continue
        out["%04d-%02d" % (yy, mm)] = hp
    return out


def block_js(hp_map):
    parts = ['    "%s": %d' % (k, hp_map[k]) for k in sorted(hp_map)]
    lines = []
    for i in range(0, len(parts), 8):
        lines.append(", ".join(parts[i:i + 8]) + ",")
    return "var HP_MONTHS = {\n" + "\n".join(lines) + "\n};"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mv-dates", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--since", type=int, default=2011)
    args = ap.parse_args()
    hp_map = read_hp(args.mv_dates, args.since)
    if not hp_map:
        sys.exit("no se leyeron datos de %s" % args.mv_dates)
    html = open(args.index).read()
    pat = re.compile(r"var HP_MONTHS = \{[^}]*\};", re.S)
    if not pat.search(html):
        sys.exit("no encontré el bloque HP_MONTHS en %s" % args.index)
    new = block_js(hp_map)
    html = pat.sub(lambda m: new, html, count=1)
    open(args.index, "w").write(html)
    print("HP_MONTHS actualizado: %d meses (desde %d) -> %s" % (len(hp_map), args.since, args.index))


if __name__ == "__main__":
    main()
