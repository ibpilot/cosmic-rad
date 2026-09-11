// Tests de la contribucion de dosis de eventos solares (GLE).
const fs = require("fs"), vm = require("vm"), path = require("path");

const REPO = process.env.REPO || path.resolve(__dirname, "..", "..");
const html = fs.readFileSync(path.join(REPO, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let app = scripts[scripts.length - 1].replace(/ReactDOM\.createRoot\([\s\S]*$/, "");

const ctx = {
  console, atob, Math, JSON, Date, isFinite, parseInt, parseFloat, String, Number,
  Array, Object, Boolean, Error, TypeError, RegExp, Float32Array, Int16Array, Uint8Array,
  fetch: () => Promise.reject(new Error("no net in tests")),
  navigator: { userAgent: "node" },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  React: { createElement: () => ({}), Fragment: "Fragment" },
  useState: () => [null, () => {}], useEffect: () => {}, useRef: () => ({ current: null }),
  useCallback: (f) => f,
};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(app, ctx);

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) { pass++; console.log("  ✓ " + name); }
  else { fail++; console.log("  ✗ " + name + (extra !== undefined ? "  → " + extra : "")); }
}

// Tabla de prueba: un evento de 1 h el 2021-10-28 a las 15:45Z.
ctx.GLE_EVENTS = [{n: 73, t0: "2021-10-28T15:45Z", dt: 15, q: "ajustado",
                   p: [[100, 2, 0.01], [100, 2, 0.01], [100, 2, 0.01], [100, 2, 0.01]]}];
ctx.GLE_CAL = {k0: 1.0, beta: 0.0, attKm: 2.0, altRefKm: 10.668, r0Ref: 1.0};

const T_IN = Date.UTC(2021, 9, 28, 16, 0, 0);   // dentro del evento
const T_OUT = Date.UTC(2021, 9, 28, 12, 0, 0);  // antes del evento

console.log("gleForMonth / gleWindow");
ok("encuentra el evento del mes", ctx.gleForMonth("2021-10").length === 1);
ok("mes sin evento devuelve vacio", ctx.gleForMonth("2021-09").length === 0);
ok("ventana activa dentro del evento", ctx.gleWindow(T_IN) !== null);
ok("ventana nula fuera del evento", ctx.gleWindow(T_OUT) === null);
ok("ventana nula con tiempo invalido", ctx.gleWindow(NaN) === null);

console.log("sepRate");
const polar = ctx.sepRate(78, -70, 10.668, T_IN);      // Rc muy baja
const ecuat = ctx.sepRate(0, 0, 10.668, T_IN);         // Rc muy alta
ok("dosis positiva en ruta polar durante el evento", polar > 0, polar);
ok("cero fuera de la ventana", ctx.sepRate(78, -70, 10.668, T_OUT) === 0);
ok("atenuacion geomagnetica: ecuador << polo", ecuat < polar / 50, ecuat + " vs " + polar);
ok("mas altitud, mas dosis",
   ctx.sepRate(78, -70, 12, T_IN) > ctx.sepRate(78, -70, 9, T_IN));
ok("evento sin ajuste no da dosis", (function () {
  const saved = ctx.GLE_EVENTS;
  ctx.GLE_EVENTS = [{n: 73, t0: "2021-10-28T15:45Z", dt: 15, q: "solo evento", p: []}];
  const r = ctx.sepRate(78, -70, 10.668, T_IN);
  ctx.GLE_EVENTS = saved;
  return r === 0;
})());
ok("sin NaN con entradas basura",
   isFinite(ctx.sepRate(NaN, 0, 10.668, T_IN)) && ctx.sepRate(78, -70, NaN, T_IN) === 0);

const T_AFTER = Date.UTC(2021, 9, 28, 18, 0, 0);  // 1 h despues del final

ok("ventana nula despues de que acabe el evento", ctx.gleWindow(T_AFTER) === null);
ok("cero despues del evento", ctx.sepRate(78, -70, 10.668, T_AFTER) === 0);
ok("el perfil temporal se sigue paso a paso", (function () {
  const saved = ctx.GLE_EVENTS;
  ctx.GLE_EVENTS = [{n: 73, t0: "2021-10-28T15:45Z", dt: 15, q: "ajustado",
                     p: [[100, 2, 0.01], [50, 2, 0.01], [25, 2, 0.01], [10, 2, 0.01]]}];
  const s0 = ctx.sepRate(78, -70, 10.668, Date.UTC(2021, 9, 28, 15, 50, 0));
  const s2 = ctx.sepRate(78, -70, 10.668, Date.UTC(2021, 9, 28, 16, 20, 0));
  ctx.GLE_EVENTS = saved;
  return s0 > 0 && Math.abs(s2 / s0 - 0.25) < 1e-9;
})());

console.log("aviso GLE sin perfil");
// GLE sin perfil NMDB (p vacio): no suma dosis, pero un vuelo que lo atraviesa
// debe avisarse igualmente (sin cifra). Ventana asumida de 6 h.
const SOLO = {n: 74, t0: "2024-05-11T01:30Z", dt: 15, q: "solo evento", p: []};
const SOLO_EPOCH = {n: 70, t0: "1970-01-01T00:00Z", dt: 15, q: "solo evento", p: []};
const AJUST = {n: 73, t0: "2021-10-28T15:45Z", dt: 15, q: "ajustado", p: [[100, 2, 0.01]]};
const E0 = Date.UTC(2024, 4, 11, 1, 30);
const A0 = Date.UTC(2021, 9, 28, 15, 45);
// Track sin hora de 2 puntos: ~1600 km => ~2 h a 830 km/h.
const NF_TRACK = [[null, 70, -30, 10.668], [null, 60, 0, 10.668]];
function withGle(list, fn) {
  const saved = ctx.GLE_EVENTS;
  ctx.GLE_EVENTS = list;
  try { return fn(); } finally { ctx.GLE_EVENTS = saved; }
}
ok("solape que arranca antes del GLE sin perfil devuelve el evento", withGle([SOLO], function () {
  const ev = ctx.gleUnprofiledOverlap(E0 - 3600000, E0 + 60000);
  return !!ev && ev.n === 74;
}));
ok("borde a 6 h exclusivo: pasada la ventana no hay aviso", withGle([SOLO], function () {
  return ctx.gleUnprofiledOverlap(E0 + 6 * 3600000, E0 + 7 * 3600000) === null;
}));
ok("un GLE con perfil no genera aviso sin cifra", withGle([AJUST], function () {
  return ctx.gleUnprofiledOverlap(A0 - 3600000, A0 + 3600000) === null;
}));
ok("track que atraviesa el GLE sin perfil -> aviso y cero SEP", withGle([SOLO], function () {
  const r = ctx.calcTrack(NF_TRACK, 650, null, E0 - 3600000);
  return r.gleNoFigure === 74 && r.doseSepUsv === 0;
}));
ok("track 12 h despues del GLE sin perfil -> sin aviso", withGle([SOLO], function () {
  return ctx.calcTrack(NF_TRACK, 650, null, E0 + 12 * 3600000).gleNoFigure === null;
}));
ok("sin fecha de salida no se avisa", withGle([SOLO, SOLO_EPOCH], function () {
  return ctx.calcTrack(NF_TRACK, 650, null, null).gleNoFigure === null;
}));
ok("las plantillas ES y EN llevan el hueco {n}",
   String(ctx.LANG.es.gleNoFigure).indexOf("{n}") !== -1 &&
   String(ctx.LANG.en.gleNoFigure).indexOf("{n}") !== -1);
ok("vuelo sin track que atraviesa el GLE sin perfil -> aviso", withGle([SOLO], function () {
  const r = ctx.flightCalc({orig: "MAD", dest: "JFK", legs: 1, flIdx: 1,
                            depDate: "2024-05-11", depTime: "00:30"}, 650);
  return r && r.gleNoFigure === 74;
}));

console.log("integracion en calcTrack");
// Track polar de 1 h: [tMin, lat, lon, altKm]
const TRACK = [[0, 78, -70, 10.668], [30, 78, -60, 10.668], [60, 78, -50, 10.668]];
const sinFecha = ctx.calcTrack(TRACK, 650, null, null);
const conFecha = ctx.calcTrack(TRACK, 650, null, T_IN);
const fuera = ctx.calcTrack(TRACK, 650, null, T_OUT);

ok("sin fecha no hay SEP", sinFecha.doseSepUsv === 0);
ok("sin fecha la dosis es la de siempre (no-regresion)",
   sinFecha.doseUsv === fuera.doseUsv, sinFecha.doseUsv + " vs " + fuera.doseUsv);
ok("fuera de ventana no hay SEP", fuera.doseSepUsv === 0);
ok("dentro de ventana hay SEP", conFecha.doseSepUsv > 0, conFecha.doseSepUsv);
ok("el total suma GCR + SEP",
   Math.abs(conFecha.doseUsv - (fuera.doseUsv + conFecha.doseSepUsv)) < 1e-6);
ok("ruta ecuatorial durante el GLE apenas suma", (function () {
  const eq = ctx.calcTrack([[0, 0, 0, 10.668], [60, 0, 10, 10.668]], 650, null, T_IN);
  return eq.doseSepUsv < conFecha.doseSepUsv / 50;
})());
ok("track que entra a mitad solo suma la parte solapada", (function () {
  // El evento arranca a las 15:45Z y dura 1 h; salida a las 15:15Z, 1 h de vuelo.
  const mitad = ctx.calcTrack(TRACK, 650, null, Date.UTC(2021, 9, 28, 15, 15, 0));
  return mitad.doseSepUsv > 0 && mitad.doseSepUsv < conFecha.doseSepUsv;
})());
ok("el SEP se integra sobre el solape exacto con la ventana", (function () {
  // 1 h quieto en el mismo punto polar: la tasa SEP es constante, asi que la
  // dosis debe ser proporcional al tiempo realmente dentro de la ventana, no a
  // la tasa de un extremo aplicada al tramo entero.
  const quieto = [[0, 78, -70, 10.668], [60, 78, -70, 10.668]];
  const ref = ctx.calcTrack(quieto, 650, null, Date.UTC(2021, 9, 28, 15, 45, 0)); // 60 min dentro
  const m30 = ctx.calcTrack(quieto, 650, null, Date.UTC(2021, 9, 28, 15, 15, 0)); // solapa 30 min
  const m45 = ctx.calcTrack(quieto, 650, null, Date.UTC(2021, 9, 28, 16, 0, 0));  // solapa 45 min
  const m0 = ctx.calcTrack([[0, 78, -70, 10.668], [45, 78, -70, 10.668]], 650, null,
                           Date.UTC(2021, 9, 28, 15, 0, 0)); // acaba justo al empezar el evento
  return ref.doseSepUsv > 0 &&
    Math.abs(m30.doseSepUsv / ref.doseSepUsv - 0.5) < 1e-9 &&
    Math.abs(m45.doseSepUsv / ref.doseSepUsv - 0.75) < 1e-9 &&
    m0.doseSepUsv === 0;
})());
ok("el SEP sigue los pasos de un perfil largo", (function () {
  const saved = ctx.GLE_EVENTS;
  ctx.GLE_EVENTS = [{n: 73, t0: "2021-10-28T15:45Z", dt: 15, q: "ajustado",
                     p: [[100, 2, 0.01], [50, 2, 0.01], [25, 2, 0.01], [10, 2, 0.01]]}];
  const largo = ctx.calcTrack([[0, 78, -70, 10.668], [60, 78, -70, 10.668]],
                              650, null, Date.UTC(2021, 9, 28, 15, 45, 0));
  ctx.GLE_EVENTS = saved;
  // Cuatro tasas constantes durante 15 min: 0.25 * (100+50+25+10).
  return Math.abs(largo.doseSepUsv - 46.25) < 1e-9;
})());

console.log("depMsOf");
ok("fecha y hora validas", isFinite(ctx.depMsOf({depDate: "2021-10-28", depTime: "16:00"})));
ok("fecha sin hora es null", ctx.depMsOf({depDate: "2021-10-28"}) === null);
ok("sin fecha es null", ctx.depMsOf({}) === null);
ok("fecha basura es null", ctx.depMsOf({depDate: "no", depTime: "16:00"}) === null);
ok("fecha calendario imposible es null", ctx.depMsOf({depDate: "2021-02-31", depTime: "16:00"}) === null);
ok("hora basura es null", ctx.depMsOf({depDate: "2021-10-28", depTime: "99:99"}) === null);
ok("no propaga NaN a la dosis", (function () {
  const r = ctx.calcTrack(TRACK, 650, null, ctx.depMsOf({depDate: "no", depTime: "x"}));
  return isFinite(r.doseUsv) && r.doseSepUsv === 0;
})());

console.log("persistencia de fecha/hora");
ok("serializeFlight preserva fecha y hora", (function () {
  const s = ctx.serializeFlight({orig: "MAD", dest: "JFK", legs: 1, flIdx: 1,
                                 depDate: "2021-10-28", depTime: "16:00"});
  return s.depDate === "2021-10-28" && s.depTime === "16:00";
})());
ok("hydrateFlight preserva fecha y hora", (function () {
  const h = ctx.hydrateFlight({orig: "MAD", dest: "JFK", legs: 1, flIdx: 1,
                               depDate: "2021-10-28", depTime: "16:00"});
  return h.depDate === "2021-10-28" && h.depTime === "16:00";
})());
ok("backup v1 sin campos carga igual", (function () {
  const h = ctx.hydrateFlight({orig: "MAD", dest: "JFK", legs: 1, flIdx: 1});
  return h.depDate === undefined && h.depTime === undefined && h.orig === "MAD";
})());
ok("ida y vuelta sin perdida", (function () {
  const f = {orig: "MAD", dest: "JFK", legs: 2, flIdx: 3,
             depDate: "2024-05-11", depTime: "01:45"};
  const r = ctx.serializeFlight(ctx.hydrateFlight(f));
  return r.depDate === f.depDate && r.depTime === f.depTime && r.legs === 2;
})());
ok("fecha no string se descarta al hidratar",
   ctx.hydrateFlight({orig: "MAD", depDate: {x: 1}}).depDate === undefined);
ok("hora no string se descarta al hidratar",
   ctx.hydrateFlight({orig: "MAD", depTime: 16}).depTime === undefined);

console.log("semaforo SWPC");
const SWPC_OK = [
  {time_tag: "2024-05-11T00:00Z", energy: ">=10 MeV", flux: 120.5},
  {time_tag: "2024-05-11T00:05Z", energy: ">=10 MeV", flux: 210.0},
  {time_tag: "2024-05-11T00:05Z", energy: ">=100 MeV", flux: 3.0}
];
ok("coge el ultimo >=10 MeV", (function () {
  const r = ctx.parseSwpcProtons(SWPC_OK);
  return r && Math.abs(r.fluxPfu - 210.0) < 1e-9 && r.timeIso === "2024-05-11T00:05Z";
})());
ok("json vacio es null", ctx.parseSwpcProtons([]) === null);
ok("json corrupto es null", ctx.parseSwpcProtons("no soy json") === null);
ok("null es null", ctx.parseSwpcProtons(null) === null);
ok("sin canal de 10 MeV es null",
   ctx.parseSwpcProtons([{time_tag: "x", energy: ">=100 MeV", flux: 1}]) === null);
ok("fondo tranquilo no pinta nada", ctx.swpcLevel(0.2) === "");
ok("umbral S1 en 10 pfu", ctx.swpcLevel(10) === "S1");
ok("S2 en 100 pfu", ctx.swpcLevel(100) === "S2");
ok("S3 en 1000 pfu", ctx.swpcLevel(1000) === "S3");
ok("S4 en 10000 pfu", ctx.swpcLevel(10000) === "S4");
ok("S5 en 100000 pfu", ctx.swpcLevel(100000) === "S5");
ok("flujo invalido no pinta nada", ctx.swpcLevel(NaN) === "");

console.log("swpcCardState");
ok("sin datos (null) es nodata", ctx.swpcCardState(null).kind === "nodata");
ok("flujo no finito es nodata",
   ctx.swpcCardState({fluxPfu: Infinity, fetchedMs: 0}).kind === "nodata");
ok("tranquilo (<10 pfu) es S0 quiet", (function () {
  const st = ctx.swpcCardState({fluxPfu: 0.76, fetchedMs: 0});
  return st.level === "S0" && st.quiet === true && st.kind === "quiet";
})());
ok("tormenta (>=10 pfu) da su nivel", (function () {
  const st = ctx.swpcCardState({fluxPfu: 5000, fetchedMs: 0});
  return st.level === "S3" && st.quiet === false && st.kind === "storm";
})());

console.log("swpcAgeText");
ok("90 s es 1 min", ctx.swpcAgeText(90000) === "1 min");
ok("119999 ms es 1 min (piso, no redondeo)", ctx.swpcAgeText(119999) === "1 min");
ok("marca de tiempo futura es cadena vacia", ctx.swpcAgeText(-1000) === "");
ok("60 min justos es 1 h", ctx.swpcAgeText(3600000) === "1 h");
ok("100 min es 1 h (piso, no redondeo)", ctx.swpcAgeText(6000000) === "1 h");

console.log("swpcAgeLabel");
ok("ES compone hace delante del valor", ctx.swpcAgeLabel("hace {age}", 90000) === "hace 1 min");
ok("EN compone ago detras del valor", ctx.swpcAgeLabel("{age} ago", 90000) === "1 min ago");
ok("marca de tiempo futura compone cadena vacia", ctx.swpcAgeLabel("hace {age}", -1000) === "");
ok("las plantillas ES y EN llevan el hueco {age}", (function () {
  const es = ctx.LANG.es.gleRtAge, en = ctx.LANG.en.gleRtAge;
  return String(es).indexOf("{age}") !== -1 && String(en).indexOf("{age}") !== -1;
})());

// === T7/T8: modelo SEP (fuente canonica tools/sep_model_runtime.js) =========
const { SepModel } = require("../sep_model_runtime.js");

const FIX_DIR = path.join(REPO, "tools", "fixtures", "goes");
const CH_NAMES = ["P1", "P2A", "P2B", "P3", "P4", "P5", "P6", "P7",
                  "P8A", "P8B", "P8C", "P9", "P10"];
const P8PLUS = ["P8A", "P8B", "P8C", "P9", "P10"];
const P910 = ["P9", "P10"];
const STEP_MS = 5 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const KEV_PER_GEV = 1e6;

function fixture(name) { return JSON.parse(fs.readFileSync(path.join(FIX_DIR, name), "utf8")); }
function channelMeta(name) {
  return fixture(name).channels.map((c) => ({ name: c.name, lo_keV: c.lo_keV, hi_keV: c.hi_keV }));
}
function median(values) {
  const v = values.slice().sort((a, b) => a - b), h = v.length >> 1;
  return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2;
}
// Bandas ponderadas por ΔE calculadas con los metadatos del fixture. Es la
// referencia INDEPENDIENTE del helper de produccion.
function channelWidths(channels) {
  const w = {};
  for (const c of channels) w[c.name] = c.hi_keV - c.lo_keV;
  return w;
}
function bandSeries(name, band, from, to, channels, weighted) {
  const d = fixture(name), widths = channelWidths(channels);
  const idx = band.map((n) => CH_NAMES.indexOf(n)), out = [];
  for (let i = from; i < to; i++) {
    let sum = 0;
    for (const j of idx) sum += d.diff[i][j] * (weighted ? widths[CH_NAMES[j]] : 1);
    out.push(sum);
  }
  return out;
}
function bandStats(name, band, channels) {
  const values = bandSeries(name, band, 144, 288, channels, true);
  const center = median(values);
  const sigma = 1.4826 * median(values.map((v) => Math.abs(v - center)));
  return { center, sigma, threshold: center + 3 * sigma };
}
function bandRun(name, band, threshold, channels) {
  const values = bandSeries(name, band, 0, 288, channels, true);
  let best = 0, current = 0;
  for (const v of values) { if (v > threshold) { current++; if (current > best) best = current; } else current = 0; }
  return best;
}
function fixtureSamples(name, baseMs) {
  const d = fixture(name), out = [];
  for (let i = 0; i < d.n_steps; i++) {
    const s = { tMs: baseMs + i * STEP_MS, sat: d.sat, int500: d.integral_500_keV[i] };
    for (let c = 0; c < CH_NAMES.length; c++) s[CH_NAMES[c]] = d.diff[i][c];
    out.push(s);
  }
  return out;
}
function stitch(baseName, detectName) {
  const base = fixtureSamples(baseName, 0);
  return { startMs: base.length * STEP_MS, channels: channelMeta(baseName),
           samples: base.concat(fixtureSamples(detectName, base.length * STEP_MS)) };
}
function quietSeries(baseSize, detectSize) {
  const d = fixture("g18_2024-05-08.json"), out = [];
  for (let i = 0; i < baseSize + detectSize; i++) {
    const row = i % d.n_steps;
    const s = { tMs: i * STEP_MS, sat: d.sat, int500: d.integral_500_keV[row] };
    for (let c = 0; c < CH_NAMES.length; c++) s[CH_NAMES[c]] = d.diff[row][c];
    out.push(s);
  }
  return { startMs: baseSize * STEP_MS, channels: channelMeta("g18_2024-05-08.json"), samples: out };
}
function injectExcess(series, indices, values) {
  for (const i of indices) Object.assign(series.samples[i], values);
}
const EXCESS = { P8A: 1e-3, P8B: 1e-3, P8C: 1e-3, P9: 1e-3, P10: 1e-3, int500: 1 };
function nullChannel(series, name, count) {
  for (let i = 144; i < 144 + count; i++) series.samples[i][name] = null;
}
function nullChannelRange(series, name, start, count) {
  for (let i = start; i < start + count; i++) series.samples[i][name] = null;
}
// Muestra con las medianas del baseline mas el promedio analitico de un
// espectro. Sirve para componer detect() -> ensemble() sin inventar un baseline.
function sampleFromMedians(channels, medians, spectrum) {
  const s = { int500: medians.int500 };
  for (const c of channels) {
    const lo = c.lo_keV / KEV_PER_GEV, hi = c.hi_keV / KEV_PER_GEV;
    s[c.name] = medians[c.name] + binAverage(spectrum, lo, hi) / KEV_PER_GEV;
  }
  return s;
}

console.log("T7 deteccion SEP — eventos y controles reales");
ok("GLE73 real detectado", (function () {
  const r = SepModel.detect(stitch("g16_2021-10-27.json", "g16_2021-10-28.json"));
  return r.state === "detectado" && r.onsetMs >= r.baseline.endMs;
})());
ok("GLE74 real detectado (baseline del dia previo tranquilo)", (function () {
  return SepModel.detect(stitch("g18_2024-05-10.json", "g18_2024-05-11.json")).state === "detectado";
})());
ok("control intenso 2024-06-08 detectado", (function () {
  return SepModel.detect(stitch("g18_2024-05-08.json", "g18_2024-06-08.json")).state === "detectado";
})());
ok("control intenso 2024-10-09 detectado", (function () {
  return SepModel.detect(stitch("g18_2024-05-08.json", "g18_2024-10-09.json")).state === "detectado";
})());
ok("control blando 2024-03-23 detectado", (function () {
  return SepModel.detect(stitch("g18_2024-05-08.json", "g18_2024-03-23.json")).state === "detectado";
})());
ok("el integral >=500 no es requisito: 2024-10-09 nunca lo cruza", (function () {
  const r = SepModel.detect(stitch("g18_2024-05-08.json", "g18_2024-10-09.json"));
  const d = fixture("g18_2024-10-09.json");
  return r.state === "detectado" && Math.max.apply(null, d.integral_500_keV) < r.thresholds.int500;
})());
ok("GLE73 si cruza el integral (disparador duro)", (function () {
  const r = SepModel.detect(stitch("g16_2021-10-27.json", "g16_2021-10-28.json"));
  const d = fixture("g16_2021-10-28.json");
  return r.state === "detectado" && Math.max.apply(null, d.integral_500_keV) > r.thresholds.int500;
})());

console.log("T7 deteccion SEP — dias tranquilos y marginales");
const QUIET = [["g16_2021-10-27.json", "g16_2021-10-27.json"],
               ["g18_2024-05-08.json", "g18_2024-05-08.json"],
               ["g18_2024-05-09.json", "g18_2024-05-09.json"],
               ["g18_2024-05-10.json", "g18_2024-05-10.json"],
               ["g16_2022-06-15.json", "g16_2022-06-15.json"],
               ["g16_2023-01-15.json", "g16_2023-01-15.json"]];
for (const pair of QUIET) {
  ok("tranquilo " + pair[1].replace(".json", "") + " no detectado", (function () {
    return SepModel.detect(stitch(pair[0], pair[1])).state === "sin_senal";
  })());
}
ok("marginal 2024-09-01 no detectado", SepModel.detect(stitch("g18_2024-05-08.json", "g18_2024-09-01.json")).state === "sin_senal");
ok("marginal 2024-12-08 no detectado", SepModel.detect(stitch("g18_2024-05-08.json", "g18_2024-12-08.json")).state === "sin_senal");

console.log("T7 deteccion SEP — linea base");
ok("la linea base es [inicio-12h, inicio) y no el evento", (function () {
  const r = SepModel.detect(stitch("g18_2024-05-10.json", "g18_2024-05-11.json"));
  return r.baseline.endMs === r.baseline.startMs + 12 * HOUR_MS && r.baseline.medians.P8A < 1e-5;
})());
ok("las bandas se ponderan por ΔE y coinciden con el calculo independiente", (function () {
  const channels = channelMeta("g18_2024-05-10.json");
  const r = SepModel.detect(stitch("g18_2024-05-10.json", "g18_2024-05-11.json"));
  const expected = bandStats("g18_2024-05-10.json", P8PLUS, channels);
  return Math.abs(r.baseline.median.p8plus / expected.center - 1) < 1e-9 &&
         Math.abs(r.baseline.sigma.p8plus / expected.sigma - 1) < 1e-9 &&
         Math.abs(r.thresholds.p8plus / expected.threshold - 1) < 1e-9;
})());
ok("ponderar por ΔE cambia el resultado respecto a sumar densidades", (function () {
  const channels = channelMeta("g18_2024-05-10.json");
  const weighted = median(bandSeries("g18_2024-05-10.json", P8PLUS, 144, 288, channels, true));
  const raw = median(bandSeries("g18_2024-05-10.json", P8PLUS, 144, 288, channels, false));
  return Math.abs(weighted / raw - 1) > 0.5;
})());
ok("sigma = 1.4826 * MAD y umbral = mediana + 3 sigma", (function () {
  const channels = channelMeta("g16_2021-10-27.json");
  const r = SepModel.detect(stitch("g16_2021-10-27.json", "g16_2021-10-28.json"));
  const values = bandSeries("g16_2021-10-27.json", P8PLUS, 144, 288, channels, true);
  const center = median(values);
  const mad = median(values.map((v) => Math.abs(v - center)));
  return Math.abs(r.baseline.median.p8plus - center) < 1e-15 &&
         Math.abs(r.baseline.sigma.p8plus - 1.4826 * mad) < 1e-15 &&
         Math.abs(r.thresholds.p8plus - (center + 3 * 1.4826 * mad)) < 1e-15;
})());
ok("P9+P10 tiene MAD nulo en dia tranquilo y P8+ no", (function () {
  const r = SepModel.detect(stitch("g16_2021-10-27.json", "g16_2021-10-28.json"));
  return r.baseline.sigma.p9p10 === 0 && r.baseline.sigma.p8plus > 0;
})());

console.log("T7 deteccion SEP — cobertura estricta");
ok("30% de huecos en un canal -> pendiente", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  nullChannel(s, "P8A", 44);
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.baseline === undefined;
})());
ok("P1-P7 ausentes durante todo el baseline -> pendiente", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (const name of ["P1", "P2A", "P2B", "P3", "P4", "P5", "P6", "P7"]) nullChannel(s, name, 144);
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "baseline_incompleta";
})());
ok("canales incompletos (solo el integral) -> pendiente", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (const name of CH_NAMES.slice(0, 12)) nullChannel(s, name, 144);
  return SepModel.detect(s).state === "pendiente";
})());
ok("cambio de satelite en la linea base -> pendiente", (function () {
  const s = stitch("g18_2024-05-10.json", "g18_2024-05-11.json");
  s.samples[200].sat = "g16";
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "cambio_satelite";
})());
ok("50% de slots del baseline sin satelite -> pendiente", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (let i = 144; i < 288; i += 2) s.samples[i].sat = "";
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "satelite_ausente";
})());
ok("frontera 116/144 slots validos -> se puede medir", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  nullChannel(s, "P8A", 28);
  const r = SepModel.detect(s);
  return r.state !== "pendiente" && r.baseline.coverage.P8A === 116;
})());
ok("frontera 115/144 slots validos -> pendiente", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  nullChannel(s, "P8A", 29);
  return SepModel.detect(s).state === "pendiente";
})());
ok("cobertura conjunta: 28 nulos disjuntos por canal dejan P8+ casi vacio -> pendiente", (function () {
  // Cada canal individual conserva 116 slots, pero los bloques de nulos son
  // disjuntos dentro de P8+, asi que los slots con P8+ COMPLETO son solo 4.
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  const off = 144;
  nullChannelRange(s, "P8A", off + 0, 28);
  nullChannelRange(s, "P8B", off + 28, 28);
  nullChannelRange(s, "P8C", off + 56, 28);
  nullChannelRange(s, "P9", off + 84, 28);
  nullChannelRange(s, "P10", off + 112, 28);
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "baseline_conjunta_incompleta";
})());
ok("cobertura conjunta: bloques solapados dejan P8+ y P9+P10 completos", (function () {
  // Si los 28 nulos de P8A,P8B,P8C,P9 y P10 caen en los MISMOS slots, P8+ y
  // P9+P10 conservan 116 slots completos y la medida sigue siendo valida.
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (const name of P8PLUS) nullChannelRange(s, name, 144, 28);
  const r = SepModel.detect(s);
  return r.state !== "pendiente" && r.baseline.count === 144;
})());
ok("cero valido no es dato ausente", (function () {
  const zeros = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (let i = 144; i < 288; i++) zeros.samples[i].P8A = 0;
  const rz = SepModel.detect(zeros);
  const absent = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  nullChannel(absent, "P8A", 144);
  return rz.state !== "pendiente" && rz.baseline.coverage.P8A === 144 &&
         SepModel.detect(absent).state === "pendiente";
})());
ok("NaN e Infinity en un canal invalidan la muestra (no son ceros)", (function () {
  const a = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (let i = 144; i < 288; i++) a.samples[i].P8A = NaN;
  const b = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (let i = 144; i < 288; i++) b.samples[i].P8A = Infinity;
  return SepModel.detect(a).state === "pendiente" && SepModel.detect(b).state === "pendiente";
})());
ok("cobertura por slots: 144 muestras amontonadas en 1 h no cubren la ventana", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  const base = s.samples.slice(0, 288), event = s.samples.slice(288), packed = [];
  for (let i = 0; i < 144; i++) {
    packed.push(Object.assign({}, base[144 + i], { tMs: (144 + (i % 12)) * STEP_MS }));
  }
  return SepModel.detect({ startMs: s.startMs, channels: s.channels,
                           samples: packed.concat(event) }).state === "pendiente";
})());
ok("duplicados de un slot no alteran medianas ni finjen cobertura", (function () {
  const ref = SepModel.detect(stitch("g18_2024-05-10.json", "g18_2024-05-11.json"));
  const base = stitch("g18_2024-05-10.json", "g18_2024-05-11.json");
  const samples = base.samples.slice();
  for (let i = 144; i < 288; i++) samples.push(Object.assign({}, base.samples[i]));
  const dup = SepModel.detect({ startMs: base.startMs, channels: base.channels, samples: samples });
  return dup.baseline.median.p8plus === ref.baseline.median.p8plus &&
         dup.baseline.count === ref.baseline.count &&
         dup.baseline.coverage.P8A === 144;
})());
ok("duplicados no rellenan slots vacios (no finjen cobertura)", (function () {
  const base = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  const samples = base.samples.slice();
  for (let i = 144; i < 144 + 29; i++) samples[i] = Object.assign({}, samples[i], { P8A: null });
  for (let i = 144; i < 144 + 29; i++) samples.push(Object.assign({}, base.samples[i]));
  return SepModel.detect({ startMs: base.startMs, channels: base.channels, samples: samples }).state === "pendiente";
})());
ok("el baseline no se contamina: un pico en el evento no mueve el umbral", (function () {
  const reference = SepModel.detect(stitch("g16_2021-10-27.json", "g16_2021-10-28.json"));
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  for (let i = 300; i < 320; i++) s.samples[i].P8A = 1e9;
  const modified = SepModel.detect(s);
  return reference.thresholds.p8plus === modified.thresholds.p8plus &&
         reference.baseline.median.p8plus === modified.baseline.median.p8plus;
})());
console.log("T7 deteccion SEP — duplicados del baseline");
function insertSample(samples, sample, place) {
  if (place === "push") samples.push(sample);
  else samples.unshift(sample);
}
ok("duplicado identico del baseline (antes o despues) no cambia nada", (function () {
  const reference = SepModel.detect(stitch("g16_2021-10-27.json", "g16_2021-10-28.json"));
  for (const place of ["push", "unshift"]) {
    const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
    insertSample(s.samples, Object.assign({}, s.samples[200]), place);
    const dup = SepModel.detect(s);
    if (dup.state !== reference.state) return false;
    if (dup.baseline.median.p8plus !== reference.baseline.median.p8plus) return false;
    if (dup.baseline.sigma.p8plus !== reference.baseline.sigma.p8plus) return false;
    if (dup.thresholds.p8plus !== reference.thresholds.p8plus) return false;
    if (dup.baseline.coverage.P8A !== reference.baseline.coverage.P8A) return false;
    if (dup.baseline.count !== reference.baseline.count) return false;
  }
  return true;
})());
ok("duplicado conflictivo del baseline -> pendiente en ambos ordenes", (function () {
  for (const place of ["push", "unshift"]) {
    const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
    const conflict = Object.assign({}, s.samples[200], { P8A: s.samples[200].P8A + 1e-3 });
    insertSample(s.samples, conflict, place);
    const r = SepModel.detect(s);
    if (r.state !== "pendiente" || r.reason !== "baseline_conflictiva") return false;
  }
  return true;
})());
ok("conflicto por satelite o int500 en el baseline -> pendiente", (function () {
  const variants = [{ sat: "g18" }, { int500: 9.87 }];
  return variants.every(function (patch) {
    const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
    s.samples.push(Object.assign({}, s.samples[200], patch));
    const r = SepModel.detect(s);
    return r.state === "pendiente" && r.reason === "baseline_conflictiva";
  });
})());
ok("el resultado del baseline no depende del orden de entrada", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  const forward = SepModel.detect(s);
  const reversed = SepModel.detect({ startMs: s.startMs, channels: s.channels,
                                     samples: s.samples.slice().reverse() });
  return forward.state === reversed.state &&
         forward.baseline.median.p8plus === reversed.baseline.median.p8plus &&
         forward.thresholds.p8plus === reversed.thresholds.p8plus &&
         forward.baseline.count === reversed.baseline.count &&
         forward.baseline.coverage.P8A === reversed.baseline.coverage.P8A;
})());

