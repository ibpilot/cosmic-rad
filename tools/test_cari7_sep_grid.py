"""Tests de la logica pura del kernel SEP_RESPONSE_GRID (T6).

La verificacion real (correr CARI-7A sobre las 53 columnas) corre en CI via el
workflow `generate-sep-grid.yml`; estos tests cubren la parte que se puede
ejecutar sin el binario: la matriz de pesos de cada bin sobre la malla del
BO11, la escritura de MY_MODEL.OUT (Z=1 arbitrario, Z>=2 literal), el
ensamblado del kernel (orden de indices, resta del fondo de iones, division
por la escala) y la generacion del bloque JS.

Ejecutar desde tools/:  python3 -m unittest test_cari7_sep_grid -v
"""
import math
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sep_grid_common as common
import generate_sep_grid as g


def bo11_grid_sintetico(n=100, e_lo=0.01, e_hi=10000.0):
    """Malla log-uniforme identica a la del BO11 Z=1 real (100 nodos)."""
    return [e_lo * (e_hi / e_lo) ** (i / (n - 1)) for i in range(n)]


class TestMatrizDePesos(unittest.TestCase):
    def setUp(self):
        self.grid = bo11_grid_sintetico()
        self.P = g.basis_weights(self.grid)

    def test_53_bins_por_n_nodos(self):
        self.assertEqual(len(self.P), common.N_E_BINS)
        for row in self.P:
            self.assertEqual(len(row), len(self.grid))

    def test_suma_1_por_bin(self):
        # Cada bin reparte exactamente 1 pfu entre los nodos (cuadratura
        # consistente): si no, el kernel no conservaria la integral.
        for row in self.P:
            self.assertAlmostEqual(sum(row), 1.0, places=9)

    def test_no_deja_huecos(self):
        # Todo el dominio [E_MIN, E_MAX] debe estar cubierto por alguna celda:
        # la particion de Voronoi del primer al ultimo nodo cubre la recta log.
        # La union de las celdas de TODOS los nodos es todo R, asi que cada bin
        # tiene peso total 1 (ya verificado); ademas, cada bin debe tocar al
        # menos 1 nodo con peso > 0 (si un bin entero cayera fuera del rango de
        # la malla, su base seria indetectable).
        for j, row in enumerate(self.P):
            nz = sum(1 for w in row if w > 1e-12)
            self.assertGreaterEqual(nz, 1, "bin %d sin nodo con peso" % j)

    def test_bins_sin_nodo_interno_siguen_cubiertos(self):
        # La malla BO11 tiene ~43 nodos en [0.05,20] frente a 53 bins: hay bins
        # que no contienen ningun nodo. Su peso debe repartirse entre los nodos
        # VECINOS (celdas de Voronoi que se solapan con el bin), no quedarse en 0.
        edges = common.bin_edges()
        for j in range(common.N_E_BINS):
            a, b = edges[j], edges[j + 1]
            inner = [e for e in self.grid if a <= e <= b]
            if not inner:
                # Este bin no contiene nodos: debe tener peso > 0 repartido.
                self.assertGreater(sum(self.P[j]), 0.999)


class TestZ1FluxForBin(unittest.TestCase):
    def setUp(self):
        self.grid = bo11_grid_sintetico()
        self.P = g.basis_weights(self.grid)

    def test_integral_es_amp(self):
        # La base de un bin con amp pfu debe tener integral ~amp sobre el
        # dominio. F(E) es un flujo diferencial (nuclei/(m2-sr-s-GeV)); la
        # integral de F dE sobre la celda de Voronoi de cada nodo es
        # F(E_n) * E_n * w_n (w_n = ancho de la celda en log E), y la
        # construccion F = amp*w/e hace que cada celda aporte amp*w -> la
        # integral del bin es amp * sum(w) = amp.
        for j in (0, 10, 26, 52):
            rows = g.z1_flux_for_bin(self.grid, self.P, j, amp=1e5)
            integral = sum(f * e * w for (e, f), w in zip(rows, self.P[j]))
            self.assertAlmostEqual(integral, 1e5, delta=1e5 * 1e-6)

    def test_solo_toca_pocos_nodos(self):
        # La base debe estar localizada (pocos nodos con flujo no-cero): si
        # tocara toda la malla, no seria una base del bin sino un espectro
        # ancho. Para bins en el interior del dominio, ~5-15 nodos.
        for j in (10, 20, 30, 40):
            rows = g.z1_flux_for_bin(self.grid, self.P, j, amp=1e5)
            nz = sum(1 for _e, f in rows if f > 0)
            self.assertGreaterEqual(nz, 1)
            self.assertLess(nz, 40)   # menos de la malla completa


