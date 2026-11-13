"""Generacion del Excel de licitaciones filtradas."""

import json
import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from aplicacion.servicios.generador_excel import (
    convertir_fecha,
    convertir_monto,
)
from aplicacion.servicios.filtros_preliminares import (
    CARPETA_ORIGINALES,
)
from aplicacion.servicios.estado_adjuntos_excel import (
    attachment_status_for_tender,
    build_attachment_status_lookup,
)


ENCABEZADOS = [
    "ID",
    "Tipo",
    "Nombre",
    "Fecha publicacion",
    "Fecha cierre",
    "Monto estimado",
    "Moneda",
    "Monto CLP",
    "Estado monto",
    "Tasa CLP",
    "Fecha tasa",
    "Estado",
    "Motivos / observaciones",
    "Clasificacion L1",
    "Adjuntos",
    "Aviso plazo",
]

URL_LICITACION = (
    "https://www.mercadopublico.cl/"
    "Procurement/Modules/RFB/"
    "DetailsAcquisition.aspx?idlicitacion={}"
)

COLORES = {
    "encabezado": "17365D",
    "alternado": "EAF1F8",
    "pendiente": "FFF2CC",
    "incluida": "E2F0D9",
    "posible_tienda": "DDEBF7",
    "revision_manual": "FFF2CC",
    "excluida": "FCE4D6",
}


def preparar_encabezado(hoja):
    """Aplica formato uniforme al encabezado."""

    for celda in hoja[1]:
        celda.fill = PatternFill(
            "solid",
            fgColor=COLORES["encabezado"],
        )
        celda.font = Font(
            bold=True,
            color="FFFFFF",
        )
        celda.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True,
        )

    hoja.row_dimensions[1].height = 32


def preparar_columnas(hoja):
    """Configura anchos, filtros y paneles inmovilizados."""

    anchos = [
        22, 12, 75, 23, 23, 22, 12, 22,
        25, 18, 18, 20, 65, 24, 30, 22,
    ]

    for indice, ancho in enumerate(anchos, start=1):
        letra = get_column_letter(indice)
        hoja.column_dimensions[letra].width = ancho

    hoja.freeze_panes = "D2"
    hoja.auto_filter.ref = hoja.dimensions


def calcular_aviso_plazo(fila, reporte):
    """Clasifica el plazo respecto de la evaluacion original."""
    fecha_cierre = fila.get("fecha_cierre")
    if not fecha_cierre:
        return "Sin fecha"

    try:
        cierre = datetime.fromisoformat(
            str(fecha_cierre).replace("Z", "+00:00")
        )
        evaluacion = datetime.fromisoformat(reporte["evaluado_en"])
        minimo = datetime.fromisoformat(reporte["cierre_minimo"])

        if cierre.tzinfo is None or evaluacion.tzinfo is None:
            return "Sin fecha"

        cierre = cierre.astimezone(evaluacion.tzinfo)
        minimo = minimo.astimezone(evaluacion.tzinfo)

        if cierre < evaluacion:
            return "Cierre vencido"
        if cierre.date() < minimo.date():
            return "Plazo corto"
        return "Plazo normal"
    except (ValueError, TypeError, KeyError, OverflowError):
        return "Sin fecha"


