"""Unit tests for the read-only attachment manifest validator."""

import csv
import tempfile
import unittest
from pathlib import Path

from aplicacion.servicios.descargador_adjuntos import (
    AttachmentManifestError,
    MANIFEST_COLUMNS,
    validate_manifest,
    verify_attachment_integrity,
)


class AttachmentManifestTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "attachments.csv"

    def create_manifest(self, rows, columns=MANIFEST_COLUMNS):
        with self.manifest.open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)

    def record(self, filename="document.pdf"):
        source = self.root / filename
        source.write_bytes(b"test fixture")

        return {
            "licitacion": "TEST-001",
            "filename": filename,
            "url": "",
            "source_path": str(source),
            "source_origin_url": "",
        }

    def test_valid_pdf(self):
        self.create_manifest([self.record()])
        records = validate_manifest(self.manifest)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].licitacion, "TEST-001")

    def test_valid_docx(self):
        self.create_manifest([self.record("document.docx")])
        records = validate_manifest(self.manifest)
        self.assertEqual(records[0].filename, "document.docx")

    def test_missing_manifest(self):
        with self.assertRaises(AttachmentManifestError):
            validate_manifest(self.root / "missing.csv")

    def test_invalid_columns(self):
        self.create_manifest(
            [self.record()],
            columns=("licitacion", "filename", "source_path"),
        )
        with self.assertRaises(AttachmentManifestError):
            validate_manifest(self.manifest)

    def test_missing_source(self):
        row = self.record()
        Path(row["source_path"]).unlink()
        self.create_manifest([row])
        with self.assertRaises(AttachmentManifestError):
            validate_manifest(self.manifest)

    def test_unsupported_extension(self):
        self.create_manifest([self.record("document.exe")])
        with self.assertRaises(AttachmentManifestError):
            validate_manifest(self.manifest)

    def test_duplicate_source(self):
        row = self.record()
        self.create_manifest([row, row])
        with self.assertRaises(AttachmentManifestError):
            validate_manifest(self.manifest)


class AttachmentIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "attachments.csv"
        self.index = self.root / "documents.json"
        self.source = self.root / "document.pdf"
        self.source.write_bytes(b"original fixture")

    def prepare(self, **changes):
        import hashlib
        import json

        row = {
            "licitacion": "TEST-001",
            "filename": self.source.name,
            "url": "",
            "source_path": str(self.source),
            "source_origin_url": "",
        }

        with self.manifest.open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.DictWriter(
                stream, fieldnames=MANIFEST_COLUMNS
            )
            writer.writeheader()
            writer.writerow(row)

        document = {
            "licitacion": "TEST-001",
            "filename": self.source.name,
            "source_path": str(self.source),
            "source_bytes": self.source.stat().st_size,
            "sha256": hashlib.sha256(
                self.source.read_bytes()
            ).hexdigest(),
        }

        document.update(changes)

        with self.index.open("w", encoding="utf-8") as stream:
            json.dump({"documents": [document]}, stream)

        return document

    def test_valid_integrity(self):
        self.prepare()
        records = verify_attachment_integrity(
            self.manifest, self.index
        )
        self.assertEqual(len(records), 1)

    def test_altered_content(self):
        self.prepare()
        self.source.write_bytes(b"modified fixture")
        with self.assertRaises(AttachmentManifestError):
            verify_attachment_integrity(self.manifest, self.index)

    def test_invalid_hash(self):
        self.prepare(sha256="invalid")
        with self.assertRaises(AttachmentManifestError):
            verify_attachment_integrity(self.manifest, self.index)

    def test_missing_index_record(self):
        self.prepare(licitacion="OTHER-001")
        with self.assertRaises(AttachmentManifestError):
            verify_attachment_integrity(self.manifest, self.index)

    def test_duplicate_index_identity(self):
        import json

        document = self.prepare()

        with self.index.open("w", encoding="utf-8") as stream:
            json.dump(
                {"documents": [document, document]},
                stream,
            )

        with self.assertRaises(AttachmentManifestError):
            verify_attachment_integrity(self.manifest, self.index)

    def test_mismatched_path(self):
        self.prepare(source_path=str(self.root / "other.pdf"))
        with self.assertRaises(AttachmentManifestError):
            verify_attachment_integrity(self.manifest, self.index)

    def test_incorrect_file_size(self):
        self.prepare(source_bytes=99999)
        with self.assertRaises(AttachmentManifestError):
            verify_attachment_integrity(self.manifest, self.index)

    def test_invalid_index_structure(self):
        import json

        self.prepare()

        with self.index.open("w", encoding="utf-8") as stream:
            json.dump({"documents": "invalid"}, stream)

        with self.assertRaises(AttachmentManifestError):
            verify_attachment_integrity(self.manifest, self.index)

if __name__ == "__main__":
    unittest.main()