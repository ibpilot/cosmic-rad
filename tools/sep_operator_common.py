#!/usr/bin/env python3
"""Shared contract for the nodal ``SEP_RESPONSE_OPERATOR`` artefact.

The CARI distribution is the source of truth for the proton energy nodes.  The
helpers in this module deliberately do not recreate that mesh from a formula:
they read the literal BO11 rows and retain only the inclusive 0.05--20 GeV
domain used by both the offline generator and the runtime.
"""

from __future__ import annotations

import base64
import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence


SCHEMA_VERSION = 2
MODEL_VERSION = "sep-2"
ENGINE_NAME = "CARI-7A"
ENGINE_VERSION = "4.2.0"
SPECIES = "proton"
QUANTITY = "D2"
GEOMETRY = "isotropic-upper"
SHIELDING = "none"
INPUT_UNIT = "proton/(cm2-sr-s-GeV)"
OUTPUT_UNIT = "uSv/h"
ORDER = "energy-rc-altitude"
TAIL_FROM_GEV = 10.0

E_MIN_GEV = 0.05
E_MAX_GEV = 20.0
# Rc axis limited to 0--17.5 GV: the IGRF2010 cutoff maps distributed with
# CARI-7A top out at ~17.64 GV, so 17.75--18.0 are not physically reachable by
# the sweep.  Extending the axis would force flat extrapolation, which the
# sep-2 contract forbids.
RC_TARGETS = [round(0.25 * i, 2) for i in range(71)]
ALT_VALUES = [8.0 + 0.5 * i for i in range(11)]
EXPECTED_ACTIVE_NODE_COUNT = 43
EXPECTED_RC_COUNT = len(RC_TARGETS)

# CARI's MY_MODEL.OUT uses m² in the differential flux column.  The public
# runtime contract uses pfu/cm², so every offline perturbation crosses this
# boundary exactly once.
CM2_TO_M2 = 1.0e4

# The exact safe limit is intentionally configurable by the CI invocation.  It
# is a probe guard, never part of the runtime or of the nodal basis.
DEFAULT_SAFE_CARI_FLUX = 1.0e8
AMPLITUDE_FACTORS = (0.3, 1.0, 3.0)
BACKGROUND_REPEATS = 3
LINEARITY_TOLERANCE = 0.01
OUTPUT_RESOLUTION_USVH = 1.0e-6


class OperatorContractError(ValueError):
    """Raised when an input cannot satisfy the fail-closed operator contract."""


