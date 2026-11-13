"""Pruebas de clasificacion L1 y fechas."""

import unittest
from datetime import datetime, timedelta

from aplicacion.servicios.filtros_preliminares import (
    ZONA,
    clasificar_l1,
    interpretar_fecha,
)


def crear_detalle(items):
    return {
        "Items": {
            "Listado": items,
        }
    }


def crear_item(codigo, producto, descripcion=""):
    return {
        "CodigoCategoria": codigo,
        "NombreProducto": producto,
        "Descripcion": descripcion,
        "Categoria": "",
    }


class PruebasClasificacionL1(unittest.TestCase):

    def clasificar(self, items):
        return clasificar_l1(crear_detalle(items))

    def test_alimento_por_categoria(self):
        resultado = self.clasificar([
            crear_item("50112000", "Carne de vacuno")
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )

    def test_poleras(self):
        resultado = self.clasificar([
            crear_item("53103000", "Poleras deportivas")
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )

    def test_jockeys(self):
        resultado = self.clasificar([
            crear_item("53102500", "Jockeys institucionales")
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )

    def test_ropa_protectora_se_mantiene_incluida(self):
        resultado = self.clasificar([
            crear_item(
                "46181500",
                "Ropa reflectante o accesorios",
                "POLERA NEGRA DE ALGODON CON ESTAMPADO"
            )
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )

    def test_panales_categoria_ropa(self):
        resultado = self.clasificar([
            crear_item("53102300", "Pa?ales para beb?")
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )

    def test_ropa_protectora(self):
        resultado = self.clasificar([
            crear_item(
                "46181500",
                "Ropa reflectante o accesorios",
                "POLERA NEGRA DE ALGODON CON ESTAMPADO"
            )
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )

    def test_notebooks(self):
        resultado = self.clasificar([
            crear_item("43211500", "Notebook")
        ])
        self.assertEqual(
            resultado["clasificacion"], "excluir"
        )

    def test_centrifuga(self):
        resultado = self.clasificar([
            crear_item("41103900", "Centrifuga laboratorio")
        ])
        self.assertEqual(
            resultado["clasificacion"], "excluir"
        )

    def test_sin_items(self):
        resultado = self.clasificar([])
        self.assertEqual(
            resultado["clasificacion"], "excluir"
        )

    def test_productos_mixtos(self):
        resultado = self.clasificar([
            crear_item("53103000", "Poleras"),
            crear_item("43211500", "Notebook"),
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )

    def test_vestimenta_como_servicio(self):
        resultado = self.clasificar([
            crear_item("91111700", "Confeccion de vestuario")
        ])
        self.assertEqual(
            resultado["clasificacion"], "incluir"
        )


class PruebasFechas(unittest.TestCase):

    def test_fecha_sin_zona(self):
        fecha = interpretar_fecha("2026-11-18T09:20:00")
        self.assertEqual(fecha.tzinfo, ZONA)

    def test_fecha_invalida(self):
        self.assertIsNone(
            interpretar_fecha("fecha-invalida")
        )

    def test_diferencia_siete_dias(self):
        evaluacion = datetime(
            2026, 11, 10, 19, 54, 54,
            tzinfo=ZONA,
        )

        minimo = evaluacion + timedelta(days=7)

        self.assertEqual(
            minimo.date().isoformat(),
            "2026-11-17",
        )


if __name__ == "__main__":
    unittest.main()
