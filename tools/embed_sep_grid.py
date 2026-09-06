#!/usr/bin/env python3
"""Embebe el bloque SEP_RESPONSE_GRID en index.html (T6 del plan).

Sigue exactamente el patron de `embed_dose_grid.py`: sustituye el bloque
`var SEP_RESPONSE_GRID = {...};` (o lo inserta la primera vez, detras del
bloque DOSE_GRID/RC_MAP) y verifica con node (vm.Script) que el <script> que
contiene el bloque sigue siendo parseable ANTES de escribir.

El bloque es generado por tools/generate_sep_grid.py assemble y NO se descarga
en runtime: kernel e interprete versionan juntos por diseno (Q92).

Uso:
    python3 tools/embed_sep_grid.py --grid sep_grid.js --index index.html
"""
import argparse, os, re, subprocess, sys, tempfile


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grid", required=True, help="fichero JS generado (var SEP_RESPONSE_GRID = {...};)")
    ap.add_argument("--index", required=True)
    args = ap.parse_args()

    block = open(args.grid).read().strip()
    assert "var SEP_RESPONSE_GRID = {" in block and block.rstrip().endswith("};"), \
        "bloque SEP_RESPONSE_GRID inválido"

    html = open(args.index).read()
    pat = re.compile(r"var SEP_RESPONSE_GRID = \{[^}]*\};", re.S)
    if pat.search(html):
        html = pat.sub(lambda m: block, html, count=1)
        print("SEP_RESPONSE_GRID sustituido (bloque ya existente)")
    else:
        # Primera vez: insertar justo detras del bloque DOSE_GRID (que termina
        # en "};" en su propia linea). Si RC_MAP esta justo detras, insertar
        # entre DOSE_GRID y RC_MAP.
        anchor = re.compile(r"^var DOSE_GRID = \{[^}]*\};\s*$", re.M)
        m = anchor.search(html)
        if not m:
            sys.exit("no encontré el bloque DOSE_GRID en %s (¿estructura cambiada?)" % args.index)
        end = m.end()
        html = html[:end] + "\n\n" + block + "\n" + html[end:]
        print("SEP_RESPONSE_GRID insertado detrás de DOSE_GRID")

    # Verificacion de sintaxis del script que contiene el bloque, antes de
    # escribir (mismo criterio que embed_dose_grid.py).
    pat_script = re.compile(r"<script[^>]*>([\s\S]*?)</script>")
    matches = [m for m in pat_script.finditer(html) if "var SEP_RESPONSE_GRID =" in m.group(1)]
    if not matches:
        sys.exit("no encontré el script que contiene SEP_RESPONSE_GRID en %s" % args.index)
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
        sys.exit("SYNTAX FAIL tras embeber:\n" + r.stderr[-2000:])
    print(r.stdout.strip())

    open(args.index, "w").write(html)
    print("SEP_RESPONSE_GRID embebido en %s (bloque de %d KB)"
          % (args.index, len(block) // 1024))


if __name__ == "__main__":
    main()
