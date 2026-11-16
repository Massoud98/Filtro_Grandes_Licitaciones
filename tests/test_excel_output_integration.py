import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from aplicacion.servicios import generador_excel
from aplicacion.servicios import generador_excel_filtrado
from aplicacion.servicios.filtros_preliminares import aplicar_filtros


FECHA = "2026-11-16"


class ExcelOutputIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="excel_output_integration_"
        )
        self.addCleanup(self.temp.cleanup)

        self.base = Path(self.temp.name)
        self.originales = self.base / "datos" / "json" / "diarios"
        self.source = self.originales / FECHA
        self.source.mkdir(parents=True)

        self.ids = [
            "TEST-1",
            "TEST-2",
            "TEST-3",
            "TEST-4",
        ]

        details = {
            code: {
                "CodigoExterno": code,
                "Tipo": "LE",
                "Nombre": "Licitacion " + code,
                "MontoEstimado": 150000,
                "Comprador": {
                    "NombreOrganismo": "Organismo de prueba",
                },
                "Fechas": {
                    "FechaPublicacion": "2026-11-16T10:00:00",
                    "FechaCierre": "2026-11-25T15:00:00",
                },
            }
            for code in self.ids
        }

        (self.source / "licitaciones_publicadas.json").write_text(
            json.dumps({
                "fecha": FECHA,
                "licitaciones": [
                    {"CodigoExterno": code}
                    for code in self.ids
                ],
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        (self.source / "detalles_licitaciones.json").write_text(
            json.dumps({
                "fecha": FECHA,
                "ids": self.ids,
                "detalles": details,
                "errores": {},
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        aplicar_filtros(
            FECHA,
            carpeta_datos=self.source,
        )

        self.patcher_original = patch.object(
            generador_excel,
            "CARPETA_ORIGINALES",
            self.originales,
        )
        self.patcher_filtered = patch.object(
            generador_excel_filtrado,
            "CARPETA_ORIGINALES",
            self.originales,
        )

        self.patcher_original.start()
        self.addCleanup(self.patcher_original.stop)

        self.patcher_filtered.start()
        self.addCleanup(self.patcher_filtered.stop)

    def assert_valid_workbook(self, path):
        self.assertTrue(path.is_file())

        with closing(load_workbook(
            path,
            read_only=True,
            data_only=True,
        )) as book:
            self.assertGreaterEqual(len(book.sheetnames), 1)

    def test_default_output_directory(self):
        original = generador_excel.generar_excel_original(FECHA)
        filtered = (
            generador_excel_filtrado.generar_excel_filtrado(FECHA)
        )

        expected = self.base / "datos"

        self.assertEqual(Path(original), expected / "originales" / (
            f"Licitaciones_Mercado_Publico_{FECHA}.xlsx"
        ))
        self.assertEqual(Path(filtered), expected / "filtrados" / (
            f"Licitaciones_Filtradas_{FECHA}.xlsx"
        ))

        self.assert_valid_workbook(Path(original))
        self.assert_valid_workbook(Path(filtered))

        self.assertEqual(
            len(list((expected / "originales").glob("*.xlsx"))),
            1,
        )
        self.assertEqual(
            len(list((expected / "filtrados").glob("*.xlsx"))),
            1,
        )
        self.assertFalse(
            list(self.originales.rglob("*.xlsx"))
        )

    def test_explicit_output_directory(self):
        custom = self.base / "custom_reports"

        original = generador_excel.generar_excel_original(
            FECHA,
            carpeta_salida=custom,
        )
        filtered = (
            generador_excel_filtrado.generar_excel_filtrado(
                FECHA,
                carpeta_salida=custom,
            )
        )

        self.assertEqual(Path(original).parent, custom)
        self.assertEqual(Path(filtered).parent, custom)

        self.assert_valid_workbook(Path(original))
        self.assert_valid_workbook(Path(filtered))

        self.assertFalse(
            list(self.originales.rglob("*.xlsx"))
        )


if __name__ == "__main__":
    unittest.main()
