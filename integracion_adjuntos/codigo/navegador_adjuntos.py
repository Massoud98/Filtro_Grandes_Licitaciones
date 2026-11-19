"""Read-only attachment discovery for Mercado Publico."""

import re
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


class BrowserDiscoveryError(RuntimeError):
    """Attachment discovery failed."""


class BrowserAccessBlocked(BrowserDiscoveryError):
    """The website refused access."""


TENDER_URL = (
    "https://www.mercadopublico.cl/"
    "Procurement/Modules/RFB/DetailsAcquisition.aspx"
)

ATTACHMENT_URL_PARTS = (
    "/Procurement/Modules/Attachment/ViewAttachmentLC.aspx",
    "/Procurement/Modules/Attachment/ViewAttachment.aspx",
)

def is_attachment_url(url):
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.mercadopublico.cl"
        and parsed.port in (None, 443)
        and parsed.path.lower() in {
            item.lower() for item in ATTACHMENT_URL_PARTS
        }
    )

DOWNLOAD_CONTROL_SELECTOR = (
    'input[type="image"]'
    '[id^="DWNL_grdId_"]'
    '[id$="_search"]'
)


def tender_url(tender_id):
    if not isinstance(tender_id, str) or re.fullmatch(
        r"[0-9]+-[0-9]+-[A-Za-z0-9]+",
        tender_id,
    ) is None:
        raise BrowserDiscoveryError("Invalid tender ID.")

    return TENDER_URL + "?idlicitacion=" + quote(tender_id)


def check_access(page, response=None):
    if response is not None and response.status in (
        401, 403, 429,
    ):
        raise BrowserAccessBlocked(
            "HTTP access restriction: "
            + str(response.status)
        )

    url = page.url.lower()

    if "/403.html" in url or "/429.html" in url:
        raise BrowserAccessBlocked(
            "Access restriction page."
        )

    body = page.locator("body").inner_text(
        timeout=10000
    ).lower()

    indicators = (
        "abnormal activity",
        "actividad anormal",
        "access denied",
        "acceso denegado",
    )

    if any(indicator in body for indicator in indicators):
        raise BrowserAccessBlocked(
            "Website access restriction detected."
        )


def discover_controls(popup):
    check_access(popup)

    controls = popup.locator(DOWNLOAD_CONTROL_SELECTOR)

    try:
        controls.first.wait_for(
            state="visible",
            timeout=15000,
        )
    except PlaywrightTimeoutError:
        # The attachment page may have redirected to a restriction
        # page while Playwright was waiting for its download controls.
        check_access(popup)

        if controls.count() == 0:
            raise BrowserDiscoveryError(
                "No individual attachment controls found."
            )

    ids = controls.evaluate_all(
        "(els) => els.map(e => e.id)"
    )

    if len(ids) != len(set(ids)):
        raise BrowserDiscoveryError(
            "Duplicate attachment controls."
        )

    if any(not control_id for control_id in ids):
        raise BrowserDiscoveryError(
            "Download control without ID."
        )

    return ids


def open_attachment_popup(page, tender_id):
    response = page.goto(
        tender_url(tender_id),
        wait_until="domcontentloaded",
        timeout=60000,
    )

    check_access(page, response)

    if response is None or response.status != 200:
        raise BrowserDiscoveryError(
            "Tender page did not return HTTP 200."
        )

    button = page.locator("#imgAdjuntos")

    if button.count() != 1:
        raise BrowserDiscoveryError(
            "Attachment button missing or ambiguous."
        )

    context = page.context
    captured = []

    def on_response(response):
        try:
            request = response.request

            if (
                request.is_navigation_request()
                and request.resource_type == "document"
                and is_attachment_url(response.url)
            ):
                captured.append(response)
        except Exception:
            pass

    context.on("response", on_response)

    try:
        try:
            with page.expect_popup(timeout=30000) as event:
                button.click(timeout=15000)

            popup = event.value

            popup.wait_for_load_state(
                "domcontentloaded",
                timeout=30000,
            )

            popup.wait_for_url(
                is_attachment_url,
                timeout=30000,
            )

        except PlaywrightTimeoutError as exc:
            # A popup may have redirected to a restriction page while
            # Playwright was waiting for the expected attachment URL.
            if "popup" in locals():
                current_url = popup.url.lower()

                if (
                    "/403.html" in current_url
                    or "/429.html" in current_url
                ):
                    raise BrowserAccessBlocked(
                        "Attachment popup redirected to an access "
                        "restriction page."
                    ) from exc

                # Also detect restriction messages on otherwise
                # unexpected popup URLs.
                check_access(popup)

            raise BrowserDiscoveryError(
                "Attachment popup timed out."
            ) from exc

        check_access(popup)

        if not is_attachment_url(popup.url):
            raise BrowserDiscoveryError(
                "Unexpected attachment popup URL."
            )

        matching = [
            item for item in captured
            if item.url == popup.url
        ]

        if len(matching) != 1:
            raise BrowserDiscoveryError(
                "Popup HTTP response could not be verified."
            )

        status = matching[0].status

        if status in (401, 403, 429):
            raise BrowserAccessBlocked(
                "Popup HTTP access restriction: "
                + str(status)
            )

        if status != 200:
            raise BrowserDiscoveryError(
                "Popup HTTP error: " + str(status)
            )

        return popup

    finally:
        context.remove_listener("response", on_response)
