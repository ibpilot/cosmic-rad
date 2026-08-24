"""Tests del remuestreo de los pares (Rc, dosis) sobre el eje uniforme."""
import unittest
from generate_dose_grid import resample_to_axis


class TestResample(unittest.TestCase):
    def setUp(self):
        # Curva sintetica decreciente, un solo alt y un solo HP.
        self.rc_axis = [0.0, 0.5, 1.0]
        self.alt_axis = [11.0]
        self.hp_axis = [650]

    def test_interpola_entre_muestras(self):
        rows = [(0.0, 11.0, 650, 10.0), (1.0, 11.0, 650, 6.0)]
        out = resample_to_axis(rows, self.rc_axis, self.alt_axis, self.hp_axis)
        self.assertEqual(len(out), 3)
        self.assertAlmostEqual(out[0], 10.0)
        self.assertAlmostEqual(out[1], 8.0)   # punto medio
        self.assertAlmostEqual(out[2], 6.0)

    def test_usa_la_muestra_exacta_si_existe(self):
        rows = [(0.0, 11.0, 650, 10.0), (0.5, 11.0, 650, 9.5), (1.0, 11.0, 650, 6.0)]
        out = resample_to_axis(rows, self.rc_axis, self.alt_axis, self.hp_axis)
        self.assertAlmostEqual(out[1], 9.5)

    def test_extrapola_plano_por_encima_de_la_ultima_muestra(self):
        # El eje llega a 18 GV pero el globo solo a 17.64: el resto se mantiene
        # en el ultimo valor, no se extrapola linealmente hacia dosis negativas.
        rows = [(0.0, 11.0, 650, 10.0), (0.5, 11.0, 650, 6.0)]
        out = resample_to_axis(rows, self.rc_axis, self.alt_axis, self.hp_axis)
        self.assertAlmostEqual(out[2], 6.0)

    def test_falla_si_una_rebanada_se_queda_sin_muestras(self):
        rows = [(0.0, 11.0, 650, 10.0)]
        with self.assertRaises(SystemExit):
            resample_to_axis(rows, self.rc_axis, self.alt_axis, [650, 700])


if __name__ == "__main__":
    unittest.main()
