import os
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import requests

from aplicacion.servicios.banco_central import (
    ErrorBancoCentral,
    consultar_tasa,
    consultar_todas_las_tasas,
    seleccionar_observacion,
)


FECHA = date(2026, 11, 10)


def observacion(fecha, valor, estado="OK"):
    return {
        "indexDateString": fecha,
        "value": valor,
        "statusCode": estado,
    }


class RespuestaSimulada:

    def __init__(self, datos=None, error_http=None, error_json=False):
        self.datos = datos
        self.error_http = error_http
        self.error_json = error_json

    def raise_for_status(self):
        if self.error_http:
            raise requests.HTTPError(self.error_http)

    def json(self):
        if self.error_json:
            raise ValueError("Invalid JSON")
        return self.datos


class SesionSimulada:

    def __init__(self, respuesta=None, error=None):
        self.respuesta = respuesta
        self.error = error
        self.llamadas = []

    def get(self, url, params=None, timeout=None):
        self.llamadas.append({
            "url": url,
            "params": params,
            "timeout": timeout,
        })

        if self.error:
            raise self.error

        return self.respuesta


def respuesta_correcta(serie, observaciones):
    return {
        "Codigo": 0,
        "Descripcion": "Success",
        "Series": {
            "seriesId": serie,
            "Obs": observaciones,
        },
    }


class PruebasBancoCentral(unittest.TestCase):

    def test_selecciona_fecha_mas_reciente(self):
        resultado = seleccionar_observacion(
            [
                observacion("09-11-2026", "979.88"),
                observacion("10-11-2026", "969.80"),
            ],
            FECHA,
        )
        self.assertEqual(resultado["fecha_tasa"], "2026-11-10")
        self.assertEqual(
            Decimal(resultado["valor_clp"]),
            Decimal("969.80"),
        )

    def test_fallback_fin_de_semana(self):
        resultado = seleccionar_observacion(
            [
                observacion("06-11-2026", "980.50"),
                observacion("07-11-2026", "NaN", "ND"),
                observacion("08-11-2026", "NaN", "ND"),
            ],
            date(2026, 11, 8),
        )
        self.assertEqual(resultado["fecha_tasa"], "2026-11-06")

    def test_ignora_fechas_futuras(self):
        resultado = seleccionar_observacion(
            [
                observacion("09-11-2026", "979.88"),
                observacion("11-11-2026", "950.00"),
            ],
            FECHA,
        )
        self.assertEqual(resultado["fecha_tasa"], "2026-11-09")

    def test_rechaza_observaciones_invalidas(self):
        invalidas = [
            observacion("10-11-2026", "NaN"),
            observacion("10-11-2026", "Infinity"),
            observacion("10-11-2026", "0"),
            observacion("10-11-2026", "-1"),
            observacion("10-11-2026", "969.80", "ND"),
            {"indexDateString": "invalid", "value": "100", "statusCode": "OK"},
            None,
        ]
        with self.assertRaises(ErrorBancoCentral):
            seleccionar_observacion(invalidas, FECHA)

    @patch.dict(os.environ, {"BCCH_API_TOKEN": "TEST_TOKEN"})
    def test_consulta_correcta(self):
        sesion = SesionSimulada(
            RespuestaSimulada(
                respuesta_correcta(
                    "F073.TCO.PRE.Z.D",
                    [observacion("10-11-2026", "969.80")],
                )
            )
        )
        resultado = consultar_tasa("USD", FECHA, sesion=sesion)

        self.assertEqual(resultado["moneda"], "USD")
        self.assertEqual(resultado["fecha_tasa"], "2026-11-10")
        self.assertEqual(resultado["valor_clp"], "969.80")
        self.assertEqual(
            sesion.llamadas[0]["params"]["timeseries"],
            "F073.TCO.PRE.Z.D",
        )
        self.assertEqual(
            sesion.llamadas[0]["params"]["lastdate"],
            "2026-11-10",
        )
        self.assertEqual(sesion.llamadas[0]["timeout"], 30)

    @patch.dict(os.environ, {"BCCH_API_TOKEN": ""})
    def test_token_ausente(self):
        with self.assertRaisesRegex(
            ErrorBancoCentral, "token unavailable"
        ):
            consultar_tasa("USD", FECHA)

    @patch.dict(os.environ, {"BCCH_API_TOKEN": "SECRET_TEST_TOKEN"})
    def test_token_rechazado_sin_exponer_secreto(self):
        sesion = SesionSimulada(
            RespuestaSimulada({
                "Codigo": -1,
                "Descripcion": "Invalid token",
            })
        )
        with self.assertRaises(ErrorBancoCentral) as contexto:
            consultar_tasa("USD", FECHA, sesion=sesion)

        self.assertNotIn(
            "SECRET_TEST_TOKEN",
            str(contexto.exception),
        )

    @patch.dict(os.environ, {"BCCH_API_TOKEN": "TEST_TOKEN"})
    def test_error_de_red(self):
        sesion = SesionSimulada(
            error=requests.ConnectionError("Connection failed")
        )
        with self.assertRaises(ErrorBancoCentral):
            consultar_tasa("USD", FECHA, sesion=sesion)

    @patch.dict(os.environ, {"BCCH_API_TOKEN": "TEST_TOKEN"})
    def test_error_http(self):
        sesion = SesionSimulada(
            RespuestaSimulada(error_http="HTTP 503")
        )
        with self.assertRaises(ErrorBancoCentral):
            consultar_tasa("USD", FECHA, sesion=sesion)

    @patch.dict(os.environ, {"BCCH_API_TOKEN": "TEST_TOKEN"})
    def test_json_invalido(self):
        sesion = SesionSimulada(
            RespuestaSimulada(error_json=True)
        )
        with self.assertRaises(ErrorBancoCentral):
            consultar_tasa("USD", FECHA, sesion=sesion)

    @patch.dict(os.environ, {"BCCH_API_TOKEN": "TEST_TOKEN"})
    def test_respuesta_incompleta(self):
        for datos in (None, {}, {"Codigo": 0}, {"Codigo": 0, "Series": {}}):
            with self.subTest(datos=datos):
                sesion = SesionSimulada(RespuestaSimulada(datos))
                with self.assertRaises(ErrorBancoCentral):
                    consultar_tasa("USD", FECHA, sesion=sesion)

    def test_moneda_no_soportada(self):
        with self.assertRaises(ValueError):
            consultar_tasa("EUR", FECHA)

    @patch.dict(os.environ, {"BCCH_API_TOKEN": "TEST_TOKEN"})
    def test_consulta_todas_las_tasas(self):
        class SesionMultiple:
            def get(self, url, params=None, timeout=None):
                return RespuestaSimulada(
                    respuesta_correcta(
                        params["timeseries"],
                        [observacion("10-11-2026", "100")],
                    )
                )

        resultados = consultar_todas_las_tasas(
            FECHA,
            sesion=SesionMultiple(),
        )
        self.assertEqual(set(resultados), {"USD", "CLF", "UTM"})


if __name__ == "__main__":
    unittest.main()
