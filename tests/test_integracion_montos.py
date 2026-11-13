"""Integration tests for monetary tender filtering."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from aplicacion.servicios import filtros_preliminares as motor


FECHA = "2026-11-09"
EVALUACION = datetime(2026, 11, 10, 19, 54, 54, tzinfo=motor.ZONA)

SNAPSHOT = {
    "version": 1,
    "fecha_revision": "2026-11-10",
    "tasas": {
        "USD": {
            "moneda": "USD",
            "serie": "F073.TCO.PRE.Z.D",
            "valor_clp": "969.8",
            "fecha_tasa": "2026-11-10",
        },
        "CLF": {
            "moneda": "CLF",
            "serie": "F073.UFF.PRE.Z.D",
            "valor_clp": "41302.33",
            "fecha_tasa": "2026-11-10",
        },
        "UTM": {
            "moneda": "UTM",
            "serie": "F073.UTR.PRE.Z.M",
            "valor_clp": "72440",
            "fecha_tasa": "2026-11-01",
        },
    },
}


class PruebasIntegracionMontos(unittest.TestCase):

    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)

        raiz = Path(temporal.name)
        self.carpeta = raiz / FECHA
        self.carpeta.mkdir()

        parche = patch.object(motor, "CARPETA_ORIGINALES", raiz)
        parche.start()
        self.addCleanup(parche.stop)

    def ejecutar(self, monto, moneda, tipo="LE", snapshot=SNAPSHOT):
        codigo = "TEST-1"

        detalle = {
            "Tipo": tipo,
            "Nombre": "Licitacion de prueba",
            "MontoEstimado": monto,
            "Moneda": moneda,
            "Fechas": {
                "FechaCierre": (
                    EVALUACION + timedelta(days=10)
                ).isoformat(),
            },
            "Items": {"Listado": []},
        }

        datos = {
            "fecha": FECHA,
            "ids": [codigo],
            "detalles": {codigo: detalle},
        }

        ruta = self.carpeta / "detalles_licitaciones.json"
        ruta.write_text(json.dumps(datos), encoding="utf-8")

        with patch(
            "aplicacion.servicios.filtros_preliminares.obtener_snapshot",
            return_value=snapshot,
        ):
            resultado = motor.aplicar_filtros(
                FECHA,
                evaluacion=EVALUACION,
            )

        return resultado["resultados"][0]

    def test_clp_bajo_minimo_excluido(self):
        fila = self.ejecutar(19000000, "CLP")
        self.assertEqual(fila["estado"], "excluida")
        self.assertEqual(
            fila["evaluacion_monto"]["estado_monto"],
            "bajo_minimo",
        )

    def test_clp_exactamente_minimo_incluido(self):
        fila = self.ejecutar(20000000, "CLP")
        self.assertEqual(fila["estado"], "incluida")

    def test_usd_bajo_minimo_excluido(self):
        fila = self.ejecutar(10000, "USD")
        self.assertEqual(fila["estado"], "excluida")
        self.assertEqual(
            fila["evaluacion_monto"]["monto_clp"],
            "9698000.0",
        )

    def test_uf_sobre_minimo_incluido(self):
        fila = self.ejecutar(500, "CLF")
        self.assertEqual(fila["estado"], "incluida")

    def test_utm_bajo_minimo_excluido(self):
        fila = self.ejecutar(200, "UTM")
        self.assertEqual(fila["estado"], "excluida")

    def test_monto_ausente_incluido(self):
        fila = self.ejecutar(None, "CLP")
        self.assertEqual(fila["estado"], "incluida")

    def test_moneda_desconocida_revision_manual(self):
        fila = self.ejecutar(25000, None)
        self.assertEqual(fila["estado"], "incluida")

    def test_o1_sigue_excluida(self):
        fila = self.ejecutar(50000000, "CLP", tipo="O1")
        self.assertEqual(fila["estado"], "excluida")


    def test_foreign_currency_without_snapshot(self):
        fila = self.ejecutar(10000, "USD", snapshot=None)
        self.assertEqual(fila["estado"], "incluida")
        self.assertEqual(
            fila["evaluacion_monto"]["estado_monto"],
            "conversion_no_disponible",
        )

    def test_clp_without_snapshot(self):
        fila = self.ejecutar(19000000, "CLP", snapshot=None)
        self.assertEqual(fila["estado"], "excluida")
        self.assertEqual(
            fila["evaluacion_monto"]["estado_monto"],
            "bajo_minimo",
        )


    def _ejecutar_con_error_snapshot(self, error):
        codigo = "TEST-BCCH-ERROR"

        detalle = {
            "Tipo": "LE",
            "Nombre": "Licitacion con moneda extranjera",
            "MontoEstimado": 10000,
            "Moneda": "USD",
            "Fechas": {
                "FechaCierre": (
                    EVALUACION + timedelta(days=10)
                ).isoformat(),
            },
            "Items": {"Listado": []},
        }

        datos = {
            "fecha": FECHA,
            "ids": [codigo],
            "detalles": {codigo: detalle},
        }

        ruta = self.carpeta / "detalles_licitaciones.json"
        ruta.write_text(json.dumps(datos), encoding="utf-8")

        with patch.object(
            motor,
            "obtener_snapshot",
            side_effect=error,
        ):
            return motor.aplicar_filtros(
                FECHA,
                evaluacion=EVALUACION,
            )

    def test_banco_central_exception(self):
        resultado = self._ejecutar_con_error_snapshot(
            motor.ErrorBancoCentral("Simulated API failure")
        )

        fila = resultado["resultados"][0]

        self.assertEqual(fila["estado"], "incluida")
        self.assertFalse(fila["evaluacion_monto"]["excluir"])
        self.assertEqual(
            fila["evaluacion_monto"]["estado_monto"],
            "conversion_no_disponible",
        )
        self.assertEqual(
            resultado["error_conversion"],
            "ErrorBancoCentral",
        )
        self.assertIsNone(resultado["snapshot_monedas"])

    def test_snapshot_exception(self):
        resultado = self._ejecutar_con_error_snapshot(
            motor.ErrorSnapshotMonedas("Simulated snapshot failure")
        )

        fila = resultado["resultados"][0]

        self.assertEqual(fila["estado"], "incluida")
        self.assertFalse(fila["evaluacion_monto"]["excluir"])
        self.assertEqual(
            resultado["error_conversion"],
            "ErrorSnapshotMonedas",
        )

    def test_unexpected_runtime_error_propagates(self):
        with self.assertRaises(RuntimeError):
            self._ejecutar_con_error_snapshot(
                RuntimeError("Unexpected programming error")
            )

    def test_unexpected_type_error_propagates(self):
        with self.assertRaises(TypeError):
            self._ejecutar_con_error_snapshot(
                TypeError("Unexpected programming error")
            )


if __name__ == "__main__":
    unittest.main()
