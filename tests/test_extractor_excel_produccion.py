"""Production XLSX extraction regression tests."""

import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

CODE = Path(__file__).resolve().parents[1] / "integracion_adjuntos" / "codigo"
sys.path.insert(0, str(CODE))

from extractor_excel import ExcelExtractionError, extract_xlsx


class ProductionExcelTests(unittest.TestCase):

    def test_multiple_sheets_cells_and_formulas(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "anexo.xlsx"

            workbook = Workbook()
            first = workbook.active
            first.title = "Requisitos"
            first["A1"] = "PRODUCTO LICITADO"
            first["B2"] = 125
            first["C3"] = "=B2*2"

            second = workbook.create_sheet("Condiciones")
            second["D4"] = "ENTREGA OBLIGATORIA"
            workbook.save(source)
            workbook.close()

            original = source.read_bytes()
            result = extract_xlsx(source)

            self.assertEqual(result["format"], "xlsx")
            self.assertEqual(result["sheet_count"], 2)
            self.assertIn("Requisitos!A1: PRODUCTO LICITADO", result["text"])
            self.assertIn("Requisitos!B2: 125", result["text"])
            self.assertIn("Requisitos!C3: =B2*2", result["text"])
            self.assertIn(
                "Condiciones!D4: ENTREGA OBLIGATORIA",
                result["text"],
            )
            self.assertNotIn("Requisitos!A2:", result["text"])
            self.assertEqual(source.read_bytes(), original)

    def test_missing_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ExcelExtractionError):
                extract_xlsx(Path(directory) / "missing.xlsx")

    def test_corrupt_workbook_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "corrupt.xlsx"
            source.write_bytes(b"not an Excel workbook")
            original = source.read_bytes()

            with self.assertRaises(ExcelExtractionError):
                extract_xlsx(source)

            self.assertEqual(source.read_bytes(), original)

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.xlsx"
            workbook = Workbook()
            workbook.active["A1"] = "TEST"
            workbook.save(original)
            workbook.close()

            link = Path(directory) / "linked.xlsx"
            try:
                link.symlink_to(original)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable on this system.")

            with self.assertRaises(ExcelExtractionError):
                extract_xlsx(link)


if __name__ == "__main__":
    unittest.main()
