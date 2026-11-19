"""Regression tests for production DOCX extraction."""

import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document

PRODUCTION_CODE = (
    Path(__file__).resolve().parents[1]
    / "integracion_adjuntos"
    / "codigo"
)

sys.path.insert(0, str(PRODUCTION_CODE))

from extractor_word import extract_docx


class ProductionWordExtractionTests(unittest.TestCase):

    def test_header_body_table_and_footer_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bases.docx"

            document = Document()
            section = document.sections[0]

            section.header.paragraphs[0].text = "HEADER UNIQUE 225"
            document.add_paragraph("BODY UNIQUE 225")

            table = document.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "TABLE LEFT 225"
            table.cell(0, 1).text = "TABLE RIGHT 225"

            section.footer.paragraphs[0].text = "FOOTER UNIQUE 225"

            document.save(source)

            result = extract_docx(source)
            text = result["text"]

            for expected in (
                "HEADER UNIQUE 225",
                "BODY UNIQUE 225",
                "TABLE LEFT 225",
                "TABLE RIGHT 225",
                "FOOTER UNIQUE 225",
            ):
                self.assertIn(expected, text)

            self.assertEqual(result["format"], "docx")
            self.assertGreater(result["total_characters"], 0)

    def test_missing_document_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.docx"

            with self.assertRaises(Exception):
                extract_docx(source)


if __name__ == "__main__":
    unittest.main()
