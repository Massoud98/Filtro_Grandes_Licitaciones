import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from aplicacion.servicios import detalles_licitaciones as servicio


class RetryAfterTests(unittest.TestCase):

    def response(self, value=None):
        response = Mock()
        response.headers = {}
        if value is not None:
            response.headers["Retry-After"] = value
        return response

    def test_numeric_retry_after(self):
        self.assertEqual(
            servicio._obtener_retry_after(
                self.response("30")
            ),
            30,
        )

    def test_http_date_retry_after(self):
        fixed_now = datetime(
            2026, 11, 11, 12, 0, 0,
            tzinfo=timezone.utc,
        )

        with patch.object(
            servicio,
            "datetime",
        ) as mock_datetime:

            mock_datetime.now.return_value = fixed_now

            result = servicio._obtener_retry_after(
                self.response(
                    "Wed, 11 Nov 2026 12:01:00 GMT"
                )
            )

        self.assertEqual(result, 60)

    def test_past_http_date_returns_zero(self):
        fixed_now = datetime(
            2026, 11, 11, 12, 0, 0,
            tzinfo=timezone.utc,
        )

        with patch.object(
            servicio,
            "datetime",
        ) as mock_datetime:

            mock_datetime.now.return_value = fixed_now

            result = servicio._obtener_retry_after(
                self.response(
                    "Wed, 11 Nov 2026 11:59:00 GMT"
                )
            )

        self.assertEqual(result, 0)

    def test_invalid_header_uses_fallback(self):
        self.assertIsNone(
            servicio._obtener_retry_after(
                self.response("invalid-value")
            )
        )

    def test_missing_header_uses_fallback(self):
        self.assertIsNone(
            servicio._obtener_retry_after(
                self.response()
            )
        )

    def test_negative_header_rejected(self):
        self.assertIsNone(
            servicio._obtener_retry_after(
                self.response("-10")
            )
        )


if __name__ == "__main__":
    unittest.main()