def crear_hoja_licitaciones(
    libro, nombre, filas, detalles, reporte=None,
    attachment_lookup=None,
):
    """Crea una hoja de licitaciones con trazabilidad."""

    hoja = libro.create_sheet(nombre)
    hoja.append(ENCABEZADOS)

    preparar_encabezado(hoja)

    for numero_fila, fila in enumerate(filas, start=2):
        codigo = fila["id"]
        detalle = detalles[codigo]
        fechas = detalle.get("Fechas") or {}

        publicacion = convertir_fecha(
            fechas.get("FechaPublicacion")
        )

        cierre = convertir_fecha(
            fechas.get("FechaCierre")
        )

        monto = convertir_monto(
            detalle.get("MontoEstimado")
        )

        evaluacion_monto = fila.get("evaluacion_monto") or {}

        moneda = (
            evaluacion_monto.get("moneda")
            or detalle.get("Moneda")
            or ""
        )

        monto_clp = convertir_monto(
            evaluacion_monto.get("monto_clp")
        )

        estados_monto = {
            "cumple_minimo": "Cumple minimo",
            "bajo_minimo": "Bajo minimo",
            "sin_monto": "Sin monto informado",
            "conversion_no_disponible": "Conversion no disponible",
            "monto_invalido": "Monto invalido",
        }

        estado_monto = estados_monto.get(
            evaluacion_monto.get("estado_monto"),
            "No evaluado",
        )

        tasa_clp = convertir_monto(
            evaluacion_monto.get("tasa_clp")
        )

        fecha_tasa = evaluacion_monto.get("fecha_tasa") or ""

        razones = fila.get("razones") or []
        observaciones = fila.get("observaciones") or []

        explicaciones = razones + observaciones

        clasificacion = fila.get("clasificacion_l1")

        if isinstance(clasificacion, dict):
            estado_l1 = clasificacion.get("clasificacion", "")
        else:
            estado_l1 = ""

        hoja.append([
            codigo,
            fila.get("tipo", ""),
            fila.get("nombre", ""),
            publicacion,
            cierre,
            monto,
            moneda,
            monto_clp,
            estado_monto,
            tasa_clp,
            fecha_tasa,
            fila["estado"],
            " | ".join(explicaciones),
            estado_l1,
            attachment_status_for_tender(codigo, attachment_lookup),
            calcular_aviso_plazo(fila, reporte) if reporte else "",
        ])

        if numero_fila % 2 == 0:
            for celda in hoja[numero_fila]:
                celda.fill = PatternFill(
                    "solid",
                    fgColor=COLORES["alternado"],
                )

        for columna in (4, 5):
            celda = hoja.cell(numero_fila, columna)
            if isinstance(celda.value, datetime):
                celda.number_format = "DD-MM-YYYY HH:MM"

        for columna in (6, 8, 10):
            hoja.cell(
                numero_fila, columna
            ).number_format = '#,##0.##'

        estado = hoja.cell(numero_fila, 12)
        estado.fill = PatternFill(
            "solid",
            fgColor=COLORES[fila["estado"]],
        )
        estado.alignment = Alignment(horizontal="center")

        motivo = hoja.cell(numero_fila, 13)
        motivo.alignment = Alignment(
            vertical="top",
            wrap_text=True,
        )

        aviso = hoja.cell(numero_fila, 16)
        if aviso.value in ("Plazo corto", "Cierre vencido"):
            aviso.fill = PatternFill(
                "solid",
                fgColor=COLORES["pendiente"]
                if aviso.value == "Plazo corto"
                else COLORES["excluida"],
            )

        pendiente = hoja.cell(numero_fila, 15)
        pendiente.fill = PatternFill(
            "solid",
            fgColor=COLORES["pendiente"],
        )

        identificador = hoja.cell(numero_fila, 1)
        identificador.hyperlink = URL_LICITACION.format(codigo)
        identificador.font = Font(
            color="0563C1",
            underline="single",
        )

    preparar_columnas(hoja)

    if not filas:
        for columna in range(1, len(ENCABEZADOS) + 1):
            hoja.cell(1, columna)

    return hoja


def crear_resumen(libro, reporte):
    """Crea el resumen de la evaluacion."""

    hoja = libro.active
    hoja.title = "Resumen"

    hoja.append(["Resumen de licitaciones filtradas", "Valor"])
    preparar_encabezado(hoja)

    resumen = reporte["resumen"]
    total = reporte["total"]

    datos = [
        ("Fecha de publicacion", reporte["fecha_publicacion"]),
        ("Fecha de evaluacion", reporte["evaluado_en"]),
        ("Cierre minimo", reporte["cierre_minimo"]),
        ("Total licitaciones", total),
        ("Incluidas", resumen["incluida"]),
        ("Posible para Tienda", resumen.get("posible_tienda", 0)),
        ("Revision manual", resumen["revision_manual"]),
        ("Excluidas", resumen["excluida"]),
        (
            "Porcentaje incluidas",
            resumen["incluida"] / total if total else 0,
        ),
        (
            "Porcentaje excluidas",
            resumen["excluida"] / total if total else 0,
        ),
        (
            "Porcentaje posible para Tienda",
            resumen.get("posible_tienda", 0) / total if total else 0,
        ),
    ]

    for etiqueta, valor in datos:
        hoja.append([etiqueta, valor])

    hoja.column_dimensions["A"].width = 36
    hoja.column_dimensions["B"].width = 44

    for fila in (10, 11, 12):
        hoja.cell(fila, 2).number_format = "0.0%"

    hoja.freeze_panes = "A2"

    return hoja


