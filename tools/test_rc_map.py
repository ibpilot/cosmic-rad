"""Tests del empaquetado de RC_MAP a Int16LE base64."""
import base64
import struct
import unittest
from cari7_cutoffs import parse_cutoff_text
from generate_dose_grid import build_rc_map

FIXTURE = """   VERTICAL COSMIC-RAY CUTOFF RIGIDITIES(20 KM)

   LAT  E LON
            0     1     2     3

    2    0.00  0.10  0.20  0.30
    1    1.00  1.10  1.20  1.30
    0    2.00  2.10  2.20 17.64
"""


class TestBuildRcMap(unittest.TestCase):
    def setUp(self):
        self.lats, self.lons, self.b64 = build_rc_map(parse_cutoff_text(FIXTURE))
        raw = base64.b64decode(self.b64)
        self.vals = struct.unpack("<%dh" % (len(raw) // 2), raw)

    def test_ejes_ordenados_ascendentes(self):
        self.assertEqual(self.lats, [0, 1, 2])
        self.assertEqual(self.lons, [0, 1, 2, 3])

    def test_orden_lat_major(self):
        # Primera fila = lat 0 (la menor), no lat 2.
        self.assertEqual(self.vals[0], 200)   # 2.00 GV / 0.01
        self.assertEqual(self.vals[3], 1764)  # 17.64 GV
        self.assertEqual(self.vals[4], 100)   # lat 1, lon 0 -> 1.00 GV

    def test_cuenta_de_valores(self):
        self.assertEqual(len(self.vals), 12)

    def test_el_maximo_global_cabe_en_int16(self):
        # 17.64 GV / 0.01 = 1764, muy por debajo de 32767.
        self.assertTrue(all(-32768 <= v <= 32767 for v in self.vals))

    def test_rejilla_incompleta_se_rechaza(self):
        rc = parse_cutoff_text(FIXTURE)
        del rc[(1, 2)]
        with self.assertRaises(SystemExit):
            build_rc_map(rc)


if __name__ == "__main__":
    unittest.main()
