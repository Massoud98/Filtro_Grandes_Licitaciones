"""Offline regression tests for date-isolated attachment workspaces."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "integracion_adjuntos" / "codigo"),
)

from workspace_diario import WorkspaceResolutionError, resolve_workspace


class DailyWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "adjuntos"

    def classification(self, run_date):
        folder = self.root / "datos" / "json" / "consolidados" / run_date
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "filtros_preliminares.json"
        source.write_text("{}", encoding="utf-8")
        return source

    def test_date_isolation(self):
        first = resolve_workspace(self.classification("2026-11-18"), self.workspace)
        second = resolve_workspace(self.classification("2026-11-19"), self.workspace)
        self.assertNotEqual(first.root, second.root)
        self.assertEqual(first.downloads, self.workspace / "2026-11-18" / "descargas")
        self.assertEqual(second.checkpoints, self.workspace / "2026-11-19" / "checkpoints")

    def test_same_date_is_stable(self):
        source = self.classification("2026-11-19")
        self.assertEqual(
            resolve_workspace(source, self.workspace),
            resolve_workspace(source, self.workspace),
        )

    def test_invalid_date_rejected(self):
        with self.assertRaises(WorkspaceResolutionError):
            resolve_workspace(self.classification("invalid-date"), self.workspace)

    def test_unexpected_location_rejected(self):
        source = self.root / "filtros_preliminares.json"
        source.write_text("{}", encoding="utf-8")
        with self.assertRaises(WorkspaceResolutionError):
            resolve_workspace(source, self.workspace)

    def test_no_filesystem_side_effects(self):
        resolve_workspace(self.classification("2026-11-19"), self.workspace)
        self.assertFalse(self.workspace.exists())


if __name__ == "__main__":
    unittest.main()
