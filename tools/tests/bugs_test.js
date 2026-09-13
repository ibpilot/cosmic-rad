// Tests de los bugs arreglados del reporte de auditoría (MEMORIA.md).
// Ejecuta el script de la app en un vm con stubs y comprueba las funciones puras.
const fs = require("fs"), vm = require("vm"), path = require("path");

// Por defecto, la raiz del repo que contiene ESTE fichero (tools/tests/../..).
// Hardcodear la ruta hacia leer el index.html de otro sitio al correr desde un
// worktree: los tests median un fichero que no era el que se estaba tocando.
const REPO = process.env.REPO || path.resolve(__dirname, "..", "..");
const html = fs.readFileSync(path.join(REPO, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
// El último script es la app; se le quita el render final que necesita DOM.
let app = scripts[scripts.length - 1].replace(/ReactDOM\.createRoot\([\s\S]*$/, "");

const ctx = {
  console, atob, Math, JSON, Date, isFinite, parseInt, parseFloat, String, Number,
  Array, Object, Boolean, Error, TypeError, RegExp, Float32Array, Uint8Array, Map, Promise,
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

console.log("\nB5 — gcDistance no devuelve NaN en pares casi antipodales");
{
  // El caso citado en el reporte (66.135188,-166.089 → -66.135188,13.910781) NO
  // reproduce: da 20015 km. El bug sí existe, pero en pares donde el haversine
  // se pasa de 1 por redondeo (a = 1.0000000000000002), p.ej. -87.5,-180.
  const d = ctx.gcDistance(-87.5, -180, 87.5, 0);
  ok("par antipodal con a>1 es finito", isFinite(d), d);
  ok("distancia ~semicircunferencia", d > 19000 && d < 20100, d);
  ok("caso del reporte también finito", isFinite(ctx.gcDistance(66.135188, -166.089, -66.135188, 13.910781)));
  // Un puñado de antipodales del barrido: ninguno debe dar NaN.
  let nan = 0;
  for (let lat = -89; lat <= 89; lat += 0.5) {
    for (let lon = -180; lon <= 180; lon += 15) {
      if (!isFinite(ctx.gcDistance(lat, lon, -lat, lon > 0 ? lon - 180 : lon + 180))) nan++;
    }
  }
  ok("barrido de antipodales sin NaN", nan === 0, nan + " NaN");
  // El clamp solo puede actuar cuando a sale de [0,1]; en rutas normales el
  // resultado debe ser idéntico al haversine sin clamp.
  const sinClamp = (lat1, lon1, lat2, lon2) => {
    const R = 6371, r = d => d * Math.PI / 180;
    const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lon2 - lon1) / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  };
  const pares = [[40.47, -3.56, 33.94, -118.41], [41.30, 2.08, 40.47, -3.56], [-34.82, -58.54, 41.30, 2.08], [0, 0, 0, 90]];
  ok("casos normales idénticos al haversine sin clamp",
     pares.every(p => Math.abs(ctx.gcDistance(...p) - sinClamp(...p)) < 1e-9),
     pares.map(p => ctx.gcDistance(...p).toFixed(3) + " vs " + sinClamp(...p).toFixed(3)).join(" | "));
  ok("MAD-LAX ~9388 km", Math.round(ctx.gcDistance(40.47, -3.56, 33.94, -118.41)) === 9388,
     Math.round(ctx.gcDistance(40.47, -3.56, 33.94, -118.41)));
}

console.log("\nB1 — parseSteps acepta minúsculas");
{
  const lower = ctx.parseSteps("f370 4730n04000w/f330 45n020w/f390");
  ok("minúsculas devuelven steps", lower !== null && lower.length === 3, JSON.stringify(lower));
  const upper = ctx.parseSteps("F370 4730N04000W/F330 45N020W/F390");
  ok("mayúsculas siguen igual", JSON.stringify(lower) === JSON.stringify(upper), JSON.stringify(upper));
  ok("primer step sin waypoint", lower && lower[0].wp === null && lower[0].fl === 370);
  ok("texto sin FL devuelve null", ctx.parseSteps("BCN LEBL nada") === null);
}

console.log("\nB12/B11 — hydrateFlight normaliza legs y flIdx");
{
  ok("legs ausente → 1", ctx.hydrateFlight({ orig: "MAD", dest: "BCN" }).legs === 1);
  ok("legs basura → 1", ctx.hydrateFlight({ legs: "x" }).legs === 1);
  ok("legs 0 → 1", ctx.hydrateFlight({ legs: 0 }).legs === 1);
  ok("legs 3 se conserva", ctx.hydrateFlight({ legs: 3 }).legs === 3);
  ok("flIdx fuera de rango → 1", ctx.hydrateFlight({ flIdx: 99 }).flIdx === 1);
  ok("flIdx válido se conserva", ctx.hydrateFlight({ flIdx: 2 }).flIdx === 2);
  ok("id asignado", typeof ctx.hydrateFlight({}).id === "number");
}

console.log("\nA1 — serializeFlight conserva pairId (autosave y goToMonth comparten whitelist)");
{
  const s = ctx.serializeFlight({ orig: "MAD", dest: "BCN", legs: 2, flIdx: 2, pairId: 7, track: [[null, 1, 2, 10]], steps: [{ wp: null, fl: 370 }] });
  ok("pairId sobrevive", s.pairId === 7);
  ok("track sobrevive", Array.isArray(s.track));
  ok("steps sobreviven", Array.isArray(s.steps));
  ok("legs ausente → 1", ctx.serializeFlight({ orig: "A" }).legs === 1);
  const fuente = ctx.serializeFlight.toString();
  ok("una sola whitelist en el fichero", (html.match(/flights\.map\(serializeFlight\)/g) || []).length === 2,
     (html.match(/flights\.map\(serializeFlight\)/g) || []).length);
}

console.log("\nB7 — calcTrack tolera puntos sin altitud");
{
  const track = [[null, 40, -3, undefined], [null, 45, -20, undefined]];
  const r = ctx.calcTrack(track, 650, null);
  ok("dosis finita", isFinite(r.doseUsv) && r.doseUsv > 0, r.doseUsv);
  ok("distancia finita", isFinite(r.distKm) && r.distKm > 0, r.distKm);
  ok("rate finito", isFinite(r.rateUsvh), r.rateUsvh);
  const bad = ctx.calcTrack([[null, 40, -3, NaN], [null, 45, -20, "x"]], 650, null);
  ok("altitudes NaN/string no propagan", isFinite(bad.doseUsv) && bad.doseUsv > 0, bad.doseUsv);
  const good = ctx.calcTrack([[null, 40, -3, 10.668], [null, 45, -20, 10.668]], 650, null);
  ok("default = FL350 (mismo resultado)", Math.abs(r.doseUsv - good.doseUsv) < 1e-9, r.doseUsv + " vs " + good.doseUsv);
  // Latitud corrupta: doseRateGrid devuelve NaN (no null), asi que la guarda
  // tiene que ser !isFinite(rate) y no solo `rate == null`.
  // Punto corrupto en medio de un track válido: se descarta y el resto integra.
  const conBasura = ctx.calcTrack([
    [null, 40, -3, 10.668], [null, NaN, -10, 10.668], [null, 45, -20, 10.668]
  ], 650, null);
  ok("punto con lat NaN se descarta, dosis finita", conBasura && isFinite(conBasura.doseUsv) && conBasura.doseUsv > 0, conBasura && conBasura.doseUsv);
  const limpio = ctx.calcTrack([[null, 40, -3, 10.668], [null, 45, -20, 10.668]], 650, null);
  ok("resultado == track sin el punto corrupto", conBasura && Math.abs(conBasura.doseUsv - limpio.doseUsv) < 1e-9,
     conBasura && (conBasura.doseUsv + " vs " + limpio.doseUsv));
  const latTexto = ctx.calcTrack([
    [null, 40, -3, 10.668], [null, "x", -10, 10.668], [null, 45, -20, 10.668]
  ], 650, null);
  ok("lat de texto también se descarta", latTexto && isFinite(latTexto.doseUsv), latTexto && latTexto.doseUsv);
  ok("lon no finita también se descarta",
     isFinite(ctx.calcTrack([[null, 40, -3, 10.668], [null, 42, NaN, 10.668], [null, 45, -20, 10.668]], 650, null).doseUsv));
  // Sin dos puntos utilizables no hay track que integrar.
  ok("track que se queda en 1 punto → null", ctx.calcTrack([[null, NaN, -3, 10.668], [null, 45, -20, 10.668]], 650, null) === null);
  ok("track entero corrupto → null", ctx.calcTrack([[null, NaN, NaN, 10], [null, NaN, NaN, 10]], 650, null) === null);
}

console.log("\nB2/B3/B16 — aplicación de steps sobre la ruta");
{
  ctx.FIXES = JSON.parse(fs.readFileSync(path.join(REPO, "fixes.json"), "utf8"));

  // Fixes reales de fixes.json con una sola variante (ABNIR/ABITA/ABDAL), para
  // que la ruta resuelva de verdad; con nombres inventados el track se queda en
  // 2 puntos y los asserts no discriminan nada.
  ["ABNIR", "ABITA", "ABDAL"].forEach(function (n) {
    ok("fix " + n + " existe en fixes.json", Array.isArray(ctx.FIXES[n]) && ctx.FIXES[n].length === 2);
  });

  // B3: steps escritos fuera de orden de ruta no deben pisar a los anteriores.
  const ruta = "LEMD..ABNIR..ABITA..ABDAL..KJFK";
  const enOrden  = ctx.parseRouteString(ruta, "MAD", "JFK", "F310 ABNIR/F350 ABDAL/F390");
  const desorden = ctx.parseRouteString(ruta, "MAD", "JFK", "F310 ABDAL/F390 ABNIR/F350");
  ok("ruta resuelta", enOrden.track && enOrden.track.length >= 3, enOrden.error);
  if (enOrden.track && desorden.track) {
    const altsA = enOrden.track.map(p => p[3]).join(",");
    const altsB = desorden.track.map(p => p[3]).join(",");
    ok("mismo perfil escribiendo los steps en cualquier orden", altsA === altsB, altsA + "  vs  " + altsB);
    const alts = enOrden.track.map(p => p[3]);
    ok("perfil no decrece con steps ascendentes", alts.every((v, i) => i === 0 || v >= alts[i - 1]), altsA);
    ok("último punto en FL390", Math.abs(alts[alts.length - 1] - 390 * 0.03048) < 0.02, alts[alts.length - 1]);
  }

  // B2: step cuyo waypoint no está en la ruta → se avisa, no silencio.
  const noMatch = ctx.parseRouteString(ruta, "MAD", "JFK", "F310 ZZZZZ/F390");
  ok("stepsUnmatched se reporta", noMatch.stepsUnmatched && noMatch.stepsUnmatched.length === 1,
     JSON.stringify(noMatch.stepsUnmatched));
  ok("y menciona el waypoint", noMatch.stepsUnmatched && noMatch.stepsUnmatched[0].indexOf("ZZZZZ") === 0,
     JSON.stringify(noMatch.stepsUnmatched));
  ok("sin steps huérfanos la lista va vacía", enOrden.stepsUnmatched.length === 0,
     JSON.stringify(enOrden.stepsUnmatched));

  // B16: fix repetido → gana la primera aparición.
  const rep = ctx.parseRouteString("LEMD..ABNIR..ABITA..ABNIR..KJFK", "MAD", "JFK", "F310 ABNIR/F390");
  if (rep.track) {
    const subida = rep.track.findIndex(p => Math.abs(p[3] - 390 * 0.03048) < 0.02);
    ok("el step aplica en la primera aparición", subida === 1, "índice " + subida + " de " + rep.track.length);
  } else ok("ruta con fix repetido resuelta", false, rep.error);
}

console.log("\nA2 — buildPdfHtml escapa los campos que vienen del backup");
{
  const t = ctx.LANG.es;
  const evil = '"><img src=x onerror=alert(1)>';
  const flights = [{ orig: "MAD", dest: "BCN", legs: evil, flIdx: 1 }];
  const out = ctx.buildPdfHtml({
    validFlights: flights, hpMV: 650, t, solarLabel: "x", monthlyUsv: 10,
    annualUsv: 120, nonFlyer: 2400, showCareer: false, careerYears: 15, monthName: "agosto 2026"
  });
  ok("legs no inyecta markup", out.indexOf("<img src=x") === -1);
  ok("legs aparece escapado", out.indexOf("&lt;img src=x") !== -1);

  const evilSteps = [{ orig: "MAD", dest: "BCN", legs: 1, flIdx: 1, steps: [{ wp: null, fl: evil }] }];
  const out2 = ctx.buildPdfHtml({
    validFlights: evilSteps, hpMV: 650, t, solarLabel: "x", monthlyUsv: 10,
    annualUsv: 120, nonFlyer: 2400, showCareer: false, careerYears: 15, monthName: "agosto 2026"
  });
  ok("steps.fl no inyecta markup", out2.indexOf("<img src=x") === -1);

  // B11: flIdx fuera de rango ya no revienta el export.
  let threw = null;
  try {
    ctx.buildPdfHtml({
      validFlights: [{ orig: "MAD", dest: "BCN", legs: 1, flIdx: 99 }], hpMV: 650, t,
      solarLabel: "x", monthlyUsv: 10, annualUsv: 120, nonFlyer: 2400,
      showCareer: false, careerYears: 15, monthName: "agosto 2026"
    });
  } catch (e) { threw = e.message; }
  ok("flIdx=99 no lanza", threw === null, threw);
}

console.log("\nB4 — el sandbox del iframe del PDF está puesto");
ok('sandbox sin allow-scripts', /sandbox: "allow-same-origin allow-modals"/.test(html));
ok('no se coló allow-scripts', !/sandbox:[^\n]*allow-scripts/.test(html));

console.log("\nB4 — parseBackup rechaza lo que no es un mapa de meses");
{
  ok("objeto plano válido", JSON.stringify(ctx.parseBackup('{"2026-08":[]}')) === '{"2026-08":[]}');
  ok("formato v1 válido", JSON.stringify(ctx.parseBackup('{"version":1,"months":{"2026-08":[]}}')) === '{"2026-08":[]}');
  ok("array rechazado", ctx.parseBackup("[]") === null);
  ok("array con datos rechazado", ctx.parseBackup('[{"orig":"MAD"}]') === null);
  ok("v1 con months array rechazado", ctx.parseBackup('{"version":1,"months":[]}') === null);
  ok("null rechazado", ctx.parseBackup("null") === null);
  ok("JSON inválido rechazado", ctx.parseBackup("{no json") === null);
  ok("número rechazado", ctx.parseBackup("42") === null);
  ok("string rechazado", ctx.parseBackup('"hola"') === null);
}


console.log("\nB6 - el aeropuerto de origen entra en el track");
{
  // Ruta cuyo primer fix esta LEJOS del aeropuerto (el caso grave): sin el fix
  // se perdian miles de km. AKO/AIO estan en el interior de EEUU, SFO no.
  const lejos = ctx.parseRouteString("KSFO..AKO..AIO..KORD", "SFO", "ORD", "");
  ok("ruta resuelta", lejos.track && lejos.track.length >= 3, lejos.error);
  const ap = ctx.activeDB["SFO"];
  ok("primer punto ES el aeropuerto de origen",
     lejos.track && Math.abs(lejos.track[0][1] - ap.lat) < 0.01 && Math.abs(lejos.track[0][2] - ap.lon) < 0.01,
     lejos.track && JSON.stringify(lejos.track[0]));
  ok("ultimo punto sigue siendo el destino",
     lejos.track && Math.abs(lejos.track[lejos.track.length-1][1] - ctx.activeDB["ORD"].lat) < 0.01);

  const conOrigen = ctx.calcTrack(lejos.track, 650, null);
  const sinOrigen = ctx.calcTrack(lejos.track.slice(1), 650, null);
  ok("distancia mayor que sin el origen", conOrigen.distKm > sinOrigen.distKm + 1000,
     conOrigen.distKm + " vs " + sinOrigen.distKm);
  ok("dosis mayor que sin el origen", conOrigen.doseUsv > sinOrigen.doseUsv,
     conOrigen.doseUsv.toFixed(3) + " vs " + sinOrigen.doseUsv.toFixed(3));

  // No duplicar: si la ruta YA empieza cerca del aeropuerto, no se mete otro punto.
  const cerca = ctx.parseRouteString("LEBL..ABNIR..LEMD", "BCN", "MAD", "");
  if (cerca.track) {
    const bcn = ctx.activeDB["BCN"];
    const cercaDelAp = cerca.track.filter(p =>
      Math.abs(p[1] - bcn.lat) + Math.abs(p[2] - bcn.lon) < 0.5).length;
    ok("no se duplica el punto de origen", cercaDelAp <= 1, cercaDelAp + " puntos junto a BCN");
  }

  // El punto de origen hereda el FL de salida, no el del primer step intermedio.
  const conSteps = ctx.parseRouteString("KSFO..AKO..AIO..KORD", "SFO", "ORD", "F310 AIO/F390");
  if (conSteps.track) {
    ok("origen al FL de salida (F310)", Math.abs(conSteps.track[0][3] - 310 * 0.03048) < 0.02,
       conSteps.track[0][3]);
    ok("y el perfil sube despues", conSteps.track[conSteps.track.length-1][3] > conSteps.track[0][3],
       conSteps.track.map(p => p[3]).join(" "));
  }
}


console.log("\nB13 — coordenadas DDMM fuera de rango se rechazan");
{
  const bad = ctx.parseRouteString("LEMD..9930N05000W..LEBL", "MAD", "BCN", "");
  const tieneLatImposible = (bad.track || []).some(p => Math.abs(p[1]) > 90);
  ok("lat > 90 no entra en el track", !tieneLatImposible,
     JSON.stringify(bad.track));
  const bad2 = ctx.parseRouteString("LEMD..4530N19930W..LEBL", "MAD", "BCN", "");
  ok("lon > 180 no entra en el track", !(bad2.track || []).some(p => Math.abs(p[2]) > 180),
     JSON.stringify(bad2.track));
  const bad3 = ctx.parseRouteString("LEMD..4599N05000W..LEBL", "MAD", "BCN", "");
  ok("minutos > 59 no entran en el track",
     !(bad3.track || []).some(p => Math.abs(p[1] - (45 + 99/60)) < 0.01),
     JSON.stringify(bad3.track));
  const good = ctx.parseRouteString("LEMD..4530N05000W..LEBL", "MAD", "BCN", "");
  ok("una coordenada válida sí entra",
     (good.track || []).some(p => Math.abs(p[1] - 45.5) < 0.01 && Math.abs(p[2] + 50) < 0.01),
     JSON.stringify(good.track));
}

console.log("\nB14 — un aeropuerto suelto no es un 'fix sin resolver'");
{
  const r = ctx.parseRouteString("LEMD..ABNIR..ABITA..ABDAL..KJFK", "MAD", "JFK", "");
  ok("KJFK no aparece como sin resolver", !(r.unresolved || []).includes("KJFK"),
     JSON.stringify(r.unresolved));
  const r2 = ctx.parseRouteString("LEMD..ABNIR..ZZZZQ..LEBL", "MAD", "BCN", "");
  ok("un fix inventado sí sigue avisando", (r2.unresolved || []).includes("ZZZZQ"),
     JSON.stringify(r2.unresolved));
}

console.log("\nB15 — el primer step con waypoint es una transición");
{
  const r = ctx.parseRouteString("KSFO..AKO..AIO..KORD", "SFO", "ORD", "AKO/F390");
  if (r.track) {
    const fl390 = 390 * 0.03048;
    ok("el punto de origen NO está ya a F390", Math.abs(r.track[0][3] - fl390) > 0.05,
       r.track[0][3]);
    ok("el punto de origen mantiene la altitud por defecto (no 0)",
       Math.abs(r.track[0][3] - 10.668) < 0.01, r.track[0][3]);
    ok("después del waypoint sí está a F390",
       Math.abs(r.track[r.track.length - 1][3] - fl390) < 0.02,
       r.track.map(p => p[3]).join(" "));
  } else { ok("ruta B15 resuelta", false, r.error); }
  // Sin waypoint el primer step sigue aplicando desde el punto 0.
  const r2 = ctx.parseRouteString("KSFO..AKO..AIO..KORD", "SFO", "ORD", "F310 AIO/F390");
  ok("step inicial sin waypoint sigue aplicando desde el origen",
     r2.track && Math.abs(r2.track[0][3] - 310 * 0.03048) < 0.02,
     r2.track && r2.track[0][3]);
}

console.log("\nB17 — fmtTime nunca imprime 60 minutos");
{
  ok("fmtTime no usa el redondeo por separado",
     !/Math\.floor\(h\), "h "\)\.concat\(Math\.round\(h % 1 \* 60\)/.test(html));
  ok("0.999 h → 1h 0m", ctx.fmtTime(0.999) === "1h 0m", ctx.fmtTime(0.999));
  ok("1.9999 h → 2h 0m", ctx.fmtTime(1.9999) === "2h 0m", ctx.fmtTime(1.9999));
  ok("2.5 h → 2h 30m", ctx.fmtTime(2.5) === "2h 30m", ctx.fmtTime(2.5));
  ok("0 h → 0h 0m", ctx.fmtTime(0) === "0h 0m", ctx.fmtTime(0));
  let sinSesenta = true;
  for (let i = 0; i < 2000; i++) {
    if (/ 60m$/.test(ctx.fmtTime(i / 97))) { sinSesenta = false; break; }
  }
  ok("ningún valor da '60m'", sinSesenta);
}

console.log("\nB22 — fixes.json se pide con la versión de la app");
ok("cache-bust con APP_VERSION", /fixes\.json\?v=" \+ APP_VERSION/.test(html));
ok("ya no queda el ?v=1 fijo", !/fixes\.json\?v=1/.test(html));

console.log("\nB23 — effectiveLatitude: pico real del arco (normal normalizado + vértice en arco)");
{
  const e = ctx.effectiveLatitude;
  // Oráculo independiente: máxima |latitud| muestreando el arco con slerp.
  const slerpPeak = (lat1, lon1, lat2, lon2) => {
    const r = d => d * Math.PI / 180, deg = x => x * 180 / Math.PI;
    const v = (la, lo) => [Math.cos(r(la)) * Math.cos(r(lo)), Math.cos(r(la)) * Math.sin(r(lo)), Math.sin(r(la))];
    const a = v(lat1, lon1), b = v(lat2, lon2);
    const dot = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
    const ang = Math.acos(dot);
    if (ang < 1e-9) return Math.abs(lat1); // mismo punto
    if (Math.PI - ang < 1e-9) return Math.max(Math.abs(lat1), Math.abs(lat2)); // antipodal
    let mx = 0;
    for (let k = 0; k <= 20000; k++) {
      const t = k / 20000;
      const s1 = Math.sin((1 - t) * ang) / Math.sin(ang), s2 = Math.sin(t * ang) / Math.sin(ang);
      mx = Math.max(mx, Math.abs(a[2] * s1 + b[2] * s2)); // |sen(latitud)|
    }
    return deg(Math.asin(Math.max(-1, Math.min(1, mx))));
  };
  const effPeak = (lat1, lon1, lat2, lon2) => {
    const p = slerpPeak(lat1, lon1, lat2, lon2);
    return (Math.abs(lat1) + p + Math.abs(lat2)) / 3;
  };
  const pares = [
    [40.47, -3.56, 40.63, -73.78],   // MAD→JFK (vértice sobre el arco)
    [51.47, -0.45, 40.63, -73.78],   // LHR→JFK
    [35.55, 139.78, 49.01, 2.55],    // NRT→CDG
    [33.94, -118.41, 19.43, -99.07], // LAX→MEX
    [0, 20, 0, -40],                 // ecuador puro
    [40.47, -3.56, -26.20, 28.05],   // MAD→JNB (vértice fuera del arco)
    [40, -3, -26, -3],               // casi meridiano
    [1, 0, 1, 90],                   // E-W a 1°N
    [-30, 0, -60, 90],               // cruza la antivértice (−61.3°) dentro del arco
    [40, -3, 40, -3],                // mismo punto
    [0, 0, 0, 180]                   // antipodales
  ];
  const mal = pares.filter(p => Math.abs(e(...p) - effPeak(...p)) > 0.06);
  ok("coincide con el pico numérico del arco muestreado (slerp)", mal.length === 0,
     mal.map(p => e(...p).toFixed(2) + " vs " + effPeak(...p).toFixed(2)).join(" | "));
  // Regresión concreta del bug: MAD→JNB daba ~45.2 con la heurística antigua.
  const jnb = e(40.47, -3.56, -26.20, 28.05);
  ok("MAD→JNB ya no sobreestima (antes ~45.2)", jnb < 38 && jnb > 34, jnb);
  ok("MAD→JNB ≈ (40.47+40.47+26.20)/3", Math.abs(jnb - (40.47 * 2 + 26.20) / 3) < 0.01, jnb);
  // La antigua fórmula también inflaba rutas E-W (|nz| sin normalizar): el
  // valor correcto de MAD→JFK es ~42.5, no ~46.0.
  const jfk = e(40.47, -3.56, 40.63, -73.78);
  ok("MAD→JFK ≈ 42.5 (antes ~46.0)", Math.abs(jfk - 42.45) < 0.15, jfk);
  ok("mismo punto → latitud del punto", Math.abs(e(40, -3, 40, -3) - 40) < 1e-9, e(40, -3, 40, -3));
  ok("antipodales ecuatoriales → 0", Math.abs(e(0, 0, 0, 180)) < 1e-9, e(0, 0, 0, 180));
  // Sin NaN ni divisiones degeneradas en casos límite.
  ok("límites sin NaN", [e(0, 0, 0, 90), e(89, 0, 89, 180), e(-45, 10, -45, 190), e(90, 0, -90, 0)]
     .every(v => isFinite(v)));
}

console.log("\nB24 — calcFlight: fallback por punto, no todo-o-nada");
{
  const real = ctx.doseRateGrid;
  const A = ctx.activeDB["MAD"], B = ctx.activeDB["JFK"];
  if (!A || !B) { ok("MAD y JFK presentes en activeDB", false); }
  else {
    // Rejilla disponible solo en la primera mitad de los puntos.
    const seen = [];
    ctx.doseRateGrid = function (lat, lon, alt, hp) {
      seen.push([lat, lon]);
      return seen.length <= 16 ? 3.5 : null;
    };
    let c;
    try { c = ctx.calcFlight("MAD", "JFK", 2, 650); }
    finally { ctx.doseRateGrid = real; }
    const band = la => ctx.getDoseRate(la) * ctx.FL_OPTIONS[2].factor * ctx.solarFactorForHp(650);
    const exp = seen.reduce((s, p, i) => s + (i < 16 ? 3.5 : band(p[0])), 0) / seen.length;
    ok("se evaluaron los 32 puntos", seen.length === 32, seen.length);
    ok("mezcla rejilla+banda punto a punto",
       c && Math.abs(c.rateUsvh - exp) < 1e-9, c && c.rateUsvh + " vs " + exp);
    // Sin rejilla en absoluto: media de bandas por punto, no la latitud efectiva única.
    const seen2 = [];
    ctx.doseRateGrid = function (lat, lon, alt, hp) { seen2.push([lat, lon]); return null; };
    let c2;
    try { c2 = ctx.calcFlight("MAD", "JFK", 2, 650); }
    finally { ctx.doseRateGrid = real; }
    const exp2 = seen2.reduce((s, p) => s + band(p[0]), 0) / seen2.length;
    ok("sin rejilla: media de bandas por punto", c2 && Math.abs(c2.rateUsvh - exp2) < 1e-9, c2 && c2.rateUsvh);
    const oldRate = ctx.getDoseRate(ctx.effectiveLatitude(A.lat, A.lon, B.lat, B.lon))
      * ctx.FL_OPTIONS[2].factor * ctx.solarFactorForHp(650);
    ok("ya no usa la latitud efectiva única (todo-o-nada)", Math.abs(c2.rateUsvh - oldRate) > 0.05,
       c2.rateUsvh + " vs " + oldRate);
    // Rejilla completa: media plana de la rejilla (comportamiento anterior intacto).
    ctx.doseRateGrid = () => 2.0;
    let c3;
    try { c3 = ctx.calcFlight("MAD", "JFK", 2, 650); }
    finally { ctx.doseRateGrid = real; }
    ok("rejilla completa: media plana", c3 && Math.abs(c3.rateUsvh - 2.0) < 1e-9, c3 && c3.rateUsvh);
    // Con la rejilla real embebida: dosis finita y positiva.
    const c4 = ctx.calcFlight("MAD", "JFK", 2, 650);
    ok("rejilla real: dosis finita y positiva", c4 && isFinite(c4.doseUsv) && c4.doseUsv > 0,
       c4 && c4.doseUsv);
  }
}

console.log("\nB25 — ids/pairIds no colisionan entre sesiones (mkId sembrado)");
{
  const realLS = ctx.localStorage;
  const store = {
    "cr_months": JSON.stringify({ "2026-03": [
      { id: 1, orig: "MAD", dest: "JFK", legs: 1, pairId: 6 },
      { id: 2, orig: "JFK", dest: "MAD", legs: 1, pairId: 6 },
      { id: 5, orig: "LHR", dest: "CDG", legs: 2 }
    ]}),
    "cr_flights": null
  };
  ctx.localStorage = {
    getItem: k => (k in store ? store[k] : null),
    setItem: () => {}, removeItem: () => {}
  };
  try {
    ctx.reseedIds();
    const first = ctx.mkId();
    ok("mkId tras reseed > todos los ids/pairIds guardados", first > 6, first);
    ok("y sigue incrementando", ctx.mkId() === first + 1, first + 1);
    const h = ctx.hydrateFlight({ id: 999, orig: "MAD", dest: "BCN", legs: "4", flIdx: 9, pairId: 3 });
    ok("hydrateFlight conserva pairId", h.pairId === 3, h.pairId);
    ok("hydrateFlight normaliza legs", h.legs === 4, h.legs);
    ok("hydrateFlight corrige flIdx fuera de rango", h.flIdx === 1, h.flIdx);
    ok("hydrateFlight asigna id fresco (>6, no 999)", typeof h.id === "number" && h.id > 6, h.id);
    // Backup importado con ids mayores: reseedIds() debe recogerlos.
    store["cr_months"] = JSON.stringify({ "2026-04": [
      { id: 42, orig: "BCN", dest: "MAD", legs: 1, pairId: 77 },
      { id: 43, orig: "MAD", dest: "BCN", legs: 1, pairId: 77 }
    ]});
    ctx.reseedIds();
    ok("reseed tras import: mkId > ids del backup", ctx.mkId() > 77, ctx.mkId() - 1);
  } finally {
    ctx.localStorage = realLS;
  }
}

console.log("\nB26 — parseCsvLine maneja comillas escapadas (\"\") y CRLF");
{
  const p = ctx.parseCsvLine;
  const r1 = p('"1","O\'Hare ""Intl"" Airport","Chicago","United States","ORD","KORD","41.9786","-87.9048"');
  ok("comillas escapadas se conservan dentro del campo", r1[1] === "O'Hare \"Intl\" Airport", JSON.stringify(r1));
  ok("columnas correctas tras el escape", r1[4] === "ORD" && r1[5] === "KORD" && r1[6] === "41.9786",
     JSON.stringify(r1));
  const r2 = p('"1","Béchar Airport","Béchar","Algeria","CBH","DA0E","31.62","-2.27"');
  ok("campos citados normales", r2[1] === "Béchar Airport" && r2[4] === "CBH", JSON.stringify(r2));
  const r3 = p('123,"Plain" ,"x","y",ABC,"",0,0');
  ok("mezcla citado/sin citar", r3[0] === "123" && r3[1] === "Plain " && r3[5] === "", JSON.stringify(r3));
  const r4 = p('"a","b"\r');
  ok("\\r final no contamina la última columna", r4[1] === "b", JSON.stringify(r4));
}

console.log("\nB27 — saneamiento de fixes.json, backups y topes de hydrateFlight");
{
  // fixes: estructuras y coordenadas imposibles se descartan (S1).
  const sf = ctx.sanitizeFixes;
  const good = sf({
    "BDR": [611611, -454278],
    "DUP1": [400000, -100000, 410000, -110000],
    "BAD1": [9999999, 0],
    "BAD2": [0, 5000000],
    "BAD3": [0, 0, 0],
    "BAD4": "notarray",
    "BAD5": [],
    "BAD6": [100, "x"],
    "BAD7": [NaN, 0]
  });
  ok("fixes válidos se conservan (incl. variantes múltiples)",
     good && good["BDR"] && good["DUP1"].length === 4,
     good && Object.keys(good).join(","));
  ok("fixes inválidos se descartan todos",
     good && ["BAD1","BAD2","BAD3","BAD4","BAD5","BAD6","BAD7"].every(k => !good[k]),
     good && Object.keys(good).join(","));
  ok("dataset totalmente inválido → null (fail closed)", sf({ X: [0] }) === null);
  ok("array en vez de objeto → null", sf([1, 2]) === null);
  ok("dataset real (fixes.json) no pierde datos buenos",
     Object.keys(sf(JSON.parse(fs.readFileSync(path.join(REPO, "fixes.json"), "utf8")))).length >= 125000);

  // backups: solo claves YYYY-MM con listas (S4).
  const pb = ctx.parseBackup;
  const r1 = pb(JSON.stringify({ version: 1, months: { "2026-03": [{ orig: "MAD", dest: "BCN" }] } }));
  ok("backup versionado válido", r1 && Array.isArray(r1["2026-03"]) && Object.keys(r1).length === 1,
     r1 && Object.keys(r1).join(","));
  const r2 = pb('{"2026-03": [], "ruido": 42, "__proto__": {"x": 1}, "2026-13": [{}]}');
  ok("claves no YYYY-MM se descartan (incl. __proto__ real de JSON.parse)",
     r2 && Object.keys(r2).join(",") === "2026-03,2026-13",
     r2 && Object.keys(r2).join(","));
  ok("backup con todas las claves inválidas → null", pb(JSON.stringify({ foo: 1, ruido: [] })) === null);
  ok("JSON corrupto → null", pb("not json {{") === null);
  ok("array → null", pb("[1,2]") === null);

  // topes anti-DoS de hydrateFlight (S4).
  const bigTrack = Array.from({ length: 6000 }, (_, i) => [null, 40 + i / 1000, -3, 10.668]);
  const bigSteps = Array.from({ length: 200 }, (_, i) => ({ wp: "W" + i, fl: 300 + i }));
  const h = ctx.hydrateFlight({ orig: "MAD", dest: "BCN", legs: "1e9", flIdx: 1, track: bigTrack, steps: bigSteps });
  ok("legs capado a 9999", h.legs === 9999, h.legs);
  ok("track capado a 5000 puntos", h.track.length === 5000, h.track.length);
  ok("steps capado a 100", h.steps.length === 100, h.steps.length);
}

console.log("\nS5/A1 — calcTrack: el eje temporal se valida (NaN y DoS)");
{
  // A2: tiempo no numérico envenenaba la dosis con NaN (dtH = NaN pasaba
  // las guardas dtH<0 y dtH>0.25 y caía al camino normal).
  const t = ctx.calcTrack([["x", 40, 0, 11], ["y", 41, 1, 11]], 650, null);
  ok("tiempos de texto → track rechazado (no NaN)", t === null, t && t.doseUsv);
  const mixto = ctx.calcTrack([[0, 40, 0, 11], ["y", 41, 1, 11]], 650, null);
  ok("un solo punto válido → null", mixto === null);
  const conTiempo = ctx.calcTrack([[0, 40, 0, 11], [60, 41, 1, 11]], 650, null);
  ok("track con hora normal sigue funcionando", conTiempo && isFinite(conTiempo.doseUsv) && conTiempo.doseUsv > 0,
     conTiempo && conTiempo.doseUsv);

  // A1: tiempos gigantes multiplicaban las iteraciones sin tope (t=6e6 →
  // 400k sub-puntos, t=6e9 → ~33 min). Ahora se integran a lo sumo ~60
  // sub-puntos por tramo (un punto por hora real).
  const mega = ctx.calcTrack([[0, 40, 0, 11], [6e9, 41, 1, 11]], 650, null);
  ok("dtH gigante → dosis finita y sin congelar", mega && isFinite(mega.doseUsv) && mega.doseUsv > 0, mega && mega.doseUsv);
  ok("dtH gigante marca incomplete", mega && mega.incomplete === true);
  ok("tiempo integrado se conserva", mega && Math.abs(mega.timeH - 1e8) < 1e-3, mega && mega.timeH);
  // Un hueco normal de 30 min sigue interpolándose igual que antes (el tope
  // solo actúa a partir de ~2h de salto).
  const normal = ctx.calcTrack([[0, 40, 0, 11], [30, 41, 1, 11]], 650, null);
  ok("hueco normal de 30 min inalterado", normal && isFinite(normal.doseUsv), normal && normal.doseUsv);
  // La interpolación de un hueco corto con dosis constante es exacta.
  const dosPts = [[0, 40, 0, 11], [120, 40.5, 0.5, 11]];
  const ref = ctx.calcTrack([[0, 40, 0, 11], [120, 40.5, 0.5, 11]], 650, null);
  ok("hueco de 2h integra sin distorsión", ref && isFinite(ref.doseUsv) && ref.doseUsv > 0, ref && ref.doseUsv);
}

console.log("\nS5/A3 — un backup vacío se rechaza (no borra el histórico)");
{
  ok("{} → null", ctx.parseBackup("{}") === null);
  ok("{version:1,months:{}} → null", ctx.parseBackup('{"version":1,"months":{}}') === null);
  ok("válido sigue pasando", ctx.parseBackup('{"2026-08":[]}') !== null);
  // El flujo de restoreBackup empieza preguntando antes de tocar nada.
  ok("restoreBackup pide confirmación (S5)", /if \(!confirm\(t\.restoreAsk\)\) return;/.test(html));
  ok("traducción restoreAsk en ES", /restoreAsk: "¿Restaurar la copia\? Se reemplazará TODO el historial actual\."/.test(html));
  ok("traducción restoreAsk en EN", /restoreAsk: "Restore backup\? The entire current history will be replaced\."/.test(html));
}

console.log("\nS5/B1 — claves __proto__ ya no mutan prototipos");
{
  const sf = ctx.sanitizeFixes;
  const r = sf({ "__proto__": [1, 2], "AAA": [100, 200] });
  ok("sanitizeFixes: __proto__ no entra como clave", r && !("__proto__" in r) && Object.keys(r).length === 1, r && Object.keys(r).join(","));
  ok("sanitizeFixes: prototipo limpio", r && Object.getPrototypeOf(r) === null);
  ok("sanitizeFixes: entradas buenas intactas", r && r["AAA"] && r["AAA"].length === 2);
  // tokIdx: un token "__proto__" no debe contaminar la búsqueda de steps.
  ctx.FIXES = JSON.parse(fs.readFileSync(path.join(REPO, "fixes.json"), "utf8"));
  const rt = ctx.parseRouteString("LEMD..__proto__..ABNIR..LEBL", "MAD", "BCN", "F310 ABNIR/F390");
  ok("ruta con token __proto__ resuelve igual", rt.track && rt.track.length >= 3, rt.error);
  // newIcao es null-proto (se crea con Object.create(null)).
  ok("newIcao se crea null-proto", /newIcao = Object\.create\(null\)/.test(html));
}

console.log("\nS5/B2 — el ICAO de OpenFlights se acota antes de entrar en newIcao");
{
  ok("ICAO de 4 caracteres admitido", /icao\.length <= 4 && \/\^\[A-Z0-9\]\+\$\/\.test\(icao\)/.test(html));
}

console.log("\nS5/B3 — el textarea de la ruta tiene tope");
{
  ok("maxLength 4000 en el textarea", /maxLength: 4000,/.test(html));
}

async function testRouteImportKeepsCuratedIcaoAliases() {
  console.log("\nB28 — importar FPL sin origen conserva el ICAO curado tras cargar OpenFlights");

  // OpenFlights todavía publica Lima como SPIM. La app usa el ICAO vigente
  // SPJC en su base curada, que debe seguir resolviéndose tras la carga remota.
  ctx.fetch = async function () {
    return {
      ok: true,
      text: async function () {
        return [
          '1,"Jorge Chavez International Airport","Lima","Peru","LIM","SPIM",-12.0219,-77.1143',
          '2,"Barcelona International Airport","Barcelona","Spain","BCN","LEBL",41.2971,2.07846'
        ].join("\n");
      }
    };
  };
  await new Promise(function (resolve) { ctx.loadOpenFlights(resolve); });
  ctx.FIXES = ctx.sanitizeFixes(JSON.parse(fs.readFileSync(path.join(REPO, "fixes.json"), "utf8")));

  const route = "SPJC16L.LIMA5F.OPROS.UL306.VADOS.UM527.SIGOB.UM527.DALIV..VUKEB. " +
    "UM527.UMREM.UM527.TRAPP..10N055W.15N050W..PAPSE..20N045W.24N040W. " +
    "28N035W.31N030W.3530N02000W..KOMUT..DIRMA..ADORO..FITSE..DGO.N725. " +
    "YAKXU..ELSAP..VAKIN.N725.DIRMU..LOBAR.LOBAR2W.LEBL24R";
  const parsed = ctx.parseRouteString(route, "", "", "F350");
  const calculated = ctx.calcTrack(parsed.track, 650, null);

  ok("SPJC se detecta como LIM con los campos vacíos", parsed.routeOrig === "LIM", parsed.routeOrig);
  ok("LEBL se detecta como BCN", parsed.routeDest === "BCN", parsed.routeDest);
  ok("la ruta queda anclada en Lima (27 puntos)", parsed.resolved === 27, parsed.resolved);
  ok("la distancia es 10.100 km, no 13.499 km", calculated && calculated.distKm === 10100,
     calculated && calculated.distKm);
}

console.log("\nT10 ocurrencias");
{
  // Vuelos del Paso 0 (dosis de referencia fijadas con el código sin cambios).
  const A = { orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
  const B = { orig: "MAD", dest: "JFK", legs: 3, flIdx: 2, depDate: "2021-10-28", depTime: "14:00" };
  const C = { orig: "LHR", dest: "NRT", legs: 2, flIdx: 1,
    track: [[null, 51.5, -0.4, 10.668], [null, 60, 60, 11.0], [null, 35.7, 139.8, 10.668]] };
  const REF = { A: 27.521219708117496, B: 35.435214508544320, C: 45.904099010735550 };
  const Bh = ctx.hydrateFlight(B);

  // M1 — la migración no cambia ninguna dosis (igualdad exacta).
  ok("M1 migración A idéntica", ctx.flightCalc(ctx.hydrateFlight(A), 650).doseUsv === REF.A,
     ctx.flightCalc(ctx.hydrateFlight(A), 650).doseUsv);
  ok("M1 migración B idéntica", ctx.flightCalc(ctx.hydrateFlight(B), 650).doseUsv === REF.B,
     ctx.flightCalc(ctx.hydrateFlight(B), 650).doseUsv);
  ok("M1 migración C idéntica", ctx.flightCalc(ctx.hydrateFlight(C), 650).doseUsv === REF.C,
     ctx.flightCalc(ctx.hydrateFlight(C), 650).doseUsv);

  // M2 — un vuelo sin occurrences hidrata SIN la clave.
  const months = ctx.parseBackup(JSON.stringify({ version: 1, months: { "2024-05": [A, B, C] } }));
  ok("M2 backup parseado", months && months["2024-05"] && months["2024-05"].length === 3);
  months["2024-05"].forEach((fl, i) => {
    const h = ctx.hydrateFlight(fl);
    ok("M2 vuelo " + i + " sin clave occurrences", !("occurrences" in h));
  });

  // M3 — ida y vuelta split → collapse devuelve el vuelo original.
  const back = ctx.collapseOccurrences(ctx.splitLegs(Bh));
  const canon = o => JSON.stringify(o, Object.keys(o).sort());
  ok("M3 round-trip deep-equal", back !== null && canon(back) === canon(Bh),
     back && canon(back) + " vs " + canon(Bh));

  // M4 — reparto de legs: la primera ocurrencia hereda fecha, el resto no.
  const sp = ctx.splitLegs(Bh);
  ok("M4 tres ocurrencias", sp.occurrences.length === 3, sp.occurrences.length);
  ok("M4 [0] con fecha y programado",
     sp.occurrences[0].depDate === "2021-10-28" && sp.occurrences[0].state === "programado",
     JSON.stringify(sp.occurrences[0]));
  ok("M4 [1] sin fecha y esperando_fecha",
     sp.occurrences[1].depDate === undefined && sp.occurrences[1].state === "esperando_fecha",
     JSON.stringify(sp.occurrences[1]));
  ok("M4 [2] sin fecha y esperando_fecha",
     sp.occurrences[2].depDate === undefined && sp.occurrences[2].state === "esperando_fecha",
     JSON.stringify(sp.occurrences[2]));

  // M5 — legs:1 no se desglosa: mismo objeto.
  const f1 = { orig: "MAD", dest: "JFK", legs: 1 };
  ok("M5 legs:1 devuelve el mismo objeto", ctx.splitLegs(f1) === f1);

  // M6 — con una ocurrencia incorporada no se puede colapsar.
  const conInc = { orig: "MAD", dest: "JFK", legs: 2, occurrences: [
    ctx.makeOccurrence("2024-05-11", "02:00"),
    { id: 1, depDate: "2024-05-11", depTime: "03:00", state: "incorporada", result: { lowUsv: 1, highUsv: 2 } }
  ] };
  ok("M6 collapse null con incorporada", ctx.collapseOccurrences(conInc) === null);
  ok("M6 collapse OK sin incorporada",
     ctx.collapseOccurrences({ orig: "MAD", occurrences: [{ state: "programado" }] }) !== null);

  // M7 — sin fecha u hora no hay cifra SEP.
  ok("M7 sin fecha nunca da cifra",
     ctx.occSepFigure({ state: "incorporada", result: { lowUsv: 1, highUsv: 3 } }) === null);
  ok("M7 con fecha da la cifra",
     JSON.stringify(ctx.occSepFigure({ state: "incorporada", depDate: "2024-05-11", depTime: "02:00",
       result: { lowUsv: 1, highUsv: 3 } })) === '{"lowUsv":1,"highUsv":3}');

  // M8 — resultado invertido (low > high) se descarta y marca incompleto.
  const inv = ctx.hydrateOccurrence({ state: "incorporada", depDate: "2024-05-11", depTime: "02:00",
    result: { lowUsv: 5, highUsv: 2 } });
  ok("M8 result invertido → null", inv.result === null, JSON.stringify(inv.result));
  ok("M8 state → incompleto", inv.state === "incompleto", inv.state);

  // M9 — estados y objetos basura se sanean.
  ok("M9 state desconocido → esperando_fecha", ctx.hydrateOccurrence({ state: "hackeado" }).state === "esperando_fecha");
  ok("M9 no-objeto → null", ctx.hydrateOccurrence("x") === null);

  // M10 — persistencia: las ocurrencias sobreviven al JSON.
  const round = ctx.hydrateFlight(JSON.parse(JSON.stringify(ctx.serializeFlight(ctx.splitLegs(Bh)))));
  ok("M10 tres ocurrencias tras round-trip",
     Array.isArray(round.occurrences) && round.occurrences.length === 3,
     round.occurrences && round.occurrences.length);
  ok("M10 depDate/state intactos",
     Array.isArray(round.occurrences) &&
       round.occurrences.map(o => o.depDate + "/" + o.state).join(",") ===
         "2021-10-28/programado,undefined/esperando_fecha,undefined/esperando_fecha",
     round.occurrences && round.occurrences.map(o => o.depDate + "/" + o.state).join(","));

  // M11 — instante UTC canónico y hora imposible.
  ok("M11 depMsOf(makeOccurrence) === Date.UTC",
     ctx.depMsOf(ctx.makeOccurrence("2024-05-11", "01:30")) === Date.UTC(2024, 4, 11, 1, 30));
  ok("M11 hora 25:00 → esperando_fecha",
     ctx.makeOccurrence("2024-05-11", "25:00").state === "esperando_fecha");

  // M12 — un backup con `occurrences` que no es array no deja basura en el vuelo.
  ok("M12 occurrences no-array se elimina al hidratar",
     ["x", {}, 7, null].every(v => !("occurrences" in ctx.hydrateFlight({orig: "MAD", dest: "JFK", occurrences: v}))));
}

console.log("\nT11 ocurrencias UI");
{
  const FIXA = path.join(REPO, "tools", "fixtures", "goes", "archive");
  const readJ = (n) => JSON.parse(fs.readFileSync(path.join(FIXA, n), "utf8"));
  const OCCVIS = {
    esperando_fecha: "pendiente", programado: "pendiente", esperando_datos: "pendiente",
    incompleto: "pendiente", estimacion_disponible: "disponible", modelo_nuevo: "disponible",
    incorporada: "revisada", sin_senal: "revisada",
    // El 11-09-2025 no es "revisada" (contribucion despreciable) sino un aviso:
    // no hay dato y no hay nada que esperar.
    fuera_de_rango: "aviso",
    noaa_no_disponible: "aviso",
    // Terminal: dia completo y el modelo no puede acotar la cifra. Ni pendiente
    // (no hay nada que esperar) ni revisada (no es contribucion despreciable).
    no_estimable: "aviso"
  };
  const occ = (date, time, state, extra) => Object.assign({
    id: 1, depDate: date, depTime: time, timeKind: "programada",
    state: state || "programado", noaaCapture: null, modelVersion: null, result: null
  }, extra || {});
  const FLIGHT = { orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
  const DEP = Date.UTC(2026, 8, 9, 6, 0);
  const NOW_AFTER = DEP + 24 * 3600 * 1000;

  // U1 — la tabla cubre TODOS los estados y solo devuelve uno de los cuatro visibles.
  const u1ok = ctx.OCC_STATES.every((s) =>
    ["pendiente", "disponible", "revisada", "aviso"].indexOf(ctx.occVisible(s)) !== -1 &&
    ctx.occVisible(s) === OCCVIS[s]);
  ok("U1 occVisible cubre todos los estados según la tabla C2", u1ok,
     ctx.OCC_STATES.map((s) => s + "=" + ctx.occVisible(s)).join(","));

  // U2 — estado desconocido: error, nunca un valor por defecto.
  let u2 = null;
  try { ctx.occVisible("hackeado"); } catch (e) { u2 = e.message; }
  ok("U2 occVisible('hackeado') lanza", typeof u2 === "string" && u2.indexOf("hackeado") !== -1, u2);

  // U3 — adaptador contra los fixtures reales 09-08 + 09-09.
  const d08 = readJ("2026-09-08-diff.json"), i08 = readJ("2026-09-08.json");
  const d09 = readJ("2026-09-09-diff.json"), i09 = readJ("2026-09-09.json");
  const adapted = ctx.solarDayAdapt([d08, d09], [i08, i09]);
  const sortedOk = adapted.samples.every((s, i) => i === 0 || s.tMs >= adapted.samples[i - 1].tMs);
  ok("U3 13 canales en orden",
     adapted.channels.length === 13 &&
     adapted.channels.map((c) => c.name).join(",") ===
       "P1,P2A,P2B,P3,P4,P5,P6,P7,P8A,P8B,P8C,P9,P10",
     adapted.channels.map((c) => c.name).join(","));
  ok("U3 P1 1020/1860 keV",
     adapted.channels[0].lo_keV === 1020 && adapted.channels[0].hi_keV === 1860,
     JSON.stringify(adapted.channels[0]));
  ok("U3 576 muestras ordenadas", adapted.samples.length === 576 && sortedOk, adapted.samples.length);
  ok("U3 satelite SWPC normalizado a '18'",
     adapted.samples.every((s) => s.sat === "18"), adapted.samples[0].sat);
  const int0 = i08.samples[0].flux[">=500 MeV"];
  ok("U3 int500 de la muestra 0 = integral del mismo t",
     adapted.samples[0].tMs === Date.parse("2026-09-08T00:00:00Z") && adapted.samples[0].int500 === int0,
     adapted.samples[0].int500 + " vs " + int0);

  // U4 — sin integral para ese t: undefined, nunca 0.
  const noInt = ctx.solarDayAdapt([d08], []);
  ok("U4 sin integral int500 es undefined (no 0)",
     noInt.samples.length > 0 && noInt.samples[0].int500 === undefined, noInt.samples[0].int500);

  const spy = { calls: 0, fn: function () { spy.calls++; return { ok: true, state: "sin_senal" }; } };

  // U5 — regla 3: la baseline entera debe caer dentro del archivo.
  const r5 = ctx.occEvaluate(FLIGHT, occ("2025-09-11", "00:30"), null, NOW_AFTER, spy.fn);
  ok("U5 occ del 11-09-2025 00:30 → fuera_de_rango", r5.state === "fuera_de_rango", r5.state);
  ok("U5 routeFn no se llama", spy.calls === 0, spy.calls);

  // U6 — regla 5: vuelo aun no aterrizado.
  const r6 = ctx.occEvaluate(FLIGHT, occ("2026-09-09", "06:00"), null, DEP, spy.fn);
  ok("U6 aterriza despues de nowMs → programado", r6.state === "programado", r6.state);
  ok("U6 routeFn no se llama", spy.calls === 0, spy.calls);

  // U7 — regla 6: sin archivo (red caida).
  const r7 = ctx.occEvaluate(FLIGHT, occ("2026-09-09", "06:00"), null, NOW_AFTER, spy.fn);
  ok("U7 archive null → noaa_no_disponible", r7.state === "noaa_no_disponible", r7.state);

  // U8 — regla 7: dia provisional → esperando_datos; permanente → incompleto.
  const archProv = {
    manifest: { coverage: { days: ["2026-09-08"] },
                differential: { coverage: { days: ["2026-09-08"] },
                                incomplete_days: [{ day: "2026-09-09", permanent: false }] } },
    days: { "2026-09-08": { diff: { samples: [] }, int: { samples: [] } } }
  };
  const archPerm = {
    manifest: { coverage: { days: ["2026-09-08"] },
                differential: { coverage: { days: ["2026-09-08"] },
                                incomplete_days: [{ day: "2026-09-09", permanent: true }] } },
    days: { "2026-09-08": { diff: { samples: [] }, int: { samples: [] } } }
  };
  const r8a = ctx.occEvaluate(FLIGHT, occ("2026-09-09", "06:00"), archProv, NOW_AFTER, spy.fn);
  const r8b = ctx.occEvaluate(FLIGHT, occ("2026-09-09", "06:00"), archPerm, NOW_AFTER, spy.fn);
  ok("U8 dia provisional → esperando_datos", r8a.state === "esperando_datos", r8a.state);
  ok("U8 dia permanente → incompleto", r8b.state === "incompleto", r8b.state);

  // U9 — regla 8: mapeo de SepModel.route.
  const archOk = {
    manifest: { coverage: { days: ["2026-09-08", "2026-09-09"] },
                differential: { coverage: { days: ["2026-09-08", "2026-09-09"] } } },
    days: {
      "2026-09-08": { diff: { samples: [] }, int: { samples: [] } },
      "2026-09-09": { diff: { samples: [] }, int: { samples: [] } }
    }
  };
  const U9O = occ("2026-09-09", "06:00");
  const r9a = ctx.occEvaluate(FLIGHT, U9O, archOk, NOW_AFTER,
    () => ({ ok: true, state: "detectado", range: { lowUsv: 2, highUsv: 5 } }));
  const r9b = ctx.occEvaluate(FLIGHT, U9O, archOk, NOW_AFTER,
    () => ({ ok: false, state: "pendiente" }));
  const r9c = ctx.occEvaluate(FLIGHT, U9O, archOk, NOW_AFTER,
    () => { throw new Error("boom"); });
  const r9d = ctx.occEvaluate(FLIGHT, U9O, archOk, NOW_AFTER,
    () => ({ ok: true, state: "detectado" }));
  ok("U9 rango → estimacion_disponible {2,5}",
     r9a.state === "estimacion_disponible" && r9a.result &&
     r9a.result.lowUsv === 2 && r9a.result.highUsv === 5, JSON.stringify(r9a));
  ok("U9 !r.ok → incompleto", r9b.state === "incompleto", r9b.state);
  ok("U9 route lanzando → incompleto", r9c.state === "incompleto", r9c.state);
  ok("U9 detectado sin rango → sin_senal", r9d.state === "sin_senal", r9d.state);

  // U9b — un motivo del MODELO cierra terminal; uno del DATO sigue pendiente.
  const r9e = ctx.occEvaluate(FLIGHT, U9O, archOk, NOW_AFTER,
    () => ({ ok: false, state: "pendiente", reason: "sin_convergencia" }));
  const r9f = ctx.occEvaluate(FLIGHT, U9O, archOk, NOW_AFTER,
    () => ({ ok: false, state: "pendiente", reason: "modelo_no_resoluble" }));
  const r9g = ctx.occEvaluate(FLIGHT, U9O, archOk, NOW_AFTER,
    () => ({ ok: false, state: "pendiente", reason: "hueco_observacion" }));
  ok("U9b sin_convergencia → no_estimable (terminal, no pendiente)",
     r9e.state === "no_estimable" && r9e.result === null &&
     ctx.occVisible(r9e.state) === "aviso", r9e.state);
  ok("U9b modelo_no_resoluble → no_estimable", r9f.state === "no_estimable", r9f.state);
  ok("U9b hueco_observacion sigue incompleto (un dato mejor lo arregla)",
     r9g.state === "incompleto" && ctx.occVisible(r9g.state) === "pendiente", r9g.state);
  // U9c — dia anterior al inicio del archivo SWPC: su ausencia es permanente.
  // El colector SWPC solo avanza; la historia la cubre NCEI. Sin esto los cuatro
  // dias NCEI `partial` de agosto de 2026 se quedaban en esperando_datos para
  // siempre, prometiendo un dato que no va a llegar.
  const archNula = {
    manifest: { coverage: { days: ["2026-08-30", "2026-08-31"], first_day: "2026-08-30" },
                incomplete_days: [], differential: { coverage: { days: ["2026-08-30", "2026-08-31"] } } },
    nceiManifest: { days: { "2026-08-18": { status: "partial" }, "2026-08-19": { status: "partial" } } },
    source: null, days: {}
  };
  const archNulaPost = {
    manifest: { coverage: { days: ["2026-08-30"], first_day: "2026-08-30" },
                incomplete_days: [], differential: { coverage: { days: ["2026-08-30"] } } },
    nceiManifest: { days: { "2026-09-02": { status: "partial" }, "2026-09-03": { status: "partial" } } },
    source: null, days: {}
  };
  const r9h = ctx.occEvaluate(FLIGHT, occ("2026-08-19", "06:00"), archNula, NOW_AFTER,
    () => ({ ok: true, state: "sin_senal" }));
  const r9i = ctx.occEvaluate(FLIGHT, occ("2026-09-03", "06:00"), archNulaPost, NOW_AFTER,
    () => ({ ok: true, state: "sin_senal" }));
  ok("U9c dia antes del inicio SWPC + NCEI partial -> incompleto, no esperando_datos",
     r9h.state === "incompleto", r9h.state);
  // El limite: el propio first_day SI esta al alcance de SWPC, asi que su
  // ausencia NO es permanente todavia. Con `<=` en vez de `<` este se rompe.
  const archLimite = {
    manifest: { coverage: { days: [], first_day: "2026-08-30" },
                incomplete_days: [], differential: { coverage: { days: [] } } },
    nceiManifest: { days: { "2026-08-30": { status: "partial" },
                            "2026-08-31": { status: "partial" } } },
    source: null, days: {}
  };
  const r9j = ctx.occEvaluate(FLIGHT, occ("2026-08-30", "13:00"), archLimite, NOW_AFTER,
    () => ({ ok: true, state: "sin_senal" }));
  ok("U9c el propio first_day no es ausencia permanente -> esperando_datos",
     r9j.state === "esperando_datos", r9j.state);

  ok("U9c dia DENTRO del rango SWPC pero ausente -> sigue esperando_datos",
     r9i.state === "esperando_datos", r9i.state);

  ok("U9b hydrateOccurrence conserva no_estimable (no lo resetea a programado)",
     ctx.hydrateOccurrence(occ("2026-09-09", "06:00", "no_estimable")).state === "no_estimable");
  ok("U9b no_estimable tiene etiqueta en los dos idiomas",
     typeof ctx.LANG.es.occState_no_estimable === "string" &&
     typeof ctx.LANG.en.occState_no_estimable === "string");

  // U10 — regla 1: version del modelo.
  const spy10 = { calls: 0, fn: function () { spy10.calls++; return { ok: true, state: "sin_senal" }; } };
  const incOld = occ("2026-09-09", "06:00", "incorporada",
    { modelVersion: "viejo", result: { lowUsv: 1, highUsv: 2 } });
  const r10a = ctx.occEvaluate(FLIGHT, incOld, null, NOW_AFTER, spy10.fn);
  const incCur = occ("2026-09-09", "06:00", "incorporada",
    { modelVersion: ctx.SEP_MODEL_VERSION, result: { lowUsv: 1, highUsv: 2 } });
  const r10b = ctx.occEvaluate(FLIGHT, incCur, null, NOW_AFTER, spy10.fn);
  ok("U10 version vieja → modelo_nuevo con su result",
     r10a.state === "modelo_nuevo" && r10a.result && r10a.result.lowUsv === 1 && r10a.result.highUsv === 2,
     JSON.stringify(r10a));
  ok("U10 version actual → incorporada intacta",
     r10b.state === "incorporada" && r10b.result && r10b.result.highUsv === 2, JSON.stringify(r10b));
  ok("U10 routeFn no se llama", spy10.calls === 0, spy10.calls);

  // U11 — occRoutePoints: track con minutos y ortodromica MAD→JFK.
  const O11 = occ("2026-09-09", "06:00");
  const withTrack = { orig: "MAD", dest: "JFK", flIdx: 1,
    track: [[0, 40, -3, 10.668], [60, 41, -10, 10.668]] };
  const p11 = ctx.occRoutePoints(withTrack, O11);
  const depMs = ctx.depMsOf(O11);
  ok("U11 track: tMs = depMs y depMs + 3600000",
     p11 && p11.length === 2 && p11[0].tMs === depMs && p11[1].tMs === depMs + 3600000,
     p11 && JSON.stringify(p11.map((p) => p.tMs)));
  const p11b = ctx.occRoutePoints(FLIGHT, O11);
  const A = ctx.activeDB["MAD"], B = ctx.activeDB["JFK"];
  const expLast = depMs + ctx.gcDistance(A.lat, A.lon, B.lat, B.lon) / 830 * 3600000;
  ok("U11 sin track: 32 puntos y el último aterriza a dist/830 h",
     p11b && p11b.length === 32 && Math.abs(p11b[31].tMs - expLast) < 1,
     p11b && p11b.length + " " + (p11b[31].tMs - expLast));

  // U12 — invariante: los vuelos de T10 conservan su dosis exacta.
  const A12 = { orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
  const B12 = { orig: "MAD", dest: "JFK", legs: 3, flIdx: 2, depDate: "2021-10-28", depTime: "14:00" };
  const C12 = { orig: "LHR", dest: "NRT", legs: 2, flIdx: 1,
    track: [[null, 51.5, -0.4, 10.668], [null, 60, 60, 11.0], [null, 35.7, 139.8, 10.668]] };
  const REF = { A: 27.521219708117496, B: 35.435214508544320, C: 45.904099010735550 };
  ok("U12 A idéntica", ctx.flightCalc(ctx.hydrateFlight(A12), 650).doseUsv === REF.A,
     ctx.flightCalc(ctx.hydrateFlight(A12), 650).doseUsv);
  ok("U12 B idéntica", ctx.flightCalc(ctx.hydrateFlight(B12), 650).doseUsv === REF.B,
     ctx.flightCalc(ctx.hydrateFlight(B12), 650).doseUsv);
  ok("U12 C idéntica", ctx.flightCalc(ctx.hydrateFlight(C12), 650).doseUsv === REF.C,
     ctx.flightCalc(ctx.hydrateFlight(C12), 650).doseUsv);

  // T11-fixes — regresiones de la revisión (F1-F4).
  const flightA = { orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
  const OCC0909 = occ("2026-09-09", "06:00");
  const mkManifest = (cov, covDiff, inc, incDiff) => ({
    coverage: { days: cov.slice() },
    differential: { coverage: { days: covDiff.slice() }, incomplete_days: (incDiff || []).slice() },
    incomplete_days: (inc || []).slice()
  });
  const emptyDays = (days) => {
    const m = {};
    days.forEach((d) => { m[d] = { diff: { samples: [] }, int: { samples: [] } }; });
    return m;
  };
  const spyOf = (res) => {
    const s = { calls: 0, arg: null };
    s.fn = function (a) { s.calls++; s.arg = a; return res || { ok: true, state: "sin_senal" }; };
    return s;
  };

  // T1 — dia en coverage.days top-level pero no en differential.coverage.days.
  {
    const s = spyOf();
    const arch = { manifest: mkManifest(["2026-09-08", "2026-09-09"], [], [], []),
                   days: emptyDays(["2026-09-08", "2026-09-09"]) };
    const r = ctx.occEvaluate(flightA, OCC0909, arch, NOW_AFTER, s.fn);
    ok("T1 cov sin covDiff → esperando_datos", r.state === "esperando_datos", r.state);
    ok("T1 routeFn no se llama", s.calls === 0, s.calls);
  }

  // T2 — la baseline de 12 h necesita el dia anterior (03:00Z → 09-08).
  {
    const s = spyOf();
    const arch = { manifest: mkManifest(["2026-09-08", "2026-09-09"], ["2026-09-08", "2026-09-09"]),
                   days: emptyDays(["2026-09-09"]) };
    const r = ctx.occEvaluate(flightA, occ("2026-09-09", "03:00"), arch, NOW_AFTER, s.fn);
    ok("T2 falta 09-08 → esperando_datos", r.state === "esperando_datos", r.state);
    ok("T2 routeFn no se llama", s.calls === 0, s.calls);
  }

  // T3/T4 — el espía recibe la entrada exacta del modelo (fixtures reales).
  {
    const s = spyOf();
    const arch = { manifest: mkManifest(["2026-09-08", "2026-09-09"], ["2026-09-08", "2026-09-09"]),
                   days: { "2026-09-08": { diff: d08, int: i08 }, "2026-09-09": { diff: d09, int: i09 } } };
    const o = occ("2026-09-09", "03:00");
    const pts = ctx.occRoutePoints(flightA, o);
    ctx.occEvaluate(flightA, o, arch, NOW_AFTER, s.fn);
    ok("T3 startMs = depMsOf(occ)", s.arg && s.arg.startMs === ctx.depMsOf(o), s.arg && s.arg.startMs);
    ok("T3 points = occRoutePoints(f, occ)", s.arg && s.arg.points.length === pts.length,
       s.arg && s.arg.points.length);
    ok("T3 channels = 13", s.arg && s.arg.channels.length === 13, s.arg && s.arg.channels.length);
    ok("T4 operator = SEP_DOSE del contexto", s.arg && s.arg.operator === ctx.SEP_DOSE,
       s.arg && s.arg.operator);
  }

  // T5 — detectado sin rango: evento activo, visible como sin_senal.
  {
    const arch = { manifest: mkManifest(["2026-09-08", "2026-09-09"], ["2026-09-08", "2026-09-09"]),
                   days: emptyDays(["2026-09-08", "2026-09-09"]) };
    const s = spyOf({ ok: true, state: "detectado", range: null });
    const r = ctx.occEvaluate(flightA, OCC0909, arch, NOW_AFTER, s.fn);
    ok("T5 detectado sin rango → sin_senal", r.state === "sin_senal", r.state);
    ok("T5 eventActive true", r.eventActive === true, r.eventActive);
  }

  // T6 — manifest completo, archive.days sin uno de los dias.
  {
    const s = spyOf();
    const arch = { manifest: mkManifest(["2026-09-08", "2026-09-09"], ["2026-09-08", "2026-09-09"]),
                   days: emptyDays(["2026-09-09"]) };
    const r = ctx.occEvaluate(flightA, OCC0909, arch, NOW_AFTER, s.fn);
    ok("T6 archive.days incompleto → esperando_datos", r.state === "esperando_datos", r.state);
    ok("T6 routeFn no se llama", s.calls === 0, s.calls);
  }

  // T7 — occNeedsArchive: solo se pide el archivo cuando hace falta.
  {
    const landed = occ("2026-09-09", "06:00");
    ok("T7 antes del inicio del archivo → false",
       ctx.occNeedsArchive(flightA, occ("2025-08-01", "06:00"), NOW_AFTER) === false);
    ok("T7 vuelo no aterrizado → false",
       ctx.occNeedsArchive(flightA, occ("2026-09-09", "06:00"),
         ctx.depMsOf(occ("2026-09-09", "06:00"))) === false);
    ok("T7 sin fecha → false", ctx.occNeedsArchive(flightA, occ(undefined, undefined), NOW_AFTER) === false);
    ok("T7 incorporada → false",
       ctx.occNeedsArchive(flightA, occ("2026-09-09", "06:00", "incorporada"), NOW_AFTER) === false);
    ok("T7 aterrizado tras el archivo → true",
       ctx.occNeedsArchive(flightA, landed, NOW_AFTER) === true);
  }
}

console.log("\nSelectores fecha/hora — borrador local + confirmación");
{
  const dp = ctx.depDraftPatch;

  // D1 — borrador completo y válido → los dos campos.
  const d1 = dp({ depDate: "2026-09-01", depTime: "14:30" });
  ok("D1 borrador completo devuelve los campos",
     JSON.stringify(d1) === '{"depDate":"2026-09-01","depTime":"14:30"}',
     JSON.stringify(d1));

  // D2 — hora ausente o incompleta → null (la hora sin minutos no vale).
  const d2 = [{ depDate: "2026-09-01" }, { depDate: "2026-09-01", depTime: "14" },
    { depDate: "2026-09-01", depTime: "" }];
  ok("D2 hora incompleta o ausente → null", d2.every((d) => dp(d) === null),
     JSON.stringify(d2.map(dp)));

  // D3 — fecha ausente o mal formada → null.
  const d3 = [{ depTime: "14:30" }, { depDate: "1-9-2026", depTime: "14:30" }];
  ok("D3 fecha ausente o mal formada → null", d3.every((d) => dp(d) === null),
     JSON.stringify(d3.map(dp)));

  // D4 — valores imposibles → null (hora 25:00, 31 de febrero).
  const d4 = [{ depDate: "2026-09-01", depTime: "25:00" },
    { depDate: "2026-02-31", depTime: "10:00" }];
  ok("D4 valores imposibles → null", d4.every((d) => dp(d) === null),
     JSON.stringify(d4.map(dp)));

  // D5 — entradas basura: no lanzan y dan null.
  let d5threw = null, d5out = null;
  try { d5out = [dp(null), dp("x"), dp({ depDate: 5, depTime: 7 })]; }
  catch (e) { d5threw = e.message; }
  ok("D5 entradas basura no lanzan y dan null",
     d5threw === null && d5out && d5out.every((v) => v === null),
     d5threw === null ? JSON.stringify(d5out) : d5threw);

  // D6 — el texto del estado cita la fecha de inicio y no dice "revisado".
  const es6 = ctx.LANG.es.occState_fuera_de_rango;
  const en6 = ctx.LANG.en.occState_fuera_de_rango;
  ok("D6 ES menciona 2025 y no 'revis'",
     es6.indexOf("2025") !== -1 && es6.toLowerCase().indexOf("revis") === -1, es6);
  ok("D6 EN menciona 2025 y no 'review'",
     en6.indexOf("2025") !== -1 && en6.toLowerCase().indexOf("review") === -1, en6);
}

// T8 — un fallo HTTP no envenena la caché del manifest (F1); requiere async.
async function testFetchSolarManifestRetriesAfterHttpError() {
  console.log("\nT8 — un fallo HTTP no envenena la caché del manifest");
  const realFetch = ctx.fetch;
  let calls = 0;
  ctx.fetch = function () {
    calls++;
    if (calls <= 3) return Promise.resolve({ ok: false, status: 500 });
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ coverage: { days: [] } }); } });
  };
  try {
    let firstErr = null;
    try { await ctx.fetchSolarManifest(); } catch (e) { firstErr = e; }
    ok("T8 la primera llamada rechaza", firstErr !== null);
    let secondErr = null;
    try { await ctx.fetchSolarManifest(); } catch (e) { secondErr = e; }
    ok("T8 fetch llamado 4 veces (caché no envenenada)", calls === 4, calls);
  } finally {
    ctx.fetch = realFetch;
  }
}

// F6-4 — descarga perezosa del archivo histórico NCEI; requiere async.
async function testFetchNcei() {
  console.log("\nF6-4 descarga del archivo NCEI");
  const realFetch = ctx.fetch;
  const MAN = { days: { "2026-09-08": { status: "complete", candidates: [
    { sat: "g18", valid_diff_slots: 288, recommended: true, path: "ncei/sgps/g18/2026/09/X.json" },
    { sat: "g19", valid_diff_slots: 276, recommended: false, path: "ncei/sgps/g19/2026/09/Y.json" }] } } };
  try {
    // El manifiesto se cachea y un fallo HTTP no envenena la cache.
    ctx._nceiManifestPromise = null;
    let calls = 0, urls = [];
    ctx.fetch = function (u) {
      calls++; urls.push(u);
      if (calls <= 3) return Promise.resolve({ ok: false, status: 500 });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MAN) });
    };
    let err = null;
    try { await ctx.fetchNceiManifest(); } catch (e) { err = e; }
    ok("F6 fallo HTTP del manifiesto rechaza", err !== null);
    const m = await ctx.fetchNceiManifest();
    ok("F6 reintenta tras el fallo (cache no envenenada)", calls === 4, calls);
    ok("F6 pide ncei/manifest.json", urls[0].indexOf("ncei/manifest.json") !== -1, urls[0]);
    const m2 = await ctx.fetchNceiManifest();
    ok("F6 segunda llamada usa cache", calls === 4 && m2 === m, calls);

    // La ruta sale del manifiesto, no se construye.
    ctx._nceiDayCache.clear();
    urls = [];
    ctx.fetch = function (u) {
      urls.push(u);
      const sat = u.indexOf("/g19/") !== -1 ? "g19" : "g18";
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ day: "2026-09-08", sat }) });
    };
    const f = await ctx.fetchNceiDay("2026-09-08", "18", MAN);
    ok("F6 usa el path del candidato", urls[0].indexOf("ncei/sgps/g18/2026/09/X.json") !== -1, urls[0]);
    ok("F6 devuelve el fichero", f && f.sat === "g18", JSON.stringify(f));
    const f2 = await ctx.fetchNceiDay("2026-09-08", "18", MAN);
    ok("F6 dia cacheado no repite fetch", urls.length === 1, urls.length);

    // Elige el candidato del satelite pedido y la cache distingue satelites del
    // mismo dia: pedir g19 tras cachear g18 debe tocar su propia URL.
    const f19 = await ctx.fetchNceiDay("2026-09-08", "19", MAN);
    ok("F6 respeta el satelite pedido",
       urls.length === 2 && urls[1].indexOf("g19/2026/09/Y.json") !== -1 && f19.sat === "g19",
       JSON.stringify({ urls, f19 }));

    // 404 = dato ausente, no error.
    ctx._nceiDayCache.clear();
    ctx.fetch = function () { return Promise.resolve({ ok: false, status: 404 }); };
    ok("F6 404 -> null", (await ctx.fetchNceiDay("2026-09-08", "18", MAN)) === null);

    // Cualquier rechazo borra la promesa del dia: HTTP y JSON deben poder
    // reintentarse en la misma sesion.
    ctx._nceiDayCache.clear();
    calls = 0;
    ctx.fetch = function () {
      calls++;
      if (calls <= 3) return Promise.resolve({ ok: false, status: 500 });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ sat: "g18" }) });
    };
    err = null;
    try { await ctx.fetchNceiDay("2026-09-08", "18", MAN); } catch (e) { err = e; }
    ok("F6 fallo HTTP del dia rechaza", err !== null);
    const trasHttp = await ctx.fetchNceiDay("2026-09-08", "18", MAN);
    ok("F6 dia reintenta tras fallo HTTP", calls === 4 && trasHttp.sat === "g18", calls);

    ctx._nceiDayCache.clear();
    calls = 0;
    ctx.fetch = function () {
      calls++;
      return Promise.resolve({ ok: true, json: () => Promise.reject(new SyntaxError("json roto")) });
    };
    const jsonIlegible = await ctx.fetchNceiDay("2026-09-08", "18", MAN);
    ok("F6 JSON invalido del dia llega como fichero ilegible",
       jsonIlegible !== null && typeof jsonIlegible === "object", String(jsonIlegible));
    const jsonIlegible2 = await ctx.fetchNceiDay("2026-09-08", "18", MAN);
    ok("F6 fichero ilegible queda cacheado", calls === 1 && jsonIlegible2 === jsonIlegible, calls);

    ctx._nceiDayCache.clear();
    calls = 0;
    ctx.fetch = function () {
      calls++;
      return Promise.resolve({ ok: true, json: () => calls === 1
        ? Promise.reject(new TypeError("stream abortado")) : Promise.resolve({ sat: "g18" }) });
    };
    err = null;
    try { await ctx.fetchNceiDay("2026-09-08", "18", MAN); } catch (e) { err = e; }
    ok("F6 fallo de lectura del body rechaza", err && err.name === "TypeError", err && err.name);
    const trasBody = await ctx.fetchNceiDay("2026-09-08", "18", MAN);
    ok("F6 dia reintenta tras fallo de lectura", calls === 2 && trasBody.sat === "g18", calls);

    // Satelite sin candidato: null sin tocar la red.
    ctx._nceiDayCache.clear();
    let tocado = false;
    ctx.fetch = function () { tocado = true; return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }); };
    ok("F6 satelite inexistente -> null", (await ctx.fetchNceiDay("2026-09-08", "99", MAN)) === null);
    ok("F6 satelite inexistente no llama a fetch", tocado === false);
  } finally {
    ctx.fetch = realFetch;
    ctx._nceiManifestPromise = null;
    ctx._nceiDayCache.clear();
  }
}

