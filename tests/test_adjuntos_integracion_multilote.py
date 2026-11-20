"""Offline regression tests for three-tender batches and legacy checkpoints."""

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
        batches = plan_batches(self.classification, checkpoints_root=self.checkpoints)
        return prepare_batch(
            self.classification,
            self.checkpoints,
            self.downloads,
            self.extracted,
            number,
            batches[number - 1] if ids is None else ids,
            authorized_ids=self.authorized,
        )

    def test_four_batches_of_three_or_fewer(self):
        batches = plan_batches(self.classification)
        self.assertEqual(len(batches), 4)
        self.assertEqual([len(batch) for batch in batches], [3, 3, 3, 1])
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
        self.assertEqual(first["ids"], self.ids[:3])
        self.assertEqual(second["ids"], self.ids[3:6])

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

    def test_resume_when_classification_hash_changes_but_ids_match(self):
        checkpoint_path, original = self.prepare(1)
        original_hash = original["classification_sha256"]

        payload = json.loads(
            self.classification.read_text(encoding="utf-8")
        )
        payload["metadata_revision"] = "updated"

        self.classification.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        resumed_path, resumed = self.prepare(1)

        self.assertEqual(checkpoint_path, resumed_path)
        self.assertEqual(resumed["ids"], self.ids[:3])
        self.assertEqual(resumed["classification_sha256"], original_hash)
        self.assertEqual(resumed["licitaciones"], original["licitaciones"])

    def test_changed_eligible_ids_reject_existing_checkpoint(self):
        checkpoint_path, _ = self.prepare(1)
        original_bytes = checkpoint_path.read_bytes()

        payload = json.loads(
            self.classification.read_text(encoding="utf-8")
        )
        payload["resultados"][0]["id"] = "999-1-LE26"

        self.classification.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

        self.ids[0] = "999-1-LE26"
        self.authorized = frozenset(self.ids)

        with self.assertRaisesRegex(CheckpointError, "Eligible IDs changed"):
            self.prepare(1)

        self.assertEqual(checkpoint_path.read_bytes(), original_bytes)

    def test_duplicate_ids_across_checkpoints_rejected(self):
        self.prepare(1)
        self.prepare(2)
        second = self.checkpoints / "lote_0002.json"
        payload = json.loads(second.read_text(encoding="utf-8"))
        original = payload["ids"][0]
        duplicate = self.ids[0]
        payload["ids"][0] = duplicate
        payload["licitaciones"][duplicate] = payload["licitaciones"].pop(original)
        second.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BatchPlanningError):
            plan_batches(self.classification, checkpoints_root=self.checkpoints)

    def test_historical_excluded_tender_rejected(self):
        self.prepare(1)
        payload = json.loads(self.classification.read_text(encoding="utf-8"))
        payload["resultados"][0]["estado"] = "excluida"
        payload["resumen"]["incluida"] -= 1
        payload["resumen"]["excluida"] += 1
        self.classification.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(CheckpointError, "Historical excluded tender"):
            plan_batches(self.classification, checkpoints_root=self.checkpoints)

    def test_historical_five_tender_checkpoint_is_preserved(self):
        from checkpoint_descargas import create_checkpoint, save_checkpoint

        self.checkpoints.mkdir(exist_ok=True)
        checkpoint_path = self.checkpoints / "lote_0001.json"

        checkpoint = create_checkpoint(self.ids[:5], self.classification)
        save_checkpoint(checkpoint_path, checkpoint)
        original_bytes = checkpoint_path.read_bytes()

        batches = plan_batches(
            self.classification,
            checkpoints_root=self.checkpoints,
        )

        self.assertEqual([len(batch) for batch in batches], [5, 3, 2])
        self.assertEqual(batches[0], self.ids[:5])

        resumed_path, resumed = self.prepare(1)

        self.assertEqual(resumed_path, checkpoint_path)
        self.assertEqual(resumed["ids"], self.ids[:5])
        self.assertEqual(checkpoint_path.read_bytes(), original_bytes)

    def test_wrong_batch_membership_is_rejected(self):
        with self.assertRaises(BatchPlanningError):
            self.prepare(1, self.ids[3:6])

    def test_incomplete_authorization_is_rejected(self):
        with self.assertRaises(BatchPlanningError):
            prepare_batch(
                self.classification,
                self.checkpoints,
                self.downloads,
                self.extracted,
                1,
                self.ids[:3],
                authorized_ids=set(self.ids[:3]),
            )


if __name__ == "__main__":
    unittest.main()