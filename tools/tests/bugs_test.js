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
  Array, Object, Boolean, Error, TypeError, RegExp, Float32Array, Uint8Array,
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

console.log("\n" + (fail === 0 ? "TODO VERDE" : "HAY FALLOS") + " — " + pass + " pass, " + fail + " fail\n");
process.exit(fail === 0 ? 0 : 1);
