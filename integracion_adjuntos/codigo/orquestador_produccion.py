"""Production attachment download, extraction and cleanup orchestrator."""

import argparse
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError

from bloqueo_instancia import single_instance
from navegador_adjuntos import (
    BrowserAccessBlocked,
    discover_controls,
    open_attachment_popup,
)
from descargador_individual import download_one
from lotes_produccion import plan_batches, prepare_batch
from checkpoint_descargas import (
    save_checkpoint,
    validate_checkpoint_structure,
    verify_extraction_lifecycle,
)
from coordinador_produccion import extract_downloaded
from coordinador_limpieza import cleanup_extracted
from workspace_diario import resolve_workspace
from coordinador_revision import (
    register_manual_review,
    review_category,
)

from reporte_revision import rebuild_manual_review_report


def resolve_resource_root():
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not bundle_root:
            raise RuntimeError("PyInstaller resource root unavailable.")
        return Path(bundle_root).resolve()

    return Path(__file__).resolve().parents[2]


RESOURCE_ROOT = resolve_resource_root()

ROOT = Path(
    os.environ.get(
        "FILTRO_LICITACIONES_ROOT",
        Path(__file__).resolve().parents[2],
    )
).expanduser().resolve()
WORKSPACE = ROOT / "datos" / "adjuntos"

DOWNLOADS = WORKSPACE / "descargas"
EXTRACTED = WORKSPACE / "extraidos"
CHECKPOINTS = WORKSPACE / "checkpoints"
PROFILE = WORKSPACE / "chrome_profile"

LOCKFILE = WORKSPACE / "produccion.lock"

CHROME = Path(
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)
TESSERACT = Path(
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
TESSDATA = RESOURCE_ROOT / "datos" / "adjuntos" / "tessdata"

ATTACHMENT_DELAY = 2
TENDER_DELAY = 5


class ProductionOrchestratorError(RuntimeError):
    """Production workflow integrity or execution failure."""


def validate_environment(classification_path):
    classification = Path(classification_path)

    if classification.is_symlink() or not classification.is_file():
        raise ProductionOrchestratorError(
            "Classification file missing or unsafe."
        )

    for directory in (
        WORKSPACE,
        DOWNLOADS,
        EXTRACTED,
        CHECKPOINTS,
        PROFILE,
    ):
        if directory.is_symlink() or not directory.is_dir():
            raise ProductionOrchestratorError(
                "Production directory missing or unsafe: "
                + str(directory)
            )

    for executable in (TESSERACT,):
        if executable.is_symlink() or not executable.is_file():
            raise ProductionOrchestratorError(
                "Required executable missing: " + str(executable)
            )

    model = TESSDATA / "spa.traineddata"

    if TESSDATA.is_symlink() or not TESSDATA.is_dir():
        raise ProductionOrchestratorError(
            "Spanish OCR data directory missing or unsafe."
        )

    if model.is_symlink() or not model.is_file():
        raise ProductionOrchestratorError(
            "Spanish OCR model missing."
        )

    return classification


def ensure_browser(playwright, context):
    if context is not None:
        return context

    if CHROME.is_symlink() or not CHROME.is_file():
        raise ProductionOrchestratorError(
            "Google Chrome executable missing."
        )

    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        executable_path=str(CHROME),
        headless=False,
        accept_downloads=True,
        viewport={"width": 1366, "height": 900},
    )


def close_page(page, popup):
    for item in (popup, page):
        if item is not None:
            try:
                if not item.is_closed():
                    item.close()
            except Exception:
                pass


