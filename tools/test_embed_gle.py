"""Tests del embebido de GLE_EVENTS en index.html."""
import unittest

from embed_gle import render_blocks, replace_blocks

HTML = ('<script>\nvar A = 1;\nvar GLE_EVENTS = [];\n'
        'var GLE_CAL = {k0: 0, beta: 0, attKm: 2.0, altRefKm: 10.668, r0Ref: 1.0};\n'
        'var B = 2;\n</script>\n')

EVENTS = [{"n": 73, "t0": "2021-10-28T15:45Z", "dt": 15, "q": "ajustado",
           "p": [[50.0, 2.0, 0.01]]}]


class TestRender(unittest.TestCase):
    def test_bloques_son_js_valido_de_una_linea(self):
        ev, cal = render_blocks(EVENTS, 1.5, 0.25)
        self.assertTrue(ev.startswith("var GLE_EVENTS = ["))
        self.assertTrue(ev.rstrip().endswith("];"))
        self.assertTrue(cal.startswith("var GLE_CAL = {"))
        self.assertIn('"n":73', ev.replace(" ", ""))

    def test_la_calibracion_viaja_en_el_bloque(self):
        _, cal = render_blocks(EVENTS, 1.5, 0.25)
        self.assertIn("1.5", cal)
        self.assertIn("0.25", cal)


class TestReplace(unittest.TestCase):
    def test_sustituye_ambos_bloques(self):
        ev, cal = render_blocks(EVENTS, 1.5, 0.25)
        out = replace_blocks(HTML, ev, cal)
        self.assertIn('"n":73', out.replace(" ", ""))
        self.assertIn("var A = 1;", out)
        self.assertIn("var B = 2;", out)
        self.assertNotIn("var GLE_EVENTS = [];", out)

    def test_sin_placeholder_falla_en_vez_de_escribir_mal(self):
        ev, cal = render_blocks(EVENTS, 1.5, 0.25)
        with self.assertRaises(SystemExit):
            replace_blocks("<script>var C = 3;</script>", ev, cal)


if __name__ == "__main__":
    unittest.main()
