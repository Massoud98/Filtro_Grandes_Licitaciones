"""Five-tender batch planning and lifecycle-aware checkpoint loading."""

import hashlib
from pathlib import Path

from seleccion_incluidas import load_included_tenders
from checkpoint_descargas import (
    create_checkpoint,
    load_checkpoint,
    save_checkpoint,
    validate_checkpoint_structure,
    verify_extraction_lifecycle,
)


class BatchPlanningError(RuntimeError):
    pass


def plan_batches(classification_path, batch_size=5):
    """Return ordered batches containing only included tender IDs."""

    if batch_size != 5 or isinstance(batch_size, bool):
        raise BatchPlanningError("Production batch size must be five.")

    ids = load_included_tenders(classification_path)

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

    planned = plan_batches(classification_path)
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

    verify_extraction_lifecycle(
        checkpoint,
        Path(downloads_root),
        Path(extracted_root),
        authorized_ids=eligible_ids,
    )

    return checkpoint_path, checkpoint
