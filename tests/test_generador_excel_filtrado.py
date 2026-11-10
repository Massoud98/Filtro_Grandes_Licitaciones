"""Pruebas aisladas del generador Excel filtrado."""

import hashlib
from contextlib import closing
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from aplicacion.servicios import generador_excel_filtrado as modulo


FECHA = "2026-11-09"


def guardar_json(ruta, contenido):
    ruta.write_text(
        json.dumps(contenido, ensure_ascii=True),
        encoding="utf-8",
    )


class PruebasExcelFiltrado(unittest.TestCase):

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)

        self.raiz = Path(self.temporal.name)
        self.carpeta = self.raiz / FECHA
        self.carpeta.mkdir()

        parche = patch.object(
            modulo,
            "CARPETA_ORIGINALES",
            self.raiz,
        )
        parche.start()
        self.addCleanup(parche.stop)

        self.ids = [
            "TEST-1",
            "TEST-2",
            "TEST-3",
            "TEST-4",
        ]

        self.estados = [
            "incluida",
            "incluida",
            "revision_manual",
            "excluida",
        ]

        self.detalles = {
            codigo: {
                "Tipo": "LE",
                "Nombre": "Licitacion " + codigo,
                "MontoEstimado": 150000,
                "Fechas": {
                    "FechaPublicacion":
                        "2026-11-09T10:00:00",
                    "FechaCierre":
                        "2026-11-25T15:00:00",
                },
            }
            for codigo in self.ids
        }

        self.resultados = [
            {
                "id": codigo,
                "tipo": "LE",
                "nombre": "Licitacion " + codigo,
                "estado": estado,
                "razones": (
                    ["No cumple los filtros."]
                    if estado == "excluida"
                    else []
                ),
                "observaciones": (
                    ["Requiere revision."]
                    if estado == "revision_manual"
                    else []
                ),
                "clasificacion_l1": None,
            }
            for codigo, estado in zip(
                self.ids, self.estados
            )
        ]

        self.guardar_datos()

    def guardar_datos(self):
        guardar_json(
            self.carpeta / "detalles_licitaciones.json",
            {
                "fecha": FECHA,
                "ids": self.ids,
                "detalles": self.detalles,
            },
        )

        guardar_json(
            self.carpeta / "filtros_preliminares.json",
            {
                "fecha_publicacion": FECHA,
                "evaluado_en":
                    "2026-11-10T19:54:54-03:00",
                "cierre_minimo":
                    "2026-11-17T19:54:54-03:00",
                "total": len(self.ids),
                "resumen": {
                    "incluida":
                        self.estados.count("incluida"),
                    "revision_manual":
                        self.estados.count("revision_manual"),
                    "excluida":
                        self.estados.count("excluida"),
                },
                "resultados": self.resultados,
            },
        )

    def generar(self):
        ruta = modulo.generar_excel_filtrado(FECHA)
        self.assertTrue(ruta.is_file())
        return ruta

    def test_cuatro_hojas(self):
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro.sheetnames,
                [
                    "Resumen",
                    "Incluidas",
                    "Revision manual",
                    "Excluidas",
                ],
            )

    def test_conteos(self):
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro["Incluidas"].max_row - 1, 2
            )
            self.assertEqual(
                libro["Revision manual"].max_row - 1,
                1,
            )
            self.assertEqual(
                libro["Excluidas"].max_row - 1, 1
            )
            self.assertEqual(
                libro["Resumen"]["B5"].value, 4
            )

    def test_enlaces(self):
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            for nombre in (
                "Incluidas",
                "Revision manual",
                "Excluidas",
            ):
                hoja = libro[nombre]
                for fila in range(2, hoja.max_row + 1):
                    celda = hoja.cell(fila, 1)
                    self.assertIsNotNone(
                        celda.hyperlink
                    )
                    self.assertIn(
                        "idlicitacion=" + celda.value,
                        celda.hyperlink.target,
                    )

    def test_hoja_manual_vacia(self):
        self.ids = ["TEST-1", "TEST-4"]
        self.estados = ["incluida", "excluida"]
        self.resultados = [
            fila for fila in self.resultados
            if fila["id"] in self.ids
        ]
        self.detalles = {
            codigo: self.detalles[codigo]
            for codigo in self.ids
        }
        self.guardar_datos()

        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            hoja = libro["Revision manual"]
            self.assertEqual(hoja.max_row, 1)
            self.assertEqual(hoja.max_column, 10)

    def test_excel_original_intacto(self):
        original = (
            self.carpeta /
            f"Licitaciones_Mercado_Publico_{FECHA}.xlsx"
        )
        contenido = b"ARCHIVO ORIGINAL DE PRUEBA"
        original.write_bytes(contenido)

        antes = hashlib.sha256(
            original.read_bytes()
        ).hexdigest()

        self.generar()

        despues = hashlib.sha256(
            original.read_bytes()
        ).hexdigest()

        self.assertEqual(antes, despues)

    def test_rechaza_ids_inconsistentes(self):
        self.resultados[0]["id"] = "ID-INEXISTENTE"
        self.guardar_datos()

        with self.assertRaises(ValueError):
            modulo.generar_excel_filtrado(FECHA)

        salida = (
            self.carpeta /
            f"Licitaciones_Filtradas_{FECHA}.xlsx"
        )
        self.assertFalse(salida.exists())


if __name__ == "__main__":
    unittest.main()
