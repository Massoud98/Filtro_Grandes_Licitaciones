"""Isolated launcher integration regression tests.

Never import iniciar_filtro here: its module initialization has
filesystem and working-directory side effects.
"""

import ast
import copy
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tests.test_politica_adjuntos_diarios import sample_report
from aplicacion.servicios.reporte_adjuntos import AttachmentReportError


RUN_DATE = "2026-11-11"
TENDER_ID = "TEST-1-LE26"


def isolated_launcher_functions():
    launcher = Path(__file__).resolve().parents[1] / "iniciar_filtro.py"
    tree = ast.parse(launcher.read_text(encoding="utf-8-sig"))

    wanted = {
        "load_optional_attachment_report",
        "run_pipeline",
    }

    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in wanted
    ]

    if {node.name for node in selected} != wanted:
        raise RuntimeError("Launcher functions unavailable.")

    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, str(launcher), "exec")


class FakeKeyring:
    pass


class Harness:
    def __init__(self, root, publication_ids=None):
        self.root = root
        self.ids = (
            [TENDER_ID]
            if publication_ids is None
            else publication_ids
        )
        self.events = []
        self.generated_kwargs = None
        self.folder = root / RUN_DATE

    def service(self, name, **functions):
        module = types.ModuleType(name)
        for key, value in functions.items():
            setattr(module, key, value)
        return module

    def setup(self, stack):
        def publication(**kwargs):
            self.events.append("publication")
            return {
                "fecha": RUN_DATE,
                "licitaciones": [
                    {"CodigoExterno": tender_id}
                    for tender_id in self.ids
                ],
            }

        def details(*args, **kwargs):
            self.events.append("details")
            self.folder.mkdir(parents=True, exist_ok=True)

            (self.folder / "detalles_licitaciones.json").write_text(
                json.dumps({
                    "fecha": RUN_DATE,
                    "ids": self.ids,
                    "detalles": {
                        tender_id: {}
                        for tender_id in self.ids
                    },
                    "errores": {},
                }),
                encoding="utf-8",
            )

            return {"status": "SUCCESS"}

        def original(*args, **kwargs):
            self.events.append("original_excel")
            return self.folder / "original.xlsx"

        def filters(*args, **kwargs):
            self.events.append("filters")
            return {
                "resumen": {
                    "incluida": 1,
                    "revision_manual": 0,
                    "excluida": 0,
                }
            }

        def filtered(*args, **kwargs):
            self.events.append("filtered_excel")
            self.generated_kwargs = kwargs
            return self.folder / "filtered.xlsx"

        base = "aplicacion.servicios"

        services = {
            f"{base}.mercado_publico": self.service(
                f"{base}.mercado_publico",
                CARPETA_ORIGINALES=self.root,
                consultar_licitaciones=publication,
                obtener_fecha_ayer=lambda: date.fromisoformat(RUN_DATE),
            ),
            f"{base}.detalles_licitaciones": self.service(
                f"{base}.detalles_licitaciones",
                obtener_detalles=details,
            ),
            f"{base}.generador_excel": self.service(
                f"{base}.generador_excel",
                generar_excel_original=original,
            ),
            f"{base}.filtros_preliminares": self.service(
                f"{base}.filtros_preliminares",
                aplicar_filtros=filters,
            ),
            f"{base}.generador_excel_filtrado": self.service(
                f"{base}.generador_excel_filtrado",
                generar_excel_filtrado=filtered,
            ),
        }

        for name, module in services.items():
            stack.enter_context(
                patch.dict(sys.modules, {name: module})
            )

        namespace = {
            "__builtins__": __builtins__,
            "os": os,
            "json": json,
            "Path": Path,
            "date": date,
            "DETAIL_INTERVAL_SECONDS": 0,
            "_keyring": lambda: FakeKeyring(),
            "credential": lambda *args: "TEST_TOKEN",
            "backup_existing": lambda path: self.events.append("backup"),
            "load_existing_publication": lambda *args: None,
            "ejecutar_procesamiento_adjuntos": lambda path: {"status": "SUCCESS"},
        }

        exec(isolated_launcher_functions(), namespace)
        self.namespace = namespace

    def run(self):
        with redirect_stdout(StringIO()):
            return self.namespace["run_pipeline"]()


class AttachmentLauncherIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        self.stack.enter_context(
            patch.dict(os.environ, {}, clear=False)
        )

        os.environ.pop("FILTRO_ATTACHMENT_REPORT_PATH", None)
        os.environ.pop("FILTRO_ATTACHMENT_REPORT_DATE", None)

        self.report = sample_report()
        self.report_path = self.root / "report.json"
        self.report_path.write_text(
            json.dumps(self.report),
            encoding="utf-8",
        )

    def configure(self, report_path=None, report_date=None):
        if report_path is None:
            os.environ.pop("FILTRO_ATTACHMENT_REPORT_PATH", None)
        else:
            os.environ["FILTRO_ATTACHMENT_REPORT_PATH"] = str(report_path)

        if report_date is None:
            os.environ.pop("FILTRO_ATTACHMENT_REPORT_DATE", None)
        else:
            os.environ["FILTRO_ATTACHMENT_REPORT_DATE"] = report_date

    def harness(self, publication_ids=None):
        harness = Harness(self.root, publication_ids)
        harness.setup(self.stack)
        return harness

    def test_default_workflow(self):
        self.configure()
        harness = self.harness()
        result = harness.run()
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(harness.generated_kwargs, {})

    def test_valid_report(self):
        self.configure(self.report_path, RUN_DATE)
        harness = self.harness()
        result = harness.run()
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(
            harness.generated_kwargs["attachment_report"],
            self.report,
        )

    def test_partial_coverage(self):
        self.configure(self.report_path, RUN_DATE)
        harness = self.harness(
            [TENDER_ID, "TEST-2-LE26"]
        )
        result = harness.run()
        self.assertEqual(result["status"], "SUCCESS")

    def test_mismatched_date_stops_early(self):
        self.configure(self.report_path, "2026-11-10")
        harness = self.harness()

        with self.assertRaises(ValueError):
            harness.run()

        self.assertNotIn("publication", harness.events)
        self.assertFalse(harness.folder.exists())

    def test_unrelated_tender_stops_before_details(self):
        self.configure(self.report_path, RUN_DATE)
        harness = self.harness(["OTHER-1-LE26"])

        with self.assertRaises(ValueError):
            harness.run()

        self.assertIn("publication", harness.events)
        self.assertNotIn("details", harness.events)
        self.assertFalse(harness.folder.exists())

    def test_missing_date_variable(self):
        self.configure(self.report_path, None)
        harness = self.harness()

        with self.assertRaises(ValueError):
            harness.run()

        self.assertEqual(harness.events, [])

    def test_missing_path_variable(self):
        self.configure(None, RUN_DATE)
        harness = self.harness()

        with self.assertRaises(ValueError):
            harness.run()

        self.assertEqual(harness.events, [])

    def test_missing_report_file(self):
        self.configure(self.root / "missing.json", RUN_DATE)
        harness = self.harness()

        with self.assertRaises(ValueError):
            harness.run()

        self.assertEqual(harness.events, [])

    def test_malformed_report(self):
        invalid = copy.deepcopy(self.report)
        invalid["tenders"][TENDER_ID]["counts"]["total"] = 999

        invalid_path = self.root / "invalid.json"
        invalid_path.write_text(
            json.dumps(invalid),
            encoding="utf-8",
        )

        self.configure(invalid_path, RUN_DATE)
        harness = self.harness()

        with self.assertRaises(AttachmentReportError):
            harness.run()

        self.assertEqual(harness.events, [])


if __name__ == "__main__":
    unittest.main()
