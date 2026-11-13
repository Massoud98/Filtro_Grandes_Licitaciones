import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from aplicacion.servicios import detalles_licitaciones as servicio


class DetailRetrievalTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fecha = "2026-11-09"
        self.folder = self.root / self.fecha
        self.folder.mkdir()

        self.ids = ["TEST-001", "TEST-002"]

        (self.folder / "licitaciones_publicadas.json").write_text(
            json.dumps({
                "fecha": self.fecha,
                "licitaciones": [
                    {"CodigoExterno": codigo}
                    for codigo in self.ids
                ],
            }),
            encoding="utf-8",
        )

        self.root_patch = patch.object(
            servicio, "CARPETA_ORIGINALES", self.root
        )
        self.env_patch = patch.dict(
            "os.environ", {"API_MP": "test-ticket"}
        )

        self.root_patch.start()
        self.env_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.env_patch.stop()
        self.temp.cleanup()

    def response(self, codigo):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "Listado": [{
                "CodigoExterno": codigo,
                "Tipo": "L1",
            }]
        }
        return response

    def read_progress(self):
        return json.loads(
            (self.folder / "detalles_licitaciones.json")
            .read_text(encoding="utf-8")
        )

    def test_connection_timeout_retries_and_succeeds(self):
        successful = self.response("TEST-001")

        with patch.object(
            servicio.requests,
            "get",
            side_effect=[
                requests.ConnectTimeout(),
                successful,
                self.response("TEST-002"),
            ],
        ) as mock_get, patch.object(
            servicio.time, "sleep"
        ) as mock_sleep:

            result = servicio.obtener_detalles(
                self.fecha, intervalo=0
            )

        self.assertEqual(result["obtenidos"], 2)
        self.assertEqual(result["pendientes"], 0)
        self.assertEqual(mock_get.call_count, 3)
        mock_sleep.assert_any_call(5)

        progress = self.read_progress()
        self.assertEqual(len(progress["detalles"]), 2)
        self.assertNotIn("TEST-001", progress["errores"])
        self.assertEqual(progress["intentos"]["TEST-001"], 2)

    def test_http_429_retries(self):
        error_response = Mock()
        error_response.status_code = 429

        http_error = requests.HTTPError(
            response=error_response
        )

        with patch.object(
            servicio.requests,
            "get",
            side_effect=[
                Mock(raise_for_status=Mock(side_effect=http_error)),
                self.response("TEST-001"),
                self.response("TEST-002"),
            ],
        ) as mock_get, patch.object(
            servicio.time, "sleep"
        ) as mock_sleep:

            result = servicio.obtener_detalles(
                self.fecha, intervalo=0
            )

        self.assertEqual(result["obtenidos"], 2)
        self.assertEqual(mock_get.call_count, 3)
        mock_sleep.assert_any_call(5)

    def test_permanent_http_error_preserves_progress(self):
        error_response = Mock()
        error_response.status_code = 401

        http_error = requests.HTTPError(
            response=error_response
        )

        with patch.object(
            servicio.requests,
            "get",
            side_effect=http_error,
        ) as mock_get:

            result = servicio.obtener_detalles(
                self.fecha, intervalo=0
            )

        self.assertEqual(result["obtenidos"], 0)
        self.assertEqual(result["pendientes"], 2)
        self.assertEqual(result["errores"], 1)
        mock_get.assert_called_once()

        progress = self.read_progress()
        self.assertIn("TEST-001", progress["errores"])

    def test_completed_tenders_are_not_requested_again(self):
        progress_path = (
            self.folder / "detalles_licitaciones.json"
        )

        progress_path.write_text(
            json.dumps({
                "fecha": self.fecha,
                "ids": self.ids,
                "detalles": {
                    "TEST-001": {
                        "CodigoExterno": "TEST-001",
                        "Tipo": "L1",
                    }
                },
                "errores": {},
                "intentos": {},
            }),
            encoding="utf-8",
        )

        with patch.object(
            servicio.requests,
            "get",
            return_value=self.response("TEST-002"),
        ) as mock_get:

            result = servicio.obtener_detalles(
                self.fecha, intervalo=0
            )

        self.assertEqual(result["obtenidos"], 2)
        self.assertEqual(result["pendientes"], 0)
        mock_get.assert_called_once()

        requested_code = mock_get.call_args.kwargs["params"]["codigo"]
        self.assertEqual(requested_code, "TEST-002")


if __name__ == "__main__":
    unittest.main()