"""Pruebas sintéticas del parser de uso de OpenCode."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uso


def evento(tokens=None, reason="stop"):
    parte = {"type": "step-finish", "reason": reason}
    if tokens is not None:
        parte["tokens"] = tokens
    return json.dumps({"type": "step-finish", "part": parte})


class TestUso(unittest.TestCase):
    def test_suma_tokens_y_cache_de_varios_pasos(self):
        lineas = [
            evento({"input": 100, "output": 20, "reasoning": 5, "cache": {"read": 10, "write": 2}}),
            json.dumps({"type": "text", "part": {"type": "text", "text": "ignorar"}}),
            evento({"input": 40, "output": 8, "reasoning": 2, "cache": {"read": 3, "write": 1}}),
        ]
        resumen = uso.resumir_stream(lineas)
        self.assertTrue(resumen["disponible"])
        self.assertTrue(resumen["completo"])
        self.assertEqual(resumen["pasos"], 2)
        self.assertEqual(resumen["entrada"], 140)
        self.assertEqual(resumen["salida"], 28)
        self.assertEqual(resumen["razonamiento"], 7)
        self.assertEqual(resumen["cache_lectura"], 13)
        self.assertEqual(resumen["cache_escritura"], 3)
        self.assertEqual(resumen["razon_final"], "stop")

    def test_no_inventa_cero_si_no_hay_tokens(self):
        resumen = uso.resumir_stream([evento(), '{"type": "text"}'])
        self.assertFalse(resumen["disponible"])
        self.assertIsNone(resumen["entrada"])
        self.assertIsNone(resumen["salida"])
        self.assertEqual(resumen["pasos"], 1)

    def test_eventos_incompletos_mantienen_campos_ausentes_como_none(self):
        resumen = uso.resumir_stream([
            evento({"input": 11, "output": 2}, reason="tool-calls"),
            evento({"input": 7, "output": 3, "reasoning": 1, "cache": {"read": 0, "write": 0}}),
        ])
        self.assertTrue(resumen["disponible"])
        self.assertFalse(resumen["completo"])
        self.assertEqual(resumen["entrada"], 18)
        self.assertEqual(resumen["salida"], 5)
        self.assertIsNone(resumen["razonamiento"])
        self.assertIsNone(resumen["cache_lectura"])
        self.assertEqual(resumen["lineas_invalidas"], 0)

    def test_cuenta_json_invalido_sin_abortar(self):
        resumen = uso.resumir_stream(["no-json", evento({
            "input": 1, "output": 2, "reasoning": 0, "cache": {"read": 0, "write": 0}
        })])
        self.assertEqual(resumen["lineas_invalidas"], 1)
        self.assertEqual(resumen["entrada"], 1)

    def test_archivo_ausente_no_se_confunde_con_uso_cero(self):
        with tempfile.TemporaryDirectory() as tmp:
            resumen = uso.resumir_archivo(Path(tmp) / "no-existe.jsonl")
        self.assertFalse(resumen["disponible"])
        self.assertEqual(resumen["motivo"], "archivo_ausente")
        self.assertIsNone(resumen["entrada"])


if __name__ == "__main__":
    unittest.main()
