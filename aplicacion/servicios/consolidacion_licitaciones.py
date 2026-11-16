"""Consolidate completed publication checkpoints without modifying them."""

import json
from pathlib import Path


def consolidar_publicaciones(carpeta_originales, fechas, carpeta_destino, fecha_reporte):
    """Build a validated dataset for one execution-date report."""

    carpeta_originales = Path(carpeta_originales)
    carpeta_destino = Path(carpeta_destino)

    if not fechas:
        raise ValueError("No publication dates provided.")

    if len(fechas) != len(set(fechas)):
        raise ValueError("Duplicate publication dates.")


    publicaciones = []
    ids = []
    detalles = {}
    origenes = {}

    for fecha in fechas:
        fecha_iso = fecha.isoformat()
        carpeta = carpeta_originales / fecha_iso

        lista = json.loads(
            (carpeta / "licitaciones_publicadas.json").read_text(
                encoding="utf-8"
            )
        )

        if lista.get("fecha") != fecha_iso:
            raise ValueError(f"Invalid publication date: {fecha_iso}")

        items = lista.get("licitaciones")
        if not isinstance(items, list):
            raise ValueError(f"Invalid publication list: {fecha_iso}")

        if not items:
            continue

        progreso = json.loads(
            (carpeta / "detalles_licitaciones.json").read_text(
                encoding="utf-8"
            )
        )

        ids_dia = [
            str(item.get("CodigoExterno") or "").strip()
            for item in items
        ]

        if (
            not all(ids_dia)
            or len(ids_dia) != len(set(ids_dia))
            or progreso.get("fecha") != fecha_iso
            or progreso.get("ids") != ids_dia
            or progreso.get("errores")
            or not isinstance(progreso.get("detalles"), dict)
            or set(progreso["detalles"]) != set(ids_dia)
        ):
            raise ValueError(
                f"Incomplete or inconsistent checkpoint: {fecha_iso}"
            )

        for item, codigo in zip(items, ids_dia):
            detalle = progreso["detalles"][codigo]

            if (
                not isinstance(detalle, dict)
                or str(detalle.get("CodigoExterno") or "").strip() != codigo
            ):
                raise ValueError(f"Invalid tender detail: {codigo}")

            if codigo in detalles:
                raise ValueError(
                    f"Duplicate tender {codigo} across "
                    f"{origenes[codigo]} and {fecha_iso}"
                )

            publicaciones.append(item)
            ids.append(codigo)
            detalles[codigo] = detalle
            origenes[codigo] = fecha_iso

    if not ids:
        return {
            "status": "NO_TENDERS",
            "published": 0,
            "dates": [fecha.isoformat() for fecha in fechas],
        }

    # Destination is isolated from the publication checkpoints.
    lista_consolidada = {
        "fecha": fecha_reporte,
        "licitaciones": publicaciones,
    }

    detalles_consolidados = {
        "fecha": fecha_reporte,
        "ids": ids,
        "detalles": detalles,
        "errores": {},
    }

    ruta_lista = carpeta_destino / "licitaciones_publicadas.json"
    ruta_detalles = carpeta_destino / "detalles_licitaciones.json"

    if carpeta_destino.exists():
        if not carpeta_destino.is_dir():
            raise ValueError("Consolidation destination is not a directory.")

        if not ruta_lista.is_file() or not ruta_detalles.is_file():
            raise ValueError("Existing consolidation is incomplete.")

        existente_lista = json.loads(
            ruta_lista.read_text(encoding="utf-8")
        )
        existente_detalles = json.loads(
            ruta_detalles.read_text(encoding="utf-8")
        )

        if (
            existente_lista != lista_consolidada
            or existente_detalles != detalles_consolidados
        ):
            raise ValueError(
                "Existing consolidation differs from publication checkpoints."
            )
    else:
        import tempfile

        carpeta_destino.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix=".consolidacion_",
            dir=carpeta_destino.parent,
        ) as temporal:
            carpeta_temporal = Path(temporal)

            (carpeta_temporal / "licitaciones_publicadas.json").write_text(
                json.dumps(lista_consolidada, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            (carpeta_temporal / "detalles_licitaciones.json").write_text(
                json.dumps(detalles_consolidados, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            carpeta_temporal.rename(carpeta_destino)

    return {
        "status": "SUCCESS",
        "published": len(ids),
        "dates": [fecha.isoformat() for fecha in fechas],
        "folder": str(carpeta_destino),
    }