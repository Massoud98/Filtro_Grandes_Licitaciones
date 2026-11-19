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
ATTACHMENT_MAX_BATCHES = None


def project_root() -> Path:
    configured_root = os.environ.get(
        "FILTRO_LICITACIONES_ROOT"
    )

    if configured_root:
        return Path(configured_root).expanduser().resolve()

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
        ROOT / "datos" / "json" / "diarios",
        ROOT / "datos" / "json" / "consolidados",
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
        print('Configuración de filtros predeterminada instalada.')

    if not target_config.is_file():
        raise RuntimeError(
            "Filtering configuration path is not a file."
        )

    print('Carpeta de la aplicación:', ROOT)


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
        print(f"Credencial guardada encontrada: {username}")
        return value
    value = getpass.getpass(prompt + (" (required): " if required else " (Enter to skip): ")).strip()
    if not value:
        if required:
            raise RuntimeError(f"Missing required credential: {username}")
        return None
    kr.set_password(APP_SERVICE, username, value)
    print(f"Credencial guardada en Windows: {username}")
    return value


def backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = ROOT / "respaldos" / "ejecuciones" / path.parent.name / stamp / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    print('Archivo anterior conservado:', destination)
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


def ejecutar_procesamiento_adjuntos(classification_path):
    """Run production attachment processing without invalidating Excel reports."""

    if getattr(sys, "frozen", False):
        code_directory = RESOURCE_ROOT
    else:
        code_directory = RESOURCE_ROOT / "integracion_adjuntos" / "codigo"

    if not code_directory.is_dir():
        print('ERROR AL PROCESAR DOCUMENTOS')
        print('Tipo de error: ModuleNotFoundError')
        return {"status": "ERROR", "error_type": "ModuleNotFoundError"}

    code_path = str(code_directory)

    if code_path not in sys.path:
        sys.path.insert(0, code_path)

    try:
        node_path = None

        if getattr(sys, "frozen", False):
            bundled_node = RESOURCE_ROOT / "node.exe"
            if bundled_node.is_file():
                node_path = str(bundled_node)

        if not node_path:
            node_path = os.environ.get("PLAYWRIGHT_NODEJS_PATH")

        if not node_path or not Path(node_path).is_file():
            node_path = (
                shutil.which("node.exe")
                or shutil.which("node")
            )

        if not node_path or not Path(node_path).is_file():
            standard_node = Path(
                r"C:\Program Files\nodejs\node.exe"
            )
            if standard_node.is_file():
                node_path = str(standard_node)

        if not node_path or not Path(node_path).is_file():
            raise FileNotFoundError(
                "Node.js is required for Playwright."
            )

        os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(
            Path(node_path).resolve()
        )

        print("Playwright Node.js:", node_path)

        from orquestador_produccion import run

        result = run(classification_path, max_batches=ATTACHMENT_MAX_BATCHES)

        if not isinstance(result, dict) or result.get("status") != "SUCCESS":
            raise RuntimeError("Unexpected orchestrator result.")

        print('PROCESAMIENTO DE DOCUMENTOS COMPLETADO')
        return result

    except Exception as exc:
        print('ERROR AL PROCESAR DOCUMENTOS')
        print('Tipo de error:', type(exc).__name__)
        print('Los archivos Excel siguen disponibles.')

        return {
            "status": "ERROR",
            "error_type": type(exc).__name__,
        }


