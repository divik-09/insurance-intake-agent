"""A *mock* carrier quote portal, served at /portal.

Real carrier portals are web forms behind logins with no API. This stand-in has the
same shape (HTML form -> submit -> quote page) so the automation code is realistic,
without touching any real carrier. It is clearly fake: premiums come from a toy formula.
"""
from __future__ import annotations

import html
import random
from typing import Callable
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse

from .schemas import US_STATES, Coverage, Industry

COVERAGE_BASE = {
    "general_liability": 900, "workers_comp": 1400, "commercial_property": 1100,
    "professional_liability": 1300, "cyber": 800, "commercial_auto": 1500, "bop": 1600,
}
INDUSTRY_FACTOR = {
    "restaurant_food": 1.3, "retail": 1.0, "construction_trades": 1.8, "professional_services": 0.9,
    "healthcare": 1.2, "technology": 0.85, "transportation": 2.0, "personal_services": 0.95,
    "manufacturing": 1.5, "other": 1.2,
}


def compute_premium(industry: str, coverages: list[str], employees: int, revenue: int) -> float:
    base = sum(COVERAGE_BASE[c] for c in coverages) * INDUSTRY_FACTOR[industry]
    size = 1 + employees / 50 + revenue / 5_000_000
    return round(base * size, 2)


def _page(body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Mock Carrier Portal</title></head>"
        f"<body><h1>Mock Carrier Portal</h1><p><em>Demo only — not a real insurer.</em></p>{body}</body></html>"
    )


def _form_html() -> str:
    industries = "".join(f"<option value='{i.value}'>{i.value}</option>" for i in Industry)
    states = "".join(f"<option value='{c}'>{n}</option>" for c, n in US_STATES.items())
    coverages = "".join(
        f"<label><input type='checkbox' id='cov-{c.value}' name='coverage' value='{c.value}'> {c.value}</label><br>"
        for c in Coverage
    )
    return _page(f"""
<form id="quote-form" method="post" action="/portal/quote">
  <p><label>Business name <input id="business_name" name="business_name" required></label></p>
  <p><label>Industry <select id="industry" name="industry">{industries}</select></label></p>
  <p><label>State <select id="state" name="state">{states}</select></label></p>
  <p><label>Employees <input id="employee_count" name="employee_count" type="number" min="0" required></label></p>
  <p><label>Annual revenue (USD) <input id="annual_revenue" name="annual_revenue" type="number" min="0" required></label></p>
  <fieldset><legend>Coverage</legend>{coverages}</fieldset>
  <p><label>Contact email <input id="contact_email" name="contact_email" type="email" required></label></p>
  <button id="submit" type="submit">Get quote</button>
</form>""")


def build_portal_router(get_failure_rate: Callable[[], float] = lambda: 0.0) -> APIRouter:
    router = APIRouter(prefix="/portal", tags=["mock-portal"])

    @router.get("/quote", response_class=HTMLResponse)
    def quote_form() -> str:
        return _form_html()

    @router.post("/quote", response_class=HTMLResponse)
    def submit_quote(
        business_name: str = Form(...),
        industry: str = Form(...),
        state: str = Form(...),
        employee_count: int = Form(..., ge=0),
        annual_revenue: int = Form(..., ge=0),
        contact_email: str = Form(...),
        coverage: list[str] = Form(default=[]),
    ) -> str:
        # optional chaos: lets you watch the retry logic work
        if random.random() < get_failure_rate():
            raise HTTPException(status_code=503, detail="carrier portal temporarily unavailable")
        if industry not in INDUSTRY_FACTOR:
            raise HTTPException(status_code=422, detail=f"unknown industry {industry!r}")
        if state not in US_STATES:
            raise HTTPException(status_code=422, detail=f"unknown state {state!r}")
        if not coverage or any(c not in COVERAGE_BASE for c in coverage):
            raise HTTPException(status_code=422, detail="select at least one valid coverage")

        premium = compute_premium(industry, coverage, employee_count, annual_revenue)
        quote_id = "Q-" + uuid4().hex[:8].upper()
        return _page(
            f"<h2>Indicative quote for {html.escape(business_name)}</h2>"
            f"<div>Quote ID: <span id='quote-id'>{quote_id}</span></div>"
            f"<div>Estimated annual premium: <span id='premium' data-value='{premium:.2f}'>${premium:,.2f}</span></div>"
        )

    return router
