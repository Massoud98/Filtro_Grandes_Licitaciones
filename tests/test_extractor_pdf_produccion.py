"""Production PDF extraction regression tests."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

CODE = Path(__file__).resolve().parents[1] / "integracion_adjuntos" / "codigo"
sys.path.insert(0, str(CODE))

from extractor_pdf import PDFExtractionError, extract_pdf


class ProductionPDFTests(unittest.TestCase):

    def make_pdf(self, directory, native=True):
        path = Path(directory) / "bases.pdf"
        document = pymupdf.open()
        page = document.new_page()
        if native:
            page.insert_text(
                (72, 72),
                "REQUISITOS DE LICITACION " * 5,
            )
        document.save(str(path))
        document.close()
        return path

    def test_native_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_pdf(directory)
            result = extract_pdf(source, "unused", "unused")
            self.assertEqual(result["page_count"], 1)
            self.assertEqual(result["native_pages"], 1)
            self.assertEqual(result["ocr_pages"], 0)
            self.assertIn("REQUISITOS", result["pages"][0]["text"])

    def test_scanned_pdf_uses_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_pdf(directory, native=False)
            with patch(
                "extractor_pdf.recognize_pdf_page",
                return_value="TEXTO OCR VERIFICADO",
            ) as recognize:
                result = extract_pdf(source, "test.exe", "tessdata")
            self.assertEqual(result["ocr_pages"], 1)
            self.assertEqual(result["pages"][0]["method"], "ocr")
            self.assertEqual(recognize.call_args.kwargs["dpi"], 200)
            self.assertEqual(
                recognize.call_args.kwargs["timeout_seconds"], 180
            )

    def test_ocr_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_pdf(directory, native=False)
            original = source.read_bytes()
            with patch(
                "extractor_pdf.recognize_pdf_page",
                side_effect=RuntimeError("OCR failure"),
            ):
                with self.assertRaises(PDFExtractionError):
                    extract_pdf(source, "test.exe", "tessdata")
            self.assertEqual(source.read_bytes(), original)

    def test_empty_ocr_is_annotated(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_pdf(directory, native=False)
            with patch(
                "extractor_pdf.recognize_pdf_page",
                return_value="",
            ):
                result = extract_pdf(source, "test.exe", "tessdata")

            self.assertEqual(result["page_count"], 1)
            self.assertEqual(result["ocr_pages"], 1)
            self.assertEqual(
                result["pages"][0]["method"],
                "sin_texto_detectado",
            )
            self.assertEqual(
                result["pages_without_detected_text"],
                [1],
            )
            self.assertIn(
                "No se detect? texto en la p?gina 1",
                result["pages"][0]["text"],
            )

    def test_blank_final_page_preserves_page_number(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "blank_final.pdf"
            document = pymupdf.open()
            first = document.new_page()
            first.insert_text(
                (72, 72),
                "REQUISITOS DE LICITACION " * 5,
            )
            document.new_page()
            document.save(str(source))
            document.close()

            with patch(
                "extractor_pdf.recognize_pdf_page",
                return_value="",
            ):
                result = extract_pdf(source, "test.exe", "tessdata")

            self.assertEqual(result["page_count"], 2)
            self.assertEqual(result["native_pages"], 1)
            self.assertEqual(result["ocr_pages"], 1)
            self.assertEqual(
                result["pages_without_detected_text"],
                [2],
            )
            self.assertEqual(
                result["pages"][1]["method"],
                "sin_texto_detectado",
            )

    def test_invalid_parameters_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.make_pdf(directory)
            with self.assertRaises(PDFExtractionError):
                extract_pdf(source, "unused", "unused", dpi=500)


if __name__ == "__main__":
    unittest.main()
