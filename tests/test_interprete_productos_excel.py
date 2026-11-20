
import tempfile
import unittest
from pathlib import Path

from integracion_adjuntos.codigo.interprete_filtro_2 import (
    count_spreadsheet_products,
)


class SpreadsheetProductCounterTests(unittest.TestCase):

    def count(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contenido.txt"
            path.write_text(text, encoding="utf-8")

            result = count_spreadsheet_products([{
                "filename": "anexo.xlsx",
                "text_path": str(path),
            }])

            return {
                sheet["sheet"]: sheet["count"]
                for sheet in result["sheets"]
            }

    def test_quantities_are_not_product_counts(self):
        result = self.count(
            "LINEA 1!B19: Cant.\n"
            "LINEA 1!D19: Requerimientos\n"
            "LINEA 1!B20: 10\n"
            "LINEA 1!D20: Grabador NVR de 16 canales\n"
            "LINEA 1!B21: 50\n"
            "LINEA 1!D21: Camara IP tipo domo\n"
            "LINEA 1!B22: 50\n"
            "LINEA 1!D22: Camara IP tipo bullet\n"
        )

        self.assertEqual(result["LINEA 1"], 3)

    def test_independent_worksheets(self):
        result = self.count(
            "LINEA 1!B20: 10\n"
            "LINEA 1!D20: Grabador NVR de 16 canales\n"
            "LINEA 2!B20: 10\n"
            "LINEA 2!D20: Gabinete mural de seis unidades\n"
        )

        self.assertEqual(result["LINEA 1"], 1)
        self.assertEqual(result["LINEA 2"], 1)

    def test_numbered_office_products(self):
        result = self.count(
            "OFERTA ECONOMICA!A12: 1\n"
            "OFERTA ECONOMICA!B12: Archivador oficio\n"
            "OFERTA ECONOMICA!D12: 50\n"
            "OFERTA ECONOMICA!A13: 2\n"
            "OFERTA ECONOMICA!B13: Carpeta plastica\n"
            "OFERTA ECONOMICA!D13: 100\n"
        )

        self.assertEqual(result["OFERTA ECONOMICA"], 2)

    def test_headers_and_totals_not_counted(self):
        result = self.count(
            "LINEA 1!B19: Cantidad\n"
            "LINEA 1!D19: Requerimientos\n"
            "LINEA 1!B20: 5\n"
            "LINEA 1!D20: Camara de seguridad\n"
            "LINEA 1!B21: Total oferta de licitacion\n"
            "LINEA 1!J21: 1000000\n"
            "LINEA 1!B22: IVA\n"
            "LINEA 1!J22: 190000\n"
        )

        self.assertEqual(result["LINEA 1"], 1)

    def test_no_spreadsheet(self):
        result = count_spreadsheet_products([])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["sheets"], [])


if __name__ == "__main__":
    unittest.main()
