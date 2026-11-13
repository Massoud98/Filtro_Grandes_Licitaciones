"""Explicit date-bound policy for daily attachment reports."""

from __future__ import annotations

from datetime import date

from aplicacion.servicios.reporte_adjuntos import validate_report


def validate_daily_attachment_report(
    report: dict,
    *,
    report_date: str,
    publication_date: str,
    daily_tender_ids: list[str],
) -> dict:
    """Validate explicit report-to-daily-run association.

    The report date is an explicit caller assertion, not metadata
    inferred from the attachment report itself.
    """
    validate_report(report)

    if not isinstance(report_date, str):
        raise ValueError("Attachment report date must be a string.")

    if not isinstance(publication_date, str):
        raise ValueError("Publication date must be a string.")

    try:
        parsed_report_date = date.fromisoformat(report_date)
        parsed_publication_date = date.fromisoformat(publication_date)
    except ValueError as exc:
        raise ValueError("Invalid ISO publication date.") from exc

    if (
        parsed_report_date.isoformat() != report_date
        or parsed_publication_date.isoformat() != publication_date
    ):
        raise ValueError("Dates must use YYYY-MM-DD.")

    if report_date != publication_date:
        raise ValueError(
            "Attachment report date does not match daily run."
        )

    if not isinstance(daily_tender_ids, list):
        raise ValueError("Daily tender IDs must be a list.")

    if not all(
        isinstance(tender_id, str) and tender_id.strip()
        for tender_id in daily_tender_ids
    ):
        raise ValueError("Invalid daily tender ID.")

    if len(daily_tender_ids) != len(set(daily_tender_ids)):
        raise ValueError("Duplicate daily tender IDs.")

    report_ids = set(report["tenders"])
    daily_ids = set(daily_tender_ids)

    if not report_ids:
        raise ValueError("Attachment report has no tenders.")

    unrelated = report_ids - daily_ids

    if unrelated:
        raise ValueError(
            "Attachment report includes tenders outside the daily run."
        )

    return report