def generar_excel_filtrado(fecha, *, attachment_report=None):
    """Genera y valida un Excel separado del original."""

    attachment_lookup = build_attachment_status_lookup(
        attachment_report
    )

    carpeta = CARPETA_ORIGINALES / fecha

    ruta_filtros = carpeta / "filtros_preliminares.json"
    ruta_detalles = carpeta / "detalles_licitaciones.json"

    reporte = json.loads(
        ruta_filtros.read_text(encoding="utf-8")
    )

    datos = json.loads(
        ruta_detalles.read_text(encoding="utf-8")
    )

    if reporte.get("fecha_publicacion") != fecha:
        raise ValueError("Fecha incorrecta en el reporte.")

    if datos.get("fecha") != fecha:
        raise ValueError("Fecha incorrecta en los detalles.")

    resultados = reporte["resultados"]
    detalles = datos["detalles"]
    ids = datos["ids"]

    if (
        len(ids) != len(set(ids))
        or len(resultados) != len(ids)
        or {fila["id"] for fila in resultados} != set(ids)
        or set(detalles) != set(ids)
    ):
        raise ValueError("Inconsistencia entre los registros.")

    conteos = Counter(
        fila["estado"] for fila in resultados
    )

    for estado in (
        "incluida",
        "posible_tienda",
        "revision_manual",
        "excluida",
    ):
        if conteos[estado] != reporte["resumen"].get(estado, 0):
            raise ValueError(
                f"Conteo inconsistente: {estado}"
            )

    libro = Workbook()

    crear_resumen(libro, reporte)

    distribucion = [
        ("Incluidas", "incluida"),
        ("Posible para Tienda", "posible_tienda"),
        ("Revision manual", "revision_manual"),
        ("Excluidas", "excluida"),
    ]

    for nombre, estado in distribucion:
        filas = [
            fila for fila in resultados
            if fila["estado"] == estado
        ]

        crear_hoja_licitaciones(
            libro,
            nombre,
            filas,
            detalles,
            reporte,
            attachment_lookup=attachment_lookup,
        )

    ruta_salida = (
        carpeta / f"Licitaciones_Filtradas_{fecha}.xlsx"
    )

    ruta_temporal = ruta_salida.with_suffix(".tmp.xlsx")

    try:
        libro.save(ruta_temporal)

        verificacion = load_workbook(
            ruta_temporal,
            read_only=True,
            data_only=True,
        )

        try:
            for nombre, estado in distribucion:
                hoja = verificacion[nombre]
                filas = hoja.max_row - 1

                if filas != conteos[estado]:
                    raise RuntimeError(
                        f"Conteo incorrecto en {nombre}."
                    )

                if hoja.max_column != len(ENCABEZADOS):
                    raise RuntimeError(
                        f"Columnas incorrectas en {nombre}."
                    )

            if "Resumen" not in verificacion.sheetnames:
                raise RuntimeError(
                    "Falta la hoja de resumen."
                )

        finally:
            verificacion.close()

        os.replace(ruta_temporal, ruta_salida)

    finally:
        libro.close()
        ruta_temporal.unlink(missing_ok=True)

    print("=== EXCEL FILTRADO GENERADO ===")
    print("Fecha:", fecha)
    print("Total:", len(resultados))

    for estado, cantidad in conteos.items():
        print(f"{estado}: {cantidad}")

    print("Archivo:", ruta_salida)
    print("RESULTADO: APROBADO")

    return ruta_salida
