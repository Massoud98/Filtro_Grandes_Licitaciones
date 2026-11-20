"""Conservative integration of Filter 2 assessments."""

from __future__ import annotations


def integrate_filter_2(
    tender_id: str,
    modality: str,
    item_assessment: dict,
    budget_assessment: dict,
    service_assessment: dict,
    *,
    universal_training: dict | None = None,
) -> dict:
    """Return a preliminary decision without guessing missing evidence."""

    if not tender_id:
        raise ValueError("Missing tender ID.")

    if modality not in {"TOTAL", "PARTIAL", "UNKNOWN"}:
        raise ValueError("Invalid modality.")

    item_status = item_assessment.get("status")
    budget_status = budget_assessment.get("status")
    obligation = service_assessment.get("obligation")

    valid_item = {
        "REJECT",
        "UNRESOLVED",
        "MANUAL_REVIEW",
        "NOT_APPLICABLE_TENDER_WIDE",
        "PASS",
    }

    valid_budget = {
        "REJECT",
        "UNRESOLVED",
        "MANUAL_REVIEW",
        "NOT_APPLICABLE_TENDER_WIDE",
        "PASS",
    }

    if item_status not in valid_item:
        raise ValueError("Invalid item assessment status.")

    if budget_status not in valid_budget:
        raise ValueError("Invalid budget assessment status.")

    if obligation not in {
        "MANDATORY",
        "OPTIONAL_INDEPENDENT",
        "NONE",
        "UNKNOWN",
    }:
        raise ValueError("Invalid service obligation.")

    reasons = []

    if modality == "TOTAL":
        if item_status == "REJECT":
            reasons.append(
                "Cantidad de items obligatorios superior al maximo."
            )

        if budget_status == "REJECT":
            reasons.append(
                "Presupuesto inferior a CLP 20.000.000."
            )

        if obligation == "MANDATORY":
            reasons.append(
                "Servicio prohibido obligatorio."
            )

    if modality == "PARTIAL":
        universal_confirmed = (
            isinstance(universal_training, dict)
            and universal_training.get("status")
                == "UNIVERSAL_MANDATORY_TRAINING"
            and universal_training.get(
                "universal_scope_confirmed"
            ) is True
        )

        if universal_confirmed and obligation == "MANDATORY":
            reasons.append(
                "Capacitacion obligatoria en todas las "
                "categorias adjudicables."
            )

    if reasons:
        decision = "EXCLUIDA"
    else:
        decision = "REVISION_MANUAL"

        if modality == "UNKNOWN":
            reasons.append(
                "Modalidad de adjudicacion no verificada."
            )
        elif modality == "PARTIAL":
            reasons.append(
                "No se ha verificado un grupo adjudicable "
                "libre de servicios prohibidos."
            )
        else:
            reasons.append(
                "Falta confirmar todos los requisitos "
                "para aprobar la licitacion."
            )

    return {
        "tender_id": tender_id,
        "decision": decision,
        "reasons": reasons,
        "modality": modality,
        "assessments": {
            "items": item_status,
            "budget": budget_status,
            "services": obligation,
        },
        "preliminary": True,
    }
