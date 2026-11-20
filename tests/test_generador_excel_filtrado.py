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
                    "posible_tienda":
                        self.estados.count("posible_tienda"),
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

    def test_cinco_hojas(self):
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro.sheetnames,
                [
                    "Resumen",
                    "Incluidas",
                    "Posible para Tienda",
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
            self.assertEqual(hoja.max_column, 19)
            self.assertEqual(hoja.cell(1, 18).value, "Categorias")
            self.assertEqual(hoja.cell(1, 19).value, "Productos")

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


    def test_datos_monetarios_en_excel(self):
        codigo = self.ids[0]
        self.detalles[codigo]["Moneda"] = "USD"

        self.resultados[0]["evaluacion_monto"] = {
            "monto_original": 150000,
            "moneda": "USD",
            "monto_clp": "145470000",
            "tasa_clp": "969.8",
            "fecha_tasa": "2026-11-10",
            "estado_monto": "cumple_minimo",
            "excluir": False,
            "revision_manual": False,
        }

        self.guardar_datos()
        ruta = self.generar()

        with closing(load_workbook(ruta)) as libro:
            hoja = libro["Incluidas"]
            fila = 2

            self.assertEqual(hoja.cell(fila, 7).value, 150000)
            self.assertEqual(hoja.cell(fila, 8).value, "USD")
            self.assertEqual(hoja.cell(fila, 9).value, 145470000)
            self.assertEqual(
                hoja.cell(fila, 10).value,
                "Cumple minimo",
            )
            self.assertAlmostEqual(
                hoja.cell(fila, 11).value,
                969.8,
            )
            self.assertEqual(
                hoja.cell(fila, 12).value,
                "2026-11-10",
            )

    def test_compatibilidad_informes_antiguos(self):
        ruta = self.generar()

        with closing(load_workbook(ruta)) as libro:
            hoja = libro["Incluidas"]

            self.assertIsNone(hoja.cell(2, 8).value)
            self.assertIsNone(hoja.cell(2, 9).value)
            self.assertEqual(
                hoja.cell(2, 10).value,
                "No evaluado",
            )
            self.assertIsNone(hoja.cell(2, 11).value)
            self.assertIsNone(hoja.cell(2, 12).value)

    def test_conversion_no_disponible_en_excel(self):
        codigo = self.ids[0]
        self.detalles[codigo]["Moneda"] = "USD"

        self.resultados[0]["evaluacion_monto"] = {
            "monto_original": 150000,
            "moneda": "USD",
            "monto_clp": None,
            "tasa_clp": None,
            "fecha_tasa": None,
            "estado_monto": "conversion_no_disponible",
            "excluir": False,
            "revision_manual": True,
        }

        self.guardar_datos()
        ruta = self.generar()

        with closing(load_workbook(ruta)) as libro:
            hoja = libro["Incluidas"]

            self.assertEqual(hoja.cell(2, 8).value, "USD")
            self.assertIsNone(hoja.cell(2, 9).value)
            self.assertEqual(
                hoja.cell(2, 10).value,
                "Conversion no disponible",
            )
            self.assertIsNone(hoja.cell(2, 11).value)
            self.assertIsNone(hoja.cell(2, 12).value)


    def test_filtro_2_preservado_en_regeneracion(self):
        """A rerun must preserve previously saved Filter 2 decisions."""
        from contextlib import closing
        from openpyxl import load_workbook

        evaluations_path = self.carpeta / "evaluaciones_filtro_2.json"

        # First execution: Filter 1 has not yet received Filter 2 results.
        initial = modulo.generar_excel_filtrado(
            FECHA,
            carpeta_salida=self.raiz / "salida",
            carpeta_datos=self.carpeta,
        )

        with closing(load_workbook(initial)) as book:
            self.assertEqual(book["Incluidas"].max_row - 1, 2)
            self.assertEqual(book["Revision manual"].max_row - 1, 1)

        evaluation = {
            "schema_version": 1,
            "evaluations": {
                "TEST-1": {
                    "tender_id": "TEST-1",
                    "decision": "REVISION_MANUAL",
                    "reasons": ["Contradiccion documental"],
                    "evidence": [],
                    "evidence_fingerprint": "synthetic-fingerprint",
                    "rule_version": "filtro2-jessika-v2",
                }
            },
        }

        evaluations_path.write_text(
            json.dumps(evaluation),
            encoding="utf-8",
        )
        original_evaluations = evaluations_path.read_bytes()

        def verify_workbook(path):
            with closing(load_workbook(path)) as book:
                included = [
                    book["Incluidas"].cell(row, 1).value
                    for row in range(2, book["Incluidas"].max_row + 1)
                ]
                manual = [
                    book["Revision manual"].cell(row, 1).value
                    for row in range(2, book["Revision manual"].max_row + 1)
                ]

                self.assertNotIn("TEST-1", included)
                self.assertIn("TEST-1", manual)
                self.assertIn("TEST-2", included)

        # First execution: final Excel after Filter 2.
        completed = modulo.generar_excel_filtrado(
            FECHA,
            carpeta_salida=self.raiz / "salida",
            carpeta_datos=self.carpeta,
            evaluaciones_filtro_2=evaluations_path,
        )
        verify_workbook(completed)

        # Second execution: preliminary Excel generation must apply
        # existing Filter 2 evaluations immediately.
        rerun = modulo.generar_excel_filtrado(
            FECHA,
            carpeta_salida=self.raiz / "salida",
            carpeta_datos=self.carpeta,
            evaluaciones_filtro_2=evaluations_path,
        )
        verify_workbook(rerun)

        # A subsequent HTTP 403 cannot erase the saved evaluation
        # if the downloader stops before the next Excel generation.
        self.assertEqual(
            evaluations_path.read_bytes(),
            original_evaluations,
        )


class PruebasExcelTienda(unittest.TestCase):
    """Verifica la nueva hoja Tienda y los avisos de plazo."""

    setUp = PruebasExcelFiltrado.setUp
    guardar_datos = PruebasExcelFiltrado.guardar_datos
    generar = PruebasExcelFiltrado.generar

    def preparar_tienda(self, cierre="2026-11-25T15:00:00-03:00"):
        self.estados[0] = "posible_tienda"
        self.resultados[0]["estado"] = "posible_tienda"
        self.resultados[0]["fecha_cierre"] = cierre
        self.resultados[0]["clasificacion_l1"] = {
            "clasificacion": "incluir",
            "categorias_detectadas": ["alimentos"],
        }
        self.resultados[0]["evaluacion_monto"] = {
            "estado_monto": "bajo_minimo",
            "monto_clp": 150000,
            "moneda": "CLP",
        }
        self.guardar_datos()

    def test_tienda_en_hoja_separada_con_enlace(self):
        self.preparar_tienda()
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            tienda = libro["Posible para Tienda"]
            self.assertEqual(tienda.max_row, 2)
            self.assertEqual(tienda["A2"].value, "TEST-1")
            self.assertEqual(tienda["M2"].value, "posible_tienda")
            self.assertIn(
                "idlicitacion=TEST-1",
                tienda["A2"].hyperlink.target,
            )
            self.assertEqual(libro["Incluidas"].max_row - 1, 1)

    def test_resumen_tienda_y_porcentaje(self):
        self.preparar_tienda()
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            resumen = {
                fila[0].value: fila[1].value
                for fila in libro["Resumen"].iter_rows()
            }
            self.assertEqual(resumen["Total licitaciones"], 4)
            self.assertEqual(resumen["Incluidas Final"], 1)
            self.assertEqual(resumen["Posible para Tienda"], 1)
            self.assertEqual(
                resumen["Porcentaje posible para Tienda"],
                0.25,
            )

    def test_plazo_normal(self):
        self.preparar_tienda("2026-11-25T15:00:00-03:00")
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro["Posible para Tienda"]["Q2"].value,
                "Plazo normal",
            )

    def test_limite_exactamente_siete_dias(self):
        self.preparar_tienda("2026-11-17T19:54:54-03:00")
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro["Posible para Tienda"]["Q2"].value,
                "Plazo normal",
            )

    def test_inicio_del_dia_limite(self):
        self.preparar_tienda("2026-11-17T00:00:00-03:00")
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro["Posible para Tienda"]["Q2"].value,
                "Plazo normal",
            )

    def test_plazo_corto(self):
        self.preparar_tienda("2026-11-13T15:00:00-03:00")
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro["Posible para Tienda"]["Q2"].value,
                "Plazo corto",
            )

    def test_cierre_vencido(self):
        self.preparar_tienda("2026-11-09T15:00:00-03:00")
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro["Posible para Tienda"]["Q2"].value,
                "Cierre vencido",
            )

    def test_sin_fecha(self):
        self.preparar_tienda(None)
        ruta = self.generar()
        with closing(load_workbook(ruta)) as libro:
            self.assertEqual(
                libro["Posible para Tienda"]["Q2"].value,
                "Sin fecha",
            )


if __name__ == "__main__":
    unittest.main()
