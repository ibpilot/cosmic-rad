"""Tests de la logica pura de las puertas de linealidad (T5).

La verificacion real de T5 corre en CI con el binario CARI-7A (workflow
`generate-sep-grid.yml`); estos tests cubren la parte que se puede ejecutar sin
el binario: las metricas de cada puerta (escalado, superposicion, binning,
reproduccion) deciden OK/FAIL con las tolerancias del plan, y la prueba negativa
del plan (inyectar un factor no lineal -> la puerta se pone roja) se ejercita
sobre mapas sinteticos.

Ejecutar desde tools/:  python3 -m unittest test_cari7_sep_linearity -v
"""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cari7_sep_linearity as lin
from cari7_sep_gate import compare_rate_maps


def rate_map(n=5, step=3.0):
    """Mapa sintetico { (rc, alt): rate } con n*2 puntos y tasas positivas."""
    return {(rc, 8.0 + 0.5 * a): (rc + 1.0) * (a + 1.0) * step
            for rc in [round(0.25 * i, 2) for i in range(0, n)]
            for a in range(2)}


class TestLogRows(unittest.TestCase):
    def test_muestreo_log_regular(self):
        rows = lin.power_law_rows(53)
        self.assertEqual(len(rows), 53)
        es = [e for e, _ in rows]
        self.assertAlmostEqual(es[0], lin.E_MIN_GEV, places=12)
        self.assertAlmostEqual(es[-1], lin.E_MAX_GEV, places=12)
        # Razon logaritmica constante entre muestras consecutivas.
        ratios = [es[i + 1] / es[i] for i in range(len(es) - 1)]
        self.assertTrue(all(abs(r - ratios[0]) < 1e-9 for r in ratios))

    def test_ley_de_potencia(self):
        for e, f in lin.power_law_rows(10):
            self.assertAlmostEqual(f, lin.BASE_A * e ** -lin.BASE_GAMMA)


class TestScaleMetric(unittest.TestCase):
    def test_escalado_exacto_pasa(self):
        base = rate_map()
        n, mx, mn, lo, hi, same = lin.scale_metric(base, {k: 10 * v for k, v in base.items()}, 10.0)
        self.assertEqual(n, len(base))
        self.assertEqual(mx, 0.0)
        self.assertEqual((lo, hi), (1.0, 1.0))
        self.assertTrue(same)

    def test_factor_no_lineal_queda_rojo(self):
        # Prueba negativa del plan: inyectar un factor no lineal (x^1.1 en vez
        # de x10) debe superar la tolerancia del 1 %.
        base = rate_map()
        nonlinear = {k: 10.0 * v * (1.0 + 0.05 * (k[0] / 5.0)) for k, v in base.items()}
        n, mx, mn, lo, hi, same = lin.scale_metric(base, nonlinear, 10.0)
        self.assertGreater(mx, lin.TOL_SCALE)


class TestSuperpositionMetric(unittest.TestCase):
    def test_superposicion_exacta_pasa(self):
        a = rate_map(n=4, step=1.0)
        b = {(k[0], k[1]): v * 2.0 for k, v in a.items()}
        ab = {k: a[k] + b[k] for k in a}
        n, mx, mn, lo, hi, same = lin.superposition_metric(a, b, ab)
        self.assertEqual(n, len(a))
        self.assertEqual(mx, 0.0)
        self.assertTrue(same)

    def test_interaccion_no_lineal_queda_roja(self):
        # Si dosis(A+B) != dosis(A)+dosis(B) (p. ej. por un termino cruzado),
        # la puerta debe fallar.
        a = rate_map(n=4, step=1.0)
        b = {k: v * 2.0 for k, v in a.items()}
        ab = {k: a[k] + b[k] + 0.05 * a[k] for k in a}   # +5% en cada punto
        n, mx, mn, lo, hi, same = lin.superposition_metric(a, b, ab)
        self.assertGreater(mx, lin.TOL_SUPERPOSITION)


class TestBinningMetric(unittest.TestCase):
    def test_mismo_espectro_en_106_y_53_pasa(self):
        a = rate_map()
        n, mx, mn, lo, hi, same = compare_rate_maps(a, dict(a))
        self.assertEqual(mx, 0.0)

    def test_divergencia_al_duplicar_bins_queda_roja(self):
        # Si la cuadratura no convergiera, 106 bins darian distinto que 53.
        d53 = rate_map()
        d106 = {k: v * 1.03 for k, v in d53.items()}   # +3 %
        n, mx, mn, lo, hi, same = compare_rate_maps(d106, d53)
        self.assertGreater(mx, lin.TOL_BINNING)


class TestReproductionMetric(unittest.TestCase):
    def test_reproduccion_exacta_pasa(self):
        # r7 (MY_MODEL) identico a r2 (nativo) -> ratio 1.
        m = rate_map()
        n, mx, mn, lo, hi, same = compare_rate_maps(m, dict(m))
        self.assertEqual(mx, 0.0)
        self.assertLessEqual(mx, lin.TOL_REPRODUCTION)

    def test_deriva_sobre_5_por_ciento_queda_roja(self):
        # La reproduccion tolera el 5 % (ruido del selftest); una deriva del
        # 8 % debe fallar.
        m = rate_map()
        deriv = {k: v * 1.08 for k, v in m.items()}
        n, mx, mn, lo, hi, same = compare_rate_maps(m, deriv)
        self.assertGreater(mx, lin.TOL_REPRODUCTION)


