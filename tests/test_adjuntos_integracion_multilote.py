"""Offline regression tests for production five-tender batch preparation."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from checkpoint_descargas import CheckpointError
from lotes_produccion import (
    BatchPlanningError,
    plan_batches,
    prepare_batch,
)


class ProductionMultiBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.checkpoints = self.root / "checkpoints"

        self.downloads.mkdir()
        self.extracted.mkdir()

        self.ids = [
            f"100-{number}-LE26"
            for number in range(1, 11)
        ]

        self.classification = self.root / "filtros_preliminares.json"

        payload = {
            "total": 11,
            "resumen": {
                "incluida": 10,
                "excluida": 1,
            },
            "resultados": [
                {"id": tender_id, "estado": "incluida"}
                for tender_id in self.ids
            ] + [
                {"id": "999-9-LE26", "estado": "excluida"}
            ],
        }

        self.classification.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        self.authorized = frozenset(self.ids)

    def prepare(self, number, ids=None):
        batches = plan_batches(self.classification)
        return prepare_batch(
            self.classification,
            self.checkpoints,
            self.downloads,
            self.extracted,
            number,
            batches[number - 1] if ids is None else ids,
            authorized_ids=self.authorized,
        )

    def test_exactly_two_batches_of_five(self):
        batches = plan_batches(self.classification)
        self.assertEqual(len(batches), 2)
        self.assertEqual([len(batch) for batch in batches], [5, 5])
        self.assertEqual(
            [item for batch in batches for item in batch],
            self.ids,
        )

    def test_two_batches_have_independent_checkpoints(self):
        first_path, first = self.prepare(1)
        second_path, second = self.prepare(2)

        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.is_file())
        self.assertTrue(second_path.is_file())
        self.assertEqual(first["ids"], self.ids[:5])
        self.assertEqual(second["ids"], self.ids[5:])

    def test_resume_existing_checkpoint(self):
        first_path, first = self.prepare(1)
        resumed_path, resumed = self.prepare(1)

        self.assertEqual(first_path, resumed_path)
        self.assertEqual(first, resumed)

    def test_other_batch_directory_is_authorized(self):
        (self.extracted / self.ids[5]).mkdir()

        self.prepare(1)
        self.prepare(2)

    def test_excluded_tender_directory_is_rejected(self):
        (self.extracted / "999-9-LE26").mkdir()

        with self.assertRaises(CheckpointError):
            self.prepare(1)

    def test_wrong_batch_membership_is_rejected(self):
        with self.assertRaises(BatchPlanningError):
            self.prepare(1, self.ids[5:])

    def test_incomplete_authorization_is_rejected(self):
        with self.assertRaises(BatchPlanningError):
            prepare_batch(
                self.classification,
                self.checkpoints,
                self.downloads,
                self.extracted,
                1,
                self.ids[:5],
                authorized_ids=set(self.ids[:5]),
            )


if __name__ == "__main__":
    unittest.main()