console.log("T7 deteccion SEP — observacion posterior al inicio");
ok("sin muestras post-start -> pendiente (nunca sin_senal)", (function () {
  const r = SepModel.detect(quietSeries(144, 0));
  return r.state === "pendiente" && r.reason === "sin_observacion" && r.baseline === undefined;
})());
ok("menos de 3 slots de observacion -> pendiente", (function () {
  const r = SepModel.detect(quietSeries(144, 2));
  return r.state === "pendiente" && r.reason === "observacion_insuficiente";
})());
ok("hueco interno en la observacion -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples.splice(150, 1);
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "hueco_observacion";
})());
ok("canal no finito en la observacion -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[150].P9 = NaN;
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "observacion_incompleta";
})());
ok("canal ausente en la observacion -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[150].P4 = null;
  return SepModel.detect(s).reason === "observacion_incompleta";
})());
ok("satelite vacio en la observacion -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[150].sat = "";
  return SepModel.detect(s).reason === "satelite_ausente";
})());
ok("satelite distinto del baseline en la observacion -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[150].sat = "g16";
  return SepModel.detect(s).reason === "cambio_satelite";
})());

console.log("T7 deteccion SEP — inicio exacto y procesamiento cronologico");
ok("la observacion debe empezar exactamente en startMs", (function () {
  const s = quietSeries(144, 25);
  s.samples.splice(144, 1);   // la primera post-start pasa a startMs + STEP
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "hueco_observacion";
})());
ok("GLE73 sin la primera hora post-start -> pendiente (nunca detectado)", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  s.samples.splice(288, 12);  // quita 1 h al inicio de la observacion
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "hueco_observacion";
})());
ok("duplicados identicos post-start se ignoran (mismo onset)", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [144, 145, 146], EXCESS);
  const reference = SepModel.detect(s);
  for (let i = 144; i < 168; i++) s.samples.push(Object.assign({}, s.samples[i]));
  const r = SepModel.detect(s);
  return reference.state === "detectado" && r.state === "detectado" &&
         r.onsetMs === reference.onsetMs;
})());
ok("duplicado conflictivo antes del onset -> pendiente", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [147, 148, 149], EXCESS);
  s.samples.push(Object.assign({}, s.samples[145], { P8A: 999 }));
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "observacion_conflictiva";
})());
ok("un hueco antes de confirmar el onset -> pendiente", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [147, 148, 149], EXCESS);
  s.samples.splice(146, 1);
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "hueco_observacion";
})());
ok("un hueco posterior al onset no revoca la deteccion", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  const reference = SepModel.detect(s);
  if (reference.state !== "detectado") return false;
  const idx = 288 + (reference.onsetMs - s.startMs) / STEP_MS + 5;
  s.samples.splice(idx, 1);
  const r = SepModel.detect(s);
  return r.state === "detectado" && r.onsetMs === reference.onsetMs;
})());
ok("una muestra corrupta posterior al onset no revoca la deteccion", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  const reference = SepModel.detect(s);
  if (reference.state !== "detectado") return false;
  const idx = 288 + (reference.onsetMs - s.startMs) / STEP_MS + 5;
  if (!s.samples[idx]) return false;
  s.samples[idx].P9 = null;
  const r = SepModel.detect(s);
  return r.state === "detectado" && r.onsetMs === reference.onsetMs;
})());
ok("un duplicado conflictivo posterior al onset no revoca la deteccion", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  const reference = SepModel.detect(s);
  if (reference.state !== "detectado") return false;
  const idx = 288 + (reference.onsetMs - s.startMs) / STEP_MS + 5;
  if (!s.samples[idx]) return false;
  s.samples.push(Object.assign({}, s.samples[idx], { P8A: s.samples[idx].P8A + 1 }));
  const r = SepModel.detect(s);
  return r.state === "detectado" && r.onsetMs === reference.onsetMs;
})());

