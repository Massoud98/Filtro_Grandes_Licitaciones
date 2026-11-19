"""Build an atomic daily manual-review report from all batch checkpoints."""

import csv
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from checkpoint_descargas import (
    sha256_file,
    validate_checkpoint_structure,
)


FIELDS = [
    "fecha_ejecucion",
    "id_licitacion",
    "archivo",
    "categoria",
    "extension",
    "motivo",
    "tamano_bytes",
    "sha256",
    "ruta_original",
    "original_presente",
    "integrity_status",
]


class ManualReviewReportError(RuntimeError):
    pass


def _csv_safe(value):
    value = str(value)
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _verify_original(path, record):
    if path.is_symlink():
        return False, "INTEGRITY_FAILED"

    if not path.is_file():
        return False, "MISSING"

    try:
        size, digest = sha256_file(path)
    except OSError:
        return True, "INTEGRITY_FAILED"

    if size != record["size_bytes"] or digest.lower() != record["sha256"].lower():
        return True, "INTEGRITY_FAILED"

    return True, "VERIFIED"


def rebuild_manual_review_report(
    checkpoints_root,
    downloads_root,
    report_path,
):
    checkpoints_root = Path(checkpoints_root)
    downloads_root = Path(downloads_root)
    report_path = Path(report_path)

    if checkpoints_root.is_symlink() or not checkpoints_root.is_dir():
        raise ManualReviewReportError("Unsafe checkpoint directory.")

    if downloads_root.is_symlink() or not downloads_root.is_dir():
        raise ManualReviewReportError("Unsafe downloads directory.")

    if report_path.is_symlink():
        raise ManualReviewReportError("Unsafe report destination.")

    if not report_path.parent.is_dir():
        raise ManualReviewReportError("Report directory missing.")

    run_date = report_path.parent.name

    try:
        if date.fromisoformat(run_date).isoformat() != run_date:
            raise ValueError
    except ValueError as exc:
        raise ManualReviewReportError("Invalid daily workspace date.") from exc

    rows = []
    seen = set()

    for checkpoint_path in sorted(checkpoints_root.glob("lote_*.json")):
        if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
            raise ManualReviewReportError("Unsafe checkpoint entry.")

        try:
            checkpoint = json.loads(
                checkpoint_path.read_text(encoding="utf-8")
            )
            validate_checkpoint_structure(checkpoint)
        except Exception as exc:
            raise ManualReviewReportError(
                "Invalid checkpoint: " + checkpoint_path.name
            ) from exc

        for tender_id, entry in checkpoint["licitaciones"].items():
            for record in entry["attachments"]:
                if record.get("status") != "REVIEW_REQUIRED":
                    continue

                review = record["review"]
                filename = record["filename"]
                identity = (tender_id, record["control_id"])

                if identity in seen:
                    raise ManualReviewReportError(
                        "Duplicate manual-review attachment."
                    )

                seen.add(identity)

                original = downloads_root / tender_id / filename
                present, integrity = _verify_original(original, record)

                rows.append({
                    "fecha_ejecucion": run_date,
                    "id_licitacion": tender_id,
                    "archivo": _csv_safe(filename),
                    "categoria": review["category"],
                    "extension": review["extension"],
                    "motivo": _csv_safe(review["reason"]),
                    "tamano_bytes": record["size_bytes"],
                    "sha256": record["sha256"],
                    "ruta_original": _csv_safe(str(original)),
                    "original_presente": present,
                    "integrity_status": integrity,
                })

    rows.sort(key=lambda row: (
        row["id_licitacion"],
        row["archivo"],
    ))

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=report_path.parent,
            prefix=".revision_manual_",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())

        if report_path.is_symlink():
            raise ManualReviewReportError("Unsafe report destination.")

        os.replace(temporary, report_path)
        temporary = None

    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return {
        "status": "SUCCESS",
        "reviews": len(rows),
        "verified": sum(r["integrity_status"] == "VERIFIED" for r in rows),
        "missing": sum(r["integrity_status"] == "MISSING" for r in rows),
        "integrity_failed": sum(
            r["integrity_status"] == "INTEGRITY_FAILED" for r in rows
        ),
        "report": str(report_path),
    }
