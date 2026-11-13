import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

manifest = Path(sys.argv[1])
output = Path(sys.argv[2])

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def extract_container(container, location):
    blocks = []
    for child in (container if hasattr(container, "iterchildren") else container._element).iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, container)
            if paragraph.text.strip():
                blocks.append({
                    "type": "paragraph",
                    "location": location,
                    "text": paragraph.text
                })
        elif child.tag == qn("w:tbl"):
            table = Table(child, container)
            rows = []
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    cells.append(cell.text)
                rows.append(cells)
            blocks.append({
                "type": "table",
                "location": location,
                "rows": rows
            })
    return blocks

with manifest.open("r", encoding="utf-8-sig", newline="") as stream:
    rows = [
        row for row in csv.DictReader(stream)
        if Path(row["filename"]).suffix.lower() == ".docx"
    ]

if len(rows) != 17:
    raise SystemExit("STOP: Expected exactly 17 DOCX records")

if output.exists():
    raise SystemExit("STOP: Output directory already exists")

output.mkdir(parents=True)

audit = []

for row in rows:
    path = Path(row["source_path"])
    if not path.is_file():
        raise SystemExit(f"STOP: Missing DOCX: {path}")

    document = Document(path)
    blocks = extract_container(document.element.body, "body")

    for section_index, section in enumerate(document.sections, start=1):
        blocks.extend(
            extract_container(
                section.header,
                f"header_section_{section_index}"
            )
        )
        blocks.extend(
            extract_container(
                section.footer,
                f"footer_section_{section_index}"
            )
        )

    characters = sum(
        len(block["text"]) if block["type"] == "paragraph"
        else sum(len(cell) for table_row in block["rows"] for cell in table_row)
        for block in blocks
    )

    result = {
        "licitacion": row["licitacion"],
        "source_name": row["filename"],
        "source_path": str(path),
        "sha256": sha256(path),
        "source_bytes": path.stat().st_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "extraction_status": "EXTRACTED_REVIEW_REQUIRED",
        "blocks": blocks,
        "characters": characters,
        "notes": [
            "Text and tables extracted; semantic accuracy not independently verified.",
            "Embedded images, drawings and text boxes may contain additional content.",
            "Repeated merged table cells may appear more than once."
        ]
    }

    lic_dir = output / row["licitacion"]
    lic_dir.mkdir(exist_ok=True)

    target = lic_dir / (result["sha256"] + ".docx.json")
    if target.exists():
        raise SystemExit(f"STOP: Output collision: {target}")

    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)

    audit.append({
        "licitacion": row["licitacion"],
        "filename": row["filename"],
        "status": result["extraction_status"],
        "sha256": result["sha256"],
        "blocks": len(blocks),
        "characters": characters,
        "json_path": str(target)
    })

    print(
        row["licitacion"],
        "EXTRACTED_REVIEW_REQUIRED",
        f"blocks={len(blocks)}",
        f"characters={characters}",
        row["filename"]
    )

with (output / "audit.csv").open("x", encoding="utf-8-sig", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(audit[0]))
    writer.writeheader()
    writer.writerows(audit)

print()
print("=== STEP 157C SUMMARY ===")
print("Documents:", len(audit))
print("Total blocks:", sum(item["blocks"] for item in audit))
print("Total characters:", sum(item["characters"] for item in audit))
print("Audit:", output / "audit.csv")
print("Original DOCX files preserved.")