console.log("T7 deteccion SEP — timestamps y flujos invalidos");
ok("timestamp NaN intermedio -> pendiente (no se descarta en silencio)", (function () {
  const s = quietSeries(144, 24);
  s.samples[160].tMs = NaN;
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "timestamp_invalido";
})());
ok("timestamp NaN terminal -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[s.samples.length - 1].tMs = NaN;
  return SepModel.detect(s).reason === "timestamp_invalido";
})());
ok("timestamp no numerico -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[150].tMs = "no";
  return SepModel.detect(s).reason === "timestamp_invalido";
})());
ok("flujo negativo en el baseline -> pendiente", (function () {
  const s = stitch("g16_2021-10-27.json", "g16_2021-10-28.json");
  s.samples[150].P8A = -1;
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "flujo_invalido";
})());
ok("flujo negativo en la observacion -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[150].P9 = -1;
  const r = SepModel.detect(s);
  return r.state === "pendiente" && r.reason === "flujo_invalido";
})());
ok("int500 negativo en la observacion -> pendiente", (function () {
  const s = quietSeries(144, 24);
  s.samples[150].int500 = -1;
  return SepModel.detect(s).reason === "flujo_invalido";
})());

console.log("T7 deteccion SEP — racha y fallos cerrados");
ok("dos muestras consecutivas no detectan", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [144, 145], EXCESS);
  return SepModel.detect(s).state === "sin_senal";
})());
ok("tres muestras consecutivas si detectan", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [144, 145, 146], EXCESS);
  const r = SepModel.detect(s);
  return r.state === "detectado" && r.onsetMs === 144 * STEP_MS;
})());
ok("tres muestras a 10 min no son consecutivas", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [144, 146, 148], EXCESS);
  return SepModel.detect(s).state === "sin_senal";
})());
ok("el integral dispara solo (P9/P10 en cero) pero exige P8+", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [144, 145, 146], { P8A: 1e-3, P8B: 1e-3, P8C: 1e-3, P9: 0, P10: 0, int500: 1 });
  return SepModel.detect(s).state === "detectado";
})());
ok("sin disparador duro no hay deteccion aunque P8+ suba", (function () {
  const s = quietSeries(144, 24);
  injectExcess(s, [144, 145, 146], { P8A: 1e-3, P8B: 1e-3, P8C: 1e-3, int500: 0 });
  return SepModel.detect(s).state === "sin_senal";
})());
ok("entradas invalidas fallan cerradas a pendiente", (function () {
  return SepModel.detect(null).state === "pendiente" &&
         SepModel.detect({}).state === "pendiente" &&
         SepModel.detect({ startMs: 0, samples: [] }).state === "pendiente" &&
         SepModel.detect({ startMs: NaN, samples: [{}] }).state === "pendiente";
})());

