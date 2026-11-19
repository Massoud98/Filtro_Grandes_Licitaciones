"""Offline integration tests for the complete production batch runner."""

import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

import orquestador_produccion as orchestrator


class FakePlaywright:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class ProductionRunOfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.workspace = self.root / "adjuntos"
        self.run_date = "2026-11-19"
        self.daily_workspace = self.workspace / self.run_date

        self.downloads = self.daily_workspace / "descargas"
        self.extracted = self.daily_workspace / "extraidos"
        self.checkpoints = self.daily_workspace / "checkpoints"

        for directory in (
            self.downloads, self.extracted, self.checkpoints
        ):
            directory.mkdir(parents=True)

        self.ids = [
            f"100-{number}-LE26"
            for number in range(1, 11)
        ]
        self.excluded_id = "999-9-LE26"

        classification_dir = (
            self.root / "datos" / "json" / "consolidados" / self.run_date
        )
        classification_dir.mkdir(parents=True)

        self.classification = (
            classification_dir / "filtros_preliminares.json"
        )
        self.classification.write_text(
            json.dumps({
                "total": 11,
                "resumen": {"incluida": 10, "excluida": 1},
                "resultados": [
                    {"id": tender_id, "estado": "incluida"}
                    for tender_id in self.ids
                ] + [
                    {"id": self.excluded_id, "estado": "excluida"}
                ],
            }),
            encoding="utf-8",
        )

        self.calls = []
        self.authorizations = []
        self.completed = set()
        self.fail_on = None

    def fake_process(
        self, playwright, context, checkpoint, checkpoint_path,
        tender_id, entry, *, authorized_ids=None
    ):
        self.calls.append(tender_id)
        self.authorizations.append(frozenset(authorized_ids))

        if tender_id in self.completed:
            self.assertEqual(entry["status"], "COMPLETE")
            return context

        if tender_id == self.fail_on:
            entry["status"] = "ERROR"
            orchestrator.save_checkpoint(checkpoint_path, checkpoint)
            raise RuntimeError("Simulated tender interruption")

        entry["status"] = "COMPLETE"
        orchestrator.save_checkpoint(checkpoint_path, checkpoint)
        self.completed.add(tender_id)
        return context

    def execute(self, max_batches=1):
        with (
            patch.object(
                orchestrator, "validate_environment",
                return_value=self.classification,
            ),
            patch.object(
                orchestrator, "WORKSPACE", self.workspace
            ),
            patch.object(
                orchestrator, "CHECKPOINTS", self.checkpoints
            ),
            patch.object(
                orchestrator, "DOWNLOADS", self.downloads
            ),
            patch.object(
                orchestrator, "EXTRACTED", self.extracted
            ),
            patch.object(
                orchestrator, "single_instance",
                side_effect=lambda path: contextlib.nullcontext(),
            ),
            patch.object(
                orchestrator, "sync_playwright",
                side_effect=FakePlaywright,
            ),
            patch.object(
                orchestrator, "process_tender",
                side_effect=self.fake_process,
            ),
            patch.object(
                orchestrator, "time"
            ) as fake_time,
        ):
            fake_time.sleep.return_value = None
            return orchestrator.run(
                self.classification,
                max_batches=max_batches,
            )

    def test_completed_tender_survives_batch_shift(self):
        self.execute(max_batches=2)
        self.assertEqual(len(self.completed), 10)

        payload = json.loads(self.classification.read_text(encoding="utf-8"))
        inserted = "100-999-LE26"
        payload["resultados"].insert(9, {"id": inserted, "estado": "incluida"})
        payload["total"] += 1
        payload["resumen"]["incluida"] += 1
        self.classification.write_text(json.dumps(payload), encoding="utf-8")
        self.ids.insert(9, inserted)

        self.calls.clear()
        result = self.execute(max_batches=3)

        self.assertEqual(result["batches"], 3)
        self.assertEqual(self.completed, set(self.ids))
        self.assertEqual(self.calls.count(inserted), 1)

    def test_one_batch_processes_only_five_included(self):
        result = self.execute()

        self.assertEqual(self.calls, self.ids[:5])
        self.assertNotIn(self.excluded_id, self.calls)
        self.assertEqual(result["batches"], 1)
        self.assertEqual(result["batches_remaining"], 1)
        self.assertEqual(result["tenders"], 5)
        self.assertEqual(result["tenders_remaining"], 5)

    def test_limited_run_authorizes_all_included(self):
        self.execute()

        expected = frozenset(self.ids)
        self.assertEqual(len(self.authorizations), 5)
        self.assertTrue(
            all(ids == expected for ids in self.authorizations)
        )
        self.assertNotIn(self.excluded_id, expected)

    def test_failure_stops_batch_immediately(self):
        self.fail_on = self.ids[2]

        with self.assertRaisesRegex(
            RuntimeError, "Simulated tender interruption"
        ):
            self.execute()

        self.assertEqual(self.calls, self.ids[:3])
        self.assertFalse(
            (self.checkpoints / "lote_0002.json").exists()
        )

        persisted = json.loads(
            (self.checkpoints / "lote_0001.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            persisted["licitaciones"][self.ids[2]]["status"],
            "ERROR",
        )

    def test_restart_continues_after_interruption(self):
        self.fail_on = self.ids[2]

        with self.assertRaises(RuntimeError):
            self.execute()

        self.assertEqual(self.completed, set(self.ids[:2]))

        self.fail_on = None
        self.calls.clear()
        result = self.execute()

        self.assertEqual(result["tenders"], 5)
        self.assertEqual(self.calls, self.ids[:5])
        self.assertEqual(self.completed, set(self.ids[:5]))

        persisted = json.loads(
            (self.checkpoints / "lote_0001.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(
            all(
                persisted["licitaciones"][tender_id]["status"]
                == "COMPLETE"
                for tender_id in self.ids[:5]
            )
        )
        self.assertFalse(
            (self.checkpoints / "lote_0002.json").exists()
        )


if __name__ == "__main__":
    unittest.main()