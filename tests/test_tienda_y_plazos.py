"""Regression tests for Tienda eligibility and short deadlines."""

import json
import unittest
from datetime import timedelta

from tests.test_motor_filtros import (
    EVALUACION,
    FECHA,
    PruebasMotorFiltros,
    crear_detalle,
    crear_item,
)


class PruebasTiendaYPlazos(unittest.TestCase):

    setUp = PruebasMotorFiltros.setUp

    def ejecutar(self, tipo, cierre, items=None, monto=15000000):
        codigo = "TEST-TIENDA-1"

        detalle = crear_detalle(tipo, cierre, items)
        detalle["MontoEstimado"] = monto
        detalle["Moneda"] = "CLP"

        contenido = {
            "fecha": FECHA,
            "ids": [codigo],
            "detalles": {codigo: detalle},
        }

        ruta = self.carpeta / "detalles_licitaciones.json"
        ruta.write_text(
            json.dumps(contenido),
            encoding="utf-8",
        )

        resultado = __import__(
            "aplicacion.servicios.filtros_preliminares",
            fromlist=["aplicar_filtros"],
        ).aplicar_filtros(FECHA, evaluacion=EVALUACION)

        return resultado["resultados"][0]

    def test_l1_alimentos_bajo_20m_tienda(self):
        fila = self.ejecutar(
            "L1",
            EVALUACION + timedelta(days=10),
            [crear_item("50112000", "Carne de vacuno")],
        )
        self.assertEqual(fila["estado"], "posible_tienda")

    def test_le_vestimenta_bajo_20m_tienda(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=10),
            [crear_item("53103000", "Poleras")],
        )
        self.assertEqual(fila["estado"], "posible_tienda")

    def test_lp_alimentos_plazo_corto(self):
        fila = self.ejecutar(
            "LP",
            EVALUACION + timedelta(days=3),
            [crear_item("50112000", "Carne de vacuno")],
        )
        self.assertEqual(fila["estado"], "posible_tienda")
        self.assertTrue(
            any("dias" in texto.lower()
                for texto in fila["observaciones"])
        )

    def test_le_no_relevante_bajo_20m(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=10),
            [crear_item("43211500", "Notebook")],
        )
        self.assertEqual(fila["estado"], "excluida")

    def test_l1_no_relevante(self):
        fila = self.ejecutar(
            "L1",
            EVALUACION + timedelta(days=10),
            [crear_item("43211500", "Notebook")],
        )
        self.assertEqual(fila["estado"], "excluida")

    def test_plazo_corto_no_excluye(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=3),
            [crear_item("43211500", "Notebook")],
            monto=30000000,
        )
        self.assertEqual(fila["estado"], "incluida")
        self.assertTrue(fila["observaciones"])


    def test_monto_exactamente_20m_incluido(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=10),
            [crear_item("53103000", "Poleras")],
            monto=20000000,
        )
        self.assertEqual(fila["estado"], "incluida")

    def test_monto_un_peso_bajo_20m_tienda(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=10),
            [crear_item("53103000", "Poleras")],
            monto=19999999,
        )
        self.assertEqual(fila["estado"], "posible_tienda")

    def test_monto_sobre_20m_incluido(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=10),
            [crear_item("50112000", "Carne de vacuno")],
            monto=20000001,
        )
        self.assertEqual(fila["estado"], "incluida")

    def test_plazo_corto_relevante_sigue_incluido(self):
        fila = self.ejecutar(
            "LE",
            EVALUACION + timedelta(days=3),
            [crear_item("53103000", "Poleras")],
            monto=25000000,
        )
        self.assertEqual(fila["estado"], "incluida")
        self.assertTrue(fila["observaciones"])
        self.assertTrue(
            any("dias" in texto.lower()
                for texto in fila["observaciones"])
        )


if __name__ == "__main__":
    import unittest
    unittest.main()
