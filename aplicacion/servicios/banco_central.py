"""Read-only Banco Central exchange-rate API client."""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests

from aplicacion.servicios.conversion_monedas import SERIES_MONEDAS


URL_API = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"


class ErrorBancoCentral(Exception):
    """Banco Central API request or validation failure."""


def seleccionar_observacion(observaciones, fecha_revision):
    """Select the latest valid observation on or before review date."""

    validas = []

    for observacion in observaciones:
        if not isinstance(observacion, dict):
            continue

        if observacion.get("statusCode") != "OK":
            continue

        try:
            fecha = datetime.strptime(
                observacion["indexDateString"],
                "%d-%m-%Y",
            ).date()

            valor = Decimal(str(observacion["value"]))
        except (KeyError, ValueError, TypeError, InvalidOperation):
            continue

        if not valor.is_finite() or valor <= 0:
            continue

        if fecha <= fecha_revision:
            validas.append((fecha, valor))

    if not validas:
        raise ErrorBancoCentral("No valid exchange rate available.")

    fecha, valor = max(validas, key=lambda item: item[0])

    return {
        "fecha_tasa": fecha.isoformat(),
        "valor_clp": str(valor),
    }


def consultar_tasa(moneda, fecha_revision, sesion=None):
    """Retrieve an official rate without modifying local files."""

    if moneda not in SERIES_MONEDAS:
        raise ValueError("Unsupported currency.")

    if not isinstance(fecha_revision, date):
        raise TypeError("Review date must be a date.")

    token = os.environ.get("BCCH_API_TOKEN")

    if not token:
        raise ErrorBancoCentral(
            "Banco Central token unavailable. Configure BCCH_API_TOKEN."
        )

    inicio = fecha_revision - timedelta(days=45)

    parametros = {
        "token": token,
        "function": "GetSeries",
        "timeseries": SERIES_MONEDAS[moneda],
        "firstdate": inicio.isoformat(),
        "lastdate": fecha_revision.isoformat(),
    }

    cliente = sesion if sesion is not None else requests

    try:
        respuesta = cliente.get(
            URL_API,
            params=parametros,
            timeout=30,
        )
        respuesta.raise_for_status()
        datos = respuesta.json()
    except requests.RequestException as exc:
        raise ErrorBancoCentral(
            "Banco Central connection or HTTP error."
        ) from None
    except ValueError:
        raise ErrorBancoCentral(
            "Banco Central returned invalid JSON."
        ) from None

    if not isinstance(datos, dict):
        raise ErrorBancoCentral(
            "Banco Central returned an unexpected response."
        )

    if datos.get("Codigo") != 0:
        raise ErrorBancoCentral(
            "Banco Central API rejected the request. "
            "Check token validity and service availability. "
            f"API code: {datos.get('Codigo')}"
        )

    serie = datos.get("Series")

    if not isinstance(serie, dict):
        raise ErrorBancoCentral("Missing series data.")

    observaciones = serie.get("Obs")

    if not isinstance(observaciones, list):
        raise ErrorBancoCentral("Missing observation list.")

    resultado = seleccionar_observacion(
        observaciones,
        fecha_revision,
    )

    resultado["moneda"] = moneda
    resultado["serie"] = SERIES_MONEDAS[moneda]

    return resultado


def consultar_todas_las_tasas(fecha_revision, sesion=None):
    """Retrieve USD, UF and UTM rates for one review date."""

    resultados = {}

    for moneda in SERIES_MONEDAS:
        resultados[moneda] = consultar_tasa(
            moneda,
            fecha_revision,
            sesion=sesion,
        )

    return resultados