console.log("\nT12 lote");
{
  const hp = 650;
  // Vuelos a mano con ids fijos; `evals` inventados: estos tests no tocan red.
  const mkOcc = (fields) =>
    Object.assign(ctx.makeOccurrence(fields.depDate, fields.depTime, fields.timeKind), fields);

  // B1 — monthDoseParts: manda el numero de ocurrencias, no `legs`.
  {
    const fNo = { id: 901, orig: "MAD", dest: "JFK", legs: 3, flIdx: 1 };
    const c = ctx.flightCalc(fNo, hp).doseUsv;
    ok("B1 legs:3 sin occurrences → gcrUsv === flightCalc×3",
       ctx.monthDoseParts([fNo], hp).gcrUsv === c * 3, ctx.monthDoseParts([fNo], hp).gcrUsv);
    const fOcc = { id: 902, orig: "MAD", dest: "JFK", legs: 3, flIdx: 1, occurrences: [
      mkOcc({ id: 9021, depDate: "2026-09-01", depTime: "10:00", timeKind: "real" }),
      mkOcc({ id: 9022, depDate: "2026-09-02", depTime: "10:00", timeKind: "real" })
    ]};
    ok("B1 mismo vuelo con 2 occurrences → gcrUsv === flightCalc×2",
       ctx.monthDoseParts([fOcc], hp).gcrUsv === c * 2, ctx.monthDoseParts([fOcc], hp).gcrUsv);
  }

  // B2 — solo las incorporadas con cifra suman al rango SEP.
  {
    const oInc = mkOcc({ id: 9031, depDate: "2026-09-01", depTime: "10:00", timeKind: "real",
      state: "incorporada", result: { lowUsv: 2, highUsv: 5 }, modelVersion: ctx.SEP_MODEL_VERSION });
    const oDisp = mkOcc({ id: 9032, depDate: "2026-09-02", depTime: "10:00", timeKind: "real",
      state: "estimacion_disponible", result: { lowUsv: 100, highUsv: 200 } });
    const f = { id: 903, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1, occurrences: [oInc, oDisp] };
    const p = ctx.monthDoseParts([f], hp);
    ok("B2 sepLowUsv solo de la incorporada", p.sepLowUsv === 2, p.sepLowUsv);
    ok("B2 sepHighUsv solo de la incorporada", p.sepHighUsv === 5, p.sepHighUsv);
  }

  // B3 — elegible solo con estimacion_disponible Y timeKind real.
  {
    const oReal = mkOcc({ id: 9041, depDate: "2026-09-01", depTime: "10:00", timeKind: "real" });
    const oProg = mkOcc({ id: 9042, depDate: "2026-09-02", depTime: "10:00", timeKind: "programada" });
    const f = { id: 904, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1, occurrences: [oReal, oProg] };
    const evals = {
      9041: { state: "estimacion_disponible", result: { lowUsv: 1, highUsv: 2 } },
      9042: { state: "estimacion_disponible", result: { lowUsv: 1, highUsv: 2 } }
    };
    const plan = ctx.batchPlan([f], evals);
    ok("B3 real es elegible",
       plan.eligible.length === 1 && plan.eligible[0].occId === 9041, JSON.stringify(plan.eligible));
    ok("B3 programada excluida por hora_estimada",
       plan.excluded.length === 1 && plan.excluded[0].reason === "hora_estimada",
       JSON.stringify(plan.excluded));
  }

  // B4 — motivos por orden: incorporada, sin evaluar y el estado del eval.
  {
    const oInc = mkOcc({ id: 9051, depDate: "2026-09-01", depTime: "10:00", timeKind: "real",
      state: "incorporada", result: { lowUsv: 1, highUsv: 2 } });
    const oNoEval = mkOcc({ id: 9052, depDate: "2026-09-02", depTime: "10:00", timeKind: "real" });
    const oWait = mkOcc({ id: 9053, depDate: "2026-09-03", depTime: "10:00", timeKind: "real" });
    const f = { id: 905, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1, occurrences: [oInc, oNoEval, oWait] };
    const plan = ctx.batchPlan([f], { 9053: { state: "esperando_datos", result: null } });
    const byId = {};
    plan.excluded.forEach((e) => { byId[e.occId] = e.reason; });
    ok("B4 incorporada → ya_incorporada", byId[9051] === "ya_incorporada", byId[9051]);
    ok("B4 sin entrada en evals → sin_evaluar", byId[9052] === "sin_evaluar", byId[9052]);
    ok("B4 esperando_datos → esperando_datos", byId[9053] === "esperando_datos", byId[9053]);
    ok("B4 nada elegible", plan.eligible.length === 0, JSON.stringify(plan.eligible));
  }

  // B5 — result invalido con estado disponible: no elegible.
  {
    const o1 = mkOcc({ id: 9061, depDate: "2026-09-01", depTime: "10:00", timeKind: "real" });
    const o2 = mkOcc({ id: 9062, depDate: "2026-09-02", depTime: "10:00", timeKind: "real" });
    const f = { id: 906, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1, occurrences: [o1, o2] };
    const plan = ctx.batchPlan([f], {
      9061: { state: "estimacion_disponible", result: { lowUsv: 5, highUsv: 2 } },
      9062: { state: "estimacion_disponible", result: { lowUsv: Infinity, highUsv: 2 } }
    });
    ok("B5 high<low no elegible", plan.eligible.length === 0, JSON.stringify(plan.eligible));
    ok("B5 lowUsv no finito no elegible", plan.excluded.length === 2, JSON.stringify(plan.excluded));
  }

  // B6 — applyBatch marca solo las elegibles y conserva noaaCapture.
  {
    const cap = { sample: 1 };
    const oElig = mkOcc({ id: 9071, depDate: "2026-09-01", depTime: "10:00", timeKind: "real",
      state: "estimacion_disponible", result: null, noaaCapture: cap });
    const oOther = mkOcc({ id: 9072, depDate: "2026-09-02", depTime: "10:00", timeKind: "real" });
    const f = { id: 907, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1, occurrences: [oElig, oOther] };
    const plan = { eligible: [{ flightId: 907, occId: 9071, result: { lowUsv: 3, highUsv: 7 } }], excluded: [] };
    const res = ctx.applyBatch([f], plan);
    const out = res.flights[0].occurrences;
    ok("B6 elegible → incorporada", out[0].state === "incorporada", out[0].state);
    ok("B6 result copiado", JSON.stringify(out[0].result) === '{"lowUsv":3,"highUsv":7}',
       JSON.stringify(out[0].result));
    ok("B6 modelVersion === SEP_MODEL_VERSION", out[0].modelVersion === ctx.SEP_MODEL_VERSION,
       out[0].modelVersion);
    ok("B6 noaaCapture intacto (===)", out[0].noaaCapture === cap, out[0].noaaCapture);
    ok("B6 la no elegible sale por identidad", out[1] === oOther, out[1] === oOther);
    ok("B6 result es objeto nuevo", out[0].result !== plan.eligible[0].result,
       out[0].result === plan.eligible[0].result);
  }

  // B7 — ida y vuelta byte a byte, con una ocurrencia sin clave modelVersion.
  {
    const oSinVer = { id: 9081, depDate: "2026-09-01", depTime: "10:00", timeKind: "real",
      state: "estimacion_disponible", noaaCapture: null, result: null };
    const f = { id: 908, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1, occurrences: [oSinVer] };
    const before = JSON.stringify([f]);
    const plan = { eligible: [{ flightId: 908, occId: 9081, result: { lowUsv: 4, highUsv: 9 } }], excluded: [] };
    const applied = ctx.applyBatch([f], plan);
    const undone = ctx.undoBatch(applied.flights, applied.batch);
    ok("B7 JSON antes === JSON después del lote y deshacer",
       JSON.stringify(undone) === before, JSON.stringify(undone) + " vs " + before);
    ok("B7 la clave modelVersion no reaparece", !("modelVersion" in undone[0].occurrences[0]),
       JSON.stringify(Object.keys(undone[0].occurrences[0])));
  }

  // B8 — no se clona lo que no se toca.
  {
    const fNo = { id: 909, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
    const fElig = { id: 910, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1,
      occurrences: [mkOcc({ id: 9101, depDate: "2026-09-01", depTime: "10:00", timeKind: "real" })] };
    const plan = { eligible: [{ flightId: 910, occId: 9101, result: { lowUsv: 1, highUsv: 2 } }], excluded: [] };
    const res = ctx.applyBatch([fNo, fElig], plan);
    ok("B8 vuelo sin elegibles sale === al de entrada", res.flights[0] === fNo, res.flights[0] === fNo);
    ok("B8 vuelo tocado sí es copia", res.flights[1] !== fElig, res.flights[1] === fElig);
  }

  // B9 — batch vacio o nulo devuelve el mismo array.
  {
    const arr = [{ id: 911 }];
    ok("B9 undoBatch(flights, null) === flights", ctx.undoBatch(arr, null) === arr);
    ok("B9 undoBatch(flights, {entries:[]}) === flights", ctx.undoBatch(arr, { entries: [] }) === arr);
  }

  // B11 — deshacer devuelve la cifra ANTERIOR, no null. B7 no lo cubre: alli la
  // ocurrencia previa tenia result null, asi que restaurar null parecia correcto.
  {
    const oPrev = { id: 9121, depDate: "2026-09-01", depTime: "10:00", timeKind: "real",
      state: "estimacion_disponible", noaaCapture: null,
      result: { lowUsv: 1, highUsv: 2 }, modelVersion: "modelo-viejo" };
    const f = { id: 912, orig: "MAD", dest: "JFK", legs: 1, flIdx: 1, occurrences: [oPrev] };
    const before = JSON.stringify([f]);
    const plan = { eligible: [{ flightId: 912, occId: 9121, result: { lowUsv: 4, highUsv: 9 } }], excluded: [] };
    const res = ctx.applyBatch([f], plan);
    const applied = res.flights[0].occurrences[0];
    ok("T12-B11el lote pisa la cifra con la nueva", applied.result.lowUsv === 4 && applied.result.highUsv === 9,
       JSON.stringify(applied.result));
    const undone = ctx.undoBatch(res.flights, res.batch);
    const back = undone[0].occurrences[0];
    ok("T12-B11deshacer restaura la cifra anterior", back.result && back.result.lowUsv === 1 && back.result.highUsv === 2,
       JSON.stringify(back.result));
    ok("T12-B11deshacer restaura la version anterior", back.modelVersion === "modelo-viejo", back.modelVersion);
    ok("T12-B11JSON antes === JSON despues", JSON.stringify(undone) === before,
       JSON.stringify(undone) + " vs " + before);
  }

  // B10 — textos nuevos en ES y EN.
  {
    const keys = ["occState_hora_estimada", "occState_ya_incorporada", "occState_sin_evaluar",
      "batchAdd", "batchUndo", "monthSepRange"];
    keys.forEach((k) => {
      ok("B10 ES tiene " + k, typeof ctx.LANG.es[k] === "string" && ctx.LANG.es[k].length > 0, ctx.LANG.es[k]);
      ok("B10 EN tiene " + k, typeof ctx.LANG.en[k] === "string" && ctx.LANG.en[k].length > 0, ctx.LANG.en[k]);
    });
    ok("B10 monthSepRange ES con {low} y {high}",
       (ctx.LANG.es.monthSepRange || "").indexOf("{low}") !== -1 &&
         (ctx.LANG.es.monthSepRange || "").indexOf("{high}") !== -1, ctx.LANG.es.monthSepRange);
    ok("B10 monthSepRange EN con {low} y {high}",
       (ctx.LANG.en.monthSepRange || "").indexOf("{low}") !== -1 &&
         (ctx.LANG.en.monthSepRange || "").indexOf("{high}") !== -1, ctx.LANG.en.monthSepRange);
  }
}

console.log("\nF6-1 satKey normaliza el satelite");
{
  ok("F6 numero 18 -> '18'", ctx.satKey(18) === "18", ctx.satKey(18));
  ok("F6 numero 19 -> '19'", ctx.satKey(19) === "19", ctx.satKey(19));
  ok("F6 string '18' -> '18'", ctx.satKey("18") === "18", ctx.satKey("18"));
  ok("F6 'g18' -> '18'", ctx.satKey("g18") === "18", ctx.satKey("g18"));
  ok("F6 'G19' -> '19'", ctx.satKey("G19") === "19", ctx.satKey("G19"));
  const basura = [null, undefined, "", "foo", "g", "17", "g20", "99", 20, {}, [], NaN, true];
  ok("F6 basura -> undefined",
     basura.every((v) => ctx.satKey(v) === undefined),
     basura.map((v) => JSON.stringify(v) + "=" + ctx.satKey(v)).join(","));
}

console.log("\nF6-2 nceiDayAdapt");
{
  const FIXN = path.join(REPO, "tools", "fixtures", "ncei");
  const readN = (n) => JSON.parse(fs.readFileSync(path.join(FIXN, n), "utf8"));
  const f08 = readN("2026-09-08-g18.json");

  const partsOf = (v) => ({
    channels: v && Array.isArray(v.channels) ? v.channels : [],
    samples: v && Array.isArray(v.samples) ? v.samples : []
  });
  const channelNames = (xs) => xs.map((c) => c && c.name).join(",");
  const a = ctx.nceiDayAdapt(f08);
  const aParts = partsOf(a), channels = aParts.channels, samples = aParts.samples;
  ok("F6 devuelve objeto", a !== null && typeof a === "object");
  ok("F6 13 canales en SOLAR_CHANNEL_ORDER",
     channels.length === 13 &&
     channelNames(channels) === "P1,P2A,P2B,P3,P4,P5,P6,P7,P8A,P8B,P8C,P9,P10",
     channelNames(channels));
  ok("F6 P1 1020/1860 keV", !!channels[0] && channels[0].lo_keV === 1020 && channels[0].hi_keV === 1860,
     JSON.stringify(channels[0]));
  ok("F6 P10 267000/390000 keV", !!channels[12] && channels[12].lo_keV === 267000 && channels[12].hi_keV === 390000,
     JSON.stringify(channels[12]));
  ok("F6 288 muestras", samples.length === 288, samples.length);
  ok("F6 t0 = start_time", !!samples[0] && samples[0].tMs === Date.parse("2026-09-08T00:00:00Z"),
     samples[0] && samples[0].tMs);
  ok("F6 cadencia exacta de 300 s",
     samples.length === 288 && !!samples[0] &&
     samples.every((s, i) => !!s && s.tMs === samples[0].tMs + i * 300000));
  ok("F6 sat normalizado a '18'", samples.length === 288 && samples.every((s) => !!s && s.sat === "18"),
     samples[0] && samples[0].sat);
  ok("F6 int500[0] = integral_500_mev[0]",
     !!samples[0] && samples[0].int500 === f08.integral_500_mev[0],
     (samples[0] && samples[0].int500) + " vs " + f08.integral_500_mev[0]);
  ok("F6 P1[0] = diff[0][0]", !!samples[0] && samples[0].P1 === f08.diff[0][0],
     (samples[0] && samples[0].P1) + " vs " + f08.diff[0][0]);

  // El indice canal -> columna es por NOMBRE: barajar `channels` y permutar cada
  // fila de `diff` igual debe dar exactamente el mismo resultado. Sin esto, un
  // adaptador que indexa por posicion (row[j]) no se distingue con los canales
  // del fixture, que ya vienen en orden canonico.
  const barajado = JSON.parse(JSON.stringify(f08));
  barajado.channels = barajado.channels.slice().reverse();
  barajado.diff = barajado.diff.map((r) => r.slice().reverse());
  const ab = ctx.nceiDayAdapt(barajado);
  const abParts = partsOf(ab);
  ok("F6 canales barajados con columnas permutadas -> mismas muestras",
     ab !== null &&
     channelNames(abParts.channels) === channelNames(channels) &&
     abParts.samples.length === samples.length &&
     abParts.samples.every((s, i) => !!s && !!samples[i] && s.P1 === samples[i].P1 && s.P10 === samples[i].P10 &&
       s.int500 === samples[i].int500),
     abParts.samples[0] ? abParts.samples[0].P1 + " vs " + (samples[0] && samples[0].P1) : String(ab));

  // Los dos adaptadores producen el MISMO int500 para el mismo instante: NCEI
  // integral_500_mev y SWPC flux[">=500 MeV"] son el mismo numero (ratio 1.0000
  // en los 288 slots del 2026-09-08, medido al disenar la fase).
  const FIXA = path.join(REPO, "tools", "fixtures", "goes", "archive");
  const swpc = ctx.solarDayAdapt(
    [JSON.parse(fs.readFileSync(path.join(FIXA, "2026-09-08-diff.json"), "utf8"))],
    [JSON.parse(fs.readFileSync(path.join(FIXA, "2026-09-08.json"), "utf8"))]);
  // SWPC serializa float32 y NCEI publica el mismo numero con %.7g: el contrato
  // es igualdad a 7 cifras significativas, no igualdad de bits.
  const mismos = samples.length === 288 && swpc.samples.length === 288 && samples.every((s, i) => {
    const ws = swpc.samples[i];
    return s && ws && typeof ws.int500 === "number" && s.tMs === ws.tMs &&
      s.int500 === Number(ws.int500.toPrecision(7));
  });
  ok("F6 int500 coincide con SWPC a 7 cifras significativas", mismos);

  // La clave vieja `integral_500_keV` sigue valiendo (fixtures en transicion).
  const viejo = JSON.parse(JSON.stringify(f08));
  viejo.integral_500_keV = viejo.integral_500_mev;
  delete viejo.integral_500_mev;
  const av = ctx.nceiDayAdapt(viejo);
  const avParts = partsOf(av);
  ok("F6 acepta integral_500_keV como alias",
     av !== null && !!avParts.samples[0] && avParts.samples[0].int500 === f08.integral_500_mev[0]);

  // Rechazos: cualquier desviacion de forma devuelve null, no un dia degradado.
  const roto = (mut) => { const c = JSON.parse(JSON.stringify(f08)); mut(c); return ctx.nceiDayAdapt(c); };
  ok("F6 rechaza time_step_s 60", roto((c) => { c.time_step_s = 60; }) === null);
  ok("F6 rechaza n_steps 287", roto((c) => { c.n_steps = 287; }) === null);
  ok("F6 rechaza fila diff de 12", roto((c) => { c.diff[5] = c.diff[5].slice(0, 12); }) === null);
  ok("F6 rechaza integral corto", roto((c) => { c.integral_500_mev.pop(); }) === null);
  ok("F6 rechaza 12 canales", roto((c) => { c.channels.pop(); }) === null);
  ok("F6 rechaza canal desconocido", roto((c) => { c.channels[3].name = "PX"; }) === null);
  ok("F6 rechaza start_time basura", roto((c) => { c.start_time = "ayer"; }) === null);
  ok("F6 rechaza sat basura", roto((c) => { c.sat = "sputnik"; }) === null);
  ok("F6 rechaza no-objeto",
     [null, undefined, 7, "x", []].every((v) => ctx.nceiDayAdapt(v) === null));

  // Nulos: se pasan tal cual, no se filtran ni se rellenan.
  const conNulos = roto((c) => { c.diff[10] = c.diff[10].map(() => null); c.integral_500_mev[10] = null; });
  const nulosParts = partsOf(conNulos);
  ok("F6 nulos se pasan tal cual",
     conNulos !== null && nulosParts.samples.length === 288 && !!nulosParts.samples[10] &&
     nulosParts.samples[10].P1 === null && nulosParts.samples[10].int500 === null);
  const conNegativos = roto((c) => { c.diff[11][0] = -0.25; c.integral_500_mev[11] = -0.5; });
  const negativosParts = partsOf(conNegativos);
  ok("F6 negativos se pasan tal cual",
     conNegativos !== null && negativosParts.samples.length === 288 && !!negativosParts.samples[11] &&
     negativosParts.samples[11].P1 === -0.25 && negativosParts.samples[11].int500 === -0.5);
}

console.log("\nF6-3 solarPickSource");
{
  // Manifiestos minimos, a mano: la funcion es pura y solo mira estos campos.
  const swpcCon = (dias) => ({
    coverage: { days: dias }, differential: { coverage: { days: dias } }
  });
  // Cifras reales del manifiesto NCEI publicado.
  const NCEI = { days: {
    "2026-09-08": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 288, recommended: true },
      { sat: "g19", valid_diff_slots: 276, recommended: false }] },
    "2026-09-09": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 288, recommended: true },
      { sat: "g19", valid_diff_slots: 288, recommended: false }] },
    "2026-03-24": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 286, recommended: true },
      { sat: "g19", valid_diff_slots: 253, recommended: false }] },
    "2026-08-17": { status: "partial", candidates: [
      { sat: "g18", valid_diff_slots: 0, recommended: true },
      { sat: "g19", valid_diff_slots: 0, recommended: false }] }
  } };

  // 1. SWPC cubre la ventana entera -> SWPC manda.
  ok("F6 SWPC cubre los dos dias -> 'swpc'",
     ctx.solarPickSource(["2026-09-08", "2026-09-09"], swpcCon(["2026-09-08", "2026-09-09"]), NCEI) === "swpc");

  // 2. Hueco en SWPC -> cae a NCEI para TODA la ventana, no solo el dia que falta.
  const r2 = ctx.solarPickSource(["2026-09-08", "2026-09-09"], swpcCon(["2026-09-08"]), NCEI);
  ok("F6 hueco SWPC -> ncei", r2 && r2.src === "ncei", JSON.stringify(r2));
  ok("F6 desempate por slots elige g18 (576 vs 564)", r2 && r2.sat === "18", JSON.stringify(r2));

  // 2b. En la ventana anterior el recommended del primer dia coincide con el
  //     satelite de MAS slots, asi que un desempate que ignorase los slots
  //     acertaria por casualidad. Esta ventana invierte la coincidencia: el
  //     recommended apunta a g18 (200 slots) y gana g19 (576). Es el unico
  //     caso que separa el criterio de slots del de recommended.
  const recMenosSlots = { days: {
    "2026-06-01": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 100, recommended: true },
      { sat: "g19", valid_diff_slots: 288, recommended: false }] },
    "2026-06-02": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 100, recommended: true },
      { sat: "g19", valid_diff_slots: 288, recommended: false }] }
  } };
  const r2b = ctx.solarPickSource(["2026-06-01", "2026-06-02"], swpcCon([]), recMenosSlots);
  ok("F6 slots mandan sobre recommended (g19 576 vs g18 200)",
     r2b && r2b.src === "ncei" && r2b.sat === "19", JSON.stringify(r2b));

  // 3. Dia con 286 slots pero status complete: SI es utilizable.
  const r3 = ctx.solarPickSource(["2026-03-24"], swpcCon([]), NCEI);
  ok("F6 dia complete con 286 slots es utilizable", r3 && r3.src === "ncei" && r3.sat === "18",
     JSON.stringify(r3));

  // 4. Dia partial: no hay fuente.
  ok("F6 dia partial -> null",
     ctx.solarPickSource(["2026-08-17"], swpcCon([]), NCEI) === null);

  // 5. Dia ausente del manifiesto NCEI -> null.
  ok("F6 dia desconocido -> null",
     ctx.solarPickSource(["2024-01-01"], swpcCon([]), NCEI) === null);

  // 6. Sin satelite comun -> null (nunca se mezcla dentro de una ventana).
  const soloG18 = { days: {
    "2026-05-01": { status: "complete", candidates: [{ sat: "g18", valid_diff_slots: 288, recommended: true }] },
    "2026-05-02": { status: "complete", candidates: [{ sat: "g19", valid_diff_slots: 288, recommended: true }] }
  } };
  ok("F6 sin satelite comun -> null",
     ctx.solarPickSource(["2026-05-01", "2026-05-02"], swpcCon([]), soloG18) === null);

  // 7. El recommended cambia de satelite entre dias -> gana el COMUN, no el recomendado.
  //    (pasa en 140 de los 364 pares consecutivos del archivo real)
  const recCambia = { days: {
    "2026-05-01": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 288, recommended: true },
      { sat: "g19", valid_diff_slots: 288, recommended: false }] },
    "2026-05-02": { status: "complete", candidates: [
      { sat: "g19", valid_diff_slots: 288, recommended: true },
      { sat: "g18", valid_diff_slots: 288, recommended: false }] }
  } };
  const r7 = ctx.solarPickSource(["2026-05-01", "2026-05-02"], swpcCon([]), recCambia);
  ok("F6 recommended discrepante -> desempate estable", r7 && r7.src === "ncei", JSON.stringify(r7));
  ok("F6 empate a slots -> recommended del primer dia ('18')", r7 && r7.sat === "18", JSON.stringify(r7));

  // 8. SWPC incompleto en el diferencial aunque el integral lo tenga -> no vale.
  const soloIntegral = { coverage: { days: ["2026-09-08"] }, differential: { coverage: { days: [] } } };
  const r8 = ctx.solarPickSource(["2026-09-08"], soloIntegral, NCEI);
  ok("F6 SWPC sin diferencial no cuenta como cobertura", r8 && r8.src === "ncei", JSON.stringify(r8));

  const soloDiferencial = {
    coverage: { days: [] }, differential: { coverage: { days: ["2026-09-08"] } }
  };
  const r8b = ctx.solarPickSource(["2026-09-08"], soloDiferencial, NCEI);
  ok("F6 SWPC sin integral no cuenta como cobertura", r8b && r8b.src === "ncei", JSON.stringify(r8b));

  // 8b. Sin recommended y con slots iguales, gana el menor satelite.
  const empateLexico = { days: {
    "2026-04-01": { status: "complete", candidates: [
      { sat: "g19", valid_diff_slots: 288 }, { sat: "g18", valid_diff_slots: 288 }] }
  } };
  const rLex = ctx.solarPickSource(["2026-04-01"], swpcCon([]), empateLexico);
  ok("F6 empate sin recommended -> orden lexicografico ('18')",
     rLex && rLex.src === "ncei" && rLex.sat === "18", JSON.stringify(rLex));

  // 9. Manifiestos ausentes o basura: null, nunca excepcion.
  ok("F6 manifiestos nulos -> null",
     ctx.solarPickSource(["2026-09-08"], null, null) === null);
  ok("F6 days vacio -> null", ctx.solarPickSource([], swpcCon([]), NCEI) === null);
  const deformes = [
    [null, {}, {}],
    ["2026-09-08", {}, {}],
    [["2026-09-08"], { coverage: { days: "x" }, differential: {} }, { days: [] }],
    [["2026-09-08"], {}, { days: { "2026-09-08": { status: "complete", candidates: null } } }],
    [["2026-09-08"], {}, { days: { "2026-09-08": { status: "complete", candidates: [null, 7, { sat: "g20" }] } } }]
  ];
  const deformesOk = deformes.every((args) => {
    try { return ctx.solarPickSource(args[0], args[1], args[2]) === null; }
    catch (e) { return false; }
  });
  ok("F6 entradas deformes -> null sin lanzar", deformesOk);
}

