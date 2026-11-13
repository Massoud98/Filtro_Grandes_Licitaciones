"""Windows launcher for the daily Mercado Público tender workflow."""
from __future__ import annotations
import getpass
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

APP_SERVICE = "FiltroGrandesLicitaciones"
DETAIL_INTERVAL_SECONDS = 2.0


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return (
            Path.home()
            / "Documents"
            / "Filtro_Grandes_Licitaciones"
        )
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(
            getattr(
                sys,
                "_MEIPASS",
                Path(sys.executable).resolve().parent,
            )
        )
    return Path(__file__).resolve().parent


ROOT = project_root()
RESOURCE_ROOT = resource_root()


def initialize_data_directory() -> None:
    """Initialize persistent application storage."""

    directories = [
        ROOT / "configuracion",
        ROOT / "datos" / "adjuntos",
        ROOT / "datos" / "filtrados",
        ROOT / "datos" / "originales",
        ROOT / "datos" / "reportes",
        ROOT / "datos" / "simulaciones",
        ROOT / "datos" / "tipos_cambio",
        ROOT / "respaldos" / "ejecuciones",
    ]

    ROOT.mkdir(parents=True, exist_ok=True)

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    bundled_config = (
        RESOURCE_ROOT
        / "configuracion"
        / "filtros.json"
    )

    target_config = (
        ROOT
        / "configuracion"
        / "filtros.json"
    )

    if not target_config.exists():
        if not bundled_config.is_file():
            raise FileNotFoundError(
                "Bundled filtering configuration unavailable."
            )

        shutil.copy2(bundled_config, target_config)
        print("Default filtering configuration installed.")

    if not target_config.is_file():
        raise RuntimeError(
            "Filtering configuration path is not a file."
        )

    print("Application directory:", ROOT)


# Configure persistent paths before importing services.
os.environ["FILTRO_LICITACIONES_ROOT"] = str(ROOT)

initialize_data_directory()
os.chdir(ROOT)

def _keyring():
    import keyring
    backend = keyring.get_keyring()
    identity = backend.__class__.__module__ + "." + backend.__class__.__name__
    if "Windows" not in identity:
        raise RuntimeError("Windows Credential Manager unavailable; refusing insecure credential storage.")
    return keyring


def credential(username: str, prompt: str, required: bool, kr=None) -> str | None:
    kr = kr or _keyring()
    value = kr.get_password(APP_SERVICE, username)
    if value:
        print(f"Saved credential found: {username}")
        return value
    value = getpass.getpass(prompt + (" (required): " if required else " (Enter to skip): ")).strip()
    if not value:
        if required:
            raise RuntimeError(f"Missing required credential: {username}")
        return None
    kr.set_password(APP_SERVICE, username, value)
    print(f"Credential saved in Windows Credential Manager: {username}")
    return value


def backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = ROOT / "respaldos" / "ejecuciones" / path.parent.name / stamp / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    print("Previous output preserved:", destination)
    return destination


