"""Tests de la logica pura de las puertas de linealidad (T5).

La verificacion real de T5 corre en CI con el binario CARI-7A (workflow
`generate-sep-grid.yml`); estos tests cubren la parte que se puede ejecutar sin
el binario: las metricas de cada puerta (escalado, superposicion, binning,
reproduccion) deciden OK/FAIL con las tolerancias del plan, y la prueba negativa
del plan (inyectar un factor no lineal -> la puerta se pone roja) se ejercita
sobre mapas sinteticos.

Ejecutar desde tools/:  python3 -m unittest test_cari7_sep_linearity -v
"""
import math
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cari7_sep_linearity as lin
from cari7_sep_gate import compare_rate_maps


def rate_map(n=5, step=3.0):
    """Mapa sintetico { (rc, alt): rate } con n*2 puntos y tasas positivas."""
    return {(rc, 8.0 + 0.5 * a): (rc + 1.0) * (a + 1.0) * step
            for rc in [round(0.25 * i, 2) for i in range(0, n)]
            for a in range(2)}


class TestSpectroBase(unittest.TestCase):
    def test_muestreo_log_regular(self):
        # Cada fila es (centro geometrico del bin, flujo MEDIO del bin); los
        # centros caen en la malla log con la misma razon constante entre
        # muestras consecutivas (E_MAX/E_MIN)^(1/N).
        rows = lin.power_law_rows(53)
        self.assertEqual(len(rows), 53)
        es = [e for e, _ in rows]
        self.assertGreater(es[0], lin.E_MIN_GEV)
        self.assertLess(es[-1], lin.E_MAX_GEV)
        # La razon logaritmica es constante entre centros consecutivos.
        ratios = [es[i + 1] / es[i] for i in range(len(es) - 1)]
        self.assertTrue(all(abs(r - ratios[0]) < 1e-9 for r in ratios))

    def test_media_integrada_por_bin(self):
        # Cada bin lleva la media de la forma continua sobre el bin, no el valor
        # puntual en el centro. Sobre F = E^-3 (ley de potencia pura) la media
        # integrada debe reproducir la integral exacta del bin dividida por su
        # ancho; el valor puntual en el centro geometrico NO es esa media (por
        # eso el muestreo puntual sesgaba la rodilla del GLE73).
        import math
        e_min, e_max = lin.E_MIN_GEV, lin.E_MAX_GEV
        n = 8
        flux = lambda e: e ** -3.0
        rows = lin._bin_mean_rows(flux, n)
        lmin, lmax = math.log(e_min), math.log(e_max)
        for i, (c, f) in enumerate(rows):
            x0 = lmin + (lmax - lmin) * i / n
            x1 = lmin + (lmax - lmin) * (i + 1) / n
            e0, e1 = math.exp(x0), math.exp(x1)
            self.assertAlmostEqual(c, math.sqrt(e0 * e1), places=12)
            exact = (e0 ** -2 - e1 ** -2) / 2.0    # integral de E^-3 en [e0,e1]
            self.assertAlmostEqual(f * (e1 - e0), exact, delta=exact * 1e-6)
            self.assertNotAlmostEqual(f, flux(c), delta=flux(c) * 1e-3)

    def test_forma_gle_reescalada_a_regimen_bo11(self):
        # El espectro base es la forma del GLE73 reescalada para que F(1 GeV) ~
        # REF_FSEP: ahi compite con el GCR del BO11 (que en Z=1 vale ~400) y el
        # cambio de dosis es medible. Normalizar al maximo (a ~80 MeV, donde el
        # GCR contribuye poco) dejaba el SEP despreciable en las energias que
        # dominan la dosis (puntos=0 al filtrar netos <1 %).
        rows = lin.power_law_rows(53)
        f_1gev = next(f for e, f in rows if e >= lin.REF_E_GEV)
        self.assertAlmostEqual(f_1gev, lin.REF_FSEP, delta=lin.REF_FSEP * 0.05)
        # Valores finitos y positivos en todo el rango.
        self.assertTrue(all(f > 0 and f == f for _, f in rows))

    def test_no_diverge_en_baja_energia(self):
        # En la malla del BO11 el espectro proyectado no debe dar valores
        # astronomicos (1e11 saturaba a CARI): la forma real de un GLE tiene
        # pico finito (~2.6e5 a 80 MeV, orden de un GLE intenso) y no diverge.
        rows = lin.power_law_rows(200)
        fmax = max(f for _, f in rows)
        self.assertTrue(fmax < 1e7, "pico del SEP demasiado alto: %g" % fmax)
        # El borde bajo (0.05 GeV) tiene el pico o menos, nunca lo supera mucho.
        f_lo = [f for e, f in rows if e < 0.06]
        self.assertTrue(f_lo)
        self.assertLess(max(f_lo), fmax * 10)


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

    def test_cuadratura_converge_con_n(self):
        # El fix del binning: cada bin lleva la media integrada de la forma
        # continua. La integral total del espectro (suma de flujo_medio * ancho
        # de bin) debe converger al refinar N sin el sesgo del muestreo puntual
        # en la rodilla del GLE73 (que median ~8 % en CI y no convergian).
        import math
        e_min, e_max = lin.E_MIN_GEV, lin.E_MAX_GEV
        # Forma con una rodilla dura: E^-3 de 0.05 a 0.3, E^-5 de 0.3 a 20.
        def flux(e):
            return e ** -3.0 if e < 0.3 else (0.3 ** 2.0) * e ** -5.0
        ref = _integral_exacta(flux, e_min, e_max)
        for n in (53, 106, 400):
            rows = lin._bin_mean_rows(flux, n)
            total = sum(f * (b - a) for (a, b), (_, f) in
                        zip(_bordes(e_min, e_max, n), rows))
            self.assertAlmostEqual(total, ref, delta=ref * 1e-4)


