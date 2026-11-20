"""Read API budget evidence without modifying production data."""

import json
import math
from pathlib import Path


def lookup_api_budget(json_path, tender_id):
    path = Path(json_path)

    if not path.is_file():
        return {
            "status": "SOURCE_MISSING",
            "tender_id": tender_id,
            "amount": None,
            "currency": None,
        }

    data = json.loads(path.read_text(encoding="utf-8"))

    details = data.get("detalles")

    if not isinstance(details, (dict, list)):
        raise ValueError("Invalid details structure.")

    if isinstance(details, dict):
        records = list(details.values())
    else:
        records = details

    matches = []

    for record in records:
        if isinstance(record, dict):
            if record.get("CodigoExterno") == tender_id:
                matches.append(record)

            elif isinstance(record.get("Listado"), list):
                matches.extend(
                    item for item in record["Listado"]
                    if isinstance(item, dict)
                    and item.get("CodigoExterno") == tender_id
                )

    if len(matches) > 1:
        raise ValueError("Duplicate tender ID.")

    if not matches:
        return {
            "status": "NOT_FOUND",
            "tender_id": tender_id,
            "amount": None,
            "currency": None,
        }

    record = matches[0]
    amount = record.get("MontoEstimado")
    currency = record.get("Moneda")

    if amount is None:
        status = "AMOUNT_MISSING"
    elif (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(amount)
        or amount < 0
    ):
        raise ValueError("Invalid API amount.")
    else:
        status = "FOUND"

    return {
        "status": status,
        "tender_id": tender_id,
        "amount": amount,
        "currency": currency,
    }
