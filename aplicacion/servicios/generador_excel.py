"""Generación del Excel original de licitaciones de Mercado Público."""

import json
import os
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from aplicacion.servicios.mercado_publico import CARPETA_ORIGINALES


ENCABEZADOS = [
    "ID",
    "Nombre",
    "Fecha Publicación",
    "Fecha Cierre",
    "Monto Estimado",
    "Archivos Descargables",
]


def convertir_fecha(valor):
    """Convierte fechas de la API a valores compatibles con Excel."""
    if not valor:
        return None

    if isinstance(valor, datetime):
        return valor

    texto = str(valor).strip()

    for formato in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue

    return texto


def convertir_monto(valor):
    """Convierte montos numéricos conservando valores no reconocidos."""
    if valor is None or valor == "":
        return None

    try:
        numero = float(valor)
        return int(numero) if numero.is_integer() else numero
    except (ValueError, TypeError, OverflowError):
        return str(valor)


def generar_excel_original(fecha):
    """Genera y valida el Excel original sin aplicar filtros."""

    carpeta = CARPETA_ORIGINALES / fecha
    ruta_lista = carpeta / "licitaciones_publicadas.json"
    ruta_detalles = carpeta / "detalles_licitaciones.json"

    lista = json.loads(ruta_lista.read_text(encoding="utf-8"))
    progreso = json.loads(ruta_detalles.read_text(encoding="utf-8"))

    if lista.get("fecha") != fecha or progreso.get("fecha") != fecha:
        raise ValueError("Las fechas de los archivos no coinciden.")

    ids = [
        str(item.get("CodigoExterno") or "").strip()
        for item in lista["licitaciones"]
    ]

    detalles = progreso["detalles"]
    errores = progreso.get("errores", {})

    if not ids or not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("Existen identificadores inválidos o duplicados.")

    if progreso.get("ids") != ids:
        raise ValueError("El orden de los identificadores no coincide.")

    if errores:
        raise ValueError("Existen errores pendientes en los detalles.")

    if set(ids) != set(detalles):
        raise ValueError("Los detalles no coinciden con el listado original.")

    for codigo in ids:
        detalle = detalles[codigo]

        if (
            not isinstance(detalle, dict)
            or str(detalle.get("CodigoExterno") or "").strip() != codigo
        ):
            raise ValueError(f"Detalle inválido: {codigo}")

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Licitaciones"
    hoja.append(ENCABEZADOS)

    sin_monto = 0
    sin_publicacion = 0
    sin_cierre = 0

    for codigo in ids:
        detalle = detalles[codigo]
        fechas = detalle.get("Fechas") or {}

        publicacion = convertir_fecha(fechas.get("FechaPublicacion"))
        cierre = convertir_fecha(fechas.get("FechaCierre"))
        monto = convertir_monto(detalle.get("MontoEstimado"))

        sin_monto += monto is None
        sin_publicacion += publicacion is None
        sin_cierre += cierre is None

        hoja.append([
            codigo,
            detalle.get("Nombre") or "",
            publicacion,
            cierre,
            monto,
            "Pendiente de verificación",
        ])

    color_encabezado = "17365D"
    color_alternado = "EAF1F8"
    color_pendiente = "FFF2CC"

    for celda in hoja[1]:
        celda.fill = PatternFill("solid", fgColor=color_encabezado)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.alignment = Alignment(
            horizontal="center",
            vertical="center",
        )

    hoja.row_dimensions[1].height = 30

    anchos = {
        "A": 22,
        "B": 75,
        "C": 23,
        "D": 23,
        "E": 22,
        "F": 30,
    }

    for columna, ancho in anchos.items():
        hoja.column_dimensions[columna].width = ancho

    for numero_fila, codigo in enumerate(ids, start=2):
        if numero_fila % 2 == 0:
            for celda in hoja[numero_fila]:
                celda.fill = PatternFill(
                    "solid",
                    fgColor=color_alternado,
                )

        for columna in (3, 4):
            celda = hoja.cell(numero_fila, columna)

            if isinstance(celda.value, datetime):
                celda.number_format = "DD-MM-YYYY HH:MM"

        hoja.cell(numero_fila, 5).number_format = '#,##0.##'

        pendiente = hoja.cell(numero_fila, 6)
        pendiente.fill = PatternFill(
            "solid",
            fgColor=color_pendiente,
        )
        pendiente.alignment = Alignment(horizontal="center")

        identificador = hoja.cell(numero_fila, 1)
        identificador.hyperlink = (
            "https://www.mercadopublico.cl/"
            "Procurement/Modules/RFB/"
            f"DetailsAcquisition.aspx?idlicitacion={codigo}"
        )
        identificador.font = Font(
            color="0563C1",
            underline="single",
        )

    hoja.freeze_panes = "C2"
    hoja.auto_filter.ref = hoja.dimensions

    ruta_salida = (
        carpeta / f"Licitaciones_Mercado_Publico_{fecha}.xlsx"
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
            hoja_verificada = verificacion["Licitaciones"]
            filas = hoja_verificada.max_row - 1
            columnas = hoja_verificada.max_column
        finally:
            verificacion.close()

        if filas != len(ids) or columnas != len(ENCABEZADOS):
            raise RuntimeError(
                "La validación del archivo Excel no fue satisfactoria."
            )

        os.replace(ruta_temporal, ruta_salida)

    finally:
        libro.close()
        ruta_temporal.unlink(missing_ok=True)

    print("=== EXCEL ORIGINAL GENERADO ===")
    print("Fecha:", fecha)
    print("Licitaciones exportadas:", filas)
    print("Columnas:", columnas)
    print("Sin monto estimado:", sin_monto)
    print("Sin fecha publicación:", sin_publicacion)
    print("Sin fecha cierre:", sin_cierre)
    print("Adjuntos pendientes:", filas)
    print("Archivo:", ruta_salida)
    print("RESULTADO: APROBADO")

    return ruta_salida
