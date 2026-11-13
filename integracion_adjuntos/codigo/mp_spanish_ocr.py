"""Isolated Spanish OCR helper for Mercado Publico PDF pages.

No cache writes, source modifications, downloads, or PDF cleanup.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pymupdf


TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

TESSDATA = (
    Path.home()
    / "Documents"
    / "Filtro_Grandes_Licitaciones"
    / "ocr_tessdata"
)

MAX_RENDER_PIXELS = 25_000_000
OCR_DPI = 150


def recognize_page(page, *, timeout=120):
    """Return OCR text for one PDF page or raise an error.

    The caller owns the PDF document and decides how to
    store or classify the recognized text.
    """
    if not TESSERACT.is_file():
        raise RuntimeError("Tesseract executable unavailable")

    if not (TESSDATA / "spa.traineddata").is_file():
        raise RuntimeError("Spanish OCR language data unavailable")

    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("Invalid OCR timeout")

    if timeout <= 0 or timeout > 300:
        raise ValueError("OCR timeout outside allowed range")

    scale = OCR_DPI / 72

    width = round(page.rect.width * scale)
    height = round(page.rect.height * scale)

    if width <= 0 or height <= 0:
        raise ValueError("Invalid PDF page dimensions")

    if width * height > MAX_RENDER_PIXELS:
        raise ValueError("PDF page exceeds OCR rendering pixel limit")

    with tempfile.TemporaryDirectory(prefix="mp_ocr_page_") as directory:
        image_path = Path(directory) / "page.png"

        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            colorspace=pymupdf.csGRAY,
            alpha=False,
        )

        if pixmap.width * pixmap.height > MAX_RENDER_PIXELS:
            raise ValueError("Rendered image exceeds OCR pixel limit")

        pixmap.save(str(image_path))

        result = subprocess.run(
            [
                str(TESSERACT),
                str(image_path),
                "stdout",
                "--tessdata-dir",
                str(TESSDATA),
                "-l",
                "spa",
                "--psm",
                "3",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Tesseract failed: "
                + result.stderr.strip()[:300]
            )

        return result.stdout.strip()
