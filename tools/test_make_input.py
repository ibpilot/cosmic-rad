"""Tests de la seleccion de puntos por rigidez objetivo."""
import unittest
from cari7_make_input import RC_TARGETS, rc_sample_targets, HP_DATES
from cari7_cutoffs import epoch_file_for_year


class TestEjeRc(unittest.TestCase):
    def test_73_nodos_de_0_a_18(self):
        self.assertEqual(len(RC_TARGETS), 73)
        self.assertEqual(RC_TARGETS[0], 0.0)
        self.assertEqual(RC_TARGETS[-1], 18.0)

    def test_paso_uniforme(self):
        pasos = {round(RC_TARGETS[i + 1] - RC_TARGETS[i], 6) for i in range(len(RC_TARGETS) - 1)}
        self.assertEqual(pasos, {0.25})


class TestSobremuestreo(unittest.TestCase):
    def test_mas_denso_que_el_eje(self):
        t = rc_sample_targets(150)
        self.assertGreaterEqual(len(t), 150)

    def test_cubre_todo_el_rango_global(self):
        t = rc_sample_targets(150)
        self.assertLessEqual(min(t), 0.01)
        # El maximo global medido en IGRF2010 es 17.64 GV: hay que llegar.
        self.assertGreaterEqual(max(t), 17.6)

    def test_incluye_los_nodos_del_eje(self):
        t = set(round(x, 4) for x in rc_sample_targets(150))
        for nodo in RC_TARGETS:
            if nodo <= 17.6:
                self.assertIn(round(nodo, 4), t, "falta el nodo %.2f" % nodo)


class TestEpocaPorHp(unittest.TestCase):
    def test_cada_hp_usa_la_epoca_de_su_fecha(self):
        # La fecha de cada HP fija tambien el mapa de campo que usa CARI-7A.
        # Elegir los puntos con otro mapa los descolocaria.
        self.assertEqual(epoch_file_for_year(int(HP_DATES[1000][:4])), "WGRC1965.1X1")
        self.assertEqual(epoch_file_for_year(int(HP_DATES[300][:4])), "IGRF2010.1X1")
        self.assertEqual(epoch_file_for_year(int(HP_DATES[1200][:4])), "DGRF1990.1X1")


if __name__ == "__main__":
    unittest.main()
