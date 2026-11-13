"""Validated configuration for preliminary tender filtering."""

import json
import os
from pathlib import Path


RAIZ_PROYECTO = Path(
    os.environ.get(
        "FILTRO_LICITACIONES_ROOT",
        Path(__file__).resolve().parents[2],
    )
).resolve()

RUTA_CONFIGURACION = (
    RAIZ_PROYECTO
    / "configuracion"
    / "filtros.json"
)


class ErrorConfiguracionFiltros(ValueError):
    """Invalid preliminary filtering configuration."""


def cargar_configuracion(ruta=None):
    """Load and validate the preliminary filtering rules."""

    ruta = Path(ruta) if ruta is not None else RUTA_CONFIGURACION

    try:
        datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ErrorConfiguracionFiltros(
            "Cannot read filtering configuration."
        ) from None

    if not isinstance(datos, dict):
        raise ErrorConfiguracionFiltros(
            "Filtering configuration must be an object."
        )

    if datos.get("version") != 1:
        raise ErrorConfiguracionFiltros(
            "Unsupported filtering configuration version."
        )

    if datos.get("excluir_tipos") != ["O1"]:
        raise ErrorConfiguracionFiltros(
            "Unexpected excluded tender types."
        )

    if (
        type(datos.get("dias_minimos_para_cierre")) is not int
        or datos["dias_minimos_para_cierre"] != 7
    ):
        raise ErrorConfiguracionFiltros(
            "Unexpected closing-date threshold."
        )

    filtro_l1 = datos.get("filtro_l1")

    if not isinstance(filtro_l1, dict):
        raise ErrorConfiguracionFiltros(
            "Invalid L1 filtering configuration."
        )

    if (
        filtro_l1.get("activo") is not True
        or filtro_l1.get("categorias_permitidas")
        != ["alimentos", "vestimenta"]
        or filtro_l1.get("clasificacion_ambigua")
        != "revision_manual"
    ):
        raise ErrorConfiguracionFiltros(
            "Unexpected L1 filtering rules."
        )

    monto = datos.get("monto_minimo_clp")

    if type(monto) is not int or monto != 20000000:
        raise ErrorConfiguracionFiltros(
            "Unexpected minimum CLP amount."
        )

    return datos
