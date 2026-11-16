import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReportDirectorySeparationTests(unittest.TestCase):

    def read_source(self, relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def function_body(self, relative, name):
        source = self.read_source(relative)
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == name
        )
        return ast.get_source_segment(source, function)

    def test_daily_json_directory(self):
        source = self.read_source(
            "aplicacion/servicios/mercado_publico.py"
        )
        self.assertIn(
            'CARPETA_ORIGINALES = RAIZ_PROYECTO / "datos" / "json" / "diarios"',
            source,
        )

    def test_original_generator_directory(self):
        source = self.read_source(
            "aplicacion/servicios/generador_excel.py"
        )
        self.assertIn(
            'CARPETA_ORIGINALES.parent.parent / "originales"',
            source,
        )
        self.assertIn("carpeta_salida is not None", source)

    def test_filtered_generator_directory(self):
        source = self.read_source(
            "aplicacion/servicios/generador_excel_filtrado.py"
        )
        self.assertIn(
            'CARPETA_ORIGINALES.parent.parent / "filtrados"',
            source,
        )
        self.assertIn("carpeta_salida is not None", source)

    def test_daily_pipeline_output_paths(self):
        body = self.function_body(
            "iniciar_filtro.py", "run_pipeline"
        )

        self.assertIn(
            "report_folder = CARPETA_ORIGINALES.parent.parent",
            body,
        )
        self.assertIn(
            'original = report_folder / "originales" /',
            body,
        )
        self.assertIn(
            'filtered = report_folder / "filtrados" /',
            body,
        )
        self.assertLess(
            body.index("if not generar_reportes:"),
            body.index("report_folder ="),
        )

    def test_consolidated_pipeline_paths(self):
        body = self.function_body(
            "iniciar_filtro.py", "run_scheduled_pipeline"
        )

        self.assertIn(
            "fecha_reporte = hoy.isoformat()",
            body,
        )
        self.assertIn(
            'base / "datos" / "json" / "consolidados" / fecha_reporte',
            body,
        )
        self.assertIn(
            'base / "datos" / "originales"',
            body,
        )
        self.assertIn(
            'carpeta_salida=base / "datos" / "filtrados"',
            body,
        )
        self.assertIn(
            "generar_reportes=False",
            body,
        )

    def test_existing_reports_folder_preserved(self):
        source = self.read_source("iniciar_filtro.py")
        self.assertIn(
            'ROOT / "datos" / "reportes"',
            source,
        )


if __name__ == "__main__":
    unittest.main()