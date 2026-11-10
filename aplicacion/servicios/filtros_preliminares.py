"""Filtros preliminares y clasificacion conservadora de licitaciones."""

import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
    """Clasifica L1 usando categor?as, productos y descripciones."""

    items = obtener_items(detalle)

    if not items:
        return {
            "clasificacion": "revision_manual",
            "categorias_detectadas": [],
            "motivo": "No hay productos disponibles para clasificar.",
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
    evidencias_positivas = []
    evidencias_contrarias = []
    codigos_desconocidos = []

    for item in items:
        codigo = str(item.get("CodigoCategoria") or "").strip()
        producto = normalizar(item.get("NombreProducto"))
        descripcion = normalizar(item.get("Descripcion"))
        categoria = normalizar(item.get("Categoria"))

        texto_producto = f"{producto} {descripcion}"

        # "Uniforme" puede describir una propiedad, no vestimenta.
        # Ejemplo: medallas de di?metro uniforme.
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
            texto_producto, PATRONES_ALIMENTOS
        ))

        # Categor?as candidatas: requieren revisi?n del producto.
        codigo_alimento = codigo.startswith("50")
        codigo_ropa = codigo.startswith(("5310", "5311"))
        codigo_proteccion = codigo.startswith("461815")

        categoria_potencial = codigo.startswith(("50", "53", "4618"))

        # Los c?digos son indicios, no decisiones absolutas.
        if codigo_alimento:
            categorias_detectadas.add("alimentos")
            evidencias_positivas.append("Categor?a alimentaria")
        elif codigo_ropa or codigo_proteccion:
            categorias_detectadas.add("vestimenta")
            evidencias_positivas.append("Categor?a de vestimenta o protecci?n")
        elif es_ropa:
            categorias_detectadas.add("vestimenta")
            evidencias_positivas.append("Producto descrito como vestimenta")
        elif categoria_potencial or es_alimento:
            # Evitar exclusiones autom?ticas de casos dudosos.
            codigos_desconocidos.append(
                f"Producto potencialmente relevante: {codigo}"
            )
        elif codigo:
            evidencias_contrarias.append(
                f"Categor?a distinta: {codigo}"
            )
        else:
            codigos_desconocidos.append(
                producto or "Producto sin identificar"
            )

        # Un servicio de confecci?n puede requerir revisi?n.
        if es_ropa and codigo.startswith("9"):
            codigos_desconocidos.append(
                "Vestimenta clasificada como servicio"
            )

    if categorias_detectadas:
        if evidencias_contrarias or codigos_desconocidos:
            clasificacion = "revision_manual"
            motivo = "Productos mixtos o clasificaci?n contradictoria."
        else:
            clasificacion = "incluir"
            motivo = "Productos identificados como alimentos o vestimenta."

    elif codigos_desconocidos:
        clasificacion = "revision_manual"
        motivo = "Productos sin clasificaci?n suficientemente clara."

    elif evidencias_contrarias:
        clasificacion = "excluir"
        motivo = "Los productos no corresponden a alimentos o vestimenta."

    else:
        clasificacion = "revision_manual"
        motivo = "No se pudo determinar la categor?a."

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


def aplicar_filtros(fecha, evaluacion=None):
    """Evalua sin modificar los datos originales."""

    if evaluacion is None:
        evaluacion = datetime.now(ZONA)
    elif evaluacion.tzinfo is None:
        raise ValueError("La evaluacion debe incluir zona horaria.")
    else:
        evaluacion = evaluacion.astimezone(ZONA)

    carpeta = CARPETA_ORIGINALES / fecha
    ruta = carpeta / "detalles_licitaciones.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))

    if datos.get("fecha") != fecha:
        raise ValueError("La fecha del conjunto no coincide.")

    ids = datos["ids"]
    detalles = datos["detalles"]

    if len(ids) != len(set(ids)) or set(ids) != set(detalles):
        raise ValueError("El conjunto de detalles esta incompleto.")

    resultados = []
    minimo_cierre = evaluacion + timedelta(days=7)

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
        revision_manual = False

        if tipo == "O1":
            razones.append("Tipo O1 excluido.")

        if cierre is None:
            revision_manual = True
            observaciones.append(
                "Fecha de cierre ausente o inv?lida."
            )
        elif cierre < minimo_cierre:
            razones.append("Cierre en menos de siete d?as.")

        if tipo == "L1":
            clasificacion = clasificar_l1(detalle)

            if clasificacion["clasificacion"] == "excluir":
                razones.append(clasificacion["motivo"])

            elif clasificacion["clasificacion"] == "revision_manual":
                revision_manual = True
                observaciones.append(clasificacion["motivo"])

        if razones:
            estado = "excluida"
        elif revision_manual:
            estado = "revision_manual"
        else:
            estado = "incluida"

        resultados.append({
            "id": codigo,
            "tipo": tipo,
            "nombre": detalle.get("Nombre") or "",
            "fecha_cierre": cierre.isoformat() if cierre else None,
            "estado": estado,
            "razones": razones,
            "observaciones": observaciones,
            "clasificacion_l1": clasificacion,
        })

    resumen = {
        estado: sum(
            fila["estado"] == estado for fila in resultados
        )
        for estado in ("incluida", "revision_manual", "excluida")
    }

    salida = {
        "fecha_publicacion": fecha,
        "evaluado_en": evaluacion.isoformat(),
        "cierre_minimo": minimo_cierre.isoformat(),
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