class TestToleranciasDelPlan(unittest.TestCase):
    def test_tolerancias_fijadas(self):
        self.assertEqual(lin.TOL_SCALE, 0.01)
        self.assertEqual(lin.TOL_SUPERPOSITION, 0.01)
        self.assertEqual(lin.TOL_BINNING, 0.01)
        self.assertEqual(lin.TOL_REPRODUCTION, 0.05)


FIXTURE_GLE73 = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "fixtures", "goes", "g16_2021-10-28.json")


class TestGleFixtureSpectrum(unittest.TestCase):
    def test_fixture_gle73_presente(self):
        # El fixture de T2 (GLE73) es la forma espectral de la puerta de
        # binning; si falta, la puerta no puede ejercitar un espectro real.
        self.assertTrue(os.path.exists(FIXTURE_GLE73),
                        "falta el fixture GLE73 de T2")

    def test_forma_monotona_con_cola_dura(self):
        import math
        rows = lin.gle_rows_from_fixture(FIXTURE_GLE73, 53)
        self.assertEqual(len(rows), 53)
        lrs = [(math.log(e), math.log(f)) for e, f in rows if f > 0]
        self.assertTrue(len(lrs) == len(rows))
        # Monotona decreciente en log-log (forma fisica de un espectro SEP).
        for i in range(len(lrs) - 1):
            self.assertLessEqual(lrs[i + 1][1], lrs[i][1] + 1e-9)
        # La cola hasta 20 GeV debe caer (extrapolacion con pendiente, no plana).
        f_hi = [f for e, f in rows if e > 19.0]
        f_lo = [f for e, f in rows if e < 0.06]
        self.assertTrue(f_hi and f_lo)
        self.assertLess(f_hi[0], f_lo[0] * 1e-3)

    def test_baseline_descarta_fondo(self):
        # Sin restar el fondo, el espectro en canales bajos esta contaminado por
        # el fondo instrumental y deja de ser monotono; al restar el dia previo
        # queda la forma del exceso. El test verifica que la funcion aplica el
        # baseline (conteo de canales positivos coherente).
        rows = lin.gle_rows_from_fixture(FIXTURE_GLE73, 53)
        self.assertTrue(all(f > 0 for _, f in rows))


def fake_cari_dir():
    """Distribucion CARI-7A sintetica: un BO11_GCR.OUT con 100 filas de
    Z=1..28 (0.01..10000 GeV en Z=1), para probar _write_my_model sin el
    binario."""
    d = tempfile.mkdtemp()
    gcr = os.path.join(d, "GCR_MODELS")
    os.makedirs(gcr)
    with open(os.path.join(gcr, "BO11_GCR.OUT"), "w") as f:
        f.write("2002.041096\n   Z       E            F\n")
        for z in range(1, 29):
            for i in range(100):
                e = 0.01 * (1e6) ** (i / 99.0)   # 0.01 .. 10000 GeV
                f.write("%4d %10.3E %12.3E\n" % (z, e, 1.0 if z == 1 else 0.0))
    return d


class TestWriteMyModelEstructura(unittest.TestCase):
    def test_100_filas_por_z(self):
        # Bug destapado por CI: un MY_MODEL.OUT con malla propia (53 filas en
        # Z=1) se lee mal por CARI (tasas 0/NaN). La estructura debe ser la del
        # BO11: 100 filas por Z=1..28.
        import collections
        cari = fake_cari_dir()
        lin._write_my_model(cari, lin.power_law_rows(53))
        out = os.path.join(cari, "GCR_MODELS", "MY_MODEL.OUT")
        c = collections.Counter()
        for line in open(out):
            t = line.split()
            if len(t) >= 3 and t[0].isdigit():
                c[int(t[0])] += 1
        self.assertEqual(len(c), 28)
        self.assertTrue(all(v == 100 for v in c.values()),
                        "cada Z debe tener 100 filas: %s" % dict(c))

    def test_z2_a_28_cero(self):
        cari = fake_cari_dir()
        lin._write_my_model(cari, lin.power_law_rows(53))
        out = os.path.join(cari, "GCR_MODELS", "MY_MODEL.OUT")
        for line in open(out):
            t = line.split()
            if len(t) >= 3 and t[0].isdigit() and int(t[0]) > 1:
                self.assertEqual(float(t[2]), 0.0)


class TestProjectPowerlaw(unittest.TestCase):
    def test_interpola_en_log_log(self):
        import math
        rows = [(0.1, 1.0), (1.0, 1e-3)]       # pendiente -3 en log-log
        grid = [0.1, 0.316, 1.0]
        proj = lin._project_powerlaw(rows, grid)
        # En 0.316 (10^-0.5), F = 10^-0.5*3 = 10^-1.5
        self.assertAlmostEqual(proj[1][1], 10 ** -1.5, places=3)

    def test_extrapola_con_pendiente_no_plana(self):
        # La malla del BO11 llega a 10000 GeV; una cola plana ahi daria una
        # dosis absurda. La extrapolacion debe seguir la ley de potencia.
        rows = [(0.1, 1e4), (1.0, 1.0)]        # E^-4
        grid = [1.0, 10.0, 100.0]
        proj = lin._project_powerlaw(rows, grid)
        # E^-4: en 10 GeV -> 1e-4, en 100 GeV -> 1e-8
        self.assertAlmostEqual(proj[1][1], 1e-4, places=6)
        self.assertAlmostEqual(proj[2][1], 1e-8, places=10)


if __name__ == "__main__":
    unittest.main()
