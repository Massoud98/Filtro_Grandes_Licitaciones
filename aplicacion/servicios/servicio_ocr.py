"""Bounded, configurable Spanish OCR for individual PDF pages."""

from __future__ import annotations

import subprocess
from pathlib import Path

OCR_DPI = 150
MAX_RENDER_PIXELS = 25_000_000
DEFAULT_TIMEOUT_SECONDS = 120


class OcrServiceError(RuntimeError):
    """Raised when OCR configuration or execution is invalid."""


def validate_ocr_environment(
    tesseract_path: str | Path,
    tessdata_directory: str | Path,
) -> tuple[Path, Path]:
    """Validate explicit executable and Spanish model locations."""
    executable = Path(tesseract_path)
    tessdata = Path(tessdata_directory)

    if not executable.is_file():
        raise OcrServiceError(
            f"Tesseract executable unavailable: {executable}"
        )

    if not (tessdata / "spa.traineddata").is_file():
        raise OcrServiceError(
            f"Spanish OCR model unavailable: {tessdata}"
        )

    return executable, tessdata


def recognize_pdf_page(
    page,
    *,
    tesseract_path: str | Path,
    tessdata_directory: str | Path,
    timeout_seconds: int | float = DEFAULT_TIMEOUT_SECONDS,
    dpi: int = OCR_DPI,
) -> str:
    """Recognize one PDF page without modifying the source PDF."""
    import pymupdf

    executable, tessdata = validate_ocr_environment(
        tesseract_path,
        tessdata_directory,
    )

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= 300
    ):
        raise OcrServiceError("Invalid OCR timeout.")

    if (
        isinstance(dpi, bool)
        or not isinstance(dpi, int)
        or not 72 <= dpi <= 300
    ):
        raise OcrServiceError("Invalid OCR DPI.")

    scale = dpi / 72
    width = round(page.rect.width * scale)
    height = round(page.rect.height * scale)

    if width <= 0 or height <= 0:
        raise OcrServiceError("Invalid PDF page dimensions.")

    if width * height > MAX_RENDER_PIXELS:
        raise OcrServiceError(
            "PDF page exceeds OCR rendering pixel limit."
        )

    try:
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            colorspace=pymupdf.csGRAY,
            alpha=False,
        )

        if pixmap.width * pixmap.height > MAX_RENDER_PIXELS:
            raise OcrServiceError(
                "Rendered image exceeds OCR pixel limit."
            )

        result = subprocess.run(
            [
                str(executable),
                "stdin",
                "stdout",
                "--tessdata-dir",
                str(tessdata),
                "-l",
                "spa",
                "--psm",
                "3",
            ],
            input=pixmap.tobytes("png"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )

    except subprocess.TimeoutExpired as exc:
        raise OcrServiceError(
            "OCR exceeded the configured timeout."
        ) from exc
    except OSError as exc:
        raise OcrServiceError(
            f"OCR execution failed: {exc}"
        ) from exc
    except (ValueError, RuntimeError) as exc:
        if isinstance(exc, OcrServiceError):
            raise
        raise OcrServiceError(
            f"PDF rendering failed: {exc}"
        ) from exc

    if result.returncode != 0:
        details = result.stderr.decode(
            "utf-8", errors="replace"
        ).strip()[:300]

        raise OcrServiceError(
            f"Tesseract returned error {result.returncode}: {details}"
        )

    return result.stdout.decode(
        "utf-8", errors="replace"
    ).strip()