def download_missing(
    playwright,
    context,
    checkpoint,
    checkpoint_path,
    tender_id,
    entry,
    *,
    authorized_ids=None,
):
    page = None
    popup = None
    created_context = context is None

    try:
        context = ensure_browser(playwright, context)
        page = context.new_page()

        popup = open_attachment_popup(page, tender_id)
        controls = discover_controls(popup)

        if len(controls) != len(set(controls)):
            raise ProductionOrchestratorError(
                "Duplicate browser attachment controls."
            )

        previous = entry.get("discovered")

        if previous is not None and previous != len(controls):
            raise ProductionOrchestratorError(
                "Attachment discovery count changed."
            )

        existing_ids = {
            record.get("control_id")
            for record in entry["attachments"]
            if record.get("status") in {
                "DOWNLOADED",
                "EXTRACTED",
                "CLEANUP_PENDING",
                "COMPLETE",
            }
        }

        if not existing_ids.issubset(set(controls)):
            raise ProductionOrchestratorError(
                "Previously recorded controls changed."
            )

        entry["discovered"] = len(controls)
        save_checkpoint(checkpoint_path, checkpoint)

        for number, control_id in enumerate(controls, 1):
            if control_id in existing_ids:
                continue

            print(
                'DESCARGA',
                tender_id,
                f"{number}/{len(controls)}",
                control_id,
                flush=True,
            )

            download_one(
                popup,
                tender_id,
                control_id,
                checkpoint,
                checkpoint_path,
                DOWNLOADS,
                EXTRACTED,
                authorized_ids=authorized_ids,
            )

            time.sleep(ATTACHMENT_DELAY)

        if len(entry["attachments"]) != len(controls):
            raise ProductionOrchestratorError(
                "Downloaded attachment count mismatch."
            )

        final_ids = {
            record.get("control_id")
            for record in entry["attachments"]
        }

        if final_ids != set(controls):
            raise ProductionOrchestratorError(
                "Downloaded attachment inventory mismatch."
            )

        return context

    except Exception:
        if created_context and context is not None:
            try:
                context.close()
            except Exception:
                pass
        raise

    finally:
        close_page(page, popup)


def process_attachment(
    checkpoint,
    checkpoint_path,
    tender_id,
    record,
    *,
    authorized_ids=None,
):
    status = record["status"]

    if status == "DOWNLOADED" and review_category(record["filename"]) is not None:
        review = register_manual_review(
            checkpoint,
            checkpoint_path,
            DOWNLOADS,
            EXTRACTED,
            tender_id,
            record,
            authorized_ids=authorized_ids,
        )
        print(
            'REVISIÓN MANUAL:',
            tender_id,
            record["filename"],
            "|",
            review["category"],
            flush=True,
        )
        return

    if status == "DOWNLOADED":
        extract_downloaded(
            checkpoint,
            checkpoint_path,
            DOWNLOADS,
            EXTRACTED,
            tender_id,
            record,
            ROOT,
            TESSERACT,
            TESSDATA,
            authorized_ids=authorized_ids,
        )

        status = record["status"]

    if status in {"EXTRACTED", "CLEANUP_PENDING"}:
        cleanup_extracted(
            checkpoint,
            checkpoint_path,
            DOWNLOADS,
            EXTRACTED,
            tender_id,
            record,
            authorized_ids=authorized_ids,
        )

    elif status in {"COMPLETE", "REVIEW_REQUIRED"}:
        return

    else:
        raise ProductionOrchestratorError(
            "Unexpected attachment lifecycle state: "
            + str(record["status"])
        )

    if record["status"] not in {"COMPLETE", "REVIEW_REQUIRED"}:
        raise ProductionOrchestratorError(
            "Attachment did not reach a terminal state."
        )


