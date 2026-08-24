"""Tests del parseo de la salida .ANS, en concreto de la columna VCR."""
import os
import tempfile
import unittest
from cari7_parse_ans import parse_ans

# Lineas reales de una salida de CARI-7A 4.2.0. Ojo al campo de altitud:
# "11.0000,K" mete una coma extra y desplaza los indices. VCR es t[6], no t[5].
ANS = """     LAT,       LON,     ALTITUDE,    DATE,    HR, VCR(GV), PARTICLE,  DOSE RATE,     SIGMA,        UNIT,      QUANTITY 
 -67.00000, 287.00000,    11.0000,K,2010/01/00,   0,  1.99,TOTAL     , 6.3485E+00, 4.1925E-01,    microSv/hr, ICRP Pub. 103 EFFECTIVE DOSE 
  32.00000, 268.00000,    11.0000,K,2010/01/00,   0,  4.01,TOTAL     , 4.8151E+00, 3.3770E-01,    microSv/hr, ICRP Pub. 103 EFFECTIVE DOSE 
  42.00000, 157.00000,     9.0000,K,2010/01/00,   0,  8.01,TOTAL     , 3.0537E+00, 2.1299E-01,    microSv/hr, ICRP Pub. 103 EFFECTIVE DOSE 
  34.00000, 145.00000,   36000.00,F,2010/01/00,   0, 11.99,TOTAL     , 2.1488E+00, 1.4407E-01,    microSv/hr, ICRP Pub. 103 EFFECTIVE DOSE 
  10.00000,  10.00000,    11.0000,K,2010/01/00,   0,  5.00,TOTAL     , 1.0000E+00, 1.0000E-01,    microSv/hr, ICRU H*(10) AMBIENT DOSE EQUIVALENT 
"""


class TestParseAns(unittest.TestCase):
    def setUp(self):
        fd, self.p = tempfile.mkstemp(suffix=".ans")
        with os.fdopen(fd, "w") as f:
            f.write(ANS)
        self.rows = parse_ans(self.p, 650)

    def tearDown(self):
        os.unlink(self.p)

    def test_devuelve_rigidez_no_latitud(self):
        # Si esto devuelve 67.0 en vez de 1.99, se esta leyendo la columna mala.
        self.assertAlmostEqual(self.rows[0][0], 1.99)
        self.assertAlmostEqual(self.rows[1][0], 4.01)

    def test_altitud_y_tasa(self):
        self.assertAlmostEqual(self.rows[0][1], 11.0)
        self.assertAlmostEqual(self.rows[0][3], 6.3485)
        self.assertAlmostEqual(self.rows[2][1], 9.0)

    def test_hp_se_propaga(self):
        self.assertTrue(all(r[2] == 650 for r in self.rows))

    def test_ignora_filas_en_pies(self):
        # La rejilla es en km; una fila con unidad F entraria con la altitud mal.
        self.assertEqual(len(self.rows), 3)

    def test_ignora_tallies_que_no_son_icrp103(self):
        self.assertTrue(all(abs(r[3] - 1.0) > 1e-9 for r in self.rows))


if __name__ == "__main__":
    unittest.main()
