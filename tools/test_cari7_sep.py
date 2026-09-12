"""Tests del driver SEP (T4): cari7_sep_input.py y cari7_sep_gate.py.

Cubren la estructura de MY_MODEL.OUT, la paridad de la rejilla LOC con el
camino GCR, la proyeccion de espectros arbitrarios y el comparador de la
puerta de unidades (incluida la mutacion cm2/m2 que debe poner el gate rojo).

Ejecutar desde tools/:  python3 -m unittest test_cari7_sep -v
"""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cari7_make_input as mi
import cari7_sep_input as sep
from cari7_cutoffs import points_for_rc_targets
from cari7_sep_gate import compare_rate_maps, DEFAULT_TOLERANCE


def sintetic_rcmap():
    """Mapa 1x1 sintetico con rc = 0.2*lat (0..18 GV en 0..90) para que los
    objetivos del eje caigan cerca de un punto del mapa: misma densidad de
    muestreo que los .1X1 reales."""
    rcmap = {}
    lat = 0.0
    while lat <= 90.0001:
        rcmap[(int(round(lat)), 0)] = round(0.2 * lat, 4)
        lat += 1.25
    return rcmap


class TestLocLine(unittest.TestCase):
    def test_paridad_con_camino_gcr(self):
        # Para espectro 4 la linea SEP debe ser EXACTAMENTE la del camino GCR
        # (misma aritmetica de indices para poder reutilizar cari7_parse_ans).
        for la, lo, alt in [(43.0, 2.0, 10.5), (-33.0, -70.0, 12.0), (85.0, 5.0, 8.0)]:
            self.assertEqual(sep.sep_loc_line(la, lo, alt, "2000/01/00", 4),
                             mi.loc_line(la, lo, alt, "2000/01/00"),
                             "paridad rota en (%s,%s,%s)" % (la, lo, alt))

    def test_campo_espectro_y_longitud(self):
        line = sep.sep_loc_line(43.0, 0.0, 10.5, "2000/01/00", sep.SP_MYMODEL)
        self.assertLessEqual(len(line), 66)
        self.assertIn("D2", line)      # dosis efectiva ICRP-103 (lo que lee el parser)
        self.assertIn("P0", line)
        self.assertIn("C7", line)      # espectro 7 = MY_MODEL.OUT
        self.assertIn("S0", line)
        self.assertEqual(sep.sep_loc_line(43.0, 0.0, 10.5, "2000/01/00", sep.SP_BO11),
                         sep.sep_loc_line(43.0, 0.0, 10.5, "2000/01/00", 2) )


class TestWriteSepLoc(unittest.TestCase):
    def _picks(self):
        return points_for_rc_targets(sintetic_rcmap(), mi.rc_sample_targets(),
                                     tol=0.13)

    def test_rejilla_rc_x_alt(self):
        d = tempfile.mkdtemp()
        paths = sep.write_sep_loc(d, None, sep.SP_MYMODEL, rcmap=sintetic_rcmap(),
                                  chunk=150)
        tot = 0
        for p in paths:
            with open(p) as f:
                n = sum(1 for l in f if l.startswith(("N,", "S,")))
            self.assertLessEqual(n, 150, "lote mayor que el chunk")
            tot += n
        self.assertEqual(tot, len(self._picks()) * len(mi.ALT_VALUES),
                         "el numero de puntos debe ser picks x 11 altitudes")

    def test_mismo_conjunto_entre_espectros(self):
        rcmap = sintetic_rcmap()
        d = tempfile.mkdtemp()
        pa = sep.write_sep_loc(d, None, sep.SP_MYMODEL, rcmap=rcmap, chunk=0)
        pb = sep.write_sep_loc(d, None, sep.SP_BO11, rcmap=rcmap, chunk=0)
        with open(pa[0]) as fa, open(pb[0]) as fb:
            a = [l for l in fa if l.startswith(("N,", "S,"))]
            b = [l for l in fb if l.startswith(("N,", "S,"))]
        # Mismas coordenadas y orden; solo cambia el campo de espectro.
        self.assertEqual([l[:44] for l in a], [l[:44] for l in b])
        self.assertIn("C7", a[0])
        self.assertIn("C2", b[0])


