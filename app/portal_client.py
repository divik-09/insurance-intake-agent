"""Automation that fills in the carrier portal form and reads back the quote.

Two interchangeable drivers behind one interface:
  * PlaywrightPortalClient – drives a real headless browser, like you'd have to for a
    real carrier portal that has no API (optional install, see requirements-browser.txt)
  * HttpPortalClient       – posts the same form fields over HTTP; fast, no browser needed

`build_portal_client` picks Playwright when a browser is installed, otherwise HTTP.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import Settings
from .schemas import Submission

log = logging.getLogger("intake.portal")


class PortalError(RuntimeError):
    """The portal call failed in a way that is worth retrying."""


@dataclass(frozen=True)
class Quote:
    quote_id: str
    premium: float


class PortalClient(Protocol):
    driver: str

    def submit(self, sub: Submission, contact_email: str) -> Quote: ...


def _form_fields(sub: Submission, contact_email: str) -> dict[str, Any]:
    if sub.missing_fields():
        raise ValueError(f"cannot submit incomplete submission, missing: {sub.missing_fields()}")
    return {
        "business_name": sub.business_name,
        "industry": sub.industry.value,  # type: ignore[union-attr]
        "state": sub.state,
        "employee_count": str(sub.employee_count),
        "annual_revenue": str(sub.annual_revenue),
        "contact_email": contact_email,
        "coverage": [c.value for c in sub.coverage_types],
    }


_QUOTE_ID_RE = re.compile(r"id=['\"]quote-id['\"]>([^<]+)<")
_PREMIUM_RE = re.compile(r"id=['\"]premium['\"] data-value=['\"]([\d.]+)['\"]")


def parse_quote_page(page_html: str) -> Quote:
    qid, prem = _QUOTE_ID_RE.search(page_html), _PREMIUM_RE.search(page_html)
    if not (qid and prem):
        raise PortalError("could not find quote on the result page")
    return Quote(quote_id=qid.group(1).strip(), premium=float(prem.group(1)))


class HttpPortalClient:
    driver = "http"

    def __init__(self, base_url: str = "", client: httpx.Client | None = None, timeout: float = 10.0):
        # `client` can be injected (tests pass FastAPI's TestClient, which *is* an httpx.Client)
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def submit(self, sub: Submission, contact_email: str) -> Quote:
        try:
            resp = self._client.post("/portal/quote", data=_form_fields(sub, contact_email))
        except httpx.HTTPError as exc:
            raise PortalError(f"http error talking to portal: {exc}") from exc
        if resp.status_code != 200:
            raise PortalError(f"portal returned HTTP {resp.status_code}")
        return parse_quote_page(resp.text)


class PlaywrightPortalClient:
    driver = "playwright"

    def __init__(self, base_url: str, headless: bool = True, timeout_ms: int = 8000):
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.timeout_ms = timeout_ms

    def submit(self, sub: Submission, contact_email: str) -> Quote:
        from playwright.sync_api import sync_playwright

        fields = _form_fields(sub, contact_email)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                try:
                    page = browser.new_page()
                    page.set_default_timeout(self.timeout_ms)
                    page.goto(f"{self.base_url}/portal/quote")
                    page.fill("#business_name", fields["business_name"])
                    page.select_option("#industry", fields["industry"])
                    page.select_option("#state", fields["state"])
                    page.fill("#employee_count", fields["employee_count"])
                    page.fill("#annual_revenue", fields["annual_revenue"])
                    for cov in fields["coverage"]:
                        page.check(f"#cov-{cov}")
                    page.fill("#contact_email", fields["contact_email"])
                    page.click("#submit")
                    page.wait_for_selector("#quote-id")  # times out if the portal errored
                    return Quote(
                        quote_id=page.inner_text("#quote-id").strip(),
                        premium=float(page.get_attribute("#premium", "data-value")),
                    )
                finally:
                    browser.close()
        except Exception as exc:  # playwright raises its own Error/TimeoutError types
            raise PortalError(f"playwright driver failed: {exc}") from exc


def playwright_available() -> bool:
    """True only if the package AND a Chromium binary are installed."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


def build_portal_client(settings: Settings) -> PortalClient:
    choice = settings.portal_driver
    if choice == "http":
        client: PortalClient = HttpPortalClient(settings.portal_base_url)
    elif choice == "playwright":
        client = PlaywrightPortalClient(settings.portal_base_url)
    elif playwright_available():
        client = PlaywrightPortalClient(settings.portal_base_url)
    else:
        client = HttpPortalClient(settings.portal_base_url)
    log.info("portal driver selected", extra={"driver": client.driver})
    return client
