"""Read-only readiness validation for Jessika's second filter."""

from __future__ import annotations

from pathlib import Path

from checkpoint_descargas import (
    extraction_folder_name,
    validate_checkpoint_structure,
    verify_extraction_lifecycle,
)
from extractor_produccion import verify_extracted


def validate_tender_readiness(
    checkpoint: dict,
    tender_id: str,
    downloads_root: str | Path,
    extracted_root: str | Path,
    *,
    authorized_ids: set[str] | frozenset[str] | None = None,
) -> dict:
    """Return readiness without modifying checkpoints or extracted files."""

    result = {
        "tender_id": tender_id,
        "status": "INVALID",
        "reason": None,
        "documents": [],
    }

    try:
        validate_checkpoint_structure(checkpoint)

        if tender_id not in checkpoint["licitaciones"]:
            result["reason"] = "Licitación ausente del checkpoint."
            return result

        entry = checkpoint["licitaciones"][tender_id]
        state = entry["status"]

        if state == "COMPLETE_WITH_REVIEW":
            result["status"] = "MANUAL_REVIEW"
            result["reason"] = "Existen documentos pendientes de revisión humana."
            return result

        if state != "COMPLETE":
            result["status"] = "PENDING"
            result["reason"] = f"Extracción no completada: {state}."
            return result

        records = entry["attachments"]
        discovered = entry.get("discovered")

        if (
            discovered is None
            or discovered != len(records)
            or not records
            or any(record.get("status") != "COMPLETE" for record in records)
        ):
            result["reason"] = "Inventario de documentos incompleto o inconsistente."
            return result

        # Validate only this tender's extracted evidence. The original
        # checkpoint structure was validated above.
        scoped_checkpoint = {
            **checkpoint,
            "ids": [tender_id],
            "licitaciones": {tender_id: entry},
        }

        allowed_ids = (
            set(checkpoint["ids"])
            if authorized_ids is None
            else authorized_ids
        )

        if not set(checkpoint["ids"]).issubset(allowed_ids):
            raise ValueError(
                "Authorized IDs must include the original checkpoint IDs."
            )

        verify_extraction_lifecycle(
            scoped_checkpoint,
            downloads_root,
            extracted_root,
            authorized_ids=allowed_ids,
        )

        extracted_root = Path(extracted_root)

        documents = []

        for record in records:
            folder = (
                extracted_root
                / tender_id
                / extraction_folder_name(record["filename"])
            )

            verify_extracted(folder, record, tender_id)

            documents.append({
                "filename": record["filename"],
                "control_id": record["control_id"],
                "source_sha256": record["sha256"],
                "metadata_path": str(folder / "contenido.json"),
                "text_path": str(folder / "contenido.txt"),
            })

        result["status"] = "READY"
        result["reason"] = "Todos los documentos fueron verificados."
        result["documents"] = documents

    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        result["status"] = "INVALID"
        result["reason"] = f"{type(exc).__name__}: {exc}"
        result["documents"] = []

    return result