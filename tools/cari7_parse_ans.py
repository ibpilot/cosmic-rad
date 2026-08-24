#!/usr/bin/env python3
"""Parsea la salida .ANS de CARI-7A (análisis de localizaciones) y extrae las
filas de dosis efectiva ICRP-103 (D2). Salida: CSV `rc_gv,alt_km,hp_mv,rate_usvh`.

El formato .ANS es CSV con cabecera:
    LAT, LON, ALTITUDE, DATE, HR, VCR(GV), PARTICLE, DOSE RATE, SIGMA, UNIT, QUANTITY
Las líneas de comentario empiezan por 'C' y se ignoran. Solo se usan las filas
cuya QUANTITY es 'ICRP Pub. 103 EFFECTIVE DOSE'.

Uso:
    python3 tools/cari7_parse_ans.py --ans grid_hp300.ans --hp 300 --out rates_hp300.csv
"""
import argparse, csv


def parse_ans(path, hp):
    """Filas D2 de un .ANS -> (rc_gv, alt_km, hp_mv, rate_usvh).

    Los indices del split por comas NO son los de la cabecera: el campo de
    altitud arrastra su unidad ("11.0000,K"), asi que VCR es t[6] y la tasa
    t[8]. Leer t[5] devuelve la hora, que siempre es 0."""
    rows = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("C") or line.lstrip().startswith("LAT,"):
                continue
            if "ICRP Pub. 103 EFFECTIVE DOSE" not in line:
                continue
            t = [x.strip() for x in line.split(",")]
            if len(t) < 9:
                continue
            try:
                alt = float(t[2])
                unit = t[3]
                rc = float(t[6])
                rate = float(t[8])
            except ValueError:
                continue
            if unit != "K":
                # La rejilla es en km; el programa devuelve la unidad de entrada.
                continue
            rows.append((rc, alt, hp, rate))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ans", required=True)
    ap.add_argument("--hp", required=True, type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rows = parse_ans(args.ans, args.hp)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rc_gv", "alt_km", "hp_mv", "rate_usvh"])
        w.writerows(rows)
    print("parseados %d puntos D2 -> %s" % (len(rows), args.out))


if __name__ == "__main__":
    main()
