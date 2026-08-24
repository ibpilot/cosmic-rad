#!/usr/bin/env bash
# Prueba de humo del pipeline completo con un solo nivel de HP y todas las
# altitudes del eje. No toca index.html. Uso:  tools/smoke_grid.sh /ruta/a/CARI_7A_DVD
set -euo pipefail
CARI="${1:?ruta a CARI_7A_DVD}"
WORK="$(mktemp -d)"
echo "workdir: $WORK"

python3 tools/cari7_make_input.py --hp 300 --cutoffs "$CARI/CUTOFFS" \
  --cari-ini "$CARI/CARI.INI" --work "$WORK"

N=$(grep -c '^[NS],' "$WORK/grid_hp300.loc")
echo "puntos en el .LOC: $N"
[ "$N" -gt 500 ] || { echo "FALLO: demasiados pocos puntos"; exit 1; }
awk 'length > 66 { print "FALLO: linea de "length" chars"; exit 1 }' "$WORK/grid_hp300.loc"

cp "$WORK/grid_hp300.loc" "$CARI/SMOKE.LOC"
printf '0000/00/00\n 0 \n 0 \n 2 \nSMOKE.LOC\n' > "$CARI/DEFAULT.INP"
python3 - "$CARI/CARI.INI" <<'PY'
import sys
p = sys.argv[1]
s = open(p, errors="replace").read()
if "MENUS     = YES" in s:
    open(p, "w").write(s.replace("MENUS     = YES", "MENUS     = NO!"))
PY

T0=$(date +%s)
( cd "$CARI" && WINEPREFIX=~/.wine-cari7a WINEDEBUG=-all \
  "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/CrossOver-Hosted Application/wineloader" \
  cari7a420.exe >/dev/null 2>&1 )
T1=$(date +%s)
S=$((T1 - T0))
X=$(awk -v s="$S" -v n="$N" 'BEGIN { printf "%.3f", s / n }')
echo "RITMO: $N puntos en $S segundos = $X s/punto"

python3 tools/cari7_parse_ans.py --ans "$CARI/SMOKE.ANS" --hp 300 --out "$WORK/rates.csv"
head -3 "$WORK/rates.csv"

python3 - "$WORK/rates.csv" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))[1:]
rc = sorted(float(r[0]) for r in rows)
print("Rc de %.2f a %.2f GV en %d filas" % (rc[0], rc[-1], len(rows)))
assert rc[0] < 0.5, "el barrido no llega a rigidez baja"
assert rc[-1] > 17.0, "el barrido no llega al maximo global (17.64)"
# La dosis debe caer al subir Rc, a altitud fija.
a11 = sorted((float(r[0]), float(r[3])) for r in rows if abs(float(r[1]) - 11.0) < 1e-6)
assert a11[0][1] > a11[-1][1] * 3, "la curva no decrece como deberia"
print("curva a 11 km: %.3f uSv/h a Rc=%.2f  ->  %.3f a Rc=%.2f"
      % (a11[0][1], a11[0][0], a11[-1][1], a11[-1][0]))
PY
echo "SMOKE OK"