// Justificacion del canal de confirmacion, con datos reales.
const EVENT_PAIRS = [["g16_2021-10-27.json", "g16_2021-10-28.json"],
                     ["g18_2024-05-10.json", "g18_2024-05-11.json"],
                     ["g18_2024-05-08.json", "g18_2024-03-23.json"],
                     ["g18_2024-05-08.json", "g18_2024-06-08.json"],
                     ["g18_2024-05-08.json", "g18_2024-10-09.json"]];
const CONTROL_PAIRS = QUIET.concat([["g18_2024-05-08.json", "g18_2024-09-01.json"],
                                    ["g18_2024-05-08.json", "g18_2024-12-08.json"]]);
ok("justificacion: P9+P10 tiene MAD nula en TODOS los baselines tranquilos", (function () {
  return QUIET.every(function (pair) {
    const r = SepModel.detect(stitch(pair[0], pair[1]));
    return r.state === "sin_senal" && r.baseline.sigma.p9p10 === 0;
  });
})());
ok("justificacion: P8+ ponderado separa eventos (racha >= 91) de controles (racha <= 4)", (function () {
  const eventsOk = EVENT_PAIRS.every(function (pair) {
    const channels = channelMeta(pair[0]);
    const stats = bandStats(pair[0], P8PLUS, channels);
    return bandRun(pair[1], P8PLUS, stats.threshold, channels) >= 91;
  });
  const controlsOk = CONTROL_PAIRS.every(function (pair) {
    const channels = channelMeta(pair[0]);
    const stats = bandStats(pair[0], P8PLUS, channels);
    return bandRun(pair[1], P8PLUS, stats.threshold, channels) <= 4;
  });
  return eventsOk && controlsOk;
})());
ok("justificacion: con P9+P10 como confirmacion un dia tranquilo daria racha >= 3", (function () {
  const channels = channelMeta("g16_2021-10-27.json");
  const stats = bandStats("g16_2021-10-27.json", P910, channels);
  return bandRun("g16_2021-10-27.json", P910, stats.threshold, channels) >= 3;
})());

