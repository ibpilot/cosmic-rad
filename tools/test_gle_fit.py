"""Tests del baseline y del incremento porcentual."""
import unittest

from gle_fit import baseline, pct_increase


def _rows(vals, day="2021-10-28", start_min=0):
    out = []
    for i, v in enumerate(vals):
        m = start_min + i
        out.append(("%s %02d:%02d:00" % (day, m // 60, m % 60), float(v)))
    return out


class TestBaseline(unittest.TestCase):
    def test_mediana_de_las_dos_horas_previas(self):
        # 120 min planos a 100, luego el evento. t0 al minuto 120.
        rows = _rows([100.0] * 120 + [300.0] * 60)
        self.assertAlmostEqual(baseline(rows, "2021-10-28 02:00:00"), 100.0)

    def test_el_evento_no_contamina_el_baseline(self):
        rows = _rows([100.0] * 120 + [300.0] * 60)
        # Si se colase el evento, la mediana subiria muy por encima de 100.
        self.assertLess(baseline(rows, "2021-10-28 02:00:00"), 110.0)

    def test_un_pico_aislado_no_mueve_la_mediana(self):
        vals = [100.0] * 120
        vals[50] = 9999.0  # spike instrumental
        rows = _rows(vals + [300.0] * 60)
        self.assertAlmostEqual(baseline(rows, "2021-10-28 02:00:00"), 100.0)

    def test_sin_datos_previos_devuelve_none(self):
        rows = _rows([300.0] * 60, start_min=120)
        self.assertIsNone(baseline(rows, "2021-10-28 02:00:00"))


class TestPctIncrease(unittest.TestCase):
    def test_tramo_tranquilo_da_cero(self):
        # Test de la correccion barometrica: un dia muerto NO debe dar evento.
        rows = _rows([100.0] * 60)
        pcts = [p for _, p in pct_increase(rows, 100.0)]
        self.assertTrue(all(abs(p) < 0.5 for p in pcts))

    def test_doble_de_cuentas_es_cien_por_cien(self):
        rows = _rows([200.0] * 5)
        self.assertAlmostEqual(pct_increase(rows, 100.0)[0][1], 100.0)

    def test_normaliza_por_el_baseline_no_por_cien(self):
        # Con baseline 50, un valor de 75 es +50%, no +25. Todos los demas tests
        # usan baseline 100, donde diferencia absoluta y porcentaje coinciden y
        # la falta de normalizacion pasaria inadvertida.
        self.assertAlmostEqual(pct_increase(_rows([75.0]), 50.0)[0][1], 50.0)

    def test_baseline_cero_se_rechaza(self):
        with self.assertRaises(ValueError):
            pct_increase(_rows([100.0]), 0.0)


if __name__ == "__main__":
    unittest.main()
