"""Tests del parseo de NMDB y de la tabla de estaciones."""
import datetime
import os
import unittest

from gle_nmdb import STATIONS, nmdb_url, parse_nmdb_ascii

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "nmdb_oulu_20240511.txt")


class TestParseNmdb(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8", errors="replace") as fh:
            self.rows = parse_nmdb_ascii(fh.read())

    def test_extrae_filas_de_datos(self):
        self.assertGreater(len(self.rows), 20)

    def test_ignora_el_html_que_envuelve_los_datos(self):
        # La respuesta de NMDB es una pagina HTML con los datos dentro.
        for iso, val in self.rows:
            self.assertRegex(iso, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
            self.assertIsInstance(val, float)

    def test_valores_en_rango_plausible(self):
        vals = [v for _, v in self.rows]
        self.assertTrue(all(0 < v < 1e6 for v in vals))

    def test_linea_html_con_forma_de_dato_se_rechaza(self):
        # La respuesta trae CSS y HTML; una linea como "body; 12" tiene forma de
        # par pero no es un dato. Sin este test, una regex laxa pasa inadvertida.
        rows = parse_nmdb_ascii("body; 12\n2024-05-11 00:00:00; 88.4\n")
        self.assertEqual(rows, [("2024-05-11 00:00:00", 88.4)])

    def test_lineas_sin_valor_se_descartan(self):
        # NMDB emite "fecha;   null" en huecos de datos.
        rows = parse_nmdb_ascii("2024-05-11 00:00:00; 88.4\n2024-05-11 00:01:00;   null\n")
        self.assertEqual(rows, [("2024-05-11 00:00:00", 88.4)])


class TestStations(unittest.TestCase):
    def test_cubre_el_rango_de_rigideces(self):
        rcs = list(STATIONS.values())
        self.assertLess(min(rcs), 1.0)    # polar
        self.assertGreater(max(rcs), 10.0)  # ecuatorial

    def test_hay_estaciones_suficientes_para_ajustar(self):
        self.assertGreaterEqual(len(STATIONS), 12)


class TestUrl(unittest.TestCase):
    def test_url_lleva_estacion_fechas_y_ascii(self):
        u = nmdb_url("OULU", datetime.datetime(2024, 5, 11, 0, 0),
                     datetime.datetime(2024, 5, 12, 0, 0), 60)
        self.assertIn("stations[]=OULU", u)
        self.assertIn("start_year=2024", u)
        self.assertIn("output=ascii", u)
        self.assertIn("tresolution=60", u)


if __name__ == "__main__":
    unittest.main()
