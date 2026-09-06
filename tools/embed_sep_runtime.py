#!/usr/bin/env python3
"""Inline the SEP-2 runtime into ``index.html`` between fixed markers.

``tools/sep_operator_runtime.js`` remains the single source of truth: this
script copies it byte-for-byte between ``// BEGIN SEP_OPERATOR_RUNTIME`` and
``// END SEP_OPERATOR_RUNTIME`` inside the app script, so the browser page
stays self-contained and the Node Module keeps being tested directly.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile


BEGIN = "// BEGIN SEP_OPERATOR_RUNTIME"
END = "// END SEP_OPERATOR_RUNTIME"
HEADER = ("// BEGIN SEP_OPERATOR_RUNTIME\n"
          "// Copia literal de tools/sep_operator_runtime.js; regenerar con\n"
          "// python3 tools/embed_sep_runtime.py. No editar a mano.\n")


def _marker_bounds(text: str) -> tuple[int, int]:
    starts = [index for index in range(len(text)) if text.startswith(BEGIN, index)]
    ends = [index for index in range(len(text)) if text.startswith(END, index)]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise ValueError("se requieren exactamente un par de marcadores SEP_OPERATOR_RUNTIME")
    end = ends[0] + len(END)
    return starts[0], end


def _embedded_block(text: str) -> str:
    start, end = _marker_bounds(text)
    return text[start:end]


def _block(runtime: str) -> str:
    return HEADER + runtime + "\n" + END


def embed(runtime_path: str, index_path: str, output_path: str | None = None) -> None:
    runtime = open(runtime_path, encoding="utf-8").read()
    html = open(index_path, encoding="utf-8").read()
    start, end = _marker_bounds(html)
    updated = html[:start] + _block(runtime) + html[end:]
    # The replacement is staged in a temporary file before the destination is
    # touched, so an I/O failure cannot leave a partially written HTML.
    target = output_path or index_path
    with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                     dir=os.path.dirname(os.path.abspath(target)),
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


def check(runtime_path: str, index_path: str) -> None:
    runtime = open(runtime_path, encoding="utf-8").read()
    html = open(index_path, encoding="utf-8").read()
    embedded = _embedded_block(html)
    if embedded != _block(runtime):
        raise ValueError(
            "el runtime embebido en index.html no coincide con "
            "tools/sep_operator_runtime.js; regenerar con python3 tools/embed_sep_runtime.py"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default="tools/sep_operator_runtime.js")
    parser.add_argument("--index", default="index.html")
    parser.add_argument("--check", action="store_true", help="no escribe; verifica la copia")
    args = parser.parse_args(argv)
    try:
        if args.check:
            check(args.runtime, args.index)
        else:
            embed(args.runtime, args.index)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.check:
        print("SEP_OPERATOR_RUNTIME embebido coincide con su fuente")
    else:
        print(f"SEP_OPERATOR_RUNTIME embebido en {args.index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
