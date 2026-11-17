import json
import tempfile
import unittest
from pathlib import Path

from aplicacion.servicios.configuracion_categorias import (
    EXCLUDED_PREFIXES,
    category_directory,
    load_editable_categories,
)


class CategoryConfigurationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

        records = [
            {"categoryCode": f"{i:08d}"}
            for i in range(1, 2032)
        ]

        (self.directory / "catalogo_oficial_completo.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )
        (self.directory / "categorias_exclusion_total.txt").write_text(
            "00000001\n", encoding="utf-8"
        )
        (self.directory / "categorias_exclusion_pasiva.txt").write_text(
            "", encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_load_valid_configuration(self):
        data = load_editable_categories(self.directory)
        self.assertEqual(len(data["official"]), 2031)
        self.assertEqual(len(data["total_excluded"]), 1)
        self.assertEqual(len(data["passive_excluded"]), 0)

    def test_all_nineteen_prefixes(self):
        self.assertEqual(len(EXCLUDED_PREFIXES), 19)

    def test_empty_passive_file_allowed(self):
        self.assertFalse(
            load_editable_categories(self.directory)["passive_excluded"]
        )

    def test_missing_total_file_rejected(self):
        (self.directory / "categorias_exclusion_total.txt").unlink()
        with self.assertRaises(ValueError):
            load_editable_categories(self.directory)

    def test_duplicate_total_code_rejected(self):
        (self.directory / "categorias_exclusion_total.txt").write_text(
            "00000001\n00000001\n", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            load_editable_categories(self.directory)

    def test_overlap_rejected(self):
        (self.directory / "categorias_exclusion_pasiva.txt").write_text(
            "00000001\n", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            load_editable_categories(self.directory)

    def test_unknown_code_rejected(self):
        (self.directory / "categorias_exclusion_total.txt").write_text(
            "99999999\n", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            load_editable_categories(self.directory)

    def test_frozen_path(self):
        result = category_directory(
            executable=self.directory / "Iniciar_Filtro.exe",
            frozen=True,
        )
        self.assertEqual(result, self.directory / "Filtro")

    def test_development_path(self):
        source = self.directory / "aplicacion" / "servicios" / "module.py"
        result = category_directory(source=source, frozen=False)
        self.assertEqual(result, self.directory / "Filtro")


if __name__ == "__main__":
    unittest.main()