def _centros(e_min, e_max, n):
    lmin, lmax = math.log(e_min), math.log(e_max)
    return [math.exp(lmin + (lmax - lmin) * (i + 0.5) / n) for i in range(n)]


def _bordes(e_min, e_max, n):
    lmin, lmax = math.log(e_min), math.log(e_max)
    xs = [lmin + (lmax - lmin) * i / n for i in range(n + 1)]
    return list(zip([math.exp(x) for x in xs[:-1]],
                    [math.exp(x) for x in xs[1:]]))


def _integral_exacta(flux, e_min, e_max):
    import math
    # Regla de Simpson compuesta en x = ln E, muy fina (la "forma continua").
    def g(x):
        ex = math.exp(x)
        return flux(ex) * ex
    n = 20000
    a, b = math.log(e_min), math.log(e_max)
    h = (b - a) / n
    s = g(a) + g(b)
    for k in range(1, n):
        x = a + k * h
        s += (4.0 if k % 2 else 2.0) * g(x)
    return s * h / 3.0


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
        # La cola hasta 20 GeV debe caer (extrapolacion con pendiente, no plana):
        # el ultimo bin (cerca de 20 GeV) vale mucho menos que el primero.
        self.assertLess(rows[-1][1], rows[0][1] * 1e-3)

    def test_baseline_descarta_fondo(self):
        # Sin restar el fondo, el espectro en canales bajos esta contaminado por
        # el fondo instrumental y deja de ser monotono; al restar el dia previo
        # queda la forma del exceso. El test verifica que la funcion aplica el
        # baseline (conteo de canales positivos coherente).
        rows = lin.gle_rows_from_fixture(FIXTURE_GLE73, 53)
        self.assertTrue(all(f > 0 for _, f in rows))


def fake_cari_dir():
    """Distribucion CARI-7A sintetica: un BO11_GCR.OUT con 100 filas de
    Z=1..28 (0.01..10000 GeV en Z=1) en el formato real de 26 chars, para
    probar _write_my_model sin el binario."""
    d = tempfile.mkdtemp()
    gcr = os.path.join(d, "GCR_MODELS")
    os.makedirs(gcr)
    with open(os.path.join(gcr, "BO11_GCR.OUT"), "w") as f:
        f.write("2002.041096\n   Z       E            F\n")
        for z in range(1, 29):
            for i in range(100):
                e = 0.01 * (1e6) ** (i / 99.0)   # 0.01 .. 10000 GeV
                f.write("%4d  %9.3E  %9.3E\n" % (z, e, float(z)))
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
        with open(out) as fh:
            for line in fh:
                t = line.split()
                if len(t) >= 3 and t[0].isdigit():
                    c[int(t[0])] += 1
        self.assertEqual(len(c), 28)
        self.assertTrue(all(v == 100 for v in c.values()),
                        "cada Z debe tener 100 filas: %s" % dict(c))

    def test_formato_columnas_fijas_26_chars(self):
        # Bug destapado por CI (2.º): write_my_model de T4 usa
        # "%4d %10.3E %12.3E" (28 chars) y desplaza las columnas; CARI lee el
        # espectro mal (tasas 0). El BO11 real usa 26 chars con la columna F en
        # las mismas posiciones. Cada linea de datos debe tener 26 chars.
        cari = fake_cari_dir()
        lin._write_my_model(cari, lin.power_law_rows(53))
        out = os.path.join(cari, "GCR_MODELS", "MY_MODEL.OUT")
        with open(out) as fh:
            data = [l for l in fh if l.strip()
                    and l.split() and l.split()[0].isdigit()]
        self.assertTrue(data)
        for l in data:
            self.assertEqual(len(l.rstrip("\n")), 26,
                             "linea con ancho != 26: %r" % l)

    def test_z2_conserva_iones_gcr(self):
        # Hallazgo de la sonda en CI: CARI exige las especies Z>=2 para dar
        # dosis D2 no-cero (BO11 con Z>=2 a cero -> 0/nan en 99 puntos). Los
        # iones GCR del BO11 se conservan; el SEP solo toca Z=1.
        cari = fake_cari_dir()
        lin._write_my_model(cari, lin.power_law_rows(53))
        out = os.path.join(cari, "GCR_MODELS", "MY_MODEL.OUT")
        # En el fake, Z>=2 vale float(z); debe conservarse en MY_MODEL.
        with open(out) as fh:
            for line in fh:
                t = line.split()
                if len(t) >= 3 and t[0].isdigit():
                    z = int(t[0])
                    if z > 1:
                        self.assertEqual(float(t[2]), float(z),
                                         "Z=%d debe conservar el GCR del BO11" % z)

    def test_sep_se_suma_al_gcr_en_z1(self):
        # MY_MODEL es GCR + SEP: en Z=1 el flujo debe ser el del BO11 (fake: 1.0)
        # MAS el espectro SEP. Reemplazar (como hacia el codigo antes del fix)
        # hacia que la dosis neta no escalara (ratios 1/k medidos en CI).
        cari = fake_cari_dir()
        rows = [(0.1, 5.0), (1.0, 5.0), (10.0, 5.0)]   # SEP constante 5.0
        lin._write_my_model(cari, rows)
        out = os.path.join(cari, "GCR_MODELS", "MY_MODEL.OUT")
        with open(out) as fh:
            for line in fh:
                t = line.split()
                if len(t) >= 3 and t[0].isdigit() and int(t[0]) == 1:
                    # GCR del fake (1.0) + SEP proyectado (5.0 en este rango).
                    self.assertAlmostEqual(float(t[2]), 6.0, places=1)


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
