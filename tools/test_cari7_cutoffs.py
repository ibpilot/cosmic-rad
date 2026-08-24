"""Tests del lector de mapas de rigidez de corte. Sin dependencias: unittest."""
import unittest
from cari7_cutoffs import epoch_file_for_year, parse_cutoff_text, points_for_rc_targets

# Fragmento con el formato real: cabecera, fila de longitudes, filas de latitud.
FIXTURE = """   VERTICAL COSMIC-RAY CUTOFF RIGIDITIES(20 KM)   DERIVED FROM INTERNAL MAGNETIC FIELD (IGRF 2010)

   LAT  E LON
            0     1     2     3

   89    0.00  0.10  0.20  0.30
   88    1.00  1.10  1.20  1.30
  -89    2.00  2.10  2.20  2.30
"""


class TestEpoch(unittest.TestCase):
    def test_elige_la_epoca_mas_cercana(self):
        self.assertEqual(epoch_file_for_year(2010), "IGRF2010.1X1")
        self.assertEqual(epoch_file_for_year(2007), "IGRF2010.1X1")
        self.assertEqual(epoch_file_for_year(1958), "WGRC1965.1X1")
        self.assertEqual(epoch_file_for_year(1992), "DGRF1990.1X1")

    def test_fecha_moderna_cae_en_el_mapa_mas_nuevo(self):
        # CARI-7A no trae nada posterior a 2010: 2026 debe caer ahi, no fallar.
        self.assertEqual(epoch_file_for_year(2026), "IGRF2010.1X1")


class TestParser(unittest.TestCase):
    def setUp(self):
        self.rc = parse_cutoff_text(FIXTURE)

    def test_lee_todas_las_celdas(self):
        self.assertEqual(len(self.rc), 12)

    def test_valores_correctos(self):
        self.assertAlmostEqual(self.rc[(89, 0)], 0.00)
        self.assertAlmostEqual(self.rc[(88, 2)], 1.20)
        self.assertAlmostEqual(self.rc[(-89, 3)], 2.30)

    def test_ignora_cabeceras_y_no_inventa_latitudes(self):
        self.assertEqual(sorted(set(k[0] for k in self.rc)), [-89, 88, 89])


class TestTargets(unittest.TestCase):
    def test_elige_el_punto_mas_cercano_a_cada_objetivo(self):
        rc = parse_cutoff_text(FIXTURE)
        got = points_for_rc_targets(rc, [1.10, 2.30], tol=0.05)
        self.assertEqual([(la, lo) for la, lo, _ in got], [(88, 1), (-89, 3)])

    def test_descarta_objetivos_fuera_de_tolerancia(self):
        rc = parse_cutoff_text(FIXTURE)
        self.assertEqual(points_for_rc_targets(rc, [9.99], tol=0.05), [])


if __name__ == "__main__":
    unittest.main()
