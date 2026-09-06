#!/usr/bin/env python3
"""G4/G5 end-to-end gates for the nodal SEP operator.

Every comparison in this file obtains the reference rate from a real CARI-7A
run and obtains the estimate from ``SepDoseOperator`` executed by Node.  There
is intentionally no analytic fallback: without the CARI executable the gate
fails and CI must retain ``sep-1``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
from statistics import mean

import sep_operator_common as common
from cari7_cutoffs import epoch_file_for_year, load_cutoff_map, points_for_rc_targets
from cari7_sep_gate import run_points, run_spectrum
from cari7_sep_linearity import _interp_from_rows, gle_rows_from_fixture
import cari7_sep_input as sep_input


TOLERANCE = 0.05
DEFAULT_DATE = "2002/01/00"
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "goes", "g16_2021-10-28.json")


def _spectrum_cases(energies):
    gle_rows = gle_rows_from_fixture(FIXTURE, max(64, len(energies)))
    gle_flux = _interp_from_rows(gle_rows)
    gle = [(float(energy), float(gle_flux(energy))) for energy in energies]
    power = [(float(energy), 100.0 * float(energy) ** -2.0) for energy in energies]
    broken = [(float(energy), 100.0 * (float(energy) ** -1.2 if energy <= 1.0
                                      else 1.0 ** -1.2 * (float(energy) / 1.0) ** -5.0))
              for energy in energies]
    rng = random.Random(20260906)
    nodal = [(float(energy), 25.0 + 150.0 * rng.random()) for energy in energies]
    return {
        "gle73": {"type": "gle", "rows": gle},
        "power-law-e-2": {"type": "power", "scale": 100.0, "rows": power},
        "broken-law": {"type": "broken", "scale": 100.0, "pivot": 1.0, "rows": broken},
        "nodal-seeded": {"type": "nodal", "rows": nodal},
    }


def _write_my_model_for_rows(cari_dir, energies, rows):
    from generate_sep_operator import write_my_model_z1

    bo11 = os.path.join(cari_dir, "GCR_MODELS", "BO11_GCR.OUT")
    full_nodes = common.read_bo11_z1_nodes(bo11)
    by_energy = {energy: value for energy, value in rows}
    perturbation = [by_energy.get(energy, 0.0) * common.CM2_TO_M2 for energy in full_nodes]
    return write_my_model_z1(bo11, os.path.join(cari_dir, "GCR_MODELS", "MY_MODEL.OUT"), perturbation)


def _run_node(artifact, spectrum, points):
    with tempfile.TemporaryDirectory(prefix="sep2-node-") as directory:
        input_path = os.path.join(directory, "input.json")
        with open(input_path, "w") as handle:
            json.dump({"spectrum": spectrum, "points": [
                {"rc_gv": rc, "altitude_km": alt} for rc, alt in points
            ]}, handle)
        # Use node directly; the JS file is the same Module the browser ships.
        result = subprocess.run(
            ["node", os.path.join(os.path.dirname(__file__), "run_sep_operator_node.js"),
             "--artifact", artifact, "--input", input_path],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError("operador Node falló:\n" + result.stderr[-4000:])
        return json.loads(result.stdout)


def _choose_offgrid_points(rcmap, count=15):
    candidates = []
    max_rc = common.RC_TARGETS[-1]
    for (lat, lon), rc in sorted(rcmap.items()):
        if not (0 <= rc <= max_rc) or abs(rc * 4.0 - round(rc * 4.0)) < 1e-8:
            continue
        # Fixed latitude bands cover polar, middle and equatorial regions.
        band = 0 if abs(lat) >= 60 else (1 if abs(lat) >= 20 else 2)
        candidates.append((band, abs(lat), lat, lon, rc))
    selected = []
    seen_bands = {0: 0, 1: 0, 2: 0}
    for band, _abs_lat, lat, lon, rc in candidates:
        if seen_bands[band] >= max(1, count // 3):
            continue
        selected.append((lat, lon, rc))
        seen_bands[band] += 1
        if len(selected) >= count:
            break
    return selected


def _metrics(label, direct, operator_results):
    by_point = {(round(item["rc_gv"], 9), round(item["altitude_km"], 9)): item["result"]
                for item in operator_results["results"]}
    relative = []
    absolute_under_error = []
    failures = []
    for point, direct_rate in direct.items():
        key = (round(point[0], 9), round(point[1], 9))
        result = by_point.get(key)
        if not result or result.get("ok") is not True:
            failures.append((point, "operator error"))
            continue
        estimate = float(result["rateUsvH"])
        bound = float(result["numericalErrorUsvH"])
        if direct_rate > bound:
            deviation = abs(estimate - direct_rate) / direct_rate
            relative.append(deviation)
            if deviation > TOLERANCE:
                failures.append((point, deviation))
        else:
            deviation = abs(estimate - direct_rate)
            absolute_under_error.append(deviation)
            if deviation > bound:
                failures.append((point, deviation, bound))
    if failures:
        raise RuntimeError(f"{label}: {len(failures)} puntos fuera de tolerancia; primeros={failures[:3]}")
    sorted_relative = sorted(relative)
    p95 = sorted_relative[min(len(sorted_relative) - 1, max(0, math.ceil(0.95 * len(sorted_relative)) - 1))] if relative else 0.0
    return {
        "label": label,
        "ok": True,
        "points": len(direct),
        "relative_points": len(relative),
        "under_resolution_points": len(absolute_under_error),
        "max_relative_error": max(relative, default=0.0),
        "p95_relative_error": p95,
        "mean_relative_error": mean(relative) if relative else 0.0,
    }


def _monotonicity_metrics(label, direct, operator_results):
    """Check Rc ordering and altitude behaviour against the same CARI run.

    Rc ordering is a hard physical invariant of the operator: a larger cutoff
    rigidity must not increase the dose beyond the two interpolated numerical
    error bounds.  Altitude is deliberately not imposed as a synthetic shape;
    instead, each adjacent altitude pair must have the same resolved ordering
    in the operator and in the corresponding direct CARI points.
    """
    by_point = {(round(item["rc_gv"], 9), round(item["altitude_km"], 9)): item["result"]
                for item in operator_results["results"]
                if item.get("result", {}).get("ok") is True}
    rc_violations = []
    altitude_disagreements = []
    by_alt = {}
    by_rc = {}
    for (rc, altitude), direct_rate in direct.items():
        key = (round(rc, 9), round(altitude, 9))
        result = by_point.get(key)
        if result is None:
            continue
        by_alt.setdefault(key[1], []).append((key[0], float(result["rateUsvH"]),
                                               float(result["numericalErrorUsvH"])))
        by_rc.setdefault(key[0], []).append((key[1], float(direct_rate),
                                             float(result["rateUsvH"]),
                                             float(result["numericalErrorUsvH"])))
    for altitude, values in by_alt.items():
        values.sort()
        for left, right in zip(values, values[1:]):
            # Higher Rc cannot increase dose outside the sum of both local
            # numerical bounds.  Keep the raw excess for the report.
            excess = right[1] - left[1] - left[2] - right[2]
            if excess > 0:
                rc_violations.append((altitude, left[0], right[0], excess))
    for rc, values in by_rc.items():
        values.sort()
        for lower, upper in zip(values, values[1:]):
            direct_delta = upper[1] - lower[1]
            operator_delta = upper[2] - lower[2]
            bound = lower[3] + upper[3]
            # Only compare a resolved ordering.  At/below the propagated
            # bound, either direction is numerically indistinguishable.
            if abs(direct_delta) > bound and abs(operator_delta) > bound and \
                    direct_delta * operator_delta < 0:
                altitude_disagreements.append((rc, lower[0], upper[0],
                                               direct_delta, operator_delta))
    if rc_violations or altitude_disagreements:
        raise RuntimeError(
            f"{label}: G7 monotonicidad inconsistente; "
            f"violaciones Rc={len(rc_violations)}, "
            f"desacuerdos altitud={len(altitude_disagreements)}"
        )
    return {
        "label": label,
        "ok": True,
        "rc_pairs": sum(max(0, len(values) - 1) for values in by_alt.values()),
        "altitude_pairs": sum(max(0, len(values) - 1) for values in by_rc.values()),
        "rc_violations": 0,
        "altitude_disagreements": 0,
    }


def _reference_background(cari_dir, binary, cutoffs, date, rcmap):
    bo11 = os.path.join(cari_dir, "GCR_MODELS", "BO11_GCR.OUT")
    my_model = os.path.join(cari_dir, "GCR_MODELS", "MY_MODEL.OUT")
    backup = None
    if os.path.exists(my_model):
        backup = my_model + ".sep2-backup"
        shutil.copy(my_model, backup)
    try:
        from generate_sep_operator import write_my_model_z1

        full_nodes = common.read_bo11_z1_nodes(bo11)
        write_my_model_z1(bo11, my_model, [0.0] * len(full_nodes))
        return run_spectrum(cari_dir, binary, sep_input.SP_MYMODEL, date,
                            os_name="unix", wine=None, chunk=150, tag="sep2-bg-g4",
                            rcmap=rcmap, cutoffs=cutoffs)
    finally:
        if backup:
            shutil.move(backup, my_model)
        elif os.path.exists(my_model):
            os.unlink(my_model)


def run_gate(args) -> dict:
    artifact = os.path.abspath(args.artifact)
    cari_dir = os.path.abspath(args.cari_dir)
    cutoffs = os.path.abspath(args.cutoffs)
    bo11 = os.path.join(cari_dir, "GCR_MODELS", "BO11_GCR.OUT")
    if not os.path.exists(bo11):
        raise RuntimeError(f"no existe BO11_GCR.OUT: {bo11}")
    full_nodes = common.read_bo11_z1_nodes(bo11)
    energies = common.active_energies(full_nodes)
    cases = _spectrum_cases(energies)
    rcmap = load_cutoff_map(os.path.join(cutoffs, epoch_file_for_year(int(args.date[:4]))))
    background = _reference_background(cari_dir, args.binary, cutoffs, args.date, rcmap)
    report = {"validation_run_id": args.validation_run_id,
              "g4": {"ok": False, "skipped": True},
              "g5": {"ok": False, "skipped": True},
              "g7": {"ok": False, "skipped": True},
              "cases": [], "offgrid_cases": [], "g7_cases": []}

    if not args.offgrid_only:
        for name, spectrum in cases.items():
            _write_my_model_for_rows(cari_dir, energies, spectrum["rows"])
            direct_total = run_spectrum(cari_dir, args.binary, sep_input.SP_MYMODEL, args.date,
                                        os_name="unix", wine=None, chunk=150,
                                        tag=f"sep2-g4-{name}", rcmap=rcmap, cutoffs=cutoffs)
            direct = {key: value - background[key] for key, value in direct_total.items()
                      if key in background}
            points = [key for key in direct if key[0] <= common.RC_TARGETS[-1]]
            direct = {key: value for key, value in direct.items() if key[0] <= common.RC_TARGETS[-1]}
            node = _run_node(artifact, spectrum, points)
            report["cases"].append(_metrics(name, direct, node))
            report["g7_cases"].append(_monotonicity_metrics(name, direct, node))
        report["g4"] = {"ok": True,
                         "max_relative_error": max((case["max_relative_error"] for case in report["cases"]), default=0),
                         "p95_relative_error": max((case["p95_relative_error"] for case in report["cases"]), default=0),
                         "mean_relative_error": mean([case["mean_relative_error"] for case in report["cases"]]) if report["cases"] else 0,
                         "under_resolution_points": sum(case["under_resolution_points"] for case in report["cases"])}
        report["g7"] = {
            "ok": True,
            "rc_pairs": sum(case["rc_pairs"] for case in report["g7_cases"]),
            "altitude_pairs": sum(case["altitude_pairs"] for case in report["g7_cases"]),
            "rc_violations": 0,
            "altitude_disagreements": 0,
        }

    offgrid = _choose_offgrid_points(rcmap)
    if len(offgrid) < 3:
        raise RuntimeError("CARI cutoff map no ofrece suficientes puntos Rc off-grid")
    # One CARI run for all fixed off-grid points per spectrum and three altitudes.
    point_specs = [(lat, lon, alt) for lat, lon, _rc in offgrid
                   for alt in (8.25, 10.25, 12.75)]
    # The CARI parser reports the actual Rc for each geographic point.
    for name in ("gle73", "power-law-e-2", "broken-law"):
        spectrum = cases[name]
        _write_my_model_for_rows(cari_dir, energies, spectrum["rows"])
        direct_total = run_points(cari_dir, args.binary, sep_input.SP_MYMODEL, args.date,
                                  point_specs, os_name="unix", wine=None)
        # Map the geographic probe's CARI key to the fixed result set.  Every
        # returned key is already an off-grid Rc value and the same key exists
        # in the background map from the full run only when it is generated;
        # run_points the background points too to avoid guessing a rate.
        _write_my_model_for_rows(cari_dir, energies, [(energy, 0.0) for energy in energies])
        bg_points = run_points(cari_dir, args.binary, sep_input.SP_MYMODEL, args.date,
                               point_specs, os_name="unix", wine=None)
        direct = {key: value - bg_points.get(key, 0.0) for key, value in direct_total.items()}
        points = list(direct)
        node = _run_node(artifact, spectrum, points)
        report["offgrid_cases"].append(_metrics(name, direct, node))
    report["g5"] = {"ok": True,
                     "max_relative_error": max((case["max_relative_error"] for case in report["offgrid_cases"]), default=0),
                     "p95_relative_error": max((case["p95_relative_error"] for case in report["offgrid_cases"]), default=0),
                     "mean_relative_error": mean([case["mean_relative_error"] for case in report["offgrid_cases"]]) if report["offgrid_cases"] else 0}
    report["validation_max_grid_relative_error"] = report["g4"].get("max_relative_error", 0.0)
    report["validation_max_offgrid_relative_error"] = report["g5"].get("max_relative_error", 0.0)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cari-dir", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--cutoffs", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--date", default=DEFAULT_DATE)
    parser.add_argument("--validation-run-id", default=os.environ.get("GITHUB_RUN_ID", "unknown"))
    parser.add_argument("--offgrid-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_gate(args)
        with open(args.report, "w") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        print(json.dumps(report, sort_keys=True))
    except (OSError, RuntimeError, common.OperatorContractError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