@dataclass(frozen=True)
class ActiveNode:
    """A literal BO11 Z=1 row and its position in the complete BO11 block."""

    index: int
    energy_gev: float


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def read_bo11_z1_nodes(path: str) -> list[float]:
    """Read the complete, ordered Z=1 energy mesh from ``BO11_GCR.OUT``.

    Every row is checked before the active subset is selected.  A malformed or
    duplicated CARI row is a generation error; silently skipping it would
    change the basis while leaving the artefact looking valid.
    """

    rows: list[float] = []
    with open(path, errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            fields = line.split()
            if not fields or fields[0] != "1":
                continue
            if len(fields) < 3:
                raise OperatorContractError(f"fila Z=1 BO11 incompleta en línea {line_no}")
            try:
                energy = float(fields[1])
            except ValueError as exc:
                raise OperatorContractError(
                    f"BO11 Z=1 energy inválida en línea {line_no}"
                ) from exc
            if not _finite(energy) or energy <= 0:
                raise OperatorContractError(
                    f"BO11 Z=1 energy no finita/positiva en línea {line_no}"
                )
            rows.append(energy)
    if len(rows) < 2:
        raise OperatorContractError("BO11 no contiene una malla Z=1 utilizable")
    if any(rows[i] >= rows[i + 1] for i in range(len(rows) - 1)):
        raise OperatorContractError("la malla BO11 Z=1 no es estrictamente creciente")
    return rows


def active_bo11_nodes(full_nodes: Sequence[float]) -> list[ActiveNode]:
    """Return the literal BO11 nodes in the inclusive SEP energy domain."""

    if not full_nodes:
        raise OperatorContractError("malla BO11 vacía")
    active = [
        ActiveNode(index=i, energy_gev=float(energy))
        for i, energy in enumerate(full_nodes)
        if E_MIN_GEV <= float(energy) <= E_MAX_GEV
    ]
    if not active:
        raise OperatorContractError("BO11 no tiene nodos dentro de 0.05--20 GeV")
    energies = [node.energy_gev for node in active]
    if any(not _finite(e) for e in energies):
        raise OperatorContractError("nodo BO11 no finito")
    if any(energies[i] >= energies[i + 1] for i in range(len(energies) - 1)):
        raise OperatorContractError("nodos activos BO11 no crecientes")
    return active


def active_energies(full_nodes: Sequence[float]) -> list[float]:
    return [node.energy_gev for node in active_bo11_nodes(full_nodes)]


def validate_active_node_list(
    energies: Sequence[float], *, expected_count: int | None = None
) -> None:
    """Validate a serialised literal node list without knowing the BO11 file."""

    if expected_count is not None and len(energies) != expected_count:
        raise OperatorContractError(
            f"se esperaban {expected_count} nodos activos, hay {len(energies)}"
        )
    if not energies:
        raise OperatorContractError("artefacto sin nodos energéticos")
    previous = None
    for energy in energies:
        if not _finite(energy) or not E_MIN_GEV <= float(energy) <= E_MAX_GEV:
            raise OperatorContractError("nodo energético fuera de dominio o no finito")
        if previous is not None and float(energy) <= previous:
            raise OperatorContractError("nodos energéticos duplicados/desordenados")
        previous = float(energy)


def one_hot_node_flux(
    full_nodes: Sequence[float],
    active: Sequence[ActiveNode],
    node_index: int,
    amplitude_cm2: float,
) -> list[float]:
    """Return a full BO11 Z=1 perturbation for one active node.

    ``amplitude_cm2`` is the public differential input unit.  The returned
    vector is in CARI's m² unit and has exactly one non-zero entry; all BO11
    rows outside the active domain therefore receive SEP zero.
    """

    if not _finite(amplitude_cm2) or float(amplitude_cm2) < 0:
        raise OperatorContractError("amplitud nodal negativa/no finita")
    if node_index < 0 or node_index >= len(active):
        raise OperatorContractError("índice nodal fuera de rango")
    target = active[node_index].index
    if target >= len(full_nodes):
        raise OperatorContractError("índice BO11 activo fuera de la malla")
    out = [0.0] * len(full_nodes)
    out[target] = float(amplitude_cm2) * CM2_TO_M2
    return out


def linear_voronoi_widths(
    energies: Sequence[float],
    e_min: float = E_MIN_GEV,
    e_max: float = E_MAX_GEV,
) -> list[float]:
    """Return linearly clipped Voronoi widths for the active node probes."""

    validate_active_node_list(energies)
    if not _finite(e_min) or not _finite(e_max) or e_min >= e_max:
        raise OperatorContractError("dominio Voronoi inválido")
    edges = [float(e_min)]
    for left, right in zip(energies, energies[1:]):
        edges.append((float(left) + float(right)) / 2.0)
    edges.append(float(e_max))
    widths = [hi - lo for lo, hi in zip(edges, edges[1:])]
    if any(width <= 0 or not math.isfinite(width) for width in widths):
        raise OperatorContractError("anchos Voronoi inválidos")
    return widths


def probe_amplitudes(
    energies: Sequence[float],
    node_index: int,
    *,
    safe_cari_flux: float = DEFAULT_SAFE_CARI_FLUX,
) -> tuple[float, tuple[float, float, float]]:
    """Compute ``A0`` and the required ``[0.3, 1, 3] × A0`` probes."""

    if not _finite(safe_cari_flux) or float(safe_cari_flux) <= 0:
        raise OperatorContractError("límite seguro CARI inválido")
    widths = linear_voronoi_widths(energies)
    if node_index < 0 or node_index >= len(widths):
        raise OperatorContractError("índice nodal fuera de rango")
    a_ref = 1000.0 / widths[node_index]
    a0 = min(a_ref, float(safe_cari_flux) / (3.0 * CM2_TO_M2))
    amplitudes = tuple(factor * a0 for factor in AMPLITUDE_FACTORS)
    return a0, amplitudes


def float32_bytes(values: Iterable[float]) -> bytes:
    """Pack finite, non-negative values as canonical little-endian Float32."""

    values = [float(value) for value in values]
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise OperatorContractError("tensor contiene NaN/infinito/negativo")
    try:
        raw = struct.pack("<%df" % len(values), *values)
    except (OverflowError, struct.error) as exc:
        raise OperatorContractError("tensor no representable como Float32") from exc
    round_trip = struct.unpack("<%df" % len(values), raw)
    if any(not math.isfinite(value) or value < 0 for value in round_trip):
        raise OperatorContractError("round-trip Float32 inválido")
    return raw


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode_float32(values: Iterable[float]) -> tuple[str, bytes, tuple[float, ...]]:
    raw = float32_bytes(values)
    unpacked = struct.unpack("<%df" % (len(raw) // 4), raw)
    return base64.b64encode(raw).decode("ascii"), raw, unpacked


def decode_float32(data: str, expected_length: int) -> tuple[bytes, tuple[float, ...]]:
    if not isinstance(data, str) or not data:
        raise OperatorContractError("tensor base64 vacío")
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, TypeError) as exc:
        raise OperatorContractError("tensor base64 inválido") from exc
    if len(raw) != expected_length * 4:
        raise OperatorContractError(
            f"tensor binario de {len(raw)} bytes; esperaba {expected_length * 4}"
        )
    values = struct.unpack("<%df" % expected_length, raw)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise OperatorContractError("tensor Float32 inválido")
    return raw, values


def expected_tensor_length(energies: Sequence[float], rc_axis=RC_TARGETS, alt_axis=ALT_VALUES) -> int:
    return len(energies) * len(rc_axis) * len(alt_axis)


def validate_axes(rc_axis: Sequence[float], alt_axis: Sequence[float]) -> None:
    if list(rc_axis) != RC_TARGETS:
        raise OperatorContractError("eje Rc no coincide con 0..17.5 cada 0.25 GV")
    if list(alt_axis) != ALT_VALUES:
        raise OperatorContractError("eje de altitud no coincide con 8..13 cada 0.5 km")
