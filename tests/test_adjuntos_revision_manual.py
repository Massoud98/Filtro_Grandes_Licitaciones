"""Offline tests for preserved attachments requiring manual review."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULES = Path(__file__).resolve().parents[1] / "integracion_adjuntos" / "codigo"
if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from checkpoint_descargas import (
    CheckpointError,
    create_checkpoint,
    save_checkpoint,
    verify_extraction_lifecycle,
)
from coordinador_revision import (
    ManualReviewError,
    register_manual_review,
    review_category,
)
from orquestador_produccion import process_tender


class ManualReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.downloads.mkdir()
        self.extracted.mkdir()
        self.tender = "100-1-LE26"
        self.authorized = frozenset({self.tender})
        classification = self.root / "classification.json"
        classification.write_text("{}", encoding="utf-8")
        self.checkpoint = create_checkpoint([self.tender], classification)
        self.checkpoint_path = self.root / "checkpoint.json"
        self.entry = self.checkpoint["licitaciones"][self.tender]
        (self.downloads / self.tender).mkdir()
        self.entry["discovered"] = 0

    def add_file(self, filename, payload=b"offline synthetic attachment"):
        original = self.downloads / self.tender / filename
        original.write_bytes(payload)
        record = {
            "control_id": f"attachment_{len(self.entry['attachments']) + 1}",
            "filename": filename,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "status": "DOWNLOADED",
        }
        self.entry["attachments"].append(record)
        self.entry["discovered"] = len(self.entry["attachments"])
        save_checkpoint(self.checkpoint_path, self.checkpoint)
        return original, record

    def register(self, record):
        return register_manual_review(
            self.checkpoint,
            self.checkpoint_path,
            self.downloads,
            self.extracted,
            self.tender,
            record,
            authorized_ids=self.authorized,
        )

    def test_media_preserved_and_verified(self):
        original, record = self.add_file("video.MP4")
        review = self.register(record)
        self.assertEqual(review["category"], "MEDIA")
        self.assertEqual(review["extension"], ".mp4")
        self.assertTrue(original.is_file())
        self.assertEqual(record["status"], "REVIEW_REQUIRED")
        self.assertIn("manual review", review["reason"].lower())
        verify_extraction_lifecycle(
            self.checkpoint, self.downloads, self.extracted,
            authorized_ids=self.authorized,
        )
        persisted = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["licitaciones"][self.tender]["attachments"][0]["review"],
            review,
        )

    def test_kmz_preserved_as_unsupported(self):
        original, record = self.add_file("planta.kmz")
        review = self.register(record)
        self.assertEqual(review["category"], "UNSUPPORTED_FORMAT")
        self.assertEqual(review["extension"], ".kmz")
        self.assertTrue(original.exists())
        self.assertEqual(record["status"], "REVIEW_REQUIRED")

    def test_tampering_is_rejected(self):
        original, record = self.add_file("audio.mp3")
        self.register(record)
        original.write_bytes(b"changed contents")
        with self.assertRaises(CheckpointError):
            verify_extraction_lifecycle(
                self.checkpoint, self.downloads, self.extracted,
                authorized_ids=self.authorized,
            )

    def test_supported_document_cannot_be_marked_for_review(self):
        _, record = self.add_file("bases.pdf")
        with self.assertRaises(ManualReviewError):
            self.register(record)
        self.assertEqual(record["status"], "DOWNLOADED")

    def test_extension_routing(self):
        self.assertIsNone(review_category("BASES.PDF"))
        self.assertIsNone(review_category("budget.xlsx"))
        self.assertEqual(review_category("video.mp4"), "MEDIA")
        self.assertEqual(review_category("audio.wav"), "MEDIA")
        self.assertEqual(review_category("map.kmz"), "UNSUPPORTED_FORMAT")

    def test_mixed_tender_completes_and_skips_on_restart(self):
        _, document = self.add_file("bases.pdf")
        _, media = self.add_file("video.mp4")

        def finish_attachment(*args, **kwargs):
            record = args[3]
            if record is document:
                record["status"] = "COMPLETE"
            elif record is media:
                record["status"] = "REVIEW_REQUIRED"
                record["review"] = {
                    "category": "MEDIA",
                    "extension": ".mp4",
                    "reason": "Video or audio attachment; manual review required.",
                }

        with (
            patch("orquestador_produccion.process_attachment",
                  side_effect=finish_attachment) as processing,
            patch("orquestador_produccion.verify_extraction_lifecycle"),
        ):
            process_tender(
                None, None, self.checkpoint, self.checkpoint_path,
                self.tender, self.entry, authorized_ids=self.authorized,
            )
            self.assertEqual(self.entry["status"], "COMPLETE_WITH_REVIEW")
            self.assertEqual(processing.call_count, 2)

            process_tender(
                None, None, self.checkpoint, self.checkpoint_path,
                self.tender, self.entry, authorized_ids=self.authorized,
            )
            self.assertEqual(processing.call_count, 2)


if __name__ == "__main__":
    unittest.main()
