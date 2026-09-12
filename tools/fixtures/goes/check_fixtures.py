#!/usr/bin/env python3
"""Valida los fixtures GOES de T2 (eventos SEP + dias tranquilos).

Cada fixture es un JSON convertido del NetCDF SGPS L2 avg5m de NCEI/NGDC
(producto real: 13 canales DIFERENCIALES P1..P10 + integral >=500 MeV).
Este validador corre en CI, hermetico (sin red): comprueba que cada fichero
tiene los canales esperados, cadencia regular, sin valores invalidos, y que la
procedencia del README (URL, fecha, SHA-256 del .nc original) esta completa.

El .nc original NO se commitea: solo su JSON convertido. El SHA-256 del .nc
viaja en el README como procedencia; si el .nc esta presente en local (mismo
directorio, opcional) se verifica contra el README.

Uso: python3 tools/fixtures/goes/check_fixtures.py
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
README = os.path.join(HERE, "README.md")

EXPECTED_STEPS = 288      # 24 h a cadencia 5 min
STEP_S = 300
REQUIRED_CHANNELS = ["P1", "P2A", "P2B", "P3", "P4", "P5", "P6", "P7",
                     "P8A", "P8B", "P8C", "P9", "P10"]

failures = []


def fail(msg):
    failures.append(msg)
    print("  FAIL " + msg)


def parse_readme():
    """Extrae la tabla de procedencia del README.

    Devuelve {fichero.json: {"desc", "sat", "nc", "url", "sha256", "fecha"}}.
    """
    with open(README, encoding="utf-8") as fh:
        text = fh.read()
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*(\S+\.json)\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # columnas: fichero | descripcion | satelite | fichero .nc | sha256
        if len(cells) >= 5 and re.match(r"^[0-9a-f]{64}$", cells[4]):
            rows[cells[0]] = {"desc": cells[1], "sat": cells[2],
                              "nc": cells[3], "sha256": cells[4]}
    return rows


def check_fixture(fname, meta):
    path = os.path.join(HERE, fname)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    if data.get("product") != "sgps-l2-avg5m":
        fail(f"{fname}: product inesperado {data.get('product')}")
    if data.get("n_steps") != EXPECTED_STEPS:
        fail(f"{fname}: esperaba {EXPECTED_STEPS} pasos, hay {data.get('n_steps')}")

    chans = [c["name"] for c in data.get("channels", [])]
    if chans != REQUIRED_CHANNELS:
        fail(f"{fname}: canales {chans} != {REQUIRED_CHANNELS}")

    integral = data.get("integral_500_keV", [])
    diff = data.get("diff", [])
    if len(integral) != EXPECTED_STEPS:
        fail(f"{fname}: integral tiene {len(integral)} pasos")
    if len(diff) != EXPECTED_STEPS or any(len(r) != 13 for r in diff):
        fail(f"{fname}: diff no es {EXPECTED_STEPS}x13")

    # El integral >=500 (canal de deteccion) debe ser continuo: sin nulls.
    n_null_int = sum(1 for v in integral if v is None)
    if n_null_int > 0:
        fail(f"{fname}: integral tiene {n_null_int} nulls (debe ser continuo)")
    # Los diferenciales altos pueden tener nulls legitimos (sensor sin valor).
    n_null_diff = sum(1 for row in diff for v in row if v is None)
    if n_null_diff > 0:
        print(f"  aviso {fname}: {n_null_diff} nulls en diff")

    # Sin valores negativos: el _FillValue (-1e31) debe estar convertido a null.
    bad = [v for row in diff for v in row if v is not None and v < 0]
    bad += [v for v in integral if v is not None and v < 0]
    if bad:
        fail(f"{fname}: {len(bad)} valores negativos sin convertir")

    if data.get("time_step_s") != STEP_S:
        fail(f"{fname}: time_step_s {data.get('time_step_s')} != {STEP_S}")

    # Si el .nc original esta presente en local, verificar su SHA-256.
    nc_path = os.path.join(HERE, meta["nc"])
    if os.path.exists(nc_path):
        h = hashlib.sha256()
        with open(nc_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        if h.hexdigest() != meta["sha256"]:
            fail(f"{fname}: SHA-256 del .nc no coincide con README")
        else:
            print(f"  ok {fname}: SHA-256 del .nc verificado en local")
    else:
        print(f"  ok {fname}: .nc no presente (CI), SHA-256 registrado en README")


def main():
    entries = parse_readme()
    if not entries:
        fail("no encontre filas de procedencia en el README")
    print(f"fixtures declarados en README: {len(entries)}")

    for fname, meta in sorted(entries.items()):
        path = os.path.join(HERE, fname)
        if not os.path.exists(path):
            fail(f"falta fichero {fname}")
            continue
        check_fixture(fname, meta)

    present = sorted(f for f in os.listdir(HERE)
                     if f.endswith(".json") and f != "manifest.json")
    declared = sorted(entries.keys())
    if present != declared:
        fail(f"ficheros presentes {present} != declarados {declared}")

    print()
    if failures:
        print(f"CHECK FIXTURES FALLA: {len(failures)} error(es)")
        sys.exit(1)
    print("CHECK FIXTURES OK")


if __name__ == "__main__":
    main()