def load_existing_publication(path: Path, expected_date: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("Existing publication list is unreadable; it was not overwritten.") from None
    if not isinstance(data, dict) or data.get("fecha") != expected_date or not isinstance(data.get("licitaciones"), list):
        raise RuntimeError("Existing publication list has invalid date or structure; it was not overwritten.")
    return data


def load_optional_attachment_report():
    """Load an explicitly selected attachment report, if configured."""
    report_path = os.environ.get(
        "FILTRO_ATTACHMENT_REPORT_PATH"
    )
    report_date = os.environ.get(
        "FILTRO_ATTACHMENT_REPORT_DATE"
    )

    if report_path is None and report_date is None:
        return None

    if not report_path or not report_date:
        raise ValueError(
            "Both attachment report environment variables are required."
        )

    from aplicacion.servicios.reporte_adjuntos import validate_report

    path = Path(report_path).expanduser()

    if not path.is_file() or path.is_symlink():
        raise ValueError(
            "Selected attachment report is missing or unsafe."
        )

    report = json.loads(path.read_text(encoding="utf-8"))
    validate_report(report)

    return report, report_date


def run_pipeline():
    # Imports occur after setting FILTRO_LICITACIONES_ROOT.
    from aplicacion.servicios.mercado_publico import CARPETA_ORIGINALES, consultar_licitaciones, obtener_fecha_ayer
    from aplicacion.servicios.detalles_licitaciones import obtener_detalles
    from aplicacion.servicios.generador_excel import generar_excel_original
    from aplicacion.servicios.filtros_preliminares import aplicar_filtros
    from aplicacion.servicios.generador_excel_filtrado import generar_excel_filtrado

    attachment_selection = load_optional_attachment_report()

    kr = _keyring()
    api_mp = credential("API_MP", "Mercado Público API ticket", True, kr)
    bc_token = credential("BCCH_API_TOKEN", "Banco Central API token", False, kr)
    os.environ["API_MP"] = api_mp
    if bc_token:
        os.environ["BCCH_API_TOKEN"] = bc_token
    else:
        os.environ.pop("BCCH_API_TOKEN", None)
        print("WARNING: Banco Central token absent; foreign-currency conversion may be unavailable.")

    fecha = obtener_fecha_ayer()
    fecha_iso = fecha.isoformat()
    if attachment_selection is not None:
        attachment_report_date = attachment_selection[1]
        try:
            parsed_attachment_date = date.fromisoformat(
                attachment_report_date
            )
        except ValueError as exc:
            raise ValueError(
                "Invalid attachment report date."
            ) from exc
        if (
            parsed_attachment_date.isoformat() != attachment_report_date
            or attachment_report_date != fecha_iso
        ):
            raise ValueError(
                "Attachment report date does not match daily run."
            )
    folder = CARPETA_ORIGINALES / fecha_iso
    list_path = folder / "licitaciones_publicadas.json"

    print("\n=== DAILY TENDER RUN ===")
    print("Publication date:", fecha_iso)
    if list_path.exists():
        published = load_existing_publication(list_path, fecha_iso)
        print("Reusing existing publication list:", len(published["licitaciones"]))
        print("To refresh it, archive/remove licitaciones_publicadas.json first.")
    else:
        published = consultar_licitaciones(fecha=fecha, ticket=api_mp)

    ids = [str(x.get("CodigoExterno") or "").strip() for x in published["licitaciones"]]
    if attachment_selection is not None:
        from aplicacion.servicios.politica_adjuntos_diarios import (
            validate_daily_attachment_report,
        )
        attachment_report, attachment_report_date = attachment_selection
        validate_daily_attachment_report(
            attachment_report,
            report_date=attachment_report_date,
            publication_date=fecha_iso,
            daily_tender_ids=ids,
        )
        print("Selected attachment report validated for daily run.")

    folder.mkdir(parents=True, exist_ok=True)

    if not ids:
        print("No published tenders found. No Excel files generated.")
        return {"status": "NO_TENDERS", "published": 0}

    print("\n=== DETAIL RETRIEVAL ===")
    detail_result = obtener_detalles(fecha_iso, intervalo=DETAIL_INTERVAL_SECONDS)
    detail_path = folder / "detalles_licitaciones.json"
    try:
        progress = json.loads(detail_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("Could not read detail progress; Excel generation stopped.") from None

    details = progress.get("detalles", {})
    errors = progress.get("errores", {})
    if (progress.get("fecha") != fecha_iso or progress.get("ids") != ids
            or not isinstance(details, dict) or set(details) != set(ids) or errors):
        print("Detail retrieval incomplete. Progress is saved and can be resumed.")
        print("Retrieved:", len(details) if isinstance(details, dict) else 0, "/", len(ids))
        print("Recorded errors:", len(errors) if isinstance(errors, dict) else 0)
        return {"status": "DETAILS_INCOMPLETE", "published": len(ids), "details": len(details)}

    original = folder / f"Licitaciones_Mercado_Publico_{fecha_iso}.xlsx"
    backup_existing(original)
    print("\n=== ORIGINAL EXCEL ===")
    original_result = generar_excel_original(fecha_iso)

    filters = folder / "filtros_preliminares.json"
    backup_existing(filters)
    print("\n=== APPLYING FILTERS ===")
    filter_result = aplicar_filtros(fecha_iso)

    filtered = folder / f"Licitaciones_Filtradas_{fecha_iso}.xlsx"
    backup_existing(filtered)
    print("\n=== FILTERED EXCEL ===")
    if attachment_selection is None:
        filtered_result = generar_excel_filtrado(fecha_iso)
    else:
        filtered_result = generar_excel_filtrado(
            fecha_iso,
            attachment_report=attachment_selection[0],
        )

    summary = filter_result.get("resumen", {})
    result = {
        "status": "SUCCESS", "date": fecha_iso, "published": len(ids),
        "details": len(details), "included": summary.get("incluida", 0),
        "manual_review": summary.get("revision_manual", 0),
        "excluded": summary.get("excluida", 0),
        "original_excel": str(original_result), "filtered_excel": str(filtered_result),
        "detail_result": detail_result,
    }
    print("\n=== RUN COMPLETE ===")
    for key, value in result.items():
        print(f"{key}: {value}")
    return result


def main() -> int:
    print("FILTRO DE GRANDES LICITACIONES\n")
    try:
        result = run_pipeline()
    except KeyboardInterrupt:
        print("\nInterrupted. Saved progress can be resumed.")
        return 130
    except Exception as exc:
        # Do not print exception text: HTTP exceptions can include ticket-bearing URLs.
        print("\nPROCESS FAILED")
        print("Error type:", type(exc).__name__)
        print("Error details suppressed to protect credentials.")
        return 1
    return 2 if result.get("status") == "DETAILS_INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
