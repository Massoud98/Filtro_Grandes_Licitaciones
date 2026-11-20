"""Conservative document-evidence interpretation for Filter 2."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def normalize_text(text: str) -> str:
    """Remove accents while preserving character positions."""
    decomposed = unicodedata.normalize("NFD", text)

    return "".join(
        character for character in decomposed
        if unicodedata.category(character) != "Mn"
    ).lower()


def page_number(text: str, position: int) -> int | None:
    """Find the last extracted PDF page marker before a match."""
    markers = list(
        re.finditer(
            r"=== PAGE (\d+) \[(?:native|ocr)\] ===",
            text[:position],
            re.IGNORECASE,
        )
    )

    if not markers:
        return None

    return int(markers[-1].group(1))


def evidence_record(
    text: str,
    match: re.Match,
    filename: str,
    category: str,
) -> dict:
    start = max(0, match.start() - 150)
    end = min(len(text), match.end() + 250)

    return {
        "filename": filename,
        "page": page_number(text, match.start()),
        "category": category,
        "excerpt": " ".join(text[start:end].split())[:450],
        "matched_clause": " ".join(
            text[match.start():match.end()].split()
        ),
    }


def interpret_modality(documents: list[dict]) -> dict:
    """Conservatively identify independently awardable bidding groups."""

    patterns = {
        "PARTIAL": [
            r"lineas? de adjudicacion independientes?",
            r"cada linea sera evaluada y adjudicada de manera independiente",
            r"podran participar en una o mas lineas",
            r"adjudicacion por lineas?",
            r"adjudicacion sera por lineas?",
            r"se adjudicara por lineas?",
            r"no sera requisito de admisibilidad la postulaci?n a todas las categorias",
            r"no sera requisito de admisibilidad la postulacion a todas las categorias",
            r"adjudicacion de la licitacion sera por cada linea de producto",
            r"puede ofertar a uno o mas de los items",
            r"adjudicacion por items?",
        ],
        "TOTAL": [
            r"debera considerar la totalidad de los .{0,90} requeridos",
            r"deberan ofertar la totalidad de los .{0,90} requeridos",
            r"no se aceptan ofertas parciales",
            r"no aceptandose ofertas parciales",
        ],
        "NO_INDEPENDENT": [
            r"no\s+contemplandose\s+adjudicacion\s+por\s+lineas?",
            r"no\s+se\s+contempla\s+adjudicacion\s+por\s+lineas?",
            r"sin\s+adjudicacion\s+por\s+lineas?",
            r"no\s+contemplandose\s+adjudicacion\s+por\s+grupos",
        ],
        "SINGLE_AWARD": [
            r"licitacion sera adjudicada a un unico proveedor",
            r"adjudicacion global a un unico proveedor",
        ],
        "COVERAGE": [
            r"cantidad de productos ofertados iguale o supere el \d+%",
            r"menor a \d+ articulos inadmisible",
        ],
    }

    found = {category: [] for category in patterns}

    for document in documents:
        filename = document["filename"]
        text = Path(document["text_path"]).read_text(encoding="utf-8")
        normalized = normalize_text(text)

        prohibited_spans = []

        for expression in patterns["NO_INDEPENDENT"]:
            for match in re.finditer(expression, normalized):
                prohibited_spans.append((match.start(), match.end()))
                found["NO_INDEPENDENT"].append(
                    evidence_record(
                        text, match, filename, "NO_INDEPENDENT"
                    )
                )

        for category, expressions in patterns.items():
            if category == "NO_INDEPENDENT":
                continue

            for expression in expressions:
                for match in re.finditer(expression, normalized):
                    if category == "PARTIAL":
                        if any(
                            start <= match.start() < end
                            for start, end in prohibited_spans
                        ):
                            continue

                        preceding = normalized[
                            max(0, match.start() - 100):match.start()
                        ]

                        if re.search(
                            r"no\s+(?:contemplandose|se\s+contempla)"
                            r"\s*$",
                            preceding,
                        ):
                            continue

                    if category == "TOTAL":
                        surrounding = normalized[
                            max(0, match.start() - 100):
                            min(len(normalized), match.end() + 100)
                        ]

                        if (
                            "dentro de una linea" in surrounding
                            or "respecto de esa linea" in surrounding
                        ):
                            continue

                    found[category].append(
                        evidence_record(
                            text, match, filename, category
                        )
                    )

    has_partial = bool(found["PARTIAL"])
    has_total = bool(
        found["TOTAL"]
        or found["NO_INDEPENDENT"]
        or found["SINGLE_AWARD"]
    )

    assumed_total = False
    contradictions = []

    if has_partial and has_total:
        modality = "UNKNOWN"
        reason = "Evidencia contradictoria de adjudicacion total y parcial."

        total_evidence = (
            found["TOTAL"]
            + found["NO_INDEPENDENT"]
            + found["SINGLE_AWARD"]
        )

        for partial in found["PARTIAL"]:
            for total in total_evidence:
                contradictions.append({
                    "partial": partial,
                    "total": total,
                    "explanation": (
                        "Un documento permite adjudicacion independiente "
                        "mientras otro exige adjudicacion total o "
                        "prohibe adjudicacion por lineas. "
                        "Verificar el alcance de ambas clausulas."
                    ),
                })

    elif has_partial:
        modality = "PARTIAL"
        reason = "Lineas independientemente adjudicables documentadas."

    elif has_total:
        modality = "TOTAL"
        reason = "Adjudicacion total documentada."

    else:
        modality = "TOTAL"
        assumed_total = True
        reason = (
            "Modalidad no especificada; se presume adjudicacion "
            "total (todo o nada)."
        )

    evidence = []
    for category in patterns:
        evidence.extend(found[category][:5])

    return {
        "modality": modality,
        "reason": reason,
        "assumed_total": assumed_total,
        "contradictions": contradictions,
        "evidence": evidence,
    }


def interpret_required_items(documents: list[dict]) -> dict:
    """Extract explicit minimum mandatory item counts."""

    patterns = [
        (
            "MINIMUM_INADMISSIBLE",
            r"menor(?:es)?\s+a\s+(\d+)\s+"
            r"(?:articulos|productos|items)\s+inadmisible",
        ),
        (
            "MINIMUM_REQUIRED",
            r"(?:al\s+menos|minimo\s+de)\s+(\d+)\s+"
            r"(?:articulos|productos|items)",
        ),
        (
            "MINIMUM_OFFER",
            r"ofertar\s+(?:como\s+minimo|al\s+menos)\s+"
            r"(\d+)\s+(?:articulos|productos|items)",
        ),
    ]

    evidence = []
    candidates = []

    for document in documents:
        text = Path(document["text_path"]).read_text(
            encoding="utf-8"
        )
        normalized = normalize_text(text)

        for category, expression in patterns:
            for match in re.finditer(expression, normalized):
                count = int(match.group(1))

                if count < 1:
                    continue

                record = evidence_record(
                    text,
                    match,
                    document["filename"],
                    category,
                )
                record["minimum_items"] = count

                evidence.append(record)
                candidates.append(count)

    if not candidates:
        return {
            "minimum_items": None,
            "status": "UNKNOWN",
            "reason": "Cantidad minima no identificada.",
            "evidence": [],
        }

    if len(set(candidates)) != 1:
        return {
            "minimum_items": None,
            "status": "CONFLICT",
            "reason": "Minimos diferentes; requiere revision.",
            "evidence": evidence[:10],
        }

    return {
        "minimum_items": candidates[0],
        "status": "CONFIRMED",
        "reason": "Minimo obligatorio documentado.",
        "evidence": evidence[:10],
    }


def count_spreadsheet_products(documents: list[dict]) -> dict:
    """Count distinct product rows in extracted XLSX worksheets."""

    from collections import defaultdict

    cell_pattern = re.compile(
        r"^(.+)!([A-Z]+)(\d+):\s*(.*)$"
    )

    excluded = (
        "total", "iva", "despacho", "identificacion",
        "proveedor", "direccion", "telefono", "correo",
        "garantia", "plazo", "cumple", "monto", "precio",
        "cantidad", "requerimientos", "listado de articulos",
    )

    results = []

    for document in documents:
        filename = document["filename"]

        if not filename.lower().endswith(".xlsx"):
            continue

        text = Path(document["text_path"]).read_text(
            encoding="utf-8"
        )

        sheets = defaultdict(lambda: defaultdict(dict))

        for line in text.splitlines():
            match = cell_pattern.match(line.strip())

            if match is None:
                continue

            sheet, column, row, value = match.groups()
            sheets[sheet][int(row)][column] = value.strip()

        for sheet, rows in sheets.items():
            product_rows = []

            for row_number, cells in sorted(rows.items()):
                values = list(cells.values())

                numeric = [
                    value for value in values
                    if re.fullmatch(r"\d+(?:[.,]\d+)?", value)
                ]

                descriptions = [
                    value for value in values
                    if len(value) >= 8
                    and not re.fullmatch(
                        r"\d+(?:[.,]\d+)?", value
                    )
                ]

                if not numeric or not descriptions:
                    continue

                description = max(descriptions, key=len)
                normalized = normalize_text(description)

                if any(
                    normalized.startswith(word)
                    for word in excluded
                ):
                    continue

                product_rows.append({
                    "row": row_number,
                    "description": description[:180],
                })

            results.append({
                "filename": filename,
                "sheet": sheet,
                "count": len(product_rows),
                "sample": product_rows[:4],
            })

    return {
        "status": "DETECTED" if results else "UNKNOWN",
        "sheets": results,
    }


def count_word_products(documents: list[dict]) -> dict:
    """Count recognizable Word product rows; flag incomplete tables."""

    import re
    from pathlib import Path

    excluded = (
        "cantidad",
        "valor neto unitario",
        "valor neto total",
        "valor total neto",
        "valor total",
        "iva",
        "plazo de entrega",
        "servicio post venta",
    )

    description_pattern = re.compile(
        r"^\|\s*(\S.{10,}?)\s*$"
    )
    quantity_pattern = re.compile(
        r"^\|\s*(\d+(?:[.,]\d+)?)\s*$"
    )

    results = []
    incomplete = []

    for document in documents:
        filename = document["filename"]

        if not filename.lower().endswith((".doc", ".docx")):
            continue

        lines = Path(document["text_path"]).read_text(
            encoding="utf-8"
        ).splitlines()

        products = []
        missing = []

        for index, line in enumerate(lines):
            match = description_pattern.fullmatch(line.strip())

            if match is None:
                continue

            description = match.group(1).strip()
            normalized = normalize_text(description)

            if any(normalized.startswith(term) for term in excluded):
                continue

            quantity = None

            for following in lines[index + 1:]:
                candidate = following.strip()

                if not candidate or candidate == "|":
                    continue

                match_quantity = quantity_pattern.fullmatch(candidate)

                if match_quantity:
                    quantity = match_quantity.group(1)

                # Never cross another populated table cell.
                break

            record = {
                "line": index + 1,
                "description": description[:180],
            }

            if quantity is None:
                missing.append(record)
            else:
                record["quantity"] = quantity
                products.append(record)

        if products:
            results.append({
                "filename": filename,
                "count": len(products),
                "products": products,
            })

        if missing:
            incomplete.append({
                "filename": filename,
                "rows": missing,
            })

    if incomplete:
        status = "PARTIAL"
    elif results:
        status = "CONFIRMED"
    else:
        status = "UNKNOWN"

    return {
        "status": status,
        "documents": results,
        "incomplete": incomplete,
    }


def consolidate_item_counts(documents: list[dict]) -> dict:
    """Combine item-count evidence without assuming table completeness."""

    minimum = interpret_required_items(documents)
    spreadsheets = count_spreadsheet_products(documents)
    word = count_word_products(documents)

    candidates = []

    for sheet in spreadsheets["sheets"]:
        if sheet["count"] > 0:
            candidates.append({
                "source": "SPREADSHEET",
                "filename": sheet["filename"],
                "group": sheet["sheet"],
                "count": sheet["count"],
                "confidence": "CANDIDATE",
            })

    for document in word["documents"]:
        if document["count"] > 0:
            candidates.append({
                "source": "WORD",
                "filename": document["filename"],
                "group": None,
                "count": document["count"],
                "confidence": (
                    "CANDIDATE"
                    if word["status"] == "CONFIRMED"
                    else "PARTIAL"
                ),
            })

    result = {
        "status": "UNKNOWN",
        "minimum_items": None,
        "total_items": None,
        "candidates": candidates,
        "evidence": minimum["evidence"],
        "warnings": [],
    }

    if minimum["status"] == "CONFLICT":
        result["status"] = "CONFLICT"
        result["warnings"].append(
            "Conflicting documented minimum item counts."
        )
        return result

    if minimum["status"] == "CONFIRMED":
        result["minimum_items"] = minimum["minimum_items"]
        result["status"] = "LOWER_BOUND"

    if word["status"] == "PARTIAL":
        result["warnings"].append(
            "At least one Word table has uncounted candidate rows."
        )

    if candidates and result["status"] == "UNKNOWN":
        result["status"] = "CANDIDATE"

    # Do not add counts across documents or worksheets here.
    # Award-group mapping and table completeness are separate tasks.
    return result


def assess_item_count(
    modality: str,
    consolidated: dict,
    *,
    max_items: int = 9,
) -> dict:
    """Assess only the item-count criterion, not the full tender."""

    if modality not in {"TOTAL", "PARTIAL", "UNKNOWN"}:
        raise ValueError("Invalid award modality.")

    if not isinstance(max_items, int) or max_items < 1:
        raise ValueError("Invalid maximum item count.")

    minimum = consolidated.get("minimum_items")
    status = consolidated.get("status", "UNKNOWN")

    result = {
        "criterion": "ITEM_COUNT",
        "status": "UNRESOLVED",
        "reason": "",
        "minimum_items": minimum,
        "max_items": max_items,
        "evidence": consolidated.get("evidence", []),
    }

    if status == "CONFLICT":
        result["status"] = "MANUAL_REVIEW"
        result["reason"] = (
            "Conflicting mandatory minimum item counts."
        )
        return result

    if modality == "UNKNOWN":
        result["status"] = "MANUAL_REVIEW"
        result["reason"] = (
            "Award modality has not been established."
        )
        return result

    if modality == "PARTIAL":
        result["status"] = "NOT_APPLICABLE_TENDER_WIDE"
        result["reason"] = (
            "Independent award groups require separate evaluation."
        )
        return result

    if (
        status == "LOWER_BOUND"
        and isinstance(minimum, int)
        and not isinstance(minimum, bool)
        and minimum > max_items
    ):
        result["status"] = "REJECT"
        result["reason"] = (
            "Documented mandatory minimum exceeds "
            "the all-or-nothing item limit."
        )
        return result

    result["reason"] = (
        "No sufficiently verified evidence establishes "
        "an item-count rejection."
    )

    return result


def interpret_budget_clp(documents: list[dict]) -> dict:
    """Extract explicitly labeled CLP budgets without guessing."""

    import re
    from pathlib import Path

    money = re.compile(
        r"\$\s*(\d{1,3}(?:\.\d{3})+|\d{5,12})(?![\d.,])"
    )

    numeric_money = re.compile(
        r"(?<![\d.,])(\d{1,3}(?:\.\d{3}){2,}|\d{7,12})(?![\d.,])"
    )

    budget_label = re.compile(
        r"presupuesto\s+(?:disponible|asignado|"
        r"maximo|total)|total\s+(?:presupuesto|disponible)"
    )

    line_label = re.compile(
        r"presupuestos?\s+maximos?\s+de\s+cada\s+linea"
    )

    observations = []
    line_observations = []

    for document in documents:
        filename = document["filename"]

        if not filename.lower().endswith((".pdf", ".doc", ".docx")):
            continue

        lines = Path(document["text_path"]).read_text(
            encoding="utf-8"
        ).splitlines()

        normalized = [normalize_text(line) for line in lines]

        for index, line in enumerate(normalized):
            if not budget_label.search(line):
                continue

            # Limit extraction to the labeled row and the next
            # two nonempty lines, avoiding unrelated price tables.
            window = []
            for offset in range(index, min(index + 7, len(lines))):
                value = lines[offset].strip()
                if value and not value.startswith("=== PAGE"):
                    window.append((offset, value))
                if len(window) >= 3:
                    break

            if not window:
                continue

            for position, value in window:
                matches = list(money.finditer(value))

                if not matches and position == index:
                    matches = list(numeric_money.finditer(value))

                if not matches:
                    continue

                for match in matches:
                    amount = int(match.group(1).replace(".", ""))

                    if amount < 100000:
                        continue

                    observations.append({
                        "amount_clp": amount,
                        "filename": filename,
                        "line": position + 1,
                        "label_line": index + 1,
                        "excerpt": value[:200],
                    })

                break

        # Detect a verified-style independent-line budget table.
        # Never use these figures as a TOTAL tender budget.
        if any(line_label.search(line) for line in normalized):
            for index, line in enumerate(normalized):
                if not re.fullmatch(r"\s*[12]\s*", line):
                    continue

                for offset in range(index + 1, min(index + 7, len(lines))):
                    match = money.search(lines[offset])

                    if match:
                        amount = int(
                            match.group(1).replace(".", "")
                        )
                        line_observations.append({
                            "line_id": line.strip(),
                            "amount_clp": amount,
                            "filename": filename,
                            "line": offset + 1,
                        })
                        break

    amounts = sorted({
        observation["amount_clp"]
        for observation in observations
    })

    if len(amounts) == 1:
        status = "DOCUMENTED"
        total = amounts[0]
    elif len(amounts) > 1:
        status = "CONFLICT"
        total = None
    else:
        status = "UNKNOWN"
        total = None

    return {
        "status": status,
        "total_clp": total,
        "currency": "CLP",
        "observations": observations,
        "line_budgets": line_observations,
        "warnings": (
            ["Conflicting documented budget amounts."]
            if status == "CONFLICT"
            else []
        ),
    }


def reconcile_budget_clp(
    documented: dict,
    api_amount: int | float | None,
    api_currency: str | None,
) -> dict:
    """Reconcile document and API budgets without silent overrides."""

    import math

    document_amount = documented.get("total_clp")
    document_status = documented.get("status", "UNKNOWN")

    if document_status not in {
        "DOCUMENTED", "CONFLICT", "UNKNOWN"
    }:
        raise ValueError("Invalid document budget status.")

    if document_status != "DOCUMENTED":
        document_amount = None

    if document_amount is not None:
        if (
            isinstance(document_amount, bool)
            or not isinstance(document_amount, int)
            or document_amount <= 0
        ):
            raise ValueError("Invalid documented CLP amount.")

    api_clp = None
    warnings = list(documented.get("warnings", []))

    if api_amount is not None:
        if isinstance(api_amount, bool):
            raise ValueError("Invalid API amount.")

        if not isinstance(api_amount, (int, float)):
            raise ValueError("Invalid API amount.")

        if not math.isfinite(api_amount) or api_amount <= 0:
            raise ValueError("Invalid API amount.")

        if api_currency == "CLP":
            if not float(api_amount).is_integer():
                raise ValueError("Fractional CLP amount.")

            api_clp = int(api_amount)
        else:
            warnings.append(
                "API currency requires explicit conversion."
            )

    if document_status == "CONFLICT":
        status = "CONFLICT"
        selected = None
    elif document_amount is not None and api_clp is not None:
        if document_amount == api_clp:
            status = "CONFIRMED"
            selected = document_amount
        else:
            status = "CONFLICT"
            selected = None
            warnings.append(
                "Document and API budgets disagree."
            )
    elif document_amount is not None:
        status = "DOCUMENTED"
        selected = document_amount
    elif api_clp is not None:
        status = "API_ONLY"
        selected = api_clp
    else:
        status = "UNKNOWN"
        selected = None

    return {
        "status": status,
        "amount_clp": selected,
        "document_amount_clp": document_amount,
        "api_amount_clp": api_clp,
        "api_currency": api_currency,
        "line_budgets": documented.get("line_budgets", []),
        "observations": documented.get("observations", []),
        "warnings": warnings,
    }


def assess_budget(
    modality: str,
    reconciled: dict,
    *,
    minimum_clp: int = 20_000_000,
) -> dict:
    """Assess the budget criterion without deciding the full tender."""

    if modality not in {"TOTAL", "PARTIAL", "UNKNOWN"}:
        raise ValueError("Invalid award modality.")

    if (
        isinstance(minimum_clp, bool)
        or not isinstance(minimum_clp, int)
        or minimum_clp <= 0
    ):
        raise ValueError("Invalid minimum budget.")

    status = reconciled.get("status", "UNKNOWN")
    amount = reconciled.get("amount_clp")

    result = {
        "criterion": "BUDGET",
        "status": "UNRESOLVED",
        "reason": "",
        "amount_clp": amount,
        "minimum_clp": minimum_clp,
        "budget_status": status,
        "document_amount_clp": reconciled.get(
            "document_amount_clp"
        ),
        "api_amount_clp": reconciled.get(
            "api_amount_clp"
        ),
        "evidence": reconciled.get("observations", []),
        "warnings": reconciled.get("warnings", []),
    }

    if status == "CONFLICT":
        result["status"] = "MANUAL_REVIEW"
        result["reason"] = (
            "Conflicting budget evidence requires review."
        )
        return result

    if modality == "UNKNOWN":
        result["status"] = "MANUAL_REVIEW"
        result["reason"] = (
            "Award modality has not been established."
        )
        return result

    if modality == "PARTIAL":
        result["status"] = "NOT_APPLICABLE_TENDER_WIDE"
        result["reason"] = (
            "Independent award groups are exempt from "
            "the tender-wide minimum budget criterion."
        )
        return result

    if status not in {"CONFIRMED", "DOCUMENTED", "API_ONLY"}:
        result["reason"] = (
            "No usable CLP budget has been established."
        )
        return result

    if (
        isinstance(amount, bool)
        or not isinstance(amount, int)
        or amount <= 0
    ):
        result["reason"] = (
            "Budget amount is missing or invalid."
        )
        return result

    if amount < minimum_clp:
        result["status"] = "REJECT"
        result["reason"] = (
            "All-or-nothing tender budget is below "
            "the minimum CLP threshold."
        )
    else:
        result["status"] = "PASS"
        result["reason"] = (
            "All-or-nothing tender meets "
            "the minimum CLP budget threshold."
        )

    return result


def detect_service_evidence(documents: list[dict]) -> dict:
    """Find service evidence without inferring final obligations."""

    import re
    from pathlib import Path

    service_patterns = {
        "MAINTENANCE": re.compile(
            r"\b(?:mantencion(?:es)?|mantenimiento(?:s)?)\b"
        ),
        "INSTALLATION": re.compile(
            r"\b(?:instalacion(?:es)?|instalar|"
            r"reinstalacion|puesta en marcha)\b"
        ),
        "TRAINING": re.compile(
            r"\b(?:capacitacion(?:es)?|capacitar|"
            r"entrenamiento|entrenar)\b"
        ),
        "LOAN": re.compile(r"\bcomodato\b"),
        "REPAIR": re.compile(
            r"\b(?:reparacion(?:es)?|servicio tecnico|"
            r"soporte tecnico|mano de obra)\b"
        ),
    }

    obligation = re.compile(
        r"\b(?:proveedor|adjudicatario|contratista|"
        r"empresa adjudicada|empresa)\b"
        r".{0,140}\b(?:debera|deberan|tendra que|"
        r"se obliga|obligatoriamente)\b"
    )

    direct_obligation = re.compile(
        r"\b(?:debera|deberan|obligatorio|obligatoria)\b"
        r".{0,120}\b(?:capacitar|entrenar|realizar|"
        r"ejecutar|proporcionar|efectuar|prestar)\b"
    )

    scope = re.compile(
        r"(?:especificaciones tecnicas para el servicio|"
        r"servicios de climatizacion|"
        r"convenio de mantenciones|"
        r"programa de capacitacion|"
        r"hito 3.{0,50}capacitacion|"
        r"servicio de mantencion preventiva)"
    )

    definition = re.compile(
        r"^\s*(?:servicio tecnico|asistencia tecnica|"
        r"mantencion correctiva|mantencion preventiva|"
        r"mano de obra)\s*:"
    )

    delivery = re.compile(
        r"\b(?:despacho|descarga|entrega|"
        r"transporte de productos)\b"
    )

    findings = []
    counts = {
        "MANDATORY_EVIDENCE": 0,
        "SERVICE_SCOPE": 0,
        "CONTEXT_ONLY": 0,
        "DELIVERY_ONLY": 0,
    }

    for document in documents:
        filename = document["filename"]

        lines = Path(document["text_path"]).read_text(
            encoding="utf-8"
        ).splitlines()

        normalized = [normalize_text(line) for line in lines]

        for index, line in enumerate(normalized):
            services = [
                name for name, pattern in service_patterns.items()
                if pattern.search(line)
            ]

            has_delivery = bool(delivery.search(line))

            if not services and not has_delivery:
                continue

            start = max(0, index - 2)
            end = min(len(lines), index + 3)

            context = " ".join(normalized[start:end])

            if services:
                if definition.search(line):
                    category = "CONTEXT_ONLY"
                elif obligation.search(context) and (
                    direct_obligation.search(context)
                    or scope.search(context)
                ):
                    category = "MANDATORY_EVIDENCE"
                elif scope.search(context):
                    category = "SERVICE_SCOPE"
                else:
                    category = "CONTEXT_ONLY"
            else:
                category = "DELIVERY_ONLY"

            counts[category] += 1

            findings.append({
                "category": category,
                "services": services,
                "filename": filename,
                "line": index + 1,
                "excerpt": " ".join(
                    " ".join(part.split())
                    for part in lines[start:end]
                )[:350],
            })

    return {
        "status": (
            "EVIDENCE_FOUND"
            if any(item["services"] for item in findings)
            else "NO_SERVICE_EVIDENCE"
        ),
        "counts": counts,
        "findings": findings,
    }


def assess_service_obligation(
    modality: str,
    service_evidence: dict,
    *,
    group_id: str | None = None,
    group_scope_confirmed: bool = False,
    universal_training: dict | None = None,
) -> dict:
    """Conservative assessment; never infer absence from missing matches."""

    if modality not in {"TOTAL", "PARTIAL", "UNKNOWN"}:
        raise ValueError("Invalid award modality.")

    findings = service_evidence.get("findings", [])

    if not isinstance(findings, list):
        raise ValueError("Invalid service findings.")

    mandatory = [
        item for item in findings
        if item.get("category") == "MANDATORY_EVIDENCE"
        and item.get("services")
    ]

    scope = [
        item for item in findings
        if item.get("category") == "SERVICE_SCOPE"
        and item.get("services")
    ]

    evidence = mandatory + scope

    universal_confirmed = (
        isinstance(universal_training, dict)
        and universal_training.get("status")
            == "UNIVERSAL_MANDATORY_TRAINING"
        and universal_training.get("universal_scope_confirmed") is True
    )

    if universal_confirmed and modality == "PARTIAL":
        obligation = "MANDATORY"
        reason = (
            "Confirmed mandatory training applies to every "
            "independently selectable award category."
        )
    elif modality == "TOTAL" and mandatory:
        obligation = "MANDATORY"
        reason = (
            "Explicit prohibited-service obligation in a "
            "confirmed all-or-nothing award."
        )
    elif (
        modality == "PARTIAL"
        and group_scope_confirmed
        and group_id
        and mandatory
        and all(
            item.get("group_id") == group_id
            for item in mandatory
        )
    ):
        obligation = "MANDATORY"
        reason = (
            "Explicit prohibited-service obligation tied "
            "to this independently awardable group."
        )
    else:
        obligation = "UNKNOWN"
        reason = (
            "Service evidence does not establish the "
            "obligation for the relevant award group."
        )

    return {
        "obligation": obligation,
        "reason": reason,
        "group_id": group_id,
        "evidence": [
            {
                "filename": item.get("filename"),
                "line": item.get("line"),
                "category": item.get("category"),
                "services": item.get("services", []),
                "excerpt": item.get("excerpt", ""),
            }
            for item in evidence[:12]
        ],
    }


def detect_universal_service_obligation(documents: list[dict]) -> dict:
    """Detect explicit service obligations tied to awarded items."""

    import re
    from pathlib import Path

    obligation = re.compile(
        r"\b(?:proveedor|adjudicatario|contratista)\b"
        r".{0,100}\b(?:debera|deberan|se obliga)\b"
        r".{0,120}\b(?:capacitar|entrenar|ejecutar la capacitacion)\b"
    )

    awarded_item = re.compile(
        r"\b(?:capacitacion|mantencion|mantenimiento|"
        r"instalacion|reparacion)\b"
        r".{0,100}\b(?:item|categoria)\s+adjudicad[oa]s?\b"
    )

    reverse_awarded_item = re.compile(
        r"\b(?:item|categoria)\s+adjudicad[oa]s?\b"
        r".{0,100}\b(?:capacitacion|mantencion|"
        r"mantenimiento|instalacion|reparacion)\b"
    )

    obligations = []
    item_links = []

    for document in documents:
        filename = document["filename"]
        lines = Path(document["text_path"]).read_text(
            encoding="utf-8"
        ).splitlines()

        normalized = [normalize_text(line) for line in lines]

        for index, line in enumerate(normalized):
            context = " ".join(
                normalized[index:min(len(lines), index + 3)]
            )

            record = {
                "filename": filename,
                "line": index + 1,
                "excerpt": " ".join(
                    " ".join(part.split())
                    for part in lines[
                        index:min(len(lines), index + 3)
                    ]
                )[:350],
            }

            if obligation.search(context):
                obligations.append(record)

            if (
                awarded_item.search(context)
                or reverse_awarded_item.search(context)
            ):
                item_links.append(record)

    # Both requirements must be supported by explicit text.
    # This proves a service is tied to awarded items, not
    # necessarily that every independent category is covered.
    confirmed = bool(obligations and item_links)

    return {
        "status": (
            "AWARDED_ITEM_OBLIGATION"
            if confirmed
            else "UNRESOLVED"
        ),
        "universal_scope_confirmed": False,
        "obligations": obligations[:8],
        "item_links": item_links[:8],
        "reason": (
            "Explicit supplier service obligation and "
            "awarded-item linkage found; universal coverage "
            "still requires verification."
            if confirmed
            else "Insufficient explicit awarded-item linkage."
        ),
    }


def confirm_universal_training_obligation(
    documents: list[dict],
    modality: str,
) -> dict:
    """Confirm mandatory training across independently selectable categories."""

    import re
    from pathlib import Path

    patterns = {
        "CATEGORY_SELECTION": re.compile(
            r"no sera requisito de admisibilidad la postulacion "
            r"a todas las categorias"
        ),
        "CATEGORY_COMPLETENESS": re.compile(
            r"categoria ofertada este completa|"
            r"categoria completa"
        ),
        "MANDATORY_TRAINING": re.compile(
            r"proveedor debera.{0,100}"
            r"(?:capacitar|entrenar)"
        ),
        "AWARDED_ITEM_TRAINING": re.compile(
            r"capacitacion del item adjudicado"
        ),
        "PAYMENT_DEPENDENCY": re.compile(
            r"(?:hito 2 e hito 3|hito 3)"
            r".{0,220}"
            r"(?:pago|recepcion conforme)"
        ),
    }

    matches = {name: [] for name in patterns}

    for document in documents:
        lines = Path(document["text_path"]).read_text(
            encoding="utf-8"
        ).splitlines()

        normalized = [normalize_text(line) for line in lines]

        for index in range(len(lines)):
            window = " ".join(
                normalized[index:min(len(lines), index + 5)]
            )

            original = " ".join(
                " ".join(part.split())
                for part in lines[
                    index:min(len(lines), index + 5)
                ]
            )

            for name, pattern in patterns.items():
                if pattern.search(window):
                    matches[name].append({
                        "filename": document["filename"],
                        "line": index + 1,
                        "excerpt": original[:400],
                    })

    required = (
        "CATEGORY_SELECTION",
        "CATEGORY_COMPLETENESS",
        "MANDATORY_TRAINING",
        "AWARDED_ITEM_TRAINING",
        "PAYMENT_DEPENDENCY",
    )

    missing = [
        name for name in required
        if not matches[name]
    ]

    confirmed = modality == "PARTIAL" and not missing

    return {
        "status": (
            "UNIVERSAL_MANDATORY_TRAINING"
            if confirmed
            else "UNRESOLVED"
        ),
        "universal_scope_confirmed": confirmed,
        "missing": missing,
        "evidence": {
            name: matches[name][:2]
            for name in required
        },
    }
