"""Pure tests for the sep-2 nodal contract and strict assembler."""

import base64
import math
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generate_sep_operator as operator
import sep_operator_common as common


class TestNodalContract(unittest.TestCase):
    def test_one_hot_and_units(self):
        full = [0.01, 0.05, 0.1, 20.0, 30.0]
        active = common.active_bo11_nodes(full)
        self.assertEqual([node.index for node in active], [1, 2, 3])
        perturbation = common.one_hot_node_flux(full, active, 1, 2.5)
        self.assertEqual(perturbation, [0.0, 0.0, 25000.0, 0.0, 0.0])
        self.assertEqual(common.CM2_TO_M2, 1.0e4)

    def test_active_nodes_are_literal_and_strict(self):
        self.assertEqual(common.active_energies([0.05, 1.0, 20.0]), [0.05, 1.0, 20.0])
        with self.assertRaises(common.OperatorContractError):
            common.active_bo11_nodes([0.1, 0.1])
        with self.assertRaises(common.OperatorContractError):
            common.validate_active_node_list([0.1, 0.05])

    def test_probe_amplitudes_use_linear_voronoi_width(self):
        energies = [0.05, 1.0, 20.0]
        a0, probes = common.probe_amplitudes(energies, 1, safe_cari_flux=1e12)
        self.assertAlmostEqual(a0, 1000.0 / ((1.0 - 0.05) / 2 + (20.0 - 1.0) / 2))
        self.assertEqual(probes, tuple(f * a0 for f in common.AMPLITUDE_FACTORS))


