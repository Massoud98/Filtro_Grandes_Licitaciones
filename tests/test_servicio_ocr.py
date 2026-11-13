"""Isolated tests for the production OCR service."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aplicacion.servicios.servicio_ocr import (
    OcrServiceError,
    recognize_pdf_page,
    validate_ocr_environment,
)


class FakePixmap:
    width = 100
    height = 100

    def tobytes(self, format_name):
        assert format_name == "png"
        return b"synthetic-png"


class FakePage:
    rect = SimpleNamespace(width=100, height=100)

    def get_pixmap(self, **kwargs):
        return FakePixmap()


class OcrServiceTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        root = Path(self.temp.name)
        self.executable = root / "tesseract.exe"
        self.tessdata = root / "tessdata"
        self.model = self.tessdata / "spa.traineddata"

        self.executable.write_bytes(b"synthetic")
        self.tessdata.mkdir()
        self.model.write_bytes(b"synthetic")

    def recognize(self, page=None, **kwargs):
        options = {
            "tesseract_path": self.executable,
            "tessdata_directory": self.tessdata,
        }
        options.update(kwargs)

        return recognize_pdf_page(
            page if page is not None else FakePage(),
            **options,
        )

    def test_valid_environment(self):
        executable, tessdata = validate_ocr_environment(
            self.executable,
            self.tessdata,
        )
        self.assertEqual(executable, self.executable)
        self.assertEqual(tessdata, self.tessdata)

    def test_missing_executable(self):
        self.executable.unlink()

        with self.assertRaises(OcrServiceError):
            self.recognize()

    def test_missing_spanish_model(self):
        self.model.unlink()

        with self.assertRaises(OcrServiceError):
            self.recognize()

    def test_invalid_timeout(self):
        for value in (0, -1, 301, True, "120"):
            with self.subTest(value=value):
                with self.assertRaises(OcrServiceError):
                    self.recognize(timeout_seconds=value)

    def test_invalid_dpi(self):
        for value in (0, 71, 301, True, 150.5):
            with self.subTest(value=value):
                with self.assertRaises(OcrServiceError):
                    self.recognize(dpi=value)

    def test_page_pixel_limit(self):
        page = FakePage()
        page.rect = SimpleNamespace(
            width=100000,
            height=100000,
        )

        with self.assertRaises(OcrServiceError):
            self.recognize(page)

    @patch("subprocess.run")
    def test_successful_recognition(self, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="Texto reconocido\n".encode("utf-8"),
            stderr=b"",
        )

        result = self.recognize()

        self.assertEqual(result, "Texto reconocido")
        self.assertEqual(run.call_count, 1)

        args = run.call_args.args[0]
        self.assertEqual(args[0], str(self.executable))
        self.assertIn("spa", args)
        self.assertEqual(
            run.call_args.kwargs["input"],
            b"synthetic-png",
        )

    @patch("subprocess.run")
    def test_tesseract_nonzero_exit(self, run):
        run.return_value = SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"Language data error",
        )

        with self.assertRaisesRegex(
            OcrServiceError,
            "Tesseract returned error",
        ):
            self.recognize()

    @patch("subprocess.run")
    def test_tesseract_timeout(self, run):
        run.side_effect = subprocess.TimeoutExpired(
            cmd="tesseract",
            timeout=120,
        )

        with self.assertRaisesRegex(
            OcrServiceError,
            "timeout",
        ):
            self.recognize()

    @patch("subprocess.run")
    def test_tesseract_os_error(self, run):
        run.side_effect = OSError("Execution unavailable")

        with self.assertRaisesRegex(
            OcrServiceError,
            "execution failed",
        ):
            self.recognize()

    @patch("subprocess.run")
    def test_rendering_error(self, run):
        page = FakePage()

        def fail_render(**kwargs):
            raise RuntimeError("Invalid rendering")

        page.get_pixmap = fail_render

        with self.assertRaisesRegex(
            OcrServiceError,
            "rendering failed",
        ):
            self.recognize(page)

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()