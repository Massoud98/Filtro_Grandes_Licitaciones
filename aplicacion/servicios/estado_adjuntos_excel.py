"""Optional Excel status lookup for validated attachment reports."""

from __future__ import annotations

from aplicacion.servicios.reporte_adjuntos import validate_report


PENDING_STATUS = "Pendiente de verificacion"


def build_attachment_status_lookup(report: dict | None) -> dict[str, str]:
    """Build tender-to-status mapping from an explicitly supplied report.

    None means no verified attachment report was supplied.

    The returned labels describe extraction evidence only; they do not
    represent interpretation or approval of tender requirements.
    """
    if report is None:
        return {}

    validate_report(report)

    lookup = {}

    for tender_id, summary in report["tenders"].items():
        counts = summary["counts"]
        total = counts["total"]
        extracted = counts["extracted"]

        if summary["status"] == "partial":
            status = (
                f"Extraccion parcial ({extracted}/{total}) - Revision"
            )
        elif summary["requires_human_review"]:
            status = f"Analizados ({total}) - Revision humana"
        else:
            status = f"Analizados ({total})"

        lookup[tender_id] = status

    return lookup


def attachment_status_for_tender(
    tender_id: str,
    lookup: dict[str, str] | None = None,
) -> str:
    """Return a tender's attachment status or the pending fallback."""
    if lookup is None:
        return PENDING_STATUS

    return lookup.get(tender_id, PENDING_STATUS)