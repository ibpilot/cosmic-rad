#!/usr/bin/env python3
"""Validacion hold-out: compara la rejilla embebida en index.html contra
CARI-7A en puntos que NO intervinieron en construirla.

Dos modos:
  --emit-loc holdout.loc      genera N puntos (lat, lon, alt, fecha) al azar
  --ans holdout.ANS           compara la salida de CARI-7A contra index.html

El criterio de aceptacion es el error relativo maximo. Sin esta prueba no
sabemos si dosis = f(Rc, alt, HP) reproduce al programa en puntos arbitrarios.
"""
import argparse, json, random, re, subprocess, sys, tempfile, os

# Fechas de HP_DATES: son las mismas que usa el pipeline, asi que el HP de cada
# punto es exactamente uno de los nodos del eje y no se mezcla el error de
# interpolar en HP con el que queremos medir. Cubren epocas distintas a proposito
# (1958-2007), que es justo lo que el diseno afirma que da igual.
FECHAS = ["2007/06/00", "1994/11/00", "1963/03/00", "1992/11/00", "1980/05/00",
          "2003/09/00", "1969/06/00", "1958/09/00", "1960/01/00", "1990/07/00"]


def emit_loc(path, n, seed):
    rnd = random.Random(seed)
    with open(path, "w") as f:
        f.write("C, hold-out: puntos aleatorios no usados para construir la rejilla\n")
        f.write("START-------------------------------------------------\n")
        for _ in range(n):
            lat = rnd.uniform(-75, 75)
            lon = rnd.uniform(0, 360)
            alt = rnd.uniform(8.0, 13.0)
            date = rnd.choice(FECHAS)
            ns = "N" if lat >= 0 else "S"
            line = "%s, %7.4f, E, %6.2f, K, %6.2f , %s, H0, D2, P0, C4, S0" % (
                ns, abs(lat), lon, alt, date)
            assert len(line) <= 66, line
            f.write(line + "\n")
        f.write("STOP--------------------------------------------------------\n")
    print("escritos %d puntos en %s" % (n, path))


def read_ans(path):
    """-> [(lat, lon, alt_km, rc, rate)]  con el signo de la latitud recuperado."""
    out = []
    for line in open(path, errors="replace"):
        if "ICRP Pub. 103 EFFECTIVE DOSE" not in line:
            continue
        t = [x.strip() for x in line.split(",")]
        if len(t) < 9 or t[3] != "K":
            continue
        out.append((float(t[0]), float(t[1]), float(t[2]), float(t[6]), float(t[8])))
    return out


def read_ans_dates(path):
    """Fechas de las mismas filas que devuelve read_ans, en el mismo orden."""
    out = []
    for line in open(path, errors="replace"):
        if "ICRP Pub. 103 EFFECTIVE DOSE" not in line:
            continue
        t = [x.strip() for x in line.split(",")]
        if len(t) < 9 or t[3] != "K":
            continue
        out.append(t[4])
    return out


def app_rates(index_path, points):
    """Evalua doseRateGrid de index.html sobre los puntos, via node."""
    js = r"""
const fs=require("fs"),vm=require("vm");
const html=fs.readFileSync(process.argv[1],"utf8");
const scripts=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
let app=scripts[scripts.length-1].replace(/ReactDOM\.createRoot\([\s\S]*$/,"");
const ctx={console,atob,Math,JSON,Date,isFinite,parseInt,parseFloat,String,Number,Array,
 Object,Boolean,Error,TypeError,RegExp,Float32Array,Int16Array,Uint8Array,
 fetch:()=>Promise.reject(new Error("x")),navigator:{userAgent:"node"},
 localStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
 React:{createElement:()=>({}),Fragment:"F"},useState:()=>[null,()=>{}],
 useEffect:()=>{},useRef:()=>({current:null}),useCallback:f=>f};
ctx.window=ctx;ctx.globalThis=ctx;vm.createContext(ctx);vm.runInContext(app,ctx);
const pts=JSON.parse(fs.readFileSync(process.argv[2],"utf8"));
console.log(JSON.stringify(pts.map(p=>ctx.doseRateGrid(p[0],p[1],p[2],p[3]))));
"""
    fd, jsp = tempfile.mkstemp(suffix=".js"); os.close(fd)
    open(jsp, "w").write(js)
    fd, pp = tempfile.mkstemp(suffix=".json"); os.close(fd)
    open(pp, "w").write(json.dumps(points))
    try:
        r = subprocess.run(["node", jsp, index_path, pp], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("node fallo: " + r.stderr[-2000:])
        return json.loads(r.stdout)
    finally:
        os.unlink(jsp); os.unlink(pp)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit-loc")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ans")
    ap.add_argument("--index", default="index.html")
    ap.add_argument("--hp-map", help="JSON {fecha: hp_mv}; por defecto, el de HP_DATES")
    ap.add_argument("--max-error", type=float, default=2.0, help="umbral en %%")
    args = ap.parse_args()

    if args.emit_loc:
        emit_loc(args.emit_loc, args.n, args.seed)
        return

    if not args.ans:
        ap.error("hace falta --ans o --emit-loc")

    rows = read_ans(args.ans)
    if not rows:
        sys.exit("el .ANS no traia filas D2 en km")
    # El HP de cada punto lo fija su FECHA, no la rigidez: comparar todo a
    # HP=650 daria un error enorme y falso. Se invierte HP_DATES.
    if args.hp_map:
        hp_by_date = json.load(open(args.hp_map))
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from cari7_make_input import HP_DATES
        hp_by_date = {d: hp for hp, d in HP_DATES.items()}
    dates = read_ans_dates(args.ans)
    faltan = sorted(set(dates) - set(hp_by_date))
    if faltan:
        sys.exit("sin HP para las fechas: %s" % faltan)
    pts = [[lat, lon, alt, hp_by_date[d]]
           for (lat, lon, alt, rc, rate), d in zip(rows, dates)]
    got = app_rates(args.index, pts)

    worst, worst_pt = 0.0, None
    errs = []
    for (lat, lon, alt, rc, ref), g in zip(rows, got):
        if g is None:
            sys.exit("doseRateGrid devolvio null en %s,%s: falta RC_MAP o DOSE_GRID" % (lat, lon))
        e = abs(g - ref) / ref * 100.0
        errs.append(e)
        if e > worst:
            worst, worst_pt = e, (lat, lon, alt, rc, ref, g)
    errs.sort()
    print("hold-out: %d puntos" % len(errs))
    print("  error medio : %.2f %%" % (sum(errs) / len(errs)))
    print("  error p95   : %.2f %%" % errs[int(0.95 * (len(errs) - 1))])
    print("  error maximo: %.2f %%  en lat=%.2f lon=%.2f alt=%.2f Rc=%.2f (CARI %.4f, app %.4f)"
          % ((worst,) + worst_pt))
    if worst > args.max_error:
        sys.exit("FALLO: el error maximo supera el umbral de %.2f %%" % args.max_error)
    print("OK: por debajo del umbral de %.2f %%" % args.max_error)


if __name__ == "__main__":
    main()
