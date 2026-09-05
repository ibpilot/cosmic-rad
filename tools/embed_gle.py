#!/usr/bin/env python3
"""Embebe GLE_EVENTS y GLE_CAL en index.html.

Sigue el patron de tools/embed_dose_grid.py: sustituye bloques marcados y
verifica que el JS resultante sigue siendo parseable antes de escribir.

Uso:
    python3 tools/embed_gle.py --events gle_events.json --k0 1.5 --beta 0.25 --index index.html
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile


def render_blocks(events, k0, beta):
    ev = "var GLE_EVENTS = %s;" % json.dumps(events, separators=(",", ":"))
    cal = ("var GLE_CAL = {k0: %r, beta: %r, attKm: 2.0, altRefKm: 10.668, r0Ref: 1.0};"
           % (float(k0), float(beta)))
    return ev, cal


def replace_blocks(html, ev_block, cal_block):
    ev_pat = re.compile(r"var GLE_EVENTS = \[.*?\];", re.S)
    cal_pat = re.compile(r"var GLE_CAL = \{.*?\};", re.S)
    if not ev_pat.search(html) or not cal_pat.search(html):
        sys.exit("no encontre los placeholders GLE_EVENTS / GLE_CAL en el index")
    html = ev_pat.sub(lambda m: ev_block, html, count=1)
    html = cal_pat.sub(lambda m: cal_block, html, count=1)
    return html


def _check_syntax(html):
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    target = [s for s in scripts if "GLE_EVENTS" in s]
    if not target:
        sys.exit("tras embeber no hay script con GLE_EVENTS")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(target[0])
        path = fh.name
    r = subprocess.run(["node", "-e",
                        "new (require('vm').Script)(require('fs').readFileSync(%r,'utf8'))" % path],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("el JS embebido no parsea: " + r.stderr.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", required=True)
    ap.add_argument("--k0", type=float, required=True)
    ap.add_argument("--beta", type=float, required=True)
    ap.add_argument("--index", default="index.html")
    args = ap.parse_args()

    events = json.load(open(args.events))
    ev_block, cal_block = render_blocks(events, args.k0, args.beta)
    html = replace_blocks(open(args.index).read(), ev_block, cal_block)
    _check_syntax(html)
    open(args.index, "w").write(html)
    print("embebidos %d eventos (K0=%s beta=%s)" % (len(events), args.k0, args.beta))


if __name__ == "__main__":
    main()
