"""Filtros preliminares y clasificacion conservadora de licitaciones."""

import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aplicacion.servicios.configuracion_filtros import cargar_configuracion
from aplicacion.servicios.evaluacion_montos import evaluar_monto
from aplicacion.servicios.banco_central import ErrorBancoCentral
from aplicacion.servicios.snapshots_monedas import (
    ErrorSnapshotMonedas,
    obtener_snapshot,
)

from aplicacion.servicios.mercado_publico import (
    CARPETA_ORIGINALES,
    guardar_json_atomico,
)

ZONA = ZoneInfo("America/Santiago")

PATRONES_ALIMENTOS = [
    r"\balimentos?\b",
    r"\babarrotes?\b",
    r"\bproductos? alimenticios?\b",
    r"\bcanastas? familiares?\b",
    r"\bcolaciones?\b",
    r"\braciones? alimenticias?\b",
    r"\bfrutas?\b",
    r"\bverduras?\b",
    r"\bproductos? lacteos?\b",
    r"\bcarne[s]?\b",
    r"\bpescados?\b",
    r"\bpanaderia\b",
    r"\bmercaderias? alimenticias?\b",
]

PATRONES_VESTIMENTA = [
    r"\bvestuario\b",
    r"\bvestimenta\b",
    r"\buniformes?\b",
    r"\bropa\b",
    r"\bcalzado\b",
    r"\bzapatos?\b",
    r"\bbotas?\b",
    r"\bprendas?\b",
    r"\btextiles?\b",
    r"\belementos? de proteccion personal\b",
    r"\bepp\b",
]

PATRONES_SERVICIOS = [
    r"\bservicios? de\b",
    r"\bcapacitacion\b",
    r"\bconsultoria\b",
    r"\bmantencion\b",
    r"\bmantenimiento\b",
    r"\breparacion\b",
    r"\belaboracion de\b",
    r"\barriendo\b",
]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(
        caracter for caracter in texto
        if not unicodedata.combining(caracter)
    )
    return texto.lower()


def buscar_patrones(texto, patrones):
    return [
        patron
        for patron in patrones
        if re.search(patron, texto)
    ]


def obtener_items(detalle):
    """Extrae los productos del detalle de una licitaci?n."""
    contenedor = detalle.get("Items") or {}

    if isinstance(contenedor, dict):
        listado = contenedor.get("Listado") or []
    elif isinstance(contenedor, list):
        listado = contenedor
    else:
        listado = []

    return [
        item for item in listado
        if isinstance(item, dict)
    ]


def clasificar_l1(detalle):
    """Clasifica L1 con inclusion permisiva de alimentos y vestimenta."""

    items = obtener_items(detalle)

    if not items:
        return {
            "clasificacion": "excluir",
            "categorias_detectadas": [],
            "motivo": "No hay productos disponibles.",
            "indicios_servicio": False,
        }

    patrones_ropa = [
        r"\bpoleras?\b",
        r"\bjockeys?\b",
        r"\bjockets?\b",
        r"\bvestuario\b",
        r"\bvestimenta\b",
        r"\buniformes?\b",
        r"\bropa\b",
        r"\bcalzado\b",
        r"\bzapatos?\b",
        r"\bbotas?\b",
        r"\bprendas?\b",
        r"\bchaquetas?\b",
        r"\bpantalones?\b",
        r"\bdelantales?\b",
        r"\bpecheras?\b",
        r"\bguantes? de proteccion\b",
    ]

    categorias_detectadas = set()

    for item in items:
        codigo = str(item.get("CodigoCategoria") or "").strip()
        producto = normalizar(item.get("NombreProducto"))
        descripcion = normalizar(item.get("Descripcion"))

        patrones_descripcion_ropa = [
            patron for patron in patrones_ropa
            if patron != r"\buniformes?\b"
        ]

        es_ropa = bool(
            buscar_patrones(producto, patrones_ropa)
            or buscar_patrones(
                descripcion,
                patrones_descripcion_ropa
            )
        )

        es_alimento = bool(buscar_patrones(
            f"{producto} {descripcion}",
            PATRONES_ALIMENTOS
        ))

        codigo_alimento = codigo.startswith("50")
        codigo_ropa = codigo.startswith(("5310", "5311"))
        codigo_proteccion = codigo.startswith("461815")

        if codigo_alimento or es_alimento:
            categorias_detectadas.add("alimentos")

        if codigo_ropa or codigo_proteccion or es_ropa:
            categorias_detectadas.add("vestimenta")

    if categorias_detectadas:
        clasificacion = "incluir"
        motivo = (
            "Se identificaron productos de alimentos o vestimenta."
        )
    else:
        clasificacion = "excluir"
        motivo = (
            "No se identificaron productos de alimentos o vestimenta."
        )

    return {
        "clasificacion": clasificacion,
        "categorias_detectadas": sorted(categorias_detectadas),
        "motivo": motivo,
        "indicios_servicio": any(
            str(item.get("CodigoCategoria") or "").startswith("9")
            for item in items
        ),
    }



def interpretar_fecha(valor):
    if not valor:
        return None

    try:
        fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None

    if fecha.tzinfo is None:
        return fecha.replace(tzinfo=ZONA)

    return fecha.astimezone(ZONA)


