import pytest
from pydantic import ValidationError

from app.schemas import Coverage, Industry, Submission, safe_submission


def test_state_names_and_codes_normalize():
    assert Submission(state="Ohio").state == "OH"
    assert Submission(state="tx").state == "TX"
    assert Submission(state="New York").state == "NY"


def test_unknown_state_rejected():
    with pytest.raises(ValidationError):
        Submission(state="Narnia")


def test_numbers_coerced_from_strings():
    s = Submission(employee_count="12", annual_revenue="1,200,000")
    assert (s.employee_count, s.annual_revenue) == (12, 1_200_000)


def test_missing_fields_and_completeness():
    s = Submission(business_name="Acme", industry=Industry.retail)
    assert s.missing_fields() == ["state", "employee_count", "annual_revenue", "coverage_types"]
    assert not s.is_complete()
    full = Submission(
        business_name="Acme", industry="retail", state="OH", employee_count=3,
        annual_revenue=100_000, coverage_types=[Coverage.bop],
    )
    assert full.is_complete()


def test_zero_employees_is_a_value_not_missing():
    s = Submission(employee_count=0)
    assert "employee_count" not in s.missing_fields()


def test_safe_submission_drops_only_invalid_fields():
    s = safe_submission({"business_name": "Acme", "state": "Narnia", "employee_count": 5, "industry": "spaceships"})
    assert s.business_name == "Acme"
    assert s.employee_count == 5
    assert s.state is None
    assert s.industry is None


def test_safe_submission_handles_none_and_garbage():
    assert safe_submission(None).missing_fields()  # all missing
    assert safe_submission({"unknown_key": 1}).business_name is None
