"""Strict tender eligibility selection for attachment downloads."""

import json
import re
from pathlib import Path


class EligibilityError(ValueError):
    """Invalid or inconsistent classification input."""


def load_included_tenders(
    classification_path: str | Path,
    *,
    limit: int | None = None,
) -> list[str]:
    """Return only validated IDs classified exactly as 'incluida'."""

    source = Path(classification_path)

    if not source.is_file() or source.is_symlink():
        raise EligibilityError(
            "Classification source missing or unsafe."
        )

    try:
        data = json.loads(
            source.read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError) as exc:
        raise EligibilityError(
            "Cannot read classification source."
        ) from exc

    if not isinstance(data, dict):
        raise EligibilityError("Invalid classification root.")

    records = data.get("resultados")
    if not isinstance(records, list):
        raise EligibilityError("Missing classification records.")

    if isinstance(limit, bool) or (
        limit is not None
        and (not isinstance(limit, int) or limit < 1)
    ):
        raise EligibilityError("Limit must be a positive integer.")

    included = []
    seen = set()

    for record in records:
        if not isinstance(record, dict):
            raise EligibilityError("Invalid classification record.")

        if record.get("estado") != "incluida":
            continue

        tender_id = record.get("id")

        if not isinstance(tender_id, str):
            raise EligibilityError("Invalid included tender ID.")

        if not re.fullmatch(
            r"[0-9]+-[0-9]+-[A-Za-z0-9]+",
            tender_id,
        ):
            raise EligibilityError(
                f"Malformed included ID: {tender_id!r}"
            )

        if tender_id in seen:
            raise EligibilityError(
                f"Duplicate included ID: {tender_id}"
            )

        seen.add(tender_id)
        included.append(tender_id)

    total = data.get("total")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total != len(records)
    ):
        raise EligibilityError("Classification total mismatch.")

    summary = data.get("resumen")
    if not isinstance(summary, dict):
        raise EligibilityError("Missing classification summary.")

    expected = summary.get("incluida")

    if (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected != len(included)
    ):
        raise EligibilityError("Included count mismatch.")

    if limit is not None:
        return included[:limit]

    return included
