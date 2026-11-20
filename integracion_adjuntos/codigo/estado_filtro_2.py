"""Persistent, versioned evaluation records for Filter 2."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
RULE_VERSION = "filtro2-jessika-v2"
DECISIONS = frozenset({
    "APROBADA",
    "EXCLUIDA",
    "REVISION_MANUAL",
})


def evidence_fingerprint(documents: list[dict], *, api_budget: dict | None = None) -> str:
    """Fingerprint verified extraction content and source metadata."""
    entries = []

    for document in documents:
        text_path = Path(document["text_path"])
        metadata_path = Path(document["metadata_path"])

        entries.append({
            "filename": document["filename"],
            "control_id": document["control_id"],
            "source_sha256": document["source_sha256"],
            "text_sha256": hashlib.sha256(
                text_path.read_bytes()
            ).hexdigest(),
            "metadata_sha256": hashlib.sha256(
                metadata_path.read_bytes()
            ).hexdigest(),
        })

    entries.sort(key=lambda item: (
        item["filename"].casefold(),
        item["control_id"],
    ))

    payload = json.dumps(
        entries,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    if api_budget is not None:
        if not isinstance(api_budget, dict):
            raise ValueError("Invalid API budget evidence.")

        required = {"status", "amount", "currency"}

        if not required.issubset(api_budget):
            raise ValueError("Incomplete API budget evidence.")

        api_payload = json.dumps(
            {
                "documents_sha256": hashlib.sha256(
                    payload
                ).hexdigest(),
                "api_budget": {
                    "status": api_budget["status"],
                    "amount": api_budget["amount"],
                    "currency": api_budget["currency"],
                    "source_date": api_budget.get("source_date"),
                },
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

        return hashlib.sha256(api_payload).hexdigest()

    return hashlib.sha256(payload).hexdigest()


def load_evaluations(path: str | Path) -> dict:
    """Load saved decisions, or return an empty store."""
    path = Path(path)

    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "evaluations": {},
        }

    data = json.loads(path.read_text(encoding="utf-8"))

    if (
        not isinstance(data, dict)
        or data.get("schema_version") != SCHEMA_VERSION
        or not isinstance(data.get("evaluations"), dict)
    ):
        raise ValueError("Invalid Filter 2 evaluation store.")

    return data


def reusable_evaluation(
    store: dict,
    tender_id: str,
    fingerprint: str,
    *,
    rule_version: str = RULE_VERSION,
) -> dict | None:
    """Return a previous decision only when evidence and rules match."""
    record = store.get("evaluations", {}).get(tender_id)

    if (
        isinstance(record, dict)
        and record.get("decision") in DECISIONS
        and record.get("evidence_fingerprint") == fingerprint
        and record.get("rule_version") == rule_version
    ):
        return record

    return None


def save_evaluation(
    path: str | Path,
    tender_id: str,
    decision: str,
    fingerprint: str,
    *,
    reasons: list[str],
    evidence: list[dict],
    rule_version: str = RULE_VERSION,
) -> dict:
    """Atomically save a Filter 2 decision without touching checkpoints."""
    if decision not in DECISIONS:
        raise ValueError("Invalid Filter 2 decision.")

    if not tender_id or not fingerprint or not rule_version:
        raise ValueError("Missing evaluation identity.")

    if not isinstance(reasons, list) or not all(
        isinstance(reason, str) for reason in reasons
    ):
        raise ValueError("Invalid evaluation reasons.")

    if not isinstance(evidence, list) or not all(
        isinstance(item, dict) for item in evidence
    ):
        raise ValueError("Invalid evaluation evidence.")

    path = Path(path)
    store = load_evaluations(path)

    record = {
        "tender_id": tender_id,
        "decision": decision,
        "reasons": reasons,
        "evidence": evidence,
        "evidence_fingerprint": fingerprint,
        "rule_version": rule_version,
        "evaluated_utc": datetime.now(timezone.utc).isoformat(),
    }

    store["evaluations"][tender_id] = record
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".filtro2_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(store, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return record