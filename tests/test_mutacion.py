import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mutacion as m

FUENTE = '''
def signo(x):
    """Docstring 5 que no se muta."""
    if x > 0:
        return 1
    if x < 0 and x != -99:
        return -1
    return 0

def ajena(y):
    return y + 10

if __name__ == "__main__":
    print(signo(3) > 1)
'''

TEST_DEBIL = '''
import unittest, calc
class T(unittest.TestCase):
    def test_positivo(self):
        self.assertEqual(calc.signo(5), 1)
'''

TEST_FUERTE = '''
import unittest, calc
class T(unittest.TestCase):
    def test_todo(self):
        self.assertEqual(calc.signo(5), 1)
        self.assertEqual(calc.signo(1), 1)
        self.assertEqual(calc.signo(0), 0)
        self.assertEqual(calc.signo(-1), -1)
        self.assertEqual(calc.signo(-99), 0)
        self.assertEqual(calc.signo(-2), -1)
'''


class TestSitios(unittest.TestCase):
    def test_enumera_y_aplica_el_mismo_indice(self):
        import ast
        todos = m.sitios(FUENTE)
        self.assertTrue(all(s.indice == i for i, s in enumerate(todos)))
        base = ast.unparse(ast.parse(FUENTE))
        for s in todos:
            self.assertNotEqual(m.aplicar(FUENTE, s.indice), base, f"el sitio {s} no cambió el código")

    def test_ignora_main_y_docstring(self):
        todos = m.sitios(FUENTE)
        self.assertFalse(any(s.linea >= 13 for s in todos), "no debe mutar el bloque __main__")
        for s in todos:
            self.assertIn('"""Docstring 5 que no se muta."""', m.aplicar(FUENTE, s.indice))

    def test_filtra_por_funcion(self):
        solo = m.sitios(FUENTE, {"ajena"})
        self.assertTrue(solo and all(s.linea == 11 for s in solo))

    def test_mutacion_cambia_el_operador(self):
        s = next(x for x in m.sitios(FUENTE) if x.tipo == "comparacion" and x.de == ">")
        self.assertIn(">=", m.aplicar(FUENTE, s.indice))

    def test_indice_inexistente(self):
        with self.assertRaises(IndexError):
            m.aplicar(FUENTE, 999)


class TestEvaluar(unittest.TestCase):
    def _proyecto(self, test: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        (tmp / "calc.py").write_text(FUENTE, encoding="utf-8")
        (tmp / "test_calc.py").write_text(test, encoding="utf-8")
        return tmp

    def test_tests_debiles_dejan_sobrevivientes(self):
        r = m.evaluar(self._proyecto(TEST_DEBIL), ["calc.py"], ["python3 -B -m unittest -q test_calc"], ["signo"])
        self.assertGreater(len(r["sobrevivientes"]), 0)
        self.assertLess(r["puntaje"], 1.0)

    def test_tests_fuertes_matan_la_mayoria(self):
        r = m.evaluar(self._proyecto(TEST_FUERTE), ["calc.py"], ["python3 -B -m unittest -q test_calc"], ["signo"])
        debil = m.evaluar(self._proyecto(TEST_DEBIL), ["calc.py"], ["python3 -B -m unittest -q test_calc"], ["signo"])
        self.assertGreater(r["puntaje"], debil["puntaje"])
        self.assertGreaterEqual(r["puntaje"], 0.8)

    def test_no_toca_el_original(self):
        p = self._proyecto(TEST_FUERTE)
        antes = (p / "calc.py").read_text(encoding="utf-8")
        m.evaluar(p, ["calc.py"], ["python3 -B -m unittest -q test_calc"])
        self.assertEqual((p / "calc.py").read_text(encoding="utf-8"), antes)

    def test_oraculo_roto_aborta(self):
        r = m.evaluar(self._proyecto(TEST_FUERTE), ["calc.py"], ["false"])
        self.assertIn("error", r)

    def test_timeout_termina_descendientes_del_oraculo_de_mutacion(self):
        import shlex
        import time
        import sys

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "sobrevivio.txt"
            child = (
                "import signal,time,pathlib; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(0.5); pathlib.Path(" + repr(str(marker)) + ").write_text('vivo')"
            )
            parent = (
                "import signal,subprocess,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); time.sleep(10)"
            )
            comando = shlex.quote(sys.executable) + " -c " + shlex.quote(parent)
            self.assertFalse(m._correr([comando], root, timeout=0.1, gracia_s=0.1))
            time.sleep(0.6)
            self.assertFalse(marker.exists(), "un descendiente de mutación sobrevivió al timeout")

    def test_respeta_el_maximo(self):
        r = m.evaluar(self._proyecto(TEST_FUERTE), ["calc.py"], ["python3 -B -m unittest -q test_calc"], maximo=3)
        self.assertEqual(r["total"], 3)
        self.assertGreater(r["universo"], 3)


if __name__ == "__main__":
    unittest.main()
