"""Isolated tests for the consolidated scheduled coordinator."""

import ast
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch


def isolated_coordinator():
    launcher = Path(__file__).resolve().parents[1] / "iniciar_filtro.py"
    tree = ast.parse(launcher.read_text(encoding="utf-8-sig"))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "run_scheduled_pipeline"
    ]
    if len(selected) != 1:
        raise RuntimeError("Scheduled coordinator unavailable.")
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, str(launcher), "exec")


class CoordinatorTests(unittest.TestCase):

    def run_coordinator(
        self, run_date, statuses=None,
        attachment_path=None, attachment_date=None,
    ):
        from aplicacion.servicios.fechas_ejecucion import (
            fechas_publicacion_para_ejecucion,
        )

        events = []
        statuses = statuses or {}

        with tempfile.TemporaryDirectory(prefix="coordinator_test_") as tmp:
            base = Path(tmp)
            originals = base / "datos" / "json" / "diarios"

            def fake_pipeline(fecha=None, *, generar_reportes=True):
                events.append(("pipeline", fecha, generar_reportes))
                status = statuses.get(fecha, "SUCCESS")
                return {"status": status, "date": fecha.isoformat()}

            def fake_consolidate(source, dates, target, report_date):
                events.append(("consolidate", tuple(dates), report_date))
                self.assertEqual(source, originals)
                self.assertEqual(
                    target,
                    base / "datos" / "json" / "consolidados" / report_date,
                )
                return {"status": "SUCCESS", "published": len(dates)}

            def fake_original(fecha, **kwargs):
                events.append(("original", fecha))
                self.assertEqual(kwargs["fecha_reporte"], run_date.isoformat())
                return kwargs["carpeta_salida"] / "original.xlsx"

            def fake_filter(fecha, **kwargs):
                events.append(("filter", fecha))
                return {"resumen": {}}

            def fake_filtered(fecha, **kwargs):
                events.append(("filtered", fecha))
                self.assertEqual(kwargs["fecha_reporte"], run_date.isoformat())
                return kwargs["carpeta_salida"] / "filtered.xlsx"

            def service(name, **members):
                module = types.ModuleType(name)
                for key, value in members.items():
                    setattr(module, key, value)
                return module

            class FakeDatetime:
                @staticmethod
                def now(tz=None):
                    class Today:
                        def date(self):
                            return run_date
                    return Today()

            real_datetime = sys.modules["datetime"]
            fake_datetime = service(
                "datetime",
                datetime=FakeDatetime,
            )

            modules = {
                "datetime": fake_datetime,
                "aplicacion.servicios.fechas_ejecucion": service(
                    "aplicacion.servicios.fechas_ejecucion",
                    fechas_publicacion_para_ejecucion=(
                        lambda *, hoy: fechas_publicacion_para_ejecucion(hoy)
                    ),
                ),
                "aplicacion.servicios.mercado_publico": service(
                    "aplicacion.servicios.mercado_publico",
                    CARPETA_ORIGINALES=originals,
                ),
                "aplicacion.servicios.consolidacion_licitaciones": service(
                    "aplicacion.servicios.consolidacion_licitaciones",
                    consolidar_publicaciones=fake_consolidate,
                ),
                "aplicacion.servicios.generador_excel": service(
                    "aplicacion.servicios.generador_excel",
                    generar_excel_original=fake_original,
                ),
                "aplicacion.servicios.generador_excel_filtrado": service(
                    "aplicacion.servicios.generador_excel_filtrado",
                    generar_excel_filtrado=fake_filtered,
                ),
                "aplicacion.servicios.filtros_preliminares": service(
                    "aplicacion.servicios.filtros_preliminares",
                    aplicar_filtros=fake_filter,
                ),
            }

            # Keep the real datetime module available to other imports.
            self.assertIsNotNone(real_datetime)

            namespace = {
                "__builtins__": __builtins__,
                "os": os,
                "run_pipeline": fake_pipeline,
                "ejecutar_procesamiento_adjuntos": lambda path: {"status": "SUCCESS"},
            }
            exec(isolated_coordinator(), namespace)

            environment = {
                "FILTRO_ATTACHMENT_REPORT_PATH": "",
                "FILTRO_ATTACHMENT_REPORT_DATE": "",
            }
            if attachment_path is not None:
                environment["FILTRO_ATTACHMENT_REPORT_PATH"] = attachment_path
            if attachment_date is not None:
                environment["FILTRO_ATTACHMENT_REPORT_DATE"] = attachment_date

            with (
                patch.dict(sys.modules, modules),
                patch.dict(os.environ, environment),
                redirect_stdout(StringIO()),
            ):
                if attachment_path is None:
                    os.environ.pop("FILTRO_ATTACHMENT_REPORT_PATH", None)
                if attachment_date is None:
                    os.environ.pop("FILTRO_ATTACHMENT_REPORT_DATE", None)

                try:
                    result = namespace["run_scheduled_pipeline"]()
                    return events, result, None
                except Exception as exc:
                    return events, None, exc

    def test_monday_one_consolidated_report_pair(self):
        friday = date(2026, 11, 13)
        saturday = date(2026, 11, 14)
        sunday = date(2026, 11, 15)
        events, result, error = self.run_coordinator(date(2026, 11, 16))

        self.assertIsNone(error)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["published"], 3)
        self.assertEqual(events, [
            ("pipeline", friday, False),
            ("pipeline", saturday, False),
            ("pipeline", sunday, False),
            ("consolidate", (friday, saturday, sunday), "2026-11-16"),
            ("original", "2026-11-16"),
            ("filter", "2026-11-16"),
            ("filtered", "2026-11-16"),
        ])

    def test_tuesday_to_friday_previous_day(self):
        for day in range(17, 21):
            run_date = date(2026, 11, day)
            previous = date.fromordinal(run_date.toordinal() - 1)

            with self.subTest(run_date=run_date):
                events, result, error = self.run_coordinator(run_date)
                self.assertIsNone(error)
                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(events, [
                    ("pipeline", previous, False),
                    ("consolidate", (previous,), run_date.isoformat()),
                    ("original", run_date.isoformat()),
                    ("filter", run_date.isoformat()),
                    ("filtered", run_date.isoformat()),
                ])

    def test_publication_date_selector_full_week(self):
        from aplicacion.servicios.fechas_ejecucion import (
            fechas_publicacion_para_ejecucion,
        )

        cases = [
            (date(2026, 11, 16), [
                date(2026, 11, 13),
                date(2026, 11, 14),
                date(2026, 11, 15),
            ]),
            (date(2026, 11, 17), [date(2026, 11, 16)]),
            (date(2026, 11, 18), [date(2026, 11, 17)]),
            (date(2026, 11, 19), [date(2026, 11, 18)]),
            (date(2026, 11, 20), [date(2026, 11, 19)]),
            (date(2026, 11, 21), []),
            (date(2026, 11, 22), []),
            (date(2026, 11, 23), [
                date(2026, 11, 20),
                date(2026, 11, 21),
                date(2026, 11, 22),
            ]),
        ]

        for run_date, expected in cases:
            with self.subTest(run_date=run_date):
                self.assertEqual(
                    fechas_publicacion_para_ejecucion(run_date),
                    expected,
                )

    def test_weekends_do_not_run(self):
        for run_date in (date(2026, 11, 21), date(2026, 11, 22)):
            with self.subTest(run_date=run_date):
                events, result, error = self.run_coordinator(run_date)
                self.assertIsNone(error)
                self.assertEqual(result["status"], "NO_RUN")
                self.assertEqual(events, [])

    def test_incomplete_details_stop_before_reports(self):
        friday = date(2026, 11, 13)
        events, result, error = self.run_coordinator(
            date(2026, 11, 16),
            statuses={friday: "DETAILS_INCOMPLETE"},
        )
        self.assertIsNone(error)
        self.assertEqual(result["status"], "DETAILS_INCOMPLETE")
        self.assertEqual(events, [("pipeline", friday, False)])

    def test_attachment_report_blocks_consolidation(self):
        events, result, error = self.run_coordinator(
            date(2026, 11, 16),
            attachment_path="report.json",
            attachment_date="2026-11-13",
        )
        self.assertEqual(events, [])
        self.assertIsNone(result)
        self.assertIsInstance(error, ValueError)

    def test_unexpected_status_stops_processing(self):
        friday = date(2026, 11, 13)
        events, result, error = self.run_coordinator(
            date(2026, 11, 16),
            statuses={friday: "UNEXPECTED"},
        )
        self.assertEqual(events, [("pipeline", friday, False)])
        self.assertIsNone(result)
        self.assertIsInstance(error, RuntimeError)

    def test_no_tenders_continues_to_next_date(self):
        friday = date(2026, 11, 13)
        events, result, error = self.run_coordinator(
            date(2026, 11, 16),
            statuses={friday: "NO_TENDERS"},
        )
        self.assertIsNone(error)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(
            [event[1] for event in events if event[0] == "pipeline"],
            [date(2026, 11, d) for d in (13, 14, 15)],
        )
        self.assertEqual(
            [event[0] for event in events].count("consolidate"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
