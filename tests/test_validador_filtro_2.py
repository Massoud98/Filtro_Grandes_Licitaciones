"""Offline tests for Filter 2 readiness validation."""

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

from validador_filtro_2 import validate_tender_readiness


class TestFilter2Readiness(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.downloads.mkdir()
        self.extracted.mkdir()
        self.tender_id = "12345-67-LE26"

        self.record = {
            "control_id": "DWNL_test_1",
            "status": "COMPLETE",
            "filename": "bases.pdf",
            "size_bytes": 100,
            "sha256": "a" * 64,
        }

        self.checkpoint = {
            "schema_version": 1,
            "created_utc": "2026-11-20T12:00:00+00:00",
            "classification_sha256": "b" * 64,
            "ids": [self.tender_id],
            "licitaciones": {
                self.tender_id: {
                    "status": "COMPLETE",
                    "discovered": 1,
                    "attachments": [self.record],
                    "errors": [],
                }
            },
        }

    def create_valid_extraction(self):
        folder = self.extracted / self.tender_id / "bases"
        folder.mkdir(parents=True)

        text = b"Documento de licitacion de prueba."
        metadata = {
            "status": "COMPLETE",
            "tender_id": self.tender_id,
            "control_id": self.record["control_id"],
            "source_filename": self.record["filename"],
            "source_size_bytes": self.record["size_bytes"],
            "source_sha256": self.record["sha256"],
            "text_sha256": hashlib.sha256(text).hexdigest(),
            "extraction": {
                "format": "pdf",
                "pages": [],
            },
        }

        (folder / "contenido.txt").write_bytes(text)
        (folder / "contenido.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        return folder

    def evaluate(self):
        return validate_tender_readiness(
            self.checkpoint,
            self.tender_id,
            self.downloads,
            self.extracted,
        )

    def test_complete_verified_tender(self):
        self.create_valid_extraction()
        result = self.evaluate()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["documents"]), 1)

    def test_pending_tender(self):
        entry = self.checkpoint["licitaciones"][self.tender_id]
        entry["status"] = "PENDING"
        entry["discovered"] = None
        entry["attachments"] = []
        self.assertEqual(self.evaluate()["status"], "PENDING")

    def test_manual_review_tender(self):
        entry = self.checkpoint["licitaciones"][self.tender_id]
        entry["status"] = "COMPLETE_WITH_REVIEW"
        self.assertEqual(self.evaluate()["status"], "MANUAL_REVIEW")

    def test_incomplete_inventory(self):
        entry = self.checkpoint["licitaciones"][self.tender_id]
        entry["discovered"] = 2
        self.assertEqual(self.evaluate()["status"], "INVALID")

    def test_missing_extraction(self):
        self.assertEqual(self.evaluate()["status"], "INVALID")

    def test_corrupted_text(self):
        folder = self.create_valid_extraction()
        (folder / "contenido.txt").write_text(
            "Contenido modificado.", encoding="utf-8"
        )
        self.assertEqual(self.evaluate()["status"], "INVALID")

    def test_unexpected_extraction_file(self):
        folder = self.create_valid_extraction()
        (folder / "archivo_extra.txt").write_text(
            "unexpected", encoding="utf-8"
        )
        self.assertEqual(self.evaluate()["status"], "INVALID")

    def test_unknown_tender(self):
        result = validate_tender_readiness(
            self.checkpoint,
            "99999-99-LE26",
            self.downloads,
            self.extracted,
        )
        self.assertEqual(result["status"], "INVALID")

    def test_other_tender_corruption_does_not_block_ready(self):
        self.create_valid_extraction()

        other_id = "98765-43-LE26"
        other_record = {
            "control_id": "DWNL_other_1",
            "status": "COMPLETE",
            "filename": "otras_bases.pdf",
            "size_bytes": 100,
            "sha256": "c" * 64,
        }

        self.checkpoint["ids"].append(other_id)
        self.checkpoint["licitaciones"][other_id] = {
            "status": "COMPLETE",
            "discovered": 1,
            "attachments": [other_record],
            "errors": [],
        }

        other_folder = self.extracted / other_id / "otras_bases"
        other_folder.mkdir(parents=True)

        (other_folder / "contenido.txt").write_text(
            "Documento alterado.", encoding="utf-8"
        )
        (other_folder / "contenido.json").write_text(
            "{}", encoding="utf-8"
        )

        result = self.evaluate()
        self.assertEqual(result["status"], "READY")
    def test_shared_workspace_authorization(self):
        self.create_valid_extraction()

        other_id = "98765-43-LE26"
        (self.extracted / other_id).mkdir()

        result = validate_tender_readiness(
            self.checkpoint,
            self.tender_id,
            self.downloads,
            self.extracted,
            authorized_ids={self.tender_id, other_id},
        )

        self.assertEqual(result["status"], "READY")
    def test_lifecycle_verifier_invoked(self):
        self.create_valid_extraction()
        with patch(
            "validador_filtro_2.verify_extraction_lifecycle",
            side_effect=RuntimeError("Integrity failure"),
        ):
            result = self.evaluate()
        self.assertEqual(result["status"], "INVALID")


if __name__ == "__main__":
    unittest.main()