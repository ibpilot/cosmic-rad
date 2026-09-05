#!/usr/bin/env python3
"""Calibracion de K0/beta y validacion hold-out de la dosis de GLE.

Criterio de aceptacion: error dentro de un factor 3 en hold-out. Si no pasa,
NO se despliegan cifras: los eventos degradan a "solo evento".

Uso:
    python3 tools/holdout_gle.py --events gle_events.json
"""
import argparse
import json
import math

R0REF_GV = 1.0
ALT_REF_KM = 10.668     # FL350
SEP_ATT_KM = 2.0        # longitud de atenuacion en altitud (knob de calibracion)
MAX_FACTOR = 3.0        # criterio de aceptacion del hold-out
MIN_FOR_BETA = 4        # menos eventos publicados -> beta = 0


def alt_factor(alt_km):
    """Escalado en altitud. El gradiente SEP es mas pronunciado que el GCR
    (espectro mas blando), asi que NO se reutiliza el de la rejilla."""
    return math.exp((alt_km - ALT_REF_KM) / SEP_ATT_KM)


def event_dose(event, rc_gv, alt_km, k0, beta):
    """Dosis efectiva integrada del evento completo, en uSv."""
    if not event.get("p"):
        return 0.0
    dt_h = event["dt"] / 60.0
    total = 0.0
    for i0, r0, _rms in event["p"]:
        if r0 <= 0:
            continue
        k = k0 * (r0 / R0REF_GV) ** beta
        total += k * i0 * math.exp(-rc_gv / r0) * alt_factor(alt_km) * dt_h
    return total


def _by_n(events):
    return {e["n"]: e for e in events}


def fit_calibration(events, published):
    """Ajusta (K0, beta) minimizando el error cuadratico en log-dosis.

    Barrido de beta y K0 analitico dado beta: la dosis es lineal en K0, asi que
    el K0 optimo en log es la media geometrica del cociente observado/predicho.
    """
    idx = _by_n(events)
    pairs = [(idx[p["n"]], p) for p in published if p["n"] in idx and idx[p["n"]].get("p")]
    if not pairs:
        raise SystemExit("ningun evento publicado casa con la tabla generada")

    # Ordenado por |beta| ascendente: ante empate (perdida plana, p. ej. eventos
    # publicados sin contraste espectral) gana el modelo mas simple, beta = 0.
    betas = ([0.0] if len(pairs) < MIN_FOR_BETA
             else sorted([b / 20.0 for b in range(-20, 41)], key=lambda x: (abs(x), x)))
    best = None
    for beta in betas:
        logs = []
        for ev, pub in pairs:
            pred = event_dose(ev, pub["rc_gv"], pub["alt_km"], 1.0, beta)
            if pred <= 0 or pub["dose_usv"] <= 0:
                continue
            logs.append(math.log(pub["dose_usv"] / pred))
        if not logs:
            continue
        k0 = math.exp(sum(logs) / len(logs))
        err = sum((l - math.log(k0)) ** 2 for l in logs)
        if best is None or err < best[0]:
            best = (err, k0, beta)
    if best is None:
        raise SystemExit("no se pudo calibrar: sin predicciones positivas")
    return (best[1], best[2])


def holdout(events, published):
    """Deja un evento fuera, calibra con el resto, y predice el excluido."""
    rows = []
    for pub in published:
        rest = [p for p in published if p["n"] != pub["n"]]
        if len(rest) < 2:
            continue
        k0, beta = fit_calibration(events, rest)
        ev = _by_n(events).get(pub["n"])
        if not ev or not ev.get("p"):
            continue
        pred = event_dose(ev, pub["rc_gv"], pub["alt_km"], k0, beta)
        obs = pub["dose_usv"]
        factor = max(pred / obs, obs / pred) if pred > 0 and obs > 0 else float("inf")
        rows.append({"n": pub["n"], "pred": pred, "obs": obs, "factor": factor})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--events", required=True)
    ap.add_argument("--published", default="tools/gle_published.json")
    args = ap.parse_args()

    events = json.load(open(args.events))
    published = [p for p in json.load(open(args.published)) if p.get("dose_usv", 0) > 0]
    k0, beta = fit_calibration(events, published)
    print("K0 = %.4f uSv/h por punto porcentual   beta = %.2f" % (k0, beta))

    worst = 0.0
    for row in holdout(events, published):
        print("  GLE%-3d pred %8.1f uSv   obs %8.1f uSv   factor %.2f"
              % (row["n"], row["pred"], row["obs"], row["factor"]))
        worst = max(worst, row["factor"])
    print("peor factor: %.2f (limite %.1f)" % (worst, MAX_FACTOR))
    if worst > MAX_FACTOR:
        raise SystemExit("HOLD-OUT FALLA: no se despliegan cifras de dosis")
    print("HOLD-OUT OK")


if __name__ == "__main__":
    main()
