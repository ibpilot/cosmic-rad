#!/usr/bin/env python3
"""Generate and strictly assemble the nodal ``SEP_RESPONSE_OPERATOR``.

The CARI binary is required only for ``node`` and ``background``.  ``assemble``
is deterministic and intentionally refuses incomplete or malformed CSV input;
it never converts a missing measurement into a zero column.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import os
import re
import struct
import sys
from dataclasses import dataclass
from statistics import stdev
from typing import Iterable, Mapping, Sequence

import sep_operator_common as common


class AssemblyError(common.OperatorContractError):
    """A strict assembly or measurement validation failure."""


@dataclass(frozen=True)
class Measurement:
    kind: str
    node_index: int
    amplitude_factor: float
    amplitude: float
    input_repeat: int
    rc_gv: float
    altitude_km: float
    total_rate_usvh: float
    output_resolution_usvh: float


@dataclass(frozen=True)
class AssemblyResult:
    energy_gev: tuple[float, ...]
    rc_gv: tuple[float, ...]
    altitude_km: tuple[float, ...]
    response: tuple[float, ...]
    error: tuple[float, ...]
    max_linearity_relative_error: float
    p95_linearity_relative_error: float
    mean_linearity_relative_error: float
    unresolved_cells: int
    zero_cells: int


CSV_FIELDS = (
    "kind",
    "node_index",
    "amplitude_factor",
    "amplitude",
    "input_repeat",
    "rc_gv",
    "altitude_km",
    "total_rate_usvh",
    "output_resolution_usvh",
)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _same_float(a: float, b: float, tolerance: float = 1.0e-9) -> bool:
    return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)


def _coord_key(rc: float, altitude: float) -> tuple[float, float]:
    return round(float(rc), 9), round(float(altitude), 9)


def _float32(value: float) -> float:
    try:
        return struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (OverflowError, struct.error) as exc:
        raise AssemblyError("valor no representable como Float32") from exc


def _float32_ceiling(value: float) -> float:
    """Round upward enough that the Float32 error bound remains conservative."""

    if value <= 0:
        return 0.0
    result = _float32(value)
    if result >= value:
        return result
    # Move to the next representable Float32 by incrementing its IEEE-754
    # payload; nextafter() on the Python double can take many steps before the
    # Float32 bucket changes.
    bits = struct.unpack("<I", struct.pack("<f", result))[0]
    if bits >= 0x7F7FFFFF:
        raise AssemblyError("cota de error fuera del rango Float32")
    return struct.unpack("<f", struct.pack("<I", bits + 1))[0]


def _quantise_error_bounds(error_raw: Sequence[float]) -> list[float]:
    """Cuantiza las cotas a Float32 sin que ninguna baje por debajo de su valor."""

    return [_float32_ceiling(value) for value in error_raw]


def _format_float(value: float) -> str:
    return format(float(value), ".17g")


def read_measurements(path: str, *, expected_kind: str | None = None) -> list[Measurement]:
    """Read a measurement CSV and reject every malformed/duplicate row."""

    rows: list[Measurement] = []
    seen: set[tuple[object, ...]] = set()
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise AssemblyError(f"{path}: CSV sin cabecera")
        missing = [field for field in CSV_FIELDS if field not in reader.fieldnames]
        if missing:
            raise AssemblyError(f"{path}: faltan columnas {missing}")
        for line_no, raw in enumerate(reader, 2):
            if not raw or all(value in (None, "") for value in raw.values()):
                raise AssemblyError(f"{path}:{line_no}: fila vacía")
            try:
                kind = str(raw["kind"]).strip()
                node_index = int(raw["node_index"])
                factor = float(raw["amplitude_factor"])
                amplitude = float(raw["amplitude"])
                repeat = int(raw["input_repeat"])
                rc = float(raw["rc_gv"])
                altitude = float(raw["altitude_km"])
                rate = float(raw["total_rate_usvh"])
                resolution = float(raw["output_resolution_usvh"])
            except (TypeError, ValueError, KeyError) as exc:
                raise AssemblyError(f"{path}:{line_no}: fila CSV inválida") from exc
            if expected_kind is not None and kind != expected_kind:
                raise AssemblyError(
                    f"{path}:{line_no}: kind={kind!r}; esperaba {expected_kind!r}"
                )
            if kind not in ("node", "background"):
                raise AssemblyError(f"{path}:{line_no}: kind desconocido {kind!r}")
            if kind == "background" and (node_index != -1 or factor != 0 or amplitude != 0):
                raise AssemblyError(f"{path}:{line_no}: metadatos de fondo inválidos")
            if kind == "node" and (node_index < 0 or factor <= 0 or amplitude <= 0):
                raise AssemblyError(f"{path}:{line_no}: metadatos de nodo inválidos")
            if repeat < 0:
                raise AssemblyError(f"{path}:{line_no}: repetición negativa")
            if not all(_finite(v) for v in (factor, amplitude, rc, altitude, rate, resolution)):
                raise AssemblyError(f"{path}:{line_no}: NaN/infinito en CSV")
            if rate < 0 or resolution <= 0:
                raise AssemblyError(f"{path}:{line_no}: tasa/resolución negativa")
            if rc < common.RC_TARGETS[0] or rc > common.RC_TARGETS[-1] or \
                    altitude < common.ALT_VALUES[0] or altitude > common.ALT_VALUES[-1]:
                raise AssemblyError(f"{path}:{line_no}: Rc/altitud fuera del dominio")
            key = (kind, node_index, round(factor, 12), repeat, *_coord_key(rc, altitude))
            if key in seen:
                raise AssemblyError(f"{path}:{line_no}: medición duplicada {key}")
            seen.add(key)
            rows.append(Measurement(kind, node_index, factor, amplitude, repeat,
                                    rc, altitude, rate, resolution))
    if not rows:
        raise AssemblyError(f"{path}: CSV sin mediciones")
    return rows


def read_measurement_files(paths: Iterable[str], *, expected_kind: str | None = None) -> list[Measurement]:
    paths = list(paths)
    if not paths:
        raise AssemblyError("no se encontraron CSV de medición")
    rows: list[Measurement] = []
    seen: set[tuple[object, ...]] = set()
    for path in paths:
        for row in read_measurements(path, expected_kind=expected_kind):
            key = (row.kind, row.node_index, round(row.amplitude_factor, 12),
                   row.input_repeat, *_coord_key(row.rc_gv, row.altitude_km))
            if key in seen:
                raise AssemblyError(f"medición duplicada entre CSV: {key}")
            seen.add(key)
            rows.append(row)
    return rows


def write_measurements(
    path: str,
    rates: Mapping[tuple[float, float], float],
    *,
    kind: str,
    node_index: int = -1,
    amplitude_factor: float = 0.0,
    amplitude: float = 0.0,
    input_repeat: int = 0,
    output_resolution_usvh: float = common.OUTPUT_RESOLUTION_USVH,
) -> None:
    if kind not in ("node", "background"):
        raise AssemblyError("kind CSV inválido")
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for (rc, altitude), rate in sorted(rates.items()):
            values = {
                "kind": kind,
                "node_index": node_index,
                "amplitude_factor": _format_float(amplitude_factor),
                "amplitude": _format_float(amplitude),
                "input_repeat": input_repeat,
                "rc_gv": _format_float(rc),
                "altitude_km": _format_float(altitude),
                "total_rate_usvh": _format_float(rate),
                "output_resolution_usvh": _format_float(output_resolution_usvh),
            }
            writer.writerow(values)


def read_bo11_z1_grid(path: str) -> list[float]:
    """Compatibility spelling for callers that need the complete BO11 mesh."""

    return common.read_bo11_z1_nodes(path)


def write_my_model_z1(bo11_path: str, dst_path: str, z1_values_m2: Sequence[float]) -> str:
    """Copy BO11 literally, adding only the supplied Z=1 perturbation in m²."""

    full_nodes = common.read_bo11_z1_nodes(bo11_path)
    if len(z1_values_m2) != len(full_nodes):
        raise AssemblyError(
            f"perturbación Z=1 de {len(z1_values_m2)} filas; BO11 tiene {len(full_nodes)}"
        )
    if any(not _finite(value) or float(value) < 0 for value in z1_values_m2):
        raise AssemblyError("perturbación Z=1 inválida")
    with open(bo11_path, errors="replace") as source:
        source_lines = source.read().splitlines()
    if len(source_lines) < 2:
        raise AssemblyError("BO11 sin cabeceras")
    out = [source_lines[0], source_lines[1]]
    z1_index = 0
    for line in source_lines[2:]:
        fields = line.split()
        if len(fields) < 3 or not fields[0].isdigit():
            out.append(line.rstrip("\n"))
            continue
        if int(fields[0]) != 1:
            out.append(line.rstrip("\n"))
            continue
        try:
            energy = float(fields[1])
            gcr_flux = float(fields[2])
        except ValueError as exc:
            raise AssemblyError("fila Z=1 BO11 inválida") from exc
        value = gcr_flux + float(z1_values_m2[z1_index])
        # CARI reads fixed columns; retain the 26-character BO11 layout.
        rendered = "%4d  %9.3E  %9.3E" % (1, energy, value)
        if len(rendered) != 26:
            raise AssemblyError("fila MY_MODEL.OUT no conserva ancho fijo de 26")
        out.append(rendered)
        z1_index += 1
    if z1_index != len(full_nodes):
        raise AssemblyError("filas Z=1 del BO11 no coinciden con su malla")
    with open(dst_path, "w") as handle:
        handle.write("\n".join(out) + "\n")
    return dst_path


def _run_cari_grid(cari: str, binary: str, cutoffs: str, date: str,
                   *, tag: str, verbose: bool = False, probe: bool = False):
    """Run the existing CARI driver without duplicating its LOC/ANS parser."""

    import cari7_sep_input as sep
    from cari7_cutoffs import epoch_file_for_year, load_cutoff_map
    from cari7_sep_gate import run_spectrum

    epoch = epoch_file_for_year(int(date[:4]))
    rcmap = load_cutoff_map(os.path.join(cutoffs, epoch))
    if probe:
        targets = {round(0.25 * i, 2) for i in range(73) if i % 8 == 0}
        rcmap = {key: value for key, value in rcmap.items()
                 if any(abs(value - target) <= 0.25 for target in targets)}
    return run_spectrum(cari, binary, sep.SP_MYMODEL, date, os_name="unix",
                        wine=None, chunk=150, tag=tag, rcmap=rcmap,
                        cutoffs=cutoffs, verbose=verbose)


def _linear_interpolation_bound(points: Sequence[Measurement], hi: int) -> float:
    """Cota del error de interpolación lineal en el intervalo [hi-1, hi].

    Usa la segunda diferencia dividida de Newton sobre las ternas disponibles que
    contienen el intervalo: |f''| ~ 2*|f[x0,x1,x2]| y el error de la recta secante
    está acotado por |f''| h^2 / 8.  Con menos de tres puntos se cae al salto
    completo entre extremos, que es trivialmente conservador.
    """

    left, right = points[hi - 1], points[hi]
    h = right.rc_gv - left.rc_gv
    triples = []
    if hi - 2 >= 0:
        triples.append((points[hi - 2], left, right))
    if hi + 1 < len(points):
        triples.append((left, right, points[hi + 1]))
    if not triples:
        return abs(right.total_rate_usvh - left.total_rate_usvh)
    worst = 0.0
    for a, b, c in triples:
        first_ab = (b.total_rate_usvh - a.total_rate_usvh) / (b.rc_gv - a.rc_gv)
        first_bc = (c.total_rate_usvh - b.total_rate_usvh) / (c.rc_gv - b.rc_gv)
        second = abs(first_bc - first_ab) / (c.rc_gv - a.rc_gv)
        worst = max(worst, 2.0 * second * h * h / 8.0)
    if not math.isfinite(worst):
        raise AssemblyError("cota de interpolación Rc no finita")
    return worst


def _strict_grid(
    rows: Sequence[Measurement],
    rc_axis: Sequence[float],
    altitude_axis: Sequence[float],
) -> dict[tuple[float, float], Measurement]:
    """Interpolate a CARI sweep to exact axes, refusing extrapolation."""

    grouped: dict[float, list[Measurement]] = {}
    for row in rows:
        altitude = round(row.altitude_km, 9)
        grouped.setdefault(altitude, []).append(row)
    expected_altitudes = {round(float(value), 9) for value in altitude_axis}
    if set(grouped) != expected_altitudes:
        missing = sorted(expected_altitudes - set(grouped))
        extra = sorted(set(grouped) - expected_altitudes)
        raise AssemblyError(f"rebanadas de altitud incompletas; faltan={missing}, sobran={extra}")
    out: dict[tuple[float, float], Measurement] = {}
    for altitude in altitude_axis:
        points = sorted(grouped[round(float(altitude), 9)], key=lambda row: row.rc_gv)
        if len(points) < 2:
            raise AssemblyError(f"altitud {altitude} no cubre Rc con dos puntos")
        if any(points[i].rc_gv >= points[i + 1].rc_gv for i in range(len(points) - 1)):
            raise AssemblyError(f"Rc duplicada/desordenada en altitud {altitude}")
        if points[0].rc_gv > rc_axis[0] or points[-1].rc_gv < rc_axis[-1]:
            raise AssemblyError(f"rebanada alt={altitude} requeriría extrapolación Rc")
        for target in rc_axis:
            if target < points[0].rc_gv or target > points[-1].rc_gv:
                raise AssemblyError("punto Rc fuera de la cobertura medida")
            exact = next((point for point in points if _same_float(point.rc_gv, target)), None)
            if exact is not None:
                out[(round(float(target), 9), round(float(altitude), 9))] = exact
                continue
            hi = next(i for i in range(1, len(points)) if points[i].rc_gv >= target)
            left, right = points[hi - 1], points[hi]
            fraction = (target - left.rc_gv) / (right.rc_gv - left.rc_gv)
            rate = left.total_rate_usvh + fraction * (right.total_rate_usvh - left.total_rate_usvh)
            resolution = max(left.output_resolution_usvh, right.output_resolution_usvh) \
                + _linear_interpolation_bound(points, hi)
            out[(round(float(target), 9), round(float(altitude), 9))] = Measurement(
                left.kind, left.node_index, left.amplitude_factor, left.amplitude,
                left.input_repeat, float(target), float(altitude), rate, resolution,
            )
    return out


def _background_grid(rows: Sequence[Measurement], rc_axis, altitude_axis):
    by_repeat: dict[int, list[Measurement]] = {}
    for row in rows:
        by_repeat.setdefault(row.input_repeat, []).append(row)
    if len(by_repeat) < common.BACKGROUND_REPEATS:
        raise AssemblyError(
            f"se requieren al menos {common.BACKGROUND_REPEATS} repeticiones de fondo"
        )
    repeats = sorted(by_repeat)
    grids = [_strict_grid(by_repeat[repeat], rc_axis, altitude_axis) for repeat in repeats]
    keys = set(grids[0])
    if any(set(grid) != keys for grid in grids[1:]):
        raise AssemblyError("repeticiones de fondo no cubren la misma rejilla")
    result = {}
    for key in sorted(keys):
        values = [grid[key].total_rate_usvh for grid in grids]
        resolutions = [grid[key].output_resolution_usvh for grid in grids]
        result[key] = (sum(values) / len(values), stdev(values), max(resolutions))
    return result


def _fit_cell(
    amplitudes: Sequence[float],
    totals: Sequence[float],
    background_mean: float,
    background_sigma: float,
    output_resolution: float,
) -> tuple[float, float, float, bool]:
    nets = [total - background_mean for total in totals]
    max_amplitude = max(amplitudes)
    min_amplitude = min(amplitudes)
    noise_floor = max(5.0 * background_sigma, output_resolution)
    normal = sum(amplitude * net for amplitude, net in zip(amplitudes, nets))
    denominator = sum(amplitude * amplitude for amplitude in amplitudes)
    if denominator <= 0:
        raise AssemblyError("amplitudes degeneradas")
    slope = normal / denominator
    residual = math.sqrt(sum((net - slope * amplitude) ** 2 for amplitude, net in zip(amplitudes, nets))
                         / len(amplitudes)) / max_amplitude
    background_error = background_sigma / max_amplitude
    resolution_error = output_resolution / max_amplitude
    error = max(residual, background_error, resolution_error)
    if slope < -error:
        raise AssemblyError(f"pendiente nodal significativamente negativa: {slope}")
    if any(net < -noise_floor for net in nets):
        raise AssemblyError("neto total-fondo negativo fuera del suelo de ruido")
    unresolved = max(abs(net) for net in nets) <= noise_floor
    if unresolved:
        return 0.0, max(error, noise_floor / max_amplitude), 0.0, True
    normalized = [net / amplitude for net, amplitude in zip(nets, amplitudes)]
    normalized_spread = max(normalized) - min(normalized)
    # La cuantización de la salida de CARI produce por sí sola una dispersión
    # normalizada de hasta noise_floor/min_amplitude; no es no-linealidad.
    allowance = noise_floor / min_amplitude
    if normalized_spread > common.LINEARITY_TOLERANCE * max(abs(slope), error) + allowance:
        raise AssemblyError("variación normalizada entre amplitudes superior al 1 %")
    if slope < 0:
        # A negative residual within the measured error is not a physical
        # negative coefficient; preserving the error bound is the honest zero.
        slope = 0.0
    return slope, error, normalized_spread / max(abs(slope), error), False


def assemble_strict(
    node_rows: Sequence[Measurement],
    background_rows: Sequence[Measurement],
    energies: Sequence[float],
    *,
    amplitudes_by_node: Mapping[int, Sequence[float]],
    rc_axis: Sequence[float] = common.RC_TARGETS,
    altitude_axis: Sequence[float] = common.ALT_VALUES,
) -> AssemblyResult:
    """Fit all nodal columns and return response/error tensors in strict order."""

    common.validate_active_node_list(energies)
    common.validate_axes(rc_axis, altitude_axis)
    for row in list(node_rows) + list(background_rows):
        if not isinstance(row, Measurement):
            raise AssemblyError("fila de medición no tipada")
        if not all(_finite(value) for value in (
                row.amplitude_factor, row.amplitude, row.rc_gv, row.altitude_km,
                row.total_rate_usvh, row.output_resolution_usvh)):
            raise AssemblyError("fila de medición con NaN/infinito")
        if row.total_rate_usvh < 0 or row.output_resolution_usvh <= 0:
            raise AssemblyError("fila de medición con tasa/resolución inválida")
    n_energy, n_rc, n_alt = len(energies), len(rc_axis), len(altitude_axis)
    if len(amplitudes_by_node) != n_energy or set(amplitudes_by_node) != set(range(n_energy)):
        raise AssemblyError("falta un nodo o aparece un nodo duplicado en amplitudes")
    background = _background_grid(background_rows, rc_axis, altitude_axis)
    grouped: dict[int, dict[float, list[Measurement]]] = {}
    for row in node_rows:
        if row.node_index < 0 or row.node_index >= n_energy:
            raise AssemblyError(f"nodo fuera de rango: {row.node_index}")
        grouped.setdefault(row.node_index, {}).setdefault(round(row.amplitude_factor, 12), []).append(row)
    if set(grouped) != set(range(n_energy)):
        missing = sorted(set(range(n_energy)) - set(grouped))
        raise AssemblyError(f"faltan columnas nodales: {missing}")

    response_raw: list[float] = []
    error_raw: list[float] = []
    linearity_errors: list[float] = []
    unresolved_cells = 0
    zero_cells = 0
    for node_index in range(n_energy):
        expected_amplitudes = tuple(float(value) for value in amplitudes_by_node[node_index])
        if len(expected_amplitudes) != len(common.AMPLITUDE_FACTORS):
            raise AssemblyError(f"nodo {node_index}: faltan amplitudes requeridas")
        by_factor = grouped[node_index]
        expected_factors = {round(factor, 12) for factor in common.AMPLITUDE_FACTORS}
        if set(by_factor) != expected_factors:
            raise AssemblyError(f"nodo {node_index}: faltan amplitudes requeridas")
        grids = {}
        for factor in common.AMPLITUDE_FACTORS:
            rows = by_factor[round(factor, 12)]
            if len(rows) == 0:
                raise AssemblyError(f"nodo {node_index}: amplitud {factor} vacía")
            expected = expected_amplitudes[common.AMPLITUDE_FACTORS.index(factor)]
            if any(not _same_float(row.amplitude, expected, tolerance=1e-7) for row in rows):
                raise AssemblyError(f"nodo {node_index}: escala absoluta inesperada")
            grids[factor] = _strict_grid(rows, rc_axis, altitude_axis)
        node_unresolved = 0
        for rc in rc_axis:
            for altitude in altitude_axis:
                key = (round(float(rc), 9), round(float(altitude), 9))
                if key not in background:
                    raise AssemblyError(f"falta fondo en Rc={rc}, alt={altitude}")
                bg_mean, bg_sigma, bg_resolution = background[key]
                totals = [grids[factor][key].total_rate_usvh for factor in common.AMPLITUDE_FACTORS]
                resolutions = [grids[factor][key].output_resolution_usvh for factor in common.AMPLITUDE_FACTORS]
                slope, error, variation, unresolved = _fit_cell(
                    list(expected_amplitudes), totals, bg_mean, bg_sigma,
                    max(bg_resolution, max(resolutions)),
                )
                linearity_errors.append(variation)
                node_unresolved += int(unresolved)
                unresolved_cells += int(unresolved)
                response_raw.append(slope)
                error_raw.append(error)
                zero_cells += int(slope == 0)
        if node_unresolved == n_rc * n_alt:
            raise AssemblyError(f"columna nodal {node_index} completa bajo resolución")

    # Quantisation is part of the numerical error contract.  Compute it after
    # the response round-trip, then round the bound upward to Float32 too.
    response_f32 = [_float32(value) for value in response_raw]
    for index, (raw, quantized, error) in enumerate(zip(response_raw, response_f32, error_raw)):
        error_raw[index] = max(error, abs(raw - quantized))
    error_f32 = _quantise_error_bounds(error_raw)
    if any(value < 0 or not math.isfinite(value) for value in response_f32 + error_f32):
        raise AssemblyError("tensor o round-trip Float32 inválido")
    linearity_errors.sort()
    p95_index = min(len(linearity_errors) - 1, max(0, math.ceil(0.95 * len(linearity_errors)) - 1))
    return AssemblyResult(
        tuple(float(value) for value in energies), tuple(float(value) for value in rc_axis),
        tuple(float(value) for value in altitude_axis), tuple(response_f32), tuple(error_f32),
        max(linearity_errors, default=0.0), linearity_errors[p95_index] if linearity_errors else 0.0,
        sum(linearity_errors) / len(linearity_errors) if linearity_errors else 0.0,
        unresolved_cells, zero_cells,
    )


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(path: str) -> str:
    """Hash a CARI distribution deterministically by relative file/path bytes."""

    digest = hashlib.sha256()
    root = os.path.abspath(path)
    for current, directories, files in os.walk(root):
        directories.sort()
        files.sort()
        for name in files:
            full = os.path.join(current, name)
            relative = os.path.relpath(full, root).replace(os.sep, "/")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with open(full, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def build_operator_block(
    result: AssemblyResult,
    *,
    distribution_sha256: str,
    bo11_sha256: str,
    validation_run_id: str,
    validation_max_grid_relative_error: float = 0.0,
    validation_max_offgrid_relative_error: float = 0.0,
) -> str:
    """Serialise an assembled result as the marker-delimited JS artefact."""

    n = len(result.response)
    expected = common.expected_tensor_length(result.energy_gev)
    if len(result.error) != expected or n != expected:
        raise AssemblyError("dimensión de tensor incorrecta")
    if not re.fullmatch(r"[0-9a-f]{64}", distribution_sha256 or ""):
        raise AssemblyError("distribution_sha256 no es SHA-256 hexadecimal")
    if not re.fullmatch(r"[0-9a-f]{64}", bo11_sha256 or ""):
        raise AssemblyError("bo11_sha256 no es SHA-256 hexadecimal")
    if not validation_run_id:
        raise AssemblyError("falta validation_run_id")
    if not all(_finite(value) and value >= 0 for value in
               (validation_max_grid_relative_error, validation_max_offgrid_relative_error)):
        raise AssemblyError("métricas de validación inválidas")
    response_b64, response_bytes, _ = common.encode_float32(result.response)
    error_b64, error_bytes, _ = common.encode_float32(result.error)
    energy = ",".join(_format_float(value) for value in result.energy_gev)
    rc = ",".join(_format_float(value) for value in result.rc_gv)
    altitude = ",".join(_format_float(value) for value in result.altitude_km)
    lines = [
        "// BEGIN SEP_RESPONSE_OPERATOR",
        "// Generado por tools/generate_sep_operator.py; no editar a mano.",
        "var SEP_RESPONSE_OPERATOR = {",
        f"  schema_version: {common.SCHEMA_VERSION},",
        f"  model_version: {common.MODEL_VERSION!r},".replace("'", '"'),
        f"  engine_name: {common.ENGINE_NAME!r},".replace("'", '"'),
        f"  engine_version: {common.ENGINE_VERSION!r},".replace("'", '"'),
        f"  distribution_sha256: {distribution_sha256!r},".replace("'", '"'),
        f"  bo11_sha256: {bo11_sha256!r},".replace("'", '"'),
        f"  species: {common.SPECIES!r},".replace("'", '"'),
        f"  quantity: {common.QUANTITY!r},".replace("'", '"'),
        f"  geometry: {common.GEOMETRY!r},".replace("'", '"'),
        f"  shielding: {common.SHIELDING!r},".replace("'", '"'),
        f"  input_unit: {common.INPUT_UNIT!r},".replace("'", '"'),
        f"  output_unit: {common.OUTPUT_UNIT!r},".replace("'", '"'),
        f"  order: {common.ORDER!r},".replace("'", '"'),
        f"  tail_from_gev: {_format_float(common.TAIL_FROM_GEV)},",
        f"  energy_gev: [{energy}],",
        f"  rc_gv: [{rc}],",
        f"  altitude_km: [{altitude}],",
        f"  response_sha256: {common.sha256_bytes(response_bytes)!r},".replace("'", '"'),
        f"  error_sha256: {common.sha256_bytes(error_bytes)!r},".replace("'", '"'),
        f"  validation_run_id: {validation_run_id!r},".replace("'", '"'),
        f"  validation_max_grid_relative_error: {_format_float(validation_max_grid_relative_error)},",
        f"  validation_max_offgrid_relative_error: {_format_float(validation_max_offgrid_relative_error)},",
        f"  response_data: {response_b64!r},".replace("'", '"'),
        f"  error_data: {error_b64!r}",
        "};",
        "// END SEP_RESPONSE_OPERATOR",
        "",
    ]
    return "\n".join(lines)


def _write_node_or_background(args, *, kind: str) -> None:
    cari = os.path.abspath(args.cari_dir)
    bo11 = os.path.join(cari, "GCR_MODELS", "BO11_GCR.OUT")
    my_model = os.path.join(cari, "GCR_MODELS", "MY_MODEL.OUT")
    full_nodes = common.read_bo11_z1_nodes(bo11)
    active = common.active_bo11_nodes(full_nodes)
    energies = [node.energy_gev for node in active]
    if kind == "node":
        if args.node_index < 0 or args.node_index >= len(active):
            raise AssemblyError(f"--node-index fuera de 0..{len(active) - 1}")
        a0, amplitudes = common.probe_amplitudes(
            energies, args.node_index, safe_cari_flux=args.safe_cari_flux
        )
        factors = [args.amplitude_factor] if args.amplitude_factor is not None else list(common.AMPLITUDE_FACTORS)
        for factor in factors:
            if not any(_same_float(factor, expected) for expected in common.AMPLITUDE_FACTORS):
                raise AssemblyError("--amplitude-factor debe ser 0.3, 1 o 3")
            amplitude = amplitudes[common.AMPLITUDE_FACTORS.index(next(
                expected for expected in common.AMPLITUDE_FACTORS if _same_float(factor, expected)
            ))]
            perturbation = common.one_hot_node_flux(full_nodes, active, args.node_index, amplitude)
            write_my_model_z1(bo11, my_model, perturbation)
            rates = _run_cari_grid(cari, args.binary, os.path.abspath(args.cutoffs), args.date,
                                   tag=f"node{args.node_index}a{factor:g}", verbose=args.verbose,
                                   probe=args.probe)
            out = args.out
            if len(factors) > 1:
                stem, extension = os.path.splitext(args.out)
                out = f"{stem}_a{factor:g}{extension or '.csv'}"
            write_measurements(out, rates, kind="node", node_index=args.node_index,
                               amplitude_factor=factor, amplitude=amplitude,
                               output_resolution_usvh=args.output_resolution)
            print(f"[node] {args.node_index} amp={factor:g} A0={a0:.9g} -> {out}")
    else:
        perturbation = [0.0] * len(full_nodes)
        write_my_model_z1(bo11, my_model, perturbation)
        rates = _run_cari_grid(cari, args.binary, os.path.abspath(args.cutoffs), args.date,
                               tag=f"background{args.repeat}", verbose=args.verbose,
                               probe=args.probe)
        write_measurements(args.out, rates, kind="background", input_repeat=args.repeat,
                           output_resolution_usvh=args.output_resolution)
        print(f"[background] repeat={args.repeat} -> {args.out}")


def _parse_marker_object(text: str) -> dict:
    start = text.find("// BEGIN SEP_RESPONSE_OPERATOR")
    end = text.find("// END SEP_RESPONSE_OPERATOR", start + 1)
    if start < 0 or end < 0:
        raise AssemblyError("artefact sin marcadores SEP_RESPONSE_OPERATOR")
    block = text[start:end + len("// END SEP_RESPONSE_OPERATOR")]
    match = re.search(r"var SEP_RESPONSE_OPERATOR = \{(?P<body>.*)\};", block, re.S)
    if not match:
        raise AssemblyError("declaración SEP_RESPONSE_OPERATOR ausente")
    body = "{" + match.group("body").strip() + "}"
    body = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', body)
    import ast
    try:
        value = ast.literal_eval(body)
    except (ValueError, SyntaxError) as exc:
        raise AssemblyError("artefacto SEP_RESPONSE_OPERATOR no parseable") from exc
    if not isinstance(value, dict):
        raise AssemblyError("artefacto SEP_RESPONSE_OPERATOR no es objeto")
    return value


def annotate_block(path: str, report_path: str, output_path: str) -> None:
    """Copy G4/G5 metrics into an artefact only after the gates complete."""

    with open(report_path) as handle:
        report = json.load(handle)
    required = ("validation_run_id", "validation_max_grid_relative_error",
                "validation_max_offgrid_relative_error")
    if any(key not in report for key in required):
        raise AssemblyError("informe de validación sin métricas obligatorias")
    if (report.get("g4", {}).get("ok") is not True or
            report.get("g5", {}).get("ok") is not True or
            report.get("g7", {}).get("ok") is not True):
        raise AssemblyError("no se puede anotar un informe G4/G5/G7 fallido")
    text = open(path).read()
    obj = _parse_marker_object(text)
    if obj.get("model_version") != common.MODEL_VERSION:
        raise AssemblyError("versión de artefacto inesperada")
    replacements = {
        "validation_run_id": json.dumps(str(report["validation_run_id"])),
        "validation_max_grid_relative_error": _format_float(float(report[required[1]])),
        "validation_max_offgrid_relative_error": _format_float(float(report[required[2]])),
    }
    block_start = text.find("// BEGIN SEP_RESPONSE_OPERATOR")
    block_end = text.find("// END SEP_RESPONSE_OPERATOR", block_start)
    block_end += len("// END SEP_RESPONSE_OPERATOR")
    block = text[block_start:block_end]
    for key, replacement in replacements.items():
        block, count = re.subn(rf"(^\s*{re.escape(key)}:\s*)([^,\n]+)(,?)$",
                               rf"\g<1>{replacement}\g<3>", block, flags=re.M)
        if count != 1:
            raise AssemblyError(f"campo {key} no aparece exactamente una vez")
    with open(output_path, "w") as handle:
        handle.write(text[:block_start] + block + text[block_end:])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    common_cari = argparse.ArgumentParser(add_help=False)
    common_cari.add_argument("--cari-dir", required=True)
    common_cari.add_argument("--binary", required=True)
    common_cari.add_argument("--cutoffs", required=True)
    common_cari.add_argument("--date", default="2000/01/00")
    common_cari.add_argument("--out", required=True)
    common_cari.add_argument("--verbose", action="store_true")
    common_cari.add_argument("--probe", action="store_true")
    common_cari.add_argument("--output-resolution", type=float,
                             default=common.OUTPUT_RESOLUTION_USVH)

    node_parser = sub.add_parser("node", parents=[common_cari], help="medir un nodo BO11")
    node_parser.add_argument("--node-index", type=int, required=True)
    node_parser.add_argument("--amplitude-factor", type=float)
    node_parser.add_argument("--safe-cari-flux", type=float, default=common.DEFAULT_SAFE_CARI_FLUX)

    background_parser = sub.add_parser("background", parents=[common_cari], help="medir una repetición de fondo")
    background_parser.add_argument("--repeat", type=int, required=True)

    assemble_parser = sub.add_parser("assemble", help="ensamblar tensors desde CSV")
    assemble_parser.add_argument("--measurements", required=True, help="glob de CSV nodales")
    assemble_parser.add_argument("--background", required=True, help="glob de CSV de fondo")
    assemble_parser.add_argument("--bo11", required=True)
    assemble_parser.add_argument("--cari-dir", required=True)
    assemble_parser.add_argument("--out", required=True)
    assemble_parser.add_argument("--validation-run-id", default="pending-g4")
    assemble_parser.add_argument("--safe-cari-flux", type=float, default=common.DEFAULT_SAFE_CARI_FLUX)

    annotate_parser = sub.add_parser("annotate", help="anotar métricas G4/G5 en el artefacto")
    annotate_parser.add_argument("--artifact", required=True)
    annotate_parser.add_argument("--report", required=True)
    annotate_parser.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.mode == "node":
            _write_node_or_background(args, kind="node")
        elif args.mode == "background":
            if args.repeat < 0:
                raise AssemblyError("--repeat negativo")
            _write_node_or_background(args, kind="background")
        elif args.mode == "assemble":
            full_nodes = common.read_bo11_z1_nodes(args.bo11)
            active = common.active_bo11_nodes(full_nodes)
            energies = [node.energy_gev for node in active]
            measurements = read_measurement_files(sorted(glob.glob(args.measurements)), expected_kind="node")
            backgrounds = read_measurement_files(sorted(glob.glob(args.background)), expected_kind="background")
            amplitudes = {index: common.probe_amplitudes(energies, index,
                                                         safe_cari_flux=args.safe_cari_flux)[1]
                          for index in range(len(energies))}
            result = assemble_strict(measurements, backgrounds, energies,
                                     amplitudes_by_node=amplitudes)
            block = build_operator_block(
                result,
                distribution_sha256=sha256_directory(args.cari_dir),
                bo11_sha256=_sha256_file(args.bo11),
                validation_run_id=args.validation_run_id,
            )
            with open(args.out, "w") as handle:
                handle.write(block)
            print(json.dumps({
                "artifact": args.out,
                "energy_nodes": len(energies),
                "tensor_length": len(result.response),
                "max_linearity_relative_error": result.max_linearity_relative_error,
                "p95_linearity_relative_error": result.p95_linearity_relative_error,
                "mean_linearity_relative_error": result.mean_linearity_relative_error,
                "unresolved_cells": result.unresolved_cells,
                "zero_cells": result.zero_cells,
            }, sort_keys=True))
        else:
            annotate_block(args.artifact, args.report, args.out)
            print(f"artefact validado escrito en {args.out}")
    except (OSError, common.OperatorContractError, AssemblyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
