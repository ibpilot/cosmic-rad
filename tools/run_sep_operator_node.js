#!/usr/bin/env node
/* Execute the production SepDoseOperator under Node for G4/G5. */
const fs = require("fs");
const vm = require("vm");
const { SepDoseOperator } = require("./sep_operator_runtime.js");

function interpolateRows(rows, energy) {
  if (!rows.length) return 0;
  if (energy <= rows[0][0]) return rows[0][1];
  if (energy >= rows[rows.length - 1][0]) return rows[rows.length - 1][1];
  for (let i = 1; i < rows.length; i++) {
    if (energy <= rows[i][0]) {
      const a = rows[i - 1], b = rows[i];
      const f = (energy - a[0]) / (b[0] - a[0]);
      return a[1] + (b[1] - a[1]) * f;
    }
  }
  return rows[rows.length - 1][1];
}

function spectrumFunction(spec) {
  if (spec.type === "power") return (energy) => spec.scale * Math.pow(energy, -2);
  if (spec.type === "broken") return (energy) => {
    const pivot = spec.pivot;
    return spec.scale * (energy <= pivot ? Math.pow(energy, -1.2) :
      Math.pow(pivot, -1.2) * Math.pow(energy / pivot, -5));
  };
  if (spec.type === "gle" || spec.type === "nodal") {
    const rows = spec.rows;
    return (energy) => interpolateRows(rows, energy);
  }
  throw new Error(`spectrum type not supported: ${spec.type}`);
}

const args = process.argv.slice(2);
function argument(name) {
  const index = args.indexOf(name);
  if (index < 0 || index + 1 >= args.length) throw new Error(`missing ${name}`);
  return args[index + 1];
}

const artifactPath = argument("--artifact");
const inputPath = argument("--input");
const source = fs.readFileSync(artifactPath, "utf8");
const sandbox = {};
vm.runInNewContext(source, sandbox, { filename: artifactPath });
const operator = new SepDoseOperator(sandbox.SEP_RESPONSE_OPERATOR);
const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
const result = input.points.map((point) => {
  const spectrum = spectrumFunction(input.spectrum);
  const value = operator.rate({
    spectrumAtGeV: spectrum,
    rcGV: point.rc_gv,
    altitudeKm: point.altitude_km
  });
  return { rc_gv: point.rc_gv, altitude_km: point.altitude_km, result: value };
});
process.stdout.write(JSON.stringify({ model_version: "sep-2", results: result }));
