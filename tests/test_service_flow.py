from app.db import COLLECTING, PORTAL_FAILED, SUBMITTED
from app.llm import ExtractionError
from tests.conftest import FlakyPortal

FIRST = "I own Sweet Crumbs Bakery in Columbus, Ohio. 6 employees. Need general liability and workers comp."
SECOND = "Sorry! We did about $450,000 in revenue last year."


# ---------------------------------------------------------------- service level
def test_two_turn_conversation_ends_in_a_quote(make_service):
    svc = make_service(portal=FlakyPortal())
    r1 = svc.handle_inbound("Owner@SweetCrumbs.com", FIRST)
    assert r1.status == COLLECTING
    assert r1.missing == ["annual_revenue"]
    assert "annual revenue" in r1.reply

    r2 = svc.handle_inbound("owner@sweetcrumbs.com", SECOND)  # same sender, different casing
    assert r2.case_id == r1.case_id                           # continued the same case
    assert r2.status == SUBMITTED
    assert r2.quote == {"quote_id": "Q-TEST0001", "premium": 1234.5}

    case = svc.get_case(r1.case_id)
    assert [m["direction"] for m in case["messages"]] == ["inbound", "outbound", "inbound", "outbound"]
    assert case["portal_runs"][0]["status"] == "ok"


def test_portal_retries_then_succeeds(make_service):
    portal = FlakyPortal(fail_times=2)
    svc = make_service(portal=portal, max_attempts=3)
    r = svc.handle_inbound("a@b.co", FIRST + " " + SECOND)
    assert r.status == SUBMITTED
    assert portal.calls == 3
    assert svc.get_case(r.case_id)["portal_runs"][0]["attempts"] == 3


def test_portal_exhaustion_marks_case_failed_and_retry_recovers(make_service):
    portal = FlakyPortal(fail_times=99)
    svc = make_service(portal=portal, max_attempts=3)
    r = svc.handle_inbound("a@b.co", FIRST + " " + SECOND)
    assert r.status == PORTAL_FAILED
    assert "delay" in r.reply  # customer gets an honest holding message, not silence
    run = svc.get_case(r.case_id)["portal_runs"][0]
    assert run["status"] == "failed" and run["attempts"] == 3 and "outage" in run["error"]

    portal.fail_times = 0  # the carrier comes back
    recovered = svc.retry_portal(r.case_id)
    assert recovered.status == SUBMITTED and recovered.quote


def test_submitted_case_is_never_submitted_twice(make_service):
    portal = FlakyPortal()
    svc = make_service(portal=portal)
    r = svc.handle_inbound("a@b.co", FIRST + " " + SECOND)
    again = svc.handle_inbound("a@b.co", "any update?", case_id=r.case_id)
    assert again.status == SUBMITTED and "already issued" in again.reply
    assert portal.calls == 1


def test_llm_outage_degrades_to_asking_the_customer(make_service):
    class DownLLM:
        name = "down"

        def extract(self, email_text, known):
            raise ExtractionError("provider unavailable")

    r = make_service(llm=DownLLM()).handle_inbound("a@b.co", FIRST)
    assert r.status == COLLECTING
    assert len(r.missing) == 6  # nothing extracted, so we ask for everything — and don't crash


def test_different_senders_get_different_cases(make_service):
    svc = make_service()
    a = svc.handle_inbound("a@b.co", FIRST)
    b = svc.handle_inbound("c@d.co", FIRST)
    assert a.case_id != b.case_id


# ---------------------------------------------------------------- API level
def test_api_end_to_end_through_real_mock_portal(client):
    r1 = client.post("/inbound", json={"sender_email": "owner@sweetcrumbs.com", "body": FIRST}).json()
    assert r1["status"] == "collecting" and r1["missing"] == ["annual_revenue"]

    r2 = client.post("/inbound", json={"sender_email": "owner@sweetcrumbs.com", "body": SECOND}).json()
    assert r2["status"] == "submitted"
    assert r2["quote"]["quote_id"].startswith("Q-") and r2["quote"]["premium"] > 0

    case = client.get(f"/cases/{r2['case_id']}").json()
    assert case["submission"]["business_name"] == "Sweet Crumbs Bakery"
    assert case["portal_runs"][0]["status"] == "ok"
    assert len(client.get("/cases").json()) == 1


def test_api_validation_and_not_found(client):
    assert client.post("/inbound", json={"sender_email": "not-an-email", "body": "hi"}).status_code == 422
    assert client.post("/inbound", json={"sender_email": "a@b.co", "body": ""}).status_code == 422
    assert client.get("/cases/does-not-exist").status_code == 404
    assert client.post("/inbound", json={"sender_email": "a@b.co", "body": "hi", "case_id": "nope"}).status_code == 404


def test_retry_endpoint_conflicts_on_incomplete_case(client):
    r = client.post("/inbound", json={"sender_email": "a@b.co", "body": "hello there"}).json()
    assert client.post(f"/cases/{r['case_id']}/retry-portal").status_code == 409


def test_retry_endpoint_recovers_failed_case(client, app):
    portal = FlakyPortal(fail_times=99)
    app.state.service.portal = portal
    r = client.post("/inbound", json={"sender_email": "a@b.co", "body": FIRST + " " + SECOND}).json()
    assert r["status"] == "portal_failed"
    portal.fail_times = 0
    assert client.post(f"/cases/{r['case_id']}/retry-portal").json()["status"] == "submitted"


def test_api_key_is_enforced_when_configured():
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(database_url="sqlite://", portal_driver="http", api_key="s3cret"))
    with TestClient(app) as c:
        body = {"sender_email": "a@b.co", "body": "hello"}
        assert c.post("/inbound", json=body).status_code == 401
        assert c.post("/inbound", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.post("/inbound", json=body, headers={"X-API-Key": "s3cret"}).status_code == 200
        assert c.get("/health").status_code == 200  # health stays open for load balancers
