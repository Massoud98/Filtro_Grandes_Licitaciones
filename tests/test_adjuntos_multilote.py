"""Regression tests for shared attachment roots across authorized batches."""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from checkpoint_descargas import (
    CheckpointError,
    create_checkpoint,
    verify_extraction_lifecycle,
)


class MultiBatchLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.downloads = self.root / "descargas"
        self.extracted = self.root / "extraidos"
        self.downloads.mkdir()
        self.extracted.mkdir()

        self.classification = self.root / "filtros_preliminares.json"
        self.classification.write_text(
            '{"total":2,"resumen":{"incluida":2},'
            '"resultados":['
            '{"id":"100-1-LE26","estado":"incluida"},'
            '{"id":"200-2-LE26","estado":"incluida"}]}',
            encoding="utf-8",
        )

        self.first = "100-1-LE26"
        self.second = "200-2-LE26"

        self.checkpoint = create_checkpoint(
            [self.first], self.classification
        )

    def test_single_batch_empty_workspace_is_valid(self):
        self.assertTrue(
            verify_extraction_lifecycle(
                self.checkpoint,
                self.downloads,
                self.extracted,
            )
        )

    def test_other_authorized_batch_directory_accepted(self):
        (self.extracted / self.second).mkdir()

        self.assertTrue(
            verify_extraction_lifecycle(
                self.checkpoint,
                self.downloads,
                self.extracted,
                authorized_ids={self.first, self.second},
            )
        )

    def test_unauthorized_directory_rejected(self):
        (self.extracted / "999-9-LE26").mkdir()

        with self.assertRaisesRegex(
            CheckpointError, "Unexpected tender directory"
        ):
            verify_extraction_lifecycle(
                self.checkpoint,
                self.downloads,
                self.extracted,
            )


    def test_unauthorized_directory_rejected_with_authorized_ids(self):
        (self.extracted / "999-9-LE26").mkdir()

        with self.assertRaisesRegex(
            CheckpointError, "Unexpected tender directory"
        ):
            verify_extraction_lifecycle(
                self.checkpoint,
                self.downloads,
                self.extracted,
                authorized_ids={self.first, self.second},
            )

if __name__ == "__main__":
    unittest.main()