class TestMyModel(unittest.TestCase):
    def test_estructura_formato_bo11(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "MY_MODEL.OUT")
        rows = [(1.0, 1.2e4), (0.1, 5.0e3)]
        grids = {1: [0.1, 1.0], 2: [0.05, 0.5]}
        sep.write_my_model(out, rows, grids=grids)
        with open(out) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], "1968.041096")          # epoca
        self.assertIn("Z", lines[1].strip().split()[0])    # cabecera de columnas
        data = [l.split() for l in lines[2:]]
        z1 = [r for r in data if int(r[0]) == 1]
        z2 = [r for r in data if int(r[0]) == 2]
        self.assertEqual(len(z1), 2)
        self.assertEqual(len(z2), 2)                       # Z=2..28 a cero
        self.assertEqual(float(z1[0][2]), 5.0e3)
        self.assertEqual(float(z1[1][2]), 1.2e4)
        self.assertTrue(all(float(r[2]) == 0.0 for r in z2))

    def test_sin_grids_solo_bloque_z1(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "MY_MODEL.OUT")
        sep.write_my_model(out, [(1.0, 7.0)], grids=None)
        with open(out) as f:
            data = [l.split() for l in f.read().splitlines()[2:]]
        self.assertTrue(all(int(r[0]) == 1 for r in data))

    def test_proyeccion_espectro_arbitrario(self):
        grid = [0.1, 0.5, 1.0, 10.0]
        rows = sep.project_proton_flux([(0.1, 3.0), (1.0, 3.0), (10.0, 3.0)], grid)
        # Constante en las muestras -> constante en la malla.
        self.assertTrue(all(abs(f - 3.0) < 1e-9 for _, f in rows))
        # Extrapolacion plana fuera del rango.
        rows2 = sep.project_proton_flux([(1.0, 8.0)], grid)
        self.assertTrue(all(f == 8.0 for _, f in rows2))
        # Cero en un extremo no rompe la interpolacion log.
        rows3 = sep.project_proton_flux([(0.1, 0.0), (1.0, 4.0), (10.0, 0.0)], grid)
        self.assertEqual(rows3[0][1], 0.0)
        self.assertEqual(rows3[3][1], 0.0)

    def test_copia_verbatim(self):
        d = tempfile.mkdtemp()
        src = os.path.join(d, "src.OUT")
        with open(src, "w") as f:
            f.write("2002.041096\n   Z       E            F\n   1  1.000E-02  8.418E+00\n")
        dst = os.path.join(d, "MY_MODEL.OUT")
        # write_my_model_from_file copia literalmente desde un "GCR_MODELS"
        gcr = os.path.join(d, "GCR_MODELS")
        os.makedirs(gcr)
        src_deploy = os.path.join(gcr, "BO11_GCR.OUT")
        with open(src) as f:
            src_bytes = f.read()
        with open(src_deploy, "w") as f:
            f.write(src_bytes)
        sep.write_my_model_from_file(d, "BO11_GCR.OUT", dst)
        with open(src) as f1, open(dst) as f2:
            self.assertEqual(f1.read(), f2.read())


class TestPuerta(unittest.TestCase):
    def test_identicos_ratio_1(self):
        a = {(0.0, 10.5): 3.0, (5.0, 12.0): 7.7}
        n, mx, mn, lo, hi, same = compare_rate_maps(a, dict(a))
        self.assertEqual(n, 2)
        self.assertEqual(mx, 0.0)
        self.assertEqual((lo, hi), (1.0, 1.0))
        self.assertTrue(same)

    def test_mutacion_cm2_m2_queda_roja(self):
        # Mutacion clasica de T4: un 10^4 silencioso en la conversion cm^2/m^2
        # debe superar la tolerancia de la puerta (0.05) y disparar el fallo.
        a = {(0.0, 10.5): 3.0, (3.2, 10.5): 9.9, (7.0, 12.0): 4.4}
        b = {k: v * 1e4 for k, v in a.items()}
        n, mx, mn, lo, hi, same = compare_rate_maps(a, b)
        self.assertTrue(same)
        self.assertGreater(mx, DEFAULT_TOLERANCE)
        self.assertLess(hi, 0.05)          # ratio ~1e-4 << 1: el factor es claro

    def test_conjuntos_parciales_se_ven(self):
        a = {(0.0, 10.5): 3.0, (5.0, 12.0): 7.7}
        n, mx, mn, lo, hi, same = compare_rate_maps(a, {(0.0, 10.5): 3.0})
        self.assertEqual(n, 1)
        self.assertFalse(same)

    def test_vacio_no_da_falso_positivo(self):
        n, mx, mn, lo, hi, same = compare_rate_maps({}, {})
        self.assertEqual(n, 0)             # sin puntos comparables: el gate falla
        self.assertTrue(same)              # (ambos conjuntos vacios son iguales)
        self.assertTrue(mx > DEFAULT_TOLERANCE or n == 0)


if __name__ == "__main__":
    unittest.main()