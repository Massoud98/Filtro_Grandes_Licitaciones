"""Five-tender batch planning and lifecycle-aware checkpoint loading."""

import hashlib
import json
import re
from pathlib import Path

from seleccion_incluidas import load_included_tenders
from checkpoint_descargas import (
    CheckpointError,
    extraction_folder_name,
    verify_attachment,
    create_checkpoint,
    load_checkpoint,
    save_checkpoint,
    validate_checkpoint_structure,
    verify_extraction_lifecycle,
)


class BatchPlanningError(RuntimeError):
    pass


def plan_batches(classification_path, batch_size=5, checkpoints_root=None):
    """Return ordered batches containing only included tender IDs."""

    if batch_size != 5 or isinstance(batch_size, bool):
        raise BatchPlanningError("Production batch size must be five.")

    ids = load_included_tenders(classification_path)
    if checkpoints_root is not None:
        root = Path(checkpoints_root)
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise BatchPlanningError("Unsafe checkpoint directory.")
        existing = []
        seen = set()
        if root.is_dir():
            paths = sorted(root.glob("lote_*.json"))
            for position, path in enumerate(paths, 1):
                if path.is_symlink() or not path.is_file():
                    raise BatchPlanningError("Unsafe checkpoint file.")
                if re.fullmatch(r"lote_[0-9]{4}\.json", path.name) is None:
                    raise BatchPlanningError("Invalid checkpoint filename.")
                if path.name != f"lote_{position:04d}.json":
                    raise BatchPlanningError("Nonconsecutive checkpoint numbers.")
                try:
                    checkpoint = json.loads(path.read_text(encoding="utf-8"))
                    validate_checkpoint_structure(checkpoint)
                except Exception as exc:
                    raise BatchPlanningError("Invalid existing checkpoint.") from exc
                batch_ids = checkpoint["ids"]
                if len(batch_ids) > batch_size or seen.intersection(batch_ids):
                    raise BatchPlanningError("Invalid or duplicate checkpoint membership.")
                if not set(batch_ids).issubset(set(ids)):
                    raise CheckpointError("Eligible IDs changed. Historical excluded tender requires reconciliation.")
                existing.append(batch_ids)
                seen.update(batch_ids)
        ids = [tender_id for tender_id in ids if tender_id not in seen]
        return existing + [
            ids[position:position + batch_size]
            for position in range(0, len(ids), batch_size)
        ]

    return [
        ids[position:position + batch_size]
        for position in range(0, len(ids), batch_size)
    ]


def batch_checkpoint_path(checkpoints_root, batch_number):
    """Return a stable, numbered checkpoint pathname."""

    if (
        isinstance(batch_number, bool)
        or not isinstance(batch_number, int)
        or batch_number < 1
    ):
        raise BatchPlanningError("Invalid batch number.")

    return Path(checkpoints_root) / f"lote_{batch_number:04d}.json"


def prepare_batch(
    classification_path,
    checkpoints_root,
    downloads_root,
    extracted_root,
    batch_number,
    ids,
    *,
    authorized_ids=None,
):
    """Load or initialize one batch without modifying attachment files."""

    if not ids or len(ids) > 5 or len(ids) != len(set(ids)):
        raise BatchPlanningError("Invalid batch membership.")

    planned = plan_batches(classification_path, checkpoints_root=checkpoints_root)
    eligible_ids = {tender_id for batch in planned for tender_id in batch}

    if authorized_ids is not None and (
        not isinstance(authorized_ids, (set, frozenset))
        or authorized_ids != eligible_ids
    ):
        raise BatchPlanningError("Authorized IDs differ from classification.")

    if batch_number < 1 or batch_number > len(planned):
        raise BatchPlanningError("Batch number outside classification.")

    if list(ids) != planned[batch_number - 1]:
        raise BatchPlanningError("Batch membership differs from classification.")

    checkpoints_root = Path(checkpoints_root)

    if checkpoints_root.is_symlink():
        raise BatchPlanningError("Unsafe checkpoint directory.")

    checkpoints_root.mkdir(parents=True, exist_ok=True)

    checkpoint_path = batch_checkpoint_path(
        checkpoints_root, batch_number
    )

    if checkpoint_path.is_symlink():
        raise BatchPlanningError("Unsafe checkpoint file.")

    if checkpoint_path.exists():
        checkpoint = load_checkpoint(
            checkpoint_path,
            list(ids),
            classification_path,
        )
    else:
        checkpoint = create_checkpoint(
            list(ids),
            classification_path,
        )

        validate_checkpoint_structure(checkpoint)

        save_checkpoint(checkpoint_path, checkpoint)

    # Recover an extraction published just before its checkpoint update.
    # Only known DOWNLOADED records qualify; all existing integrity checks
    # remain mandatory and unrelated directories are never accepted.
    from extractor_produccion import verify_extracted

    downloads_root = Path(downloads_root)
    extracted_root = Path(extracted_root)

    recovered = False
    for tender_id in checkpoint["ids"]:
        for record in checkpoint["licitaciones"][tender_id]["attachments"]:
            if record["status"] != "DOWNLOADED":
                continue

            output = (
                extracted_root / tender_id
                / extraction_folder_name(record["filename"])
            )
            if not output.exists() and not output.is_symlink():
                continue

            if not verify_attachment(record, downloads_root / tender_id):
                raise CheckpointError("Recovery original verification failed.")

            verify_extracted(output, record, tender_id)
            record["status"] = "EXTRACTED"
            recovered = True

    verify_extraction_lifecycle(
        checkpoint,
        downloads_root,
        extracted_root,
        authorized_ids=eligible_ids,
    )
    if recovered:
        save_checkpoint(checkpoint_path, checkpoint)

    return checkpoint_path, checkpoint
