"""Structured, in-memory analysis of verified local attachments."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from aplicacion.servicios.descargador_adjuntos import AttachmentRecord
from aplicacion.servicios.lector_adjuntos import extract_attachment


def analyze_verified_attachments(
    records: Iterable[AttachmentRecord],
    *,
    extractor: Callable | None = None,
    ocr_config: dict | None = None,
) -> dict:
    """Summarize extraction without writing files or classifying tenders.

    The caller must first verify records with
    verify_attachment_integrity(). This function does not independently
    authenticate their source files.
    """
    if extractor is None:
        extractor = extract_attachment

    grouped = defaultdict(list)

    for record in records:
        grouped[record.licitacion].append(record)

    tenders = {}

    for tender_id, attachments in sorted(grouped.items()):
        documents = []

        for record in attachments:
            path = Path(record.source_path)

            document = {
                "filename": record.filename,
                "status": "pending",
                "method": None,
                "searchable_characters": 0,
                "ocr_pages": 0,
                "pages_requiring_ocr": [],
                "requires_human_review": False,
                "error_type": None,
            }

            try:
                result = extractor(path, ocr_config=ocr_config)

                if not isinstance(result, dict):
                    raise ValueError("Extractor returned an invalid result.")

                text = result.get("searchable_text")

                if not isinstance(text, str):
                    raise ValueError("Extractor returned invalid text.")

                segments = result.get("segments", [])

                if not isinstance(segments, list):
                    raise ValueError("Extractor returned invalid segments.")

                pending = result.get("pages_requiring_ocr", [])

                if not isinstance(pending, list):
                    raise ValueError("Extractor returned invalid OCR metadata.")

                ocr_pages = sum(
                    isinstance(segment, dict)
                    and segment.get("kind") == "pdf_ocr"
                    for segment in segments
                )

                document.update({
                    "status": (
                        "extracted" if text.strip()
                        else "empty"
                    ),
                    "method": result.get("method"),
                    "searchable_characters": len(text),
                    "ocr_pages": ocr_pages,
                    "pages_requiring_ocr": pending,
                    "requires_human_review": bool(
                        result.get("requires_human_review")
                        or pending
                        or ocr_pages
                        or not text.strip()
                    ),
                })

            except Exception as exc:
                document.update({
                    "status": "error",
                    "requires_human_review": True,
                    "error_type": type(exc).__name__,
                })

            documents.append(document)

        counts = {
            "total": len(documents),
            "extracted": sum(
                doc["status"] == "extracted"
                for doc in documents
            ),
            "empty": sum(
                doc["status"] == "empty"
                for doc in documents
            ),
            "errors": sum(
                doc["status"] == "error"
                for doc in documents
            ),
            "ocr_pages": sum(
                doc["ocr_pages"]
                for doc in documents
            ),
        }

        if counts["errors"] or counts["empty"]:
            status = "partial"
        else:
            status = "extracted"

        tenders[tender_id] = {
            "status": status,
            "counts": counts,
            "requires_human_review": any(
                doc["requires_human_review"]
                for doc in documents
            ),
            "requirements_interpreted": False,
            "documents": documents,
        }

    return {
        "schema_version": 1,
        "tenders": tenders,
        "totals": {
            "tenders": len(tenders),
            "documents": sum(
                tender["counts"]["total"]
                for tender in tenders.values()
            ),
            "extracted": sum(
                tender["counts"]["extracted"]
                for tender in tenders.values()
            ),
            "errors": sum(
                tender["counts"]["errors"]
                for tender in tenders.values()
            ),
        },
    }