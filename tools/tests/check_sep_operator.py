#!/usr/bin/env python3
"""Strict structural checker for a ``SEP_RESPONSE_OPERATOR`` artefact.

This checker is deliberately independent of the browser runtime.  CI runs it
before embedding and again after embedding; it verifies the decoded bytes and
the SHA-256 digests, while the synchronous Module validates structure at load.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import math
import os
import re
import struct
import sys

# tools/tests/check_sep_operator.py vive en tools/tests, asi que la raiz de
# este fichero es <repo>/tools (no la raiz del repositorio).
TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import sep_operator_common as common

BEGIN = "// BEGIN SEP_RESPONSE_OPERATOR"
END = "// END SEP_RESPONSE_OPERATOR"


class CheckError(ValueError):
    pass


def extract_block(text: str) -> str:
    starts = [m.start() for m in re.finditer(re.escape(BEGIN), text)]
    ends = [m.start() for m in re.finditer(re.escape(END), text)]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise CheckError("se requiere exactamente un par de marcadores SEP_RESPONSE_OPERATOR")
    return text[starts[0]:ends[0] + len(END)]


def parse_block(text: str) -> tuple[dict, tuple[float, ...], tuple[float, ...]]:
    block = extract_block(text) if BEGIN in text else text
    match = re.search(r"var SEP_RESPONSE_OPERATOR = \{(?P<body>.*)\};", block, re.S)
    if not match:
        raise CheckError("declaración SEP_RESPONSE_OPERATOR ausente")
    body = "{" + match.group("body").strip() + "}"
    body = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', body)
    try:
        obj = ast.literal_eval(body)
    except (SyntaxError, ValueError) as exc:
        raise CheckError(f"objeto SEP_RESPONSE_OPERATOR no parseable: {exc}") from exc
    if not isinstance(obj, dict):
        raise CheckError("artefacto no es un objeto")
    energies = obj.get("energy_gev")
    rc = obj.get("rc_gv")
    altitude = obj.get("altitude_km")
    if not isinstance(energies, list) or not isinstance(rc, list) or not isinstance(altitude, list):
        raise CheckError("faltan ejes")
    expected = common.expected_tensor_length(energies, rc, altitude)
    try:
        response_raw = base64.b64decode(obj.get("response_data", ""), validate=True)
        error_raw = base64.b64decode(obj.get("error_data", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise CheckError("base64 inválido") from exc
    if len(response_raw) != expected * 4 or len(error_raw) != expected * 4:
        raise CheckError("longitud de tensor incorrecta")
    response = struct.unpack("<%df" % expected, response_raw)
    error = struct.unpack("<%df" % expected, error_raw)
    return obj, response, error


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def check(text: str, *, bo11_path: str | None = None, require_node_count: bool = False):
    obj, response, error = parse_block(text)
    exact = {
        "schema_version": common.SCHEMA_VERSION,
        "model_version": common.MODEL_VERSION,
        "engine_name": common.ENGINE_NAME,
        "engine_version": common.ENGINE_VERSION,
        "species": common.SPECIES,
        "quantity": common.QUANTITY,
        "geometry": common.GEOMETRY,
        "shielding": common.SHIELDING,
        "input_unit": common.INPUT_UNIT,
        "output_unit": common.OUTPUT_UNIT,
        "order": common.ORDER,
        "tail_from_gev": common.TAIL_FROM_GEV,
    }
    for key, value in exact.items():
        _require(obj.get(key) == value, f"{key} inválido")
    for key in ("distribution_sha256", "bo11_sha256", "response_sha256", "error_sha256"):
        _require(isinstance(obj.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", obj[key] or ""),
                 f"{key} no es SHA-256 hexadecimal")
    _require(isinstance(obj.get("validation_run_id"), str) and bool(obj["validation_run_id"]),
             "validation_run_id ausente")
    for key in ("validation_max_grid_relative_error", "validation_max_offgrid_relative_error"):
        _require(isinstance(obj.get(key), (int, float)) and math.isfinite(float(obj[key])) and obj[key] >= 0,
                 f"métrica inválida: {key}")
    energies = obj["energy_gev"]
    common.validate_active_node_list(energies, expected_count=43 if require_node_count else None)
    if bo11_path:
        full_nodes = common.read_bo11_z1_nodes(bo11_path)
        active = common.active_energies(full_nodes)
        _require(len(active) == len(energies), "el artefacto no contiene todos los nodos activos BO11")
        _require(all(a == b for a, b in zip(active, energies)), "la lista energética no es literal BO11")
    _require(obj["rc_gv"] == common.RC_TARGETS, "eje Rc alterado")
    _require(obj["altitude_km"] == common.ALT_VALUES, "eje altitud alterado")
    _require(all(math.isfinite(float(value)) and value >= 0 for value in response),
             "response_data contiene NaN/infinito/negativo")
    _require(all(math.isfinite(float(value)) and value >= 0 for value in error),
             "error_data contiene NaN/infinito/negativo")
    response_raw = base64.b64decode(obj["response_data"], validate=True)
    error_raw = base64.b64decode(obj["error_data"], validate=True)
    _require(hashlib.sha256(response_raw).hexdigest() == obj["response_sha256"],
             "response_sha256 no coincide con los bytes decodificados")
    _require(hashlib.sha256(error_raw).hexdigest() == obj["error_sha256"],
             "error_sha256 no coincide con los bytes decodificados")
    n_rc, n_alt = len(obj["rc_gv"]), len(obj["altitude_km"])
    column_size = n_rc * n_alt
    zero_columns = []
    for index in range(len(energies)):
        column = response[index * column_size:(index + 1) * column_size]
        if not any(value > 0 for value in column):
            zero_columns.append(index)
    _require(not zero_columns, f"columnas nodales completamente nulas: {zero_columns}")
    return obj, response, error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=os.path.join(os.path.dirname(TOOLS_DIR), "index.html"))
    parser.add_argument("--operator", "--grid", dest="operator")
    parser.add_argument("--bo11")
    parser.add_argument("--require-43", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = args.operator or args.index
        text = open(path, encoding="utf-8").read()
        obj, response, _error = check(text, bo11_path=args.bo11,
                                      require_node_count=args.require_43)
    except (OSError, CheckError, common.OperatorContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("CHECK SEP OPERATOR OK: %dx%dx%d, model %s, %d nonzero columns" % (
        len(obj["energy_gev"]), len(obj["rc_gv"]), len(obj["altitude_km"]),
        obj["model_version"], len(obj["energy_gev"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
