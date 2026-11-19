import sys
import unittest
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

PROJECT = Path(__file__).resolve().parents[1]
MODULES = PROJECT / "integracion_adjuntos" / "codigo"

if str(MODULES) not in sys.path:
    sys.path.insert(0, str(MODULES))

from navegador_adjuntos import (
    BrowserAccessBlocked,
    BrowserDiscoveryError,
    discover_controls,
)


class FakeBody:
    def __init__(self, popup):
        self.popup = popup

    def inner_text(self, timeout=None):
        self.popup.body_calls += 1
        return self.popup.body_text


class FakeControls:
    def __init__(self, popup, *, fail_wait=True, ids=None):
        self.popup = popup
        self.first = self
        self.fail_wait = fail_wait
        self.ids = ids or []

    def wait_for(self, **kwargs):
        if self.popup.on_timeout is not None:
            self.popup.on_timeout()

        if self.fail_wait:
            raise PlaywrightTimeoutError("Simulated timeout")

    def count(self):
        return len(self.ids)

    def evaluate_all(self, script):
        return self.ids


class FakePopup:
    def __init__(self, *, fail_wait=True, ids=None, on_timeout=None):
        self.url = (
            "https://www.mercadopublico.cl/"
            "Procurement/Modules/Attachment/ViewAttachmentLC.aspx"
        )
        self.body_text = "Attachment list"
        self.body_calls = 0
        self.on_timeout = on_timeout
        self.controls = FakeControls(
            self,
            fail_wait=fail_wait,
            ids=ids,
        )

    def locator(self, selector):
        if selector == "body":
            return FakeBody(self)
        return self.controls


class AttachmentDiscoveryTests(unittest.TestCase):

    def test_delayed_403_detected_after_timeout(self):
        popup = FakePopup(
            on_timeout=lambda: setattr(
                popup, "url", "https://www.mercadopublico.cl/403.html"
            )
        )

        with self.assertRaises(BrowserAccessBlocked):
            discover_controls(popup)

    def test_delayed_abnormal_activity_detected(self):
        popup = FakePopup(
            on_timeout=lambda: setattr(
                popup, "body_text", "Abnormal activity detected"
            )
        )

        with self.assertRaises(BrowserAccessBlocked):
            discover_controls(popup)

    def test_genuinely_empty_page_remains_discovery_error(self):
        popup = FakePopup()

        with self.assertRaises(BrowserDiscoveryError):
            discover_controls(popup)

    def test_successful_discovery_unchanged(self):
        expected = [
            "DWNL_grdId_ctl02_search",
            "DWNL_grdId_ctl03_search",
        ]

        popup = FakePopup(
            fail_wait=False,
            ids=expected,
        )

        self.assertEqual(discover_controls(popup), expected)


if __name__ == "__main__":
    unittest.main()
