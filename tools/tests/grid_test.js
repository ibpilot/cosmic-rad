// Tests de la rejilla de dosis por rigidez de corte.
// Carga el ultimo <script> de index.html en un vm de Node, igual que bugs_test.js.
const fs = require("fs"), vm = require("vm"), path = require("path");

// Por defecto, la raiz del repo que contiene ESTE fichero (tools/tests/../..).
// Hardcodear la ruta hacia leer el index.html equivocado al correr desde un
// worktree, y los tests pasaban o reventaban por el fichero de otro sitio.
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

console.log("\nrcAt — valores contra el fichero fuente de CARI-7A");
{
  // Valores leidos de CUTOFFS/IGRF2010.1X1. Si estos fallan, el empaquetado
  // Int16 o el orden lat-major estan mal.
  ok("50N 270E = 0.87 GV", Math.abs(ctx.rcAt(50, 270) - 0.87) < 0.005, ctx.rcAt(50, 270));
  ok("50N 150E = 4.66 GV", Math.abs(ctx.rcAt(50, 150) - 4.66) < 0.005, ctx.rcAt(50, 150));
  ok("50N 0E = 3.39 GV", Math.abs(ctx.rcAt(50, 0) - 3.39) < 0.005, ctx.rcAt(50, 0));
  ok("todos los valores en rango fisico",
     [[0,0],[45,45],[-60,200],[80,300]].every(p => {
       const v = ctx.rcAt(p[0], p[1]); return v >= 0 && v <= 18;
     }));
}

console.log("\nrcAt — costura de longitud");
{
  // 359.5E debe caer entre los valores de 359E y 0E, no saltar.
  const a = ctx.rcAt(45, 359), b = ctx.rcAt(45, 0), m = ctx.rcAt(45, 359.5);
  ok("359.5E interpola entre 359E y 0E", m >= Math.min(a, b) - 1e-6 && m <= Math.max(a, b) + 1e-6,
     a + " / " + m + " / " + b);
  ok("lon 360 equivale a lon 0", Math.abs(ctx.rcAt(45, 360) - ctx.rcAt(45, 0)) < 1e-6);
  ok("lon negativa equivale a +360", Math.abs(ctx.rcAt(45, -90) - ctx.rcAt(45, 270)) < 1e-6,
     ctx.rcAt(45, -90) + " vs " + ctx.rcAt(45, 270));
  // El rango no basta: con la costura rota, rcAt(359.5) devuelve exactamente
  // rcAt(359), que TAMBIEN esta dentro del rango. Hay que exigir la
  // interpolacion exacta. Latitud entera -> fLat=0 -> solo interpola longitud.
  // lat -25 es donde el salto de la costura es mayor (0.03 GV).
  const s359 = ctx.rcAt(-25, 359), s0 = ctx.rcAt(-25, 0);
  ok("los dos lados de la costura difieren (si no, el test no prueba nada)",
     Math.abs(s359 - s0) > 1e-6, s359 + " vs " + s0);
  ok("359.5E es exactamente la media de 359E y 0E",
     Math.abs(ctx.rcAt(-25, 359.5) - (s359 + s0) / 2) < 1e-9,
     ctx.rcAt(-25, 359.5) + " vs " + ((s359 + s0) / 2));
  ok("359.99E practicamente vale lo de 0E",
     Math.abs(ctx.rcAt(-25, 359.99) - s0) < Math.abs(s359 - s0) * 0.02 + 1e-9);
  // Sin envolvente habria un salto brusco: comprobamos que no lo hay.
  let maxSalto = 0;
  for (let lo = 350; lo < 370; lo += 0.5) {
    const d = Math.abs(ctx.rcAt(45, lo) - ctx.rcAt(45, lo + 0.5));
    if (d > maxSalto) maxSalto = d;
  }
  ok("sin discontinuidad en el antimeridiano de Greenwich", maxSalto < 0.2, maxSalto);
}

console.log("\nrcAt — polos y bordes");
{
  // Nota: quitar el Math.max/min de la latitud NO cambia el resultado, porque
  // las guardas de i0 ya recortan. Es un mutante equivalente, no un hueco.
  ok("lat 90 se recorta a 89 sin romper", isFinite(ctx.rcAt(90, 0)), ctx.rcAt(90, 0));
  ok("lat -90 se recorta a -89 sin romper", isFinite(ctx.rcAt(-90, 0)), ctx.rcAt(-90, 0));
  ok("lat 89 y lat 90 dan lo mismo", Math.abs(ctx.rcAt(89, 0) - ctx.rcAt(90, 0)) < 1e-6);
  ok("en el polo la rigidez es baja", ctx.rcAt(89, 0) < 1.0, ctx.rcAt(89, 0));
  ok("en el ecuador es alta", ctx.rcAt(0, 80) > 10, ctx.rcAt(0, 80));
}

console.log("\nrcAt — la longitud importa de verdad");
{
  const canada = ctx.rcAt(50, 270), asia = ctx.rcAt(50, 150);
  ok("a 50N hay factor >4 entre Canada y Kamchatka", asia / canada > 4,
     canada + " vs " + asia);
}

console.log("\n" + (fail === 0 ? "TODO VERDE" : "HAY FALLOS") + " — " + pass + " pass, " + fail + " fail\n");
process.exit(fail === 0 ? 0 : 1);
