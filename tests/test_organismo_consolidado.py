"""Regression test for Organismo in the filtered workbook."""

import unittest
from contextlib import closing

from openpyxl import load_workbook

from tests.test_generador_excel_filtrado import PruebasExcelFiltrado


class PruebasOrganismo(unittest.TestCase):
    def test_organismo_en_excel_filtrado(self):
        # Reuse the existing fixture without inheriting its test methods.
        fixture = PruebasExcelFiltrado(methodName="test_cinco_hojas")
        fixture.setUp()

        try:
            codigo = fixture.ids[0]
            fixture.detalles[codigo]["Comprador"] = {
                "NombreOrganismo": "Ministerio de prueba"
            }
            fixture.guardar_datos()

            ruta = fixture.generar()

            with closing(load_workbook(ruta)) as libro:
                hoja = libro["Incluidas"]
                encabezados = [celda.value for celda in hoja[1]]

                self.assertEqual(len(encabezados), 17)
                self.assertEqual(encabezados[5], "Organismo")

                filas = {
                    str(fila[0].value): fila
                    for fila in hoja.iter_rows(min_row=2)
                }

                self.assertIn(codigo, filas)
                self.assertEqual(
                    filas[codigo][5].value,
                    "Ministerio de prueba",
                )

                self.assertEqual(len(libro.sheetnames), 5)

        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()