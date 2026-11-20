"""Build auditable Filter 2 records without saving them."""

import math
from datetime import date

from estado_filtro_2 import RULE_VERSION, evidence_fingerprint


def build_evaluation_record(
    documents,
    api_budget,
    api_source_date,
    decision_result,
    *,
    modality_result,
    item_assessment,
    budget_reconciliation,
    budget_assessment,
    service_assessment,
    universal_training,
):
    if not isinstance(documents, list) or not documents:
        raise ValueError("Missing verified documents.")

    if not isinstance(api_budget, dict):
        raise ValueError("Missing API budget.")

    if not isinstance(decision_result, dict):
        raise ValueError("Missing decision.")

    if (
        not isinstance(api_source_date, str)
        or date.fromisoformat(api_source_date).isoformat()
        != api_source_date
    ):
        raise ValueError("Invalid API source date.")

    tender_id = decision_result.get("tender_id")
    decision = decision_result.get("decision")
    reasons = decision_result.get("reasons")

    if not isinstance(tender_id, str) or not tender_id:
        raise ValueError("Missing tender ID.")

    if decision not in {
        "APROBADA", "EXCLUIDA", "REVISION_MANUAL"
    }:
        raise ValueError("Invalid decision.")

    if not isinstance(reasons, list) or not all(
        isinstance(value, str) for value in reasons
    ):
        raise ValueError("Invalid reasons.")

    if api_budget.get("tender_id") != tender_id:
        raise ValueError("API tender ID mismatch.")

    status = api_budget.get("status")
    amount = api_budget.get("amount")
    currency = api_budget.get("currency")

    if status not in {
        "FOUND", "AMOUNT_MISSING",
        "NOT_FOUND", "SOURCE_MISSING"
    }:
        raise ValueError("Invalid API status.")

    if status == "FOUND":
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(amount)
            or amount < 0
            or not isinstance(currency, str)
            or not currency.strip()
        ):
            raise ValueError("Invalid API amount.")
    elif amount is not None:
        raise ValueError("Unexpected API amount.")

    assessments = {
        "modality": modality_result,
        "items": item_assessment,
        "budget_reconciliation": budget_reconciliation,
        "budget": budget_assessment,
        "services": service_assessment,
        "universal_training": universal_training,
    }

    if not all(
        isinstance(value, dict)
        for value in assessments.values()
    ):
        raise ValueError("Invalid assessments.")

    if decision_result.get("modality") != modality_result.get(
        "modality"
    ):
        raise ValueError("Modality mismatch.")

    expected = {
        "items": item_assessment.get("status"),
        "budget": budget_assessment.get("status"),
        "services": service_assessment.get("obligation"),
    }

    if decision_result.get("assessments") != expected:
        raise ValueError("Assessment mismatch.")

    reconciled_api = budget_reconciliation.get(
        "api_amount_clp"
    )

    if status == "FOUND" and currency == "CLP":
        if (
            isinstance(reconciled_api, bool)
            or not isinstance(reconciled_api, (int, float))
            or not math.isfinite(reconciled_api)
            or not math.isclose(
                reconciled_api,
                amount,
                rel_tol=0,
                abs_tol=0.01,
            )
        ):
            raise ValueError("API reconciliation mismatch.")

    if status != "FOUND" and reconciled_api is not None:
        raise ValueError("Unexpected reconciled API amount.")

    api_identity = {
        "source_date": api_source_date,
        "status": status,
        "amount": amount,
        "currency": currency,
    }

    fingerprint = evidence_fingerprint(
        documents,
        api_budget=api_identity,
    )

    evidence = [
        {
            "type": "API_BUDGET",
            **api_identity,
        },
        {
            "type": "FILTER_2_ASSESSMENTS",
            "details": assessments,
        },
    ]

    return {
        "tender_id": tender_id,
        "decision": decision,
        "reasons": reasons,
        "evidence": evidence,
        "evidence_fingerprint": fingerprint,
        "rule_version": RULE_VERSION,
    }
