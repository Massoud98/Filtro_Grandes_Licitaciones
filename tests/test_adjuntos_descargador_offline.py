"""Offline transaction tests for the individual attachment downloader."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from checkpoint_descargas import create_checkpoint, save_checkpoint, CheckpointError
from descargador_individual import download_one, IndividualDownloadError


class FakeDownload:
    suggested_filename = "bases.pdf"

    def __init__(self, payload=b"Offline attachment content.", failure=None,
                 interrupt=False):
        self.payload = payload
        self.failure_message = failure
        self.interrupt = interrupt

    def failure(self):
        return self.failure_message

    def save_as(self, path):
        Path(path).write_bytes(self.payload)
        if self.interrupt:
            raise OSError("Simulated interrupted download")


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


class DownloaderTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.checkpoints = self.root / "checkpoints"

        for folder in (self.downloads, self.extracted, self.checkpoints):
            folder.mkdir()

        self.tender_id = "100-1-LE26"
        self.other_id = "200-2-LE26"
        self.control_id = "DWNL_grdId_01_search"
        self.authorized = frozenset((self.tender_id, self.other_id))

        classification = self.root / "classification.json"
        classification.write_text("{}", encoding="utf-8")

        self.checkpoint = create_checkpoint(
            [self.tender_id], classification
        )
        self.checkpoint_path = self.checkpoints / "lote_0001.json"
        save_checkpoint(self.checkpoint_path, self.checkpoint)

    def download(self, fake):
        with patch("descargador_individual.check_access"):
            return download_one(
                FakePopup(fake),
                self.tender_id,
                self.control_id,
                self.checkpoint,
                self.checkpoint_path,
                self.downloads,
                self.extracted,
                authorized_ids=self.authorized,
            )

    def persisted(self):
        return json.loads(
            self.checkpoint_path.read_text(encoding="utf-8")
        )

    def records(self):
        return self.checkpoint["licitaciones"][self.tender_id]["attachments"]

    def test_successful_download_is_verified_and_checkpointed(self):
        payload = b"Verified offline attachment."
        record = self.download(FakeDownload(payload))

        self.assertEqual(record["status"], "DOWNLOADED")
        self.assertEqual(record["size_bytes"], len(payload))
        self.assertEqual(
            record["sha256"], hashlib.sha256(payload).hexdigest()
        )
        self.assertEqual(
            (self.downloads / self.tender_id / "bases.pdf").read_bytes(),
            payload,
        )
        self.assertEqual(self.persisted(), self.checkpoint)

    def test_browser_failure_preserves_checkpoint(self):
        with self.assertRaises(IndividualDownloadError):
            self.download(FakeDownload(failure="Simulated failure"))

        self.assertEqual(self.records(), [])
        self.assertEqual(self.persisted(), self.checkpoint)

    def test_interrupted_download_preserves_partial_file(self):
        with self.assertRaises(IndividualDownloadError):
            self.download(FakeDownload(interrupt=True))

        folder = self.downloads / self.tender_id
        self.assertEqual(len(list(folder.glob(".mp-download-*.part"))), 1)
        self.assertEqual(self.records(), [])
        self.assertEqual(self.persisted(), self.checkpoint)

    def test_duplicate_control_is_rejected(self):
        self.download(FakeDownload())

        with self.assertRaises(IndividualDownloadError):
            self.download(FakeDownload())

        self.assertEqual(len(self.records()), 1)

    def test_modified_persisted_checkpoint_is_rejected(self):
        self.checkpoint_path.write_text(
            '{"unexpected":true}', encoding="utf-8"
        )

        with self.assertRaises(IndividualDownloadError):
            self.download(FakeDownload())

        self.assertEqual(self.records(), [])

    def test_checkpoint_save_failure_preserves_published_file(self):
        payload = b"Published before checkpoint persistence."
        original = self.persisted()

        with patch(
            "descargador_individual.save_checkpoint",
            side_effect=OSError("Simulated checkpoint failure"),
        ):
            with self.assertRaises(IndividualDownloadError):
                self.download(FakeDownload(payload))

        published = self.downloads / self.tender_id / "bases.pdf"

        self.assertTrue(published.is_file())
        self.assertEqual(published.read_bytes(), payload)
        self.assertEqual(self.records(), [])
        self.assertEqual(self.persisted(), original)

        with self.assertRaisesRegex(
            CheckpointError, "Untracked original attachment"
        ):
            self.download(FakeDownload(b"Replacement must be refused."))

        self.assertEqual(published.read_bytes(), payload)
        self.assertEqual(self.records(), [])
        self.assertEqual(self.persisted(), original)

    def test_other_authorized_batch_directory_is_accepted(self):
        (self.extracted / self.other_id).mkdir()

        record = self.download(FakeDownload())

        self.assertEqual(record["status"], "DOWNLOADED")
        self.assertTrue((self.extracted / self.other_id).is_dir())


if __name__ == "__main__":
    unittest.main()