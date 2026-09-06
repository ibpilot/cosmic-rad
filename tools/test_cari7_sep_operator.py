"""Pure tests for the sep-2 nodal contract and strict assembler."""

import base64
import math
import os
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
        self.assertEqual(len(result.response), 2 * 73 * 11)
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
        with self.assertRaises(operator.AssemblyError):
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
