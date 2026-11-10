"""Obtencion de detalles de licitaciones con guardado y reanudacion."""

import json
import os
import time
from pathlib import Path

import requests

from aplicacion.servicios.mercado_publico import (
    URL_API,
    CARPETA_ORIGINALES,
    guardar_json_atomico,
)


def obtener_detalles(fecha, limite=None, intervalo=2.0):
    """Obtiene detalles pendientes y permite reanudar el proceso."""

    carpeta = CARPETA_ORIGINALES / fecha
    ruta_lista = carpeta / "licitaciones_publicadas.json"
    ruta_detalles = carpeta / "detalles_licitaciones.json"

    if not ruta_lista.is_file():
        raise FileNotFoundError(
            f"No existe el listado original: {ruta_lista}"
        )

    datos_lista = json.loads(
        ruta_lista.read_text(encoding="utf-8")
    )

    if datos_lista.get("fecha") != fecha:
        raise ValueError("La fecha del listado no coincide.")

    licitaciones = datos_lista["licitaciones"]

    ids = [
        str(item.get("CodigoExterno") or "").strip()
        for item in licitaciones
    ]

    if not ids or not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("El listado contiene IDs invalidos o duplicados.")

    if limite is not None and (
        not isinstance(limite, int)
        or isinstance(limite, bool)
        or limite < 1
    ):
        raise ValueError("El limite debe ser un entero positivo.")

    if intervalo < 0:
        raise ValueError("El intervalo no puede ser negativo.")

    ticket = os.environ.get("API_MP", "").strip()

    if not ticket:
        raise RuntimeError("No se encontro la credencial API_MP.")

    detalles = {}
    errores = {}
    intentos = {}

    if ruta_detalles.exists():
        progreso = json.loads(
            ruta_detalles.read_text(encoding="utf-8")
        )

        if progreso.get("fecha") != fecha:
            raise ValueError("La fecha del progreso no coincide.")

        if progreso.get("ids") != ids:
            raise ValueError(
                "El listado cambio desde el ultimo guardado. "
                "Se requiere revision antes de continuar."
            )

        detalles = progreso.get("detalles", {})
        errores = progreso.get("errores", {})
        intentos = progreso.get("intentos", {})

        if not all(
            isinstance(valor, dict)
            and str(valor.get("CodigoExterno") or "").strip() == codigo
            and codigo in ids
            for codigo, valor in detalles.items()
        ):
            raise ValueError(
                "El archivo de progreso contiene detalles invalidos."
            )

    def guardar_progreso():
        guardar_json_atomico(
            ruta_detalles,
            {
                "fecha": fecha,
                "ids": ids,
                "detalles": detalles,
                "errores": errores,
                "intentos": intentos,
            },
        )

    pendientes = [
        codigo for codigo in ids
        if codigo not in detalles
    ]

    if limite is not None:
        pendientes = pendientes[:limite]

    print("=== RECUPERACION DE DETALLES ===")
    print("Fecha:", fecha)
    print("Total de licitaciones:", len(ids))
    print("Detalles recuperados:", len(detalles))
    print("Solicitudes pendientes seleccionadas:", len(pendientes))
    print("Intervalo:", intervalo, "segundos")

    procesadas = 0
    inicio = time.monotonic()

    for codigo in pendientes:
        if procesadas > 0:
            time.sleep(intervalo)

        print(
            f"\n{procesadas + 1}/{len(pendientes)} | {codigo}",
            flush=True,
        )

        try:
            respuesta = requests.get(
                URL_API,
                params={
                    "codigo": codigo,
                    "ticket": ticket,
                },
                timeout=60,
            )

            respuesta.raise_for_status()

            contenido = respuesta.json()

            if not isinstance(contenido, dict):
                raise ValueError("Respuesta JSON invalida.")

            listado = contenido.get("Listado")

            if not isinstance(listado, list) or not listado:
                raise ValueError("Listado vacio o invalido.")

            detalle = listado[0]

            if not isinstance(detalle, dict):
                raise ValueError("Detalle invalido.")

            codigo_recibido = str(
                detalle.get("CodigoExterno") or ""
            ).strip()

            if codigo_recibido != codigo:
                raise ValueError(
                    "El codigo recibido no coincide con el solicitado."
                )

        except (requests.RequestException, ValueError) as error:
            errores[codigo] = str(error)
            intentos[codigo] = intentos.get(codigo, 0) + 1

            guardar_progreso()

            print("ERROR:", error)
            print("Proceso detenido sin reintentos automaticos.")
            break

        detalles[codigo] = detalle
        errores.pop(codigo, None)
        intentos[codigo] = intentos.get(codigo, 0) + 1

        guardar_progreso()

        procesadas += 1

        print("OK | Tipo:", detalle.get("Tipo"))
        print(
            "Progreso total:",
            f"{len(detalles)}/{len(ids)}",
            f"({len(detalles) / len(ids) * 100:.2f}%)",
        )

    duracion = time.monotonic() - inicio

    print("\n=== RESUMEN ===")
    print("Detalles guardados:", len(detalles))
    print("Pendientes:", len(ids) - len(detalles))
    print("Errores registrados:", len(errores))
    print("Duracion (s):", round(duracion, 2))
    print("Archivo:", ruta_detalles)

    return {
        "total": len(ids),
        "obtenidos": len(detalles),
        "pendientes": len(ids) - len(detalles),
        "errores": len(errores),
    }
