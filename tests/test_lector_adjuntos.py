"""Tests for read-only native attachment extraction."""

import tempfile
import unittest
from pathlib import Path

import pymupdf
from docx import Document

from aplicacion.servicios.lector_adjuntos import (
    AttachmentExtractionError,
    extract_attachment,
)


class NativeAttachmentReaderTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="mp_reader_unit_"
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def create_pdf(self, filename, texts):
        path = self.root / filename
        document = pymupdf.open()

        try:
            for text in texts:
                page = document.new_page()

                if text:
                    page.insert_text((72, 72), text)

            document.save(str(path))
        finally:
            document.close()

        return path

    def test_pdf_preserves_page_boundaries(self):
        path = self.create_pdf(
            "native.pdf",
            [
                "LICITACION DE PRUEBA CON TEXTO NATIVO SUFICIENTE",
                "REQUISITOS ADMINISTRATIVOS Y TECNICOS DE PRUEBA",
            ],
        )

        result = extract_attachment(path)

        self.assertEqual(result["format"], "pdf")
        self.assertEqual(result["method"], "native_pdf")
        self.assertEqual(
            [segment["page"] for segment in result["segments"]],
            [1, 2],
        )
        self.assertEqual(result["pages_requiring_ocr"], [])
        self.assertFalse(result["requires_human_review"])

    def test_pdf_flags_image_only_page(self):
        path = self.create_pdf("scanned.pdf", [""])

        result = extract_attachment(path)

        self.assertEqual(result["pages_requiring_ocr"], [1])
        self.assertTrue(result["requires_human_review"])

    def test_docx_preserves_paragraph_and_table_order(self):
        path = self.root / "structured.docx"

        document = Document()
        document.add_paragraph("REQUISITOS ADMINISTRATIVOS")

        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Producto"
        table.cell(0, 1).text = "Cantidad"
        table.cell(1, 0).text = "Arroz"
        table.cell(1, 1).text = "100"

        document.add_paragraph("PLAZO DE ENTREGA")
        document.save(str(path))

        result = extract_attachment(path)

        self.assertEqual(result["format"], "docx")
        self.assertEqual(
            [segment["kind"] for segment in result["segments"]],
            [
                "docx_paragraph",
                "docx_table_row",
                "docx_table_row",
                "docx_paragraph",
            ],
        )

        rows = [
            segment["cells"]
            for segment in result["segments"]
            if segment["kind"] == "docx_table_row"
        ]

        self.assertEqual(
            rows,
            [
                ["Producto", "Cantidad"],
                ["Arroz", "100"],
            ],
        )

        self.assertIn(
            "PLAZO DE ENTREGA",
            result["searchable_text"],
        )

    def test_docx_header_footer_extraction(self):
        path = self.root / "header_footer.docx"

        document = Document()
        document.add_paragraph("REQUISITOS DEL CONTRATO")

        section = document.sections[0]
        section.header.paragraphs[0].text = (
            "SERVICIO DE SALUD ARAUCANIA NORTE"
        )
        section.footer.paragraphs[0].text = (
            "PAGINA UNO"
        )

        document.save(str(path))

        result = extract_attachment(path)

        self.assertIn(
            "REQUISITOS DEL CONTRATO",
            result["searchable_text"],
        )
        self.assertIn(
            "SERVICIO DE SALUD ARAUCANIA NORTE",
            result["searchable_text"],
        )
        self.assertIn(
            "PAGINA UNO",
            result["searchable_text"],
        )

        header_segments = [
            segment for segment in result["segments"]
            if segment["kind"] == "docx_header"
        ]
        footer_segments = [
            segment for segment in result["segments"]
            if segment["kind"] == "docx_footer"
        ]

        self.assertEqual(len(header_segments), 1)
        self.assertEqual(len(footer_segments), 1)
        self.assertEqual(header_segments[0]["section"], 1)
        self.assertEqual(footer_segments[0]["section"], 1)

    def test_docx_linked_headers_not_duplicated(self):
        from docx.enum.section import WD_SECTION_START

        path = self.root / "linked_headers.docx"

        document = Document()
        document.add_paragraph("PRIMERA SECCION")

        document.sections[0].header.paragraphs[0].text = (
            "ENCABEZADO COMPARTIDO"
        )

        second = document.add_section(
            WD_SECTION_START.NEW_PAGE
        )
        self.assertTrue(second.header.is_linked_to_previous)

        document.add_paragraph("SEGUNDA SECCION")
        document.save(str(path))

        result = extract_attachment(path)

        matching = [
            segment for segment in result["segments"]
            if segment["kind"] == "docx_header"
            and "ENCABEZADO COMPARTIDO" in segment["text"]
        ]

        self.assertEqual(len(matching), 1)

    def test_docx_without_headers_has_no_empty_segments(self):
        path = self.root / "plain.docx"

        document = Document()
        document.add_paragraph("DOCUMENTO SIN ENCABEZADOS")
        document.save(str(path))

        result = extract_attachment(path)

        self.assertEqual(
            [segment["kind"] for segment in result["segments"]],
            ["docx_paragraph"],
        )

    def test_missing_file_rejected(self):
        with self.assertRaises(AttachmentExtractionError):
            extract_attachment(self.root / "missing.pdf")

    def test_unsupported_extension_rejected(self):
        path = self.root / "unsupported.txt"
        path.write_text("test", encoding="utf-8")

        with self.assertRaises(AttachmentExtractionError):
            extract_attachment(path)

    def test_corrupt_pdf_rejected(self):
        path = self.root / "corrupt.pdf"
        path.write_bytes(b"not a real PDF")

        with self.assertRaises(AttachmentExtractionError):
            extract_attachment(path)


if __name__ == "__main__":
    unittest.main()