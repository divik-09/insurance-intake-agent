from app.extraction import extract_submission, merge
from app.followup import draft_confirmation, draft_followup
from app.llm import HeuristicClient
from app.schemas import Coverage, Submission


def test_merge_new_value_overrides_and_none_does_not_erase():
    old = Submission(business_name="Acme", state="OH", employee_count=5)
    new = Submission(state="TX", annual_revenue=100_000)  # a correction + a new fact
    m = merge(old, new)
    assert m.business_name == "Acme"      # untouched: new had None
    assert m.state == "TX"                # corrected
    assert m.employee_count == 5
    assert m.annual_revenue == 100_000


def test_merge_unions_coverages_in_first_seen_order():
    old = Submission(coverage_types=[Coverage.cyber, Coverage.bop])
    new = Submission(coverage_types=[Coverage.bop, Coverage.workers_comp])
    assert merge(old, new).coverage_types == [Coverage.cyber, Coverage.bop, Coverage.workers_comp]


def test_extract_submission_merges_across_turns():
    llm = HeuristicClient()
    first = extract_submission(llm, "I own Sweet Crumbs Bakery in Ohio. 6 employees. Need general liability.")
    assert first.annual_revenue is None
    second = extract_submission(llm, "Sorry! We did about $450,000 last year.", first)
    assert second.annual_revenue == 450_000
    assert second.business_name == "Sweet Crumbs Bakery"  # kept from turn one


def test_followup_asks_only_for_missing_fields():
    text = draft_followup(["annual_revenue", "state"])
    assert "annual revenue" in text and "state" in text
    assert "employees" not in text and "business name" not in text.lower()


def test_confirmation_contains_quote_details():
    sub = Submission(business_name="Acme", coverage_types=[Coverage.cyber, Coverage.bop])
    text = draft_confirmation(sub, "Q-ABC123", 2345.6)
    assert "Q-ABC123" in text and "$2,345.60" in text and "Cyber" in text
