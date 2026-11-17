import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from aplicacion.servicios import filtros_preliminares as motor

FECHA = "2026-11-10"
EVALUACION = datetime(2026, 11, 10, 12, 0, tzinfo=motor.ZONA)


class CategoryPipelineIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / FECHA
        self.folder.mkdir()

        patcher = patch.object(motor, "CARPETA_ORIGINALES", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, items):
        code = "TEST-CATEGORY-1"

        detail = {
            "Tipo": "LE",
            "Nombre": "Category integration test",
            "MontoEstimado": 50000000,
            "Moneda": "CLP",
            "Fechas": {
                "FechaCierre": (
                    EVALUACION + timedelta(days=10)
                ).isoformat()
            },
        }

        if items is not None:
            detail["Items"] = {"Listado": items}

        payload = {
            "fecha": FECHA,
            "ids": [code],
            "detalles": {code: detail},
        }

        (self.folder / "detalles_licitaciones.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        result = motor.aplicar_filtros(
            FECHA,
            evaluacion=EVALUACION,
        )

        return result["resultados"][0]

    def test_hard_exclusion_wins_over_permitted_item(self):
        row = self.execute([
            {"CodigoCategoria": "53103000"},
            {"CodigoCategoria": "91111700"},
        ])
        self.assertEqual(row["estado"], "excluida")
        self.assertEqual(row["categoria_decision"], "EXCLUDED_SERVICES")

    def test_permitted_category_continues(self):
        row = self.execute([
            {"CodigoCategoria": "53103000"},
        ])
        self.assertEqual(row["estado"], "incluida")
        self.assertEqual(row["categoria_decision"], "CONTINUE")

    def test_unknown_category_requires_manual_review(self):
        row = self.execute([
            {"CodigoCategoria": "99999999"},
        ])
        self.assertEqual(row["estado"], "revision_manual")
        self.assertEqual(row["categoria_decision"], "INVESTIGATE")

    def test_missing_items_requires_manual_review(self):
        row = self.execute(None)
        self.assertEqual(row["estado"], "revision_manual")
        self.assertEqual(row["categoria_decision"], "INVESTIGATE")


if __name__ == "__main__":
    unittest.main()
