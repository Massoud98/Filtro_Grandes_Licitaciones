"""Offline tender orchestration and restart regression tests."""

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

from checkpoint_descargas import create_checkpoint, save_checkpoint
from navegador_adjuntos import BrowserAccessBlocked
from orquestador_produccion import process_tender


class OrchestratorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.tender_id = "100-1-LE26"
        self.authorized = frozenset((self.tender_id,))

        source = self.root / "classification.json"
        source.write_text("{}", encoding="utf-8")

        self.checkpoint = create_checkpoint([self.tender_id], source)
        self.checkpoint_path = self.root / "checkpoint.json"
        save_checkpoint(self.checkpoint_path, self.checkpoint)

        self.entry = self.checkpoint["licitaciones"][self.tender_id]

    def persisted(self):
        return json.loads(
            self.checkpoint_path.read_text(encoding="utf-8")
        )

    def process(self):
        return process_tender(
            None,
            None,
            self.checkpoint,
            self.checkpoint_path,
            self.tender_id,
            self.entry,
            authorized_ids=self.authorized,
        )

    def add_downloaded(self):
        record = {
            "control_id": "DWNL_grdId_01_search",
            "status": "DOWNLOADED",
            "filename": "bases.pdf",
            "size_bytes": 10,
            "sha256": "a" * 64,
        }
        self.entry["attachments"].append(record)
        self.entry["discovered"] = 1
        save_checkpoint(self.checkpoint_path, self.checkpoint)
        return record

    def test_successful_tender_completion(self):
        record = self.add_downloaded()

        def finish(*args, **kwargs):
            record["status"] = "COMPLETE"

        with (
            patch("orquestador_produccion.process_attachment",
                  side_effect=finish),
            patch("orquestador_produccion.verify_extraction_lifecycle"),
        ):
            self.process()

        self.assertEqual(self.entry["status"], "COMPLETE")
        self.assertEqual(self.persisted(), self.checkpoint)

    def test_completed_tender_skips_processing(self):
        record = self.add_downloaded()
        record["status"] = "COMPLETE"
        self.entry["status"] = "COMPLETE"
        save_checkpoint(self.checkpoint_path, self.checkpoint)

        with patch(
            "orquestador_produccion.process_attachment"
        ) as processing:
            self.process()

        processing.assert_not_called()
        self.assertEqual(self.persisted(), self.checkpoint)

    def test_processing_failure_persists_error(self):
        self.add_downloaded()

        with patch(
            "orquestador_produccion.process_attachment",
            side_effect=RuntimeError("Simulated extraction failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Simulated extraction failure"
            ):
                self.process()

        self.assertEqual(self.entry["status"], "ERROR")
        self.assertEqual(self.persisted(), self.checkpoint)
        self.assertEqual(
            self.entry["attachments"][0]["status"], "DOWNLOADED"
        )

    def test_restart_after_error_with_verified_record(self):
        record = self.add_downloaded()
        self.entry["status"] = "ERROR"
        save_checkpoint(self.checkpoint_path, self.checkpoint)

        def finish(*args, **kwargs):
            record["status"] = "COMPLETE"

        with (
            patch("orquestador_produccion.process_attachment",
                  side_effect=finish),
            patch("orquestador_produccion.verify_extraction_lifecycle"),
        ):
            self.process()

        self.assertEqual(self.entry["status"], "COMPLETE")
        self.assertEqual(record["status"], "COMPLETE")
        self.assertEqual(self.persisted(), self.checkpoint)

    def test_transient_browser_failure_retries(self):
        from orquestador_produccion import process_tender_with_retry
        from playwright.sync_api import Error as PlaywrightError

        with (
            patch(
                "orquestador_produccion.process_tender",
                side_effect=[
                    PlaywrightError("Temporary browser failure"),
                    "RECOVERED",
                ],
            ) as processing,
            patch("orquestador_produccion.time.sleep") as sleep,
        ):
            result = process_tender_with_retry(
                None, None, self.checkpoint,
                self.checkpoint_path, self.tender_id,
                self.entry, authorized_ids=self.authorized,
            )

        self.assertEqual(result, "RECOVERED")
        self.assertEqual(processing.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_access_block_is_not_retried(self):
        from orquestador_produccion import process_tender_with_retry

        with (
            patch(
                "orquestador_produccion.process_tender",
                side_effect=BrowserAccessBlocked("HTTP 403"),
            ) as processing,
            patch("orquestador_produccion.time.sleep") as sleep,
        ):
            with self.assertRaises(BrowserAccessBlocked):
                process_tender_with_retry(
                    None, None, self.checkpoint,
                    self.checkpoint_path, self.tender_id,
                    self.entry, authorized_ids=self.authorized,
                )

        processing.assert_called_once()
        sleep.assert_not_called()

    def test_transient_failure_stops_after_three_attempts(self):
        from orquestador_produccion import process_tender_with_retry
        from playwright.sync_api import Error as PlaywrightError

        with (
            patch(
                "orquestador_produccion.process_tender",
                side_effect=PlaywrightError("Temporary browser failure"),
            ) as processing,
            patch("orquestador_produccion.time.sleep") as sleep,
        ):
            with self.assertRaises(PlaywrightError):
                process_tender_with_retry(
                    None, None, self.checkpoint,
                    self.checkpoint_path, self.tender_id,
                    self.entry, authorized_ids=self.authorized,
                )

        self.assertEqual(processing.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_new_browser_closed_after_download_failure(self):
        from unittest.mock import MagicMock
        from orquestador_produccion import download_missing

        context = MagicMock()
        context.new_page.return_value = MagicMock()

        with (
            patch(
                "orquestador_produccion.ensure_browser",
                return_value=context,
            ),
            patch(
                "orquestador_produccion.open_attachment_popup",
                side_effect=RuntimeError("Temporary failure"),
            ),
            patch("orquestador_produccion.close_page"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Temporary failure"
            ):
                download_missing(
                    None, None, self.checkpoint,
                    self.checkpoint_path, self.tender_id,
                    self.entry, authorized_ids=self.authorized,
                )

        context.close.assert_called_once()

    def test_existing_browser_not_closed_by_download_missing(self):
        from unittest.mock import MagicMock
        from orquestador_produccion import download_missing

        context = MagicMock()

        with (
            patch(
                "orquestador_produccion.ensure_browser",
                return_value=context,
            ),
            patch(
                "orquestador_produccion.open_attachment_popup",
                side_effect=RuntimeError("Temporary failure"),
            ),
            patch("orquestador_produccion.close_page"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Temporary failure"
            ):
                download_missing(
                    None, context, self.checkpoint,
                    self.checkpoint_path, self.tender_id,
                    self.entry, authorized_ids=self.authorized,
                )

        context.close.assert_not_called()

    def test_browser_access_block_persists_blocked(self):
        with patch(
            "orquestador_produccion.download_missing",
            side_effect=BrowserAccessBlocked("Simulated access restriction"),
        ):
            with self.assertRaises(BrowserAccessBlocked):
                self.process()

        self.assertEqual(self.entry["status"], "BLOCKED")
        self.assertEqual(self.persisted(), self.checkpoint)


if __name__ == "__main__":
    unittest.main()