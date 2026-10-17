"""Regresión de contratos críticos entre la skill y los agentes del orquestador."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestContratosDeInstrucciones(unittest.TestCase):
    def test_skill_no_presenta_el_worktree_como_frontera_de_seguridad(self):
        skill = (ROOT / "skills" / "director-opencode" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Un worktree no es un sandbox de seguridad", skill)
        self.assertIn("Por defecto, el despachador **no** enlaza", skill)
        self.assertNotIn("el trabajador nunca puede leer fuera de él", skill)
        self.assertNotIn(
            "El despachador enlaza `.venv`/`node_modules` del repo en el worktree",
            skill,
        )

    def test_prompt_del_revisor_usa_una_severidad_por_hallazgo(self):
        reviewer = (ROOT / "agents" / "revisor.md").read_text(encoding="utf-8")

        self.assertIn("exactamente UNA severidad", reviewer)
        self.assertIn("`[ALTA]`, `[MEDIA]` o `[BAJA]`", reviewer)
        self.assertNotIn("- [ALTA|MEDIA|BAJA] archivo:línea", reviewer)


if __name__ == "__main__":
    unittest.main()