def process_tender(
    playwright,
    context,
    checkpoint,
    checkpoint_path,
    tender_id,
    entry,
    *,
    authorized_ids=None,
):
    if (
        entry["status"] in {"COMPLETE", "COMPLETE_WITH_REVIEW"}
        and entry.get("discovered") is not None
        and all(
            record.get("status") in {"COMPLETE", "REVIEW_REQUIRED"}
            for record in entry["attachments"]
        )
    ):
        print('OMITIENDO LICITACIÓN YA VERIFICADA:', tender_id, flush=True)
        return context

    entry["status"] = "IN_PROGRESS"
    save_checkpoint(checkpoint_path, checkpoint)

    try:
        records = entry["attachments"]

        if any(record.get("status") == "ERROR" for record in records):
            raise ProductionOrchestratorError(
                "Attachment has ERROR status; manual recovery required."
            )

        discovered = entry.get("discovered")

        if discovered is None or len(records) < discovered:
            context = download_missing(
                playwright,
                context,
                checkpoint,
                checkpoint_path,
                tender_id,
                entry,
                authorized_ids=authorized_ids,
            )

        elif len(records) > discovered:
            raise ProductionOrchestratorError(
                "Checkpoint contains more attachments than discovered."
            )

        for record in entry["attachments"]:
            if record["status"] in {"COMPLETE", "REVIEW_REQUIRED"}:
                continue

            print(
                'PROCESANDO',
                tender_id,
                record["filename"],
                record["status"],
                flush=True,
            )

            process_attachment(
                checkpoint,
                checkpoint_path,
                tender_id,
                record,
                authorized_ids=authorized_ids,
            )

        if not all(
            record.get("status") in {"COMPLETE", "REVIEW_REQUIRED"}
            for record in entry["attachments"]
        ):
            raise ProductionOrchestratorError(
                "Tender has unfinished attachments."
            )

        validate_checkpoint_structure(checkpoint)

        verify_extraction_lifecycle(
            checkpoint,
            DOWNLOADS,
            EXTRACTED,
            authorized_ids=authorized_ids,
        )

        review_count = sum(
            record["status"] == "REVIEW_REQUIRED"
            for record in entry["attachments"]
        )
        entry["status"] = (
            "COMPLETE_WITH_REVIEW" if review_count else "COMPLETE"
        )
        save_checkpoint(checkpoint_path, checkpoint)

        print(
            'LICITACIÓN COMPLETADA:',
            tender_id,
            '| documentos:',
            len(entry["attachments"]),
            '| revisiones manuales:',
            review_count,
            flush=True,
        )

        return context

    except BrowserAccessBlocked as exc:
        entry["status"] = "BLOCKED"
        entry["errors"].append(str(exc))
        save_checkpoint(checkpoint_path, checkpoint)
        raise

    except Exception as exc:
        entry["status"] = "ERROR"
        entry["errors"].append(
            f"{type(exc).__name__}: {exc}"
        )
        save_checkpoint(checkpoint_path, checkpoint)
        raise



def refresh_daily_workspace(authorized_ids):
    """Rebuild the daily report and remove only empty authorized folders."""

    report_path = DOWNLOADS.parent / "revision_manual.csv"

    report = rebuild_manual_review_report(
        CHECKPOINTS,
        DOWNLOADS,
        report_path,
    )

    removed = 0

    for root in (DOWNLOADS, EXTRACTED):
        if root.is_symlink() or not root.is_dir():
            raise ProductionOrchestratorError(
                "Unsafe daily attachment directory."
            )

        for tender_id in authorized_ids:
            folder = root / tender_id

            if folder.is_symlink():
                raise ProductionOrchestratorError(
                    "Unsafe tender directory."
                )

            if not folder.exists():
                continue

            if not folder.is_dir():
                raise ProductionOrchestratorError(
                    "Unexpected tender directory entry."
                )

            if not any(folder.iterdir()):
                folder.rmdir()
                removed += 1

    print(
        'INFORME DIARIO DE REVISIÓN:',
        report["reviews"],
        '| verificados:',
        report["verified"],
        '| faltantes:',
        report["missing"],
        '| errores de integridad:',
        report["integrity_failed"],
        flush=True,
    )

    print('CARPETAS VACÍAS ELIMINADAS:', removed, flush=True)

    return report



def process_tender_with_retry(
    playwright,
    context,
    checkpoint,
    checkpoint_path,
    tender_id,
    entry,
    *,
    authorized_ids=None,
    attempts=3,
    delay_seconds=5,
):
    """Retry transient browser failures without retrying access restrictions."""
    for attempt in range(1, attempts + 1):
        try:
            return process_tender(
                playwright,
                context,
                checkpoint,
                checkpoint_path,
                tender_id,
                entry,
                authorized_ids=authorized_ids,
            )
        except BrowserAccessBlocked:
            raise
        except (PlaywrightError, ConnectionError, TimeoutError, OSError) as exc:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
                context = None

            if attempt == attempts:
                raise

            print(
                f"FALLO TEMPORAL DEL NAVEGADOR: {tender_id} "
                f"| intento {attempt}/{attempts} "
                f"| {type(exc).__name__} "
                f"| nuevo intento en {delay_seconds}s",
                flush=True,
            )
            time.sleep(delay_seconds)

    raise ProductionOrchestratorError("Retry attempts exhausted.")