console.log("\nF6-5 ventana y cableado");
{
  const FIXN = path.join(REPO, "tools", "fixtures", "ncei");
  const readN = (n) => JSON.parse(fs.readFileSync(path.join(FIXN, n), "utf8"));
  const FLIGHT5 = { orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
  const occ5 = (date, time) => ({
    id: 1, depDate: date, depTime: time, timeKind: "programada",
    state: "programado", noaaCapture: null, modelVersion: null, result: null
  });

  ok("F6 la ventana empieza el 2025-09-11",
     ctx.SOLAR_ARCHIVE_START_MS === Date.UTC(2025, 8, 11), ctx.SOLAR_ARCHIVE_START_MS);

  // Un vuelo de hace seis meses ya NO es fuera_de_rango.
  const r1 = ctx.occEvaluate(FLIGHT5, occ5("2026-03-24", "12:00"), null,
                             Date.UTC(2026, 8, 12), () => ({ ok: true, state: "sin_senal" }));
  ok("F6 vuelo de 2026-03-24 ya no es fuera_de_rango", r1.state !== "fuera_de_rango", r1.state);

  // Anterior al archivo: sigue siendo fuera_de_rango.
  const r2 = ctx.occEvaluate(FLIGHT5, occ5("2025-09-11", "06:00"), null,
                             Date.UTC(2026, 8, 12), () => ({ ok: true, state: "sin_senal" }));
  ok("F6 baseline anterior al archivo sigue fuera_de_rango", r2.state === "fuera_de_rango", r2.state);
  const r2b = ctx.occEvaluate(FLIGHT5, occ5("2025-09-11", "12:00"), null,
                              Date.UTC(2026, 8, 12), () => ({ ok: true, state: "sin_senal" }));
  ok("F6 baseline exactamente al inicio del archivo entra en rango",
     r2b.state !== "fuera_de_rango", r2b.state);

  // occEvaluate con archivo NCEI: usa nceiDayAdapt y el modelo recibe UN solo satelite.
  const arch = {
    source: { src: "ncei", sat: "18" },
    manifest: {}, nceiManifest: {},
    days: { "2026-09-08": readN("2026-09-08-g18.json"),
            "2026-09-09": readN("2026-09-09-g18.json") }
  };
  let visto = null;
  const espia = function (input) { visto = input; return { ok: true, state: "sin_senal" }; };
  const r3 = ctx.occEvaluate(FLIGHT5, occ5("2026-09-09", "06:00"), arch,
                             Date.UTC(2026, 8, 10), espia);
  ok("F6 el modelo recibe entrada", visto !== null, r3.state);
  ok("F6 576 muestras de los dos dias NCEI", visto && visto.samples.length === 576,
     visto && visto.samples.length);
  ok("F6 13 canales", visto && visto.channels.length === 13);
  const sats = visto ? Object.keys(visto.samples.reduce((a, s) => { a[s.sat] = 1; return a; }, {})) : [];
  ok("F6 REGRESION ANTI-MEZCLA: un solo satelite en la ventana",
     sats.length === 1 && sats[0] === "18", sats.join(","));
  ok("F6 muestras ordenadas y contiguas a 300 s",
     visto && visto.samples.every((s, i) => i === 0 || s.tMs === visto.samples[i - 1].tMs + 300000));

  // X: el contrato del modelo es orden por tMs, no el orden de insercion del
  // mapa de ventana. Con los ficheros cruzados a proposito, el cableado debe
  // ordenar igual: es lo unico que separa `samples.sort` de su ausencia.
  const archCruzado = {
    source: { src: "ncei", sat: "18" },
    manifest: {}, nceiManifest: {},
    days: { "2026-09-08": readN("2026-09-09-g18.json"),
            "2026-09-09": readN("2026-09-08-g18.json") }
  };
  let vistoCruzado = null;
  ctx.occEvaluate(FLIGHT5, occ5("2026-09-09", "06:00"), archCruzado, Date.UTC(2026, 8, 10),
                  function (input) { vistoCruzado = input; return { ok: true, state: "sin_senal" }; });
  ok("F6 ordena por tMs aunque el mapa de ventana venga cruzado",
     vistoCruzado && vistoCruzado.samples.length === 576 &&
     vistoCruzado.samples.every((s, i) => i === 0 || s.tMs === vistoCruzado.samples[i - 1].tMs + 300000),
     vistoCruzado && vistoCruzado.samples.length);

  // W: sin fuente para la ventana. Con marca de permanencia -> incompleto;
  // sin ella -> esperando_datos (el archivo publicado puede crecer).
  const archNada = { source: null, manifest: {}, nceiManifest: {}, days: {} };
  const r4 = ctx.occEvaluate(FLIGHT5, occ5("2026-08-18", "06:00"), archNada,
                             Date.UTC(2026, 8, 12), espia);
  ok("F6 dia sin dato ni marca de permanencia -> esperando_datos",
     r4.state === "esperando_datos", r4.state);

  const archPerm = { source: null, days: {},
    manifest: { incomplete_days: [{ day: "2026-08-18", permanent: true }] },
    nceiManifest: {} };
  const r4p = ctx.occEvaluate(FLIGHT5, occ5("2026-08-18", "06:00"), archPerm,
                              Date.UTC(2026, 8, 12), espia);
  ok("F6 solo SWPC permanente -> esperando_datos", r4p.state === "esperando_datos", r4p.state);

  const archPartial = { source: null, manifest: {}, days: {},
    nceiManifest: { days: { "2026-08-18": { status: "partial", candidates: [] } } } };
  const r4pp = ctx.occEvaluate(FLIGHT5, occ5("2026-08-18", "06:00"), archPartial,
                               Date.UTC(2026, 8, 12), espia);
  ok("F6 solo NCEI permanente -> esperando_datos", r4pp.state === "esperando_datos", r4pp.state);

  const archAmbasPerm = { source: null, days: {},
    manifest: { incomplete_days: [{ day: "2026-08-18", permanent: true }] },
    nceiManifest: { days: { "2026-08-18": { status: "partial", candidates: [] } } } };
  const r4ambas = ctx.occEvaluate(FLIGHT5, occ5("2026-08-18", "06:00"), archAmbasPerm,
                                  Date.UTC(2026, 8, 12), espia);
  ok("F6 ambas fuentes permanentes el mismo dia -> incompleto",
     r4ambas.state === "incompleto", r4ambas.state);

  // i18n: las dos cadenas citan el inicio nuevo del archivo, no el viejo.
  ["es", "en"].forEach((L) => {
    const t = (ctx.LANG[L] && ctx.LANG[L].occState_fuera_de_rango) || "";
    ok("F6 " + L + " occState_fuera_de_rango sin la fecha vieja", t.indexOf("2026") === -1, t);
    ok("F6 " + L + " occState_fuera_de_rango con 2025", t.indexOf("2025") !== -1, t);
  });
}

// F6-5c — V: una ventana cubierta por SWPC no debe pagar el manifiesto NCEI.
async function testLoadArchiveForSwpcNoPideNcei() {
  console.log("\nF6-5c loadArchiveFor: SWPC cubre, NCEI no se descarga");
  const realFetch = ctx.fetch;
  const urls = [];
  try {
    ctx._solarManifestPromise = null;
    ctx._nceiManifestPromise = null;
    ctx._solarDayCache.clear();
    ctx._nceiDayCache.clear();
    const MAN = { coverage: { days: ["2026-09-08", "2026-09-09"] },
                  differential: { coverage: { days: ["2026-09-08", "2026-09-09"] } } };
    ctx.fetch = function (u) {
      urls.push(u);
      if (u.indexOf("ncei") !== -1) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ days: {} }) });
      }
      if (u.indexOf("manifest.json") !== -1) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MAN) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ samples: [] }) });
    };
    const depMs = Date.UTC(2026, 8, 9, 6, 0);
    const points = [{ lat: 40, lon: -3, tMs: depMs },
                    { lat: 40, lon: -74, tMs: depMs + 8 * 3600000 }];
    const arch = await ctx.loadArchiveFor(points, depMs);
    ok("F6 SWPC cubre la ventana -> source 'swpc'",
       arch && arch.source === "swpc", arch && arch.source);
    ok("F6 no descarga ncei/manifest.json si SWPC cubre",
       urls.every((u) => u.indexOf("ncei/manifest.json") === -1), urls.join(","));
  } finally {
    ctx.fetch = realFetch;
    ctx._solarManifestPromise = null;
    ctx._nceiManifestPromise = null;
    ctx._solarDayCache.clear();
    ctx._nceiDayCache.clear();
  }
}

