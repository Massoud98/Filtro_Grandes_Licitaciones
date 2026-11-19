"""End-to-end offline tests for the production attachment lifecycle."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from checkpoint_descargas import create_checkpoint, save_checkpoint
from descargador_individual import download_one
from coordinador_produccion import extract_downloaded
from coordinador_limpieza import cleanup_extracted


class FakeDownload:
    suggested_filename = "bases.pdf"

    def __init__(self, payload=b"Synthetic PDF attachment."):
        self.payload = payload

    def failure(self):
        return None

    def save_as(self, path):
        Path(path).write_bytes(self.payload)


class FakeEvent:
    def __init__(self, download):
        self.value = download

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeLocator:
    def click(self, timeout=None):
        return None


class FakePopup:
    def __init__(self, download):
        self.download = download

    def expect_download(self, timeout=None):
        return FakeEvent(self.download)

    def locator(self, selector):
        return FakeLocator()


class AttachmentPipelineIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.checkpoints = self.root / "checkpoints"

        for folder in (
            self.downloads,
            self.extracted,
            self.checkpoints,
        ):
            folder.mkdir()

        self.tender_id = "100-1-LE26"
        self.other_id = "200-2-LE26"
        self.control_id = "DWNL_grdId_01_search"
        self.authorized = frozenset(
            (self.tender_id, self.other_id)
        )

        self.classification = self.root / "classification.json"
        self.classification.write_text(
            json.dumps({
                "total": 2,
                "resumen": {"incluida": 2},
                "resultados": [
                    {"id": item, "estado": "incluida"}
                    for item in self.authorized
                ],
            }),
            encoding="utf-8",
        )

        self.checkpoint = create_checkpoint(
            [self.tender_id],
            self.classification,
        )

        self.checkpoint_path = (
            self.checkpoints / "lote_0001.json"
        )

        save_checkpoint(
            self.checkpoint_path,
            self.checkpoint,
        )

        self.original = (
            self.downloads / self.tender_id / "bases.pdf"
        )

        self.output = (
            self.extracted / self.tender_id / "bases"
        )

    def download(self):
        with patch("descargador_individual.check_access"):
            return download_one(
                FakePopup(FakeDownload()),
                self.tender_id,
                self.control_id,
                self.checkpoint,
                self.checkpoint_path,
                self.downloads,
                self.extracted,
                authorized_ids=self.authorized,
            )

    def extract(self, *, failure=None):
        with patch(
            "extractor_produccion.extract_document",
            side_effect=failure,
        ) if failure else patch(
            "extractor_produccion.extract_document",
            return_value=(
                {"format": "pdf", "method": "synthetic"},
                "Synthetic extracted attachment text.",
            ),
        ):
            return extract_downloaded(
                self.checkpoint,
                self.checkpoint_path,
                self.downloads,
                self.extracted,
                self.tender_id,
                self.record,
                self.root,
                self.root / "tesseract.exe",
                self.root / "tessdata",
                authorized_ids=self.authorized,
            )

    @property
    def record(self):
        return self.checkpoint["licitaciones"][
            self.tender_id
        ]["attachments"][0]

    def delete_original(
        self,
        path,
        parent,
        file_identity,
        work_identity,
        digest,
    ):
        self.assertEqual(path, self.original)
        self.assertEqual(path.stat(), file_identity)
        self.assertEqual(parent.stat(), work_identity)
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            digest,
        )
        path.unlink()

    def cleanup(self, delete_function=None):
        return cleanup_extracted(
            self.checkpoint,
            self.checkpoint_path,
            self.downloads,
            self.extracted,
            self.tender_id,
            self.record,
            delete_function=(
                delete_function or self.delete_original
            ),
            authorized_ids=self.authorized,
        )

    def persisted(self):
        return json.loads(
            self.checkpoint_path.read_text(
                encoding="utf-8"
            )
        )

    def test_complete_download_extraction_and_cleanup(self):
        self.download()

        self.assertEqual(self.record["status"], "DOWNLOADED")
        self.assertTrue(self.original.is_file())

        result = self.extract()

        self.assertEqual(result, self.output)
        self.assertEqual(self.record["status"], "EXTRACTED")
        self.assertTrue(self.original.is_file())

        self.cleanup()

        self.assertEqual(self.record["status"], "COMPLETE")
        self.assertFalse(self.original.exists())
        self.assertTrue(
            (self.output / "contenido.txt").is_file()
        )

        persisted = self.persisted()
        self.assertEqual(
            persisted["licitaciones"][self.tender_id]
            ["attachments"][0]["status"],
            "COMPLETE",
        )

    def test_extraction_failure_preserves_original(self):
        self.download()

        with self.assertRaises(RuntimeError):
            self.extract(
                failure=RuntimeError(
                    "Synthetic extraction failure."
                )
            )

        self.assertTrue(self.original.is_file())
        self.assertEqual(self.record["status"], "DOWNLOADED")
        self.assertEqual(
            self.persisted()["licitaciones"][self.tender_id]
            ["attachments"][0]["status"],
            "DOWNLOADED",
        )

    def test_corrupted_extraction_preserves_original(self):
        self.download()
        self.extract()

        (self.output / "contenido.txt").write_text(
            "CORRUPTED CONTENT",
            encoding="utf-8",
        )

        with self.assertRaises(Exception):
            self.cleanup()

        self.assertTrue(self.original.is_file())
        self.assertEqual(self.record["status"], "EXTRACTED")

    def test_cleanup_interruption_persists_pending_state(self):
        self.download()
        self.extract()

        def interrupted_delete(*args):
            raise OSError("Synthetic deletion interruption.")

        with self.assertRaisesRegex(
            OSError,
            "Synthetic deletion interruption",
        ):
            self.cleanup(interrupted_delete)

        self.assertTrue(self.original.is_file())
        self.assertEqual(
            self.record["status"],
            "CLEANUP_PENDING",
        )

        self.assertEqual(
            self.persisted()["licitaciones"][self.tender_id]
            ["attachments"][0]["status"],
            "CLEANUP_PENDING",
        )

    def test_cleanup_recovers_after_interruption(self):
        self.download()
        self.extract()

        def interrupted_delete(*args):
            raise OSError("Synthetic interruption.")

        with self.assertRaises(OSError):
            self.cleanup(interrupted_delete)

        self.assertEqual(
            self.record["status"],
            "CLEANUP_PENDING",
        )

        self.cleanup()

        self.assertEqual(self.record["status"], "COMPLETE")
        self.assertFalse(self.original.exists())

        self.assertEqual(
            self.persisted()["licitaciones"][self.tender_id]
            ["attachments"][0]["status"],
            "COMPLETE",
        )

    def test_cleanup_without_verified_extraction_preserves_original(self):
        self.download()

        with self.assertRaises(Exception):
            self.cleanup()

        self.assertTrue(self.original.is_file())
        self.assertEqual(self.record["status"], "DOWNLOADED")


if __name__ == "__main__":
    unittest.main()