class TestWriteMyModelZ1(unittest.TestCase):
    def _fake_bo11(self, path):
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            f.write("2002.041096\n   Z       E            F\n")
            for z in range(1, 29):
                for i in range(100):
                    e = 0.01 * (1e6) ** (i / 99.0)
                    f.write("%4d  %9.3E  %9.3E\n" % (z, e, float(z)))

    def test_z1_se_suma_al_gcr_y_z2_literal(self):
        d = tempfile.mkdtemp()
        bo11 = os.path.join(d, "GCR_MODELS", "BO11_GCR.OUT")
        self._fake_bo11(bo11)
        grid = g.read_bo11_z1_grid(bo11)
        z1 = [float(i) for i in range(len(grid))]   # valores arbitrarios
        dst = os.path.join(d, "GCR_MODELS", "MY_MODEL.OUT")
        g.write_my_model_z1(bo11, dst, z1)
        # Z=1 con el GCR del BO11 (en el fake, 1.0) MAS el valor SEP; Z>=2 con
        # los del BO11 (float(z)). Hallazgo T5: el SEP se SUMA al GCR de Z=1,
        # no lo reemplaza (reemplazar hacia que la dosis neta no escalara).
        n_z1 = n_ge2 = 0
        with open(dst) as f:
            for line in f:
                t = line.split()
                if len(t) < 3 or not t[0].isdigit():
                    continue
                z = int(t[0])
                if z == 1:
                    self.assertEqual(float(t[2]), 1.0 + float(n_z1))
                    n_z1 += 1
                else:
                    self.assertEqual(float(t[2]), float(z))
                    n_ge2 += 1
        self.assertEqual(n_z1, 100)
        self.assertEqual(n_ge2, 27 * 100)

    def test_fondo_z1_ceros_deja_gcr_puro(self):
        # El subcomando bg escribe z1_values = 0; write_my_model_z1 suma al GCR,
        # asi que Z=1 debe quedar con el flujo del BO11 (el fake: 1.0).
        d = tempfile.mkdtemp()
        bo11 = os.path.join(d, "GCR_MODELS", "BO11_GCR.OUT")
        self._fake_bo11(bo11)
        grid = g.read_bo11_z1_grid(bo11)
        dst = os.path.join(d, "GCR_MODELS", "MY_MODEL.OUT")
        g.write_my_model_z1(bo11, dst, [0.0] * len(grid))
        with open(dst) as f:
            for line in f:
                t = line.split()
                if len(t) >= 3 and t[0].isdigit() and int(t[0]) == 1:
                    self.assertEqual(float(t[2]), 1.0)

    def test_ancho_de_linea_26(self):
        # Bug destapado por CI en T4/T5: las filas deben tener 26 chars con las
        # columnas del BO11; un ancho distinto desplaza las columnas y CARI lee
        # mal el espectro.
        d = tempfile.mkdtemp()
        bo11 = os.path.join(d, "GCR_MODELS", "BO11_GCR.OUT")
        self._fake_bo11(bo11)
        grid = g.read_bo11_z1_grid(bo11)
        dst = os.path.join(d, "GCR_MODELS", "MY_MODEL.OUT")
        g.write_my_model_z1(bo11, dst, [1.0] * len(grid))
        with open(dst) as f:
            for line in f:
                t = line.split()
                if len(t) >= 3 and t[0].isdigit():
                    self.assertEqual(len(line.rstrip("\n")), 26,
                                     "linea con ancho != 26: %r" % line)