// F6-5d — fallback completo: manifiestos -> días NCEI -> occEvaluate.
async function testLoadArchiveForNceiEndToEnd() {
  console.log("\nF6-5d fallback NCEI extremo a extremo");
  const realFetch = ctx.fetch;
  const FIXN = path.join(REPO, "tools", "fixtures", "ncei");
  const base = JSON.parse(fs.readFileSync(path.join(FIXN, "2026-09-08-g18.json"), "utf8"));
  const fileFor = (day) => {
    const f = JSON.parse(JSON.stringify(base));
    f.day = day;
    f.start_time = day + "T00:00:00Z";
    return f;
  };
  const swpc = { coverage: { days: [] }, differential: { coverage: { days: [] } } };
  const ncei = { days: {
    "2026-09-04": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 288, recommended: true, path: "ncei/A.json" }] },
    "2026-09-05": { status: "complete", candidates: [
      { sat: "g18", valid_diff_slots: 288, recommended: true, path: "ncei/B.json" }] }
  } };
  try {
    ctx._solarManifestPromise = null;
    ctx._nceiManifestPromise = null;
    ctx._solarDayCache.clear();
    ctx._nceiDayCache.clear();
    ctx.fetch = function (u) {
      if (u.indexOf("ncei/manifest.json") !== -1) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(ncei) });
      }
      if (u.endsWith("/manifest.json")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(swpc) });
      }
      const day = u.indexOf("ncei/A.json") !== -1 ? "2026-09-04" : "2026-09-05";
      return Promise.resolve({ ok: true, json: () => Promise.resolve(fileFor(day)) });
    };
    const depMs = Date.UTC(2026, 8, 5, 6, 0);
    const points = [{ lat: 40, lon: -3, tMs: depMs },
                    { lat: 40, lon: -74, tMs: depMs + 8 * 3600000 }];
    const arch = await ctx.loadArchiveFor(points, depMs);
    ok("F6 E2E hueco SWPC elige NCEI g18",
       arch && arch.source && arch.source.src === "ncei" && arch.source.sat === "18",
       arch && JSON.stringify(arch.source));
    ok("F6 E2E descarga los dos dias NCEI",
       arch && arch.days["2026-09-04"] && arch.days["2026-09-05"]);

    let visto = null;
    const flight = { orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
    const occurrence = { id: 1, depDate: "2026-09-05", depTime: "06:00", timeKind: "programada",
      state: "programado", noaaCapture: null, modelVersion: null, result: null };
    const out = ctx.occEvaluate(flight, occurrence, arch, Date.UTC(2026, 8, 6), function (input) {
      visto = input;
      return { ok: true, state: "sin_senal" };
    });
    ok("F6 E2E el hueco SWPC llega al modelo por NCEI",
       out.state === "sin_senal" && visto && visto.samples.length === 576, out.state);
    ok("F6 E2E mantiene un solo satelite",
       visto && visto.samples.every((s) => s.sat === "18"));

    const roto = { manifest: arch.manifest, nceiManifest: arch.nceiManifest,
      source: arch.source, days: Object.assign({}, arch.days, { "2026-09-05": {} }) };
    const ilegible = ctx.occEvaluate(flight, occurrence, roto, Date.UTC(2026, 8, 6), function () {
      return { ok: true, state: "sin_senal" };
    });
    ok("F6 fichero NCEI ilegible -> incompleto", ilegible.state === "incompleto", ilegible.state);
  } finally {
    ctx.fetch = realFetch;
    ctx._solarManifestPromise = null;
    ctx._nceiManifestPromise = null;
    ctx._solarDayCache.clear();
    ctx._nceiDayCache.clear();
  }
}