def run(classification_path, *, max_batches=None):
    if max_batches is not None and (
        isinstance(max_batches, bool)
        or not isinstance(max_batches, int)
        or max_batches < 1
    ):
        raise ValueError("max_batches must be a positive integer or None.")

    global DOWNLOADS, EXTRACTED, CHECKPOINTS

    daily = resolve_workspace(classification_path, WORKSPACE)

    DOWNLOADS = daily.downloads
    EXTRACTED = daily.extracted
    CHECKPOINTS = daily.checkpoints

    for directory in (daily.root, DOWNLOADS, EXTRACTED, CHECKPOINTS):
        if directory.is_symlink():
            raise RuntimeError("Unsafe dated attachment directory.")
        directory.mkdir(parents=True, exist_ok=True)

    classification = validate_environment(classification_path)
    batches = plan_batches(classification)
    authorized_ids = frozenset(
        tender_id for batch in batches for tender_id in batch
    )
    available_batches = len(batches)

    refresh_daily_workspace(authorized_ids)

    if max_batches is not None:
        batches = batches[:max_batches]

    print('=== PROCESAMIENTO DE DOCUMENTOS ===')
    print('Licitaciones incluidas:', sum(len(batch) for batch in plan_batches(classification)))
    print('Lotes disponibles:', available_batches)
    print('Lotes seleccionados:', len(batches))
    print('Tamaño del lote: 5')
    print('Límite de ejecución:', max_batches if max_batches is not None else "TODOS")

    if not batches:
        print('No hay licitaciones incluidas.')
        return {"status": "SUCCESS", "batches": 0, "tenders": 0}

    completed = 0
    context = None

    with single_instance(LOCKFILE):
        with sync_playwright() as playwright:
            try:
                for number, ids in enumerate(batches, 1):
                    print(
                        f"\n=== LOTE {number}/{len(batches)} ===",
                        flush=True,
                    )

                    checkpoint_path, checkpoint = prepare_batch(
                        classification,
                        CHECKPOINTS,
                        DOWNLOADS,
                        EXTRACTED,
                        number,
                        ids,
                        authorized_ids=authorized_ids,
                    )

                    for position, tender_id in enumerate(ids, 1):
                        if position > 1:
                            time.sleep(TENDER_DELAY)

                        print(
                            f"\n[{position}/5] {tender_id}",
                            flush=True,
                        )

                        entry = checkpoint["licitaciones"][tender_id]

                        try:
                            context = process_tender_with_retry(
                                playwright,
                                context,
                                checkpoint,
                                checkpoint_path,
                                tender_id,
                                entry,
                                authorized_ids=authorized_ids,
                            )
                        except Exception:
                            try:
                                refresh_daily_workspace(authorized_ids)
                            except Exception as report_error:
                                print(
                                    'ADVERTENCIA: Falló la actualización del informe diario:',
                                    type(report_error).__name__,
                                    str(report_error),
                                    flush=True,
                                )
                            raise
                        else:
                            refresh_daily_workspace(authorized_ids)

                        completed += 1

                    verify_extraction_lifecycle(
                        checkpoint,
                        DOWNLOADS,
                        EXTRACTED,
                        authorized_ids=authorized_ids,
                    )

                    print('LOTE VERIFICADO:', number, flush=True)

            finally:
                if context is not None:
                    context.close()

    result = {
        "status": "SUCCESS",
        "batches": len(batches),
        "batches_available": available_batches,
        "batches_remaining": available_batches - len(batches),
        "tenders": completed,
        "tenders_remaining": sum(len(batch) for batch in plan_batches(classification)[len(batches):]),
        "limited": len(batches) < available_batches,
    }

    print("\n=== PROCESAMIENTO DE DOCUMENTOS FINALIZADO ===")
    for key, value in result.items():
        print(f"{key}: {value}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Production attachment processing."
    )
    parser.add_argument(
        "classification",
        help="Path to filtros_preliminares.json",
    )
    args = parser.parse_args()

    run(args.classification)


if __name__ == "__main__":
    main()
