#!/usr/bin/env python3
"""Descarga el track REAL de un vuelo desde la API gratuita de OpenSky Network
(anónima, sin key) y lo guarda como CSV importable por la app.

Modos:
  --callsign IBE03KK --now            vuelo en el aire ahora (busca el icao24 en vivo)
  --icao24 3455d5 --time <epoch>      vuelo histórico (track alrededor de ese momento)
  --icao24 3455d5 --now               vuelo actual
  --time "2026-08-23 15:30" (UTC)     hora legible en vez de epoch

El CSV de salida usa cabeceras reconocibles por el parser de la app:
    UTC,latitude,longitude,altitude_m
(hora UTC como "YYYY-MM-DD HH:MM:SS", altitud en metros -> la app la convierte a km)

Notas:
- La API anónima tiene límites de créditos diarios y cobertura ADS-B irregular
  (el Atlántico Sur y zonas oceánicas pueden tener huecos).
- Sin CORS para navegadores: se ejecuta en terminal (o CI), no dentro de la app.

Uso:
    python3 tools/download_opensky_track.py --callsign IBE03KK --now --out track_ibe.csv
    python3 tools/download_opensky_track.py --icao24 3455d5 --time 1787501500 --out track.csv
"""
import argparse, json, sys, time, urllib.request
from datetime import datetime, timezone

API = "https://opensky-network.org/api"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "cosmic-rad-track/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def find_icao_by_callsign(callsign, bbox=None):
    """Busca en vivo el icao24 de un callsign (mayúsculas, sin espacios)."""
    target = callsign.upper().replace(" ", "")
    if bbox is None:
        bbox = dict(lamin=-90, lomin=-180, lamax=90, lomax=180)
    q = "&".join("%s=%s" % (k, v) for k, v in bbox.items())
    d = fetch("%s/states/all?%s" % (API, q))
    for s in d.get("states") or []:
        if s[1] and s[1].strip().upper().replace(" ", "") == target:
            return s[0], s[5], s[6]  # icao24, lat, lon
    return None, None, None


def parse_time(s):
    if s is None:
        return int(time.time())
    try:
        return int(s)  # epoch (str o numérico)
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    sys.exit("no pude interpretar la hora: %s" % s)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--callsign", help="callsign (p.ej. IBE03KK). Busca el icao24 en vivo.")
    ap.add_argument("--icao24", help="identificador hex del avión (si lo conoces)")
    ap.add_argument("--time", help="hora UTC: epoch, 'YYYY-MM-DD HH:MM' o ISO")
    ap.add_argument("--now", action="store_true", help="usar la hora actual")
    ap.add_argument("--out", required=True, help="CSV de salida")
    ap.add_argument("--bbox", help="opcional: lamin,lomin,lamax,lomax para la búsqueda en vivo")
    args = ap.parse_args()

    if not args.icao24 and not args.callsign:
        ap.error("necesitas --icao24 o --callsign")
    t = parse_time(args.time) if (args.time or args.now) else int(time.time())

    icao = args.icao24
    if not icao:
        bbox = None
        if args.bbox:
            a = [float(x) for x in args.bbox.split(",")]
            bbox = dict(zip("lamin lomin lamax lomax".split(), a))
        icao, lat, lon = find_icao_by_callsign(args.callsign, bbox)
        if not icao:
            sys.exit("callsign %s no encontrado en el aire (¿está volando ahora? ¿cubre tu zona ADS-B?)" % args.callsign)
        print("icao24 encontrado:", icao, "(pos %.1f, %.1f)" % (lat, lon))

    d = fetch("%s/tracks/all?icao24=%s&time=%d" % (API, icao, t))
    path = d.get("path") or []
    if not path:
        sys.exit("sin track para icao24=%s time=%d (¿cobertura o vuelo no visible?)" % (icao, t))
    print("callsign:", d.get("callsign"), "| puntos:", len(path))

    with open(args.out, "w") as f:
        f.write("UTC,latitude,longitude,altitude_m\n")
        for p in path:
            ts, lat, lon, alt, _, ong = p
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            f.write("%s,%.5f,%.5f,%.1f\n" % (iso, lat, lon, alt))
    print("escrito %s (%d puntos)" % (args.out, len(path)))


if __name__ == "__main__":
    main()