def run_pipeline(fecha=None, *, generar_reportes=True):
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
        print('ADVERTENCIA: Falta la credencial del Banco Central; puede fallar la conversión de monedas.')

    if fecha is None:
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

    print("\n=== PROCESAMIENTO DIARIO DE LICITACIONES ===")
    print('Fecha de publicación:', fecha_iso)
    if list_path.exists():
        published = load_existing_publication(list_path, fecha_iso)
        print('Reutilizando lista de publicaciones existente:', len(published["licitaciones"]))
        print('Para actualizar la lista, primero retire licitaciones_publicadas.json.')
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
        print('Informe de documentos validado para la ejecución diaria.')

    folder.mkdir(parents=True, exist_ok=True)

    if not ids:
        print('No se encontraron licitaciones publicadas. No se generaron archivos Excel.')
        return {"status": "NO_TENDERS", "published": 0}

    print("\n=== OBTENCIÓN DE DETALLES ===")
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
        print('Obtención de detalles incompleta. El progreso se guardó y puede retomarse.')
        print('Obtenidos:', len(details) if isinstance(details, dict) else 0, "/", len(ids))
        print('Errores registrados:', len(errors) if isinstance(errors, dict) else 0)
        return {"status": "DETAILS_INCOMPLETE", "published": len(ids), "details": len(details)}

    if not generar_reportes:
        print('Detalles completos. La generación de Excel se realizará posteriormente.')
        return {
            "status": "SUCCESS",
            "date": fecha_iso,
            "published": len(ids),
            "details": len(details),
            "detail_result": detail_result,
        }

    report_folder = CARPETA_ORIGINALES.parent.parent
    original = report_folder / "originales" / f"Licitaciones_Mercado_Publico_{fecha_iso}.xlsx"
    backup_existing(original)
    print("\n=== EXCEL ORIGINAL ===")
    original_result = generar_excel_original(fecha_iso)

    filters = folder / "filtros_preliminares.json"
    backup_existing(filters)
    print("\n=== APLICANDO FILTROS ===")
    filter_result = aplicar_filtros(fecha_iso)

    filtered = report_folder / "filtrados" / f"Licitaciones_Filtradas_{fecha_iso}.xlsx"
    backup_existing(filtered)
    print("\n=== EXCEL FILTRADO ===")
    if attachment_selection is None:
        filtered_result = generar_excel_filtrado(fecha_iso)
    else:
        filtered_result = generar_excel_filtrado(
            fecha_iso,
            attachment_report=attachment_selection[0],
        )

    print("\n=== PROCESAMIENTO DE DOCUMENTOS ===")
    attachment_result = ejecutar_procesamiento_adjuntos(filters)

    summary = filter_result.get("resumen", {})
    result = {
        "status": ("SUCCESS" if attachment_result.get("status") == "SUCCESS" else "ERROR"), "date": fecha_iso, "published": len(ids),
        "details": len(details), "included": summary.get("incluida", 0),
        "manual_review": summary.get("revision_manual", 0),
        "excluded": summary.get("excluida", 0),
        "original_excel": str(original_result), "filtered_excel": str(filtered_result),
        "detail_result": detail_result,
        "attachment_result": attachment_result,
    }
    print("\n=== RESUMEN DE EJECUCIÓN ===")
    for key, value in result.items():
        print(f"{key}: {value}")
    return result


