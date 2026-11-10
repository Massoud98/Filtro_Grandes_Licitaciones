"""Generación del Excel de licitaciones filtradas."""

import json
import os
from collections import Counter
from datetime import datetime
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


ENCABEZADOS = [
    "ID",
    "Tipo",
    "Nombre",
    "Fecha publicación",
    "Fecha cierre",
    "Monto estimado",
    "Estado",
    "Motivos / observaciones",
    "Clasificación L1",
    "Adjuntos",
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

    anchos = [22, 12, 75, 23, 23, 22, 20, 65, 24, 30]

    for indice, ancho in enumerate(anchos, start=1):
        letra = get_column_letter(indice)
        hoja.column_dimensions[letra].width = ancho

    hoja.freeze_panes = "D2"
    hoja.auto_filter.ref = hoja.dimensions


def crear_hoja_licitaciones(libro, nombre, filas, detalles):
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
            fila["estado"],
            " | ".join(explicaciones),
            estado_l1,
            "Pendiente de verificación",
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

        hoja.cell(numero_fila, 6).number_format = '#,##0.##'

        estado = hoja.cell(numero_fila, 7)
        estado.fill = PatternFill(
            "solid",
            fgColor=COLORES[fila["estado"]],
        )
        estado.alignment = Alignment(horizontal="center")

        motivo = hoja.cell(numero_fila, 8)
        motivo.alignment = Alignment(
            vertical="top",
            wrap_text=True,
        )

        pendiente = hoja.cell(numero_fila, 10)
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
    """Crea el resumen de la evaluación."""

    hoja = libro.active
    hoja.title = "Resumen"

    hoja.append(["Resumen de licitaciones filtradas", "Valor"])
    preparar_encabezado(hoja)

    resumen = reporte["resumen"]
    total = reporte["total"]

    datos = [
        ("Fecha de publicación", reporte["fecha_publicacion"]),
        ("Fecha de evaluación", reporte["evaluado_en"]),
        ("Cierre mínimo", reporte["cierre_minimo"]),
        ("Total licitaciones", total),
        ("Incluidas", resumen["incluida"]),
        ("Revisión manual", resumen["revision_manual"]),
        ("Excluidas", resumen["excluida"]),
        (
            "Porcentaje incluidas",
            resumen["incluida"] / total if total else 0,
        ),
        (
            "Porcentaje excluidas",
            resumen["excluida"] / total if total else 0,
        ),
    ]

    for etiqueta, valor in datos:
        hoja.append([etiqueta, valor])

    hoja.column_dimensions["A"].width = 36
    hoja.column_dimensions["B"].width = 44

    for fila in (9, 10):
        hoja.cell(fila, 2).number_format = "0.0%"

    hoja.freeze_panes = "A2"

    return hoja


def generar_excel_filtrado(fecha):
    """Genera y valida un Excel separado del original."""

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
        "revision_manual",
        "excluida",
    ):
        if conteos[estado] != reporte["resumen"][estado]:
            raise ValueError(
                f"Conteo inconsistente: {estado}"
            )

    libro = Workbook()

    crear_resumen(libro, reporte)

    distribucion = [
        ("Incluidas", "incluida"),
        ("Revisión manual", "revision_manual"),
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
