"""Real-browser test. Skipped automatically unless Playwright + Chromium are installed:

    pip install -r requirements-browser.txt && playwright install chromium
"""
import socket
import threading
import time

import pytest

from app.portal_client import PlaywrightPortalClient, playwright_available
from app.schemas import Submission

pytestmark = pytest.mark.skipif(not playwright_available(), reason="Playwright/Chromium not installed")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_playwright_fills_form_and_reads_quote():
    import uvicorn

    from app.config import Settings
    from app.main import create_app

    port = _free_port()
    app = create_app(Settings(database_url="sqlite://", portal_driver="http"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    try:
        sub = Submission(business_name="Sweet Crumbs Bakery", industry="restaurant_food", state="OH",
                         employee_count=6, annual_revenue=450_000, coverage_types=["general_liability"])
        quote = PlaywrightPortalClient(f"http://127.0.0.1:{port}").submit(sub, "owner@example.com")
        assert quote.quote_id.startswith("Q-") and quote.premium > 0
    finally:
        server.should_exit = True
        thread.join(timeout=5)
