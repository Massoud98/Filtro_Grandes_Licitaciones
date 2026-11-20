"""Read-only coordinator for verified Filter 2 evaluations."""

import json
from collections import Counter
from pathlib import Path

from adaptador_montos_api_filtro_2 import lookup_api_budget
from estado_filtro_2 import RULE_VERSION, evidence_fingerprint, load_evaluations, reusable_evaluation, save_evaluation
from pipeline_filtro_2 import evaluate_ready_tender
from validador_filtro_2 import validate_tender_readiness


def coordinate_filter_2(
    workspace,
    api_path,
    source_date,
    *,
    evaluations_path=None,
    persist=False,
):
    """Evaluate READY tenders; optionally persist verified decisions."""

    if persist and evaluations_path is None:
        raise ValueError("Persistence requires evaluations_path.")

    workspace = Path(workspace)
    api_path = Path(api_path)

    if not workspace.is_dir():
        raise FileNotFoundError(workspace)

    if not api_path.is_file():
        raise FileNotFoundError(api_path)

    checkpoints = []
    owners = {}

    for path in sorted(workspace.rglob("lote_*.json")):
        checkpoint = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(checkpoint, dict):
            raise ValueError("Invalid checkpoint structure.")

        ids = checkpoint.get("ids")

        if not isinstance(ids, list):
            raise ValueError("Checkpoint missing ID list.")

        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate ID within checkpoint.")

        for tender_id in ids:
            if not isinstance(tender_id, str) or not tender_id:
                raise ValueError("Invalid tender ID.")

            if tender_id in owners:
                raise ValueError(
                    f"Duplicate tender across checkpoints: {tender_id}"
                )

            owners[tender_id] = checkpoint

        checkpoints.append((path, checkpoint))

    if not checkpoints:
        raise ValueError("No checkpoints found.")

    authorized_ids = set(owners)

    store = (
        load_evaluations(evaluations_path)
        if evaluations_path is not None
        else {"evaluations": {}}
    )

    counts = Counter()
    results = []

    for tender_id, checkpoint in owners.items():
        readiness = validate_tender_readiness(
            checkpoint,
            tender_id,
            workspace / "descargas",
            workspace / "extraidos",
            authorized_ids=authorized_ids,
        )

        status = readiness["status"]

        if status != "READY":
            counts[status] += 1
            results.append({
                "tender_id": tender_id,
                "readiness": status,
                "decision": None,
                "record": None,
                "reused": False,
                "reason": readiness.get("reason"),
            })
            continue

        api_budget = lookup_api_budget(api_path, tender_id)

        fingerprint = evidence_fingerprint(
            readiness["documents"],
            api_budget={
                "source_date": source_date,
                "status": api_budget["status"],
                "amount": api_budget["amount"],
                "currency": api_budget["currency"],
            },
        )

        cached = reusable_evaluation(
            store,
            tender_id,
            fingerprint,
            rule_version=RULE_VERSION,
        )

        if cached is not None:
            record = cached
        else:
            evaluated = evaluate_ready_tender(
                tender_id,
                readiness["documents"],
                api_budget,
                source_date,
            )
            record = evaluated["record"]

            if record["evidence_fingerprint"] != fingerprint:
                raise ValueError(
                    "Filter 2 evidence changed during evaluation."
                )

        counts["READY"] += 1
        counts[record["decision"]] += 1

        if cached is not None:
            counts["REUSED"] += 1
        elif persist:
            save_evaluation(
                evaluations_path,
                tender_id,
                record["decision"],
                record["evidence_fingerprint"],
                reasons=record["reasons"],
                evidence=record["evidence"],
                rule_version=record["rule_version"],
            )
            counts["SAVED"] += 1

        results.append({
            "tender_id": tender_id,
            "readiness": "READY",
            "decision": record["decision"],
            "record": cached if cached is not None else record,
            "reused": cached is not None,
            "reason": "; ".join(record["reasons"]),
        })

    return {
        "source_date": source_date,
        "checkpoint_count": len(checkpoints),
        "authorized_count": len(authorized_ids),
        "counts": dict(counts),
        "results": results,
        "dry_run": not persist,
    }
