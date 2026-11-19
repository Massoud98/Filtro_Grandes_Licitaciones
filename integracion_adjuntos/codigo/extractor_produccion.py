"""Reusable, verified attachment extraction. No original deletion."""

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from extractor_pdf import extract_pdf
from extractor_word import extract_docx
from extractor_excel import extract_xlsx


class ProductionExtractionError(RuntimeError):
    pass


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest_file(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_legacy_doc(source, helper, staging):
    output = staging / "legacy_doc.txt"

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(helper),
            "-SourcePath",
            str(source),
            "-OutputPath",
            str(output),
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=180,
        check=False,
    )

    if completed.returncode != 0:
        raise ProductionExtractionError(
            "Legacy DOC extraction failed: "
            + (completed.stderr or completed.stdout)[-500:]
        )

    if output.is_symlink() or not output.is_file():
        raise ProductionExtractionError("Legacy DOC output missing.")

    text = output.read_text(encoding="utf-8-sig")

    if not text.strip():
        raise ProductionExtractionError("Legacy DOC text empty.")

    return {
        "format": "doc",
        "method": "microsoft_word_com",
        "total_characters": len(text),
        "text": text,
    }


def extract_document(source, root, staging, tesseract, tessdata):
    extension = source.suffix.lower()

    if extension == ".pdf":
        result = extract_pdf(source, tesseract, tessdata)

        if result["page_count"] < 1:
            raise ProductionExtractionError("PDF contains no pages.")

        if (
            result["native_pages"] + result["ocr_pages"]
            != result["page_count"]
        ):
            raise ProductionExtractionError("PDF page coverage mismatch.")

        pages = result["pages"]

        if len(pages) != result["page_count"]:
            raise ProductionExtractionError("PDF page inventory mismatch.")

        if any(
            page.get("page") != index
            or not isinstance(page.get("text"), str)
            or not page["text"].strip()
            for index, page in enumerate(pages, 1)
        ):
            raise ProductionExtractionError(
                "PDF contains an unreadable or empty page; original preserved."
            )

        text = "\n\n".join(
            f"=== PAGE {page['page']} [{page['method']}] ===\n"
            + page["text"]
            for page in pages
        )

    elif extension == ".docx":
        result = extract_docx(source)
        text = result["text"]

    elif extension == ".xlsx":
        result = extract_xlsx(source)
        text = result["text"]

    elif extension == ".doc":
        helper = (
            Path(__file__).resolve().parent
            / "extractor_doc_legacy.ps1"
        )

        if helper.is_symlink() or not helper.is_file():
            raise ProductionExtractionError("Legacy DOC helper missing.")

        result = extract_legacy_doc(source, helper, staging)
        text = result["text"]

    else:
        raise ProductionExtractionError(
            "Unsupported attachment format: " + extension
        )

    if not isinstance(text, str) or not text.strip():
        raise ProductionExtractionError(
            "No readable text; original must be preserved."
        )

    return result, text


def verify_extracted(output, record, tender_id):
    if output.is_symlink() or not output.is_dir():
        raise ProductionExtractionError("Extraction directory missing or unsafe.")

    entries = list(output.iterdir())

    if {entry.name for entry in entries} != {
        "contenido.json", "contenido.txt"
    }:
        raise ProductionExtractionError("Unexpected extraction files.")

    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ProductionExtractionError("Unsafe extraction output.")

    text_bytes = (output / "contenido.txt").read_bytes()
    text = text_bytes.decode("utf-8")

    if not text.strip():
        raise ProductionExtractionError("Extracted text empty.")

    metadata = json.loads(
        (output / "contenido.json").read_text(encoding="utf-8")
    )

    if not isinstance(metadata, dict):
        raise ProductionExtractionError("Invalid extraction metadata.")

    if (
        metadata.get("status") != "COMPLETE"
        or metadata.get("tender_id") != tender_id
        or metadata.get("control_id") != record["control_id"]
        or metadata.get("source_filename") != record["filename"]
        or metadata.get("source_size_bytes") != record["size_bytes"]
        or str(metadata.get("source_sha256", "")).lower()
            != record["sha256"].lower()
        or metadata.get("text_sha256") != digest_bytes(text_bytes)
        or not isinstance(metadata.get("extraction"), dict)
    ):
        raise ProductionExtractionError("Extraction metadata mismatch.")

    return True


def extract_verified(
    source,
    output_root,
    tender_id,
    record,
    project_root,
    tesseract,
    tessdata,
):
    source = Path(source)
    output_root = Path(output_root)
    project_root = Path(project_root)

    if source.is_symlink() or not source.is_file():
        raise ProductionExtractionError("Source missing or unsafe.")

    if source.name != record["filename"]:
        raise ProductionExtractionError("Source filename mismatch.")

    if source.stat().st_size != record["size_bytes"]:
        raise ProductionExtractionError("Source size mismatch.")

    if digest_file(source).lower() != record["sha256"].lower():
        raise ProductionExtractionError("Source SHA256 mismatch.")

    if output_root.is_symlink() or not output_root.is_dir():
        raise ProductionExtractionError("Unsafe output root.")

    tender_output = output_root / tender_id

    if tender_output.is_symlink():
        raise ProductionExtractionError("Linked tender output.")

    tender_output.mkdir(exist_ok=True)

    output = tender_output / source.stem

    if output.exists() or output.is_symlink():
        verify_extracted(output, record, tender_id)
        return output

    with tempfile.TemporaryDirectory(
        prefix=".extract_",
        dir=str(tender_output),
    ) as temporary:
        staging = Path(temporary)

        result, text = extract_document(
            source, project_root, staging, tesseract, tessdata
        )

        if (
            source.stat().st_size != record["size_bytes"]
            or digest_file(source).lower() != record["sha256"].lower()
        ):
            raise ProductionExtractionError("Source changed during extraction.")

        text_bytes = text.encode("utf-8")

        metadata = {
            "schema_version": 1,
            "status": "COMPLETE",
            "tender_id": tender_id,
            "control_id": record["control_id"],
            "source_filename": record["filename"],
            "source_size_bytes": record["size_bytes"],
            "source_sha256": record["sha256"],
            "text_sha256": digest_bytes(text_bytes),
            "extracted_utc": datetime.now(timezone.utc).isoformat(),
            "extraction": result,
        }

        text_path = staging / "contenido.txt"
        json_path = staging / "contenido.json"

        with text_path.open("xb") as stream:
            stream.write(text_bytes)
            stream.flush()
            os.fsync(stream.fileno())

        with json_path.open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

        # Legacy DOC conversion creates an intermediate file in staging.
        legacy = staging / "legacy_doc.txt"
        if legacy.exists():
            legacy.unlink()

        verify_extracted(staging, record, tender_id)

        os.rename(staging, output)

    verify_extracted(output, record, tender_id)

    return output
