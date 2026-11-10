"""Consulta de licitaciones publicadas en Mercado Público."""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


URL_API = (
    "https://api.mercadopublico.cl/"
    "servicios/v1/publico/licitaciones.json"
)

ZONA_HORARIA = ZoneInfo("America/Santiago")

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
CARPETA_ORIGINALES = RAIZ_PROYECTO / "datos" / "originales"


def obtener_fecha_ayer():
    """Obtiene la fecha de ayer según el horario de Chile."""
    hoy = datetime.now(ZONA_HORARIA).date()
    return hoy - timedelta(days=1)


def guardar_json_atomico(ruta, contenido):
    """Guarda información JSON sin sobrescribir directamente el destino."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")

    try:
        temporal.write_text(
            json.dumps(contenido, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporal, ruta)
    finally:
        temporal.unlink(missing_ok=True)


def consultar_licitaciones(fecha=None, ticket=None):
    """
    Consulta licitaciones publicadas para una fecha.

    Si no se indica fecha, consulta el día anterior en Chile.
    """
    if fecha is None:
        fecha = obtener_fecha_ayer()

    if not isinstance(fecha, date) or isinstance(fecha, datetime):
        raise TypeError("La fecha debe ser un objeto date.")

    if ticket is None:
        ticket = os.environ.get("API_MP", "").strip()

    if not ticket:
        raise RuntimeError(
            "No se encontró la credencial API_MP. "
            "Configure la variable de entorno antes de consultar."
        )

    fecha_api = fecha.strftime("%d%m%Y")
    fecha_iso = fecha.isoformat()

    print("=== CONSULTA MERCADO PÚBLICO ===")
    print("Fecha consultada:", fecha_iso)

    respuesta = requests.get(
        URL_API,
        params={
            "fecha": fecha_api,
            "ticket": ticket,
        },
        timeout=60,
    )

    # No se realizan reintentos automáticos ante errores de acceso.
    respuesta.raise_for_status()

    datos = respuesta.json()

    if not isinstance(datos, dict):
        raise RuntimeError("La API devolvió un formato inesperado.")

    registros = datos.get("Listado")

    if not isinstance(registros, list):
        raise RuntimeError(
            "La respuesta no contiene un listado válido."
        )

    publicadas = [
        registro
        for registro in registros
        if isinstance(registro, dict)
        and str(registro.get("CodigoEstado")) == "5"
    ]

    licitaciones = []
    ids_vistos = set()

    for registro in publicadas:
        codigo = str(
            registro.get("CodigoExterno") or ""
        ).strip()

        if not codigo or codigo in ids_vistos:
            continue

        ids_vistos.add(codigo)
        licitaciones.append(registro)

    resultado = {
        "fecha": fecha_iso,
        "fecha_api": fecha_api,
        "total": len(licitaciones),
        "licitaciones": licitaciones,
    }

    ruta_salida = (
        CARPETA_ORIGINALES
        / fecha_iso
        / "licitaciones_publicadas.json"
    )

    guardar_json_atomico(ruta_salida, resultado)

    print("\n=== RESULTADO ===")
    print("Registros recibidos:", len(registros))
    print("Registros publicados:", len(publicadas))
    print("Duplicados eliminados:", len(publicadas) - len(licitaciones))
    print("Licitaciones únicas:", len(licitaciones))
    print("Archivo:", ruta_salida)

    return resultado


if __name__ == "__main__":
    consultar_licitaciones()
