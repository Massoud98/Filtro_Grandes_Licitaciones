"""Read-only native extraction of local PDF and DOCX attachments."""

from __future__ import annotations

from pathlib import Path

MIN_NATIVE_PDF_CHARS = 40


class AttachmentExtractionError(ValueError):
    """Raised when a supported attachment cannot be extracted."""


def extract_pdf(path: str | Path, *, ocr_config: dict | None = None) -> dict:
    """Extract native PDF text, preserving page boundaries."""
    import pymupdf

    source = Path(path)
    segments = []
    pages_requiring_ocr = []

    try:
        with pymupdf.open(str(source)) as document:
            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text") or ""

                segments.append(
                    {
                        "kind": "pdf_text",
                        "page": page_number,
                        "text": text,
                    }
                )

                if len(text.strip()) < MIN_NATIVE_PDF_CHARS:
                    pages_requiring_ocr.append(page_number)

    except (OSError, ValueError, RuntimeError) as exc:
        raise AttachmentExtractionError(
            f"Cannot extract PDF: {source.name}"
        ) from exc

    if ocr_config is not None:
        from aplicacion.servicios.servicio_ocr import (
            recognize_pdf_page,
        )

        with pymupdf.open(str(source)) as document:
            for page_number in pages_requiring_ocr:
                recognized = recognize_pdf_page(
                    document[page_number - 1],
                    **ocr_config,
                )

                if not recognized.strip():
                    raise AttachmentExtractionError(
                        f"OCR returned no text for page {page_number}: {source}"
                    )

                segments[page_number - 1] = {
                    "kind": "pdf_ocr",
                    "page": page_number,
                    "text": recognized,
                }

        pages_requiring_ocr = []

    return {
        "filename": source.name,
        "format": "pdf",
        "method": (
            "hybrid_pdf" if any(
                segment["kind"] == "pdf_ocr"
                for segment in segments
            ) else "native_pdf"
        ),
        "segments": segments,
        "searchable_text": "\n\n".join(
            segment["text"] for segment in segments
        ),
        "pages_requiring_ocr": pages_requiring_ocr,
        "requires_human_review": (
            bool(pages_requiring_ocr)
            or any(segment["kind"] == "pdf_ocr" for segment in segments)
        ),
    }


def extract_docx(path: str | Path) -> dict:
    """Extract DOCX paragraphs and structured table rows."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    source = Path(path)
    segments = []

    try:
        document = Document(str(source))

        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                text = block.text

                if text.strip():
                    segments.append(
                        {
                            "kind": "docx_paragraph",
                            "text": text,
                        }
                    )

            elif isinstance(block, Table):
                for row_number, row in enumerate(block.rows, start=1):
                    cells = [cell.text for cell in row.cells]

                    segments.append(
                        {
                            "kind": "docx_table_row",
                            "row": row_number,
                            "cells": cells,
                            "text": " | ".join(cells),
                        }
                    )

        seen_parts = set()

        for section_number, section in enumerate(
            document.sections, start=1
        ):
            containers = (
                ("header", "default", section.header),
                ("footer", "default", section.footer),
                ("header", "first_page", section.first_page_header),
                ("footer", "first_page", section.first_page_footer),
                ("header", "even_page", section.even_page_header),
                ("footer", "even_page", section.even_page_footer),
            )

            for location, variant, container in containers:
                part = container.part
                part_name = str(part.partname)

                if part_name in seen_parts:
                    continue

                seen_parts.add(part_name)

                for block in container.iter_inner_content():
                    if isinstance(block, Paragraph):
                        if block.text.strip():
                            segments.append(
                                {
                                    "kind": f"docx_{location}",
                                    "section": section_number,
                                    "variant": variant,
                                    "text": block.text,
                                }
                            )

                    elif isinstance(block, Table):
                        for row_number, row in enumerate(
                            block.rows, start=1
                        ):
                            cells = [
                                cell.text for cell in row.cells
                            ]

                            segments.append(
                                {
                                    "kind": f"docx_{location}",
                                    "section": section_number,
                                    "variant": variant,
                                    "row": row_number,
                                    "cells": cells,
                                    "text": " | ".join(cells),
                                }
                            )

    except (OSError, ValueError, RuntimeError) as exc:
        raise AttachmentExtractionError(
            f"Cannot extract DOCX: {source.name}"
        ) from exc

    return {
        "filename": source.name,
        "format": "docx",
        "method": "native_docx",
        "segments": segments,
        "searchable_text": "\n\n".join(
            segment["text"] for segment in segments
        ),
        "pages_requiring_ocr": [],
        "requires_human_review": False,
    }


def extract_attachment(path: str | Path, *, ocr_config: dict | None = None) -> dict:
    """Dispatch a local attachment to the appropriate native reader."""
    source = Path(path)

    if not source.is_file():
        raise AttachmentExtractionError(
            f"Attachment does not exist: {source.name}"
        )

    extension = source.suffix.lower()

    if extension == ".pdf":
        return extract_pdf(source, ocr_config=ocr_config)

    if extension == ".docx":
        return extract_docx(source)

    raise AttachmentExtractionError(
        f"Unsupported attachment type: {extension}"
    )