// === T8: ensemble espectral (fuente canonica) ==============================
const CHANNELS = channelMeta("g16_2021-10-28.json");
function quietMedians(name) {
  const d = fixture(name), out = {};
  for (let c = 0; c < CH_NAMES.length; c++) {
    const values = [];
    for (let i = 0; i < d.n_steps; i++) values.push(d.diff[i][c]);
    out[CH_NAMES[c]] = median(values);
  }
  const iv = [];
  for (let i = 0; i < d.n_steps; i++) iv.push(d.integral_500_keV[i]);
  out.int500 = median(iv);
  return out;
}
const BASE_Q = quietMedians("g16_2021-10-27.json");
// Promedio analitico del bin por Simpson en log-E: referencia INDEPENDIENTE del
// ajuste de produccion (que usa la integral analitica de la forma).
function binAverage(spectrumAtGeV, loGeV, hiGeV, subintervals) {
  const n = subintervals || 400, logLo = Math.log(loGeV), logHi = Math.log(hiGeV), h = (logHi - logLo) / n;
  let sum = 0;
  for (let i = 0; i <= n; i++) {
    const E = Math.exp(logLo + i * h);
    const weight = (i === 0 || i === n) ? 1 : (i % 2 ? 4 : 2);
    sum += weight * spectrumAtGeV(E) * E;
  }
  return (sum * h / 3) / (hiGeV - loGeV);
}
function syntheticSample(spectrumAtGeV, baseline) {
  const s = { int500: 0.4 };
  for (const c of CHANNELS) {
    const lo = c.lo_keV / KEV_PER_GEV, hi = c.hi_keV / KEV_PER_GEV;
    // El fixture guarda densidad por keV; la verdad es por GeV.
    s[c.name] = baseline[c.name] + binAverage(spectrumAtGeV, lo, hi) / KEV_PER_GEV;
  }
  return s;
}
function runEnsemble(sample, operator) {
  return SepModel.ensemble({ channels: CHANNELS, sample: sample, baseline: BASE_Q,
                             operator: operator, rcGV: 0, altitudeKm: 10.5 });
}
function fakeOperator(rate, tail) {
  return { rate: function () { return { ok: true, rateUsvH: rate, tailRateUsvH: tail }; } };
}
const SYNTH = (E) => 100 * Math.pow(E, -2.5);
const DOUBLE = (E) => 100 * Math.pow(E / 0.05, E < 0.05 ? -1.5 : -3.5);
function binRecoveryError(solution, truth) {
  let worst = 0;
  for (const c of CHANNELS) {
    const lo = c.lo_keV / KEV_PER_GEV, hi = c.hi_keV / KEV_PER_GEV;
    const model = binAverage(solution.spectrumAtGeV, lo, hi);
    const target = binAverage(truth, lo, hi);
    worst = Math.max(worst, Math.abs(model / target - 1));
  }
  return worst;
}

console.log("T8 ensemble espectral — recuperacion");
ok("power-law conocido recuperado <10% en los 13 bins", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(1, 0.01));
  if (!r.ok) return false;
  const solution = r.solutions.filter((s) => s.model === "power-law")[0];
  return !!solution && binRecoveryError(solution, SYNTH) < 0.10;
})());
ok("doble ley conocida recuperada <10% en los 13 bins", (function () {
  const r = runEnsemble(syntheticSample(DOUBLE, BASE_Q), fakeOperator(1, 0.01));
  if (!r.ok) return false;
  const solution = r.solutions.filter((s) => s.model === "double-power-law")[0];
  return !!solution && binRecoveryError(solution, DOUBLE) < 0.10;
})());
ok("conversion keV/GeV y por-keV/por-GeV correctas (amplitud a 1 GeV)", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(1, 0.01));
  if (!r.ok) return false;
  const solution = r.solutions.filter((s) => s.model === "power-law")[0];
  return Math.abs(solution.spectrumAtGeV(1) / SYNTH(1) - 1) < 0.10 &&
         Math.abs(solution.amplitude - 100) / 100 < 0.10;
})());
ok("ambas spectrumAtGeV son finitas y no negativas entre 50 MeV y 20 GeV", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(1, 0.01));
  if (!r.ok) return false;
  return r.solutions.every(function (solution) {
    for (let energy = 0.05; energy <= 20.0001; energy *= 1.1) {
      const flux = solution.spectrumAtGeV(energy);
      if (typeof flux !== "number" || !isFinite(flux) || flux < 0) return false;
    }
    return true;
  });
})());
ok("usa tambien los canales diferenciales por debajo de 50 MeV", (function () {
  // Exceso solo en P1..P3 (<50 MeV). Si el ajuste descartase los canales blandos
  // no habria bins suficientes y devolveria sin cifra.
  const sample = { int500: BASE_Q.int500 };
  for (const c of CHANNELS) sample[c.name] = BASE_Q[c.name];
  for (const c of CHANNELS.slice(0, 4)) {
    const lo = c.lo_keV / KEV_PER_GEV, hi = c.hi_keV / KEV_PER_GEV;
    sample[c.name] = BASE_Q[c.name] + binAverage(SYNTH, lo, hi) / KEV_PER_GEV;
  }
  return runEnsemble(sample, fakeOperator(1, 0.01)).ok === true;
})());

