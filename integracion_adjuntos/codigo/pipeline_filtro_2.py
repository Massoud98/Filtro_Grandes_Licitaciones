"""Read-only evaluation pipeline for verified Filter 2 evidence."""

from interprete_filtro_2 import (
    interpret_modality,
    consolidate_item_counts,
    assess_item_count,
    interpret_budget_clp,
    reconcile_budget_clp,
    assess_budget,
    detect_service_evidence,
    assess_service_obligation,
    confirm_universal_training_obligation,
)
from integrador_filtro_2 import integrate_filter_2
from registro_filtro_2 import build_evaluation_record


def evaluate_ready_tender(
    tender_id,
    documents,
    api_budget,
    api_source_date,
):
    """Evaluate verified documents without persisting decisions."""

    if not isinstance(tender_id, str) or not tender_id:
        raise ValueError("Missing tender ID.")

    if not isinstance(documents, list) or not documents:
        raise ValueError("Missing verified documents.")

    if not isinstance(api_budget, dict):
        raise ValueError("Missing API budget lookup.")

    if api_budget.get("tender_id") != tender_id:
        raise ValueError("API tender ID mismatch.")

    modality_result = interpret_modality(documents)
    modality = modality_result["modality"]

    consolidated = consolidate_item_counts(documents)
    item_assessment = assess_item_count(
        modality,
        consolidated,
    )

    documented_budget = interpret_budget_clp(documents)

    api_amount = (
        api_budget.get("amount")
        if api_budget.get("status") == "FOUND"
        else None
    )

    api_currency = (
        api_budget.get("currency")
        if api_budget.get("status") == "FOUND"
        else None
    )

    reconciliation = reconcile_budget_clp(
        documented_budget,
        api_amount,
        api_currency,
    )

    budget_assessment = assess_budget(
        modality,
        reconciliation,
    )

    service_evidence = detect_service_evidence(documents)

    universal_training = confirm_universal_training_obligation(
        documents,
        modality,
    )

    service_assessment = assess_service_obligation(
        modality,
        service_evidence,
        universal_training=universal_training,
    )

    decision_result = integrate_filter_2(
        tender_id,
        modality,
        item_assessment,
        budget_assessment,
        service_assessment,
        universal_training=universal_training,
    )

    if modality_result.get("contradictions"):
        reasons = decision_result["reasons"]

        for conflict in modality_result["contradictions"]:
            partial = conflict["partial"]
            total = conflict["total"]

            def describe(item):
                location = item["filename"]
                if item.get("page") is not None:
                    location += f", pagina {item['page']}"
                return (
                    f"{location}: "
                    f"'{item['matched_clause']}'"
                )

            reasons.append(
                "Contradiccion de adjudicacion: "
                + "PARCIAL ["
                + describe(partial)
                + "] frente a TOTAL ["
                + describe(total)
                + "]. "
                + conflict["explanation"]
            )

    elif modality_result.get("assumed_total"):
        decision_result["reasons"].insert(
            0,
            "Los documentos no especifican modalidad de "
            "adjudicacion; se presume TOTAL (todo o nada).",
        )

    record = build_evaluation_record(
        documents,
        api_budget,
        api_source_date,
        decision_result,
        modality_result=modality_result,
        item_assessment=item_assessment,
        budget_reconciliation=reconciliation,
        budget_assessment=budget_assessment,
        service_assessment=service_assessment,
        universal_training=universal_training,
    )

    return {
        "decision": decision_result,
        "record": record,
        "details": {
            "modality": modality_result,
            "item_counts": consolidated,
            "documented_budget": documented_budget,
            "budget_reconciliation": reconciliation,
            "service_evidence": service_evidence,
            "universal_training": universal_training,
        },
    }
