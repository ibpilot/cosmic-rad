#!/usr/bin/env python3
"""Ajuste de la respuesta geomagnetica de un GLE a partir de NMDB.

Modelo por paso de tiempo:  pct(Rc) = I0 * exp(-Rc / R0)
  I0 = incremento porcentual extrapolado a Rc = 0
  R0 = rigidez de caida (proxy de dureza del espectro)

Se ajusta en espacio logaritmico, donde el modelo es una recta:
  ln(pct) = ln(I0) - Rc / R0
"""
import datetime
import math

MIN_STATIONS = 8      # por debajo de esto el ajuste no es fiable
MIN_PCT = 0.3         # suelo absoluto, por debajo de esto no hay sennal util
NSIGMA = 3.0          # umbral en sigmas del ruido de la propia estacion
R0_MAX_GV = 10.0      # por encima de esto no hay dependencia con la rigidez:
                      # es un Forbush o ruido de fondo, no un GLE


def _dt(iso):
    return datetime.datetime.strptime(iso, "%Y-%m-%d %H:%M:%S")


def baseline(rows, t0_iso, pre_hours=2.0):
    """Mediana de las `pre_hours` previas a t0. None si no hay datos previos.

    Mediana y no media: un spike instrumental de una sola muestra desplaza la
    media lo bastante como para borrar un GLE pequenno.
    """
    t0 = _dt(t0_iso)
    lo = t0 - datetime.timedelta(hours=pre_hours)
    vals = sorted(v for iso, v in rows if lo <= _dt(iso) < t0)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def stdev(vals):
    """Desviacion tipica poblacional. Ruido propio de cada estacion."""
    n = len(vals)
    if n < 2:
        return None
    mu = sum(vals) / float(n)
    return math.sqrt(sum((v - mu) ** 2 for v in vals) / float(n))


def pct_increase(rows, base):
    """[(iso, incremento %)] respecto al baseline."""
    if not base:
        raise ValueError("baseline nulo o cero")
    return [(iso, (v - base) / base * 100.0) for iso, v in rows]


def fit_step(samples):
    """Ajusta pct(Rc) = I0*exp(-Rc/R0) por minimos cuadrados en log.

    samples: [(rc_gv, pct, sigma_pct)]. Devuelve (I0, R0, rms) o None si no
    hay bastantes estaciones con sennal.

    El rms es el residuo en espacio logaritmico. Sube cuando el flujo NO es
    isotropo (fase inicial del GLE): dos estaciones a igual Rc discrepan segun
    su direccion asintotica. Se guarda para marcar esos pasos como de baja
    confianza en vez de esconder el problema.
    """
    pts = [(rc, p) for rc, p, sg in samples
           if p >= max(MIN_PCT, NSIGMA * (sg or 0.0))]
    if len(pts) < MIN_STATIONS:
        return None

    n = float(len(pts))
    xs = [rc for rc, _ in pts]
    ys = [math.log(p) for _, p in pts]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None   # todas las estaciones a la misma Rc: pendiente indefinida
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    if slope >= 0:
        return None   # el incremento crece con Rc: no es un GLE, es ruido
    intercept = my - slope * mx

    i0 = math.exp(intercept)
    r0 = -1.0 / slope
    if r0 > R0_MAX_GV:
        return None   # sin dependencia con la rigidez: no es un GLE
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    rms = math.sqrt(sum(r * r for r in resid) / n)
    return (i0, r0, rms)
