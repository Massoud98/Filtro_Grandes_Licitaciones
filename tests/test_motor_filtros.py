"""Pruebas aisladas del motor de filtros."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from aplicacion.servicios import filtros_preliminares as motor


FECHA = "2026-11-09"

EVALUACION = datetime(
    2026, 11, 10, 19, 54, 54,
    tzinfo=motor.ZONA,
)


def crear_item(codigo, nombre):
    return {
        "CodigoCategoria": codigo,
        "NombreProducto": nombre,
        "Descripcion": "",
        "Categoria": "",
    }


def crear_detalle(tipo, cierre, items=None):
    return {
        "Tipo": tipo,
        "Nombre": "Licitacion de prueba",
        "Fechas": {
            "FechaCierre": cierre.isoformat(),
        },
        "Items": {
            "Listado": items or [],
        },
    }


class PruebasMotorFiltros(unittest.TestCase):

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)

        self.raiz = Path(self.temporal.name)
        self.carpeta = self.raiz / FECHA
        self.carpeta.mkdir()

        parche = patch.object(
            motor,
            "CARPETA_ORIGINALES",
            self.raiz,
        )
        parche.start()
        self.addCleanup(parche.stop)

    def ejecutar(self, tipo, cierre, items=None):
        codigo = "TEST-1"

        contenido = {
            "fecha": FECHA,
            "ids": [codigo],
            "detalles": {
                codigo: crear_detalle(
                    tipo, cierre, items
                ),
            },
        }

        ruta = self.carpeta / "detalles_licitaciones.json"
        ruta.write_text(
            json.dumps(contenido),
            encoding="utf-8",
        )

        resultado = motor.aplicar_filtros(
            FECHA,
            evaluacion=EVALUACION,
        )

        self.assertEqual(resultado["total"], 1)

        salida = (
            self.carpeta / "filtros_preliminares.json"
        )
        self.assertTrue(salida.is_file())

        return resultado["resultados"][0]

    def test_o1_excluida(self):
        fila = self.ejecutar(
            "O1",
            EVALUACION + timedelta(days=10),
        )
        self.assertEqual(fila["estado"], "excluida")

    def test_cierre_exactamente_siete_dias(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=7),
        )
        self.assertEqual(fila["estado"], "incluida")

    def test_cierre_un_segundo_antes(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(
                days=7, seconds=-1
            ),
        )
        self.assertEqual(fila["estado"], "incluida")

    def test_l1_vestimenta(self):
        fila = self.ejecutar(
            "L1",
            EVALUACION + timedelta(days=10),
            [crear_item("53103000", "Poleras")],
        )
        self.assertEqual(fila["estado"], "incluida")

    def test_l1_no_relevante(self):
        fila = self.ejecutar(
            "L1",
            EVALUACION + timedelta(days=10),
            [crear_item("43211500", "Notebook")],
        )
        self.assertEqual(fila["estado"], "excluida")

    def test_l1_ambiguo(self):
        fila = self.ejecutar(
            "L1",
            EVALUACION + timedelta(days=10),
            [crear_item(
                "91111700",
                "Confeccion de vestuario",
            )],
        )
        self.assertEqual(
            fila["estado"],
            "incluida",
        )

    def test_exclusion_prioritaria(self):
        fila = self.ejecutar(
            "L1",
            EVALUACION + timedelta(days=2),
            [crear_item(
                "91111700",
                "Confeccion de vestuario",
            )],
        )
        self.assertEqual(fila["estado"], "incluida")
        self.assertFalse(fila["razones"])
        self.assertTrue(fila["observaciones"])
        self.assertTrue(
            any(
                "dias" in observacion.lower()
                for observacion in fila["observaciones"]
            )
        )


if __name__ == "__main__":
    unittest.main()
