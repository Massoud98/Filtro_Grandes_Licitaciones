"""Permanent regression tests for date-bound attachment reports."""

import copy
import unittest

from aplicacion.servicios.politica_adjuntos_diarios import (
    validate_daily_attachment_report,
)
from aplicacion.servicios.reporte_adjuntos import (
    AttachmentReportError,
)


DATE = "2026-11-11"


def sample_report():
    """Return a structurally valid synthetic attachment report."""
    document = {
        "licitacion": "TEST-1-LE26",
        "filename": "document.pdf",
        "sha256": "a" * 64,
        "source_bytes": 100,
        "status": "extracted",
        "searchable_text": "Synthetic procurement document.",
        "segments": [
            {
                "index": 0,
                "locator": "page 1",
                "method": "pdf_text",
                "text": "Synthetic procurement document.",
            }
        ],
        "requires_extraction_review": False,
        "requires_document_review": False,
        "pages_requiring_ocr": [],
        "ocr_pages": 0,
    }

    return {
        "schema_version": 1,
        "documents": [document],
        "tenders": {
            "TEST-1-LE26": {
                "status": "extracted",
                "counts": {
                    "total": 1,
                    "extracted": 1,
                    "empty": 0,
                    "errors": 0,
                    "ocr_pages": 0,
                },
                "requires_human_review": False,
                "requirements_interpreted": False,
            }
        },
    }


class DateBoundPolicyTests(unittest.TestCase):

    def setUp(self):
        self.report = sample_report()
        self.ids = ["TEST-1-LE26"]

    def validate(
        self,
        report=None,
        report_date=DATE,
        publication_date=DATE,
        daily_ids=None,
    ):
        return validate_daily_attachment_report(
            self.report if report is None else report,
            report_date=report_date,
            publication_date=publication_date,
            daily_tender_ids=self.ids if daily_ids is None else daily_ids,
        )

    def test_valid_exact_match(self):
        self.assertIs(self.validate(), self.report)

    def test_valid_partial_coverage(self):
        self.assertIs(
            self.validate(daily_ids=self.ids + ["TEST-2-LE26"]),
            self.report,
        )

    def test_unrelated_tender_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(daily_ids=["OTHER-1-LE26"])

    def test_mismatched_date_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(report_date="2026-11-10")

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(report_date="not-a-date")

    def test_noncanonical_date_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(report_date="2026-1-11")

    def test_duplicate_daily_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(daily_ids=self.ids + self.ids)

    def test_invalid_daily_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(daily_ids=self.ids + [""])

    def test_nonlist_daily_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(daily_ids=tuple(self.ids))

    def test_malformed_report_rejected(self):
        invalid = copy.deepcopy(self.report)
        invalid["tenders"]["TEST-1-LE26"]["counts"]["total"] = 999
        with self.assertRaises(AttachmentReportError):
            self.validate(report=invalid)

    def test_inputs_unchanged(self):
        original = copy.deepcopy(self.report)
        daily_ids = self.ids + ["TEST-2-LE26"]
        original_ids = daily_ids.copy()

        self.validate(daily_ids=daily_ids)

        self.assertEqual(self.report, original)
        self.assertEqual(daily_ids, original_ids)


if __name__ == "__main__":
    unittest.main()