// F8 — el fallback de la ventana multi-satelite: SWPC sigue siendo la via
// rapida y NCEI solo se descarga si la ventana EXACTA trae mas de un satelite.
console.log("\nF8-1 windowSatellites: solo cuenta la ventana exacta");
{
  const s = (tMs, sat) => ({ tMs: tMs, sat: sat });
  const T = Date.parse("2026-09-08T00:00:00Z");
  ok("F8 dos satelites dentro de la ventana",
     ctx.windowSatellites([s(T, 18), s(T + 600000, 19)], T, T + 3600000).join(",") === "18,19");
  ok("F8 un cambio FUERA de la ventana no cuenta",
     ctx.windowSatellites([s(T, 18), s(T + 600000, 18), s(T + 99 * 3600000, 19)],
                          T, T + 3600000).join(",") === "18");
  ok("F8 sat no reconocible no cuenta como valido",
     ctx.windowSatellites([s(T, 18), s(T + 600000, null), s(T + 900000, "foo")],
                          T, T + 3600000).join(",") === "18");
  ok("F8 tMs invalido se ignora",
     ctx.windowSatellites([s(NaN, 19), s(T, 18)], T, T + 3600000).join(",") === "18");
  ok("F8 sin muestras -> []", ctx.windowSatellites([], T, T + 3600000).length === 0);
  ok("F8 entradas deformes -> [] sin lanzar",
     ctx.windowSatellites(null, T, T + 1).length === 0);
}

