"""Offline tests for persistent Filter 2 evaluation records."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from estado_filtro_2 import (
    RULE_VERSION,
    evidence_fingerprint,
    load_evaluations,
    reusable_evaluation,
    save_evaluation,
)


class TestFilter2Persistence(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.store_path = self.root / "estado_filtro_2.json"
        self.text_path = self.root / "contenido.txt"
        self.metadata_path = self.root / "contenido.json"

        self.text_path.write_text(
            "Bases de licitación de prueba.", encoding="utf-8"
        )
        self.metadata_path.write_text(
            '{"status":"COMPLETE"}', encoding="utf-8"
        )

        self.documents = [{
            "filename": "bases.pdf",
            "control_id": "DWNL_test_1",
            "source_sha256": "a" * 64,
            "text_path": str(self.text_path),
            "metadata_path": str(self.metadata_path),
        }]

        self.tender_id = "12345-67-LE26"

    def save(self, decision="APROBADA", fingerprint=None, tender_id=None, rule_version=None):
        return save_evaluation(
            self.store_path,
            tender_id or self.tender_id,
            decision,
            fingerprint or evidence_fingerprint(self.documents),
            reasons=["Evaluación documental completada."],
            evidence=[{"filename": "bases.pdf", "page": 1}],
            **({"rule_version": rule_version} if rule_version else {}),
        )

    def test_empty_store(self):
        data = load_evaluations(self.store_path)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["evaluations"], {})

    def test_save_and_reload(self):
        self.save()
        data = load_evaluations(self.store_path)
        self.assertEqual(
            data["evaluations"][self.tender_id]["decision"],
            "APROBADA",
        )

    def test_reuse_unchanged_evidence(self):
        fingerprint = evidence_fingerprint(self.documents)
        self.save(fingerprint=fingerprint)
        store = load_evaluations(self.store_path)
        record = reusable_evaluation(
            store, self.tender_id, fingerprint
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["decision"], "APROBADA")

    def test_changed_text_invalidates_cache(self):
        fingerprint = evidence_fingerprint(self.documents)
        self.save(fingerprint=fingerprint)

        self.text_path.write_text(
            "Contenido actualizado.", encoding="utf-8"
        )

        changed = evidence_fingerprint(self.documents)
        self.assertNotEqual(fingerprint, changed)

        store = load_evaluations(self.store_path)
        self.assertIsNone(
            reusable_evaluation(store, self.tender_id, changed)
        )

    def test_changed_metadata_invalidates_cache(self):
        before = evidence_fingerprint(self.documents)
        self.metadata_path.write_text(
            '{"status":"COMPLETE","updated":true}',
            encoding="utf-8",
        )
        after = evidence_fingerprint(self.documents)
        self.assertNotEqual(before, after)

    def test_changed_rule_version_invalidates_cache(self):
        fingerprint = evidence_fingerprint(self.documents)
        self.save(fingerprint=fingerprint, rule_version="filtro2-jessika-v1")

        store = load_evaluations(self.store_path)

        self.assertIsNone(
            reusable_evaluation(
                store,
                self.tender_id,
                fingerprint,
                rule_version="filtro2-jessika-v2",
            )
        )

    def test_invalid_decision_rejected(self):
        with self.assertRaises(ValueError):
            self.save(decision="PENDING")

        self.assertFalse(self.store_path.exists())

    def test_multiple_tenders_preserved(self):
        self.save()
        self.save(
            decision="EXCLUIDA",
            tender_id="98765-43-LE26",
        )

        store = load_evaluations(self.store_path)
        self.assertEqual(len(store["evaluations"]), 2)

    def test_replacement_updates_one_tender(self):
        self.save()
        self.save(decision="EXCLUIDA")

        store = load_evaluations(self.store_path)
        self.assertEqual(len(store["evaluations"]), 1)
        self.assertEqual(
            store["evaluations"][self.tender_id]["decision"],
            "EXCLUIDA",
        )

    def test_corrupted_store_rejected(self):
        self.store_path.write_text(
            '{"schema_version":999,"evaluations":{}}',
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            load_evaluations(self.store_path)

    def test_fingerprint_order_independent(self):
        second_text = self.root / "segundo.txt"
        second_meta = self.root / "segundo.json"
        second_text.write_text("Segundo documento.", encoding="utf-8")
        second_meta.write_text("{}", encoding="utf-8")

        second = {
            "filename": "anexo.pdf",
            "control_id": "DWNL_test_2",
            "source_sha256": "b" * 64,
            "text_path": str(second_text),
            "metadata_path": str(second_meta),
        }

        forward = evidence_fingerprint(self.documents + [second])
        backward = evidence_fingerprint([second] + self.documents)

        self.assertEqual(forward, backward)


if __name__ == "__main__":
    unittest.main()

def test_api_budget_changes_fingerprint(tmp_path):
    from estado_filtro_2 import evidence_fingerprint

    text_path = tmp_path / "document.txt"
    metadata_path = tmp_path / "metadata.json"

    text_path.write_text("Evidence", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    documents = [{
        "filename": "bases.pdf",
        "control_id": "TEST",
        "source_sha256": "source",
        "text_path": str(text_path),
        "metadata_path": str(metadata_path),
    }]

    api = {
        "status": "FOUND",
        "amount": 80000000,
        "currency": "CLP",
    }

    original = evidence_fingerprint(
        documents, api_budget=api
    )

    assert original != evidence_fingerprint(documents)

    for changed in (
        dict(api, amount=580000000),
        dict(api, currency="USD"),
        dict(api, status="AMOUNT_MISSING"),
    ):
        assert evidence_fingerprint(
            documents, api_budget=changed
        ) != original


def test_api_fingerprint_order_independent(tmp_path):
    from estado_filtro_2 import evidence_fingerprint

    text_path = tmp_path / "document.txt"
    metadata_path = tmp_path / "metadata.json"

    text_path.write_text("Evidence", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    documents = [{
        "filename": "bases.pdf",
        "control_id": "TEST",
        "source_sha256": "source",
        "text_path": str(text_path),
        "metadata_path": str(metadata_path),
    }]

    first = {
        "status": "FOUND",
        "amount": 80000000,
        "currency": "CLP",
    }

    second = dict(reversed(list(first.items())))

    assert evidence_fingerprint(
        documents, api_budget=first
    ) == evidence_fingerprint(
        documents, api_budget=second
    )


def test_api_source_date_changes_fingerprint(tmp_path):
    from estado_filtro_2 import evidence_fingerprint

    text_path = tmp_path / "document.txt"
    metadata_path = tmp_path / "metadata.json"

    text_path.write_text("Evidence", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    documents = [{
        "filename": "bases.pdf",
        "control_id": "TEST",
        "source_sha256": "source",
        "text_path": str(text_path),
        "metadata_path": str(metadata_path),
    }]

    first = {
        "status": "FOUND",
        "amount": 80000000,
        "currency": "CLP",
        "source_date": "2026-11-19",
    }

    second = dict(first, source_date="2026-11-20")

    assert evidence_fingerprint(
        documents, api_budget=first
    ) != evidence_fingerprint(
        documents, api_budget=second
    )
