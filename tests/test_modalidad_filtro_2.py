import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "integracion_adjuntos" / "codigo"
if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from interprete_filtro_2 import interpret_modality
from estado_filtro_2 import RULE_VERSION


class TestAdjudicationModality(unittest.TestCase):
    def interpret(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documento.txt"
            path.write_text(content, encoding="utf-8")
            return interpret_modality([
                {"filename": "documento.txt", "text_path": str(path)}
            ])

    def test_missing_modality_assumes_total(self):
        result = self.interpret("Compra de computadores y monitores.")
        self.assertEqual(result["modality"], "TOTAL")
        self.assertTrue(result["assumed_total"])
        self.assertIn("presume", result["reason"])

    def test_explicit_total(self):
        result = self.interpret("No se aceptan ofertas parciales.")
        self.assertEqual(result["modality"], "TOTAL")
        self.assertFalse(result["assumed_total"])

    def test_explicit_partial(self):
        result = self.interpret("Adjudicacion por lineas.")
        self.assertEqual(result["modality"], "PARTIAL")
        self.assertFalse(result["assumed_total"])

    def test_contradiction_remains_unknown(self):
        result = self.interpret(
            "Adjudicacion por lineas. "
            "No se aceptan ofertas parciales."
        )
        self.assertEqual(result["modality"], "UNKNOWN")
        self.assertFalse(result["assumed_total"])

    def test_partial_wording_with_sera(self):
        result = self.interpret(
            "La adjudicacion sera por lineas. "
            "No se aceptan ofertas parciales."
        )
        self.assertEqual(result["modality"], "UNKNOWN")
        self.assertEqual(len(result["contradictions"]), 1)
        self.assertIn(
            "adjudicacion sera por lineas",
            result["contradictions"][0]["partial"]["matched_clause"],
        )

    def test_partial_wording_with_adjudicara(self):
        result = self.interpret(
            "Se adjudicara por lineas. "
            "No se aceptan ofertas parciales."
        )
        self.assertEqual(result["modality"], "UNKNOWN")
        self.assertTrue(result["contradictions"])

    def test_independent_awards_prohibited(self):
        result = self.interpret(
            "No se contempla adjudicacion por lineas."
        )
        self.assertEqual(result["modality"], "TOTAL")
        self.assertFalse(result["assumed_total"])

    def test_contradiction_identifies_both_clauses(self):
        result = self.interpret(
            "=== PAGE 2 [native] ===\\n"
            "Adjudicacion por lineas.\\n"
            "=== PAGE 5 [native] ===\\n"
            "No se aceptan ofertas parciales."
        )
        self.assertEqual(result["modality"], "UNKNOWN")
        self.assertTrue(result["contradictions"])

        conflict = result["contradictions"][0]
        self.assertEqual(conflict["partial"]["page"], 2)
        self.assertEqual(conflict["total"]["page"], 5)
        self.assertIn(
            "Adjudicacion por lineas",
            conflict["partial"]["matched_clause"],
        )
        self.assertIn(
            "No se aceptan ofertas parciales",
            conflict["total"]["matched_clause"],
        )

    def test_no_contradictions_when_modality_assumed(self):
        result = self.interpret("Compra de equipos.")
        self.assertEqual(result["contradictions"], [])
        self.assertTrue(result["assumed_total"])

    def test_rule_version(self):
        self.assertEqual(RULE_VERSION, "filtro2-jessika-v2")


if __name__ == "__main__":
    unittest.main()