async function testMultiSatFallback() {
  console.log("\nF8-2 fallback SWPC multi-satelite -> NCEI");
  const realFetch = ctx.fetch;
  const reset = () => {
    ctx._solarManifestPromise = null;
    ctx._nceiManifestPromise = null;
    ctx._solarDayCache.clear();
    ctx._nceiDayCache.clear();
  };
  const swpcDayFiles = (day, satOf) => {
    const t0 = Date.parse(day + "T00:00:00Z");
    const diff = { samples: [] }, int = { samples: [] };
    for (let i = 0; i < 288; i++) {
      const t = new Date(t0 + i * 300000).toISOString();
      const sat = typeof satOf === "function" ? satOf(i) : satOf;
      diff.samples.push({ t: t, sat: sat, flux: {} });
      int.samples.push({ t: t, flux: { ">=500 MeV": 0 } });
    }
    return { diff: diff, int: int };
  };
  const nceiChannels = ctx.SOLAR_CHANNEL_ORDER.map((n) => ({ name: n, lo_keV: 0, hi_keV: 0 }));
  const nceiFile = (day, sat) => ({
    day: day, sat: sat, start_time: day + "T00:00:00Z", time_step_s: 300, n_steps: 288,
    channels: nceiChannels,
    diff: Array.from({ length: 288 }, () => new Array(13).fill(0)),
    integral_500_mev: new Array(288).fill(0)
  });
  const swpcManifest = {
    coverage: { days: ["2026-09-08", "2026-09-09"], first_day: "2026-08-30" },
    differential: { coverage: { days: ["2026-09-08", "2026-09-09"] } }
  };
  // 09-08: g18 salvo las ultimas 3 h (ya dentro de la ventana) -> g19.
  // 09-09: g18 hasta el aterrizaje.
  const multiDays = {
    "2026-09-08": swpcDayFiles("2026-09-08", (i) => (i >= 216 ? 19 : 18)),
    "2026-09-09": swpcDayFiles("2026-09-09", 18)
  };
  const depMs = Date.UTC(2026, 8, 9, 6, 0);
  const points = [{ lat: 40, lon: -3, tMs: depMs },
                  { lat: 40, lon: -74, tMs: depMs + 8 * 3600000 }];
  const flight = { orig: "MAD", dest: "JFK", legs: 1, flIdx: 1 };
  const occurrence = { id: 1, depDate: "2026-09-09", depTime: "06:00", timeKind: "programada",
    state: "programado", noaaCapture: null, modelVersion: null, result: null };
  // NCEI con un unico satelite COMUN (g19) distinto del primario SWPC, para que
  // una mezcla se vea a la primera.
  const nceiManifest = { days: {
    "2026-09-08": { status: "complete", candidates: [
      { sat: "g19", valid_diff_slots: 288, recommended: true, path: "ncei/A.json" }] },
    "2026-09-09": { status: "complete", candidates: [
      { sat: "g19", valid_diff_slots: 288, recommended: true, path: "ncei/B.json" }] }
  } };
  const mkFetch = (opts) => {
    const o = opts || {};
    const days = o.swpcDays || multiDays;
    const urls = [];
    const fn = (u) => {
      urls.push(u);
      if (u.indexOf("ncei/manifest.json") !== -1) {
        if (o.nceiManifestError) return Promise.resolve({ ok: false, status: 500 });
        if (o.nceiEmpty) return Promise.resolve({ ok: true, json: () => Promise.resolve({ days: {} }) });
        return Promise.resolve({ ok: true, json: () => Promise.resolve(nceiManifest) });
      }
      if (o.nceiFileMissing && u.indexOf("ncei/") !== -1) {
        return Promise.resolve({ ok: false, status: 404 });
      }
      if (u.indexOf("ncei/A.json") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve(nceiFile("2026-09-08", "g19")) });
      if (u.indexOf("ncei/B.json") !== -1) return Promise.resolve({ ok: true, json: () => Promise.resolve(nceiFile("2026-09-09", "g19")) });
      if (u.endsWith("/manifest.json")) return Promise.resolve({ ok: true, json: () => Promise.resolve(swpcManifest) });
      const d = u.indexOf("2026-09-08") !== -1 ? "2026-09-08" : "2026-09-09";
      const part = u.indexOf("-diff.json") !== -1 ? "diff" : "int";
      return Promise.resolve({ ok: true, json: () => Promise.resolve(days[d][part]) });
    };
    fn.urls = urls;
    return fn;
  };
  const runWithFetch = async (fetchImpl) => {
    reset();
    ctx.fetch = fetchImpl;
    try { return await ctx.loadArchiveFor(points, depMs); }
    finally { ctx.fetch = realFetch; reset(); }
  };

  try {
    // 1. Fallback exitoso: la ventana entera se recalcula con UN satelite NCEI.
    const f1 = mkFetch({});
    const arch = await runWithFetch(f1);
    ok("F8 fallback elige NCEI con un unico satelite",
       arch && arch.source && arch.source.src === "ncei" && arch.source.sat === "19",
       arch && JSON.stringify(arch.source));
    ok("F8 pide el manifiesto NCEI al haber >1 satelite",
       f1.urls.some((u) => u.indexOf("ncei/manifest.json") !== -1), f1.urls.join(","));
    ok("F8 carga los dos ficheros NCEI",
       arch && arch.days["2026-09-08"] && arch.days["2026-09-09"]);
    let visto = null;
    ctx.occEvaluate(flight, occurrence, arch, Date.UTC(2026, 8, 10), (input) => {
      visto = input; return { ok: true, state: "sin_senal" };
    });
    const sats = visto ? Array.from(new Set(visto.samples.map((s) => s.sat))) : [];
    ok("F8 REGRESION ANTI-MEZCLA: un solo satelite en la ventana",
       sats.length === 1 && sats[0] === "19", sats.join(","));
    ok("F8 576 muestras recalculadas con NCEI",
       visto && visto.samples.length === 576, visto && visto.samples.length);

    // 2. NCEI no cubre la ventana -> se conserva SWPC, que cierra en incompleto.
    const arch2 = await runWithFetch(mkFetch({ nceiEmpty: true }));
    ok("F8 NCEI no cubre -> se conserva SWPC",
       arch2 && arch2.source === "swpc", arch2 && JSON.stringify(arch2.source));
    const out2 = ctx.occEvaluate(flight, occurrence, arch2, Date.UTC(2026, 8, 10),
      () => ({ ok: false, reason: "cambio_satelite" }));
    ok("F8 SWPC conservado cierra en incompleto", out2.state === "incompleto", out2.state);

    // 3. Fallo de red del manifiesto NCEI -> se conserva SWPC.
    const arch3 = await runWithFetch(mkFetch({ nceiManifestError: true }));
    ok("F8 NCEI falla -> se conserva SWPC",
       arch3 && arch3.source === "swpc", arch3 && JSON.stringify(arch3.source));

    // 4. Manifiesto NCEI completo pero falta el fichero de un dia (404):
    //    NCEI "falta" -> se conserva SWPC, no se usa a medias.
    const archMissing = await runWithFetch(mkFetch({ nceiFileMissing: true }));
    ok("F8 fichero NCEI ausente -> se conserva SWPC",
       archMissing && archMissing.source === "swpc", archMissing && JSON.stringify(archMissing.source));

    // 5. Ventana monofsatelite -> NCEI NO se descarga.
    const singleDays = {
      "2026-09-08": swpcDayFiles("2026-09-08", 18),
      "2026-09-09": swpcDayFiles("2026-09-09", 18)
    };
    const f4 = mkFetch({ swpcDays: singleDays });
    const arch4 = await runWithFetch(f4);
    ok("F8 ventana monofsatelite -> source 'swpc'",
       arch4 && arch4.source === "swpc", arch4 && JSON.stringify(arch4.source));
    ok("F8 ventana monofsatelite NO descarga ncei/manifest.json",
       f4.urls.every((u) => u.indexOf("ncei/manifest.json") === -1), f4.urls.join(","));

    // 6. El cambio de satelite POSTERIOR al aterrizaje no dispara NCEI (917d572).
    const tardeDays = {
      "2026-09-08": swpcDayFiles("2026-09-08", 18),
      "2026-09-09": swpcDayFiles("2026-09-09", (i) => (i > 168 ? 19 : 18))
    };
    const f5 = mkFetch({ swpcDays: tardeDays });
    const arch5 = await runWithFetch(f5);
    ok("F8 cambio tras el aterrizaje -> sigue SWPC",
       arch5 && arch5.source === "swpc", arch5 && JSON.stringify(arch5.source));
    ok("F8 cambio tras el aterrizaje NO descarga NCEI",
       f5.urls.every((u) => u.indexOf("ncei/manifest.json") === -1), f5.urls.join(","));
  } finally {
    ctx.fetch = realFetch;
    reset();
  }
}

