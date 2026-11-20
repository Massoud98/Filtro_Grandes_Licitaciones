"""Conservative, evidence-based business rules for Jessika's Filter 2."""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_AMOUNT_CLP = 20_000_000
MAX_REQUIRED_ITEMS = 9

ALLOWED_MODALITIES = frozenset({
    "TOTAL",
    "PARTIAL",
    "UNKNOWN",
})

ALLOWED_OBLIGATIONS = frozenset({
    "NONE",
    "MANDATORY",
    "OPTIONAL_INDEPENDENT",
    "UNKNOWN",
})


@dataclass
class AwardGroup:
    """Smallest independently awardable group of goods."""

    group_id: str
    item_count: int | None = None
    amount_clp: int | None = None
    forbidden_obligation: str = "UNKNOWN"
    evidence: list[dict] = field(default_factory=list)


@dataclass
class TenderEvidence:
    tender_id: str
    modality: str = "UNKNOWN"
    groups: list[AwardGroup] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)


def evaluate_group(group: AwardGroup, *, partial: bool) -> dict:
    """Evaluate one independently awardable group."""

    if not group.group_id:
        raise ValueError("Missing award group ID.")

    if group.item_count is not None and (
        isinstance(group.item_count, bool)
        or not isinstance(group.item_count, int)
        or group.item_count < 1
    ):
        raise ValueError("Invalid item count.")

    if group.amount_clp is not None and (
        isinstance(group.amount_clp, bool)
        or not isinstance(group.amount_clp, int)
        or group.amount_clp < 0
    ):
        raise ValueError("Invalid CLP amount.")

    if group.forbidden_obligation not in ALLOWED_OBLIGATIONS:
        raise ValueError("Invalid service obligation.")

    reasons = []

    if group.forbidden_obligation == "MANDATORY":
        reasons.append(
            "El grupo exige un servicio o componente prohibido."
        )

    if not partial:
        if (
            group.item_count is not None
            and group.item_count > MAX_REQUIRED_ITEMS
        ):
            reasons.append(
                f"Exige {group.item_count} items; maximo permitido: "
                f"{MAX_REQUIRED_ITEMS}."
            )

        if (
            group.amount_clp is not None
            and group.amount_clp < MIN_AMOUNT_CLP
        ):
            reasons.append(
                f"Presupuesto CLP {group.amount_clp}; minimo requerido: "
                f"CLP {MIN_AMOUNT_CLP}."
            )

    if reasons:
        decision = "EXCLUIDA"

    elif group.forbidden_obligation == "UNKNOWN":
        decision = "REVISION_MANUAL"
        reasons.append(
            "No se pudo determinar si existen servicios obligatorios."
        )

    elif not partial and group.item_count is None:
        decision = "REVISION_MANUAL"
        reasons.append("Cantidad de items no verificada.")

    elif not partial and group.amount_clp is None:
        decision = "REVISION_MANUAL"
        reasons.append("Presupuesto CLP no verificado.")

    else:
        decision = "APROBADA"
        reasons.append("Cumple las reglas verificadas de Filtro 2.")

    return {
        "group_id": group.group_id,
        "decision": decision,
        "reasons": reasons,
        "evidence": group.evidence,
    }


def evaluate_tender(tender: TenderEvidence) -> dict:
    """Evaluate a tender without guessing missing bidding information."""

    if not tender.tender_id:
        raise ValueError("Missing tender ID.")

    if tender.modality not in ALLOWED_MODALITIES:
        raise ValueError("Invalid bidding modality.")

    if not tender.groups:
        return {
            "tender_id": tender.tender_id,
            "decision": "REVISION_MANUAL",
            "reasons": ["No se identificaron grupos adjudicables."],
            "groups": [],
            "evidence": tender.evidence,
        }

    ids = [group.group_id for group in tender.groups]

    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate award group IDs.")

    if tender.modality == "TOTAL" and len(tender.groups) != 1:
        raise ValueError(
            "TOTAL bidding requires exactly one award group."
        )

    if tender.modality == "UNKNOWN":
        return {
            "tender_id": tender.tender_id,
            "decision": "REVISION_MANUAL",
            "reasons": ["Modalidad de adjudicacion no verificada."],
            "groups": [],
            "evidence": tender.evidence,
        }

    partial = tender.modality == "PARTIAL"

    results = [
        evaluate_group(group, partial=partial)
        for group in tender.groups
    ]

    approved = [
        result for result in results
        if result["decision"] == "APROBADA"
    ]

    uncertain = [
        result for result in results
        if result["decision"] == "REVISION_MANUAL"
    ]

    if approved:
        decision = "APROBADA"
        reasons = [
            f"{len(approved)} grupo(s) adjudicable(s) elegible(s)."
        ]

    elif uncertain:
        decision = "REVISION_MANUAL"
        reasons = [
            "No hay grupos aprobados y existen requisitos sin verificar."
        ]

    else:
        decision = "EXCLUIDA"
        reasons = [
            "Ningun grupo adjudicable cumple los requisitos."
        ]

    return {
        "tender_id": tender.tender_id,
        "decision": decision,
        "reasons": reasons,
        "groups": results,
        "evidence": tender.evidence,
    }