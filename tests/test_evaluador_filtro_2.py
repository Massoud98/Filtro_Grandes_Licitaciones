"""Offline tests for Jessika's Filter 2 decision engine."""

import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from evaluador_filtro_2 import (
    AwardGroup,
    TenderEvidence,
    evaluate_group,
    evaluate_tender,
)


def evaluate(modality, *groups):
    return evaluate_tender(
        TenderEvidence(
            tender_id="12345-67-LE26",
            modality=modality,
            groups=list(groups),
        )
    )


class TestFilter2Evaluator(unittest.TestCase):

    def test_total_under_20m_excluded(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 5, 11_460_000, "NONE"),
        )
        self.assertEqual(result["decision"], "EXCLUIDA")

    def test_total_exactly_20m_approved(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 9, 20_000_000, "NONE"),
        )
        self.assertEqual(result["decision"], "APROBADA")

    def test_total_above_nine_items_excluded(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 10, 50_000_000, "NONE"),
        )
        self.assertEqual(result["decision"], "EXCLUIDA")

    def test_total_nine_items_approved(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 9, 50_000_000, "NONE"),
        )
        self.assertEqual(result["decision"], "APROBADA")

    def test_partial_under_20m_approved(self):
        result = evaluate(
            "PARTIAL",
            AwardGroup("LINEA_1", 3, 8_267_228, "NONE"),
            AwardGroup("LINEA_2", 1, 608_209, "NONE"),
        )
        self.assertEqual(result["decision"], "APROBADA")
        self.assertEqual(len(result["groups"]), 2)

    def test_partial_many_items_approved(self):
        result = evaluate(
            "PARTIAL",
            AwardGroup("LINEA_1", 151, 5_000_000, "NONE"),
        )
        self.assertEqual(result["decision"], "APROBADA")

    def test_total_mandatory_service_excluded(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 2, 40_000_000, "MANDATORY"),
        )
        self.assertEqual(result["decision"], "EXCLUIDA")

    def test_partial_mandatory_service_group_excluded(self):
        result = evaluate(
            "PARTIAL",
            AwardGroup("BIENES", 3, 5_000_000, "NONE"),
            AwardGroup("SERVICIO", 1, 5_000_000, "MANDATORY"),
        )
        self.assertEqual(result["decision"], "APROBADA")
        self.assertEqual(
            result["groups"][1]["decision"],
            "EXCLUIDA",
        )

    def test_partial_only_mandatory_service_excluded(self):
        result = evaluate(
            "PARTIAL",
            AwardGroup("SERVICIO", 1, 50_000_000, "MANDATORY"),
        )
        self.assertEqual(result["decision"], "EXCLUIDA")

    def test_optional_independent_service_allowed(self):
        result = evaluate(
            "TOTAL",
            AwardGroup(
                "TOTAL", 3, 40_000_000, "OPTIONAL_INDEPENDENT"
            ),
        )
        self.assertEqual(result["decision"], "APROBADA")

    def test_unknown_service_requires_review(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 3, 40_000_000, "UNKNOWN"),
        )
        self.assertEqual(result["decision"], "REVISION_MANUAL")

    def test_unknown_modality_requires_review(self):
        result = evaluate(
            "UNKNOWN",
            AwardGroup("TOTAL", 3, 40_000_000, "NONE"),
        )
        self.assertEqual(result["decision"], "REVISION_MANUAL")

    def test_missing_item_count_requires_review(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", None, 40_000_000, "NONE"),
        )
        self.assertEqual(result["decision"], "REVISION_MANUAL")

    def test_missing_budget_requires_review(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 3, None, "NONE"),
        )
        self.assertEqual(result["decision"], "REVISION_MANUAL")

    def test_known_exclusion_overrides_missing_budget(self):
        result = evaluate(
            "TOTAL",
            AwardGroup("TOTAL", 12, None, "UNKNOWN"),
        )
        self.assertEqual(result["decision"], "EXCLUIDA")

    def test_uncertain_partial_group_without_approved_group(self):
        result = evaluate(
            "PARTIAL",
            AwardGroup("LINEA_1", 2, 10_000_000, "UNKNOWN"),
            AwardGroup("LINEA_2", 1, 10_000_000, "MANDATORY"),
        )
        self.assertEqual(result["decision"], "REVISION_MANUAL")

    def test_approved_partial_group_with_uncertain_group(self):
        result = evaluate(
            "PARTIAL",
            AwardGroup("LINEA_1", 2, 10_000_000, "NONE"),
            AwardGroup("LINEA_2", 2, 10_000_000, "UNKNOWN"),
        )
        self.assertEqual(result["decision"], "APROBADA")
        self.assertEqual(
            result["groups"][1]["decision"],
            "REVISION_MANUAL",
        )

    def test_no_groups_requires_review(self):
        result = evaluate("TOTAL")
        self.assertEqual(result["decision"], "REVISION_MANUAL")

    def test_total_multiple_groups_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(
                "TOTAL",
                AwardGroup("A", 1, 30_000_000, "NONE"),
                AwardGroup("B", 1, 30_000_000, "NONE"),
            )

    def test_duplicate_group_ids_rejected(self):
        with self.assertRaises(ValueError):
            evaluate(
                "PARTIAL",
                AwardGroup("A", 1, 30_000_000, "NONE"),
                AwardGroup("A", 1, 30_000_000, "NONE"),
            )

    def test_invalid_item_count_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_group(
                AwardGroup("A", -1, 30_000_000, "NONE"),
                partial=False,
            )

    def test_invalid_amount_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_group(
                AwardGroup("A", 1, -100, "NONE"),
                partial=False,
            )

    def test_invalid_obligation_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_group(
                AwardGroup("A", 1, 30_000_000, "INVALID"),
                partial=False,
            )


if __name__ == "__main__":
    unittest.main()