console.log("T8 ensemble espectral — contrato de canales");
ok("exige exactamente 13 canales: 4, 12, 14, duplicados y desconocidos fallan cerrado", (function () {
  const sample = syntheticSample(SYNTH, BASE_Q);
  const run = (list) => SepModel.ensemble({ channels: list, sample: sample, baseline: BASE_Q,
                                             operator: fakeOperator(1, 0.01), rcGV: 0, altitudeKm: 10.5 });
  const four = CHANNELS.slice(0, 4);
  const twelve = CHANNELS.slice(0, 12);
  const fourteen = CHANNELS.concat([{ name: "P11", lo_keV: 1000, hi_keV: 2000 }]);
  const duplicate = CHANNELS.map((c, i) => i === 3 ? { name: "P1", lo_keV: c.lo_keV, hi_keV: c.hi_keV } : c);
  const unknown = CHANNELS.map((c, i) => i === 0 ? { name: "ZZ", lo_keV: c.lo_keV, hi_keV: c.hi_keV } : c);
  const badEdges = CHANNELS.map((c, i) => i === 0 ? { name: c.name, lo_keV: 5, hi_keV: 5 } : c);
  return [four, twelve, fourteen, duplicate, unknown, badEdges].every(function (list) {
    return run(list).code === "CANALES_INVALIDOS";
  });
})());
ok("exige muestra y baseline finitos en los 13 canales", (function () {
  const brokenSample = syntheticSample(SYNTH, BASE_Q);
  brokenSample.P9 = null;
  const brokenBaseline = Object.assign({}, BASE_Q);
  delete brokenBaseline.P8A;
  const a = SepModel.ensemble({ channels: CHANNELS, sample: brokenSample, baseline: BASE_Q,
                                operator: fakeOperator(1, 0.01), rcGV: 0, altitudeKm: 10.5 });
  const b = SepModel.ensemble({ channels: CHANNELS, sample: syntheticSample(SYNTH, BASE_Q),
                                baseline: brokenBaseline, operator: fakeOperator(1, 0.01),
                                rcGV: 0, altitudeKm: 10.5 });
  return a.code === "CANALES_INCOMPLETOS" && b.code === "CANALES_INCOMPLETOS";
})());
ok("bordes de canal exigen typeof number y finitos, sin coercion", (function () {
  const sample = syntheticSample(SYNTH, BASE_Q);
  const run = (list) => SepModel.ensemble({ channels: list, sample: sample, baseline: BASE_Q,
                                             operator: fakeOperator(1, 0.01), rcGV: 0, altitudeKm: 10.5 });
  const mutate = (field, value) => CHANNELS.map((c, i) =>
    i === 0 ? Object.assign({}, c, { [field]: value }) : c);
  const bad = ["1020", true, false, null, NaN, Infinity, undefined, [1020], { v: 1020 }];
  return bad.every((value) =>
    run(mutate("lo_keV", value)).code === "CANALES_INVALIDOS" &&
    run(mutate("hi_keV", value)).code === "CANALES_INVALIDOS");
})());
ok("densidad negativa en la muestra del ensemble -> CANALES_INCOMPLETOS", (function () {
  const sample = syntheticSample(SYNTH, BASE_Q);
  sample.P9 = -1;
  const r = runEnsemble(sample, fakeOperator(1, 0.01));
  return r.ok === false && r.code === "CANALES_INCOMPLETOS";
})());
ok("densidad negativa en el baseline del ensemble -> CANALES_INCOMPLETOS", (function () {
  const baseline = Object.assign({}, BASE_Q, { P9: -1 });
  const r = SepModel.ensemble({ channels: CHANNELS, sample: syntheticSample(SYNTH, BASE_Q),
                                baseline: baseline, operator: fakeOperator(1, 0.01),
                                rcGV: 0, altitudeKm: 10.5 });
  return r.ok === false && r.code === "CANALES_INCOMPLETOS";
})());
ok("muestra negativa con baseline mas negativo no produce exceso positivo", (function () {
  const sample = syntheticSample(SYNTH, BASE_Q);
  const baseline = Object.assign({}, BASE_Q);
  sample.P9 = -1; baseline.P9 = -2;   // -1 - (-2) = +1 si se calculara
  const r = SepModel.ensemble({ channels: CHANNELS, sample: sample, baseline: baseline,
                                operator: fakeOperator(1, 0.01), rcGV: 0, altitudeKm: 10.5 });
  return r.ok === false && r.code === "CANALES_INCOMPLETOS";
})());

console.log("T8 ensemble espectral — composicion detect -> ensemble");
ok("ensemble acepta literalmente detect().baseline", (function () {
  const series = quietSeries(144, 24);
  const detection = SepModel.detect(series);
  if (detection.state === "pendiente") return false;
  const sample = sampleFromMedians(series.channels, detection.baseline.medians, SYNTH);
  const r = SepModel.ensemble({ channels: series.channels, sample: sample,
                                baseline: detection.baseline, operator: fakeOperator(1, 0.01),
                                rcGV: 0, altitudeKm: 10.5 });
  return r.ok === true && r.code === undefined;
})());
ok("ensemble acepta tambien el mapa plano de medianas (compatibilidad)", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(1, 0.01));
  return r.ok === true;
})());

console.log("T8 ensemble espectral — validacion de las dos soluciones");
ok("la segunda solucion se evalua y su corrupcion falla cerrado", (function () {
  let calls = 0;
  const op = { rate: function () {
    calls++;
    return calls === 1 ? { ok: true, rateUsvH: 1, tailRateUsvH: 0.01 }
                       : { ok: true, rateUsvH: NaN, tailRateUsvH: 0 };
  } };
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), op);
  return r.ok === false && r.range === undefined && calls === 2;
})());
ok("si la primera solucion falla, la segunda se sigue evaluando", (function () {
  let calls = 0;
  const op = { rate: function () {
    calls++;
    return calls === 1 ? { ok: false, code: "INVALID_MODEL" }
                       : { ok: true, rateUsvH: 1, tailRateUsvH: 0.01 };
  } };
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), op);
  return r.ok === false && r.code === "INVALID_MODEL" && calls === 2;
})());
ok("no ajusta con solo 3 bins utiles", (function () {
  // Exceso solo en P1, P2A y P2B: 3 bins utilizables, insuficiente para un
  // regimen con rodilla (doble ley). Debe fallar cerrado, no ajustar con tres.
  const sample = { int500: BASE_Q.int500 };
  for (const c of CHANNELS) sample[c.name] = BASE_Q[c.name];
  for (const c of CHANNELS.slice(0, 3)) {
    const lo = c.lo_keV / KEV_PER_GEV, hi = c.hi_keV / KEV_PER_GEV;
    sample[c.name] = BASE_Q[c.name] + binAverage(SYNTH, lo, hi) / KEV_PER_GEV;
  }
  const r = runEnsemble(sample, fakeOperator(1, 0.01));
  return r.ok === false && r.code === "AJUSTE_INSUFICIENTE";
})());
ok("el rango usa las dos soluciones, no solo una", (function () {
  let calls = 0;
  const op = { rate: function () {
    calls++;
    return calls === 1 ? { ok: true, rateUsvH: 1, tailRateUsvH: 0.01 }
                       : { ok: true, rateUsvH: 9, tailRateUsvH: 0.05 };
  } };
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), op);
  return r.ok === true && calls === 2 &&
         r.solutions[0].rateUsvH === 1 && r.solutions[1].rateUsvH === 9 &&
         r.range.lowUsvH === 1 && r.range.highUsvH === 9;
})());
ok("si solo una solucion incumple la cola, todo el ensemble falla cerrado", (function () {
  let calls = 0;
  const op = { rate: function () {
    calls++;
    return calls === 1 ? { ok: true, rateUsvH: 1, tailRateUsvH: 0.5 }
                       : { ok: true, rateUsvH: 1, tailRateUsvH: 0.01 };
  } };
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), op);
  return r.ok === false && r.code === "SIN_CONVERGENCIA" && r.range === undefined && calls === 2;
})());
ok("cola exactamente 10% no converge; 9.9% si", (function () {
  const bad = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(1, 0.10));
  const good = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(1, 0.099));
  return bad.ok === false && bad.code === "SIN_CONVERGENCIA" && good.ok === true;
})());
ok("error del operador se propaga como sin cifra, nunca como cero", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), { rate: function () { return { ok: false, code: "INVALID_MODEL" }; } });
  return r.ok === false && r.code === "INVALID_MODEL" && r.range === undefined;
})());
ok("excepcion del operador se propaga como sin cifra", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), { rate: function () { throw new Error("boom"); } });
  return r.ok === false && r.code === "NUMERIC_FAILURE";
})());
ok("dosis cero del operador no se publica como cifra", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(0, 0));
  return r.ok === false && r.range === undefined;
})());
ok("un error real del operador (altitud fuera de rango) es sin cifra", (function () {
  const r = SepModel.ensemble({ channels: CHANNELS, sample: syntheticSample(SYNTH, BASE_Q), baseline: BASE_Q,
                                operator: ctx.SEP_DOSE, rcGV: 0, altitudeKm: 99 });
  return r.ok === false && r.code === "ALTITUDE_OUT_OF_RANGE" && r.range === undefined;
})());
ok("espectro artificialmente duro provoca sin cifra (no un numero)", (function () {
  const sample = syntheticSample(function () { return 1; }, BASE_Q);
  const r = SepModel.ensemble({ channels: CHANNELS, sample: sample, baseline: BASE_Q,
                                operator: ctx.SEP_DOSE, rcGV: 0, altitudeKm: 10.5 });
  return r.ok === false && r.code === "SIN_CONVERGENCIA" && r.range === undefined && r.solutions === undefined;
})());
ok("flujo por debajo de la linea base se satura a cero (nunca negativo)", (function () {
  const baseline = {}, sample = { int500: 1 };
  for (const c of CHANNELS) { baseline[c.name] = 1.5; sample[c.name] = 0.5; }
  const r = SepModel.ensemble({ channels: CHANNELS, sample: sample, baseline: baseline,
                                operator: fakeOperator(1, 0.01), rcGV: 0, altitudeKm: 10.5 });
  return r.ok === false && r.code === "AJUSTE_INSUFICIENTE";
})());
ok("rango final factor >= 3 con ensemble degenerado y simetrico en log", (function () {
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), fakeOperator(2, 0.1));
  return r.ok === true && r.range.factor >= 2.999999 &&
         Math.abs(Math.sqrt(r.range.lowUsvH * r.range.highUsvH) - 2) < 1e-9;
})());
ok("ni el rango ni las soluciones dan NaN, Infinity ni dosis negativa", (function () {
  let calls = 0;
  const op = { rate: function () {
    calls++;
    return calls === 1 ? { ok: true, rateUsvH: 1.25, tailRateUsvH: 0.01 }
                       : { ok: true, rateUsvH: 3.5, tailRateUsvH: 0.02 };
  } };
  const r = runEnsemble(syntheticSample(SYNTH, BASE_Q), op);
  if (!r.ok) return false;
  const numbers = [r.range.lowUsvH, r.range.highUsvH, r.range.factor];
  for (const solution of r.solutions) numbers.push(solution.rateUsvH, solution.tailRateUsvH);
  return numbers.every((x) => typeof x === "number" && isFinite(x) && x >= 0);
})());
ok("sin canales u operador invalido falla cerrado", (function () {
  const sample = syntheticSample(SYNTH, BASE_Q);
  return SepModel.ensemble({ channels: [], sample: sample, baseline: BASE_Q, operator: fakeOperator(1, 0) }).code === "CANALES_INVALIDOS" &&
         SepModel.ensemble({ channels: CHANNELS, sample: sample, baseline: BASE_Q }).code === "MODELO_NO_DISPONIBLE" &&
         SepModel.ensemble(null).code === "ENTRADA_INVALIDA";
})());

