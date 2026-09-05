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

console.log("\n" + pass + " pass, " + fail + " fail");
process.exit(fail ? 1 : 0);
