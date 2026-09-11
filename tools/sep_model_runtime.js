/* Synchronous fail-closed SEP model: detection (T7), spectral ensemble (T8)
 * and route integration (T9).
 *
 * Public interface (deliberately small; validators, coverage, bin construction,
 * spectral fitting and the optimizer are private helpers):
 *   SepModel.detect(input)   -> detection state
 *   SepModel.ensemble(input) -> spectral ensemble + range, or a closed error
 *   SepModel.route(input)    -> route-integrated dose range, or a closed error
 *
 * detect(input):
 *   {startMs, samples:[{tMs, sat, <canal>, int500}], channels:[{name,lo_keV,hi_keV}]}
 *   -> {state:"detectado", onsetMs, baseline, thresholds}
 *    | {state:"sin_senal", baseline, thresholds}
 *    | {state:"pendiente", reason}
 *   "pendiente" es la respuesta a cualquier entrada invalida, linea base no
 *   fiable u observacion posterior no evaluable: "no puedo medir" NUNCA se
 *   convierte en "no hay nada". La linea base es una ventana FIJA de 12 h
 *   anteriores a startMs (nunca una mediana rodante, que se contaminaria con el
 *   evento) y la observacion es el tramo posterior a startMs, que debe ser
 *   completo y contiguo a cadencia de 5 min.
 *
 * ensemble(input):
 *   {channels, sample, baseline, operator, rcGV, altitudeKm}
 *   baseline admite tanto el objeto devuelto por detect().baseline como un mapa
 *   plano {canal: mediana}. Devuelve
 *   -> {ok:true, solutions, range:{lowUsvH, highUsvH, factor}}
 *    | {ok:false, code}
 *   Un fallo del operador o de convergencia se propaga como {ok:false}, nunca
 *   como dosis cero. "Compatible" significa ajuste finito + operador valido +
 *   cola 10-20 GeV < 10% del total; no hay umbral de bondad estadistica aqui:
 *   el backtesting es T14.
 *
 * route(input):
 *   {channels, samples, startMs, points:[{tMs, rcGV, altitudeKm}], operator}
 *   Integra el ensemble espectral a lo largo de una ruta: cada paso aporta su
 *   Rc (calculado FUERA del Module, con rcAt) y su altitud, y el flujo se
 *   muestrea del instante UTC con retencion de orden cero a cadencia de 5 min.
 *   -> {ok:true, state:"sin_senal"|"detectado", onsetMs, range, members, steps}
 *    | {ok:false, state:"pendiente", reason}
 *    | {ok:false, code}
 *   Cada miembro del ensemble se integra por separado y el rango se forma
 *   DESPUES de integrar, nunca mezclando minimos y maximos punto a punto. Se
 *   rechaza la cifra (sin numero, no cero) si tailDose/totalDose >= 10% en
 *   cualquier miembro o si totalDose <= numericalErrorDose. Un paso sin exceso
 *   sobre la linea base es dosis cero SOLO si los 13 canales estan presentes y
 *   el flujo no es negativo; un canal ausente/corrupto, un hueco de la serie,
 *   un cambio de satelite o un exceso insuficiente para ajustar cierran la
 *   ocurrencia como pendiente.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.SepModel = api.SepModel;
    root.SEP_MODEL_ERROR_CODES = api.ERROR_CODES;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var ERROR_CODES = Object.freeze({
    ENTRADA_INVALIDA: "ENTRADA_INVALIDA",
    CANALES_INVALIDOS: "CANALES_INVALIDOS",
    CANALES_INCOMPLETOS: "CANALES_INCOMPLETOS",
    AJUSTE_INSUFICIENTE: "AJUSTE_INSUFICIENTE",
    MODELO_NO_DISPONIBLE: "MODELO_NO_DISPONIBLE",
    SIN_CONVERGENCIA: "SIN_CONVERGENCIA",
    NUMERIC_FAILURE: "NUMERIC_FAILURE"
  });

  // Motivos de estado "pendiente". Descriptivos a proposito: distinguen "no hay
  // datos" de "los datos no permiten medir".
  var REASONS = Object.freeze({
    ENTRADA_INVALIDA: "entrada_invalida",
    INICIO_INVALIDO: "inicio_invalido",
    TIMESTAMP_INVALIDO: "timestamp_invalido",
    SIN_DATOS: "sin_datos",
    CANALES_INVALIDOS: "canales_invalidos",
    SATELITE_AUSENTE: "satelite_ausente",
    CAMBIO_SATELITE: "cambio_satelite",
    FLUJO_INVALIDO: "flujo_invalido",
    BASELINE_INCOMPLETA: "baseline_incompleta",
    BASELINE_CONJUNTA_INCOMPLETA: "baseline_conjunta_incompleta",
    BASELINE_CONFLICTIVA: "baseline_conflictiva",
    SIN_OBSERVACION: "sin_observacion",
    OBSERVACION_INCOMPLETA: "observacion_incompleta",
    OBSERVACION_INSUFICIENTE: "observacion_insuficiente",
    OBSERVACION_CONFLICTIVA: "observacion_conflictiva",
    HUECO_OBSERVACION: "hueco_observacion",
    MODELO_NO_RESOLUBLE: "modelo_no_resoluble",
    SIN_CONVERGENCIA: "sin_convergencia"
  });

  // --- Deteccion (T7): constantes -------------------------------------------
  var SAMPLING_INTERVAL_MS = 5 * 60 * 1000;
  var BASELINE_WINDOW_MS = 12 * 60 * 60 * 1000;
  var BASELINE_SLOTS = BASELINE_WINDOW_MS / SAMPLING_INTERVAL_MS;             // 144
  var MIN_BASELINE_COVERAGE = 0.8;
  var MIN_BASELINE_SLOTS = Math.ceil(MIN_BASELINE_COVERAGE * BASELINE_SLOTS); // 116
  var MIN_CONSECUTIVE_SAMPLES = 3;
  var SIGMA_MULTIPLIER = 3;
  var MAD_TO_SIGMA = 1.4826;

  var CHANNEL_NAMES = ["P1", "P2A", "P2B", "P3", "P4", "P5", "P6", "P7",
                       "P8A", "P8B", "P8C", "P9", "P10"];
  // Confirmacion ancha (~83-404 MeV), analogo diferencial de ">=100 MeV". Se
  // eligio sobre P9+P10 con los fixtures: en los seis baselines tranquilos la
  // MAD de P9+P10 es EXACTAMENTE CERO (P9/P10 quedan cuantizados), su umbral
  // 3 sigma degenera a la mediana y confirmaria cualquier fluctuacion. P8+
  // conserva dispersion y separa los eventos reales de los controles.
  var CONFIRMATION_CHANNELS = ["P8A", "P8B", "P8C", "P9", "P10"];
  // Disparador duro diferencial (~160-404 MeV), analogo del integral >=500.
  var TRIGGER_CHANNELS = ["P9", "P10"];
  var INTEGRAL_CHANNEL = "int500";
  var SAMPLE_CHANNELS = CHANNEL_NAMES.concat([INTEGRAL_CHANNEL]);

  // --- Ensemble (T8): constantes --------------------------------------------
  var KEV_PER_GEV = 1e6;
  var MIN_USABLE_BINS = 4;
  var TAIL_MAX_FRACTION = 0.10;
  var RANGE_MIN_FACTOR = 3;

  // --- Optimizador: rangos, pasos, semillas, iteraciones y tolerancias -------
  var GOLDEN_RATIO_INVERSE = 0.6180339887498949;
  var EXPONENT_MIN = -8;              // pendiente log-log minima explorada
  var EXPONENT_MAX = 4;               // pendiente log-log maxima explorada
  var POWER_GAMMA_MIN = -2;           // rejilla gruesa de la ley de potencia
  var POWER_GAMMA_MAX = 8;
  var POWER_GAMMA_COARSE_STEP = 0.05;
  var POWER_GAMMA_REFINE_HALF_WIDTH = 0.1;
  var POWER_GAMMA_REFINE_ITERATIONS = 30;
  var BREAKPOINT_COARSE_STEPS = 20;   // rejilla log de la rodilla (g=0..20)
  var DOUBLE_LAW_STATIC_SEEDS = [[-1, -3], [-2, -4]];
  var DOUBLE_LAW_ALTERNATIONS = 2;    // barridos alternos en la exploracion
  var DOUBLE_LAW_COARSE_ITERATIONS = 20;
  var DOUBLE_LAW_REFINE_ALTERNATIONS = 12;
  var DOUBLE_LAW_REFINE_ITERATIONS = 40;
  var SSE_EARLY_STOP = 1e-12;         // SSE bajo el cual no se refina mas

  function isFiniteNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  function pending(reason) { return { ok: false, reason: reason }; }
  function failed(code) { return { ok: false, code: code }; }

  function median(values) {
    var sorted = [];
    for (var i = 0; i < values.length; i++) {
      if (isFiniteNumber(values[i])) sorted.push(values[i]);
    }
    if (!sorted.length) return NaN;
    sorted.sort(function (a, b) { return a - b; });
    var half = sorted.length >> 1;
    return sorted.length % 2 ? sorted[half] : (sorted[half - 1] + sorted[half]) / 2;
  }

  // Mediana, MAD escalada 1.4826 (sigma robusto) y umbral mediana + 3 sigma.
  function robustStats(values) {
    var center = median(values);
    if (!isFiniteNumber(center)) return null;
    var deviations = [];
    for (var i = 0; i < values.length; i++) {
      if (isFiniteNumber(values[i])) deviations.push(Math.abs(values[i] - center));
    }
    var sigma = MAD_TO_SIGMA * median(deviations);
    if (!isFiniteNumber(sigma)) return null;
    return { median: center, sigma: sigma, threshold: center + SIGMA_MULTIPLIER * sigma };
  }

  // --- Validacion -----------------------------------------------------------
  // Los bordes deben ser numeros finitos: NO se usa Number(), porque "1020",
  // true o null se coercionarian a un numero plausible y colarian un canal
  // malformado. Un borde no numerico es un dato ausente, no un dato valido.
  function validChannelEdges(channel) {
    if (typeof channel.lo_keV !== "number" || !isFinite(channel.lo_keV)) return false;
    if (typeof channel.hi_keV !== "number" || !isFinite(channel.hi_keV)) return false;
    return channel.lo_keV > 0 && channel.hi_keV > channel.lo_keV;
  }

  // Exige exactamente los 13 canales esperados, sin duplicados y con bordes
  // validos. Devuelve el mapa por nombre y la lista en orden canonico.
  function normalizeChannels(channels) {
    if (!Array.isArray(channels) || channels.length !== CHANNEL_NAMES.length) return null;
    var map = {};
    for (var i = 0; i < channels.length; i++) {
      var channel = channels[i];
      if (!channel || typeof channel.name !== "string") return null;
      if (CHANNEL_NAMES.indexOf(channel.name) < 0) return null;
      if (Object.prototype.hasOwnProperty.call(map, channel.name)) return null;
      if (!validChannelEdges(channel)) return null;
      map[channel.name] = { name: channel.name, lo_keV: channel.lo_keV, hi_keV: channel.hi_keV };
    }
    var list = [];
    for (var n = 0; n < CHANNEL_NAMES.length; n++) {
      if (!Object.prototype.hasOwnProperty.call(map, CHANNEL_NAMES[n])) return null;
      list.push(map[CHANNEL_NAMES[n]]);
    }
    return { map: map, list: list };
  }

  // Muestra COMPLETA: timestamp y satelite utilizables y los 13 diferenciales
  // mas el integral presentes y finitos. Un canal ausente no es un cero medido.
  function isCompleteSample(sample) {
    if (!sample || typeof sample !== "object") return false;
    if (!isFiniteNumber(sample.tMs)) return false;
    if (typeof sample.sat !== "string" || !sample.sat) return false;
    for (var i = 0; i < SAMPLE_CHANNELS.length; i++) {
      if (!isFiniteNumber(sample[SAMPLE_CHANNELS[i]])) return false;
    }
    return true;
  }

  // Flujo fisico valido: numero finito y no negativo. Un flujo negativo es un
  // dato corrupto, no un cero: cerrar antes de usarlo evita calcular excesos
  // absurdos (p. ej. -1 - (-2) = +1) que parecerian senal.
  function isValidFlux(value) {
    return isFiniteNumber(value) && value >= 0;
  }

  // Presente pero corrupto (negativo, NaN o infinito). `null`/`undefined` es
  // ausente, no corrupto: en la linea base solo reduce la cobertura.
  function isAbsentFlux(value) {
    return value === null || value === undefined;
  }

  function hasCorruptFlux(sample) {
    for (var i = 0; i < SAMPLE_CHANNELS.length; i++) {
      var value = sample[SAMPLE_CHANNELS[i]];
      if (isAbsentFlux(value)) continue;
      if (!isValidFlux(value)) return true;
    }
    return false;
  }

  function hasNegativeFlux(sample) {
    for (var i = 0; i < SAMPLE_CHANNELS.length; i++) {
      if (sample[SAMPLE_CHANNELS[i]] < 0) return true;
    }
    return false;
  }

  // Ordena y NO descarta nada en silencio: una muestra sin timestamp utilizable
  // es una entrada invalida y debe senalarse, no desaparecer.
  function normalizeSamples(samples) {
    var ordered = [];
    for (var i = 0; i < samples.length; i++) {
      var sample = samples[i];
      if (!sample || typeof sample !== "object" || !isFiniteNumber(sample.tMs)) {
        return pending(REASONS.TIMESTAMP_INVALIDO);
      }
      ordered.push(sample);
    }
    ordered.sort(function (a, b) { return a.tMs - b.tMs; });
    return { ok: true, ordered: ordered };
  }

  // Banda diferencial: suma(flujo[canal] * (hi_keV - lo_keV)). Las densidades
  // vienen por keV; sin ponderar por el ancho, sumar densidades no tiene
  // unidades de flujo integrado y mezcla canales de anchos muy distintos.
  function bandValue(sample, channelMap, names) {
    var total = 0;
    for (var i = 0; i < names.length; i++) {
      var channel = channelMap[names[i]];
      var value = sample[names[i]];
      if (!channel || !isFiniteNumber(value)) return null;
      total += value * (channel.hi_keV - channel.lo_keV);
    }
    return total;
  }

  // Una muestra excede si un disparador duro cruza su umbral (P9+P10 o el
  // integral >=500) Y la confirmacion ancha P8+ tambien. Un canal ausente nunca
  // confirma: dato que falta no es dato en cero.
  function sampleExceeds(sample, channelMap, thresholds) {
    var trigger = bandValue(sample, channelMap, TRIGGER_CHANNELS);
    var confirmation = bandValue(sample, channelMap, CONFIRMATION_CHANNELS);
    if (trigger === null || confirmation === null) return false;
    var hardTrigger = trigger > thresholds.p9p10 ||
      (isFiniteNumber(sample[INTEGRAL_CHANNEL]) && sample[INTEGRAL_CHANNEL] > thresholds.int500);
    return hardTrigger && confirmation > thresholds.p8plus;
  }

  // --- Construccion de baseline --------------------------------------------
  function slotIndex(tMs, windowStart) {
    return Math.floor((tMs - windowStart) / SAMPLING_INTERVAL_MS);
  }

  // Agrupa por timestamp exacto y devuelve los timestamps en orden ascendente.
  // El orden de las claves no depende del orden de entrada.
  function groupByTimestamp(samples) {
    var groups = {};
    var timestamps = [];
    for (var i = 0; i < samples.length; i++) {
      var key = String(samples[i].tMs);
      if (!Object.prototype.hasOwnProperty.call(groups, key)) {
        groups[key] = [];
        timestamps.push(samples[i].tMs);
      }
      groups[key].push(samples[i]);
    }
    timestamps.sort(function (a, b) { return a - b; });
    return { groups: groups, timestamps: timestamps };
  }

  // Deduplica el baseline en dos fases, para que el resultado NO dependa del
  // orden de entrada:
  //   1. Por timestamp exacto: duplicados identicos se colapsan a una muestra;
  //      si difieren en satelite, canales o int500, no se puede medir y se
  //      devuelve baseline_conflictiva (antes decidia "la primera gana", lo que
  //      hacia el resultado dependiente del orden).
  //   2. Por slot de 5 min: entre timestamps distintos del mismo slot gana el
  //      cronologicamente primero, para que duplicados no alteren las medianas
  //      ni finjan cobertura.
  // Un flujo presente pero corrupto (negativo, NaN, infinito) cierra antes.
  function collectBaselineRepresentatives(ordered, windowStart, endMs) {
    var inWindow = [];
    var satellites = {};
    for (var i = 0; i < ordered.length; i++) {
      var current = ordered[i];
      if (current.tMs < windowStart || current.tMs >= endMs) continue;
      if (typeof current.sat !== "string" || !current.sat) return pending(REASONS.SATELITE_AUSENTE);
      if (hasCorruptFlux(current)) return pending(REASONS.FLUJO_INVALIDO);
      satellites[current.sat] = true;
      inWindow.push(current);
    }
    var grouped = groupByTimestamp(inWindow);
    var seenSlots = {};
    var representatives = [];
    for (var g = 0; g < grouped.timestamps.length; g++) {
      var resolved = resolveDuplicate(grouped.groups[String(grouped.timestamps[g])]);
      if (!resolved) return pending(REASONS.BASELINE_CONFLICTIVA);
      var slot = slotIndex(resolved.tMs, windowStart);
      if (slot < 0 || slot >= BASELINE_SLOTS) continue;
      if (Object.prototype.hasOwnProperty.call(seenSlots, slot)) continue;
      seenSlots[slot] = true;
      representatives.push(resolved);
    }
    return { ok: true, representatives: representatives, satellites: satellites };
  }

  function perChannelCoverage(representatives) {
    var coverage = {};
    for (var c = 0; c < SAMPLE_CHANNELS.length; c++) {
      var name = SAMPLE_CHANNELS[c];
      var count = 0;
      for (var r = 0; r < representatives.length; r++) {
        if (isFiniteNumber(representatives[r][name])) count++;
      }
      coverage[name] = count;
    }
    return coverage;
  }

  function coverageSatisfied(coverage, required) {
    for (var c = 0; c < SAMPLE_CHANNELS.length; c++) {
      if (coverage[SAMPLE_CHANNELS[c]] < required) return false;
    }
    return true;
  }

  // Cobertura CONJUNTA: cuantos slots tienen P9+P10 completos a la vez y
  // cuantos tienen P8+ completo. Un canal puede tener 116 slots validos y aun
  // asi no dejar ni un solo slot donde la banda entera exista; sin este check,
  // las medianas de banda se calcularian sobre un puñado de muestras.
  function jointBandCoverage(representatives, channelMap) {
    var trigger = 0, confirmation = 0;
    for (var r = 0; r < representatives.length; r++) {
      if (bandValue(representatives[r], channelMap, TRIGGER_CHANNELS) !== null) trigger++;
      if (bandValue(representatives[r], channelMap, CONFIRMATION_CHANNELS) !== null) confirmation++;
    }
    return { p9p10: trigger, p8plus: confirmation };
  }

  function channelStatsFrom(representatives, name) {
    var values = [];
    for (var i = 0; i < representatives.length; i++) {
      var value = representatives[i][name];
      if (isFiniteNumber(value)) values.push(value);
    }
    return robustStats(values);
  }

  function bandStatsFrom(representatives, channelMap, names) {
    var values = [];
    for (var i = 0; i < representatives.length; i++) {
      var value = bandValue(representatives[i], channelMap, names);
      if (value !== null) values.push(value);
    }
    return robustStats(values);
  }

  // Ventana FIJA [startMs - 12 h, startMs). Exige >=116 de 144 slots por cada
  // canal e integral Y >=116 slots completos para cada banda de confirmacion.
  function buildBaseline(input) {
    var channels = normalizeChannels(input.channels);
    if (!channels) return pending(REASONS.CANALES_INVALIDOS);
    if (!Array.isArray(input.samples) || input.samples.length < MIN_CONSECUTIVE_SAMPLES) {
      return pending(REASONS.SIN_DATOS);
    }
    if (!isFiniteNumber(input.startMs)) return pending(REASONS.INICIO_INVALIDO);
    var normalized = normalizeSamples(input.samples);
    if (!normalized.ok) return normalized;
    var ordered = normalized.ordered;
    if (ordered.length < MIN_CONSECUTIVE_SAMPLES) return pending(REASONS.SIN_DATOS);

    var windowStart = input.startMs - BASELINE_WINDOW_MS;
    var collected = collectBaselineRepresentatives(ordered, windowStart, input.startMs);
    if (!collected.ok) return collected;
    var satelliteNames = Object.keys(collected.satellites);
    if (!satelliteNames.length) return pending(REASONS.SIN_DATOS);
    if (satelliteNames.length > 1) return pending(REASONS.CAMBIO_SATELITE);
    var representatives = collected.representatives;

    var coverage = perChannelCoverage(representatives);
    if (!coverageSatisfied(coverage, MIN_BASELINE_SLOTS)) {
      return pending(REASONS.BASELINE_INCOMPLETA);
    }
    var jointCoverage = jointBandCoverage(representatives, channels.map);
    if (jointCoverage.p9p10 < MIN_BASELINE_SLOTS || jointCoverage.p8plus < MIN_BASELINE_SLOTS) {
      return pending(REASONS.BASELINE_CONJUNTA_INCOMPLETA);
    }

    var channelStats = {};
    var medians = {};
    for (var n = 0; n < CHANNEL_NAMES.length; n++) {
      var stats = channelStatsFrom(representatives, CHANNEL_NAMES[n]);
      if (!stats) return pending(REASONS.BASELINE_INCOMPLETA);
      channelStats[CHANNEL_NAMES[n]] = stats;
      medians[CHANNEL_NAMES[n]] = stats.median;
    }
    var integralStats = channelStatsFrom(representatives, INTEGRAL_CHANNEL);
    var triggerStats = bandStatsFrom(representatives, channels.map, TRIGGER_CHANNELS);
    var confirmationStats = bandStatsFrom(representatives, channels.map, CONFIRMATION_CHANNELS);
    if (!integralStats || !triggerStats || !confirmationStats) {
      return pending(REASONS.BASELINE_INCOMPLETA);
    }
    channelStats[INTEGRAL_CHANNEL] = integralStats;
    medians[INTEGRAL_CHANNEL] = integralStats.median;

    var thresholds = {
      p9p10: triggerStats.threshold,
      p8plus: confirmationStats.threshold,
      int500: integralStats.threshold
    };
    var baseline = {
      startMs: windowStart, endMs: input.startMs,
      expected: BASELINE_SLOTS, count: representatives.length,
      coverage: coverage, jointCoverage: jointCoverage,
      satellites: satelliteNames, channels: channelStats, medians: medians,
      median: { p9p10: triggerStats.median, p8plus: confirmationStats.median, int500: integralStats.median },
      sigma: { p9p10: triggerStats.sigma, p8plus: confirmationStats.sigma, int500: integralStats.sigma },
      threshold: thresholds
    };
    return { ok: true, channels: channels, baseline: baseline, thresholds: thresholds,
             samples: ordered, satellite: satelliteNames[0] };
  }

  // --- Observacion posterior a startMs --------------------------------------
  // Agrupa las muestras post-start por timestamp.
  function groupObservationSamples(ordered, startMs) {
    var observed = [];
    for (var i = 0; i < ordered.length; i++) {
      if (ordered[i].tMs >= startMs) observed.push(ordered[i]);
    }
    return groupByTimestamp(observed);
  }

  function sameMeasurement(a, b) {
    if (a.sat !== b.sat) return false;
    for (var i = 0; i < SAMPLE_CHANNELS.length; i++) {
      var name = SAMPLE_CHANNELS[i];
      if (a[name] !== b[name]) return false;
    }
    return true;
  }

  // Duplicados del mismo timestamp: identicos se ignoran (se toma el primero);
  // con valores distintos es una entrada conflictiva y no se puede medir.
  function resolveDuplicate(samples) {
    var first = samples[0];
    for (var i = 1; i < samples.length; i++) {
      if (!sameMeasurement(first, samples[i])) return null;
    }
    return first;
  }

  // Recorrido CRONOLOGICO desde startMs. La primera muestra debe estar
  // exactamente en startMs y la cadencia debe ser exacta. En cuanto hay tres
  // muestras completas, consecutivas y sobre umbral se devuelve el onset; ese
  // onset es IRREVERSIBLE, asi que un problema posterior (hueco, duplicado
  // conflictivo o muestra corrupta) no lo revoca: el bucle ya ha retornado.
  // Un problema ANTES de confirmar el onset devuelve pendiente, nunca sin_senal.
  function scanObservation(ordered, startMs, baselineSatellite, channelMap, thresholds) {
    var grouped = groupObservationSamples(ordered, startMs);
    if (!grouped.timestamps.length) return pending(REASONS.SIN_OBSERVACION);

    // `expected` arranca en startMs: si la primera muestra post-start llega
    // despues, la primera vuelta del bucle ya la rechaza como hueco.
    var consecutive = 0;
    var processed = 0;
    var expected = startMs;
    for (var i = 0; i < grouped.timestamps.length; i++) {
      if (grouped.timestamps[i] !== expected) return pending(REASONS.HUECO_OBSERVACION);
      var sample = resolveDuplicate(grouped.groups[String(expected)]);
      if (!sample) return pending(REASONS.OBSERVACION_CONFLICTIVA);
      if (typeof sample.sat !== "string" || !sample.sat) return pending(REASONS.SATELITE_AUSENTE);
      if (sample.sat !== baselineSatellite) return pending(REASONS.CAMBIO_SATELITE);
      if (!isCompleteSample(sample)) return pending(REASONS.OBSERVACION_INCOMPLETA);
      if (hasNegativeFlux(sample)) return pending(REASONS.FLUJO_INVALIDO);
      processed++;
      if (sampleExceeds(sample, channelMap, thresholds)) {
        consecutive++;
        if (consecutive >= MIN_CONSECUTIVE_SAMPLES) {
          return { ok: true, onsetMs: expected - (MIN_CONSECUTIVE_SAMPLES - 1) * SAMPLING_INTERVAL_MS };
        }
      } else {
        consecutive = 0;
      }
      expected += SAMPLING_INTERVAL_MS;
    }
    if (processed < MIN_CONSECUTIVE_SAMPLES) return pending(REASONS.OBSERVACION_INSUFICIENTE);
    return { ok: true, onsetMs: null };
  }

  function detect(input) {
    if (!input || typeof input !== "object") return { state: "pendiente", reason: REASONS.ENTRADA_INVALIDA };
    var built = buildBaseline(input);
    if (!built.ok) return { state: "pendiente", reason: built.reason };
    var observation = scanObservation(built.samples, input.startMs, built.satellite,
                                      built.channels.map, built.thresholds);
    if (!observation.ok) return { state: "pendiente", reason: observation.reason };
    if (observation.onsetMs === null) {
      return { state: "sin_senal", baseline: built.baseline, thresholds: built.thresholds };
    }
    return { state: "detectado", onsetMs: observation.onsetMs,
             baseline: built.baseline, thresholds: built.thresholds };
  }

  // --- Ajuste espectral (T8) -----------------------------------------------
  // El modelo se compara contra el PROMEDIO ANALITICO del bin, no contra el
  // valor puntual en la media geometrica: el flujo medido es la densidad media
  // del bin y la amplitud se perfila analiticamente para cada forma.
  function powerShape(loGeV, hiGeV, gamma) {
    var exponent = -gamma;
    if (Math.abs(exponent + 1) < 1e-12) return Math.log(hiGeV / loGeV) / (hiGeV - loGeV);
    return (Math.pow(hiGeV, exponent + 1) - Math.pow(loGeV, exponent + 1)) /
      ((exponent + 1) * (hiGeV - loGeV));
  }

  function powerIntegral(a, b, exponent, reference) {
    if (!(b > a)) return 0;
    if (Math.abs(exponent + 1) < 1e-12) return reference * Math.log(b / a);
    return reference * (Math.pow(b / reference, exponent + 1) - Math.pow(a / reference, exponent + 1)) /
      (exponent + 1);
  }

  function doubleShape(loGeV, hiGeV, exponentLow, exponentHigh, breakGeV) {
    var integral = 0;
    if (loGeV < breakGeV) integral += powerIntegral(loGeV, Math.min(hiGeV, breakGeV), exponentLow, breakGeV);
    if (hiGeV > breakGeV) integral += powerIntegral(Math.max(loGeV, breakGeV), hiGeV, exponentHigh, breakGeV);
    return integral / (hiGeV - loGeV);
  }

  // SSE tras perfilar la amplitud (logA = media de los residuos).
  function shapeResidual(bins, shapeFn) {
    var count = bins.length;
    var sum = 0, sumSq = 0;
    for (var i = 0; i < count; i++) {
      var shape = shapeFn(bins[i].loGeV, bins[i].hiGeV);
      if (!isFiniteNumber(shape) || !(shape > 0)) return null;
      var residual = Math.log(bins[i].measuredPerGeV) - Math.log(shape);
      if (!isFiniteNumber(residual)) return null;
      sum += residual;
      sumSq += residual * residual;
    }
    return sumSq - sum * sum / count;
  }

  function amplitudeFrom(bins, shapeFn) {
    var sum = 0;
    for (var i = 0; i < bins.length; i++) {
      var shape = shapeFn(bins[i].loGeV, bins[i].hiGeV);
      if (!isFiniteNumber(shape) || !(shape > 0)) return null;
      var residual = Math.log(bins[i].measuredPerGeV) - Math.log(shape);
      if (!isFiniteNumber(residual)) return null;
      sum += residual;
    }
    var amplitude = Math.exp(sum / bins.length);
    return isFiniteNumber(amplitude) && amplitude > 0 ? amplitude : null;
  }

  // Minimizacion 1D por seccion aurea sobre [low, high]. Un punto no finito se
  // trata como "peor": estrecha el intervalo sin propagar NaN.
  function minimize1D(fn, low, high, iterations) {
    var a = low, b = high;
    var c = b - GOLDEN_RATIO_INVERSE * (b - a), d = a + GOLDEN_RATIO_INVERSE * (b - a);
    var fc = fn(c), fd = fn(d);
    for (var i = 0; i < iterations; i++) {
      if (fc === null || !isFiniteNumber(fc)) {
        a = c; c = d; fc = fd; d = a + GOLDEN_RATIO_INVERSE * (b - a); fd = fn(d); continue;
      }
      if (fd === null || !isFiniteNumber(fd)) {
        b = d; d = c; fd = fc; c = b - GOLDEN_RATIO_INVERSE * (b - a); fc = fn(c); continue;
      }
      if (fc < fd) { b = d; d = c; fd = fc; c = b - GOLDEN_RATIO_INVERSE * (b - a); fc = fn(c); }
      else { a = c; c = d; fc = fd; d = a + GOLDEN_RATIO_INVERSE * (b - a); fd = fn(d); }
    }
    return (a + b) / 2;
  }

  function powerLawSSE(bins, gamma) {
    return shapeResidual(bins, function (loGeV, hiGeV) { return powerShape(loGeV, hiGeV, gamma); });
  }

  // Rejilla gruesa de gamma y refinamiento local por seccion aurea.
  function fitPowerLaw(bins) {
    var best = null;
    for (var gamma = POWER_GAMMA_MIN; gamma <= POWER_GAMMA_MAX + 1e-9;
         gamma += POWER_GAMMA_COARSE_STEP) {
      var sse = powerLawSSE(bins, gamma);
      if (sse === null) continue;
      if (!best || sse < best.sse) best = { gamma: gamma, sse: sse };
    }
    if (!best) return null;
    var refined = minimize1D(function (x) { return powerLawSSE(bins, x); },
                             best.gamma - POWER_GAMMA_REFINE_HALF_WIDTH,
                             best.gamma + POWER_GAMMA_REFINE_HALF_WIDTH,
                             POWER_GAMMA_REFINE_ITERATIONS);
    var amplitude = amplitudeFrom(bins, function (loGeV, hiGeV) {
      return powerShape(loGeV, hiGeV, refined);
    });
    if (amplitude === null || !isFiniteNumber(refined)) return null;
    return {
      model: "power-law", amplitude: amplitude, gamma: refined,
      spectrumAtGeV: function (energyGeV) {
        return energyGeV > 0 ? amplitude * Math.pow(energyGeV, -refined) : 0;
      }
    };
  }

  function doubleLawSSE(bins, exponentLow, exponentHigh, breakGeV) {
    return shapeResidual(bins, function (loGeV, hiGeV) {
      return doubleShape(loGeV, hiGeV, exponentLow, exponentHigh, breakGeV);
    });
  }

  // Exploracion multi-semilla: rodilla en rejilla log de BREAKPOINT_COARSE_STEPS
  // y varios pares de pendientes iniciales (la de la ley de potencia mas dos
  // fijas). Despues, alternancias de coordenadas con refinamiento del log de la
  // rodilla. Sin umbral de bondad: solo se para antes si el SSE es despreciable.
  function fitDoublePowerLaw(bins) {
    var minEnergy = Infinity, maxEnergy = -Infinity;
    for (var i = 0; i < bins.length; i++) {
      if (bins[i].loGeV < minEnergy) minEnergy = bins[i].loGeV;
      if (bins[i].hiGeV > maxEnergy) maxEnergy = bins[i].hiGeV;
    }
    if (!(maxEnergy > minEnergy)) return null;
    var seed = fitPowerLaw(bins);
    var seedExponent = seed ? -seed.gamma : -2.5;
    var seeds = [[seedExponent, seedExponent]].concat(DOUBLE_LAW_STATIC_SEEDS);
    var best = null;
    for (var g = 0; g <= BREAKPOINT_COARSE_STEPS; g++) {
      var breakGeV = minEnergy * Math.pow(maxEnergy / minEnergy, g / BREAKPOINT_COARSE_STEPS);
      for (var si = 0; si < seeds.length; si++) {
        var exponentLow = seeds[si][0], exponentHigh = seeds[si][1];
        for (var round = 0; round < DOUBLE_LAW_ALTERNATIONS; round++) {
          exponentLow = minimize1D(function (x) { return doubleLawSSE(bins, x, exponentHigh, breakGeV); },
                                   EXPONENT_MIN, EXPONENT_MAX, DOUBLE_LAW_COARSE_ITERATIONS);
          exponentHigh = minimize1D(function (x) { return doubleLawSSE(bins, exponentLow, x, breakGeV); },
                                    EXPONENT_MIN, EXPONENT_MAX, DOUBLE_LAW_COARSE_ITERATIONS);
        }
        var sse = doubleLawSSE(bins, exponentLow, exponentHigh, breakGeV);
        if (sse === null) continue;
        if (!best || sse < best.sse) {
          best = { exponentLow: exponentLow, exponentHigh: exponentHigh, breakGeV: breakGeV, sse: sse };
        }
      }
    }
    if (!best) return null;
    var lowExp = best.exponentLow, highExp = best.exponentHigh, knee = best.breakGeV;
    for (var refine = 0; refine < DOUBLE_LAW_REFINE_ALTERNATIONS; refine++) {
      lowExp = minimize1D(function (x) { return doubleLawSSE(bins, x, highExp, knee); },
                          EXPONENT_MIN, EXPONENT_MAX, DOUBLE_LAW_REFINE_ITERATIONS);
      highExp = minimize1D(function (x) { return doubleLawSSE(bins, lowExp, x, knee); },
                           EXPONENT_MIN, EXPONENT_MAX, DOUBLE_LAW_REFINE_ITERATIONS);
      var logBreak = minimize1D(function (x) {
        return doubleLawSSE(bins, lowExp, highExp, Math.exp(x));
      }, Math.log(minEnergy / 2), Math.log(maxEnergy * 2), DOUBLE_LAW_REFINE_ITERATIONS);
      knee = Math.exp(logBreak);
      var residual = doubleLawSSE(bins, lowExp, highExp, knee);
      if (residual !== null && residual < SSE_EARLY_STOP) break;
    }
    var amplitude = amplitudeFrom(bins, function (loGeV, hiGeV) {
      return doubleShape(loGeV, hiGeV, lowExp, highExp, knee);
    });
    if (amplitude === null || !isFiniteNumber(knee) || !(knee > 0)) return null;
    return {
      model: "double-power-law", amplitude: amplitude, breakGeV: knee,
      gamma1: -lowExp, gamma2: -highExp,
      spectrumAtGeV: function (energyGeV) {
        if (!(energyGeV > 0)) return 0;
        return amplitude * Math.pow(energyGeV / knee, energyGeV < knee ? lowExp : highExp);
      }
    };
  }

  function widenLogRange(low, high, minFactor) {
    if (!(low > 0) || !(high >= low)) return null;
    if (high / low >= minFactor) return { lowUsvH: low, highUsvH: high, factor: high / low };
    var center = Math.sqrt(low * high);
    var half = Math.sqrt(minFactor);
    return { lowUsvH: center / half, highUsvH: center * half, factor: minFactor };
  }

  // El baseline puede ser el objeto de detect() (con .medians) o un mapa plano.
  function resolveBaselineValues(baseline) {
    if (!baseline || typeof baseline !== "object") return {};
    if (baseline.medians && typeof baseline.medians === "object") return baseline.medians;
    return baseline;
  }

  // Construye los bins del ajuste: recorta el exceso negativo a cero y convierte
  // por-keV a por-GeV (1 GeV = 1e6 keV). Muestra y baseline deben ser numeros
  // finitos y NO negativos en TODOS los canales: una densidad negativa es un
  // dato corrupto y cierra, en vez de restarse y producir un exceso falso.
  function buildBins(channels, sample, baselineValues) {
    var bins = [];
    for (var i = 0; i < channels.list.length; i++) {
      var channel = channels.list[i];
      var measured = sample[channel.name];
      var base = baselineValues[channel.name];
      if (!isValidFlux(measured) || !isValidFlux(base)) {
        return failed(ERROR_CODES.CANALES_INCOMPLETOS);
      }
      var loGeV = channel.lo_keV / KEV_PER_GEV;
      var hiGeV = channel.hi_keV / KEV_PER_GEV;
      if (!(loGeV > 0) || !(hiGeV > loGeV)) return failed(ERROR_CODES.CANALES_INVALIDOS);
      var excessPerKeV = measured - base;
      if (excessPerKeV < 0) excessPerKeV = 0;
      bins.push({ loGeV: loGeV, hiGeV: hiGeV, measuredPerGeV: excessPerKeV * KEV_PER_GEV });
    }
    return { ok: true, bins: bins };
  }

  function usableBins(bins) {
    var usable = [];
    for (var i = 0; i < bins.length; i++) {
      if (bins[i].measuredPerGeV > 0) usable.push(bins[i]);
    }
    return usable;
  }

  function evaluateWithOperator(operator, solution, rcGV, altitudeKm) {
    var result;
    try {
      result = operator.rate({ spectrumAtGeV: solution.spectrumAtGeV, rcGV: rcGV, altitudeKm: altitudeKm });
    } catch (error) {
      return failed(ERROR_CODES.NUMERIC_FAILURE);
    }
    if (!result || result.ok !== true || !isFiniteNumber(result.rateUsvH) || !(result.rateUsvH > 0) ||
        !isFiniteNumber(result.tailRateUsvH) || result.tailRateUsvH < 0) {
      return failed((result && result.code) || ERROR_CODES.NUMERIC_FAILURE);
    }
    return { ok: true, rateUsvH: result.rateUsvH, tailRateUsvH: result.tailRateUsvH };
  }

  // Evalua TODAS las soluciones antes de decidir. Se acumula el primer error sin
  // cortar el bucle, para que una segunda solucion corrupta no pase
  // desapercibida. Cualquier fallo o cola >=10% invalida todo el ensemble.
  function evaluateSolutions(operator, solutions, rcGV, altitudeKm) {
    var rates = [];
    var failure = null;
    for (var s = 0; s < solutions.length; s++) {
      var evaluated = evaluateWithOperator(operator, solutions[s], rcGV, altitudeKm);
      if (!evaluated.ok) { if (!failure) failure = evaluated.code; continue; }
      if (!(evaluated.tailRateUsvH < TAIL_MAX_FRACTION * evaluated.rateUsvH)) {
        if (!failure) failure = ERROR_CODES.SIN_CONVERGENCIA;
        continue;
      }
      solutions[s].rateUsvH = evaluated.rateUsvH;
      solutions[s].tailRateUsvH = evaluated.tailRateUsvH;
      rates.push(evaluated.rateUsvH);
    }
    if (failure || rates.length !== solutions.length) {
      return failed(failure || ERROR_CODES.NUMERIC_FAILURE);
    }
    return { ok: true, rates: rates };
  }

  function ensemble(input) {
    if (!input || typeof input !== "object") return failed(ERROR_CODES.ENTRADA_INVALIDA);
    var operator = input.operator;
    if (!operator || typeof operator.rate !== "function") {
      return failed(ERROR_CODES.MODELO_NO_DISPONIBLE);
    }
    var channels = normalizeChannels(input.channels);
    if (!channels) return failed(ERROR_CODES.CANALES_INVALIDOS);
    if (!input.sample || typeof input.sample !== "object") {
      return failed(ERROR_CODES.ENTRADA_INVALIDA);
    }

    var built = buildBins(channels, input.sample, resolveBaselineValues(input.baseline));
    if (!built.ok) return built;
    var usable = usableBins(built.bins);
    if (usable.length < MIN_USABLE_BINS) return failed(ERROR_CODES.AJUSTE_INSUFICIENTE);

    var solutions = [fitPowerLaw(usable), fitDoublePowerLaw(usable)];
    if (!solutions[0] || !solutions[1]) return failed(ERROR_CODES.AJUSTE_INSUFICIENTE);

    var evaluated = evaluateSolutions(operator, solutions, input.rcGV, input.altitudeKm);
    if (!evaluated.ok) return evaluated;

    var low = evaluated.rates[0], high = evaluated.rates[0];
    for (var r = 1; r < evaluated.rates.length; r++) {
      if (evaluated.rates[r] < low) low = evaluated.rates[r];
      if (evaluated.rates[r] > high) high = evaluated.rates[r];
    }
    var range = widenLogRange(low, high, RANGE_MIN_FACTOR);
    if (!range) return failed(ERROR_CODES.NUMERIC_FAILURE);
    return { ok: true, solutions: solutions, range: range };
  }

  // --- Integracion por ruta (T9) -------------------------------------------
  // Evaluacion del operador para un miembro del ensemble. A diferencia de
  // evaluateWithOperator (que sirve al caso puntual de ensemble) exige tambien
  // la cota de error numerico: la ruta la integra y la usa como puerta final.
  function evaluateMember(operator, solution, rcGV, altitudeKm) {
    var result;
    try {
      result = operator.rate({ spectrumAtGeV: solution.spectrumAtGeV, rcGV: rcGV,
                               altitudeKm: altitudeKm });
    } catch (error) {
      return failed(ERROR_CODES.NUMERIC_FAILURE);
    }
    if (!result || result.ok !== true) {
      return failed((result && result.code) || ERROR_CODES.NUMERIC_FAILURE);
    }
    if (!isFiniteNumber(result.rateUsvH) || !(result.rateUsvH > 0) ||
        !isFiniteNumber(result.tailRateUsvH) || !(result.tailRateUsvH >= 0) ||
        !isFiniteNumber(result.numericalErrorUsvH) || !(result.numericalErrorUsvH >= 0)) {
      return failed(ERROR_CODES.NUMERIC_FAILURE);
    }
    return { ok: true, rateUsvH: result.rateUsvH, tailRateUsvH: result.tailRateUsvH,
             numericalErrorUsvH: result.numericalErrorUsvH };
  }

  // Copia ordenada por tiempo. normalizeSamples ordena pero no devuelve la
  // lista (solo el resultado de detect), y la ruta necesita buscar por instante.
  function sortedByTime(samples) {
    var ordered = [];
    for (var i = 0; i < samples.length; i++) ordered.push(samples[i]);
    ordered.sort(function (a, b) { return a.tMs - b.tMs; });
    return ordered;
  }

  // Retencion de orden cero: la ultima muestra con tMs <= t. Se exige que no
  // haya mas de una cadencia de separacion; un hueco devuelve null (fail-closed)
  // en vez de arrastrar una muestra vieja como si fuera el flujo del instante.
  function sampleAt(ordered, tMs) {
    var low = 0, high = ordered.length - 1, found = null;
    while (low <= high) {
      var mid = (low + high) >> 1;
      if (ordered[mid].tMs <= tMs) { found = ordered[mid]; low = mid + 1; }
      else high = mid - 1;
    }
    if (!found) return null;
    if (tMs - found.tMs >= SAMPLING_INTERVAL_MS) return null;
    return found;
  }

  function validRoutePoints(points) {
    if (!Array.isArray(points) || points.length < 2) return null;
    for (var i = 0; i < points.length; i++) {
      var point = points[i];
      if (!point || !isFiniteNumber(point.tMs) || !isFiniteNumber(point.rcGV) ||
          !isFiniteNumber(point.altitudeKm)) return null;
      if (i && !(point.tMs > points[i - 1].tMs)) return null;
    }
    return points;
  }

  // Un fallo de datos en la ruta se expone con el mismo `state:"pendiente"` que
  // detect(), para que el llamador no tenga que distinguir dos formas de "no
  // puedo medir".
  function routePending(reason) {
    return { ok: false, state: "pendiente", reason: reason };
  }

  function route(input) {
    if (!input || typeof input !== "object") return failed(ERROR_CODES.ENTRADA_INVALIDA);
    var operator = input.operator;
    if (!operator || typeof operator.rate !== "function") {
      return failed(ERROR_CODES.MODELO_NO_DISPONIBLE);
    }
    var points = validRoutePoints(input.points);
    if (!points) return failed(ERROR_CODES.ENTRADA_INVALIDA);
    if (!Array.isArray(input.samples) || input.samples.length < MIN_CONSECUTIVE_SAMPLES) {
      return routePending(REASONS.SIN_DATOS);
    }

    var detection = detect({ startMs: input.startMs, channels: input.channels,
                             samples: input.samples });
    if (detection.state === "pendiente") return routePending(detection.reason);
    if (detection.state === "sin_senal") {
      return { ok: true, state: "sin_senal", onsetMs: null, range: null,
               members: [], steps: 0 };
    }

    var channels = normalizeChannels(input.channels);
    if (!channels) return routePending(REASONS.CANALES_INVALIDOS);
    var baselineValues = resolveBaselineValues(detection.baseline);
    var ordered = sortedByTime(input.samples);
    var satellite = detection.baseline.satellites[0];

    var members = [
      { model: "power-law", doseUsv: 0, tailDoseUsv: 0, errorDoseUsv: 0 },
      { model: "double-power-law", doseUsv: 0, tailDoseUsv: 0, errorDoseUsv: 0 }
    ];
    var measuredSteps = 0;
    for (var i = 0; i + 1 < points.length; i++) {
      var a = points[i], b = points[i + 1];
      var dtH = (b.tMs - a.tMs) / 3600000;
      if (!(dtH > 0)) continue;
      var tMid = (a.tMs + b.tMs) / 2;
      var sample = sampleAt(ordered, tMid);
      if (!sample) return routePending(REASONS.HUECO_OBSERVACION);
      if (typeof sample.sat !== "string" || !sample.sat) {
        return routePending(REASONS.SATELITE_AUSENTE);
      }
      if (sample.sat !== satellite) return routePending(REASONS.CAMBIO_SATELITE);

      var built = buildBins(channels, sample, baselineValues);
      if (!built.ok) return routePending(REASONS.OBSERVACION_INCOMPLETA);
      var usable = usableBins(built.bins);
      if (!usable.length) continue;   // 13 canales presentes y sin exceso: cero medido
      if (usable.length < MIN_USABLE_BINS) return routePending(REASONS.MODELO_NO_RESOLUBLE);

      var solutions = [fitPowerLaw(usable), fitDoublePowerLaw(usable)];
      if (!solutions[0] || !solutions[1]) return routePending(REASONS.MODELO_NO_RESOLUBLE);

      // Punto medio del tramo: regla de punto medio, converge al refinar la ruta.
      var rcGV = (a.rcGV + b.rcGV) / 2;
      var altitudeKm = (a.altitudeKm + b.altitudeKm) / 2;
      for (var s = 0; s < solutions.length; s++) {
        var evaluated = evaluateMember(operator, solutions[s], rcGV, altitudeKm);
        if (!evaluated.ok) return failed(evaluated.code);
        members[s].doseUsv += evaluated.rateUsvH * dtH;
        members[s].tailDoseUsv += evaluated.tailRateUsvH * dtH;
        members[s].errorDoseUsv += evaluated.numericalErrorUsvH * dtH;
      }
      measuredSteps++;
    }

    var low = Infinity, high = -Infinity;
    for (var m = 0; m < members.length; m++) {
      var member = members[m];
      if (!(member.doseUsv > 0)) continue;
      if (member.tailDoseUsv / member.doseUsv >= TAIL_MAX_FRACTION) {
        return routePending(REASONS.SIN_CONVERGENCIA);
      }
      if (member.doseUsv <= member.errorDoseUsv) {
        return routePending(REASONS.MODELO_NO_RESOLUBLE);
      }
      if (member.doseUsv < low) low = member.doseUsv;
      if (member.doseUsv > high) high = member.doseUsv;
    }
    if (low === Infinity) {
      // Evento detectado pero sin contribucion medible a lo largo de esta ruta.
      return { ok: true, state: "detectado", onsetMs: detection.onsetMs, range: null,
               members: members, steps: measuredSteps };
    }
    var range = widenLogRange(low, high, RANGE_MIN_FACTOR);
    if (!range) return failed(ERROR_CODES.NUMERIC_FAILURE);
    return {
      ok: true, state: "detectado", onsetMs: detection.onsetMs,
      range: { lowUsv: range.lowUsvH, highUsv: range.highUsvH, factor: range.factor },
      members: members, steps: measuredSteps
    };
  }

  return {
    SepModel: { detect: detect, ensemble: ensemble, route: route },
    ERROR_CODES: ERROR_CODES
  };
}));
