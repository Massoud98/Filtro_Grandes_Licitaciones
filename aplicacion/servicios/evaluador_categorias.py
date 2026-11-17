"""Evaluate Mercado Publico total and passive category exclusions."""

import re


EXCLUDED_PREFIXES = frozenset({
    "70", "71", "72", "73", "76", "77", "78",
    "80", "81", "82", "83", "84", "85", "86",
    "90", "91", "92", "93", "94",
})


def extract_items(tender):
    """Extract tender items without silently accepting invalid structures."""
    container = tender.get("Items")

    if isinstance(container, dict):
        items = container.get("Listado")
    elif isinstance(container, list):
        items = container
    else:
        items = None

    if not isinstance(items, list):
        return None

    if not all(isinstance(item, dict) for item in items):
        return None

    return items


def evaluate_category_filter(tender, category_data):
    """Evaluate category rules before the existing business filters."""

    tender_type = str(tender.get("Tipo") or "").strip().upper()

    result = {
        "decision": None,
        "excluded_items": 0,
        "total_excluded_items": 0,
        "passive_excluded_items": 0,
        "permitted_items": 0,
        "unknown_items": 0,
        "new_excluded_prefix_items": 0,
        "requires_manual_review": False,
        "continue_filtering": False,
        "unknown_codes": [],
    }

    if tender_type == "O1":
        result["decision"] = "EXCLUDED_O1"
        return result

    items = extract_items(tender)

    if not items:
        result["decision"] = "INVESTIGATE"
        result["requires_manual_review"] = True
        return result

    official = category_data["official"]
    total = category_data["total_excluded"]
    passive = category_data["passive_excluded"]
    prefixes = category_data.get("prefixes", EXCLUDED_PREFIXES)

    unknown_codes = set()

    for item in items:
        raw = item.get("CodigoCategoria")
        code = str(raw).strip() if raw is not None else ""

        if not re.fullmatch(r"[0-9]{8}", code):
            result["unknown_items"] += 1
            unknown_codes.add(code)
            continue

        if code in total:
            result["total_excluded_items"] += 1
            result["excluded_items"] += 1
            continue

        if code in passive:
            result["passive_excluded_items"] += 1
            result["excluded_items"] += 1
            continue

        # Hard-exclusion prefixes apply even to valid codes absent
        # from the current official catalogue or explicit exclusion list.
        if code[:2] in prefixes:
            result["new_excluded_prefix_items"] += 1
            result["excluded_items"] += 1
            continue

        if code not in official:
            result["unknown_items"] += 1
            unknown_codes.add(code)
            continue

        result["permitted_items"] += 1

    result["unknown_codes"] = sorted(unknown_codes)

    # Total exclusion always wins, including mixed tenders.
    if (
        result["total_excluded_items"]
        or result["new_excluded_prefix_items"]
    ):
        result["decision"] = "EXCLUDED_SERVICES"

    elif result["unknown_items"]:
        result["decision"] = "INVESTIGATE"
        result["requires_manual_review"] = True

    elif result["passive_excluded_items"]:
        result["decision"] = "PASSIVE_REVIEW"
        result["requires_manual_review"] = True
        result["continue_filtering"] = True

    else:
        result["decision"] = "CONTINUE"
        result["continue_filtering"] = True

    return result