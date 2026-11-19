"""Verified per-attachment cleanup with resumable checkpoints."""

import os
from pathlib import Path

from checkpoint_descargas import (
    extraction_folder_name,
    save_checkpoint,
    validate_checkpoint_structure,
    verify_attachment,
    verify_extraction_lifecycle,
)
from extractor_produccion import verify_extracted
from mp_windows_cleanup import cleanup_verified


class CleanupCoordinatorError(RuntimeError):
    pass


def cleanup_extracted(
    checkpoint,
    checkpoint_path,
    downloads_root,
    extracted_root,
    tender_id,
    record,
    delete_function=None,
    *,
    authorized_ids=None,
):
    """Persist cleanup intent before deleting a verified original."""

    if delete_function is None:
        delete_function = cleanup_verified

    validate_checkpoint_structure(checkpoint)

    if tender_id not in checkpoint["ids"]:
        raise CleanupCoordinatorError("Unauthorized tender.")

    entry = checkpoint["licitaciones"][tender_id]

    if not any(item is record for item in entry["attachments"]):
        raise CleanupCoordinatorError("Attachment identity mismatch.")

    if record["status"] not in {"EXTRACTED", "CLEANUP_PENDING"}:
        raise CleanupCoordinatorError("Attachment not ready for cleanup.")

    downloads_root = Path(downloads_root)
    extracted_root = Path(extracted_root)

    original_dir = downloads_root / tender_id
    original = original_dir / record["filename"]
    output = extracted_root / tender_id / extraction_folder_name(record["filename"])

    verify_extracted(output, record, tender_id)

    verify_extraction_lifecycle(
        checkpoint, downloads_root, extracted_root,
        authorized_ids=authorized_ids,
    )

    if record["status"] == "EXTRACTED":
        if not verify_attachment(
            {**record, "status": "DOWNLOADED"},
            original_dir,
        ):
            raise CleanupCoordinatorError("Original verification failed.")

        record["status"] = "CLEANUP_PENDING"

        try:
            save_checkpoint(checkpoint_path, checkpoint)
        except Exception:
            record["status"] = "EXTRACTED"
            raise

    if original.is_symlink():
        raise CleanupCoordinatorError("Linked original forbidden.")

    if original.exists():
        if not original.is_file():
            raise CleanupCoordinatorError("Unsafe original.")

        if not verify_attachment(
            {**record, "status": "DOWNLOADED"},
            original_dir,
        ):
            raise CleanupCoordinatorError("Original changed before deletion.")

        file_identity = original.stat()
        work_identity = original_dir.stat()

        delete_function(
            original,
            original_dir,
            file_identity,
            work_identity,
            record["sha256"].lower(),
        )

    if os.path.lexists(original):
        raise CleanupCoordinatorError("Original still exists.")

    verify_extracted(output, record, tender_id)

    record["status"] = "COMPLETE"

    try:
        verify_extraction_lifecycle(
            checkpoint, downloads_root, extracted_root,
            authorized_ids=authorized_ids,
        )
        save_checkpoint(checkpoint_path, checkpoint)
    except Exception:
        record["status"] = "CLEANUP_PENDING"
        raise

    return True
