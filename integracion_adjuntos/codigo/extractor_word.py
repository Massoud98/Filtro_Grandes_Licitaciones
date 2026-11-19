"""Production DOCX adapter using the application's canonical reader."""

from pathlib import Path

from aplicacion.servicios.lector_adjuntos import extract_docx as read_docx


class WordExtractionError(RuntimeError):
    pass


def extract_docx(path):
    source = Path(path)

    if source.is_symlink() or not source.is_file():
        raise WordExtractionError("Unsafe or missing DOCX.")

    try:
        document = read_docx(source)
        segments = document["segments"]
        text_parts = []
        paragraphs = []
        tables = []
        blocks = []

        for segment in segments:
            kind = segment["kind"]
            text = segment["text"]

            if kind == "docx_paragraph":
                paragraphs.append(text)
                blocks.append({"type": "paragraph", "text": text})
                text_parts.append(text)

            elif kind == "docx_table_row":
                blocks.append({
                    "type": "table_row",
                    "row": segment["row"],
                    "cells": segment["cells"],
                })
                text_parts.append(text)

            else:
                blocks.append({
                    "type": kind,
                    "text": text,
                    **{
                        key: value
                        for key, value in segment.items()
                        if key not in {"kind", "text"}
                    },
                })
                text_parts.append(text)

        text = "\n".join(text_parts)

        if not text.strip():
            raise WordExtractionError("DOCX contains no readable text.")

        return {
            "format": "docx",
            "paragraph_count": len(paragraphs),
            "table_count": sum(
                block["type"] == "table_row"
                for block in blocks
            ),
            "total_characters": len(text),
            "paragraphs": paragraphs,
            "tables": tables,
            "blocks": blocks,
            "text": text,
        }

    except WordExtractionError:
        raise
    except Exception as exc:
        raise WordExtractionError(
            "DOCX extraction failed."
        ) from exc
