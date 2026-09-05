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
MIN_PCT = 0.5         # una estacion por debajo de 0,5% es ruido, no sennal


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


def pct_increase(rows, base):
    """[(iso, incremento %)] respecto al baseline."""
    if not base:
        raise ValueError("baseline nulo o cero")
    return [(iso, (v - base) / base * 100.0) for iso, v in rows]
