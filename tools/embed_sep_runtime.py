#!/usr/bin/env python3
"""Inline the SEP runtimes into ``index.html`` between fixed markers.

Each ``tools/sep_*_runtime.js`` file remains the single source of truth: this
script copies it byte-for-byte between its BEGIN/END markers inside the app
script, so the browser page stays self-contained while the Node Modules keep
being tested directly against the canonical source.

Runtimes are declared in :data:`RUNTIMES`. ``--check`` verifies every embedded
copy against its source (used by CI); without it, every copy is rewritten.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

RUNTIMES = (
    {
        "name": "SEP_OPERATOR_RUNTIME",
        "source": "tools/sep_operator_runtime.js",
        "begin": "// BEGIN SEP_OPERATOR_RUNTIME",
        "end": "// END SEP_OPERATOR_RUNTIME",
        "header": ("// Copia literal de tools/sep_operator_runtime.js; regenerar con\n"
                   "// python3 tools/embed_sep_runtime.py. No editar a mano.\n"),
    },
    {
        "name": "SEP_MODEL_RUNTIME",
        "source": "tools/sep_model_runtime.js",
        "begin": "// BEGIN SEP_MODEL_RUNTIME",
        "end": "// END SEP_MODEL_RUNTIME",
        "header": ("// Copia literal de tools/sep_model_runtime.js; regenerar con\n"
                   "// python3 tools/embed_sep_runtime.py. No editar a mano.\n"),
    },
)


def _marker_bounds(text: str, begin: str, end: str, name: str) -> tuple[int, int]:
    starts = [index for index in range(len(text)) if text.startswith(begin, index)]
    ends = [index for index in range(len(text)) if text.startswith(end, index)]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise ValueError(f"se requieren exactamente un par de marcadores {name}")
    return starts[0], ends[0] + len(end)


def _block(runtime: str, begin: str, header: str, end: str) -> str:
    return begin + "\n" + header + runtime + "\n" + end


def _sources_by_index() -> dict[str, dict]:
    return {runtime["name"]: runtime for runtime in RUNTIMES}


def _selected(only: str | None) -> list[dict]:
    return [runtime for runtime in RUNTIMES if only in (None, runtime["name"])]


def embed(index_path: str, only: str | None = None) -> list[str]:
    index = Path(index_path)
    html = index.read_text(encoding="utf-8")
    selected = _selected(only)
    for runtime in selected:
        source = Path(runtime["source"]).read_text(encoding="utf-8")
        start, end = _marker_bounds(html, runtime["begin"], runtime["end"], runtime["name"])
        html = html[:start] + _block(source, runtime["begin"], runtime["header"], runtime["end"]) + html[end:]
    # The replacement is staged before the destination is touched, so an I/O
    # failure cannot leave a partially written HTML.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                     dir=os.path.dirname(os.path.abspath(index_path)),
                                     delete=False) as handle:
        temporary = handle.name
        handle.write(html)
    try:
        os.replace(temporary, index_path)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return [runtime["name"] for runtime in selected]


def check(index_path: str, only: str | None = None) -> list[str]:
    html = Path(index_path).read_text(encoding="utf-8")
    selected = _selected(only)
    for runtime in selected:
        source = Path(runtime["source"]).read_text(encoding="utf-8")
        start, end = _marker_bounds(html, runtime["begin"], runtime["end"], runtime["name"])
        if html[start:end] != _block(source, runtime["begin"], runtime["header"], runtime["end"]):
            raise ValueError(
                f"el runtime {runtime['name']} embebido en {index_path} no coincide con "
                f"{runtime['source']}; regenerar con python3 tools/embed_sep_runtime.py"
            )
    return [runtime["name"] for runtime in selected]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default="index.html")
    parser.add_argument("--runtime", choices=sorted(_sources_by_index()),
                        help="limita a un runtime; por defecto, todos")
    parser.add_argument("--check", action="store_true", help="no escribe; verifica la copia")
    args = parser.parse_args(argv)
    try:
        names = check(args.index, args.runtime) if args.check else embed(args.index, args.runtime)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    verb = "coinciden con su fuente" if args.check else f"embebidos en {args.index}"
    print(f"{', '.join(names)} {verb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
