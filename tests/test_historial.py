"""Pruebas del ledger append-only y agregación de corridas."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import historial


class TestHistorial(unittest.TestCase):
    def test_registrar_anexa_registros_sin_prompts_ni_diffs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "runs" / "historial.jsonl"
            estado = {
                "fin_utc": "2026-10-17T12:00:00+00:00",
                "proyecto": "demo", "id": "001", "ronda": 1, "agente": "tester",
                "resultado": "pasa", "duracion_s": 12,
                "uso": {"disponible": True, "completo": True, "entrada": 100, "salida": 20},
                "prompt": "no debe guardarse", "diff": "no debe guardarse",
            }
            historial.registrar_estado(estado, ruta)
            historial.registrar_estado({**estado, "ronda": 2}, ruta)
            lineas = ruta.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lineas), 2)
            primera = json.loads(lineas[0])
            self.assertEqual(primera["uso"]["entrada"], 100)
            self.assertNotIn("prompt", primera)
            self.assertNotIn("diff", primera)

    def test_lectura_ignora_lineas_corruptas_y_no_objetos(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "historial.jsonl"
            ruta.write_text('{"agente":"tester"}\nno-json\n[]\n', encoding="utf-8")
            registros, invalidas = historial.leer_historial(ruta)
        self.assertEqual(registros, [{"agente": "tester"}])
        self.assertEqual(invalidas, 2)

    def test_agrupar_no_inventa_tokens_ausentes(self):
        registros = [
            {"agente": "tester", "resultado": "pasa", "duracion_s": 10,
             "uso": {"entrada": 100, "salida": 20}},
            {"agente": "tester", "resultado": "falla_oraculo", "duracion_s": None, "uso": {}},
            {"agente": "implementador", "resultado": "pasa", "uso": {"entrada": 5}},
        ]
        resumen = historial.agrupar(registros, "agente")
        tester = next(g for g in resumen if g["agente"] == "tester")
        impl = next(g for g in resumen if g["agente"] == "implementador")
        self.assertEqual(tester["corridas"], 2)
        self.assertEqual(tester["pasa"], 1)
        self.assertEqual(tester["uso"]["entrada"]["total"], 100)
        self.assertFalse(tester["uso"]["entrada"]["completo"])
        self.assertEqual(impl["uso"]["entrada"]["total"], 5)
        self.assertIsNone(impl["uso"]["salida"]["total"])

    def test_rechaza_dimensiones_de_agrupacion_desconocidas(self):
        with self.assertRaisesRegex(ValueError, "por debe ser"):
            historial.agrupar([], "modelo")

    def test_archivo_ausente_da_historial_vacio(self):
        with tempfile.TemporaryDirectory() as tmp:
            registros, invalidas = historial.leer_historial(Path(tmp) / "no-existe.jsonl")
        self.assertEqual(registros, [])
        self.assertEqual(invalidas, 0)


if __name__ == "__main__":
    unittest.main()
