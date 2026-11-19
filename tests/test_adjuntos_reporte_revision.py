"""Offline regression tests for daily manual-review reporting."""

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"
sys.path.insert(0, str(MODULES))

from checkpoint_descargas import create_checkpoint, save_checkpoint
from reporte_revision import (
    ManualReviewReportError,
    rebuild_manual_review_report,
)


class ManualReviewReportTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.daily = self.root / "2026-11-19"
        self.checkpoints = self.daily / "checkpoints"
        self.downloads = self.daily / "descargas"

        self.checkpoints.mkdir(parents=True)
        self.downloads.mkdir()

        self.report = self.daily / "revision_manual.csv"
        self.classification = self.root / "classification.json"
        self.classification.write_text("{}", encoding="utf-8")

    def add_checkpoint(self, batch, tender, files):
        checkpoint = create_checkpoint(
            [tender], self.classification
        )
        entry = checkpoint["licitaciones"][tender]
        folder = self.downloads / tender
        folder.mkdir(parents=True)

        for number, (filename, payload, mode) in enumerate(files, 1):
            original = folder / filename

            if mode != "missing":
                original.write_bytes(payload)

            record = {
                "control_id": f"attachment_{number}",
                "filename": filename,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "status": "REVIEW_REQUIRED",
                "review": {
                    "category": "MEDIA" if filename.endswith(".mp4")
                    else "UNSUPPORTED_FORMAT",
                    "extension": Path(filename).suffix.lower(),
                    "reason": "Offline manual review test.",
                },
            }
            entry["attachments"].append(record)

        entry["discovered"] = len(files)
        entry["status"] = "COMPLETE_WITH_REVIEW"

        save_checkpoint(
            self.checkpoints / f"lote_{batch:04d}.json",
            checkpoint,
        )

    def rows(self):
        with self.report.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_multiple_batches_and_integrity_statuses(self):
        self.add_checkpoint(1, "100-1-LE26", [
            ("video.mp4", b"valid media", "valid"),
            ("mapa.kmz", b"changed", "tampered"),
        ])

        self.add_checkpoint(2, "100-2-LE26", [
            ("missing.kmz", b"original", "missing"),
        ])

        (self.downloads / "100-1-LE26" / "mapa.kmz").write_bytes(
            b"tampered contents"
        )

        result = rebuild_manual_review_report(
            self.checkpoints, self.downloads, self.report
        )

        self.assertEqual(result["reviews"], 3)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(result["integrity_failed"], 1)

        statuses = {row["archivo"]: row["integrity_status"]
                    for row in self.rows()}

        self.assertEqual(statuses["video.mp4"], "VERIFIED")
        self.assertEqual(statuses["mapa.kmz"], "INTEGRITY_FAILED")
        self.assertEqual(statuses["missing.kmz"], "MISSING")

    def test_empty_report(self):
        result = rebuild_manual_review_report(
            self.checkpoints, self.downloads, self.report
        )
        self.assertEqual(result["reviews"], 0)
        self.assertEqual(len(self.rows()), 0)

    def test_report_replacement(self):
        self.report.write_text("old report", encoding="utf-8")
        self.add_checkpoint(1, "100-1-LE26", [
            ("video.mp4", b"valid", "valid"),
        ])

        rebuild_manual_review_report(
            self.checkpoints, self.downloads, self.report
        )

        self.assertNotEqual(
            self.report.read_text(encoding="utf-8"),
            "old report",
        )

    def test_duplicate_review_attachment_rejected(self):
        self.add_checkpoint(1, "100-1-LE26", [
            ("video.mp4", b"valid", "valid"),
        ])

        source = self.checkpoints / "lote_0001.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        duplicate = json.loads(json.dumps(data))
        duplicate["ids"] = ["100-1-LE26"]
        duplicate["licitaciones"]["100-1-LE26"]["attachments"][0][
            "control_id"
        ] = "attachment_1"

        save_checkpoint(self.checkpoints / "lote_0002.json", duplicate)

        with self.assertRaises(ManualReviewReportError):
            rebuild_manual_review_report(
                self.checkpoints, self.downloads, self.report
            )

    def test_corrupt_checkpoint_rejected(self):
        (self.checkpoints / "lote_0001.json").write_text(
            "{invalid", encoding="utf-8"
        )

        with self.assertRaises(ManualReviewReportError):
            rebuild_manual_review_report(
                self.checkpoints, self.downloads, self.report
            )


if __name__ == "__main__":
    unittest.main()
