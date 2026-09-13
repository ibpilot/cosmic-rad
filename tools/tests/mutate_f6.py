#!/usr/bin/env python3
"""Fase 6 (Task 6) + SC (comprobacion puntual) mutation harness.

Applies one mutation at a time to index.html, runs bugs_test.js, restores the
byte-exact original, runs the control, and records the outcome.

Usage:
  python3 mutate_f6.py --check      # dry run: verify every old string matches
  python3 mutate_f6.py --run        # execute the matrix (mutant + control each)

REPO se deriva de la ubicacion de ESTE fichero (o de la variable de entorno
REPO) para que correrlo desde un worktree no mute el index.html de otro sitio.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("REPO") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(REPO, "index.html")
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.orig.html")
RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "f6_mutants.json")

# (id, note, old, new, expected_killer)
MUTANTS = []


def add(mid, note, old, new, expected):
    MUTANTS.append((mid, note, old, new, expected))


# ── satKey ───────────────────────────────────────────────────────────────────
add("A", "satKey: quitar [gG]? de la regex",
    '  var m = /^[gG]?(18|19)$/.exec(s);',
    '  var m = /^(18|19)$/.exec(s);',
    "F6 'g18' -> '18' / F6 'G19' -> '19'")
add("B", "satKey: devolver s en vez de m[1]",
    '  return m ? m[1] : undefined;',
    '  return m ? s : undefined;',
    "F6 'g18' -> '18'")
add("C", "satKey: borrar la rama numerica",
    '''  var s;
  if (typeof v === "number" && isFinite(v)) s = String(v);
  else if (typeof v === "string") s = v;
  else return undefined;''',
    '''  var s;
  if (typeof v === "string") s = v;
  else return undefined;''',
    "F6 numero 18 -> '18' / F6 numero 19 -> '19'")

# ── nceiDayAdapt ─────────────────────────────────────────────────────────────
add("D", "nceiDayAdapt: time_step_s !== 300 -> !== 301",
    '  if (file.time_step_s !== 300) return null;',
    '  if (file.time_step_s !== 301) return null;',
    "F6 rechaza time_step_s 60 / F6 devuelve objeto")
add("E", "nceiDayAdapt: t0 + i*300000 -> t0 + i*300",
    '    var smp = { tMs: t0 + i * 300000, sat: sat, int500: integ[i] };',
    '    var smp = { tMs: t0 + i * 300, sat: sat, int500: integ[i] };',
    "F6 cadencia exacta de 300 s")
add("F", "nceiDayAdapt: row[colOf[...]] -> row[j]",
    '      smp[SOLAR_CHANNEL_ORDER[j]] = row[colOf[SOLAR_CHANNEL_ORDER[j]]];',
    '      smp[SOLAR_CHANNEL_ORDER[j]] = row[j];',
    "F6 canales barajados con columnas permutadas -> mismas muestras")
add("G", "nceiDayAdapt: devolver {channels,samples} en vez de null al fallar",
    None,  # scoped: all `return null;` inside nceiDayAdapt
    'return { channels: [], samples: [] };',
    "los rechazos (time_step/n_steps/fila/integral/12 canales/canal/start/sat/no-objeto)")
add("H", "nceiDayAdapt: quitar la comprobacion de longitud de integral",
    '  if (integ === null || integ.length !== n) return null;',
    '  if (integ === null) return null;',
    "F6 rechaza integral corto")
add("I", "nceiDayAdapt: quitar indexOf(c.name) < 0 (EQUIVALENTE)",
    '    if (SOLAR_CHANNEL_ORDER.indexOf(c.name) < 0) return null;\n',
    '',
    "superviviente esperado: longitud+duplicados+completitud lo cubren")
add("J", "nceiDayAdapt: quitar el alias integral_500_keV",
    '''  var integ = Array.isArray(file.integral_500_mev) ? file.integral_500_mev
            : Array.isArray(file.integral_500_keV) ? file.integral_500_keV : null;''',
    '  var integ = Array.isArray(file.integral_500_mev) ? file.integral_500_mev : null;',
    "F6 acepta integral_500_keV como alias")

# ── solarPickSource ──────────────────────────────────────────────────────────
add("K", "solarPickSource: covInt sin comprobar covDiff",
    '    if (covInt.indexOf(days[i]) === -1 || covDiff.indexOf(days[i]) === -1) { todosSwpc = false; break; }',
    '    if (covInt.indexOf(days[i]) === -1) { todosSwpc = false; break; }',
    "F6 SWPC sin diferencial no cuenta como cobertura")
add("L", "solarPickSource: union en vez de interseccion",
    '''      var siguiente = {};
      for (var s in comun) {
        if (Object.prototype.hasOwnProperty.call(comun, s) &&
            Object.prototype.hasOwnProperty.call(aqui, s)) siguiente[s] = true;
      }
      comun = siguiente;''',
    '''      var siguiente = {};
      for (var s in comun) {
        if (Object.prototype.hasOwnProperty.call(comun, s)) siguiente[s] = true;
      }
      for (var s2 in aqui) {
        if (Object.prototype.hasOwnProperty.call(aqui, s2)) siguiente[s2] = true;
      }
      comun = siguiente;''',
    "F6 sin satelite comun -> null")
add("M", "solarPickSource: admitir status !== complete",
    '    if (!e || e.status !== "complete" || !Array.isArray(e.candidates)) return null;',
    '    if (!e || !Array.isArray(e.candidates)) return null;',
    "F6 dia partial -> null")
add("N", "solarPickSource: quitar el criterio de slots del sort",
    '    if (da !== db) return db - da;\n',
    '',
    "F6 desempate por slots elige g18 (576 vs 564) / F6 slots mandan sobre recommended")
add("O", "solarPickSource: todosSwpc -> return null",
    '  if (todosSwpc) return "swpc";',
    '  if (todosSwpc) return null;',
    "F6 SWPC cubre los dos dias -> 'swpc'")
add("P", "solarPickSource: quitar el criterio covInt",
    '    if (covInt.indexOf(days[i]) === -1 || covDiff.indexOf(days[i]) === -1) { todosSwpc = false; break; }',
    '    if (covDiff.indexOf(days[i]) === -1) { todosSwpc = false; break; }',
    "F6 SWPC sin integral no cuenta como cobertura")
add("Q", "solarPickSource: invertir el comparador lexicografico",
    '    return a < b ? -1 : a > b ? 1 : 0;',
    '    return a < b ? 1 : a > b ? -1 : 0;',
    "F6 empate sin recommended -> orden lexicografico ('18')")
add("R", "solarPickSource: quitar la guarda de candidato no-objeto",
    '      if (!c || typeof c !== "object") continue;\n',
    '',
    "F6 entradas deformes -> null sin lanzar")

# ── fetchNceiManifest / fetchNceiDay ─────────────────────────────────────────
add("S", "fetchNceiDay: ignorar sat y coger candidates[0]",
    '      if (c && satKey(c.sat) === sat && typeof c.path === "string") { path = c.path; break; }',
    '      if (c && typeof c.path === "string") { path = c.path; break; }',
    "F6 respeta el satelite pedido")
add("T", "fetchNceiDay: quitar el trato del 404",
    '''    if (!res || res.status === 404) return null;
    if (!res.ok) throw new Error("ncei HTTP " + res.status);''',
    '''    if (!res) return null;
    if (!res.ok) throw new Error("ncei HTTP " + res.status);''',
    "F6 404 -> null")
add("U", "fetchNceiManifest: borrar el catch que resetea la promesa",
    '''    return res.json();
  }).catch(function (err) {
    _nceiManifestPromise = null;
    throw err;
  });''',
    '''    return res.json();
  });''',
    "F6 reintenta tras el fallo (cache no envenenada)")
add("V", "fetchNceiDay: no cachear (borrar _nceiDayCache.set)",
    '  _nceiDayCache.set(key, p);\n',
    '',
    "F6 dia cacheado no repite fetch")
add("W", "fetchNceiDay: path null sigue y hace fetch",
    '  if (path === null) return Promise.resolve(null);\n',
    '',
    "F6 satelite inexistente no llama a fetch")
add("X", "fetchNceiDay: .then(success, failure) en vez de .then().catch()",
    '''  }).catch(function (err) {
    _nceiDayCache.delete(key);
    throw err;
  });''',
    '''  }, function (err) {
    _nceiDayCache.delete(key);
    throw err;
  });''',
    "F6 dia reintenta tras fallo HTTP")
add("Y", "fetchNceiDay: clave de cache solo por day (sin sat)",
    '  var key = day + "|" + sat;',
    '  var key = day;',
    "F6 respeta el satelite pedido")
add("Z", "fetchNceiDay: quitar el catch interior de res.json()",
    '''    return res.json().catch(function (err) {
      if (err && err.name === "SyntaxError") return {};
      throw err;
    });''',
    '    return res.json();',
    "F6 JSON invalido del dia llega como fichero ilegible")

# ── occEvaluate / loadArchiveFor ─────────────────────────────────────────────
add("AA", "occEvaluate: usar solarDayAdapt tambien para NCEI",
    '  if (source !== "swpc") {',
    '  if (false) {',
    "F6 576 muestras de los dos dias NCEI / REGRESION ANTI-MEZCLA")
add("AB", "SOLAR_ARCHIVE_START_MS -> Date.UTC(2025, 8, 12)",
    'var SOLAR_ARCHIVE_START_MS = Date.UTC(2025, 8, 11);',
    'var SOLAR_ARCHIVE_START_MS = Date.UTC(2025, 8, 12);',
    "F6 la ventana empieza el 2025-09-11")
add("AC", "loadArchiveFor: quitar el atajo SWPC (cargar siempre NCEI)",
    '    if (solarPickSource(days, manifest, null) === "swpc") {',
    '    if (false) {',
    "F6 no descarga ncei/manifest.json si SWPC cubre / F6 SWPC cubre la ventana -> source 'swpc'")
add("AD", "occEvaluate: source null -> siempre esperando_datos",
    '''    return permanent
      ? { state: "incompleto", result: null }
      : { state: "esperando_datos", result: null };
  }
  if (source === "swpc") {''',
    '''    return { state: "esperando_datos", result: null };
  }
  if (source === "swpc") {''',
    "F6 ambas fuentes permanentes el mismo dia -> incompleto")
add("AE", "occEvaluate: no ordenar las muestras NCEI",
    '''    samples.sort(function (a, b) { return a.tMs - b.tMs; });
    adapted = { channels: channels || [], samples: samples };''',
    '    adapted = { channels: channels || [], samples: samples };',
    "F6 ordena por tMs aunque el mapa de ventana venga cruzado")
add("AF", "occEvaluate: combinar permanencia con || en vez de &&",
    '      if (swpcPermanent && nceiPermanent) permanent = true;',
    '      if (swpcPermanent || nceiPermanent) permanent = true;',
    "F6 solo SWPC permanente -> esperando_datos / F6 solo NCEI permanente -> esperando_datos")
add("AG", "occEvaluate: fichero NCEI ilegible tratado como rechazo de red",
    '''      var one = nceiDayAdapt(dayMap[days[i]]);
      if (one === null) return { state: "incompleto", result: null };''',
    '''      var one = nceiDayAdapt(dayMap[days[i]]);
      if (one === null) return { state: "noaa_no_disponible", result: null };''',
    "F6 fichero NCEI ilegible -> incompleto")

# ── SC (comprobacion puntual de actividad solar) ─────────────────────────────
add("SC-A", "SolarCheckPanel: quitar la invalidacion al cambiar ruta/FL/fecha/hora",
    '    solarGateRef.current.begin();\n    setCheck(_solarCheckCache.get(cacheKey) || null);\n',
    '',
    "SC5 el panel descarta la respuesta vieja")
add("SC-B", "solarCheckView: eventActive vuelve a heredar el visible del estado",
    '    out.vis = "aviso";\n    out.label = t.occVis_aviso || "";\n',
    '',
    "SC7 evento activo: aviso, no revisada")
add("SC-C", "solarCheckView: admitir un resultado no finito como cifra",
    '    if (r && isFinite(r.lowUsv) && isFinite(r.highUsv) && r.lowUsv >= 0 && r.lowUsv <= r.highUsv) {',
    '    if (r) {',
    "SC7 cifra prometida con NaN -> pendiente, no cero")
add("SC-D", "solarCheckNums: repetir el total en el cero medido",
    '  if (view.totalLowUsv !== null && !view.measuredZero) {',
    '  if (view.totalLowUsv !== null) {',
    "SC10 cero medido: GCR y SEP 0, sin total duplicado")


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_mutation(orig, mid, old, new):
    if mid == "G":
        # Scoped: replace every `return null;` inside nceiDayAdapt.
        start = orig.index("function nceiDayAdapt(file) {")
        end = orig.index("\n}\n", start) + len("\n}\n")
        body = orig[start:end]
        cnt = body.count("return null;")
        assert cnt > 0, "G: no return null found"
        mutated = body.replace("return null;", new)
        return orig[:start] + mutated + orig[end:], cnt
    cnt = orig.count(old)
    assert cnt == 1, "%s: old string count=%d (expected 1)" % (mid, cnt)
    return orig.replace(old, new, 1), cnt


def parse(out):
    fails = re.findall(r"^\s+\u2717 (.+)$", out, re.M)
    m = re.search(r"(TODO VERDE|HAY FALLOS) \u2014 (\d+) pass, (\d+) fail", out)
    if m:
        return {"verdict": m.group(1), "pass": int(m.group(2)), "fail": int(m.group(3)),
                "fails": fails}
    return {"verdict": "ABORTO", "pass": None, "fail": None, "fails": fails}


def run_bugs():
    p = subprocess.run(["node", "tools/tests/bugs_test.js"], cwd=REPO,
                       capture_output=True, text=True, timeout=600)
    res = parse(p.stdout + "\n" + p.stderr)
    if res["verdict"] == "ABORTO" and p.returncode != 0:
        tail = (p.stderr.strip().splitlines() or [""])[-1]
        res["abort_msg"] = tail
    res["exit"] = p.returncode
    return res


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    orig = read(BACKUP) if os.path.exists(BACKUP) else read(INDEX)
    if not os.path.exists(BACKUP):
        write(BACKUP, orig)
    # The live file must equal the backup before we start (or be created from it).
    live = read(INDEX)
    if live != orig:
        print("WARN: index.html differs from backup; refreshing backup")
        write(BACKUP, live)
        orig = live
    print("original sha256:", sha(orig))

    if mode == "--check":
        bad = 0
        for mid, note, old, new, exp in MUTANTS:
            try:
                mutated, cnt = apply_mutation(orig, mid, old, new)
            except AssertionError as e:
                print("  !! %s %s" % (mid, e))
                bad += 1
                continue
            if mutated == orig:
                print("  !! %s mutation did not change the file" % mid)
                bad += 1
                continue
        print("checked %d mutants, %d problems" % (len(MUTANTS), bad))
        return 1 if bad else 0

    control = run_bugs()
    print("control:", control["verdict"], control["pass"], "pass", control["fail"], "fail",
          "exit", control["exit"])
    results = []

    for mid, note, old, new, exp in MUTANTS:
        mutated, cnt = apply_mutation(orig, mid, old, new)
        write(INDEX, mutated)
        mut = run_bugs()
        # restore
        write(INDEX, orig)
        ctrl = run_bugs()
        ok_restore = read(INDEX) == orig and ctrl["verdict"] == "TODO VERDE" and ctrl["fail"] == 0
        rec = {"id": mid, "note": note, "expected": exp,
               "mutant": mut, "restore_green": ok_restore,
               "control": {"verdict": ctrl["verdict"], "pass": ctrl["pass"], "fail": ctrl["fail"]}}
        results.append(rec)
        print("[%s] mutant=%s fail=%s exit=%s | restore_green=%s | killers=%s"
              % (mid, mut["verdict"], mut["fail"], mut["exit"], ok_restore,
                 "; ".join(mut["fails"])[:400]))
        sys.stdout.flush()
        with open(RESULTS, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)

    write(INDEX, orig)
    final_ok = read(INDEX) == orig
    print("final restore byte-exact:", final_ok)
    print("written:", RESULTS)


if __name__ == "__main__":
    sys.exit(main() or 0)
