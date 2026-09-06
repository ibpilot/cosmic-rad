/* Node-only contract tests for the real SepDoseOperator implementation. */
const assert = require("assert");
const { SepDoseOperator, ERROR_CODES, validateArtifact } = require("../sep_operator_runtime.js");

function f32(values) {
  const buffer = Buffer.alloc(values.length * 4);
  values.forEach((value, index) => buffer.writeFloatLE(value, index * 4));
  return buffer.toString("base64");
}

function artifact(makeResponse, makeError) {
  const energy = [0.1, 10];
  const rc = Array.from({ length: 73 }, (_, i) => i * 0.25);
  const altitude = Array.from({ length: 11 }, (_, i) => 8 + i * 0.5);
  const values = [];
  const errors = [];
  for (let ei = 0; ei < energy.length; ei++) {
    for (const r of rc) {
      for (const a of altitude) {
        values.push(makeResponse(ei, r, a));
        errors.push(makeError(ei, r, a));
      }
    }
  }
  return {
    schema_version: 2, model_version: "sep-2", engine_name: "CARI-7A", engine_version: "4.2.0",
    distribution_sha256: "a".repeat(64), bo11_sha256: "b".repeat(64), species: "proton",
    quantity: "D2", geometry: "isotropic-upper", shielding: "none",
    input_unit: "proton/(cm2-sr-s-GeV)", output_unit: "uSv/h", order: "energy-rc-altitude",
    tail_from_gev: 10, energy_gev: energy, rc_gv: rc, altitude_km: altitude,
    response_sha256: "c".repeat(64), error_sha256: "d".repeat(64), validation_run_id: "test",
    validation_max_grid_relative_error: 0, validation_max_offgrid_relative_error: 0,
    response_data: f32(values), error_data: f32(errors)
  };
}

function ok(name, fn) {
  fn();
  process.stdout.write(`ok - ${name}\n`);
}

ok("exact nodal product, tail, error and one call per energy", () => {
  const model = new SepDoseOperator(artifact((ei) => ei + 2, (ei) => (ei + 1) * 0.1));
  let calls = 0;
  const result = model.rate({
    spectrumAtGeV: (energy) => { calls++; return energy === 0.1 ? 2 : 3; },
    rcGV: 0, altitudeKm: 8
  });
  assert.strictEqual(result.ok, true);
  assert.strictEqual(calls, 2);
  assert.strictEqual(result.rateUsvH, 13);
  assert.strictEqual(result.tailRateUsvH, 9);
  assert(Math.abs(result.numericalErrorUsvH - 0.8) < 1e-6);
  assert.strictEqual(result.modelVersion, "sep-2");
});

ok("bilinear interpolation at an off-grid point", () => {
  const model = new SepDoseOperator(artifact((ei, rc, alt) => ei + rc + alt, () => 0.5));
  const result = model.rate({ spectrumAtGeV: () => 1, rcGV: 0.125, altitudeKm: 8.25 });
  assert.strictEqual(result.ok, true);
  assert(Math.abs(result.rateUsvH - ((0 + 0.125 + 8.25) + (1 + 0.125 + 8.25))) < 1e-6);
  assert(Math.abs(result.numericalErrorUsvH - 1) < 1e-6);
});

ok("boundary epsilon is corrected, larger excursions are rejected", () => {
  const model = new SepDoseOperator(artifact(() => 1, () => 0));
  assert.strictEqual(model.rate({ spectrumAtGeV: () => 1, rcGV: -5e-10, altitudeKm: 8 }).ok, true);
  assert.strictEqual(model.rate({ spectrumAtGeV: () => 1, rcGV: -2e-9, altitudeKm: 8 }).code, ERROR_CODES.RC_OUT_OF_RANGE);
  assert.strictEqual(model.rate({ spectrumAtGeV: () => 1, rcGV: 0, altitudeKm: 13 + 2e-9 }).code, ERROR_CODES.ALTITUDE_OUT_OF_RANGE);
});

ok("closed errors never return a zero dose result", () => {
  const model = new SepDoseOperator(artifact(() => 1, () => 0));
  assert.deepStrictEqual(new SepDoseOperator(null).rate({}), { ok: false, code: ERROR_CODES.MODEL_UNAVAILABLE });
  assert.strictEqual(model.rate({ spectrumAtGeV: () => -1, rcGV: 0, altitudeKm: 8 }).code, ERROR_CODES.INVALID_SPECTRUM);
  assert.strictEqual(model.rate({ spectrumAtGeV: () => NaN, rcGV: 0, altitudeKm: 8 }).code, ERROR_CODES.INVALID_SPECTRUM);
  assert.strictEqual(model.rate({ spectrumAtGeV: () => 1, rcGV: 19, altitudeKm: 8 }).code, ERROR_CODES.RC_OUT_OF_RANGE);
});

ok("schema, layout and tensor mutations fail validation", () => {
  const original = artifact(() => 1, () => 0);
  assert.strictEqual(validateArtifact({ ...original, schema_version: 1 }).code, ERROR_CODES.INVALID_MODEL);
  assert.strictEqual(validateArtifact({ ...original, species: ["proton"] }).code, ERROR_CODES.INVALID_MODEL);
  assert.strictEqual(validateArtifact({ ...original, rc_gv: original.rc_gv.slice().reverse() }).code, ERROR_CODES.INVALID_MODEL);
  assert.strictEqual(validateArtifact({ ...original, response_data: f32([1]) }).code, ERROR_CODES.INVALID_MODEL);
  const broken = new SepDoseOperator({ ...original, error_data: f32(new Array(146).fill(-1)) });
  assert.strictEqual(broken.rate({ spectrumAtGeV: () => 1, rcGV: 0, altitudeKm: 8 }).code, ERROR_CODES.INVALID_MODEL);
});

process.stdout.write("SEP OPERATOR NODE TESTS OK\n");
