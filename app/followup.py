"""Outbound email drafting.

Replies are templated on purpose: a customer-facing message should be predictable
and reviewable, and the LLM is only used where we need judgment (extraction).
"""
from __future__ import annotations

from .schemas import Submission

FIELD_QUESTIONS: dict[str, str] = {
    "business_name": "the legal name of your business",
    "industry": "what kind of business you run (for example restaurant, retail, construction, technology)",
    "state": "the US state your business is located in",
    "employee_count": "how many people work at the business in total, including owners",
    "annual_revenue": "your approximate annual revenue in US dollars",
    "coverage_types": "which coverages you are looking for (for example general liability, workers' comp, "
    "commercial property, professional liability, cyber, commercial auto, or a business owner's policy)",
}

COVERAGE_LABELS = {
    "general_liability": "General liability",
    "workers_comp": "Workers' compensation",
    "commercial_property": "Commercial property",
    "professional_liability": "Professional liability (E&O)",
    "cyber": "Cyber",
    "commercial_auto": "Commercial auto",
    "bop": "Business owner's policy",
}


def draft_followup(missing: list[str]) -> str:
    """Ask for exactly the fields we still need — nothing more."""
    lines = [
        "Hi,",
        "",
        "Thanks for reaching out. To put together your quote I just need a few more details:",
        "",
    ]
    lines += [f"  {i}. Please tell us {FIELD_QUESTIONS[f]}." for i, f in enumerate(missing, 1)]
    lines += ["", "Just reply to this email and we'll take it from there.", "", "Best,", "The Intake Team"]
    return "\n".join(lines)


def draft_confirmation(sub: Submission, quote_id: str, premium: float) -> str:
    coverages = ", ".join(COVERAGE_LABELS[c.value] for c in sub.coverage_types)
    name = sub.business_name or "your business"
    return "\n".join([
        "Hi,",
        "",
        f"Good news — we have an indicative quote for {name}.",
        "",
        f"  Coverage:  {coverages}",
        f"  Estimated annual premium:  ${premium:,.2f}",
        f"  Reference:  {quote_id}",
        "",
        "This is an estimate based on the details you sent; a licensed broker will confirm final terms.",
        "",
        "Best,",
        "The Intake Team",
    ])


def draft_holding_message() -> str:
    return "\n".join([
        "Hi,",
        "",
        "Thanks — we have everything we need. We hit a delay reaching the carrier and our team "
        "is finishing your quote manually. You'll hear from us shortly.",
        "",
        "Best,",
        "The Intake Team",
    ])
