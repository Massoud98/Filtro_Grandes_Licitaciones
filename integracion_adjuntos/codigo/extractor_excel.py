"""Excel worksheet text extraction.

Reads workbooks without modifying them.
Preserves sheet names, coordinates, values and formulas.
"""

from pathlib import Path

from openpyxl import load_workbook


class ExcelExtractionError(RuntimeError):
    pass


def extract_xlsx(path):
    path = Path(path)

    if not path.is_file() or path.is_symlink():
        raise ExcelExtractionError("Unsafe or missing XLSX.")

    workbook = None

    try:
        workbook = load_workbook(
            filename=str(path),
            read_only=True,
            data_only=False,
            keep_links=False,
        )

        sheets = []
        text_parts = []

        for worksheet in workbook.worksheets:
            cells = []

            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue

                    value = str(cell.value)

                    cells.append({
                        "coordinate": cell.coordinate,
                        "value": value,
                    })

                    text_parts.append(
                        f"{worksheet.title}!{cell.coordinate}: {value}"
                    )

            sheets.append({
                "name": worksheet.title,
                "cell_count": len(cells),
                "cells": cells,
            })

        return {
            "format": "xlsx",
            "sheet_count": len(sheets),
            "total_characters": sum(len(x) for x in text_parts),
            "sheets": sheets,
            "text": "\n".join(text_parts),
        }

    except Exception as exc:
        raise ExcelExtractionError(
            f"{type(exc).__name__}: {exc}"
        ) from exc

    finally:
        if workbook is not None:
            workbook.close()
