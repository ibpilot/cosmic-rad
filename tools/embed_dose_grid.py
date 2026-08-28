#!/usr/bin/env python3
"""Sustituye el bloque DOSE_GRID de index.html por el generado
(tools/generate_dose_grid.py). Verifica que el JS resultante sigue siendo
parseable (node vm.Script) antes de escribir.

Uso:
    python3 tools/embed_dose_grid.py --grid dose_grid.js --index index.html
"""
import argparse, os, re, subprocess, sys, tempfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", required=True, help="fichero JS generado (var DOSE_GRID = {...};)")
    ap.add_argument("--rc-map", help="fichero JS generado (var RC_MAP = {...};)")
    ap.add_argument("--index", required=True)
    args = ap.parse_args()

    block = open(args.grid).read().strip()
    assert "var DOSE_GRID = {" in block and block.rstrip().endswith("};"), "bloque DOSE_GRID inválido"

    html = open(args.index).read()
    pat = re.compile(r"var DOSE_GRID = \{[^}]*\};", re.S)
    if not pat.search(html):
        sys.exit("no encontré el bloque DOSE_GRID (placeholder) en %s" % args.index)
    html = pat.sub(lambda m: block, html, count=1)

    if args.rc_map:
        rc_block = open(args.rc_map).read().strip()
        assert "var RC_MAP = {" in rc_block and rc_block.rstrip().endswith("};"), \
            "bloque RC_MAP inválido"
        rc_pat = re.compile(r"var RC_MAP = \{[^}]*\};", re.S)
        if rc_pat.search(html):
            html = rc_pat.sub(lambda m: rc_block, html, count=1)
        else:
            # Primera vez: insertar justo detrás del bloque DOSE_GRID.
            html = html.replace(block, block + "\n" + rc_block, 1)

    # verificación de sintaxis del script completo antes de guardar. Se busca
    # el <script> que CONTIENE el bloque DOSE_GRID recién embebido (el primero
    # del fichero no es necesariamente la app; la rejilla está en otro bloque).
    pat = re.compile(r"<script[^>]*>([\s\S]*?)</script>")
    matches = [m for m in pat.finditer(html) if "var DOSE_GRID =" in m.group(1)]
    if not matches:
        sys.exit("no encontré el script de la app en %s" % args.index)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(matches[0].group(1))
        tmp = f.name
    try:
        r = subprocess.run(["node", "-e",
                            'const fs=require("fs"),vm=require("vm");'
                            'new vm.Script(fs.readFileSync(process.argv[1],"utf8"));console.log("SYNTAX OK");',
                            tmp], capture_output=True, text=True)
    finally:
        os.unlink(tmp)
    if r.returncode != 0:
        sys.exit("SYNTAX FAIL tras embeker:\n" + r.stderr[-2000:])
    print(r.stdout.strip())

    open(args.index, "w").write(html)
    print("DOSE_GRID embebido en %s (bloque de %d KB)" % (args.index, len(block) // 1024))


if __name__ == "__main__":
    main()