// === T9: integracion por ruta (fuente canonica) ============================
// Serie real de GLE73 (baseline del 27 + dia del evento) para todos los casos
// que necesitan un evento detectable. Los fallos cerrados se fabrican mutando
// esa misma serie DESPUES del onset, que detect() no vuelve a mirar.
function t9Series() { return stitch("g16_2021-10-27.json", "g16_2021-10-28.json"); }
function t9OnsetIndex(s) {
  const d = SepModel.detect(s);
  return d.state === "detectado" ? (d.onsetMs - s.startMs) / STEP_MS : -1;
}
// Indice dentro del array `samples` (las series de prueba arrancan en t=0).
function t9OnsetGlobal(s) {
  const d = SepModel.detect(s);
  return d.state === "detectado" ? Math.round(d.onsetMs / STEP_MS) : -1;
}
function t9Fn(v) { return typeof v === "function" ? v : () => v; }
function routePoints(startMs, endMs, n, rcAtf, altAtf) {
  const rcFn = t9Fn(rcAtf), altFn = t9Fn(altAtf), pts = [];
  for (let i = 0; i <= n; i++) {
    const f = i / n;
    pts.push({ tMs: startMs + (endMs - startMs) * f, rcGV: rcFn(f), altitudeKm: altFn(f) });
  }
  return pts;
}
function routeFromOnset(s, k, hours, n, rcAtf, altAtf) {
  const t0 = s.startMs + k * STEP_MS;
  return routePoints(t0, t0 + hours * HOUR_MS, n, rcAtf, altAtf);
}
function runRoute(series, points, operator) {
  return SepModel.route({ channels: series.channels, samples: series.samples,
                          startMs: series.startMs, points: points,
                          operator: operator || ctx.SEP_DOSE });
}
function routeCenter(r) { return Math.sqrt(r.range.lowUsv * r.range.highUsv); }
// Operador sintetico que alterna la tasa de los dos miembros del ensemble (la
// primera llamada de cada paso es la ley de potencia, la segunda la doble ley).
function alternatingOperator(rateA, rateB) {
  let calls = 0;
  return { rate: function () {
    calls++;
    return { ok: true, rateUsvH: calls % 2 ? rateA : rateB, tailRateUsvH: 0,
             numericalErrorUsvH: 0 };
  } };
}
// Deja la muestra con exceso solo en los canales indicados, sobre las medianas
// reales del baseline (los demas canales quedan exactamente en su mediana).
function setOnlyChannels(sample, medians, names) {
  for (const name of CH_NAMES) sample[name] = medians[name];
  for (const name of names) sample[name] = medians[name] + 1e-3;
}
// Evento sintetico con espectro BLANDO (E^-3) sobre la linea base del fixture
// tranquilo. GLE73 real no sirve para los casos que publican cifra: su ajuste de
// ley de potencia sale casi plano (~E^-0.7) y su cola >=10 GeV supera el 10%,
// asi que el ensemble falla cerrado (se prueba aparte, mas abajo).
function softEventSeries() {
  const d = fixture("g18_2024-05-08.json"), med = {};
  for (let c = 0; c < CH_NAMES.length; c++) {
    const values = [];
    for (let i = 0; i < 144; i++) values.push(d.diff[i][c]);
    med[CH_NAMES[c]] = median(values);
  }
  const iv = [];
  for (let i = 0; i < 144; i++) iv.push(d.integral_500_keV[i]);
  med.int500 = median(iv);
  const s = quietSeries(144, 96);
  const SOFT = (E) => Math.pow(E, -3);
  for (let i = 144; i < 240; i++) {
    const sample = s.samples[i];
    for (const c of s.channels) {
      sample[c.name] = med[c.name] +
        binAverage(SOFT, c.lo_keV / KEV_PER_GEV, c.hi_keV / KEV_PER_GEV) / KEV_PER_GEV;
    }
    sample.int500 = med.int500 + 1;
  }
  return s;
}

console.log("T9 ruta SEP — integracion y rango");
ok("ruta polar da mas dosis que ecuatorial en el mismo evento", (function () {
  const s = softEventSeries();
  const det = SepModel.detect(s);
  if (det.state !== "detectado") return false;
  const t0 = det.onsetMs, t1 = t0 + 2 * HOUR_MS;
  const polar = runRoute(s, routePoints(t0, t1, 24, 0.5, 10.5));
  const ecuat = runRoute(s, routePoints(t0, t1, 24, 2, 10.5));
  return polar.ok && ecuat.ok && polar.range && ecuat.range &&
         routeCenter(polar) > routeCenter(ecuat);
})());
ok("Rc muy alta (ecuador real) -> la cola domina y no hay cifra", (function () {
  const s = softEventSeries();
  const det = SepModel.detect(s);
  if (det.state !== "detectado") return false;
  const t0 = det.onsetMs, t1 = t0 + 2 * HOUR_MS;
  const r = runRoute(s, routePoints(t0, t1, 24, 12, 10.5));
  return r.ok === false && r.state === "pendiente" && r.reason === "sin_convergencia";
})());
ok("convergencia de ruta <5% al duplicar pasos", (function () {
  const s = softEventSeries();
  const det = SepModel.detect(s);
  if (det.state !== "detectado") return false;
  const t0 = det.onsetMs, t1 = t0 + 2 * HOUR_MS;
  const rc = (f) => 0.5 + 1.5 * f, alt = (f) => 9 + 3 * f;
  const coarse = runRoute(s, routePoints(t0, t1, 16, rc, alt));
  const fine = runRoute(s, routePoints(t0, t1, 64, rc, alt));
  return coarse.ok && fine.ok && coarse.range && fine.range &&
         Math.abs(routeCenter(fine) / routeCenter(coarse) - 1) < 0.05;
})());
ok("GLE73 real (espectro duro) falla cerrado por cola, no da cifra", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const r = runRoute(s, routeFromOnset(s, k, 2, 24, 1, 10.5));
  return r.ok === false && r.state === "pendiente" && r.reason === "sin_convergencia";
})());
ok("el rango se forma DESPUES de integrar cada miembro (no punto a punto)", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  // 24 pasos x 1/12 h = 2 h: el miembro 0 integra 2 uSv y el miembro 1, 6 uSv.
  const r = runRoute(s, routeFromOnset(s, k, 2, 24, 1, 10.5),
                     alternatingOperator(1, 3));
  return r.ok && r.steps === 24 && r.range &&
         Math.abs(r.range.lowUsv - 2) < 1e-9 && Math.abs(r.range.highUsv - 6) < 1e-9 &&
         Math.abs(r.range.factor - 3) < 1e-9 &&
         r.members[0].doseUsv === r.range.lowUsv && r.members[1].doseUsv === r.range.highUsv;
})());
ok("el rango no se estrecha por debajo de factor 3 con miembros iguales", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const r = runRoute(s, routeFromOnset(s, k, 2, 24, 1, 10.5),
                     alternatingOperator(2, 2));
  return r.ok && r.range && r.range.factor >= 2.999999 &&
         Math.abs(routeCenter(r) - 4) < 1e-9;
})());
ok("sin senal -> estado sin_senal, dosis cero y sin cifra", (function () {
  const s = quietSeries(144, 24);
  const r = runRoute(s, routePoints(s.startMs, s.startMs + 2 * HOUR_MS, 12, 1, 10.5));
  return r.ok && r.state === "sin_senal" && r.range === null && r.steps === 0;
})());
ok("paso con los 13 canales en la linea base -> cero medido, no pendiente", (function () {
  const s = t9Series(), k = t9OnsetIndex(s), g = t9OnsetGlobal(s);
  if (k < 0) return false;
  const medians = SepModel.detect(s).baseline.medians;
  for (let i = g + 8; i < g + 24; i++) setOnlyChannels(s.samples[i], medians, []);
  const r = runRoute(s, routeFromOnset(s, k, 2, 48, 1, 10.5), alternatingOperator(1, 1));
  return r.ok === true && r.state === "detectado" && r.range !== null &&
         r.steps > 0 && r.steps < 24;
})());
ok("T1 ruta anterior al onset (punto medio < onset) -> cero medido, 0 pasos", (function () {
  // El ruido de la linea base por encima de la mediana no es dosis: una ruta que
  // termina antes del onset no mide ni un solo paso, incluida la excursion
  // aislada en onset-2 pasos que si supera el umbral pero no es racha de tres.
  const s = t9Series();
  const det = SepModel.detect(s);
  if (det.state !== "detectado") return false;
  const onset = det.onsetMs;
  const r = runRoute(s, routePoints(onset - 2 * HOUR_MS, onset, 24, 0.5, 10.5));
  return r.ok === true && r.state === "detectado" && r.range === null && r.steps === 0;
})());
ok("T2 banda P8+ en la mediana -> esos pasos son cero medido", (function () {
  // Muestras con 5 bins de exceso (P1..P4) pero la banda dura P8+ clavada en su
  // mediana: no superan el umbral, asi que no se ajustan y no cuentan.
  const s = t9Series(), k = t9OnsetIndex(s), g = t9OnsetGlobal(s);
  if (k < 0) return false;
  const medians = SepModel.detect(s).baseline.medians;
  for (let i = g + 8; i < g + 24; i++) {
    setOnlyChannels(s.samples[i], medians, ["P1", "P2A", "P2B", "P3", "P4"]);
  }
  const r = runRoute(s, routeFromOnset(s, k, 2, 48, 1, 10.5), alternatingOperator(1, 1));
  return r.ok === true && r.state === "detectado" && r.range !== null &&
         r.steps > 0 && r.steps < 48;
})());
ok("T3 Rc y altitud se interpolan en el punto medio del tramo", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const seen = [];
  const spy = { rate: function (args) {
    seen.push({ rcGV: args.rcGV, altitudeKm: args.altitudeKm });
    return { ok: true, rateUsvH: 1, tailRateUsvH: 0, numericalErrorUsvH: 0 };
  } };
  const t0 = s.startMs + k * STEP_MS;
  const points = routePoints(t0, t0 + 5 * 60 * 1000, 1, (f) => 2 * f, (f) => 9 + 2 * f);
  const r = runRoute(s, points, spy);
  return r.ok === true && seen.length > 0 &&
         seen.every((c) => c.rcGV === 1 && c.altitudeKm === 10);
})());
ok("T4 el flujo se muestrea en el punto medio, no en el extremo del tramo", (function () {
  // Hueco en [onset+45, onset+65) min: la muestra de a.tMs (onset+60) no existe,
  // pero la de tMid (onset+70) si, asi que la ruta puede medir.
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const onset = s.startMs + k * STEP_MS;
  for (let i = s.samples.length - 1; i >= 0; i--) {
    const t = s.samples[i].tMs;
    if (t >= onset + 45 * 60 * 1000 && t < onset + 65 * 60 * 1000) s.samples.splice(i, 1);
  }
  const points = [{ tMs: onset + 60 * 60 * 1000, rcGV: 1, altitudeKm: 10.5 },
                  { tMs: onset + 80 * 60 * 1000, rcGV: 1, altitudeKm: 10.5 }];
  const r = runRoute(s, points, alternatingOperator(1, 1));
  return r.ok === true;
})());

