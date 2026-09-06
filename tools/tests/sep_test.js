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

console.log("\n" + pass + " pass, " + fail + " fail");
process.exit(fail ? 1 : 0);
