"""Tests de la calibracion y del hold-out."""
import unittest

from holdout_gle import (ALT_REF_KM, R0REF_GV, SEP_ATT_KM, event_dose,
                         fit_calibration, holdout)

EV = {"n": 73, "t0": "2021-10-28T15:45Z", "dt": 15, "q": "ajustado",
      "p": [[100.0, 2.0, 0.01]] * 4}   # 4 pasos de 15 min = 1 h a I0=100%


class TestEventDose(unittest.TestCase):
    def test_dosis_proporcional_a_k0(self):
        d1 = event_dose(EV, 0.0, ALT_REF_KM, 1.0, 0.0)
        d2 = event_dose(EV, 0.0, ALT_REF_KM, 2.0, 0.0)
        self.assertAlmostEqual(d2, 2 * d1)

    def test_una_hora_a_i0_100_con_k0_1_da_100_usv(self):
        # 4 pasos x 15 min = 1 h; K0=1 uSv/h por punto porcentual; I0=100.
        self.assertAlmostEqual(event_dose(EV, 0.0, ALT_REF_KM, 1.0, 0.0), 100.0)

    def test_rigidez_alta_atenua(self):
        polar = event_dose(EV, 0.0, ALT_REF_KM, 1.0, 0.0)
        ecuat = event_dose(EV, 15.0, ALT_REF_KM, 1.0, 0.0)
        self.assertLess(ecuat, polar / 100.0)

    def test_mas_altitud_mas_dosis(self):
        bajo = event_dose(EV, 0.0, 8.0, 1.0, 0.0)
        alto = event_dose(EV, 0.0, 12.0, 1.0, 0.0)
        self.assertGreater(alto, bajo)

    def test_altitud_de_referencia_no_escala(self):
        d = event_dose(EV, 0.0, ALT_REF_KM, 1.0, 0.0)
        self.assertAlmostEqual(d, 100.0)

    def test_evento_solo_evento_no_da_dosis(self):
        vacio = dict(EV, q="solo evento", p=[])
        self.assertEqual(event_dose(vacio, 0.0, ALT_REF_KM, 1.0, 0.0), 0.0)

    def test_evento_sin_campo_p_no_revienta(self):
        # Un evento embebido sin la clave "p" daria KeyError sin la guarda.
        self.assertEqual(event_dose({"n": 1, "t0": "x", "dt": 15}, 0.0,
                                    ALT_REF_KM, 1.0, 0.0), 0.0)

    def test_beta_endurece_segun_r0(self):
        blando = dict(EV, p=[[100.0, 1.0, 0.01]] * 4)
        duro = dict(EV, p=[[100.0, 4.0, 0.01]] * 4)
        # Con beta>0 un evento duro deposita mas por el mismo incremento.
        self.assertGreater(event_dose(duro, 0.0, ALT_REF_KM, 1.0, 1.0),
                           event_dose(blando, 0.0, ALT_REF_KM, 1.0, 1.0))

    def test_constantes_fijadas_por_el_plan(self):
        self.assertEqual(R0REF_GV, 1.0)
        self.assertEqual(ALT_REF_KM, 10.668)
        self.assertEqual(SEP_ATT_KM, 2.0)


class TestCalibration(unittest.TestCase):
    def test_recupera_k0_de_datos_sinteticos(self):
        events = [dict(EV, n=i) for i in range(1, 5)]
        pub = [{"n": i, "rc_gv": 0.0, "alt_km": ALT_REF_KM,
                "dose_usv": event_dose(EV, 0.0, ALT_REF_KM, 3.0, 0.0)}
               for i in range(1, 5)]
        k0, beta = fit_calibration(events, pub)
        self.assertAlmostEqual(k0, 3.0, places=2)

    def test_menos_de_cuatro_eventos_fuerza_beta_cero(self):
        events = [dict(EV, n=i) for i in range(1, 4)]
        pub = [{"n": i, "rc_gv": 0.0, "alt_km": ALT_REF_KM, "dose_usv": 100.0}
               for i in range(1, 4)]
        _, beta = fit_calibration(events, pub)
        self.assertEqual(beta, 0.0)

    def test_empate_en_beta_gana_el_modelo_simple(self):
        # Eventos identicos: la perdida es plana en beta y cualquier valor
        # encaja. Sin desempate salia beta = -1.0 y un K0 del doble.
        events = [dict(EV, n=i) for i in range(1, 5)]
        pub = [{"n": i, "rc_gv": 0.0, "alt_km": ALT_REF_KM,
                "dose_usv": event_dose(EV, 0.0, ALT_REF_KM, 3.0, 0.0)}
               for i in range(1, 5)]
        k0, beta = fit_calibration(events, pub)
        self.assertEqual(beta, 0.0)
        self.assertAlmostEqual(k0, 3.0, places=2)


class TestHoldout(unittest.TestCase):
    def test_holdout_perfecto_da_factor_uno(self):
        events = [dict(EV, n=i) for i in range(1, 6)]
        pub = [{"n": i, "rc_gv": 0.0, "alt_km": ALT_REF_KM,
                "dose_usv": event_dose(EV, 0.0, ALT_REF_KM, 3.0, 0.0)}
               for i in range(1, 6)]
        for row in holdout(events, pub):
            self.assertAlmostEqual(row["factor"], 1.0, places=2)


    def test_el_factor_es_simetrico_y_caza_la_subestimacion(self):
        # Sin simetrizar, subestimar da factor < 1 y el criterio de aceptacion
        # nunca salta: la puerta de calidad se abriria sola en media de los casos.
        from holdout_gle import MAX_FACTOR
        self.assertEqual(MAX_FACTOR, 3.0)
        events = [dict(EV, n=i) for i in range(1, 6)]
        real = event_dose(EV, 0.0, ALT_REF_KM, 3.0, 0.0)
        pub = [{"n": i, "rc_gv": 0.0, "alt_km": ALT_REF_KM, "dose_usv": real}
               for i in range(1, 5)]
        # El quinto evento vale 5 veces mas de lo que predice el ajuste del resto.
        pub.append({"n": 5, "rc_gv": 0.0, "alt_km": ALT_REF_KM, "dose_usv": real * 5})
        peor = max(row["factor"] for row in holdout(events, pub))
        self.assertGreater(peor, MAX_FACTOR)


if __name__ == "__main__":
    unittest.main()
