#!/usr/bin/env python3
"""Verificador del kernel SEP_RESPONSE_GRID embebido en index.html (verify de T6).

Comprueba el bloque JS `var SEP_RESPONSE_GRID = {...}` (el generado por
tools/generate_sep_grid.py y embebido con tools/embed_sep_grid.py):

  1. dimensiones 53 E x 73 Rc x 11 alt x 1 magnitud (D2)
  2. version del modelo presente y conocida
  3. ejes literales (energia 50 MeV..20 GeV creciente, Rc 0..18, alt 8..13)
  4. sin NaN ni negativos en los datos
  5. monotonía esperada, a igual espectro (misma columna E):
       - mas altitud  -> mas dosis
       - mas Rc       -> menos dosis
     (la dosis decrece al subir Rc porque el corte geomagnetico excluye mas
     particulas; crece con la altitud porque hay menos atmosfera que blinde)

Uso:
    python3 tools/tests/check_sep_grid.py [--index index.html] [--grid sep_grid.js]
Si se pasa --grid se valida el bloque generado; si no, se extrae de index.html.
Exit 0 si todo pasa; != 0 con el detalle si algo falla.
"""
import argparse, base64, os, re, struct, sys


def extract_block(text):
    m = re.search(r"var SEP_RESPONSE_GRID = \{(.*?)\};", text, re.S)
    if not m:
        sys.exit("no encontré var SEP_RESPONSE_GRID = {...};")
    return m.group(1)


def parse_block(block_text):
    """Devuelve (meta, floats) donde meta es un dict con los campos del bloque
    y floats es el array Float32 decodificado.

    El bloque no es JSON (claves sin comillas), asi que se convierte a una
    representacion Python con ast.literal_eval (seguro, no ejecuta codigo):
    se anaden comillas a las claves `ident:` y se deja el resto igual.
    """
    # extract_block ya devuelve SOLO el cuerpo (sin las llaves exterior); se
    # reenvuelve en {} para que la primera clave quede precedida de '{' y el
    # regex de conversion la capture (si no, la primera clave del objeto se
    # queda sin comillas y ast.literal_eval falla).
    body = "{" + block_text.strip() + "}"
    # Las claves de objeto son identificadores seguidos de ':'. Anadir comillas
    # solo cuando la clave no esta ya entre comillas.
    def fix_key(m):
        pre, key = m.group(1), m.group(2)
        return '%s"%s":' % (pre, key)
    body = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", fix_key, body)
    import ast
    try:
        obj = ast.literal_eval(body)
    except (ValueError, SyntaxError) as e:
        sys.exit("bloque SEP_RESPONSE_GRID no es parseable: %s" % e)
    data_b64 = obj.get("data", "")
    raw = base64.b64decode(data_b64)
    floats = struct.unpack("<%df" % (len(raw) // 4), raw)
    return obj, floats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "index.html"), help="ruta a index.html (por defecto, la raiz del repo)")
    ap.add_argument("--grid", help="si se da, validar este bloque JS en vez de extraerlo de index.html")
    args = ap.parse_args()

    if args.grid:
        text = open(args.grid).read()
        meta, floats = parse_block(extract_block(text))
    else:
        html = open(args.index).read()
        meta, floats = parse_block(extract_block(html))

    # --- dimensiones y version ---
    e = meta.get("e") or []
    rc = meta.get("rc") or []
    alt = meta.get("alt") or []
    q = meta.get("q") or []
    version = meta.get("model_version") or ""
    n_e, n_rc, n_alt, n_q = len(e), len(rc), len(alt), len(q)
    if (n_e, n_rc, n_alt, n_q) != (53, 73, 11, 1):
        sys.exit("dimensiones %dx%dx%dx%d (esperado 53x73x11x1)"
                 % (n_e, n_rc, n_alt, n_q))
    if version != "sep-1":
        sys.exit("model_version %r (esperado 'sep-1')" % version)
    if q != ["D2"]:
        sys.exit("magnitud %r (esperado ['D2'])" % q)

    # --- ejes ---
    if not all(e[i] < e[i + 1] for i in range(n_e - 1)):
        sys.exit("eje de energia no creciente")
    if not (e[0] >= 0.049 and e[-1] <= 20.5):
        sys.exit("eje de energia fuera del dominio 50 MeV..20 GeV: %g..%g"
                 % (e[0], e[-1]))
    if rc != [round(0.25 * i, 2) for i in range(73)]:
        sys.exit("eje Rc no es 0..18 cada 0.25")
    if alt != [8.0 + 0.5 * i for i in range(11)]:
        sys.exit("eje alt no es 8..13 cada 0.5")

    expected = n_e * n_rc * n_alt
    if len(floats) != expected:
        sys.exit("%d floats (esperado %d = 53x73x11)" % (len(floats), expected))

    # --- NaN / negativos ---
    n_nan = sum(1 for v in floats if v != v)
    n_neg = sum(1 for v in floats if v < 0)
    if n_nan:
        sys.exit("%d NaN en el kernel" % n_nan)
    if n_neg:
        sys.exit("%d negativos en el kernel" % n_neg)

    # --- monotonía esperada (por columna E, misma posicion) ---
    # Orden: E-major -> Rc -> alt. Para una columna fija j, el bloque de
    # n_rc*n_alt va rc-major -> alt.
    bad = 0
    n_alt_good = n_alt_bad = 0
    for j in range(n_e):
        base = j * n_rc * n_alt
        for ri in range(n_rc):
            slice_alt = [floats[base + ri * n_alt + ai] for ai in range(n_alt)]
            # mas altitud -> mas o igual dosis
            for ai in range(n_alt - 1):
                if slice_alt[ai + 1] < slice_alt[ai]:
                    # tolerancia: ruido de CARI en la cola (~0.1 %) o punto
                    # geomagneticamente nulo (0) puede dar un escalon tiny
                    if slice_alt[ai] > 0 and \
                       (slice_alt[ai] - slice_alt[ai + 1]) > 0.01 * slice_alt[ai]:
                        bad += 1
            # mas Rc -> menos o igual dosis (por columna alt)
        for ai in range(n_alt):
            slice_rc = [floats[base + ri * n_alt + ai] for ri in range(n_rc)]
            for ri in range(n_rc - 1):
                if slice_rc[ri + 1] > slice_rc[ri]:
                    if slice_rc[ri] > 0 and \
                       (slice_rc[ri + 1] - slice_rc[ri]) > 0.01 * slice_rc[ri]:
                        bad += 1
    if bad:
        sys.exit("%d violaciones de monotonia (>1 %%)" % bad)

    n_zero = sum(1 for v in floats if v == 0)
    print("CHECK SEP GRID OK: %dx%dx%dx%d, version %s, %d zeros, monotonia OK"
          % (n_e, n_rc, n_alt, n_q, version, n_zero))


if __name__ == "__main__":
    main()