class TestStrictAssembly(unittest.TestCase):
    energies = (0.1, 10.0)
    amplitudes = {
        0: common.probe_amplitudes((0.1, 10.0), 0, safe_cari_flux=1e12)[1],
        1: common.probe_amplitudes((0.1, 10.0), 1, safe_cari_flux=1e12)[1],
    }

    def _measurements(self, *, nonlinear_factor=None, unresolved=False):
        bg = []
        nodes = []
        for repeat in range(3):
            for rc in common.RC_TARGETS:
                for alt in common.ALT_VALUES:
                    bg.append(operator.Measurement(
                        "background", -1, 0.0, 0.0, repeat, rc, alt,
                        2.0 + repeat * 1e-7, 1e-6))
        for node, probes in self.amplitudes.items():
            for factor, amplitude in zip(common.AMPLITUDE_FACTORS, probes):
                for rc in common.RC_TARGETS:
                    for alt in common.ALT_VALUES:
                        coefficient = 2.0 + 0.01 * rc + 0.001 * alt
                        if unresolved:
                            coefficient = 1e-12
                        if nonlinear_factor is not None and factor == 3.0:
                            coefficient *= nonlinear_factor
                        nodes.append(operator.Measurement(
                            "node", node, factor, amplitude, 0, rc, alt,
                            2.0 + amplitude * coefficient, 1e-6))
        return nodes, bg

    def test_recovers_known_slope_and_error_tensor(self):
        nodes, bg = self._measurements()
        result = operator.assemble_strict(nodes, bg, self.energies,
                                           amplitudes_by_node=self.amplitudes)
        self.assertEqual(len(result.response), 2 * len(common.RC_TARGETS) * 11)
        self.assertEqual(len(result.error), len(result.response))
        self.assertGreater(result.response[0], 2.0)
        self.assertTrue(all(value >= 0 and math.isfinite(value) for value in result.error))
        self.assertLess(result.max_linearity_relative_error, 1e-5)

    def test_missing_amplitude_fails(self):
        nodes, bg = self._measurements()
        nodes = [row for row in nodes if not (row.node_index == 0 and row.amplitude_factor == 3.0)]
        with self.assertRaises(operator.AssemblyError):
            operator.assemble_strict(nodes, bg, self.energies,
                                     amplitudes_by_node=self.amplitudes)

    def test_partial_rc_slice_fails_without_extrapolation(self):
        nodes, bg = self._measurements()
        bg = [row for row in bg if not (row.rc_gv == 0 and row.input_repeat == 0)]
        with self.assertRaises(operator.AssemblyError):
            operator.assemble_strict(nodes, bg, self.energies,
                                     amplitudes_by_node=self.amplitudes)

    def test_invalid_inf_fails(self):
        nodes, bg = self._measurements()
        bad = nodes[0]
        nodes[0] = operator.Measurement(
            bad.kind, bad.node_index, bad.amplitude_factor, bad.amplitude,
            bad.input_repeat, bad.rc_gv, bad.altitude_km, float("inf"), bad.output_resolution_usvh)
        with self.assertRaises(operator.AssemblyError):
            operator.assemble_strict(nodes, bg, self.energies,
                                     amplitudes_by_node=self.amplitudes)

    def test_non_linearity_over_one_percent_fails(self):
        nodes, bg = self._measurements(nonlinear_factor=1.06)
        with self.assertRaises(operator.AssemblyError):
            operator.assemble_strict(nodes, bg, self.energies,
                                     amplitudes_by_node=self.amplitudes)

    def test_complete_unresolved_column_fails(self):
        nodes, bg = self._measurements(unresolved=True)
        with self.assertRaisesRegex(
                operator.AssemblyError,
                r"columna nodal \d+ completa bajo resolución"):
            operator.assemble_strict(nodes, bg, self.energies,
                                     amplitudes_by_node=self.amplitudes)

    def test_csv_parser_rejects_inf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bad.csv")
            with open(path, "w") as handle:
                handle.write(",".join(operator.CSV_FIELDS) + "\n")
                handle.write("node,0,1,1,0,0,8,inf,1e-6\n")
            with self.assertRaises(operator.AssemblyError):
                operator.read_measurements(path)

    def test_negative_slope_fails(self):
        # Regresión F10.2: quitar el `if slope < -error: raise` deja pasar una
        # columna cuyo neto es negativo y crece en magnitud con la amplitud.
        bg = []
        nodes = []
        # Fondo sin ruido (neto = rate - 2.0), resolución mínima para que no
        # haya suelo de ruido; el neto es negativo y crece en magnitud con la
        # amplitud (2 * amplitude por debajo del fondo, fuera del suelo).
        for repeat in range(3):
            for rc in common.RC_TARGETS:
                for alt in common.ALT_VALUES:
                    bg.append(operator.Measurement(
                        "background", -1, 0.0, 0.0, repeat, rc, alt, 2.0, 1e-30))
        for node, probes in self.amplitudes.items():
            for factor, amplitude in zip(common.AMPLITUDE_FACTORS, probes):
                for rc in common.RC_TARGETS:
                    for alt in common.ALT_VALUES:
                        # Por debajo del fondo y fuera del suelo de ruido: el
                        # neto es negativo y crece en magnitud con la amplitud.
                        rate = max(0.0, 2.0 - 2.0 * amplitude)
                        nodes.append(operator.Measurement(
                            "node", node, factor, amplitude, 0, rc, alt, rate, 1e-30))
        with self.assertRaisesRegex(operator.AssemblyError,
                                    r"pendiente nodal significativamente negativa"):
            operator.assemble_strict(nodes, bg, self.energies,
                                     amplitudes_by_node=self.amplitudes)

    def test_fewer_than_three_background_repeats_fails(self):
        # Regresión F10.3: sustituir el mínimo de repeticiones por `if False`
        # deja pasar un fondo con solo dos repeticiones.
        bg = []
        nodes = []
        for repeat in range(2):
            for rc in common.RC_TARGETS:
                for alt in common.ALT_VALUES:
                    bg.append(operator.Measurement(
                        "background", -1, 0.0, 0.0, repeat, rc, alt,
                        2.0 + repeat * 1e-7, 1e-6))
        for node, probes in self.amplitudes.items():
            for factor, amplitude in zip(common.AMPLITUDE_FACTORS, probes):
                for rc in common.RC_TARGETS:
                    for alt in common.ALT_VALUES:
                        coefficient = 2.0 + 0.01 * rc + 0.001 * alt
                        nodes.append(operator.Measurement(
                            "node", node, factor, amplitude, 0, rc, alt,
                            2.0 + amplitude * coefficient, 1e-6))
        with self.assertRaisesRegex(operator.AssemblyError,
                                    r"al menos 3 repeticiones de fondo"):
            operator.assemble_strict(nodes, bg, self.energies,
                                     amplitudes_by_node=self.amplitudes)

    def test_float32_ceiling_is_conservative(self):
        # Regresión F10.4a: si `_float32_ceiling` pasara por `_float32`, la cota
        # no subiría hasta el siguiente Float32 representable y podría quedar
        # por debajo del valor.
        self.assertEqual(operator._float32_ceiling(0.0), 0.0)
        self.assertGreaterEqual(operator._float32_ceiling(0.1), 0.1)
        found = [v for v in (0.1, 0.2, 0.3, 1.1, 2.1, 3.3)
                 if operator._float32(v) < v]
        self.assertTrue(found, "ningún valor de prueba redondea hacia abajo")
        for v in found:
            self.assertGreaterEqual(operator._float32_ceiling(v), v)

    def test_quantise_error_bounds_never_rounds_a_bound_down(self):
        # Regresión F10.4c: el uso de _float32_ceiling en assemble_strict está
        # extraido a _quantise_error_bounds. Para valores cuyo Float32 redondea
        # hacia abajo (el propio hueco de 0.5002 es uno), una cota que pasara
        # por _float32 quedaria por debajo del valor que debe cubrir.
        candidates = []
        value = 0.5002
        while len(candidates) < 3 and value < 0.6:
            gap = abs(value - operator._float32(value))
            if gap > 0 and operator._float32(gap) < gap:
                candidates.append(gap)
            value += 0.0001
        self.assertTrue(candidates)
        for candidate in candidates:
            quantised = operator._quantise_error_bounds([candidate])[0]
            self.assertGreaterEqual(quantised, candidate)

    def test_quantisation_error_alone_lands_in_error_tensor(self):
        # Regresión F10.4b: con resolución 1e-30 y fondo sin dispersión (tres
        # repeticiones idénticas), la única fuente de error de cada celda es la
        # cuantización Float32 del coeficiente ensamblado. El coeficiente 0.5002
        # no es representable en Float32; su hueco vale ~2.6e-8 y cada error del
        # tensor debe cubrirlo. La comparación es contra la pendiente CRUDA que
        # inyecta el test: contra la ya cuantizada siempre daria cero.
        coefficient = 0.5002
        raw_gap = abs(coefficient - operator._float32(coefficient))
        self.assertGreater(raw_gap, 1e-8)
        res = 1e-30
        bg = []
        nodes = []
        for repeat in range(3):
            for rc in common.RC_TARGETS:
                for alt in common.ALT_VALUES:
                    bg.append(operator.Measurement(
                        "background", -1, 0.0, 0.0, repeat, rc, alt, 2.0, res))
        for node, probes in self.amplitudes.items():
            for factor, amplitude in zip(common.AMPLITUDE_FACTORS, probes):
                for rc in common.RC_TARGETS:
                    for alt in common.ALT_VALUES:
                        nodes.append(operator.Measurement(
                            "node", node, factor, amplitude, 0, rc, alt,
                            2.0 + amplitude * coefficient, res))
        result = operator.assemble_strict(nodes, bg, self.energies,
                                           amplitudes_by_node=self.amplitudes)
        self.assertEqual(len(result.response), 2 * len(common.RC_TARGETS) * 11)
        self.assertEqual(len(result.error), len(result.response))
        self.assertTrue(all(error > 1e-9 for error in result.error),
                        "cada cota debe cubrir el hueco Float32 de la pendiente cruda")

    def test_weak_cells_inside_a_strong_column_are_resolved(self):
        # Regresión F1: celdas débiles (rc >= 17, respuesta nula) cuantizadas a
        # la resolución de salida con un fondo que fluctúa entre repeticiones
        # deben ensamblar sin excepción, quedando a 0 en response y con cota
        # positiva en error. Antes abortaban por el falso positivo de linealidad.
        res = 1e-6
        quantize = lambda value: round(value / res) * res
        rng = [0.0, 3e-7, 6e-7]  # fluctuación de fondo entre repeticiones
        bg = []
        nodes = []
        for repeat in range(3):
            for rc in common.RC_TARGETS:
                for alt in common.ALT_VALUES:
                    bg.append(operator.Measurement(
                        "background", -1, 0.0, 0.0, repeat, rc, alt,
                        quantize(2.0 + rng[repeat]), res))
        for node, probes in self.amplitudes.items():
            for factor, amplitude in zip(common.AMPLITUDE_FACTORS, probes):
                for rc in common.RC_TARGETS:
                    for alt in common.ALT_VALUES:
                        if rc >= 17:
                            total = quantize(2.0 + rng[0])
                        else:
                            coefficient = 2.0 + 0.01 * rc + 0.001 * alt
                            total = quantize(2.0 + amplitude * coefficient)
                        nodes.append(operator.Measurement(
                            "node", node, factor, amplitude, 0, rc, alt,
                            total, res))
        result = operator.assemble_strict(nodes, bg, self.energies,
                                           amplitudes_by_node=self.amplitudes)
        n_alt = len(common.ALT_VALUES)
        for index, rc in enumerate(common.RC_TARGETS):
            for alt_index in range(n_alt):
                offset = (alt_index + index * n_alt) % len(result.response)
                if rc >= 17:
                    self.assertEqual(result.response[offset], 0.0)
                    self.assertGreater(result.error[offset], 0.0)

    def test_weak_solvable_cell_hits_the_quantisation_margin(self):
        # Regresión F1 en el margen de cuantización: una celda débil PERO
        # resoluble (máximo neto por encima del suelo) cuya dispersión
        # normalizada la produce enteramente la cuantización de salida debe
        # pasar el margen allowance de _fit_cell y no abortar por linealidad.
        # Con allowance == 0.0 ese margen desaparece y assemble_strict lanza.
        res = 1e-6
        quantize = lambda value: round(value / res) * res
        bg = []
        nodes = []
        for repeat in range(3):
            for rc in common.RC_TARGETS:
                for alt in common.ALT_VALUES:
                    bg.append(operator.Measurement(
                        "background", -1, 0.0, 0.0, repeat, rc, alt,
                        quantize(2.0), res))
        for node, probes in self.amplitudes.items():
            for factor, amplitude in zip(common.AMPLITUDE_FACTORS, probes):
                for rc in common.RC_TARGETS:
                    for alt in common.ALT_VALUES:
                        # Coeficiente fuerte en la columna, salvo en las celdas
                        # rc >= 17, que llevan un neto cuantizado a 1e-6/2e-6/
                        # 6e-6 según la amplitud: el máximo supera el suelo
                        # (res) pero la dispersión normalizada sale entera de
                        # la cuantización.
                        coefficient = 2.0 + 0.01 * rc + 0.001 * alt
                        if rc >= 17:
                            coefficient = 1e-8
                        nodes.append(operator.Measurement(
                            "node", node, factor, amplitude, 0, rc, alt,
                            quantize(2.0 + amplitude * coefficient), res))
        result = operator.assemble_strict(nodes, bg, self.energies,
                                           amplitudes_by_node=self.amplitudes)
        n_alt = len(common.ALT_VALUES)
        for index, rc in enumerate(common.RC_TARGETS):
            for alt_index in range(n_alt):
                offset = (alt_index + index * n_alt) % len(result.response)
                if rc >= 17:
                    self.assertGreaterEqual(result.response[offset], 0.0)
                    self.assertGreater(result.error[offset], 0.0)

    def test_strict_grid_bounds_interpolation_error_in_rc(self):
        # Regresión F6: la celda interpolada en Rc debe aumentar
        # output_resolution_usvh en, al menos, el error real de la secante. Sin
        # _linear_interpolation_bound la celda rc=0.5 queda clavada en 1e-6 y
        # el test no distingue el caso curvo del lineal.
        altitude_axis = [8.0]
        rc_axis = [0.0, 0.5, 1.0]
        rate_curved = {0.0: 0.0, 0.25: 0.25 ** 2, 0.75: 0.75 ** 2, 1.0: 1.0}
        rate_linear = {0.0: 0.0, 0.25: 3.0 * 0.25, 0.75: 3.0 * 0.75, 1.0: 3.0}

        def measurements(rate_by_rc):
            rows = []
            for rc, rate in rate_by_rc.items():
                rows.append(operator.Measurement(
                    "background", -1, 0.0, 0.0, 0, rc, 8.0, rate, 1e-6))
            return rows

        grid = operator._strict_grid(measurements(rate_curved),
                                     rc_axis, altitude_axis)
        self.assertGreater(grid[(0.5, 8.0)].total_rate_usvh, 0.2)
        curved = grid[(0.5, 8.0)].output_resolution_usvh - 1e-6
        self.assertGreaterEqual(curved, (0.75 - 0.25) ** 2 / 8)

        grid = operator._strict_grid(measurements(rate_linear),
                                     rc_axis, altitude_axis)
        self.assertAlmostEqual(grid[(0.5, 8.0)].output_resolution_usvh, 1e-6)
        self.assertAlmostEqual(grid[(0.5, 8.0)].total_rate_usvh, 1.5)
        self.assertEqual(grid[(0.0, 8.0)].output_resolution_usvh, 1e-6)
        self.assertEqual(grid[(1.0, 8.0)].output_resolution_usvh, 1e-6)

    def test_write_my_model_z1_preserves_comment_lines(self):
        # Regresión F5: las líneas no numéricas del BO11 deben copiarse
        # literales al MY_MODEL.OUT, no descartarse.
        with tempfile.TemporaryDirectory() as directory:
            bo11 = os.path.join(directory, "BO11_GCR.OUT")
            out = os.path.join(directory, "MY_MODEL.OUT")
            with open(bo11, "w") as handle:
                handle.write("  version 4.2.0\n")
                handle.write("  species  proton\n")
                handle.write("1  0.05   1.000000E+02\n")
                handle.write("1  1.00   5.000000E+01\n")
                handle.write("2  3.00   9.900000E+01\n")
                handle.write("1  20.0   1.000000E+01\n")
                handle.write("# fila de comentario final\n")
            operator.write_my_model_z1(bo11, out, [0.0, 0.0, 0.0])
            with open(out) as handle:
                lines = handle.read().splitlines()
            self.assertEqual(lines[0], "  version 4.2.0")
            self.assertEqual(lines[1], "  species  proton")
            self.assertEqual(lines[-1], "# fila de comentario final")
            self.assertEqual(len(lines), 7)
            self.assertIn("   1  5.000E-02  1.000E+02", lines)

    def test_read_bo11_z1_nodes_rejects_short_z1_rows(self):
        # Regresión F7: una fila que empieza por 1 pero tiene menos de tres
        # campos es un error de generación, no una fila a saltar en silencio.
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "BO11_GCR.OUT")
            with open(path, "w") as handle:
                handle.write("  cabecera\n")
                handle.write("1  0.05   1.000000E+02\n")
                handle.write("1  0.1\n")
                handle.write("1  20.0   1.000000E+01\n")
            with self.assertRaisesRegex(common.OperatorContractError,
                                        r"fila Z=1 BO11 incompleta en línea 3"):
                common.read_bo11_z1_nodes(path)


class TestArtifactSerialization(unittest.TestCase):
    def test_float32_round_trip_is_strict(self):
        encoded, raw, unpacked = common.encode_float32([0.0, 1.25, 2.5])
        self.assertEqual(len(raw), 12)
        self.assertEqual(len(unpacked), 3)
        decoded, values = common.decode_float32(encoded, 3)
        self.assertEqual(decoded, raw)
        self.assertEqual(values, unpacked)


if __name__ == "__main__":
    unittest.main()
