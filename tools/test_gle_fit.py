"""Tests del baseline y del incremento porcentual."""
import math
import unittest

from gle_fit import MIN_STATIONS, baseline, fit_step, pct_increase


def _rows(vals, day="2021-10-28", start_min=0):
    out = []
    for i, v in enumerate(vals):
        m = start_min + i
        out.append(("%s %02d:%02d:00" % (day, m // 60, m % 60), float(v)))
    return out


def _synth(i0, r0, rcs):
    """Muestras sinteticas exactas del modelo I0*exp(-Rc/R0)."""
    return [(rc, i0 * math.exp(-rc / r0)) for rc in rcs]


RCS = [0.10, 0.30, 0.65, 0.81, 1.14, 3.84, 4.49, 6.27, 8.20, 8.53]


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


class TestFitStep(unittest.TestCase):
    def test_recupera_los_parametros_conocidos(self):
        i0, r0, rms = fit_step(_synth(50.0, 2.0, RCS))
        self.assertAlmostEqual(i0, 50.0, places=3)
        self.assertAlmostEqual(r0, 2.0, places=3)
        self.assertLess(rms, 1e-6)

    def test_recupera_un_evento_duro(self):
        i0, r0, rms = fit_step(_synth(12.0, 6.0, RCS))
        self.assertAlmostEqual(i0, 12.0, places=3)
        self.assertAlmostEqual(r0, 6.0, places=3)

    def test_el_ruido_sube_el_rms_pero_no_rompe_el_ajuste(self):
        s = _synth(50.0, 2.0, RCS)
        s[0] = (s[0][0], s[0][1] * 2.0)   # una estacion anomala (anisotropia)
        i0, r0, rms = fit_step(s)
        self.assertGreater(rms, 0.05)
        self.assertGreater(i0, 10.0)

    def test_pocas_estaciones_devuelve_none(self):
        pocas = _synth(50.0, 2.0, RCS[:3])
        self.assertIsNone(fit_step(pocas))

    def test_estaciones_por_debajo_del_umbral_no_cuentan(self):
        # 10 muestras, pero 8 son ruido de 0,1%: quedan 2 utiles -> None.
        s = _synth(50.0, 2.0, RCS[:2]) + [(rc, 0.1) for rc in RCS[2:]]
        self.assertIsNone(fit_step(s))

    def test_sin_sennal_devuelve_none(self):
        self.assertIsNone(fit_step([(rc, 0.0) for rc in RCS]))

    def test_incremento_que_crece_con_rc_no_es_un_gle(self):
        # Ruido, no evento: sin esta guarda el ajuste devuelve un R0 negativo y
        # se cuela en la tabla como si fuese un evento valido.
        subiendo = [(rc, 1.0 + rc) for rc in RCS]
        self.assertIsNone(fit_step(subiendo))

    def test_todas_las_estaciones_a_la_misma_rc(self):
        # Pendiente indefinida: sin la guarda de sxx esto es ZeroDivisionError.
        self.assertIsNone(fit_step([(2.0, 10.0)] * 10))

    def test_umbral_de_estaciones_es_ocho(self):
        self.assertEqual(MIN_STATIONS, 8)


if __name__ == "__main__":
    unittest.main()
