#!/usr/bin/env python3
"""Acceso a NMDB (Neutron Monitor Database) y tabla de estaciones.

La red de monitores cubre rigideces de corte de 0,8 a 17 GV. El incremento
porcentual observado en cada estacion frente a su Rc ES la curva de atenuacion
geomagnetica del evento, medida. No hace falta modelarla.

Se usa el canal corregido por eficiencia y presion (dtype=corr_for_efficiency):
la presion atmosferica mueve el conteo varios por ciento, del mismo orden que
un GLE pequenno.
"""
import re
import urllib.request

# Codigo NMDB -> rigidez de corte vertical en GV.
STATIONS = {
    "SOPO": 0.10,   # South Pole
    "THUL": 0.30,   # Thule
    "MCMU": 0.30,   # McMurdo
    "TERA": 0.01,   # Terre Adelie
    "APTY": 0.65,   # Apatity
    "OULU": 0.81,   # Oulu
    "KERG": 1.14,   # Kerguelen
    "INVK": 0.30,   # Inuvik
    "NAIN": 0.30,   # Nain
    "JUNG": 4.49,   # Jungfraujoch
    "LMKS": 3.84,   # Lomnicky Stit
    "ROME": 6.27,   # Rome
    "ATHN": 8.53,   # Athens
    "MXCO": 8.20,   # Mexico City
    "TSMB": 9.15,   # Tsumeb
    "PSNM": 16.80,  # Doi Inthanon
}

_URL = ("https://www.nmdb.eu/nest/draw_graph.php?formchk=1&stations[]={st}"
        "&tabchoice=revori&dtype=corr_for_efficiency&tresolution={res}"
        "&force=1&yunits=0&date_choice=bydate"
        "&start_day={sd}&start_month={sm}&start_year={sy}&start_hour={sh}&start_min={smi}"
        "&end_day={ed}&end_month={em}&end_year={ey}&end_hour={eh}&end_min={emi}"
        "&output=ascii")

_ROW = re.compile(r"^\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*;\s*([-\d.eE+]+)\s*$")


def nmdb_url(station, start, end, res_min):
    """URL del endpoint ascii de NMDB para una estacion y ventana."""
    return _URL.format(st=station, res=res_min,
                       sd=start.day, sm=start.month, sy=start.year,
                       sh=start.hour, smi=start.minute,
                       ed=end.day, em=end.month, ey=end.year,
                       eh=end.hour, emi=end.minute)


def parse_nmdb_ascii(text):
    """Extrae [(iso_utc, valor)] de la pagina HTML que devuelve NMDB.

    Los datos vienen embebidos en HTML; las lineas de datos son las unicas con
    formato "fecha; valor". Los huecos vienen como "null" y se descartan: un
    hueco no es un cero, y tratarlo como cero hunde el baseline.
    """
    out = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        try:
            out.append((m.group(1), float(m.group(2))))
        except ValueError:
            continue
    return out


def fetch_nmdb(station, start, end, res_min=1, timeout=60):
    """Descarga y parsea. Solo se llama desde el pipeline, nunca desde tests."""
    url = nmdb_url(station, start, end, res_min)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return parse_nmdb_ascii(raw)
