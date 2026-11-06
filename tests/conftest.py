import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.llm import HeuristicClient
from app.main import create_app
from app.portal_client import HttpPortalClient, PortalError, Quote
from app.service import IntakeService


@pytest.fixture
def settings() -> Settings:
    # in-memory SQLite, HTTP portal driver, no random portal failures
    return Settings(database_url="sqlite://", portal_driver="http", portal_failure_rate=0.0)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        # The mock portal lives inside the same app, so route the automation through this client.
        app.state.service.portal = HttpPortalClient(client=c)
        app.state.service.base_delay = 0  # never sleep in tests
        yield c


class FlakyPortal:
    """Fails `fail_times` times with PortalError, then returns a quote."""

    driver = "fake"

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0

    def submit(self, sub, contact_email):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise PortalError("simulated portal outage")
        return Quote(quote_id="Q-TEST0001", premium=1234.5)


@pytest.fixture
def make_service():
    def _make(portal=None, llm=None, max_attempts=3) -> IntakeService:
        sf = make_session_factory(make_engine("sqlite://"))
        return IntakeService(
            sf, llm or HeuristicClient(), portal or FlakyPortal(),
            max_attempts=max_attempts, base_delay=0, sleep=lambda s: None,
        )

    return _make
