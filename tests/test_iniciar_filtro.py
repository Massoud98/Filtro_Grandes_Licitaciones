import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import iniciar_filtro


class FakeKeyring:
    def __init__(self):
        self.data = {}
    def get_password(self, service, username):
        return self.data.get((service, username))
    def set_password(self, service, username, value):
        self.data[(service, username)] = value


class LauncherTests(unittest.TestCase):
    def test_help_does_not_run_pipeline(self):
        with patch.object(iniciar_filtro.sys, "argv", ["Iniciar_Filtro.exe", "--help"]):
            with patch.object(iniciar_filtro, "run_scheduled_pipeline", side_effect=AssertionError("Production started")):
                self.assertEqual(iniciar_filtro.main(), 0)

    def test_self_test_does_not_run_pipeline(self):
        with patch.object(iniciar_filtro.sys, "argv", ["Iniciar_Filtro.exe", "--self-test"]):
            with patch.object(iniciar_filtro, "run_scheduled_pipeline", side_effect=AssertionError("Production started")):
                with patch.object(iniciar_filtro, "run_runtime_self_test", return_value=0) as validation:
                    self.assertEqual(iniciar_filtro.main(), 0)
                    validation.assert_called_once_with()

    def test_unknown_argument_does_not_run_pipeline(self):
        with patch.object(iniciar_filtro.sys, "argv", ["Iniciar_Filtro.exe", "--unexpected"]):
            with patch.object(iniciar_filtro, "run_scheduled_pipeline", side_effect=AssertionError("Production started")):
                self.assertEqual(iniciar_filtro.main(), 2)

    def test_combined_arguments_do_not_run_pipeline(self):
        with patch.object(iniciar_filtro.sys, "argv", ["Iniciar_Filtro.exe", "--self-test", "--unexpected"]):
            with patch.object(iniciar_filtro, "run_scheduled_pipeline", side_effect=AssertionError("Production started")):
                with patch.object(iniciar_filtro, "run_runtime_self_test", side_effect=AssertionError("Self-test started")):
                    self.assertEqual(iniciar_filtro.main(), 2)

    def test_saved_credential_reused(self):
        kr = FakeKeyring()
        kr.data[(iniciar_filtro.APP_SERVICE, "API_MP")] = "saved"
        prompt = Mock(side_effect=AssertionError("unexpected prompt"))
        self.assertEqual(iniciar_filtro.credential("API_MP", "Ticket", True, kr), "saved")

    def test_new_credential_saved(self):
        kr = FakeKeyring()
        original = iniciar_filtro.getpass.getpass
        try:
            iniciar_filtro.getpass.getpass = lambda _: "new-token"
            self.assertEqual(iniciar_filtro.credential("API_MP", "Ticket", True, kr), "new-token")
            self.assertEqual(kr.get_password(iniciar_filtro.APP_SERVICE, "API_MP"), "new-token")
        finally:
            iniciar_filtro.getpass.getpass = original

    def test_optional_token_can_be_skipped(self):
        kr = FakeKeyring()
        original = iniciar_filtro.getpass.getpass
        try:
            iniciar_filtro.getpass.getpass = lambda _: ""
            self.assertIsNone(iniciar_filtro.credential("BCCH_API_TOKEN", "BC token", False, kr))
        finally:
            iniciar_filtro.getpass.getpass = original

    def test_required_token_cannot_be_blank(self):
        kr = FakeKeyring()
        original = iniciar_filtro.getpass.getpass
        try:
            iniciar_filtro.getpass.getpass = lambda _: ""
            with self.assertRaises(RuntimeError):
                iniciar_filtro.credential("API_MP", "Ticket", True, kr)
        finally:
            iniciar_filtro.getpass.getpass = original

    def test_existing_list_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "list.json"
            p.write_text(json.dumps({"fecha": "2026-11-10", "licitaciones": []}), encoding="utf-8")
            self.assertEqual(iniciar_filtro.load_existing_publication(p, "2026-11-10")["fecha"], "2026-11-10")

    def test_wrong_date_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "list.json"
            p.write_text(json.dumps({"fecha": "2026-11-09", "licitaciones": []}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                iniciar_filtro.load_existing_publication(p, "2026-11-10")

    def test_existing_output_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = iniciar_filtro.ROOT
            try:
                iniciar_filtro.ROOT = Path(tmp)
                out = Path(tmp) / "data" / "2026-11-10" / "file.xlsx"
                out.parent.mkdir(parents=True)
                out.write_bytes(b"old")
                backup = iniciar_filtro.backup_existing(out)
                self.assertTrue(backup.is_file())
                self.assertEqual(backup.read_bytes(), b"old")
                self.assertEqual(out.read_bytes(), b"old")
            finally:
                iniciar_filtro.ROOT = root

    def test_missing_output_not_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent.xlsx"
            self.assertIsNone(iniciar_filtro.backup_existing(path))



    def test_custom_runtime_root_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                iniciar_filtro.os.environ,
                {"FILTRO_LICITACIONES_ROOT": tmp},
            ):
                self.assertEqual(
                    iniciar_filtro.project_root(),
                    Path(tmp).resolve(),
                )

    def test_frozen_default_production_root_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                iniciar_filtro.os.environ,
                {"FILTRO_LICITACIONES_ROOT": ""},
            ):
                with patch.object(
                    iniciar_filtro.sys,
                    "frozen",
                    True,
                    create=True,
                ):
                    with patch(
                        "pathlib.Path.home",
                        return_value=Path(tmp),
                    ):
                        self.assertEqual(
                            iniciar_filtro.project_root(),
                            Path(tmp) / "Documents"
                            / "Filtro_Grandes_Licitaciones",
                        )

    def test_development_root_preserved(self):
        with patch.dict(
            iniciar_filtro.os.environ,
            {"FILTRO_LICITACIONES_ROOT": ""},
        ):
            with patch.object(
                iniciar_filtro.sys,
                "frozen",
                False,
                create=True,
            ):
                self.assertEqual(
                    iniciar_filtro.project_root(),
                    Path(iniciar_filtro.__file__).resolve().parent,
                )


if __name__ == "__main__":
    unittest.main()
