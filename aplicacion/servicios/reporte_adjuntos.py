"""Validated, non-overwriting attachment report persistence."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = 1

class AttachmentReportError(RuntimeError):
    """Invalid attachment report or failed publication."""


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def validate_report(report: dict) -> None:
    """Validate evidence and tender-summary consistency."""
    if not isinstance(report, dict):
        raise AttachmentReportError("Report root must be an object.")

    if type(report.get("schema_version")) is not int or report["schema_version"] != SCHEMA_VERSION:
        raise AttachmentReportError("Unsupported schema version.")

    documents = report.get("documents")
    tenders = report.get("tenders")

    if not isinstance(documents, list) or not isinstance(tenders, dict):
        raise AttachmentReportError("Invalid report collections.")

    identities = set()
    actual = Counter()
    extracted = Counter()
    empty = Counter()
    errors = Counter()
    ocr_pages = Counter()
    review = Counter()

    for document in documents:
        if not isinstance(document, dict):
            raise AttachmentReportError("Invalid document record.")

        tender = document.get("licitacion")
        filename = document.get("filename")
        digest = document.get("sha256")
        source_bytes = document.get("source_bytes")
        status = document.get("status")
        text = document.get("searchable_text")
        segments = document.get("segments")
        extraction_review = document.get("requires_extraction_review")
        document_review = document.get("requires_document_review")
        pending = document.get("pages_requiring_ocr")
        counted_ocr = document.get("ocr_pages")

        if not _nonempty(tender) or not _nonempty(filename):
            raise AttachmentReportError("Invalid document identity.")

        identity = (tender, filename)
        if identity in identities:
            raise AttachmentReportError("Duplicate document identity.")
        identities.add(identity)

        if not (
            isinstance(digest, str)
            and len(digest) == 64
            and all(c in "0123456789abcdefABCDEF" for c in digest)
        ):
            raise AttachmentReportError("Invalid SHA256.")

        if not _integer(source_bytes, 1):
            raise AttachmentReportError("Invalid source size.")

        if status not in ("extracted", "empty", "error"):
            raise AttachmentReportError("Invalid extraction status.")

        if not isinstance(text, str) or not isinstance(segments, list):
            raise AttachmentReportError("Invalid extraction evidence.")

        if type(extraction_review) is not bool or type(document_review) is not bool:
            raise AttachmentReportError("Invalid review flags.")

        if not isinstance(pending, list) or not _integer(counted_ocr):
            raise AttachmentReportError("Invalid OCR metadata.")

        if any(not _integer(page, 1) for page in pending):
            raise AttachmentReportError("Invalid pending OCR page.")

        indexes = set()
        observed_ocr = 0

        for segment in segments:
            if not isinstance(segment, dict):
                raise AttachmentReportError("Invalid evidence segment.")

            index = segment.get("index")
            if not _integer(index):
                raise AttachmentReportError("Invalid segment index.")
            if index in indexes:
                raise AttachmentReportError("Duplicate segment index.")
            indexes.add(index)

            if not _nonempty(segment.get("locator")):
                raise AttachmentReportError("Invalid segment locator.")
            if not _nonempty(segment.get("method")):
                raise AttachmentReportError("Invalid segment method.")
            if not isinstance(segment.get("text"), str):
                raise AttachmentReportError("Invalid segment text.")

            observed_ocr += segment["method"] == "pdf_ocr"

        if observed_ocr != counted_ocr:
            raise AttachmentReportError("OCR count mismatch.")

        if status == "extracted" and not text.strip():
            raise AttachmentReportError("Extracted document has no text.")

        if status == "empty" and text.strip():
            raise AttachmentReportError("Empty document contains text.")

        if status == "error" and (text or segments):
            raise AttachmentReportError("Failed extraction contains evidence.")

        if (status != "extracted" or counted_ocr or pending) and not extraction_review:
            raise AttachmentReportError("Missing extraction review flag.")

        actual[tender] += 1
        extracted[tender] += status == "extracted"
        empty[tender] += status == "empty"
        errors[tender] += status == "error"
        ocr_pages[tender] += counted_ocr
        review[tender] += extraction_review or document_review

    if set(actual) != set(tenders):
        raise AttachmentReportError("Tender identities do not match documents.")

    for tender, summary in tenders.items():
        if not _nonempty(tender) or not isinstance(summary, dict):
            raise AttachmentReportError("Invalid tender summary.")

        counts = summary.get("counts")
        if not isinstance(counts, dict):
            raise AttachmentReportError("Missing tender counts.")

        expected = {
            "total": actual[tender],
            "extracted": extracted[tender],
            "empty": empty[tender],
            "errors": errors[tender],
            "ocr_pages": ocr_pages[tender],
        }

        if any(type(counts.get(key)) is not int or counts[key] != value
               for key, value in expected.items()):
            raise AttachmentReportError("Tender count mismatch.")

        expected_status = (
            "partial" if empty[tender] or errors[tender] else "extracted"
        )
        if summary.get("status") != expected_status:
            raise AttachmentReportError("Tender status mismatch.")

        if summary.get("requires_human_review") is not bool(review[tender]):
            raise AttachmentReportError("Tender review mismatch.")

        if summary.get("requirements_interpreted") is not False:
            raise AttachmentReportError("Requirements interpretation is unsupported.")


def save_report_new(report: dict, destination: str | Path) -> Path:
    """Publish a complete JSON file without replacing an existing report."""
    validate_report(report)
    target = Path(destination)

    if not target.parent.is_dir():
        raise AttachmentReportError("Report directory does not exist.")

    try:
        payload = (
            json.dumps(report, ensure_ascii=False, indent=2,
                       sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise AttachmentReportError("Report cannot be serialized.") from exc

    temporary = None
    published = False

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".attachment_report_",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        os.link(temporary, target)
        published = True

    except FileExistsError as exc:
        raise AttachmentReportError(
            "Report already exists; overwrite refused."
        ) from exc
    except OSError as exc:
        raise AttachmentReportError(
            f"Report publication failed: {type(exc).__name__}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                if not published:
                    raise AttachmentReportError(
                        "Temporary report cleanup failed."
                    )

    return target
