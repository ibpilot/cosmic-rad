#!/usr/bin/env python3
"""Replace the marker-delimited SEP_RESPONSE_OPERATOR block atomically.

Only the text between ``BEGIN SEP_RESPONSE_OPERATOR`` and
``END SEP_RESPONSE_OPERATOR`` is writable.  This intentionally avoids a brace
counting regular expression: the Float32 base64 payload and future metadata may
contain arbitrary text without changing the replacement boundary.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile


BEGIN = "// BEGIN SEP_RESPONSE_OPERATOR"
END = "// END SEP_RESPONSE_OPERATOR"


def _marker_bounds(text: str) -> tuple[int, int]:
    starts = [index for index in range(len(text)) if text.startswith(BEGIN, index)]
    ends = [index for index in range(len(text)) if text.startswith(END, index)]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise ValueError("se requieren exactamente un par de marcadores SEP_RESPONSE_OPERATOR")
    end = ends[0] + len(END)
    return starts[0], end


def _validate_block(block: str) -> None:
    if "var SEP_RESPONSE_OPERATOR = {" not in block or not block.rstrip().endswith(END):
        raise ValueError("el artefacto no contiene la declaración sep-2 delimitada")
    if "model_version: \"sep-2\"" not in block:
        raise ValueError("el artefacto no es model_version sep-2")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(block)
        path = handle.name
    try:
        result = subprocess.run(
            ["node", "--check", path], capture_output=True, text=True, check=False
        )
    finally:
        os.unlink(path)
    if result.returncode != 0:
        raise ValueError("sintaxis JS inválida en el artefacto:\n" + result.stderr[-2000:])


def embed(operator_path: str, index_path: str, output_path: str | None = None) -> None:
    operator = open(operator_path, encoding="utf-8").read().strip()
    if BEGIN not in operator or END not in operator:
        raise ValueError("artefacto sin marcadores SEP_RESPONSE_OPERATOR")
    op_start, op_end = _marker_bounds(operator)
    _validate_block(operator[op_start:op_end])
    html = open(index_path, encoding="utf-8").read()
    start, end = _marker_bounds(html)
    updated = html[:start] + operator[op_start:op_end] + html[end:]
    # The replacement is staged in a temporary file before the destination is
    # touched, so a syntax or I/O failure cannot leave a partially written HTML.
    target = output_path or index_path
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=os.path.dirname(os.path.abspath(target)),
                                     delete=False) as handle:
        temporary = handle.name
        handle.write(updated)
    try:
        os.replace(temporary, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator", "--grid", dest="operator", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--out", help="salida opcional; por defecto reemplaza --index")
    args = parser.parse_args(argv)
    try:
        embed(args.operator, args.index, args.out)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"SEP_RESPONSE_OPERATOR embebido en {args.out or args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
