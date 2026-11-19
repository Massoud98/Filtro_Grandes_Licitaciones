"""Conservative checkpoint management for attachment downloads."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class CheckpointError(RuntimeError):
    """Unsafe or inconsistent download checkpoint."""


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    size = 0

    with Path(path).open("rb") as stream:
        for chunk in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)
            size += len(chunk)

    return size, digest.hexdigest()


def create_checkpoint(ids, classification_path):
    if not ids or len(ids) != len(set(ids)):
        raise CheckpointError("Invalid eligible IDs.")

    source = Path(classification_path)

    if not source.is_file() or source.is_symlink():
        raise CheckpointError("Unsafe classification source.")

    _, source_hash = sha256_file(source)

    return {
        "schema_version": 1,
        "created_utc": timestamp(),
        "classification_sha256": source_hash,
        "ids": list(ids),
        "licitaciones": {
            tender_id: {
                "status": "PENDING",
                "discovered": None,
                "attachments": [],
                "errors": [],
            }
            for tender_id in ids
        },
    }


def save_checkpoint(path, data):
    destination = Path(path)

    if destination.is_symlink():
        raise CheckpointError("Checkpoint is a link.")

    if not destination.parent.is_dir():
        raise CheckpointError("Checkpoint directory missing.")

    temporary = destination.with_name(
        destination.name + ".tmp"
    )

    if temporary.exists() or temporary.is_symlink():
        raise CheckpointError("Unexpected temporary checkpoint.")

    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(
                data,
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, destination)

    finally:
        if temporary.exists():
            temporary.unlink()


def load_checkpoint(path, ids, classification_path):
    source = Path(path)

    if source.is_symlink() or not source.is_file():
        raise CheckpointError("Checkpoint missing or unsafe.")

    try:
        data = json.loads(
            source.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise CheckpointError("Invalid checkpoint JSON.") from exc

    expected = create_checkpoint(ids, classification_path)

    if data.get("schema_version") != 1:
        raise CheckpointError("Checkpoint schema mismatch.")

    if data.get("ids") != expected["ids"]:
        raise CheckpointError("Eligible IDs changed.")

    # The original classification fingerprint is retained as historical
    # metadata. Resume compatibility is established by the exact ordered
    # eligible batch IDs, validated above, not by unrelated JSON changes.

    entries = data.get("licitaciones")

    if not isinstance(entries, dict):
        raise CheckpointError("Invalid checkpoint entries.")

    if set(entries) != set(ids):
        raise CheckpointError("Checkpoint tender IDs mismatch.")

    return validate_checkpoint_structure(data)


def verify_attachment(record, folder):
    if record.get("status") != "DOWNLOADED":
        return False

    filename = record.get("filename")

    if not isinstance(filename, str):
        return False

    if (
        not filename
        or filename in (".", "..")
        or "/" in filename
        or "\\" in filename
        or ":" in filename
    ):
        return False

    target = Path(folder) / filename

    if target.is_symlink() or not target.is_file():
        return False

    size, digest = sha256_file(target)

    return (
        size > 0
        and size == record.get("size_bytes")
        and digest == record.get("sha256")
    )




TENDER_STATUSES = frozenset({
    "PENDING",
    "IN_PROGRESS",
    "COMPLETE",
    "COMPLETE_WITH_REVIEW",
    "PARTIAL",
    "ERROR",
    "BLOCKED",
})

ATTACHMENT_STATUSES = frozenset({
    "DOWNLOADED",
    "EXTRACTED",
    "CLEANUP_PENDING",
    "COMPLETE",
    "REVIEW_REQUIRED",
    "ERROR",
})


def extraction_folder_name(filename):
    """Return a stable Windows-safe extraction directory name."""
    validate_windows_filename(filename)
    stem = Path(filename).stem.rstrip(" .")
    if not stem or stem in (".", ".."):
        raise CheckpointError("Invalid extraction folder name.")
    return stem


def validate_windows_filename(filename):
    if not isinstance(filename, str) or not filename:
        raise CheckpointError("Invalid attachment filename.")

    if filename != filename.strip(" ."):
        raise CheckpointError("Unsafe filename ending.")

    if any(ord(character) < 32 for character in filename):
        raise CheckpointError("Control character in filename.")

    if any(character in filename for character in '<>:"/\\|?*'):
        raise CheckpointError("Invalid Windows filename.")

    if filename in (".", ".."):
        raise CheckpointError("Unsafe filename.")

    stem = filename.split(".", 1)[0].upper()

    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }

    if stem in reserved:
        raise CheckpointError(
            "Reserved Windows filename: " + filename
        )

    return filename


def validate_checkpoint_structure(data):
    if not isinstance(data, dict):
        raise CheckpointError("Invalid checkpoint root.")

    ids = data.get("ids")
    entries = data.get("licitaciones")

    if not isinstance(ids, list) or not ids:
        raise CheckpointError("Invalid checkpoint IDs.")

    if not all(
        isinstance(item, str)
        and __import__("re").fullmatch(
            r"[0-9]+-[0-9]+-[A-Za-z0-9]+",
            item,
        )
        for item in ids
    ):
        raise CheckpointError("Malformed tender ID.")

    if len(ids) != len(set(ids)):
        raise CheckpointError("Duplicate tender IDs.")

    if not isinstance(entries, dict) or set(entries) != set(ids):
        raise CheckpointError("Checkpoint tender mismatch.")

    for tender_id in ids:
        entry = entries[tender_id]

        if not isinstance(entry, dict):
            raise CheckpointError("Invalid tender entry.")

        if entry.get("status") not in TENDER_STATUSES:
            raise CheckpointError(
                "Unknown tender status: " + tender_id
            )

        discovered = entry.get("discovered")

        if discovered is not None and (
            isinstance(discovered, bool)
            or not isinstance(discovered, int)
            or discovered < 0
        ):
            raise CheckpointError("Invalid discovered count.")

        records = entry.get("attachments")

        if not isinstance(records, list):
            raise CheckpointError("Invalid attachment list.")

        if not isinstance(entry.get("errors"), list):
            raise CheckpointError("Invalid tender errors.")

        names = set()
        controls = set()

        for record in records:
            if not isinstance(record, dict):
                raise CheckpointError("Invalid attachment record.")

            status = record.get("status")

            if status not in ATTACHMENT_STATUSES:
                raise CheckpointError(
                    "Unknown attachment status."
                )

            control_id = record.get("control_id")

            if control_id is not None:
                if not isinstance(control_id, str) or not control_id:
                    raise CheckpointError("Invalid control ID.")

                if status in {
                    "DOWNLOADED",
                    "EXTRACTED",
                    "CLEANUP_PENDING",
                    "COMPLETE",
                    "REVIEW_REQUIRED",
                }:
                    if control_id in controls:
                        raise CheckpointError("Duplicate control ID.")
                    controls.add(control_id)

            if status in {
                "DOWNLOADED",
                "EXTRACTED",
                "CLEANUP_PENDING",
                "COMPLETE",
                "REVIEW_REQUIRED",
            }:
                filename = validate_windows_filename(
                    record.get("filename")
                )

                normalized = filename.casefold()

                if normalized in names:
                    raise CheckpointError(
                        "Duplicate attachment filename."
                    )

                names.add(normalized)

                if status == "REVIEW_REQUIRED":
                    review = record.get("review")
                    if (
                        not isinstance(review, dict)
                        or review.get("category") not in {
                            "MEDIA", "UNSUPPORTED_FORMAT"
                        }
                        or not isinstance(review.get("reason"), str)
                        or not review["reason"].strip()
                        or review.get("extension") != Path(filename).suffix.lower()
                    ):
                        raise CheckpointError("Invalid manual review metadata.")

                size = record.get("size_bytes")
                digest = record.get("sha256")

                if (
                    isinstance(size, bool)
                    or not isinstance(size, int)
                    or size <= 0
                ):
                    raise CheckpointError(
                        "Invalid attachment size."
                    )

                if (
                    not isinstance(digest, str)
                    or __import__("re").fullmatch(
                        r"[0-9a-fA-F]{64}",
                        digest,
                    ) is None
                ):
                    raise CheckpointError(
                        "Invalid attachment SHA256."
                    )

    return data


def verify_all_downloads(data, downloads_root):
    """Verify recorded files and reject all untracked filesystem entries."""

    validate_checkpoint_structure(data)

    root = Path(downloads_root)

    if root.is_symlink() or not root.is_dir():
        raise CheckpointError("Unsafe downloads directory.")

    ids = data.get("ids")
    entries = data.get("licitaciones")

    if (
        not isinstance(ids, list)
        or not isinstance(entries, dict)
        or len(ids) != len(set(ids))
        or set(entries) != set(ids)
    ):
        raise CheckpointError("Invalid checkpoint structure.")

    expected_folders = set(ids)

    for item in root.iterdir():
        if item.is_symlink():
            raise CheckpointError(
                "Linked entry in downloads directory."
            )

        if item.name not in expected_folders:
            raise CheckpointError(
                "Unexpected download directory entry: "
                + item.name
            )

        if not item.is_dir():
            raise CheckpointError(
                "Expected tender directory: " + item.name
            )

    for tender_id in ids:
        entry = entries[tender_id]

        if not isinstance(entry, dict):
            raise CheckpointError("Invalid tender entry.")

        records = entry.get("attachments")

        if not isinstance(records, list):
            raise CheckpointError("Invalid attachment records.")

        folder = root / tender_id

        if folder.is_symlink():
            raise CheckpointError("Linked tender directory.")

        if folder.exists() and not folder.is_dir():
            raise CheckpointError("Unsafe tender directory.")

        recorded_names = set()
        control_ids = set()

        for record in records:
            if not isinstance(record, dict):
                raise CheckpointError("Invalid attachment record.")

            if record.get("status") != "DOWNLOADED":
                continue

            filename = record.get("filename")
            control_id = record.get("control_id")

            if (
                not isinstance(filename, str)
                or not filename
                or filename in (".", "..")
                or "/" in filename
                or "\\" in filename
                or ":" in filename
            ):
                raise CheckpointError("Unsafe attachment filename.")

            if filename.casefold() in recorded_names:
                raise CheckpointError(
                    "Duplicate recorded filename."
                )

            recorded_names.add(filename.casefold())

            if control_id is not None:
                if (
                    not isinstance(control_id, str)
                    or control_id in control_ids
                ):
                    raise CheckpointError(
                        "Duplicate or invalid control ID."
                    )

                control_ids.add(control_id)

            if not verify_attachment(record, folder):
                raise CheckpointError(
                    "Missing or changed attachment: "
                    + tender_id + "/" + filename
                )

        if folder.is_dir():
            for item in folder.iterdir():
                if item.is_symlink() or not item.is_file():
                    raise CheckpointError(
                        "Unexpected filesystem entry: "
                        + str(item)
                    )

                if item.name.casefold() not in recorded_names:
                    raise CheckpointError(
                        "Untracked attachment: " + str(item)
                    )

def verify_extraction_lifecycle(data, downloads_root, extracted_root, *, authorized_ids=None):
    """Verify originals and extracted outputs across processing states."""
    import hashlib
    import json
    import re

    validate_checkpoint_structure(data)

    if authorized_ids is None:
        allowed_ids = set(data["ids"])
    else:
        if (
            not isinstance(authorized_ids, (set, frozenset))
            or not authorized_ids
            or not set(data["ids"]).issubset(authorized_ids)
            or not all(
                isinstance(item, str)
                and re.fullmatch(
                    r"[0-9]+-[0-9]+-[A-Za-z0-9]+", item
                ) is not None
                for item in authorized_ids
            )
        ):
            raise CheckpointError("Invalid authorized tender IDs.")

        allowed_ids = set(authorized_ids)

    downloads = Path(downloads_root)
    extracted = Path(extracted_root)

    for root in (downloads, extracted):
        if root.is_symlink() or not root.is_dir():
            raise CheckpointError("Unsafe attachment root.")

        for item in root.iterdir():
            if item.is_symlink() or not item.is_dir():
                raise CheckpointError("Unsafe root entry.")
            if item.name not in allowed_ids:
                raise CheckpointError("Unexpected tender directory.")

    processed = {
        "DOWNLOADED", "EXTRACTED", "CLEANUP_PENDING", "COMPLETE",
        "REVIEW_REQUIRED"
    }

    for tender_id in data["ids"]:
        entry = data["licitaciones"][tender_id]
        original_dir = downloads / tender_id
        extracted_dir = extracted / tender_id

        for folder in (original_dir, extracted_dir):
            if folder.is_symlink():
                raise CheckpointError("Linked tender directory.")
            if folder.exists() and not folder.is_dir():
                raise CheckpointError("Unsafe tender directory.")

        expected_originals = set()
        expected_extractions = set()

        seen_extraction_names = set()

        for record in entry["attachments"]:
            filename = validate_windows_filename(record["filename"])
            folder_name = extraction_folder_name(filename)

            if (
                not folder_name
                or folder_name in (".", "..")
                or folder_name.casefold() in seen_extraction_names
            ):
                raise CheckpointError(
                    "Duplicate or invalid extraction folder name."
                )

            seen_extraction_names.add(folder_name.casefold())

            status = record["status"]

            if status not in processed:
                continue

            control = record.get("control_id")

            if not isinstance(control, str) or re.fullmatch(
                r"[A-Za-z0-9_-]+", control
            ) is None:
                raise CheckpointError("Invalid attachment control ID.")

            original = original_dir / filename
            output = extracted_dir / folder_name

            if status != "REVIEW_REQUIRED":
                expected_extractions.add(folder_name.casefold())

            if original.is_symlink():
                raise CheckpointError("Linked original.")

            original_exists = original.is_file()

            if status in {"DOWNLOADED", "EXTRACTED", "REVIEW_REQUIRED"}:
                if not verify_attachment(
                    {**record, "status": "DOWNLOADED"},
                    original_dir,
                ):
                    raise CheckpointError("Original verification failed.")
                expected_originals.add(filename.casefold())

            elif status == "CLEANUP_PENDING" and original_exists:
                if not verify_attachment(
                    {**record, "status": "DOWNLOADED"},
                    original_dir,
                ):
                    raise CheckpointError("Cleanup original changed.")
                expected_originals.add(filename.casefold())

            elif status == "COMPLETE" and original.exists():
                raise CheckpointError("Completed original still exists.")

            if status in {"DOWNLOADED", "REVIEW_REQUIRED"}:
                if output.exists() or output.is_symlink():
                    raise CheckpointError("Unexpected extraction output.")
                continue

            if output.is_symlink() or not output.is_dir():
                raise CheckpointError("Missing extraction directory.")

            files = list(output.iterdir())

            if {item.name for item in files} != {
                "contenido.json", "contenido.txt"
            }:
                raise CheckpointError("Invalid extraction inventory.")

            if any(item.is_symlink() or not item.is_file() for item in files):
                raise CheckpointError("Unsafe extraction output.")

            try:
                metadata = json.loads(
                    (output / "contenido.json").read_text(encoding="utf-8")
                )
                text_bytes = (output / "contenido.txt").read_bytes()
                text = text_bytes.decode("utf-8")
            except (OSError, UnicodeError, ValueError) as exc:
                raise CheckpointError("Unreadable extraction output.") from exc

            if not text.strip():
                raise CheckpointError("Empty extraction output.")

            digest = hashlib.sha256(text_bytes).hexdigest()

            if (
                not isinstance(metadata, dict)
                or metadata.get("status") != "COMPLETE"
                or metadata.get("tender_id") != tender_id
                or metadata.get("control_id") != control
                or metadata.get("source_filename") != filename
                or metadata.get("source_size_bytes") != record["size_bytes"]
                or str(metadata.get("source_sha256", "")).lower()
                    != record["sha256"].lower()
                or metadata.get("text_sha256") != digest
                or not isinstance(metadata.get("extraction"), dict)
            ):
                raise CheckpointError("Extraction metadata mismatch.")

        if original_dir.is_dir():
            for item in original_dir.iterdir():
                if item.is_symlink() or not item.is_file():
                    raise CheckpointError("Unsafe original directory entry.")
                if item.name.casefold() not in expected_originals:
                    raise CheckpointError("Untracked original attachment.")

        if extracted_dir.is_dir():
            for item in extracted_dir.iterdir():
                if item.is_symlink() or not item.is_dir():
                    raise CheckpointError("Unsafe extraction directory entry.")
                if item.name.casefold() not in expected_extractions:
                    raise CheckpointError("Untracked extraction directory.")

    return True