def aplicar_filtros(fecha, evaluacion=None, *, carpeta_datos=None):
    """Evalua sin modificar los datos originales."""

    if evaluacion is None:
        evaluacion = datetime.now(ZONA)
    elif evaluacion.tzinfo is None:
        raise ValueError("La evaluacion debe incluir zona horaria.")
    else:
        evaluacion = evaluacion.astimezone(ZONA)

    carpeta = Path(carpeta_datos) if carpeta_datos is not None else CARPETA_ORIGINALES / fecha
    ruta = carpeta / "detalles_licitaciones.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))

    if datos.get("fecha") != fecha:
        raise ValueError("La fecha del conjunto no coincide.")

    ids = datos["ids"]
    detalles = datos["detalles"]

    if len(ids) != len(set(ids)) or set(ids) != set(detalles):
        raise ValueError("El conjunto de detalles esta incompleto.")

    configuracion = cargar_configuracion()
    monto_minimo = configuracion["monto_minimo_clp"]

    resultados = []
    minimo_cierre = evaluacion + timedelta(
        days=configuracion["dias_minimos_para_cierre"]
    )

    necesita_conversion = any(
        detalle.get("MontoEstimado") is not None
        and str(detalle.get("MontoEstimado")).strip() != ""
        and str(detalle.get("Moneda") or "").strip().upper()
        in {"USD", "CLF", "UTM"}
        for detalle in detalles.values()
    )

    snapshot = None
    error_conversion = None

    if necesita_conversion:
        try:
            snapshot = obtener_snapshot(evaluacion.date())
        except (ErrorBancoCentral, ErrorSnapshotMonedas) as exc:
            error_conversion = type(exc).__name__

    for codigo in ids:
        detalle = detalles[codigo]
        tipo = str(detalle.get("Tipo") or "").strip().upper()
        fechas = detalle.get("Fechas") or {}

        cierre = interpretar_fecha(
            fechas.get("FechaCierre") or detalle.get("FechaCierre")
        )

        razones = []
        observaciones = []
        clasificacion = None

        # 1. O1: exclusion takes priority.
        if tipo == "O1":
            razones.append("Tipo O1 excluido.")

        # 2. Classify categories for all types.
        # The L1 category restriction remains unchanged.
        clasificacion = clasificar_l1(detalle)

        if tipo == "L1":
            if (
                not razones
                and clasificacion["clasificacion"] == "excluir"
            ):
                razones.append(clasificacion["motivo"])

            elif clasificacion["clasificacion"] == "revision_manual":
                observaciones.append(clasificacion["motivo"])

        # 3. Closing date: compare calendar dates.
        if cierre is None:
            observaciones.append(
                "Fecha de cierre ausente o invalida."
            )

        elif cierre.date() < minimo_cierre.date():
            observaciones.append(
                f"Cierre en menos de "
                f"{configuracion['dias_minimos_para_cierre']} dias."
            )

        # 4. Amount: only confirmed amounts below the threshold
        # determine exclusion. Other monetary statuses pass.
        evaluacion_monto = evaluar_monto(
            detalle,
            monto_minimo,
            snapshot,
        )

        elegible_tienda = (
            not razones
            and tipo != "O1"
            and evaluacion_monto["estado_monto"] == "bajo_minimo"
            and clasificacion["clasificacion"] == "incluir"
            and bool(
                set(clasificacion["categorias_detectadas"])
                & {"alimentos", "vestimenta"}
            )
        )

        if (
            not razones
            and evaluacion_monto["excluir"]
            and not elegible_tienda
        ):
            razones.append(
                "Monto estimado inferior al minimo de 20000000 CLP."
            )

        if evaluacion_monto["revision_manual"]:
            observaciones.append(
                "Monto o conversion requiere revision manual: "
                + evaluacion_monto["estado_monto"]
            )

            if error_conversion is not None:
                observaciones.append(
                    "Banco Central unavailable: " + error_conversion
                )

        # Ambiguous or unavailable information never creates
        # a manual-review classification at this stage.
        estado = (
            "excluida" if razones
            else "posible_tienda" if elegible_tienda
            else "incluida"
        )

        resultados.append({
            "id": codigo,
            "tipo": tipo,
            "nombre": detalle.get("Nombre") or "",
            "fecha_cierre": cierre.isoformat() if cierre else None,
            "estado": estado,
            "razones": razones,
            "observaciones": observaciones,
            "clasificacion_l1": clasificacion,
            "evaluacion_monto": evaluacion_monto,
        })

    resumen = {
        estado: sum(
            fila["estado"] == estado for fila in resultados
        )
        for estado in (
            "incluida", "posible_tienda",
            "revision_manual", "excluida"
        )
    }

    salida = {
        "fecha_publicacion": fecha,
        "evaluado_en": evaluacion.isoformat(),
        "cierre_minimo": minimo_cierre.isoformat(),
        "monto_minimo_clp": monto_minimo,
        "fecha_revision_tasas": evaluacion.date().isoformat(),
        "snapshot_monedas": snapshot,
        "error_conversion": error_conversion,
        "total": len(resultados),
        "resumen": resumen,
        "resultados": resultados,
    }

    ruta_salida = carpeta / "filtros_preliminares.json"
    guardar_json_atomico(ruta_salida, salida)

    print("=== FILTROS PRELIMINARES ===")
    print("Fecha de publicacion:", fecha)
    print("Evaluacion:", evaluacion.isoformat())
    print("Cierre minimo:", minimo_cierre.isoformat())
    print("Total:", len(resultados))

    for estado, cantidad in resumen.items():
        print(f"{estado}: {cantidad}")

    print("Archivo:", ruta_salida)

    return salida
