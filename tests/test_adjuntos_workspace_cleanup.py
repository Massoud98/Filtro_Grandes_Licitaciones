import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"
sys.path.insert(0, str(MODULES))

import orquestador_produccion as orchestrator


class DailyWorkspaceCleanupTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name) / "2026-11-19"
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.checkpoints = self.root / "checkpoints"

        for folder in (self.downloads, self.extracted, self.checkpoints):
            folder.mkdir(parents=True)

        self.authorized = {"100-1-LE26", "100-2-LE26"}

        self.report_result = {
            "reviews": 2,
            "verified": 2,
            "missing": 0,
            "integrity_failed": 0,
            "report": str(self.root / "revision_manual.csv"),
        }

    def execute(self, report_mock):
        with (
            patch.object(orchestrator, "DOWNLOADS", self.downloads),
            patch.object(orchestrator, "EXTRACTED", self.extracted),
            patch.object(orchestrator, "CHECKPOINTS", self.checkpoints),
            patch.object(
                orchestrator,
                "rebuild_manual_review_report",
                report_mock,
            ),
        ):
            return orchestrator.refresh_daily_workspace(self.authorized)

    def test_empty_authorized_directories_removed(self):
        for root in (self.downloads, self.extracted):
            (root / "100-1-LE26").mkdir()

        with patch(
            "orquestador_produccion.rebuild_manual_review_report",
            return_value=self.report_result,
        ):
            self.execute(
                orchestrator.rebuild_manual_review_report
            )

        for root in (self.downloads, self.extracted):
            self.assertFalse((root / "100-1-LE26").exists())

    def test_nonempty_directories_preserved(self):
        for root in (self.downloads, self.extracted):
            folder = root / "100-2-LE26"
            folder.mkdir()
            (folder / "preserve.txt").write_text("keep")

        from unittest.mock import Mock
        report = Mock(return_value=self.report_result)
        self.execute(report)

        for root in (self.downloads, self.extracted):
            self.assertTrue(
                (root / "100-2-LE26" / "preserve.txt").is_file()
            )

    def test_unauthorized_directories_preserved(self):
        for root in (self.downloads, self.extracted):
            (root / "999-9-LE26").mkdir()

        from unittest.mock import Mock
        report = Mock(return_value=self.report_result)
        self.execute(report)

        for root in (self.downloads, self.extracted):
            self.assertTrue((root / "999-9-LE26").is_dir())

    def test_report_failure_prevents_cleanup(self):
        folder = self.downloads / "100-1-LE26"
        folder.mkdir()

        from unittest.mock import Mock
        report = Mock(side_effect=RuntimeError("Report failure"))

        with self.assertRaises(RuntimeError):
            self.execute(report)

        self.assertTrue(folder.is_dir())

    def test_report_uses_dated_workspace(self):
        from unittest.mock import Mock
        report = Mock(return_value=self.report_result)

        self.execute(report)

        report.assert_called_once_with(
            self.checkpoints,
            self.downloads,
            self.root / "revision_manual.csv",
        )


if __name__ == "__main__":
    unittest.main()