"""Regression tests for scheduled publication date selection."""

import unittest
from datetime import date, datetime

from aplicacion.servicios.fechas_ejecucion import (
    fechas_publicacion_para_ejecucion,
)


class PublicationDateSelectionTests(unittest.TestCase):

    def test_monday_covers_friday_saturday_sunday(self):
        self.assertEqual(
            fechas_publicacion_para_ejecucion(date(2026, 11, 16)),
            [
                date(2026, 11, 13),
                date(2026, 11, 14),
                date(2026, 11, 15),
            ],
        )

    def test_other_weekdays_cover_previous_day(self):
        cases = {
            date(2026, 11, 17): date(2026, 11, 16),
            date(2026, 11, 18): date(2026, 11, 17),
            date(2026, 11, 19): date(2026, 11, 18),
            date(2026, 11, 20): date(2026, 11, 19),
        }

        for run_date, expected in cases.items():
            with self.subTest(run_date=run_date):
                self.assertEqual(
                    fechas_publicacion_para_ejecucion(run_date),
                    [expected],
                )

    def test_weekends_have_no_scheduled_publications(self):
        for run_date in (
            date(2026, 11, 21),
            date(2026, 11, 22),
        ):
            with self.subTest(run_date=run_date):
                self.assertEqual(
                    fechas_publicacion_para_ejecucion(run_date),
                    [],
                )

    def test_monday_crosses_month_boundary(self):
        self.assertEqual(
            fechas_publicacion_para_ejecucion(date(2026, 6, 1)),
            [
                date(2026, 5, 29),
                date(2026, 5, 30),
                date(2026, 5, 31),
            ],
        )

    def test_monday_crosses_year_boundary(self):
        self.assertEqual(
            fechas_publicacion_para_ejecucion(date(2029, 1, 1)),
            [
                date(2028, 12, 29),
                date(2028, 12, 30),
                date(2028, 12, 31),
            ],
        )

    def test_invalid_inputs_rejected(self):
        for value in (
            "2026-11-16",
            None if False else 123,
            datetime(2026, 11, 16, 9, 0),
        ):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    fechas_publicacion_para_ejecucion(value)


if __name__ == "__main__":
    unittest.main()