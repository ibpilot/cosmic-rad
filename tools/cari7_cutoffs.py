#!/usr/bin/env python3
"""Lee los mapas de rigidez de corte vertical que distribuye CARI-7A en
CUTOFFS/*.1X1 (rejilla 1x1 grados, lat -89..89, lon 0..359 E, GV) y elige la
epoca que el programa usaria para una fecha dada.

CARI-7A calcula la dosis a partir de la rigidez de corte del punto: dos
localizaciones con la misma Rc dan la misma dosis. Por eso la rejilla de la app
se indexa por Rc y no por latitud.
"""
import re

# Anio nominal -> fichero, en el orden en que CARI-7A los distribuye.
EPOCHS = [
    (1965, "WGRC1965.1X1"),
    (1980, "IGRF1980.1X1"),
    (1990, "DGRF1990.1X1"),
    (1995, "IGRF1995.1X1"),
    (2000, "IGRF2000.1X1"),
    (2010, "IGRF2010.1X1"),
]


def epoch_file_for_year(year):
    """Fichero de epoca mas cercano al anio.

    OJO: CARI-7A no salta al mapa mas cercano, INTERPOLA entre epocas (medido:
    en 50N/270E da 0.70 GV en 1958, 0.77 en 1985, 0.85 en 2006 y 0.87 de 2010
    en adelante, donde se satura). Esta funcion solo sirve para ELEGIR los
    puntos de muestreo; la rejilla se construye con el VCR real que CARI-7A
    reporta, asi que la aproximacion no afecta al resultado."""
    return min(EPOCHS, key=lambda e: abs(e[0] - year))[1]


def parse_cutoff_text(text):
    """Texto de un .1X1 -> {(lat, lon): Rc en GV}."""
    rc, lonblock = {}, None
    for line in text.splitlines():
        s = line.rstrip()
        if not s.strip() or "CUTOFF" in s.upper():
            continue
        if "LAT" in s and "LON" in s:
            continue
        parts = s.split()
        # Fila de indices de longitud: solo enteros sin signo ni decimales.
        if len(parts) >= 4 and all(re.fullmatch(r"\d+", x) for x in parts):
            lonblock = [int(x) for x in parts]
            continue
        if lonblock and re.fullmatch(r"-?\d+", parts[0]) and len(parts) > 1:
            lat = int(parts[0])
            for lo, v in zip(lonblock, parts[1:]):
                try:
                    rc[(lat, lo)] = float(v)
                except ValueError:
                    pass
    return rc


def load_cutoff_map(path):
    """Ruta de un .1X1 -> {(lat, lon): Rc en GV}."""
    with open(path, "r", errors="replace") as f:
        return parse_cutoff_text(f.read())


def points_for_rc_targets(rcmap, targets, tol=0.13):
    """Para cada Rc objetivo, el (lat, lon, rc_real) mas cercano del mapa.
    Los objetivos que no se acercan a `tol` se descartan: sin esto entrarian
    nodos inventados en el eje de la rejilla."""
    out = []
    for t in targets:
        best, bd = None, float("inf")
        for (la, lo), v in rcmap.items():
            d = abs(v - t)
            if d < bd:
                bd, best = d, (la, lo, v)
        if best is not None and bd <= tol:
            out.append(best)
    return out
