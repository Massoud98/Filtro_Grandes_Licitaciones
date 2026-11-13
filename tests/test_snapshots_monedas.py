import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from aplicacion.servicios import snapshots_monedas as snapshots
from aplicacion.servicios.banco_central import ErrorBancoCentral
from aplicacion.servicios.conversion_monedas import SERIES_MONEDAS


FECHA = date(2026, 11, 10)


def tasas_validas():
    return {
        moneda: {
            "moneda": moneda,
            "serie": serie,
            "fecha_tasa": (
                "2026-11-01" if moneda == "UTM" else "2026-11-10"
            ),
            "valor_clp": {
                "USD": "969.80",
                "CLF": "41302.33",
                "UTM": "72440",
            }[moneda],
        }
        for moneda, serie in SERIES_MONEDAS.items()
    }


class PruebasSnapshotsMonedas(unittest.TestCase):

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)

        self.carpeta = Path(self.temporal.name) / "tipos_cambio"

        parche = patch.object(
            snapshots,
            "CARPETA_TASAS",
            self.carpeta,
        )
        parche.start()
        self.addCleanup(parche.stop)

    def ruta(self):
        return self.carpeta / "2026-11-10.json"

    def test_crea_snapshot(self):
        with patch.object(
            snapshots,
            "consultar_todas_las_tasas",
            return_value=tasas_validas(),
        ) as consulta:
            resultado = snapshots.obtener_snapshot(FECHA)

        consulta.assert_called_once()
        self.assertTrue(self.ruta().is_file())
        self.assertEqual(resultado["fecha_revision"], "2026-11-10")
        self.assertEqual(resultado["tasas"]["USD"]["valor_clp"], "969.80")

    def test_reutiliza_snapshot_sin_consultar_api(self):
        with patch.object(
            snapshots,
            "consultar_todas_las_tasas",
            return_value=tasas_validas(),
        ):
            primero = snapshots.obtener_snapshot(FECHA)

        contenido_original = self.ruta().read_bytes()

        with patch.object(
            snapshots,
            "consultar_todas_las_tasas",
            side_effect=AssertionError("Unexpected API call"),
        ):
            segundo = snapshots.obtener_snapshot(FECHA)

        self.assertEqual(primero, segundo)
        self.assertEqual(self.ruta().read_bytes(), contenido_original)

    def test_rechaza_snapshot_corrupto_sin_sobrescribir(self):
        self.carpeta.mkdir(parents=True)
        self.ruta().write_text("{invalid json", encoding="utf-8")
        contenido_original = self.ruta().read_bytes()

        with patch.object(
            snapshots,
            "consultar_todas_las_tasas",
            side_effect=AssertionError("Unexpected API call"),
        ):
            with self.assertRaises(snapshots.ErrorSnapshotMonedas):
                snapshots.obtener_snapshot(FECHA)

        self.assertEqual(self.ruta().read_bytes(), contenido_original)

    def test_rechaza_snapshot_incompleto(self):
        datos = {
            "version": 1,
            "fecha_revision": FECHA.isoformat(),
            "tasas": tasas_validas(),
        }
        del datos["tasas"]["UTM"]

        self.carpeta.mkdir(parents=True)
        self.ruta().write_text(
            json.dumps(datos),
            encoding="utf-8",
        )

        with self.assertRaises(snapshots.ErrorSnapshotMonedas):
            snapshots.obtener_snapshot(FECHA)

    def test_fallo_api_no_crea_snapshot(self):
        with patch.object(
            snapshots,
            "consultar_todas_las_tasas",
            side_effect=ErrorBancoCentral("Service unavailable"),
        ):
            with self.assertRaises(ErrorBancoCentral):
                snapshots.obtener_snapshot(FECHA)

        self.assertFalse(self.ruta().exists())

    def test_fecha_invalida(self):
        for valor in ("2026-11-10", None, 20261110):
            with self.subTest(valor=valor):
                with self.assertRaises(TypeError):
                    snapshots.obtener_snapshot(valor)

    def test_rechaza_fecha_futura_en_tasa(self):
        tasas = tasas_validas()
        tasas["USD"]["fecha_tasa"] = "2026-11-11"

        datos = {
            "version": 1,
            "fecha_revision": FECHA.isoformat(),
            "tasas": tasas,
        }

        with self.assertRaises(snapshots.ErrorSnapshotMonedas):
            snapshots.validar_snapshot(datos, FECHA)

    def test_rechaza_valor_no_finito(self):
        for valor in ("NaN", "Infinity", "0", "-1"):
            with self.subTest(valor=valor):
                tasas = tasas_validas()
                tasas["USD"]["valor_clp"] = valor

                datos = {
                    "version": 1,
                    "fecha_revision": FECHA.isoformat(),
                    "tasas": tasas,
                }

                with self.assertRaises(snapshots.ErrorSnapshotMonedas):
                    snapshots.validar_snapshot(datos, FECHA)


if __name__ == "__main__":
    unittest.main()
