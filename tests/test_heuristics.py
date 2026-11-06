import pytest

from app import heuristics


@pytest.mark.parametrize("text,expected", [
    ("We have 6 employees.", 6),
    ("Team of twelve.", 12),
    ("We're a 14 person practice", 14),
    ("a 25-employee firm", 25),
    ("5 attorneys and 4 support staff (9 total)", 9),
    ("we employ twenty-two staff", 22),
    ("Our revenue was $450,000 total", None),  # money must not be read as headcount
    ("no headcount mentioned", None),
])
def test_employees(text, expected):
    assert heuristics._employees(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("did about $450,000 in revenue last year", 450_000),
    ("Annual sales around $1.2M", 1_200_000),
    ("About 600k a year in revenue", 600_000),
    ("Revenue is about 4.5 million a year", 4_500_000),
    ("We did $8 million last year", 8_000_000),
    ("6 employees and 3 locations", None),  # bare numbers are not money
])
def test_revenue(text, expected):
    assert heuristics._revenue(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("based in Columbus, Ohio", "OH"),
    ("Austin, TX.", "TX"),
    ("Phoenix AZ.", "AZ"),
    ("Portland, Maine (not Oregon!)", "ME"),  # first-mentioned wins
    ("call me or email me", None),  # lowercase 'or'/'me' must not become OR/ME
    ("we are IN trouble", None),  # ambiguous bare codes are ignored
])
def test_state(text, expected):
    assert heuristics._state(text) == expected


def test_coverages_are_found_and_deduplicated():
    found = heuristics._coverages("GL + WC + property, and general liability again")
    assert set(found) == {"general_liability", "workers_comp", "commercial_property"}
    assert len(found) == len(set(found))


@pytest.mark.parametrize("text,expected", [
    ("I own Sweet Crumbs Bakery in Columbus", "Sweet Crumbs Bakery"),
    ("our company, Northwind Landscaping LLC, is based in Austin", "Northwind Landscaping LLC"),
    ("name: Tavola Group", "Tavola Group"),
    ("quote for Rivera Plumbing & Heating, Phoenix", "Rivera Plumbing & Heating"),
    ("just thinking about coffee", None),
])
def test_business_name(text, expected):
    assert heuristics._business_name(text) == expected


def test_extract_returns_full_shape():
    out = heuristics.extract("Hi")
    assert set(out) == {"business_name", "industry", "state", "employee_count", "annual_revenue", "coverage_types"}
    assert out["coverage_types"] == []
