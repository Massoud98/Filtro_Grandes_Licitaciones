"""Checkpoint-driven extraction coordinator; cleanup disabled."""

from pathlib import Path

from checkpoint_descargas import (
    extraction_folder_name,
    save_checkpoint,
    validate_checkpoint_structure,
    verify_attachment,
    verify_extraction_lifecycle,
)
from extractor_produccion import extract_verified, verify_extracted


class ProductionCoordinatorError(RuntimeError):
    pass


def extract_downloaded(
    checkpoint,
    checkpoint_path,
    downloads_root,
    extracted_root,
    tender_id,
    record,
    project_root,
    tesseract,
    tessdata,
    *,
    authorized_ids=None,
):
    """Extract and checkpoint one verified downloaded attachment."""

    validate_checkpoint_structure(checkpoint)

    if tender_id not in checkpoint["ids"]:
        raise ProductionCoordinatorError("Tender not authorized.")

    entry = checkpoint["licitaciones"][tender_id]

    if record not in entry["attachments"]:
        raise ProductionCoordinatorError("Attachment not in checkpoint.")

    if record["status"] != "DOWNLOADED":
        raise ProductionCoordinatorError("Attachment not DOWNLOADED.")

    downloads_root = Path(downloads_root)
    extracted_root = Path(extracted_root)

    # Recover verified outputs published before checkpoint persistence.
    source = downloads_root / tender_id / record["filename"]
    existing_output = extracted_root / tender_id / extraction_folder_name(record["filename"])

    if existing_output.exists() or existing_output.is_symlink():
        if not verify_attachment(record, source.parent):
            raise ProductionCoordinatorError(
                "Original verification failed during recovery."
            )

        verify_extracted(existing_output, record, tender_id)

        record["status"] = "EXTRACTED"

        try:
            verify_extraction_lifecycle(
                checkpoint,
                downloads_root,
                extracted_root,
                authorized_ids=authorized_ids,
            )
            save_checkpoint(checkpoint_path, checkpoint)
        except Exception:
            record["status"] = "DOWNLOADED"
            raise

        return existing_output

    verify_extraction_lifecycle(
        checkpoint,
        downloads_root,
        extracted_root,
        authorized_ids=authorized_ids,
    )

    source = downloads_root / tender_id / record["filename"]

    if not verify_attachment(record, source.parent):
        raise ProductionCoordinatorError("Original verification failed.")

    output = extract_verified(
        source,
        extracted_root,
        tender_id,
        record,
        project_root,
        tesseract,
        tessdata,
    )

    verify_extracted(output, record, tender_id)

    record["status"] = "EXTRACTED"

    try:
        verify_extraction_lifecycle(
            checkpoint,
            downloads_root,
            extracted_root,
            authorized_ids=authorized_ids,
        )
        save_checkpoint(checkpoint_path, checkpoint)
    except Exception:
        record["status"] = "DOWNLOADED"
        raise

    return output