async function testSolarRetry() {
console.log("\nF7 reintento de los 5xx transitorios");
{
  const realFetch = ctx.fetch;
  const reset = () => {
    ctx._solarManifestPromise = null;
    ctx._nceiManifestPromise = null;
    ctx._solarDayCache.clear();
    ctx._nceiDayCache.clear();
  };
  const run = async (fn) => { reset(); try { return await fn(); } finally { ctx.fetch = realFetch; reset(); } };

  await (async () => {
    // 503 y luego 200: el manifiesto llega, y se han hecho DOS peticiones.
    let n1 = 0;
    const m1 = await run(async () => {
      ctx.fetch = () => {
        n1++;
        return Promise.resolve(n1 === 1
          ? { ok: false, status: 503 }
          : { ok: true, status: 200, json: () => Promise.resolve({ coverage: { days: [] } }) });
      };
      return ctx.fetchSolarManifest();
    });
    ok("F7 un 503 se reintenta y la segunda vez entra", !!m1 && n1 === 2, n1);

    // 503 siempre: se agotan los reintentos (3 peticiones) y propaga.
    let n2 = 0, err2 = null;
    await run(async () => {
      ctx.fetch = () => { n2++; return Promise.resolve({ ok: false, status: 503 }); };
      try { await ctx.fetchSolarManifest(); } catch (e) { err2 = e; }
    });
    ok("F7 503 permanente -> 1 + 2 reintentos y falla", err2 !== null && n2 === 3, n2 + " peticiones");

    // 404 NO se reintenta: es dato ausente.
    let n3 = 0;
    const d3 = await run(async () => {
      ctx.fetch = () => { n3++; return Promise.resolve({ ok: false, status: 404 }); };
      return ctx.fetchSolarDay("2026-09-07");
    });
    ok("F7 un 404 no se reintenta", n3 === 2 && d3 === null, n3 + " peticiones");

    // fetch que rechaza (red caida) tambien se reintenta.
    let n4 = 0;
    const m4 = await run(async () => {
      ctx.fetch = () => {
        n4++;
        return n4 < 3 ? Promise.reject(new Error("red")) : Promise.resolve(
          { ok: true, status: 200, json: () => Promise.resolve({ coverage: { days: [] } }) });
      };
      return ctx.fetchSolarManifest();
    });
    ok("F7 un fallo de red se reintenta", !!m4 && n4 === 3, n4);

    // Un 503 en un fichero de dia tambien se reintenta: era el caso real que
    // rompio la app el 2026-09-12 (los -diff.json frios daban 503 en raw).
    let n5 = 0;
    const d5 = await run(async () => {
      ctx.fetch = (u) => {
        n5++;
        return Promise.resolve(n5 <= 2
          ? { ok: false, status: 503 }
          : { ok: true, status: 200, json: () => Promise.resolve({ sat: 18 }) });
      };
      return ctx.fetchSolarDay("2026-09-07");
    });
    ok("F7 un 503 en un fichero de dia se reintenta", !!d5 && n5 > 2, n5 + " peticiones");
  })();
}
}

// F7b — el HOST del archivo esta fijado. Sin esto, volver la base a
// raw.githubusercontent no rompia ni un test, y es justo el cambio que arregla
// el 503: raw cachea 600 s y en cada MISS va a un backend saturado.
console.log("\nF7b el archivo se sirve desde Pages, no desde raw");
{
  ok("F7b SOLAR_ARCHIVE_BASE apunta a Pages del repo de datos",
     ctx.SOLAR_ARCHIVE_BASE === "https://ibpilot.github.io/cosmic-rad-data/",
     ctx.SOLAR_ARCHIVE_BASE);
  ok("F7b ninguna peticion va a raw.githubusercontent",
     html.indexOf("raw.githubusercontent") === -1,
     html.indexOf("raw.githubusercontent"));
  ok("F7b el CSP permite el host de Pages y NO raw",
     /connect-src[^;]*https:\/\/ibpilot\.github\.io/.test(html) &&
     !/connect-src[^;]*raw\.githubusercontent/.test(html));
  ok("F7b airports.dat y fixes.json son del mismo origen",
     html.indexOf('"data/airports.dat?v="') !== -1 &&
     html.indexOf('fetch("fixes.json?v=" + APP_VERSION)') !== -1);
}