class TestEnsamblado(unittest.TestCase):
    def setUp(self):
        self.rc_axis = [0.0, 0.25, 0.5, 0.75, 1.0]      # eje corto de prueba
        self.alt_axis = [8.0, 8.5, 9.0]
        self.n_rc, self.n_alt = len(self.rc_axis), len(self.alt_axis)
        self.f = lambda rc, alt: (2.0 + rc) * (1.0 + 0.1 * alt)

    def _csv(self, path, make):
        with open(path, "w") as f:
            f.write("rc_gv,alt_km,rate_usvh\n")
            for rc in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2]:
                for alt in self.alt_axis:
                    f.write("%.6f,%.4f,%.9g\n" % (rc, alt, make(rc, alt)))

    def test_resta_fondo_y_divide_amp(self):
        import tempfile
        d = tempfile.mkdtemp()
        n_bins = 5
        paths = []
        for j in range(n_bins):
            p = os.path.join(d, "k%d.csv" % j)
            # total = fondo(1.0) + (j+1)*f
            self._csv(p, lambda rc, alt, jj=j: 1.0 + (jj + 1) * self.f(rc, alt))
            paths.append(p)
        bg = os.path.join(d, "bg.csv")
        self._csv(bg, lambda rc, alt: 1.0)
        col_csvs = [g.read_rates_csv(p) for p in paths]
        kernel, nulos = g.assemble_kernel(col_csvs, g.read_rates_csv(bg),
                                          amp=1.0, rc_axis=self.rc_axis,
                                          alt_axis=self.alt_axis, n_bins=n_bins)
        self.assertEqual(len(kernel), n_bins * self.n_rc * self.n_alt)
        self.assertEqual(nulos, 0)
        # celda (bin 2, rc 0.5, alt 8.5) = 3*f(0.5, 8.5)
        ri, ai = 2, 1
        got = kernel[2 * self.n_rc * self.n_alt + ri * self.n_alt + ai]
        exp = 3.0 * self.f(self.rc_axis[ri], self.alt_axis[ai])
        self.assertAlmostEqual(got, exp, places=6)

    def test_amp_divide(self):
        import tempfile
        d = tempfile.mkdtemp()
        n_bins = 3
        paths = []
        for j in range(n_bins):
            p = os.path.join(d, "k%d.csv" % j)
            self._csv(p, lambda rc, alt, jj=j: 1.0 + (jj + 1) * self.f(rc, alt))
            paths.append(p)
        bg = os.path.join(d, "bg.csv")
        self._csv(bg, lambda rc, alt: 1.0)
        col_csvs = [g.read_rates_csv(p) for p in paths]
        k1, _ = g.assemble_kernel(col_csvs, g.read_rates_csv(bg), amp=1.0,
                                  rc_axis=self.rc_axis, alt_axis=self.alt_axis,
                                  n_bins=n_bins)
        k100, _ = g.assemble_kernel(col_csvs, g.read_rates_csv(bg), amp=100.0,
                                    rc_axis=self.rc_axis, alt_axis=self.alt_axis,
                                    n_bins=n_bins)
        for a, b in zip(k1, k100):
            self.assertAlmostEqual(a / b, 100.0, places=6)


class TestBuildBlock(unittest.TestCase):
    def test_estructura_del_bloque(self):
        kernel = [1.0] * (common.N_E_BINS * 73 * 11)
        block = g.build_block(kernel, 0, 1.0)
        self.assertIn("var SEP_RESPONSE_GRID = {", block)
        self.assertIn('model_version: "sep-1"', block)
        self.assertIn('unit: "uSv/h per pfu"', block)
        self.assertIn('q: ["D2"]', block)
        self.assertTrue(block.rstrip().endswith("};"))
        # El base64 decodifica al mismo numero de floats.
        import base64, re, struct
        b64 = re.search(r'data: "([A-Za-z0-9+/=]+)"', block).group(1)
        raw = base64.b64decode(b64)
        self.assertEqual(len(raw), 4 * common.N_E_BINS * 73 * 11)

    def test_version_y_ejes_literales(self):
        self.assertEqual(common.MODEL_VERSION, "sep-1")
        self.assertEqual(len(common.RC_TARGETS), 73)
        self.assertEqual(len(common.ALT_VALUES), 11)
        self.assertEqual(len(common.bin_centers()), 53)


if __name__ == "__main__":
    unittest.main()
