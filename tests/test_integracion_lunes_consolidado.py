import json
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from aplicacion.servicios.consolidacion_licitaciones import consolidar_publicaciones
from aplicacion.servicios.generador_excel import generar_excel_original
from aplicacion.servicios.generador_excel_filtrado import generar_excel_filtrado
from aplicacion.servicios.filtros_preliminares import aplicar_filtros
from tests.test_generador_excel_filtrado import PruebasExcelFiltrado


class MondayIntegrationTests(unittest.TestCase):

    def test_three_days_one_report_pair(self):
        fixture = PruebasExcelFiltrado(methodName="test_cinco_hojas")
        fixture.setUp()

        try:
            days = [date(2026, 11, d) for d in (13, 14, 15)]
            report_date = "2026-11-16"

            with tempfile.TemporaryDirectory(prefix="monday_integration_") as temp:
                base = Path(temp)
                originals = base / "datos" / "originales"
                reports = base / "datos" / "reportes"
                output = reports / report_date
                consolidated = reports / "consolidados" / report_date

                for index, day in enumerate(days):
                    code = fixture.ids[index]
                    day_string = day.isoformat()
                    folder = originals / day_string
                    folder.mkdir(parents=True)

                    detail = dict(fixture.detalles[code])
                    detail["CodigoExterno"] = code
                    detail["Comprador"] = {
                        "NombreOrganismo": f"Organismo {index + 1}"
                    }

                    (folder / "licitaciones_publicadas.json").write_text(
                        json.dumps({
                            "fecha": day_string,
                            "licitaciones": [{"CodigoExterno": code}],
                        }, ensure_ascii=False),
                        encoding="utf-8",
                    )

                    (folder / "detalles_licitaciones.json").write_text(
                        json.dumps({
                            "fecha": day_string,
                            "ids": [code],
                            "detalles": {code: detail},
                            "errores": {},
                        }, ensure_ascii=False),
                        encoding="utf-8",
                    )

                result = consolidar_publicaciones(
                    originals, days, consolidated, report_date
                )

                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(result["published"], 3)

                # Repeated consolidation must reuse identical checkpoints.
                repeated = consolidar_publicaciones(
                    originals, days, consolidated, report_date
                )
                self.assertEqual(repeated["published"], 3)

                original = generar_excel_original(
                    report_date,
                    carpeta_datos=consolidated,
                    carpeta_salida=output,
                    fecha_reporte=report_date,
                )

                aplicar_filtros(
                    report_date,
                    carpeta_datos=consolidated,
                )

                filtered = generar_excel_filtrado(
                    report_date,
                    carpeta_datos=consolidated,
                    carpeta_salida=output,
                    fecha_reporte=report_date,
                )

                expected = {
                    f"Licitaciones_Mercado_Publico_{report_date}.xlsx",
                    f"Licitaciones_Filtradas_{report_date}.xlsx",
                }

                self.assertEqual(
                    {p.name for p in output.glob("*.xlsx")},
                    expected,
                )

                organisations = {
                    "Organismo 1", "Organismo 2", "Organismo 3"
                }

                with closing(load_workbook(original, read_only=True)) as book:
                    sheet = book.active
                    headers = [cell.value for cell in sheet[1]]
                    self.assertEqual(headers[4], "Organismo")
                    self.assertEqual(sheet.max_row, 4)
                    self.assertEqual(
                        {sheet.cell(row, 5).value for row in range(2, 5)},
                        organisations,
                    )

                with closing(load_workbook(filtered, read_only=True)) as book:
                    seen = set()

                    for name in book.sheetnames:
                        if name == "Resumen":
                            continue

                        sheet = book[name]
                        headers = [cell.value for cell in sheet[1]]
                        self.assertEqual(headers[5], "Organismo")

                        for row in sheet.iter_rows(min_row=2, values_only=True):
                            if row[0]:
                                seen.add(row[5])

                    self.assertEqual(seen, organisations)

                self.assertFalse((originals / report_date).exists())
                self.assertEqual(
                    sorted(p.name for p in originals.iterdir()),
                    [day.isoformat() for day in days],
                )

                print("PASS: Friday, Saturday and Sunday consolidated.")
                print("PASS: Consolidation safely reusable.")
                print("PASS: Exactly two Monday-dated Excel files.")
                print("PASS: All three Organismo values in both reports.")
                print("PASS: Original publication checkpoints preserved.")
                print("PASS: No synthetic Monday checkpoint.")

        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()