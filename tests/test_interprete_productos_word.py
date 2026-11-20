
import tempfile
import unittest
from pathlib import Path

from integracion_adjuntos.codigo.interprete_filtro_2 import (
    count_word_products,
)


class WordProductCounterTests(unittest.TestCase):

    def count(self, text, filename="anexo.doc"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contenido.txt"
            path.write_text(text, encoding="utf-8")

            result = count_word_products([{
                "filename": filename,
                "text_path": str(path),
            }])

            return result, sum(
                item["count"]
                for item in result["documents"]
            )

    def test_quantities_not_product_counts(self):
        _, count = self.count(
            "| Camara de seguridad IP\n"
            "| 50\n"
            "| Grabador digital NVR\n"
            "| 10\n"
        )
        self.assertEqual(count, 2)

    def test_blank_lines_between_cells(self):
        _, count = self.count(
            "| Unidad SSD externo\n"
            "\n|\n\n"
            "| 30\n"
            "\n|\n"
            "| Pendrive Kingston USB\n"
            "\n|\n"
            "| 41\n"
        )
        self.assertEqual(count, 2)

    def test_totals_are_not_products(self):
        _, count = self.count(
            "| Unidad SSD externo\n"
            "| 30\n"
            "| VALOR TOTAL NETO\n"
            "| 100000\n"
            "| IVA\n"
            "| 19000\n"
        )
        self.assertEqual(count, 1)

    def test_no_table_returns_unknown(self):
        result, count = self.count(
            "Se requieren accesorios computacionales."
        )
        self.assertEqual(count, 0)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_docx_supported(self):
        _, count = self.count(
            "| Unidad SSD externo\n"
            "| 30\n",
            filename="anexo.docx",
        )
        self.assertEqual(count, 1)

    def test_missing_quantity_not_counted(self):
        _, count = self.count(
            "| Unidad SSD externo\n"
            "| 30\n"
            "| Pendrive Kingston USB\n"
            "| Grabador digital NVR\n"
            "| 10\n"
        )
        self.assertEqual(count, 2)

    def test_unrecognized_row_must_not_be_confirmed(self):
        result, _ = self.count(
            "| Unidad SSD externo\n"
            "| 30\n"
            "| Pendrive Kingston USB\n"
            "| Grabador digital NVR\n"
            "| 10\n"
        )

        # A missing quantity makes the full table count uncertain.
        self.assertNotEqual(result["status"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
