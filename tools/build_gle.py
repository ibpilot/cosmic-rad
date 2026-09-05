#!/usr/bin/env python3
"""Genera la tabla GLE_EVENTS a partir de NMDB.

Se ejecuta a mano; su salida se embebe en index.html (tools/embed_gle.py),
igual que la rejilla de CARI-7A.

Uso:
    python3 tools/build_gle.py --out gle_events.json
    python3 tools/build_gle.py --out gle_events.json --only 73
"""
import argparse
import datetime
import json

from gle_fit import baseline, fit_step, pct_increase
from gle_list import GLE_LIST
from gle_nmdb import STATIONS, fetch_nmdb

STEP_MIN = 15
WINDOW_H = 24.0
PRE_H = 2.0


def _t0_dt(t0_iso):
    return datetime.datetime.strptime(t0_iso, "%Y-%m-%dT%H:%MZ")


def _sql_iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_event(n, t0_iso, series, step_min=STEP_MIN, window_h=WINDOW_H):
    """Construye un evento del esquema embebido a partir de las series NMDB.

    series: {estacion: [(iso, valor)]}. Devuelve
    {"n", "t0", "dt", "q", "p": [[I0, R0, rms], ...]}.

    Sin ajuste fiable en ningun paso -> q = "solo evento" y p vacio: se marca
    que hubo GLE pero no se inventa una dosis.
    """
    t0 = _t0_dt(t0_iso)
    base = {}
    for st, rows in series.items():
        b = baseline(rows, _sql_iso(t0), PRE_H)
        if b:
            base[st] = b

    steps = int(window_h * 60 // step_min)
    prof = []
    for k in range(steps):
        lo = t0 + datetime.timedelta(minutes=k * step_min)
        hi = lo + datetime.timedelta(minutes=step_min)
        samples = []
        for st, b in base.items():
            rc = STATIONS.get(st)
            if rc is None:
                continue
            vals = [p for iso, p in pct_increase(series[st], b)
                    if _sql_iso(lo) <= iso < _sql_iso(hi)]
            if vals:
                samples.append((rc, sum(vals) / len(vals)))
        fit = fit_step(samples)
        if fit is None:
            if prof:
                break   # el evento ya termino: se corta el perfil
            continue    # todavia no ha empezado
        prof.append([round(fit[0], 3), round(fit[1], 3), round(fit[2], 3)])

    return {"n": n, "t0": t0_iso, "dt": step_min,
            "q": "ajustado" if prof else "solo evento", "p": prof}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", type=int, help="procesar solo este numero de GLE")
    args = ap.parse_args()

    events = []
    for ev in GLE_LIST:
        if args.only and ev["n"] != args.only:
            continue
        t0 = _t0_dt(ev["t0"])
        start = t0 - datetime.timedelta(hours=PRE_H)
        end = t0 + datetime.timedelta(hours=WINDOW_H)
        series = {}
        for st in STATIONS:
            try:
                rows = fetch_nmdb(st, start, end, res_min=1)
            except Exception as exc:            # estacion caida o sin datos
                print("  aviso: %s sin datos (%s)" % (st, exc))
                continue
            if rows:
                series[st] = rows
        out = build_event(ev["n"], ev["t0"], series)
        print("GLE%-3d %s  %s  %d pasos" % (out["n"], out["t0"], out["q"], len(out["p"])))
        events.append(out)

    with open(args.out, "w") as fh:
        json.dump(events, fh, separators=(",", ":"))
    print("escritos %d eventos en %s" % (len(events), args.out))


if __name__ == "__main__":
    main()
