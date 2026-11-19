"""Preserve unsupported attachments for verified manual review."""

from pathlib import Path

from checkpoint_descargas import (
    save_checkpoint,
    validate_checkpoint_structure,
    verify_attachment,
    verify_extraction_lifecycle,
)


MEDIA_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mpeg", ".mpg",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma",
})

EXTRACTABLE_EXTENSIONS = frozenset({
    ".pdf", ".doc", ".docx", ".xlsx",
})


class ManualReviewError(RuntimeError):
    """Unsafe or inconsistent manual-review transition."""


def review_category(filename):
    extension = Path(filename).suffix.lower()

    if extension in EXTRACTABLE_EXTENSIONS:
        return None

    if extension in MEDIA_EXTENSIONS:
        return "MEDIA"

    return "UNSUPPORTED_FORMAT"


def register_manual_review(
    checkpoint,
    checkpoint_path,
    downloads_root,
    extracted_root,
    tender_id,
    record,
    *,
    authorized_ids=None,
):
    """Verify and retain an unsupported original, then persist review state."""

    validate_checkpoint_structure(checkpoint)

    if tender_id not in checkpoint["ids"]:
        raise ManualReviewError("Unauthorized tender.")

    entry = checkpoint["licitaciones"][tender_id]

    if not any(item is record for item in entry["attachments"]):
        raise ManualReviewError("Attachment identity mismatch.")

    if record["status"] != "DOWNLOADED":
        raise ManualReviewError("Attachment is not awaiting processing.")

    category = review_category(record["filename"])

    if category is None:
        raise ManualReviewError("Extractable format cannot enter manual review.")

    downloads_root = Path(downloads_root)
    extracted_root = Path(extracted_root)

    original_dir = downloads_root / tender_id

    if not verify_attachment(record, original_dir):
        raise ManualReviewError("Original verification failed.")

    extension = Path(record["filename"]).suffix.lower()

    if category == "MEDIA":
        reason = "Video or audio attachment; manual review required."
    else:
        reason = "Unsupported attachment format; manual review required."

    review = {
        "category": category,
        "extension": extension,
        "reason": reason,
    }

    previous_status = record["status"]
    record["status"] = "REVIEW_REQUIRED"
    record["review"] = review

    try:
        verify_extraction_lifecycle(
            checkpoint,
            downloads_root,
            extracted_root,
            authorized_ids=authorized_ids,
        )
        save_checkpoint(checkpoint_path, checkpoint)
    except Exception:
        record["status"] = previous_status
        record.pop("review", None)
        raise

    return review