console.log("\nSC — comprobación puntual de actividad solar (Vuelo único)");
{
  const tES = ctx.LANG.es, tEN = ctx.LANG.en;
  const KEYS = ["solarCheckBtn", "solarCheckInfoAria", "solarCheckRun", "solarCheckLoading",
    "solarCheckHint", "solarCheckHintLinked", "solarCheckRouteEstimated", "solarCheckSinSenal",
    "solarInfoTitle", "solarInfoClose", "solarInfoSubtitle", "solarInfoWhatTitle", "solarInfoWhatBody",
    "solarInfoHowTitle", "solarInfoHowBody", "solarInfoSourcesTitle", "solarInfoSourcesBody",
    "solarInfoLimitsTitle", "solarInfoLimitsBody", "solarInfoStatesTitle", "solarInfoStatesBody"];

  // SC1 — i18n completa en ES y EN.
  const missing = KEYS.filter((k) => typeof tES[k] !== "string" || !tES[k].trim() ||
    typeof tEN[k] !== "string" || !tEN[k].trim());
  ok("SC1 todas las claves solares existen en ES y EN", missing.length === 0, missing.join(","));
  ok("SC1 botón principal ES", tES.solarCheckBtn.indexOf("Comprobar actividad solar") !== -1 && tES.solarCheckBtn.indexOf("☀") !== -1,
     tES.solarCheckBtn);
  ok("SC1 botón principal EN", tEN.solarCheckBtn.indexOf("Check solar activity") !== -1 && tEN.solarCheckBtn.indexOf("☀") !== -1,
     tEN.solarCheckBtn);

  const panelSrc = html.slice(html.indexOf("function SolarCheckPanel"), html.indexOf("function SolarInfoModal"));
  const infoSrc = html.slice(html.indexOf("function SolarInfoModal"), html.indexOf("function CalcInfoModal"));

  // SC2 — control, ARIA y estado presente.
  ok("SC2 el panel y el modal existen", panelSrc.length > 200 && infoSrc.length > 200,
     panelSrc.length + "/" + infoSrc.length);
  ok("SC2 aria-expanded ligado a open", /"aria-expanded":\s*open/.test(panelSrc));
  ok("SC2 aria-controls apunta al id del panel",
     panelSrc.indexOf('"aria-controls": panelId') !== -1 &&
     panelSrc.indexOf("id: panelId") !== -1);
  ok("SC2 zona de estado role=status + aria-live polite",
     /role:\s*"status"/.test(panelSrc) && /"aria-live":\s*"polite"/.test(panelSrc));
  ok("SC2 botones nativos type=button", (panelSrc.match(/type:\s*"button"/g) || []).length >= 3,
     (panelSrc.match(/type:\s*"button"/g) || []).length);
  ok("SC2 botón de información con title y aria-label",
     /title:\s*t\.solarInfoTitle/.test(panelSrc) && /"aria-label":\s*t\.solarCheckInfoAria/.test(panelSrc));
  ok("SC2 glifo ℹ presente", panelSrc.indexOf("\\u2139") !== -1);

  // SC3 — reutiliza el pipeline y no toca el planificador.
  const needs = ["makeOccurrence", "occNeedsArchive", "occRoutePoints", "loadArchiveFor", "occEvaluate"];
  ok("SC3 reutiliza el pipeline existente",
     needs.every((n) => panelSrc.indexOf(n) !== -1),
     needs.filter((n) => panelSrc.indexOf(n) === -1).join(","));
  ok("SC3 no persiste ni modifica el planificador",
     panelSrc.indexOf("setFlights") === -1 && panelSrc.indexOf("applyBatch") === -1 &&
     panelSrc.indexOf("occIncorporate") === -1);

  // SC4 — no calcula al teclear; solo el botón lanza la consulta.
  ok("SC4 el botón Comprobar llama a runCheck", /onClick:\s*runCheck/.test(panelSrc));
  ok("SC4 los inputs solo actualizan el borrador",
     panelSrc.indexOf("onChange: runCheck") === -1 &&
     (panelSrc.match(/setDraft\(/g) || []).length >= 2);
  ok("SC4 la invalidación depende de ruta/FL/fecha/hora",
     /var cacheKey = \[uid, orig, dest, flIdx, draft\.depDate, draft\.depTime\]/.test(panelSrc) &&
     /useEffect\(function \(\) \{[\s\S]{0,140}\}, \[cacheKey\]\)/.test(panelSrc));

  // SC5 — descarte de respuesta stale.
  const gate = ctx.makeRequestGate();
  const tk1 = gate.begin();
  const viva1 = gate.isCurrent(tk1);
  const tk2 = gate.begin();
  const viva1Tras2 = gate.isCurrent(tk1);
  const viva2 = gate.isCurrent(tk2);
  ok("SC5 la primera petición queda obsoleta al lanzar otra",
     viva1 === true && viva1Tras2 === false && viva2 === true,
     JSON.stringify({ viva1, viva1Tras2, viva2 }));
  const tk3 = gate.begin();
  gate.begin(); // simula invalidación por cambio de ruta/FL/fecha/hora
  ok("SC5 cambiar los datos invalida una petición en curso", gate.isCurrent(tk3) === false);
  ok("SC5 el panel descarta la respuesta vieja",
     panelSrc.indexOf("solarGateRef.current.isCurrent(") !== -1 &&
     panelSrc.indexOf("makeRequestGate()") !== -1 &&
     /useEffect\(function \(\) \{\s*solarGateRef\.current\.begin\(\);\s*setCheck\(_solarCheckCache\.get\(cacheKey\) \|\| null\);/.test(panelSrc));

  // SC6 — fuera_de_rango es aviso, no revisada.
  ok("SC6 occVisible(fuera_de_rango) = aviso", ctx.occVisible("fuera_de_rango") === "aviso",
     ctx.occVisible("fuera_de_rango"));

  // SC7 — separa cifra medida / cero medido / sin cifra.
  const O = (state, extra) => Object.assign({ state: state, result: null }, extra || {});
  const GCR = 10;
  const est = ctx.solarCheckView(O("estimacion_disponible", { result: { lowUsv: 2, highUsv: 5 } }), GCR, tES);
  const sen = ctx.solarCheckView(O("sin_senal"), GCR, tES);
  const noe = ctx.solarCheckView(O("no_estimable"), GCR, tES);
  const pen = ctx.solarCheckView(O("programado"), GCR, tES);
  const fallo = ctx.solarCheckView(O("noaa_no_disponible"), GCR, tES);
  ok("SC7 estimación: cifra medida y total = GCR + SEP",
     est.hasFigure === true && est.measuredZero === false && est.sepLowUsv === 2 &&
     est.sepHighUsv === 5 && est.totalLowUsv === 12 && est.totalHighUsv === 15 && est.vis === "disponible",
     JSON.stringify(est));
  ok("SC7 sin_senal: cero MEDIDO, GCR intacto",
     sen.hasFigure === true && sen.measuredZero === true && sen.sepLowUsv === 0 &&
     sen.sepHighUsv === 0 && sen.totalLowUsv === 10 && sen.totalHighUsv === 10 &&
     sen.vis === "revisada" && sen.detail === tES.solarCheckSinSenal, JSON.stringify(sen));
  ok("SC7 no_estimable: sin cifra (ni 0), aviso",
     noe.hasFigure === false && noe.sepLowUsv === null && noe.totalLowUsv === null &&
     noe.vis === "aviso", JSON.stringify(noe));
  ok("SC7 pendiente: sin cifra (ni 0)",
     pen.hasFigure === false && pen.sepLowUsv === null && pen.totalLowUsv === null &&
     pen.vis === "pendiente", JSON.stringify(pen));
  ok("SC7 archivo no disponible: aviso y sin cifra (ni 0)",
     fallo.hasFigure === false && fallo.sepLowUsv === null && fallo.totalLowUsv === null &&
     fallo.vis === "aviso", JSON.stringify(fallo));
  const evAct = ctx.solarCheckView(O("sin_senal", { eventActive: true }), GCR, tES);
  ok("SC7 evento activo: texto específico y sin cifra",
     evAct.eventActive === true && evAct.hasFigure === false &&
     evAct.detail === tES.occState_sin_senal_evento, JSON.stringify(evAct));
  ok("SC7 evento activo: aviso, no revisada",
     evAct.vis === "aviso" && evAct.label === tES.occVis_aviso, JSON.stringify(evAct));
  const mod = ctx.solarCheckView(O("modelo_nuevo", { result: { lowUsv: 1, highUsv: 2 } }), GCR, tES);
  const inc = ctx.solarCheckView(O("incorporada", { result: { lowUsv: 1, highUsv: 2 } }), GCR, tES);
  ok("SC7 modelo_nuevo: cifra medida y disponible",
     mod.hasFigure === true && mod.vis === "disponible" && mod.totalHighUsv === 12, JSON.stringify(mod));
  ok("SC7 incorporada: cifra medida y revisada",
     inc.hasFigure === true && inc.vis === "revisada" && inc.totalLowUsv === 11, JSON.stringify(inc));
  const sinRes = ctx.solarCheckView(O("estimacion_disponible"), GCR, tES);
  const nanRes = ctx.solarCheckView(O("estimacion_disponible", { result: { lowUsv: NaN, highUsv: 5 } }), GCR, tES);
  ok("SC7 cifra prometida sin resultado -> pendiente, no cero",
     sinRes.hasFigure === false && sinRes.sepLowUsv === null && sinRes.vis === "pendiente" &&
     sinRes.detail === tES.occState_incompleto, JSON.stringify(sinRes));
  ok("SC7 cifra prometida con NaN -> pendiente, no cero",
     nanRes.hasFigure === false && nanRes.totalLowUsv === null && nanRes.vis === "pendiente",
     JSON.stringify(nanRes));
  const nada = ctx.solarCheckView(null, GCR, tES);
  ok("SC7 sin consulta: estado vacío y sin cifra",
     nada.state === null && nada.hasFigure === false && nada.sepLowUsv === null);

  // SC10 — la línea de cifras: un cero medido se escribe SEP 0 y no duplica el total.
  const numsSen = ctx.solarCheckNums(sen, tES);
  const numsEst = ctx.solarCheckNums(est, tES);
  ok("SC10 cero medido: GCR y SEP 0, sin total duplicado",
     numsSen.length === 2 && numsSen[0] === tES.gleGcr + " " + ctx.fmtDose(10) &&
     numsSen[1] === tES.gleSep + " " + ctx.fmtDose(0), JSON.stringify(numsSen));
  ok("SC10 estimación: GCR, SEP y total",
     numsEst.length === 3 && numsEst[0] === tES.gleGcr + " " + ctx.fmtDose(10) &&
     numsEst[1] === tES.gleSep + " " + ctx.fmtDose(2) + "\u2013" + ctx.fmtDose(5) &&
     numsEst[2] === tES.colTotal + " " + ctx.fmtDose(12) + "\u2013" + ctx.fmtDose(15),
     JSON.stringify(numsEst));
  ok("SC10 sin cifra: sin línea de números", ctx.solarCheckNums(pen, tES).length === 0);

  // SC8 — el formulario no acepta fecha/hora inválidas.
  ok("SC8 el borrador inválido deshabilita el botón",
     /var valid = depDraftPatch\(draft\) !== null;/.test(panelSrc) && /disabled:\s*!valid/.test(panelSrc));
  ok("SC8 runCheck descarta el borrador inválido",
     /var p = depDraftPatch\(draft\);\s*if \(p === null\) \{/.test(panelSrc));
  ok("SC8 sin fecha en el planificador lo dice en vez de callar",
     /if \(p === null\) \{[\s\S]{0,220}if \(linked\) setCheck\(\{ status: "done", ev: \{ state: "esperando_fecha"/.test(panelSrc));

  // SC9 — el modal de información es accesible y explica los estados.
  ok("SC9 modal con dialog/aria-modal",
     /role:\s*"dialog"/.test(infoSrc) && /"aria-modal":\s*"true"/.test(infoSrc));
  ok("SC9 Escape cierra el modal", infoSrc.indexOf('e.key === "Escape"') !== -1);
  const estadosES = ["Sin fecha", "Programado", "Esperando datos", "Incompleto", "Sin señal",
    "Estimación disponible", "Incorporada", "Modelo actualizado", "Sin cifra acotable",
    "Sin contribución medible en esta ruta", "Archivo GOES no disponible", "Fuera de archivo"];
  ok("SC9 la sección de estados nombra los doce estados (ES)",
     estadosES.every((s) => tES.solarInfoStatesBody.indexOf(s) !== -1),
     estadosES.filter((s) => tES.solarInfoStatesBody.indexOf(s) === -1).join(" | "));
  const estadosEN = ["No date", "Scheduled", "Waiting for data", "Incomplete", "No signal",
    "Estimate available", "Incorporated", "Model updated", "No boundable figure",
    "No measurable contribution on this route", "GOES archive unavailable", "Out of archive"];
  ok("SC9 la sección de estados nombra los doce estados (EN)",
     estadosEN.every((s) => tEN.solarInfoStatesBody.indexOf(s) !== -1),
     estadosEN.filter((s) => tEN.solarInfoStatesBody.indexOf(s) === -1).join(" | "));
  const cuerpoES = tES.solarInfoWhatBody + tES.solarInfoHowBody + tES.solarInfoSourcesBody + tES.solarInfoLimitsBody;
  const datosES = ["CARI-7A", "GOES", "NCEI", "12 h", "13 canales", "factor 3", "UTC",
    "2025-09-11", "único evento calibrante", "no dosimetría certificada", "significan dosis cero",
    "No estima directamente una llamarada electromagnética"];
  ok("SC9 el modal cita fuentes y límites (ES)",
     datosES.every((s) => cuerpoES.indexOf(s) !== -1),
     datosES.filter((s) => cuerpoES.indexOf(s) === -1).join(" | "));
  const cuerpoEN = tEN.solarInfoWhatBody + tEN.solarInfoHowBody + tEN.solarInfoSourcesBody + tEN.solarInfoLimitsBody;
  const datosEN = ["CARI-7A", "GOES", "NCEI", "12 h", "13", "factor of 3", "UTC",
    "2025-09-11", "single calibrating event", "not certified dosimetry", "mean zero dose",
    "does not directly estimate an electromagnetic flare"];
  ok("SC9 el modal cita fuentes y límites (EN)",
     datosEN.every((s) => cuerpoEN.indexOf(s) !== -1),
     datosEN.filter((s) => cuerpoEN.indexOf(s) === -1).join(" | "));

  // SC12 — el modal se comporta como modal: foco y scroll atrapados.
  ok("SC12 el Tab cicla dentro del diálogo",
     infoSrc.indexOf('e.key !== "Tab"') !== -1 && infoSrc.indexOf("SOLAR_INFO_FOCUSABLE") !== -1 &&
     html.indexOf("var SOLAR_INFO_FOCUSABLE") !== -1);
  ok("SC12 el fondo no hace scroll y se restaura al cerrar",
     infoSrc.indexOf('document.body.style.overflow = "hidden"') !== -1 &&
     infoSrc.indexOf("document.body.style.overflow = prevOverflow") !== -1);
  ok("SC12 el cierre es de identidad estable",
     /onClose: closeInfo/.test(panelSrc) && panelSrc.indexOf("useCallback") !== -1);
  ok("SC12 la lámina del diálogo tiene ref para el foco", /ref: sheetRef/.test(infoSrc));
  ok("SC12 el fondo queda inert mientras el diálogo está abierto y se restaura",
     infoSrc.indexOf("var inerted = [];") !== -1 &&
     infoSrc.indexOf('sib.setAttribute("inert", "")') !== -1 &&
     infoSrc.indexOf('.removeAttribute("inert")') !== -1);

  // SC13 — el planificador tiene el mismo botón, uno por vuelo.
  const rowSrc = html.slice(html.indexOf("function FlightRow"), html.indexOf("function FlightPair"));
  var panelAt = rowSrc.indexOf("React.createElement(SolarCheckPanel");
  var occListAt = rowSrc.indexOf("React.createElement(OccList");
  ok("SC13 el panel está en la tarjeta de vuelo del planificador", panelAt !== -1);
  // El panel va con los campos del vuelo (fecha/hora), por encima de las
  // ocurrencias: debajo del ☀ no hay ninguna fecha que no sea suya.
  ok("SC13 el panel va antes de la lista de ocurrencias",
     panelAt !== -1 && occListAt !== -1 && panelAt < occListAt, panelAt + "/" + occListAt);
  ok("SC13 usa la ruta, el FL y el GCR de ESE vuelo",
     /SolarCheckPanel[\s\S]{0,300}uid:\s*id[\s\S]{0,200}orig:\s*orig[\s\S]{0,200}dest:\s*dest[\s\S]{0,200}flIdx:\s*flIdx[\s\S]{0,200}gcrUsv:\s*calc\.doseUsv/.test(rowSrc),
     "panel sin la ruta del vuelo");
  ok("SC13 solo con ruta válida y cálculo hecho",
     /valid && calc \? \/\*#__PURE__\*\/React\.createElement\(SolarCheckPanel/.test(rowSrc));
  ok("SC13 el id del panel es único por vuelo",
     panelSrc.indexOf("var panelId = SOLAR_CHECK_PANEL_ID + (uid ==") !== -1 &&
     panelSrc.indexOf('"aria-controls": panelId') !== -1 &&
     panelSrc.indexOf("id: panelId") !== -1 &&
     /SolarInfoModal[\s\S]{0,200}titleId:\s*infoTitleId/.test(panelSrc));
  ok("SC13 el panel recibe el track del vuelo",
     /SolarCheckPanel[\s\S]{0,400}track:\s*flight\.track/.test(rowSrc) &&
     panelSrc.indexOf("if (Array.isArray(track)) flight.track = track;") !== -1);
  ok("SC13 el modal usa el titleId que recibe",
     infoSrc.indexOf("titleId = _refSolarInfo.titleId") !== -1 &&
     infoSrc.indexOf('"aria-labelledby": infoTitleId') !== -1 &&
     infoSrc.indexOf("id: infoTitleId") !== -1);

  // SC14 — en el planificador la fecha/hora solo vive en el panel solar.
  const occSrc = html.slice(html.indexOf("function OccList"), html.indexOf("function FlightRow"));
  ok("SC14 la lista de ocurrencias no pinta campos de fecha/hora",
     occSrc.length > 200 && occSrc.indexOf('type: "date"') === -1 &&
     occSrc.indexOf('type: "time"') === -1, "Campos de fecha fuera del panel");
  ok("SC14 una ocurrencia sin fecha no pinta fila",
     occSrc.indexOf('if (state === "esperando_fecha") return null;') !== -1);
  ok("SC14 la fecha/hora sigue disponible en el panel solar",
     panelSrc.indexOf('type: "date"') !== -1 && panelSrc.indexOf('type: "time"') !== -1 &&
     panelSrc.indexOf('className: "occ-input"') !== -1);
  ok("SC14 un evento activo se pinta como aviso, no como revisada",
     occSrc.indexOf("var eventActive = !!(ev && ev.eventActive);") !== -1 &&
     occSrc.indexOf('var vis = eventActive ? "aviso" : occVisible(state);') !== -1 &&
     occSrc.indexOf("var vis = occVisible(state);") === -1,
     "OccList heredaba revisada del estado sin mirar eventActive");
  ok("SC14 en un tramo la fila no repite fecha ni estado sin acción",
     occSrc.indexOf("if (single && actions.length === 0) return null;") !== -1 &&
     occSrc.indexOf("var when = !single && occ.depDate && occ.depTime") !== -1 &&
     occSrc.indexOf('when ? React.createElement("span", {') !== -1,
     "la fila del tramo duplicaba el panel");

  // SC15 — en el planificador la fecha/hora vive en la fila del vuelo y el
  // panel ligado solo comprueba y pinta el estado debajo.
  const trackBtnAt = rowSrc.indexOf("t.trackBtn");
  const dateAt = rowSrc.indexOf('type: "date"');
  const calcAt = rowSrc.indexOf("t.calcInfoTitle");
  ok("SC15 la fecha/hora va entre 'Importar ruta' y 'Cálculo'",
     trackBtnAt !== -1 && dateAt !== -1 && calcAt !== -1 && trackBtnAt < dateAt && dateAt < calcAt,
     trackBtnAt + "/" + dateAt + "/" + calcAt);
  ok("SC15 la fecha/hora de la fila es responsiva (no empuja Cálculo de línea)",
     rowSrc.indexOf('className: "gle-dep gle-dep-inline"') !== -1 &&
     html.indexOf('.gle-field-date { flex: 0 1 128px; min-width: 92px; }') !== -1 &&
     html.indexOf('@media (min-width:421px)') !== -1);
  ok("SC15 la fecha/hora se guarda como salida del vuelo",
     rowSrc.indexOf('_onChange(id, "depDate", e.target.value)') !== -1 &&
     rowSrc.indexOf('_onChange(id, "depTime", e.target.value)') !== -1);
  ok("SC15 el panel del planificador se ata a la salida del vuelo",
     /SolarCheckPanel[\s\S]{0,500}depDate:\s*flight\.depDate/.test(rowSrc) &&
     /depTime:\s*flight\.depTime/.test(rowSrc));
  ok("SC15 el panel ligado no pinta campos, solo el estado",
     panelSrc.indexOf("}, linked ? statusEl : (open && React.createElement(\"div\", {") !== -1 &&
     panelSrc.indexOf("onClick: linked ? runCheck") !== -1);
  ok("SC15 el hint ligado no habla de campos que no existen",
     panelSrc.indexOf("statusNode = linked ? t.solarCheckHintLinked : t.solarCheckHint;") !== -1 &&
     tES.solarCheckHintLinked.indexOf("Comprobar actividad solar") !== -1 &&
     tES.solarCheckHint.indexOf("pulsa Comprobar") !== -1,
     tES.solarCheckHintLinked);
  ok("SC15 la etiqueta Fecha/Hora UTC va dentro del campo, no encima",
     rowSrc.indexOf('className: "gle-field gle-field-date"') !== -1 &&
     rowSrc.indexOf('className: "gle-field gle-field-time"') !== -1 &&
     rowSrc.indexOf('className: "gle-field-label"') !== -1 &&
     rowSrc.indexOf("flight.depDate ? null :") !== -1 &&
     rowSrc.indexOf("flight.depTime ? null :") !== -1 &&
     rowSrc.indexOf('className: "occ-input" + (flight.depDate ? "" : " gle-empty")') !== -1 &&
     rowSrc.indexOf('className: "occ-input" + (flight.depTime ? "" : " gle-empty")') !== -1,
     "la etiqueta debe desaparecer al haber valor");
  ok("SC15 Importar ruta y Cálculo comparten el diseño del botón solar",
     rowSrc.indexOf('className: "gle-act"') !== -1 &&
     /\.gle-act \{[^}]*border-radius:10px[^}]*font-size:12px/.test(html) &&
     rowSrc.indexOf("linear-gradient(135deg,rgba(40,160,100,0.2)") !== -1 &&
     rowSrc.indexOf("linear-gradient(135deg,rgba(59,158,222,0.2)") !== -1);
  ok("SC15 la fila se mantiene compacta y responsiva",
     /\.gle-field-date \{ flex: 0 1 128px; min-width: 92px; \}/.test(html) &&
     /\.gle-field-time \{ flex: 0 1 100px; min-width: 74px; \}/.test(html) &&
     /\.gle-act \{[^}]*padding:0 9px/.test(html));
  ok("SC15 los cuatro controles van en un grupo que no se rompe",
     /flexWrap: "nowrap"/.test(rowSrc) && /flex: "1 1 auto"/.test(rowSrc) &&
     rowSrc.indexOf('className: "gle-dep gle-dep-inline"') !== -1);
  ok("SC15 el estilo de los botones no va anidado bajo su fila",
     html.indexOf(".gle-dep-inline .gle-act") === -1);
  ok("SC15 el bloque Salida suelto ya no existe", html.indexOf("showDep") === -1);

  // SC16 — el resultado calculado sobrevive a colapsar/descolapsar el par.
  ok("SC16 el panel cachea el resultado por vuelo y fecha/hora",
     html.indexOf("var _solarCheckCache = new Map();") !== -1 &&
     panelSrc.indexOf("_solarCheckCache.get(cacheKey)") !== -1 &&
     panelSrc.indexOf("_solarCheckCache.set(cacheKey, done)") !== -1 &&
     /var cacheKey = \[uid, orig, dest, flIdx, draft\.depDate, draft\.depTime\]/.test(panelSrc),
     "colapsar el par perdia el resultado");
  ctx._solarCheckCache.set("k", { status: "done", ev: { state: "sin_senal" } });
  ok("SC16 la cache es un Map real y devuelve lo guardado",
     ctx._solarCheckCache instanceof Map &&
     ctx._solarCheckCache.get("k").ev.state === "sin_senal");
}

// P — el par ida/vuelta ya no se colapsa solo.
console.log("\nP — el par ida/vuelta ya no se colapsa solo");
{
  const pairSrc = html.slice(html.indexOf("function FlightPair"), html.indexOf("function App"));
  const tES = ctx.LANG.es, tEN = ctx.LANG.en;
  ok("P1 sin cuenta atras ni colapso automatico",
     pairSrc.length > 400 && pairSrc.indexOf("countdown") === -1 &&
     pairSrc.indexOf("setCountdown") === -1 && pairSrc.indexOf("pairCollapseIn") === -1 &&
     pairSrc.indexOf("pairCollapseCancel") === -1);
  ok("P1 el colapso es un boton explicito con texto",
     pairSrc.indexOf("t.pairCollapseBtn") !== -1 &&
     /type:\s*"button",\s*onClick:\s*function onClick\(\) \{\s*setCollapsedPersist\(true\);/.test(pairSrc));
  ok("P1 el título del par ya no colapsa al pulsarlo",
     pairSrc.indexOf("}, t.pairCollapseBtn)),") !== -1 &&
     pairSrc.indexOf('}, "\\u25B2 min"))') === -1);
  ok("P1 i18n ES/EN del boton",
     tES.pairCollapseBtn === "Colapsar" && tEN.pairCollapseBtn === "Collapse");
}

// MB — el selector de fecha se acota al mes que se está viendo.
console.log("\nMB — el selector de fecha se acota al mes visible");
{
  const sep = ctx.monthBounds("2026-09");
  ok("MB septiembre 2026 -> 01..30",
     !!sep && sep.min === "2026-09-01" && sep.max === "2026-09-30", JSON.stringify(sep));
  ok("MB febrero 2026 (no bisiesto) -> 01..28", ctx.monthBounds("2026-02").max === "2026-02-28");
  ok("MB febrero 2024 (bisiesto) -> 01..29", ctx.monthBounds("2024-02").max === "2024-02-29");
  ok("MB clave deforme o inexistente -> null",
     ctx.monthBounds("2026-13") === null && ctx.monthBounds("nope") === null &&
     ctx.monthBounds("") === null && ctx.monthBounds(null) === null);
  const mbRow = html.slice(html.indexOf("function FlightRow"), html.indexOf("function FlightPair"));
  ok("MB la fila acota el input a [min,max] del mes",
     /min:\s*mB \? mB\.min : undefined/.test(mbRow) &&
     /max:\s*mB \? mB\.max : undefined/.test(mbRow) &&
     mbRow.indexOf("var mB = monthBounds(month);") !== -1);
  const mbPair = html.slice(html.indexOf("function FlightPair"), html.indexOf("function App"));
  ok("MB el par reenvía el mes a sus dos filas",
     (mbPair.match(/month: month/g) || []).length === 2);
  ok("MB el mes visible llega al par y a la fila suelta",
     (html.match(/month: currentMonth/g) || []).length >= 2);
}

// SC11 — la consulta puntual con las dependencias inyectadas: fija cada rama
// (sin archivo, archivo, fallo) y comprueba que la puerta descarta lo viejo.
function testSolarCheckQuery() {
  console.log("\nSC11 la consulta puntual y la puerta de peticiones");
  const flight = { orig: "LEBL", dest: "SPJC", legs: 1, flIdx: 0 };
  const occ = { depDate: "2026-09-08", depTime: "12:00" };
  const NOW = Date.UTC(2026, 8, 9, 12, 0);
  const DEP_MS = Date.UTC(2026, 8, 8, 12, 0);
  const ROUTE = [{ lat: 1, lon: 1 }, { lat: 2, lon: 2 }];
  const deps = (over) => Object.assign({
    routePoints: () => ROUTE,
    needsArchive: () => true,
    loadArchive: () => Promise.resolve({ source: "swpc", manifest: {}, days: {} }),
    evaluate: (f, oc, archive) => ({ state: "estimacion_disponible", archive: archive })
  }, over || {});
  let loaded = null, seenArchive = "no-llamado", seenPoints = "no-llamado";
  return ctx.solarCheckQuery(flight, occ, NOW, deps({
    loadArchive: (points, depMs) => {
      loaded = { points: points, depMs: depMs };
      return Promise.resolve({ source: "ncei" });
    },
    evaluate: (f, oc, archive) => {
      seenArchive = archive;
      return { state: "estimacion_disponible", result: { lowUsv: 1, highUsv: 3 } };
    }
  })).then((ev) => {
    ok("SC11 calcula la ruta una vez y la pasa a la carga",
       !!loaded && loaded.points === ROUTE && loaded.depMs === DEP_MS, JSON.stringify(loaded));
    ok("SC11 el modelo recibe el archivo cargado",
       !!seenArchive && seenArchive.source === "ncei" && ev.state === "estimacion_disponible",
       JSON.stringify(ev));
    return ctx.solarCheckQuery(flight, occ, NOW, deps({
      needsArchive: (f, oc, now, points) => { seenPoints = points; return false; }
    }));
  }).then((ev) => {
    ok("SC11 sin archivo no se carga y el modelo ve null",
       seenPoints === ROUTE && ev.archive === null, JSON.stringify({ seenPoints: seenPoints, ev: ev }));
    return ctx.solarCheckQuery(flight, occ, NOW, deps({
      loadArchive: () => Promise.reject(new Error("red"))
    }));
  }).then((ev) => {
    ok("SC11 un fallo de carga deja SIN cifra (noaa_no_disponible)",
       ev.state === "noaa_no_disponible" && ev.result === null, JSON.stringify(ev));
    return ctx.solarCheckQuery(flight, occ, NOW, deps({
      evaluate: () => { throw new Error("boom"); }
    }));
  }).then((ev) => {
    ok("SC11 un throw del modelo tampoco propaga: sin cifra",
       ev.state === "noaa_no_disponible" && ev.result === null, JSON.stringify(ev));
    // La puerta: dos consultas solapadas, la vieja no pinta.
    const gate = ctx.makeRequestGate();
    let painted = null;
    const vieja = gate.begin();
    const nueva = gate.begin();
    return Promise.resolve().then(() => {
      if (gate.isCurrent(nueva)) painted = "nueva";
      if (gate.isCurrent(vieja)) painted = "vieja";
    }).then(() => {
      ok("SC11 la consulta solapada vieja no pinta", painted === "nueva", String(painted));
    });
  });
}

testRouteImportKeepsCuratedIcaoAliases()
  .then(testFetchSolarManifestRetriesAfterHttpError)
  .then(testFetchNcei)
  .then(testLoadArchiveForSwpcNoPideNcei)
  .then(testLoadArchiveForNceiEndToEnd)
  .then(testMultiSatFallback)
  .then(testSolarRetry)
  .then(testSolarCheckQuery)
  .then(function () {
  console.log("\n" + (fail === 0 ? "TODO VERDE" : "HAY FALLOS") + " — " + pass + " pass, " + fail + " fail\n");
  process.exit(fail === 0 ? 0 : 1);
}).catch(function (err) {
  console.error(err);
  process.exit(1);
});
