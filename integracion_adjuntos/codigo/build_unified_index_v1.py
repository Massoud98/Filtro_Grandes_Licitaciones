import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

manifest, native, ocr, docx, output = map(Path, sys.argv[1:6])

sources = {
    "NATIVE_PDF": native,
    "OCR_PDF": ocr,
    "DOCX": docx,
}

expected_status = {
    "NATIVE_PDF": "COMPLETE_TEXT_EXTRACTION",
    "OCR_PDF": "REVIEW_REQUIRED",
    "DOCX": "EXTRACTED_REVIEW_REQUIRED",
}

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()

with manifest.open("r", encoding="utf-8-sig", newline="") as stream:
    rows = list(csv.DictReader(stream))

if len(rows) != 27:
    raise SystemExit("STOP: Expected exactly 27 manifest rows")

records = defaultdict(list)

for method, folder in sources.items():
    for path in sorted(folder.rglob("*.json")):
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)

        digest = data.get("sha256")

        if not isinstance(digest, str) or len(digest) != 64:
            raise SystemExit(f"STOP: Invalid extraction hash: {path}")

        records[digest].append({
            "method": method,
            "path": str(path),
            "data": data,
        })

if sum(map(len, records.values())) != 30:
    raise SystemExit("STOP: Expected 30 extraction records")

documents = []
audit = []
seen = set()

for row in rows:
    original = Path(row["source_path"])

    if not original.is_file():
        raise SystemExit(f"STOP: Missing original: {original}")

    digest = sha256(original)

    if digest in seen:
        raise SystemExit("STOP: Duplicate manifest content hash")

    seen.add(digest)
    candidates = records.get(digest, [])

    if not candidates:
        raise SystemExit(f"STOP: Missing extraction: {original.name}")

    extension = original.suffix.lower()

    if extension == ".docx":
        selected_method = "DOCX"
    elif extension == ".pdf":
        selected_method = (
            "OCR_PDF"
            if any(c["method"] == "OCR_PDF" for c in candidates)
            else "NATIVE_PDF"
        )
    else:
        raise SystemExit(f"STOP: Unsupported extension: {extension}")

    selected = [
        c for c in candidates
        if c["method"] == selected_method
    ]

    if len(selected) != 1:
        raise SystemExit(f"STOP: Ambiguous extraction: {original.name}")

    chosen = selected[0]
    data = chosen["data"]
    status = data.get("extraction_status")

    if status != expected_status[selected_method]:
        raise SystemExit(
            f"STOP: Unexpected status for {original.name}: {status!r}"
        )

    if data.get("licitacion") != row["licitacion"]:
        raise SystemExit(f"STOP: Licitacion mismatch: {original.name}")

    if data.get("source_bytes") != original.stat().st_size:
        raise SystemExit(f"STOP: Source size mismatch: {original.name}")

    segments = []

    if selected_method in ("NATIVE_PDF", "OCR_PDF"):
        for index, segment in enumerate(data["segments"], 1):
            text = segment.get("text")
            if not isinstance(text, str):
                raise SystemExit("STOP: Invalid PDF segment text")

            segments.append({
                "index": index,
                "locator": segment.get("locator"),
                "method": segment.get("method"),
                "text": text,
            })
    else:
        for index, block in enumerate(data["blocks"], 1):
            kind = block.get("type")

            if kind == "paragraph":
                text = block.get("text")
                if not isinstance(text, str):
                    raise SystemExit("STOP: Invalid DOCX paragraph")

            elif kind == "table":
                table_rows = block.get("rows")
                if not isinstance(table_rows, list):
                    raise SystemExit("STOP: Invalid DOCX table")

                lines = []
                for table_row in table_rows:
                    if not isinstance(table_row, list):
                        raise SystemExit("STOP: Invalid DOCX table row")
                    if not all(isinstance(cell, str) for cell in table_row):
                        raise SystemExit("STOP: Invalid DOCX table cell")
                    lines.append(" | ".join(table_row))

                text = "\n".join(lines)

            else:
                raise SystemExit(f"STOP: Unknown DOCX block: {kind!r}")

            segments.append({
                "index": index,
                "locator": block.get("location"),
                "method": "DOCX_" + kind.upper(),
                "text": text,
            })

    searchable_text = "\n\n".join(
        s["text"] for s in segments if s["text"].strip()
    )

    if not searchable_text.strip():
        raise SystemExit(f"STOP: Empty text: {original.name}")

    alternates = [
        {
            "method": c["method"],
            "path": c["path"],
            "status": c["data"].get("extraction_status"),
        }
        for c in candidates
        if c is not chosen
    ]

    document = {
        "licitacion": row["licitacion"],
        "filename": row["filename"],
        "sha256": digest,
        "source_path": str(original),
        "source_url": row.get("url", ""),
        "source_origin_url": row.get("source_origin_url", ""),
        "source_bytes": original.stat().st_size,
        "extraction_method": selected_method,
        "extraction_status": status,
        "extraction_json": chosen["path"],
        "alternate_extractions": alternates,
        "segments": segments,
        "searchable_text": searchable_text,
        "characters": len(searchable_text),
        "requires_human_review": selected_method != "NATIVE_PDF",
    }

    documents.append(document)

    audit.append({
        "licitacion": row["licitacion"],
        "filename": row["filename"],
        "sha256": digest,
        "method": selected_method,
        "status": status,
        "segments": len(segments),
        "characters": len(searchable_text),
        "alternate_extractions": len(alternates),
        "requires_human_review": document["requires_human_review"],
    })

methods = Counter(d["extraction_method"] for d in documents)

if methods != Counter({
    "NATIVE_PDF": 7,
    "OCR_PDF": 3,
    "DOCX": 17,
}):
    raise SystemExit(f"STOP: Wrong method distribution: {methods}")

if len(documents) != 27 or len(seen) != 27:
    raise SystemExit("STOP: Document accounting mismatch")

if set(records) != seen:
    raise SystemExit("STOP: Unmatched extraction hashes")

if sum(len(d["alternate_extractions"]) for d in documents) != 3:
    raise SystemExit("STOP: Expected three alternate extractions")

if output.exists():
    raise SystemExit("STOP: Output already exists")

summary = {
    "documents": len(documents),
    "unique_sha256": len(seen),
    "methods": dict(methods),
    "alternate_extractions": 3,
    "total_characters": sum(d["characters"] for d in documents),
    "human_review_documents": sum(
        d["requires_human_review"] for d in documents
    ),
}

output.mkdir(parents=True, exist_ok=False)

with (output / "documents.json").open("x", encoding="utf-8") as stream:
    json.dump({
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents": documents,
    }, stream, ensure_ascii=False, indent=2)

with (output / "audit.csv").open(
    "x", encoding="utf-8-sig", newline=""
) as stream:
    writer = csv.DictWriter(stream, fieldnames=list(audit[0]))
    writer.writeheader()
    writer.writerows(audit)

with (output / "summary.json").open("x", encoding="utf-8") as stream:
    json.dump(summary, stream, ensure_ascii=False, indent=2)

print("=== STEP 158F — SUCCESS ===")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("Output:", output)
print("Existing extraction files preserved.")