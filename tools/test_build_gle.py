"""Tests del orquestador del pipeline de GLE."""
import math
import unittest

from build_gle import build_event
from gle_list import GLE_LIST
from gle_nmdb import STATIONS


def _series(i0, r0, n_steps=4, step_min=15, quiet_min=120):
    """Series sinteticas por estacion: 2 h planas y luego el evento."""
    out = {}
    for st, rc in STATIONS.items():
        rows = []
        for m in range(quiet_min):
            rows.append(("2021-10-28 %02d:%02d:00" % (13 + m // 60, m % 60), 100.0))
        pct = i0 * math.exp(-rc / r0)
        for k in range(n_steps * step_min):
            m = quiet_min + k
            rows.append(("2021-10-28 %02d:%02d:00" % (13 + m // 60, m % 60),
                         100.0 * (1.0 + pct / 100.0)))
        out[st] = rows
    return out


class TestBuildEvent(unittest.TestCase):
    def setUp(self):
        self.ev = build_event(73, "2021-10-28T15:00Z", _series(50.0, 2.0))

    def test_esquema_del_evento(self):
        self.assertEqual(set(self.ev), {"n", "t0", "dt", "q", "p"})
        self.assertEqual(self.ev["n"], 73)
        self.assertEqual(self.ev["dt"], 15)

    def test_recupera_los_parametros_en_cada_paso(self):
        for i0, r0, rms in self.ev["p"]:
            self.assertAlmostEqual(i0, 50.0, places=2)
            self.assertAlmostEqual(r0, 2.0, places=2)
            self.assertLess(rms, 1e-6)

    def test_evento_con_ajuste_se_etiqueta_ajustado(self):
        self.assertEqual(self.ev["q"], "ajustado")

    def test_pocas_estaciones_da_solo_evento_sin_dosis(self):
        ser = _series(50.0, 2.0)
        for st in list(ser)[3:]:
            del ser[st]
        ev = build_event(73, "2021-10-28T15:00Z", ser)
        self.assertEqual(ev["q"], "solo evento")
        self.assertEqual(ev["p"], [])

    def test_dia_tranquilo_no_produce_dosis(self):
        ser = {st: [("2021-10-28 %02d:%02d:00" % (13 + m // 60, m % 60), 100.0)
                    for m in range(240)] for st in STATIONS}
        ev = build_event(73, "2021-10-28T15:00Z", ser)
        self.assertEqual(ev["q"], "solo evento")

    def test_promedia_dentro_del_paso_no_coge_la_primera_muestra(self):
        # Paso de 15 min cuyo primer minuto vale la mitad: la media es P, la
        # primera muestra es 0.5P. Con datos de 1 min y un evento que sube
        # rapido, coger la primera muestra falsea I0.
        target, r0 = 50.0, 2.0
        ser = {}
        for st, rc in STATIONS.items():
            rows = [("2021-10-28 %02d:%02d:00" % (13 + m // 60, m % 60), 100.0)
                    for m in range(120)]
            p = target * math.exp(-rc / r0)
            for m in range(15):
                pct = 0.5 * p if m == 0 else p * (1.0 + 0.5 / 14.0)
                rows.append(("2021-10-28 %02d:%02d:00" % (15 + (m // 60), m % 60),
                             100.0 * (1.0 + pct / 100.0)))
            ser[st] = rows
        ev = build_event(73, "2021-10-28T15:00Z", ser)
        self.assertAlmostEqual(ev["p"][0][0], target, places=2)

    def test_el_perfil_se_corta_al_acabar_el_evento(self):
        # Evento de 1 h, 2 h de calma, y un segundo brote. El perfil debe medir
        # 4 pasos: la app deduce la duracion de len(p)*dt, y un hueco colado
        # desplazaria la dosis a la hora equivocada.
        i0, r0 = 50.0, 2.0
        ser = {}
        for st, rc in STATIONS.items():
            pct = i0 * math.exp(-rc / r0)
            rows = [("2021-10-28 %02d:%02d:00" % (13 + m // 60, m % 60), 100.0)
                    for m in range(120)]
            for m in range(300):
                activo = m < 60 or m >= 180
                v = 100.0 * (1.0 + pct / 100.0) if activo else 100.0
                rows.append(("2021-10-28 %02d:%02d:00" % (15 + (m // 60), m % 60), v))
            ser[st] = rows
        ev = build_event(73, "2021-10-28T15:00Z", ser)
        self.assertEqual(len(ev["p"]), 4)

    def test_valores_redondeados_para_caber_en_la_tabla(self):
        for row in self.ev["p"]:
            for v in row:
                self.assertEqual(v, round(v, 3))


class TestGleList(unittest.TestCase):
    def test_formato_de_la_lista(self):
        self.assertGreaterEqual(len(GLE_LIST), 4)
        for ev in GLE_LIST:
            self.assertIsInstance(ev["n"], int)
            self.assertRegex(ev["t0"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")

    def test_numeros_de_evento_unicos(self):
        ns = [e["n"] for e in GLE_LIST]
        self.assertEqual(len(ns), len(set(ns)))


if __name__ == "__main__":
    unittest.main()
