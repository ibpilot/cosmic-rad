/* Synchronous fail-closed runtime for the SEP_RESPONSE_OPERATOR artefact. */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.SepDoseOperator = api.SepDoseOperator;
    root.SEP_OPERATOR_ERROR_CODES = api.ERROR_CODES;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var ERROR_CODES = Object.freeze({
    MODEL_UNAVAILABLE: "MODEL_UNAVAILABLE",
    INVALID_MODEL: "INVALID_MODEL",
    INVALID_SPECTRUM: "INVALID_SPECTRUM",
    RC_OUT_OF_RANGE: "RC_OUT_OF_RANGE",
    ALTITUDE_OUT_OF_RANGE: "ALTITUDE_OUT_OF_RANGE",
    NUMERIC_FAILURE: "NUMERIC_FAILURE"
  });
  var REQUIRED = {
    schema_version: 2,
    model_version: "sep-2",
    engine_name: "CARI-7A",
    engine_version: "4.2.0",
    species: "proton",
    quantity: "D2",
    geometry: "isotropic-upper",
    shielding: "none",
    input_unit: "proton/(cm2-sr-s-GeV)",
    output_unit: "uSv/h",
    order: "energy-rc-altitude",
    tail_from_gev: 10
  };
  var RC_EXPECTED = [];
  var ALT_EXPECTED = [];
  for (var ri = 0; ri < 71; ri++) RC_EXPECTED.push(ri * 0.25);
  for (var ai = 0; ai < 11; ai++) ALT_EXPECTED.push(8 + ai * 0.5);
  var B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

  function fail(code) {
    return { ok: false, code: code };
  }

  function isFiniteNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function isStrictAxis(axis) {
    if (!Array.isArray(axis) || axis.length < 2) return false;
    for (var i = 0; i < axis.length; i++) {
      if (!isFiniteNumber(axis[i])) return false;
      if (i && !(axis[i] > axis[i - 1])) return false;
    }
    return true;
  }

  function sameAxis(actual, expected) {
    if (!Array.isArray(actual) || actual.length !== expected.length) return false;
    for (var i = 0; i < expected.length; i++) {
      if (actual[i] !== expected[i]) return false;
    }
    return true;
  }

  function decodeBase64(value) {
    if (typeof value !== "string" || !value || value.length % 4 !== 0 ||
        !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) return null;
    try {
      if (typeof atob === "function") {
        var binary = atob(value), bytes = new Uint8Array(binary.length);
        for (var j = 0; j < binary.length; j++) bytes[j] = binary.charCodeAt(j);
        return bytes;
      }
      if (typeof Buffer !== "undefined") return new Uint8Array(Buffer.from(value, "base64"));
    } catch (error) {
      return null;
    }
    return null;
  }

  function decodeFloat32(value, expectedLength) {
    var bytes = decodeBase64(value);
    if (!bytes || bytes.byteLength !== expectedLength * 4 || bytes.byteLength % 4) return null;
    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    var values = new Array(expectedLength);
    for (var i = 0; i < expectedLength; i++) {
      var number = view.getFloat32(i * 4, true);
      if (!isFiniteNumber(number) || number < 0) return null;
      values[i] = number;
    }
    return { bytes: bytes, values: values };
  }

  function validateArtifact(artifact) {
    if (!artifact || typeof artifact !== "object") return { code: ERROR_CODES.MODEL_UNAVAILABLE };
    for (var key in REQUIRED) {
      if (Object.prototype.hasOwnProperty.call(REQUIRED, key) && artifact[key] !== REQUIRED[key]) {
        return { code: ERROR_CODES.INVALID_MODEL };
      }
    }
    if (typeof artifact.distribution_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(artifact.distribution_sha256) ||
        typeof artifact.bo11_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(artifact.bo11_sha256)) {
      return { code: ERROR_CODES.INVALID_MODEL };
    }
    if (typeof artifact.response_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(artifact.response_sha256) ||
        typeof artifact.error_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(artifact.error_sha256) ||
        typeof artifact.validation_run_id !== "string" || !artifact.validation_run_id) {
      return { code: ERROR_CODES.INVALID_MODEL };
    }
    if (!isFiniteNumber(artifact.validation_max_grid_relative_error) ||
        artifact.validation_max_grid_relative_error < 0 ||
        !isFiniteNumber(artifact.validation_max_offgrid_relative_error) ||
        artifact.validation_max_offgrid_relative_error < 0) {
      return { code: ERROR_CODES.INVALID_MODEL };
    }
    if (!isStrictAxis(artifact.energy_gev) || !sameAxis(artifact.rc_gv, RC_EXPECTED) ||
        !sameAxis(artifact.altitude_km, ALT_EXPECTED)) {
      return { code: ERROR_CODES.INVALID_MODEL };
    }
    if (artifact.energy_gev[0] < 0.05 || artifact.energy_gev[artifact.energy_gev.length - 1] > 20) {
      return { code: ERROR_CODES.INVALID_MODEL };
    }
    var length = artifact.energy_gev.length * artifact.rc_gv.length * artifact.altitude_km.length;
    var response = decodeFloat32(artifact.response_data, length);
    var error = decodeFloat32(artifact.error_data, length);
    if (!response || !error) return { code: ERROR_CODES.INVALID_MODEL };
    return { code: null, response: response.values, error: error.values,
             energy: artifact.energy_gev, rc: artifact.rc_gv, altitude: artifact.altitude_km };
  }

  function boundaryValue(value, low, high) {
    if (value < low && low - value < 1e-9) return low;
    if (value > high && value - high < 1e-9) return high;
    return value;
  }

  function bracket(axis, value) {
    if (value === axis[axis.length - 1]) return axis.length - 2;
    var hi = 1;
    while (hi < axis.length && axis[hi] < value) hi++;
    return hi - 1;
  }

  function bilinear(values, base, nAlt, rcAxis, altAxis, rc, altitude) {
    var ri = bracket(rcAxis, rc), ai = bracket(altAxis, altitude);
    var rc0 = rcAxis[ri], rc1 = rcAxis[ri + 1];
    var alt0 = altAxis[ai], alt1 = altAxis[ai + 1];
    var fr = (rc - rc0) / (rc1 - rc0), fa = (altitude - alt0) / (alt1 - alt0);
    var p00 = values[base + ri * nAlt + ai];
    var p01 = values[base + ri * nAlt + ai + 1];
    var p10 = values[base + (ri + 1) * nAlt + ai];
    var p11 = values[base + (ri + 1) * nAlt + ai + 1];
    return p00 + (p10 - p00) * fr + (p01 - p00 + (p11 - p10 - p01 + p00) * fr) * fa;
  }

  function SepDoseOperator(artifact) {
    var checked = validateArtifact(artifact);
    this._artifact = artifact;
    this._valid = !checked.code;
    this._code = checked.code;
    if (this._valid) {
      this._response = checked.response;
      this._error = checked.error;
      this._energy = checked.energy;
      this._rc = checked.rc;
      this._altitude = checked.altitude;
      this._nRc = this._rc.length;
      this._nAlt = this._altitude.length;
    }
  }

  SepDoseOperator.validateArtifact = validateArtifact;

  SepDoseOperator.prototype.rate = function (request) {
    if (!this._valid) return fail(this._code || ERROR_CODES.INVALID_MODEL);
    if (!request || typeof request.spectrumAtGeV !== "function") return fail(ERROR_CODES.INVALID_SPECTRUM);
    var rc = request.rcGV;
    var altitude = request.altitudeKm;
    if (!isFiniteNumber(rc)) return fail(ERROR_CODES.RC_OUT_OF_RANGE);
    if (!isFiniteNumber(altitude)) return fail(ERROR_CODES.ALTITUDE_OUT_OF_RANGE);
    rc = boundaryValue(rc, this._rc[0], this._rc[this._rc.length - 1]);
    altitude = boundaryValue(altitude, this._altitude[0], this._altitude[this._altitude.length - 1]);
    if (rc < this._rc[0] || rc > this._rc[this._rc.length - 1]) return fail(ERROR_CODES.RC_OUT_OF_RANGE);
    if (altitude < this._altitude[0] || altitude > this._altitude[this._altitude.length - 1]) {
      return fail(ERROR_CODES.ALTITUDE_OUT_OF_RANGE);
    }
    var total = 0, tail = 0, numericalError = 0;
    var cellSize = this._nRc * this._nAlt;
    for (var i = 0; i < this._energy.length; i++) {
      var flux;
      try {
        flux = request.spectrumAtGeV(this._energy[i]);
      } catch (error) {
        return fail(ERROR_CODES.INVALID_SPECTRUM);
      }
      if (!isFiniteNumber(flux) || flux < 0) return fail(ERROR_CODES.INVALID_SPECTRUM);
      var base = i * cellSize;
      var coefficient = bilinear(this._response, base, this._nAlt, this._rc, this._altitude, rc, altitude);
      var coefficientError = bilinear(this._error, base, this._nAlt, this._rc, this._altitude, rc, altitude);
      if (!isFiniteNumber(coefficient) || coefficient < 0 || !isFiniteNumber(coefficientError) || coefficientError < 0) {
        return fail(ERROR_CODES.NUMERIC_FAILURE);
      }
      var contribution = coefficient * flux;
      var errorContribution = coefficientError * flux;
      if (!isFiniteNumber(contribution) || contribution < 0 || !isFiniteNumber(errorContribution) || errorContribution < 0) {
        return fail(ERROR_CODES.NUMERIC_FAILURE);
      }
      total += contribution;
      numericalError += errorContribution;
      if (this._energy[i] >= REQUIRED.tail_from_gev) tail += contribution;
    }
    if (!isFiniteNumber(total) || !isFiniteNumber(tail) || !isFiniteNumber(numericalError) ||
        total < 0 || tail < 0 || numericalError < 0 || tail > total + numericalError) {
      return fail(ERROR_CODES.NUMERIC_FAILURE);
    }
    return { ok: true, rateUsvH: total, tailRateUsvH: tail,
             numericalErrorUsvH: numericalError, modelVersion: REQUIRED.model_version };
  };

  return { SepDoseOperator: SepDoseOperator, ERROR_CODES: ERROR_CODES,
           validateArtifact: validateArtifact };
}));
