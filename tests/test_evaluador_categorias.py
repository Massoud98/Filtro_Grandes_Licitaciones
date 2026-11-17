import unittest

from aplicacion.servicios.evaluador_categorias import (
    EXCLUDED_PREFIXES,
    evaluate_category_filter,
)


class CategoryEvaluatorTests(unittest.TestCase):

    def setUp(self):
        self.data = {
            "official": {"10000001", "20000001", "30000001"},
            "total_excluded": {"10000001"},
            "passive_excluded": {"20000001"},
            "prefixes": EXCLUDED_PREFIXES,
        }

    def tender(self, *codes, tipo="LE"):
        return {
            "Tipo": tipo,
            "Items": {
                "Listado": [
                    {"CodigoCategoria": code}
                    for code in codes
                ]
            },
        }

    def test_explicit_total_exclusion(self):
        result = evaluate_category_filter(
            self.tender("10000001"), self.data
        )
        self.assertEqual(result["decision"], "EXCLUDED_SERVICES")
        self.assertEqual(result["total_excluded_items"], 1)

    def test_total_exclusion_wins_over_permitted_item(self):
        result = evaluate_category_filter(
            self.tender("10000001", "30000001"), self.data
        )
        self.assertEqual(result["decision"], "EXCLUDED_SERVICES")
        self.assertEqual(result["permitted_items"], 1)

    def test_new_hard_prefix_excludes_unknown_official_code(self):
        result = evaluate_category_filter(
            self.tender("70000099", "30000001"), self.data
        )
        self.assertEqual(result["decision"], "EXCLUDED_SERVICES")
        self.assertEqual(result["new_excluded_prefix_items"], 1)
        self.assertEqual(result["unknown_items"], 0)

    def test_all_nineteen_prefixes_are_configured(self):
        self.assertEqual(len(EXCLUDED_PREFIXES), 19)

    def test_passive_exclusion_requires_manual_review(self):
        result = evaluate_category_filter(
            self.tender("20000001"), self.data
        )
        self.assertEqual(result["decision"], "PASSIVE_REVIEW")
        self.assertTrue(result["requires_manual_review"])
        self.assertTrue(result["continue_filtering"])

    def test_passive_and_permitted_requires_review(self):
        result = evaluate_category_filter(
            self.tender("20000001", "30000001"), self.data
        )
        self.assertEqual(result["decision"], "PASSIVE_REVIEW")
        self.assertEqual(result["permitted_items"], 1)

    def test_unknown_code_requires_investigation(self):
        result = evaluate_category_filter(
            self.tender("99999999"), self.data
        )
        self.assertEqual(result["decision"], "INVESTIGATE")
        self.assertTrue(result["requires_manual_review"])
        self.assertEqual(result["unknown_codes"], ["99999999"])

    def test_permitted_code_continues(self):
        result = evaluate_category_filter(
            self.tender("30000001"), self.data
        )
        self.assertEqual(result["decision"], "CONTINUE")
        self.assertTrue(result["continue_filtering"])

    def test_o1_remains_excluded(self):
        result = evaluate_category_filter(
            self.tender("30000001", tipo="O1"), self.data
        )
        self.assertEqual(result["decision"], "EXCLUDED_O1")

    def test_missing_items_requires_investigation(self):
        result = evaluate_category_filter(
            {"Tipo": "LE"}, self.data
        )
        self.assertEqual(result["decision"], "INVESTIGATE")
        self.assertTrue(result["requires_manual_review"])

    def test_malformed_category_requires_investigation(self):
        result = evaluate_category_filter(
            self.tender("7000"), self.data
        )
        self.assertEqual(result["decision"], "INVESTIGATE")
        self.assertEqual(result["unknown_items"], 1)


if __name__ == "__main__":
    unittest.main()