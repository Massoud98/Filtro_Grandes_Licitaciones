"""Convert an existing unified document index into a validated report."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from aplicacion.servicios.reporte_adjuntos import validate_report


SUPPORTED_STATUSES = frozenset({
    "COMPLETE_TEXT_EXTRACTION",
    "EXTRACTED_REVIEW_REQUIRED",
    "REVIEW_REQUIRED",
})


class AttachmentIndexAdapterError(RuntimeError):
    """Raised when a unified document index cannot be converted."""


def adapt_unified_index(index: dict) -> dict:
    """Convert verified index data without modifying the input.

    The caller must independently verify the source attachments against
    the manifest and integrity index before trusting this report.
    """
    if not isinstance(index, dict):
        raise AttachmentIndexAdapterError("Index root must be an object.")

    sources = index.get("documents")

    if not isinstance(sources, list):
        raise AttachmentIndexAdapterError("Index documents must be a list.")

    converted = []
    grouped = defaultdict(list)

    for source in sources:
        if not isinstance(source, dict):
            raise AttachmentIndexAdapterError("Invalid source document.")

        status = source.get("extraction_status")

        if status not in SUPPORTED_STATUSES:
            raise AttachmentIndexAdapterError(
                "Unsupported source extraction status."
            )

        text = source.get("searchable_text")
        segments = source.get("segments")

        if not isinstance(text, str) or not text.strip():
            raise AttachmentIndexAdapterError(
                "Source document has no searchable text."
            )

        if not isinstance(segments, list) or not segments:
            raise AttachmentIndexAdapterError(
                "Source document has no evidence segments."
            )

        document_review = source.get("requires_human_review")

        if type(document_review) is not bool:
            raise AttachmentIndexAdapterError(
                "Invalid source document review flag."
            )

        ocr_pages = sum(
            isinstance(segment, dict)
            and segment.get("method") == "pdf_ocr"
            for segment in segments
        )

        document = {
            "licitacion": source.get("licitacion"),
            "filename": source.get("filename"),
            "sha256": source.get("sha256"),
            "source_bytes": source.get("source_bytes"),
            "status": "extracted",
            "searchable_text": text,
            "segments": deepcopy(segments),
            "requires_extraction_review": bool(ocr_pages),
            "requires_document_review": document_review,
            "pages_requiring_ocr": [],
            "ocr_pages": ocr_pages,
        }

        converted.append(document)
        grouped[document["licitacion"]].append(document)

    tenders = {}

    for tender_id, documents in grouped.items():
        tenders[tender_id] = {
            "status": "extracted",
            "counts": {
                "total": len(documents),
                "extracted": len(documents),
                "empty": 0,
                "errors": 0,
                "ocr_pages": sum(
                    document["ocr_pages"]
                    for document in documents
                ),
            },
            "requires_human_review": any(
                document["requires_extraction_review"]
                or document["requires_document_review"]
                for document in documents
            ),
            "requirements_interpreted": False,
        }

    report = {
        "schema_version": 1,
        "documents": converted,
        "tenders": tenders,
    }

    validate_report(report)
    return report