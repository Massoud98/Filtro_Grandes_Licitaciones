"""Read-only validation of local Mercado Publico attachment manifests."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


MANIFEST_COLUMNS = (
    "licitacion",
    "filename",
    "url",
    "source_path",
    "source_origin_url",
)

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx"})


class AttachmentManifestError(ValueError):
    """Raised when an attachment manifest cannot be trusted."""


@dataclass(frozen=True)
class AttachmentRecord:
    licitacion: str
    filename: str
    url: str
    source_path: Path
    source_origin_url: str


def validate_manifest(manifest_path: str | Path) -> list[AttachmentRecord]:
    """Validate an existing local manifest without changing any files."""

    manifest = Path(manifest_path)

    if not manifest.is_file():
        raise AttachmentManifestError("Manifest does not exist.")

    records = []
    seen_paths = set()

    with manifest.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)

        if reader.fieldnames is None:
            raise AttachmentManifestError("Manifest has no header.")

        if tuple(reader.fieldnames) != MANIFEST_COLUMNS:
            raise AttachmentManifestError(
                "Manifest columns do not match the expected schema."
            )

        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise AttachmentManifestError(
                    f"Malformed CSV record at line {line_number}."
                )

            values = {
                key: (row[key] or "").strip()
                for key in MANIFEST_COLUMNS
            }

            if not values["licitacion"]:
                raise AttachmentManifestError(
                    f"Missing licitacion at line {line_number}."
                )

            if not values["filename"] or not values["source_path"]:
                raise AttachmentManifestError(
                    f"Missing file information at line {line_number}."
                )

            filename = values["filename"]

            if Path(filename).name != filename or "\\" in filename:
                raise AttachmentManifestError(
                    f"Invalid filename at line {line_number}."
                )

            if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise AttachmentManifestError(
                    f"Unsupported document type at line {line_number}."
                )

            source = Path(values["source_path"])

            if not source.is_absolute():
                raise AttachmentManifestError(
                    f"Source path must be absolute at line {line_number}."
                )

            if not source.is_file():
                raise AttachmentManifestError(
                    f"Source file missing at line {line_number}."
                )

            if source.name != filename:
                raise AttachmentManifestError(
                    f"Filename mismatch at line {line_number}."
                )

            identity = str(source.resolve()).casefold()

            if identity in seen_paths:
                raise AttachmentManifestError(
                    f"Duplicate source path at line {line_number}."
                )

            seen_paths.add(identity)

            records.append(
                AttachmentRecord(
                    licitacion=values["licitacion"],
                    filename=filename,
                    url=values["url"],
                    source_path=source,
                    source_origin_url=values["source_origin_url"],
                )
            )

    if not records:
        raise AttachmentManifestError("Manifest contains no attachments.")

    return records
def verify_attachment_integrity(
    manifest_path: str | Path,
    index_path: str | Path,
) -> list[AttachmentRecord]:
    """Verify local originals against previously recorded SHA256 hashes."""

    import hashlib
    import json
    import re

    records = validate_manifest(manifest_path)
    index_file = Path(index_path)

    if not index_file.is_file():
        raise AttachmentManifestError("Integrity index does not exist.")

    try:
        with index_file.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (OSError, ValueError) as exc:
        raise AttachmentManifestError(
            "Integrity index cannot be read."
        ) from exc

    if not isinstance(payload, dict):
        raise AttachmentManifestError("Invalid integrity index root.")

    documents = payload.get("documents")

    if not isinstance(documents, list):
        raise AttachmentManifestError("Invalid integrity document list.")

    def identity(licitacion, filename):
        return (licitacion.strip(), filename.strip())

    indexed = {}

    for document in documents:
        if not isinstance(document, dict):
            raise AttachmentManifestError("Invalid indexed document.")

        licitacion = document.get("licitacion")
        filename = document.get("filename")

        if not isinstance(licitacion, str) or not isinstance(filename, str):
            raise AttachmentManifestError("Invalid indexed identity.")

        key = identity(licitacion, filename)

        if not all(key):
            raise AttachmentManifestError("Empty indexed identity.")

        if key in indexed:
            raise AttachmentManifestError("Duplicate indexed identity.")

        indexed[key] = document

    manifest_keys = [
        identity(record.licitacion, record.filename)
        for record in records
    ]

    if len(set(manifest_keys)) != len(manifest_keys):
        raise AttachmentManifestError("Duplicate manifest identity.")

    if set(manifest_keys) != set(indexed):
        raise AttachmentManifestError(
            "Manifest and integrity index identities differ."
        )

    for record in records:
        document = indexed[identity(record.licitacion, record.filename)]

        expected_hash = document.get("sha256")
        expected_size = document.get("source_bytes")
        expected_path = document.get("source_path")

        if (
            not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) is None
        ):
            raise AttachmentManifestError("Invalid indexed SHA256.")

        if type(expected_size) is not int or expected_size < 0:
            raise AttachmentManifestError("Invalid indexed file size.")

        if not isinstance(expected_path, str):
            raise AttachmentManifestError("Invalid indexed source path.")

        if Path(expected_path) != record.source_path:
            raise AttachmentManifestError("Indexed source path mismatch.")

        if record.source_path.stat().st_size != expected_size:
            raise AttachmentManifestError("Attachment file size mismatch.")

        digest = hashlib.sha256()

        with record.source_path.open("rb") as stream:
            for chunk in iter(
                lambda: stream.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        if digest.hexdigest().lower() != expected_hash.lower():
            raise AttachmentManifestError("Attachment SHA256 mismatch.")

    return records