def run_scheduled_pipeline():
    """Generate one execution-date report from scheduled publication dates."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from aplicacion.servicios.fechas_ejecucion import (
        fechas_publicacion_para_ejecucion,
    )
    from aplicacion.servicios.mercado_publico import CARPETA_ORIGINALES
    from aplicacion.servicios.consolidacion_licitaciones import (
        consolidar_publicaciones,
    )
    from aplicacion.servicios.generador_excel import generar_excel_original
    from aplicacion.servicios.generador_excel_filtrado import generar_excel_filtrado
    from aplicacion.servicios.filtros_preliminares import aplicar_filtros

    hoy = datetime.now(ZoneInfo("America/Santiago")).date()

    if hoy.weekday() >= 5:
        print('Fin de semana: no hay procesamiento programado.')
        return {"status": "NO_RUN", "results": []}

    fechas = fechas_publicacion_para_ejecucion(hoy=hoy)

    if (
        os.environ.get("FILTRO_ATTACHMENT_REPORT_PATH") is not None
        or os.environ.get("FILTRO_ATTACHMENT_REPORT_DATE") is not None
    ):
        raise ValueError(
            "Scheduled consolidated reports do not support "
            "a single-date attachment report."
        )

    results = []

    for fecha in fechas:
        print("\n=== FECHA DE PUBLICACIÓN PROGRAMADA ===")
        print('Fecha:', fecha.isoformat())

        result = run_pipeline(
            fecha=fecha,
            generar_reportes=False,
        )
        results.append(result)

        if result.get("status") == "DETAILS_INCOMPLETE":
            return {
                "status": "DETAILS_INCOMPLETE",
                "results": results,
            }

        if result.get("status") not in ("SUCCESS", "NO_TENDERS"):
            raise RuntimeError("Unexpected publication processing status.")

    base = CARPETA_ORIGINALES.parent.parent.parent
    fecha_reporte = hoy.isoformat()

    carpeta_proceso = (
        base / "datos" / "json" / "consolidados" / fecha_reporte
    )
    carpeta_salida_original = (
        base / "datos" / "originales"
    )

    consolidation = consolidar_publicaciones(
        CARPETA_ORIGINALES,
        fechas,
        carpeta_proceso,
        fecha_reporte,
    )

    if consolidation["status"] == "NO_TENDERS":
        print('No se encontraron licitaciones en las fechas seleccionadas.')
        return {
            "status": "NO_TENDERS",
            "results": results,
        }

    original = generar_excel_original(
        fecha_reporte,
        carpeta_datos=carpeta_proceso,
        carpeta_salida=carpeta_salida_original,
        fecha_reporte=fecha_reporte,
    )

    filtered_data = aplicar_filtros(
        fecha_reporte,
        carpeta_datos=carpeta_proceso,
    )

    filtered = generar_excel_filtrado(
        fecha_reporte,
        carpeta_datos=carpeta_proceso,
        carpeta_salida=base / "datos" / "filtrados",
        fecha_reporte=fecha_reporte,
    )

    print("\n=== PROCESAMIENTO DE DOCUMENTOS CONSOLIDADOS ===")
    attachment_classification = carpeta_proceso / "filtros_preliminares.json"
    attachment_result = ejecutar_procesamiento_adjuntos(
        attachment_classification
    )

    print("\n=== RESUMEN DE EJECUCIÓN CONSOLIDADA ===")
    print('Fecha de ejecución:', fecha_reporte)
    print('Publicadas:', consolidation["published"])
    print('Excel original:', original)
    print('Excel filtrado:', filtered)

    return {
        "status": ("SUCCESS" if attachment_result.get("status") == "SUCCESS" else "ERROR"),
        "date": fecha_reporte,
        "published": consolidation["published"],
        "original_excel": str(original),
        "filtered_excel": str(filtered),
        "filter_summary": filtered_data.get("resumen", {}),
        "attachment_result": attachment_result,
        "results": results,
    }

def run_runtime_self_test() -> int:
    """Verify local application initialization without network access."""

    print("\n=== PRUEBA DE FUNCIONAMIENTO ===")

    print('Carpeta de datos:', ROOT)
    print('Carpeta de recursos:', RESOURCE_ROOT)

    required_directories = [
        ROOT / "configuracion",
        ROOT / "datos" / "adjuntos",
        ROOT / "datos" / "filtrados",
        ROOT / "datos" / "originales",
        ROOT / "datos" / "json" / "diarios",
        ROOT / "datos" / "json" / "consolidados",
        ROOT / "datos" / "reportes",
        ROOT / "datos" / "simulaciones",
        ROOT / "datos" / "tipos_cambio",
        ROOT / "respaldos" / "ejecuciones",
    ]

    for directory in required_directories:
        if not directory.is_dir():
            raise RuntimeError(
                "Required runtime directory missing."
            )
        print('CARPETA CORRECTA:', directory.relative_to(ROOT))

    config = ROOT / "configuracion" / "filtros.json"

    if not config.is_file():
        raise RuntimeError("Runtime configuration missing.")

    with config.open("r", encoding="utf-8") as stream:
        configuration = json.load(stream)

    if not isinstance(configuration, dict):
        raise RuntimeError("Invalid configuration structure.")

    print('Configuración: JSON VÁLIDO')
    print('Tamaño de configuración:', config.stat().st_size)
    print('Carpeta de trabajo actual:', Path.cwd())

    if Path.cwd().resolve() != ROOT.resolve():
        raise RuntimeError("Unexpected working directory.")

    print("\nRESULTADO DE PRUEBA: CORRECTO")
    print('Solicitudes de red: NINGUNA')
    print('Ejecución del recopilador: NINGUNA')

    return 0


def main() -> int:
    args = sys.argv[1:]
    if args == ["--help"]:
        print("Usage: Iniciar_Filtro.exe [--help | --self-test]")
        print("No arguments: run the scheduled production pipeline.")
        return 0
    if args and args != ["--self-test"]:
        print("ERROR: Unknown or incompatible arguments.", file=sys.stderr)
        print("Usage: Iniciar_Filtro.exe [--help | --self-test]", file=sys.stderr)
        return 2
    if args == ["--self-test"]:
        try:
            return run_runtime_self_test()
        except Exception as exc:
            print("PRUEBA DE FUNCIONAMIENTO FALLIDA")
            print("Tipo de error:", type(exc).__name__)
            return 1

    print("FILTRO DE GRANDES LICITACIONES")
    exit_code = 0

    try:
        result = run_scheduled_pipeline()
        status = result.get("status")

        if status == "DETAILS_INCOMPLETE":
            print("\n========================================")
            print("PROCESO INCOMPLETO")
            print("========================================")
            print("No se pudieron obtener todos los detalles.")
            print("El progreso guardado se conserva.")
            print("Ejecute nuevamente el programa para continuar.")
            exit_code = 2

        elif status == "ERROR":
            print("\n========================================")
            print("PROCESO INTERRUMPIDO POR UN ERROR")
            print("========================================")
            print("No fue posible completar el procesamiento de documentos.")
            print("Los archivos Excel y el progreso guardado se conservan.")
            print("Ejecute nuevamente el programa más tarde para continuar.")
            exit_code = 1

        elif status in ("SUCCESS", "NO_TENDERS", "NO_RUN"):
            print("\n========================================")
            print("PROCESO FINALIZADO CORRECTAMENTE")
            print("========================================")
            if status == "NO_RUN":
                print("No hay procesamiento programado para hoy.")
            elif status == "NO_TENDERS":
                print("No se encontraron licitaciones para procesar.")
            else:
                print("El procesamiento ha terminado correctamente.")
            exit_code = 0

        else:
            print("\nPROCESO INTERRUMPIDO: resultado inesperado.")
            print("Ejecute nuevamente el programa para continuar.")
            exit_code = 1

    except KeyboardInterrupt:
        print("\n========================================")
        print("PROCESO INTERRUMPIDO")
        print("========================================")
        print("La ejecución fue interrumpida.")
        print("El progreso guardado se conserva.")
        print("Ejecute nuevamente el programa para continuar.")
        exit_code = 130

    except Exception as exc:
        # Do not display exception text: it may contain credentials.
        print("\n========================================")
        print("PROCESO INTERRUMPIDO POR UN ERROR")
        print("========================================")
        print("Tipo de error:", type(exc).__name__)
        print("Los detalles técnicos se ocultan para proteger credenciales.")
        print("El progreso guardado se conserva.")
        print("Ejecute nuevamente el programa más tarde para continuar.")
        exit_code = 1

    finally:
        if getattr(sys, "frozen", False):
            try:
                input("\nPresione ENTER para cerrar...")
            except (EOFError, OSError):
                pass

    return exit_code



if __name__ == "__main__":
    raise SystemExit(main())
