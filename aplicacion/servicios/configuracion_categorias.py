"""Load and validate external category configuration."""

import json
import re
import sys
from pathlib import Path


EXCLUDED_PREFIXES = frozenset({
    "70", "71", "72", "73", "76", "77", "78",
    "80", "81", "82", "83", "84", "85", "86",
    "90", "91", "92", "93", "94",
})


def category_directory(executable=None, frozen=None, source=None):
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    if frozen:
        base = Path(executable or sys.executable).resolve().parent
        external = base / "Filtro"

        if external.exists():
            return external

        bundled = Path(
            getattr(sys, "_MEIPASS", base)
        ) / "Filtro"

        return bundled

    base = Path(source or __file__).resolve().parents[2]
    return base / "Filtro"


def _read_codes(path, allow_empty):
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ValueError(
            f"Category configuration unavailable: {path.name}"
        ) from exc

    codes = [line.strip() for line in lines]

    if allow_empty and not codes:
        return frozenset()

    if not codes or any(not code for code in codes):
        raise ValueError(f"Empty or blank entries: {path.name}")

    if not all(re.fullmatch(r"[0-9]{8}", code) for code in codes):
        raise ValueError(f"Invalid category code: {path.name}")

    if len(codes) != len(set(codes)):
        raise ValueError(f"Duplicate category code: {path.name}")

    return frozenset(codes)


def load_editable_categories(directory=None):
    directory = Path(directory) if directory else category_directory()

    catalogue_path = directory / "catalogo_oficial_completo.json"
    total_path = directory / "categorias_exclusion_total.txt"
    passive_path = directory / "categorias_exclusion_pasiva.txt"

    try:
        catalogue = json.loads(
            catalogue_path.read_text(encoding="utf-8-sig")
        )
        records = catalogue["records"]

        if not isinstance(records, list):
            raise ValueError("Catalogue records must be a list.")

        official_codes = [str(item["categoryCode"]) for item in records]

    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Official category catalogue unavailable or invalid."
        ) from exc

    if (
        len(official_codes) != 2031
        or len(set(official_codes)) != 2031
        or not all(
            re.fullmatch(r"[0-9]{8}", code)
            for code in official_codes
        )
    ):
        raise ValueError("Official category catalogue failed validation.")

    official = frozenset(official_codes)
    total = _read_codes(total_path, allow_empty=False)
    passive = _read_codes(passive_path, allow_empty=True)

    if total & passive:
        raise ValueError("Total/passive exclusion overlap detected.")

    if (total | passive) - official:
        raise ValueError("Exclusion list contains non-catalogue codes.")

    return {
        "directory": directory,
        "official": official,
        "total_excluded": total,
        "passive_excluded": passive,
        "prefixes": EXCLUDED_PREFIXES,
    }