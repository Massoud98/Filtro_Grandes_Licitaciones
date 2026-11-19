"""Production PDF extractor using the shared Spanish OCR service."""

from pathlib import Path

import pymupdf

from aplicacion.servicios.servicio_ocr import (
    recognize_pdf_page,
)


class PDFExtractionError(RuntimeError):
    pass


def extract_pdf(
    pdf_path,
    tesseract_path,
    tessdata_path,
    min_characters=50,
    dpi=200,
):
    source = Path(pdf_path)

    if source.is_symlink() or not source.is_file():
        raise PDFExtractionError("Unsafe or missing PDF.")

    if (
        type(min_characters) is not int
        or min_characters < 0
        or type(dpi) is not int
        or not 72 <= dpi <= 300
    ):
        raise PDFExtractionError("Invalid extraction parameters.")

    pages = []
    native_count = 0
    ocr_count = 0

    try:
        with pymupdf.open(str(source)) as document:
            if document.needs_pass:
                raise PDFExtractionError(
                    "Encrypted PDF requires a password."
                )

            for page_index, page in enumerate(document):
                native_text = (page.get_text("text") or "").strip()

                if len(native_text) >= min_characters:
                    text = native_text
                    method = "native"
                    native_count += 1
                else:
                    text = recognize_pdf_page(
                        page,
                        tesseract_path=tesseract_path,
                        tessdata_directory=tessdata_path,
                        timeout_seconds=180,
                        dpi=dpi,
                    )
                    method = "ocr"
                    ocr_count += 1

                if not text.strip():
                    # OCR completed but detected no text. Preserve the
                    # page number and flag the uncertainty explicitly.
                    text = (
                        f"No se detect? texto en la p?gina {page_index + 1} "
                        "(posible p?gina en blanco)."
                    )
                    method = "sin_texto_detectado"


                pages.append({
                    "page": page_index + 1,
                    "method": method,
                    "characters": len(text),
                    "text": text,
                })

    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(
            f"PDF extraction failed: {type(exc).__name__}."
        ) from exc

    return {
        "format": "pdf",
        "page_count": len(pages),
        "native_pages": native_count,
        "ocr_pages": ocr_count,
        "pages_without_detected_text": [
            page["page"]
            for page in pages
            if page["method"] == "sin_texto_detectado"
        ],
        "total_characters": sum(
            page["characters"] for page in pages
        ),
        "pages": pages,
    }
