"""Offline recovery and verified-cleanup regression tests."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from checkpoint_descargas import create_checkpoint, save_checkpoint
from coordinador_produccion import extract_downloaded
from coordinador_limpieza import cleanup_extracted
from extractor_produccion import ProductionExtractionError


class AttachmentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.checkpoints = self.root / "checkpoints"

        for folder in (self.downloads, self.extracted, self.checkpoints):
            folder.mkdir()

        self.first = "100-1-LE26"
        self.second = "200-2-LE26"
        self.authorized = frozenset((self.first, self.second))

        self.classification = self.root / "classification.json"
        self.classification.write_text(
            json.dumps({
                "total": 2,
                "resumen": {"incluida": 2},
                "resultados": [
                    {"id": item, "estado": "incluida"}
                    for item in (self.first, self.second)
                ],
            }),
            encoding="utf-8",
        )

        self.checkpoint = create_checkpoint(
            [self.first], self.classification
        )
        self.checkpoint_path = self.checkpoints / "lote_0001.json"

        self.original_dir = self.downloads / self.first
        self.original_dir.mkdir()
        self.original = self.original_dir / "bases.pdf"

        original_bytes = b"Synthetic original attachment for offline tests."
        self.original.write_bytes(original_bytes)

        self.record = {
            "control_id": "attachment_1",
            "filename": "bases.pdf",
            "size_bytes": len(original_bytes),
            "sha256": hashlib.sha256(original_bytes).hexdigest(),
            "status": "DOWNLOADED",
        }

        self.checkpoint["licitaciones"][self.first]["attachments"].append(
            self.record
        )
        save_checkpoint(self.checkpoint_path, self.checkpoint)

        self.output = self.extracted / self.first / "bases"

    def publish_extraction(self):
        self.output.mkdir(parents=True, exist_ok=True)
        text_bytes = b"Synthetic extracted text for verification."

        (self.output / "contenido.txt").write_bytes(text_bytes)

        metadata = {
            "status": "COMPLETE",
            "tender_id": self.first,
            "control_id": self.record["control_id"],
            "source_filename": self.record["filename"],
            "source_size_bytes": self.record["size_bytes"],
            "source_sha256": self.record["sha256"],
            "text_sha256": hashlib.sha256(text_bytes).hexdigest(),
            "extraction": {"format": "pdf", "method": "synthetic"},
        }

        (self.output / "contenido.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )

    def cleanup(self):
        return cleanup_extracted(
            self.checkpoint,
            self.checkpoint_path,
            self.downloads,
            self.extracted,
            self.first,
            self.record,
            authorized_ids=self.authorized,
        )

    def test_recover_extraction_before_checkpoint_update(self):
        self.publish_extraction()

        result = extract_downloaded(
            self.checkpoint,
            self.checkpoint_path,
            self.downloads,
            self.extracted,
            self.first,
            self.record,
            self.root,
            None,
            None,
            authorized_ids=self.authorized,
        )

        self.assertEqual(result, self.output)
        self.assertEqual(self.record["status"], "EXTRACTED")
        self.assertTrue(self.original.exists())

    def test_cleanup_from_extracted_state(self):
        self.publish_extraction()
        self.record["status"] = "EXTRACTED"
        save_checkpoint(self.checkpoint_path, self.checkpoint)

        self.assertTrue(self.cleanup())
        self.assertEqual(self.record["status"], "COMPLETE")
        self.assertFalse(self.original.exists())
        self.assertTrue(self.output.is_dir())

    def test_resume_cleanup_before_deletion(self):
        self.publish_extraction()
        self.record["status"] = "CLEANUP_PENDING"
        save_checkpoint(self.checkpoint_path, self.checkpoint)

        self.assertTrue(self.cleanup())
        self.assertEqual(self.record["status"], "COMPLETE")
        self.assertFalse(self.original.exists())

    def test_resume_cleanup_after_deletion(self):
        self.publish_extraction()
        self.record["status"] = "CLEANUP_PENDING"
        self.original.unlink()
        save_checkpoint(self.checkpoint_path, self.checkpoint)

        self.assertTrue(self.cleanup())
        self.assertEqual(self.record["status"], "COMPLETE")

    def test_corrupted_extraction_preserves_original(self):
        self.publish_extraction()
        self.record["status"] = "EXTRACTED"
        (self.output / "contenido.txt").write_text(
            "CORRUPTED", encoding="utf-8"
        )

        with self.assertRaises(ProductionExtractionError):
            self.cleanup()

        self.assertTrue(self.original.exists())
        self.assertEqual(self.record["status"], "EXTRACTED")

    def test_other_authorized_batch_directory_is_preserved(self):
        self.publish_extraction()
        self.record["status"] = "EXTRACTED"

        other = self.extracted / self.second
        other.mkdir()

        self.assertTrue(self.cleanup())
        self.assertTrue(other.is_dir())


if __name__ == "__main__":
    unittest.main()