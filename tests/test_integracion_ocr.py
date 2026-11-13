"""Regression tests for optional PDF OCR integration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from aplicacion.servicios.lector_adjuntos import (
    extract_attachment,
)
from aplicacion.servicios.servicio_ocr import OcrServiceError


OCR_CONFIG = {
    "tesseract_path": "synthetic-tesseract",
    "tessdata_directory": "synthetic-tessdata",
}


class OptionalOcrIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_pdf(self, *, native_first=False):
        path = self.root / "synthetic.pdf"

        with pymupdf.open() as document:
            if native_first:
                page = document.new_page()
                page.insert_text(
                    (50, 70),
                    "Native text from the procurement document. "
                    "This page has sufficient selectable text.",
                )

            document.new_page()
            document.save(str(path))

        return path

    def test_ocr_disabled_preserves_pending_review(self):
        path = self.make_pdf()

        with patch(
            "aplicacion.servicios.servicio_ocr.recognize_pdf_page"
        ) as recognize:
            result = extract_attachment(path)

        recognize.assert_not_called()
        self.assertEqual(result["method"], "native_pdf")
        self.assertEqual(result["pages_requiring_ocr"], [1])
        self.assertTrue(result["requires_human_review"])
        self.assertEqual(
            [segment["kind"] for segment in result["segments"]],
            ["pdf_text"],
        )

    def test_successful_ocr_still_requires_human_review(self):
        path = self.make_pdf()

        with patch(
            "aplicacion.servicios.servicio_ocr.recognize_pdf_page",
            return_value="Texto OCR de la pagina escaneada.",
        ) as recognize:
            result = extract_attachment(
                path,
                ocr_config=OCR_CONFIG,
            )

        recognize.assert_called_once()
        self.assertEqual(result["method"], "hybrid_pdf")
        self.assertEqual(result["pages_requiring_ocr"], [])
        self.assertTrue(result["requires_human_review"])
        self.assertEqual(result["segments"][0]["kind"], "pdf_ocr")
        self.assertEqual(result["segments"][0]["page"], 1)
        self.assertIn(
            "Texto OCR",
            result["searchable_text"],
        )

    def test_mixed_pdf_preserves_native_and_ocr_pages(self):
        path = self.make_pdf(native_first=True)

        with patch(
            "aplicacion.servicios.servicio_ocr.recognize_pdf_page",
            return_value="Contenido de la segunda pagina.",
        ) as recognize:
            result = extract_attachment(
                path,
                ocr_config=OCR_CONFIG,
            )

        recognize.assert_called_once()
        self.assertEqual(result["method"], "hybrid_pdf")
        self.assertEqual(
            [segment["kind"] for segment in result["segments"]],
            ["pdf_text", "pdf_ocr"],
        )
        self.assertEqual(
            [segment["page"] for segment in result["segments"]],
            [1, 2],
        )
        self.assertEqual(result["pages_requiring_ocr"], [])
        self.assertTrue(result["requires_human_review"])
        self.assertIn(
            "Native text",
            result["searchable_text"],
        )
        self.assertIn(
            "Contenido de la segunda pagina",
            result["searchable_text"],
        )

    def test_ocr_failure_is_not_silently_accepted(self):
        path = self.make_pdf()

        with patch(
            "aplicacion.servicios.servicio_ocr.recognize_pdf_page",
            side_effect=OcrServiceError("Synthetic OCR failure"),
        ):
            with self.assertRaisesRegex(
                OcrServiceError,
                "Synthetic OCR failure",
            ):
                extract_attachment(
                    path,
                    ocr_config=OCR_CONFIG,
                )


if __name__ == "__main__":
    unittest.main()