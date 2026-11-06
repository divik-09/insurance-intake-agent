import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.portal_app import compute_premium
from app.portal_client import HttpPortalClient, PortalError, parse_quote_page
from app.schemas import Submission


def complete_submission() -> Submission:
    return Submission(
        business_name="Sweet Crumbs Bakery", industry="restaurant_food", state="OH",
        employee_count=6, annual_revenue=450_000, coverage_types=["general_liability", "workers_comp"],
    )


def test_portal_serves_a_form_with_the_expected_fields(client):
    html = client.get("/portal/quote").text
    for field_id in ("business_name", "industry", "state", "employee_count", "annual_revenue",
                     "contact_email", "cov-general_liability", "submit"):
        assert f'id="{field_id}"' in html or f"id='{field_id}'" in html


def test_http_driver_submits_form_and_reads_quote(client):
    sub = complete_submission()
    quote = HttpPortalClient(client=client).submit(sub, "owner@example.com")
    assert quote.quote_id.startswith("Q-")
    expected = compute_premium("restaurant_food", ["general_liability", "workers_comp"], 6, 450_000)
    assert quote.premium == expected


def test_driver_refuses_incomplete_submission(client):
    with pytest.raises(ValueError):
        HttpPortalClient(client=client).submit(Submission(business_name="x"), "a@b.co")


def test_portal_rejects_invalid_form_data(client):
    resp = client.post("/portal/quote", data={
        "business_name": "X", "industry": "retail", "state": "ZZ", "employee_count": "3",
        "annual_revenue": "100", "contact_email": "a@b.co", "coverage": ["bop"],
    })
    assert resp.status_code == 422


def test_portal_5xx_becomes_retryable_portal_error():
    app = create_app(Settings(database_url="sqlite://", portal_driver="http", portal_failure_rate=1.0))
    with TestClient(app) as c:
        with pytest.raises(PortalError):
            HttpPortalClient(client=c).submit(complete_submission(), "owner@example.com")


def test_parse_quote_page_rejects_garbage():
    with pytest.raises(PortalError):
        parse_quote_page("<html>nothing here</html>")


def test_premium_increases_with_risk_and_size():
    low = compute_premium("technology", ["cyber"], 3, 100_000)
    high = compute_premium("transportation", ["cyber"], 30, 5_000_000)
    assert high > low