console.log("T9 ruta SEP — fallos cerrados");
ok("hueco de la serie dentro de la ruta -> pendiente (no cero)", (function () {
  const s = t9Series(), k = t9OnsetIndex(s), g = t9OnsetGlobal(s);
  if (k < 0) return false;
  s.samples.splice(g + 10, 2);
  const r = runRoute(s, routeFromOnset(s, k, 2, 48, 1, 10.5), alternatingOperator(1, 1));
  return r.ok === false && r.state === "pendiente" && r.reason === "hueco_observacion";
})());
ok("canal ausente en un paso -> pendiente (no se inventa el flujo)", (function () {
  const s = t9Series(), k = t9OnsetIndex(s), g = t9OnsetGlobal(s);
  if (k < 0) return false;
  s.samples[g + 5].P9 = null;
  const r = runRoute(s, routeFromOnset(s, k, 2, 48, 1, 10.5), alternatingOperator(1, 1));
  return r.ok === false && r.state === "pendiente" && r.reason === "observacion_incompleta";
})());
ok("cambio de satelite despues del onset -> pendiente (detect retorna antes)", (function () {
  const s = t9Series(), k = t9OnsetIndex(s), g = t9OnsetGlobal(s);
  if (k < 0) return false;
  s.samples[g + 5].sat = "g18";
  const r = runRoute(s, routeFromOnset(s, k, 2, 48, 1, 10.5), alternatingOperator(1, 1));
  return r.ok === false && r.state === "pendiente" && r.reason === "cambio_satelite";
})());
ok("exceso en menos de 4 bins -> pendiente, nunca cero", (function () {
  const s = t9Series(), k = t9OnsetIndex(s), g = t9OnsetGlobal(s);
  if (k < 0) return false;
  const medians = SepModel.detect(s).baseline.medians;
  for (let i = g + 8; i < g + 24; i++) setOnlyChannels(s.samples[i], medians, ["P8A", "P8B", "P8C"]);
  const r = runRoute(s, routeFromOnset(s, k, 2, 48, 1, 10.5), alternatingOperator(1, 1));
  return r.ok === false && r.state === "pendiente" && r.reason === "modelo_no_resoluble";
})());
ok("cola integrada >=10% en un miembro -> sin convergencia", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const op = { rate: function () {
    return { ok: true, rateUsvH: 1, tailRateUsvH: 0.5, numericalErrorUsvH: 0 };
  } };
  const r = runRoute(s, routeFromOnset(s, k, 2, 24, 1, 10.5), op);
  return r.ok === false && r.state === "pendiente" && r.reason === "sin_convergencia";
})());
ok("dosis integrada bajo la cota de error -> sin cifra", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const op = { rate: function () {
    return { ok: true, rateUsvH: 1, tailRateUsvH: 0, numericalErrorUsvH: 2 };
  } };
  const r = runRoute(s, routeFromOnset(s, k, 2, 24, 1, 10.5), op);
  return r.ok === false && r.state === "pendiente" && r.reason === "modelo_no_resoluble";
})());
ok("error del operador se propaga como codigo, nunca como cero", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const op = { rate: function () { return { ok: false, code: "INVALID_MODEL" }; } };
  const r = runRoute(s, routeFromOnset(s, k, 2, 24, 1, 10.5), op);
  return r.ok === false && r.code === "INVALID_MODEL" && r.range === undefined;
})());
ok("cota de error ausente del operador -> fallo cerrado", (function () {
  const s = t9Series(), k = t9OnsetIndex(s);
  if (k < 0) return false;
  const op = { rate: function () { return { ok: true, rateUsvH: 1, tailRateUsvH: 0 }; } };
  const r = runRoute(s, routeFromOnset(s, k, 2, 24, 1, 10.5), op);
  return r.ok === false && r.code === "NUMERIC_FAILURE";
})());
ok("ruta invalida (menos de dos puntos, no creciente, no finita) -> entrada invalida", (function () {
  const t0 = 0;
  const bad = [[], [{ tMs: t0, rcGV: 1, altitudeKm: 10.5 }],
    [{ tMs: t0, rcGV: 1, altitudeKm: 10.5 }, { tMs: t0, rcGV: 1, altitudeKm: 10.5 }],
    [{ tMs: t0, rcGV: NaN, altitudeKm: 10.5 }, { tMs: t0 + STEP_MS, rcGV: 1, altitudeKm: 10.5 }]];
  return bad.every((points) => SepModel.route({ channels: CHANNELS, samples: [],
    startMs: 0, points: points, operator: alternatingOperator(1, 1) }).code === "ENTRADA_INVALIDA");
})());

console.log("T9 ruta SEP — instrumentacion (informe T14)");
(function () {
  const s = softEventSeries();
  const det = SepModel.detect(s);
  if (det.state !== "detectado") { console.log("  (sin evento: no se mide)"); return; }
  const points = routePoints(det.onsetMs, det.onsetMs + 2 * HOUR_MS, 32,
                             (f) => 0.5 + 1.5 * f, (f) => 9 + 3 * f);
  const probe = runRoute(s, points);
  const t0 = Date.now();
  for (let i = 0; i < 40; i++) runRoute(s, points);
  const perFlight = (Date.now() - t0) / 40;
  console.log("  T9 40 rutas x 32 pasos (mes lleno): " + (perFlight * 40).toFixed(0) +
    " ms total, " + perFlight.toFixed(1) + " ms/vuelo; umbral de troceo 200 ms");
  console.log("  rango de referencia: " + (probe.range ? probe.range.lowUsv.toFixed(4) +
    " - " + probe.range.highUsv.toFixed(4) + " uSv" : "sin cifra (" + probe.reason + ")"));
  ok("T5 rango de referencia a <=5% de 6.0466 - 18.1399 uSv",
     probe.range !== null &&
     Math.abs(probe.range.lowUsv / 6.0466 - 1) <= 0.05 &&
     Math.abs(probe.range.highUsv / 18.1399 - 1) <= 0.05,
     probe.range ? probe.range.lowUsv.toFixed(4) + " - " + probe.range.highUsv.toFixed(4) +
       " uSv" : "sin cifra (" + probe.reason + ")");
})();

console.log("\n" + pass + " pass, " + fail + " fail");
process.exit(fail ? 1 : 0);
