"""Regex/keyword extractor. A deterministic *baseline* that needs no API key.

It exists for three reasons: (1) tests and CI run offline, (2) it gives the eval
harness a floor to compare an LLM against, and (3) it is a handy fallback if the
LLM provider is down. It is deliberately simple and will miss tricky emails —
that is the point of having an eval.
"""
from __future__ import annotations

import re
from typing import Any

from .schemas import STATE_NAME_TO_CODE, US_STATES

# ---------------------------------------------------------------- numbers
_UNITS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
          "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
          "eighteen", "nineteen"]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_WORD_VALUES = {w: i + 1 for i, w in enumerate(_UNITS)}
_WORD_VALUES.update({w: (i + 2) * 10 for i, w in enumerate(_TENS)})

_NUM_WORD = (
    rf"(?:(?:{'|'.join(_TENS)})(?:[- ](?:{'|'.join(_UNITS[:9])}))?"
    rf"|{'|'.join(sorted(_UNITS, key=len, reverse=True))})"
)
_NUM = rf"(?:\d[\d,]*|{_NUM_WORD})"


def _to_number(token: str) -> int | None:
    t = token.strip().lower().replace(",", "")
    if t.isdigit():
        return int(t)
    parts = re.split(r"[- ]", t)
    try:
        return sum(_WORD_VALUES[p] for p in parts if p)
    except KeyError:
        return None


# ---------------------------------------------------------------- employees
_EMP_PATTERNS = [
    rf"(?<![$\d,.])\b({_NUM})\s*(?:total|in total)\b",
    rf"\bteam of ({_NUM})\b",
    rf"\b({_NUM})[- ](?:person|employee|member)\b",
    rf"\b({_NUM})\s+(?:full[- ]time\s+|part[- ]time\s+)?(?:employees|staff|people|workers|team members|associates)\b",
    rf"\b({_NUM})\s+(?:\w+\s+)?staff\b",
]


def _employees(text: str) -> int | None:
    for pat in _EMP_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            n = _to_number(m.group(1))
            if n is not None and 0 <= n <= 5000:
                return n
    return None


# ---------------------------------------------------------------- revenue
_MONEY = re.compile(
    r"(?P<dollar>\$)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<suffix>k|mm|m|million|thousand)?\b",
    re.I,
)
_REV_WORDS = re.compile(
    r"\b(?:revenue|sales|gross|turnover|income|last year|a year|per year|annually|did|made|generated|grossed|earn\w*)\b",
    re.I,
)
_MULT = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "mm": 1_000_000, "million": 1_000_000}


def _revenue(text: str) -> int | None:
    keywords = [m.span() for m in _REV_WORDS.finditer(text)]
    best: tuple[int, int] | None = None  # (distance, value)
    for m in _MONEY.finditer(text):
        suffix = (m.group("suffix") or "").lower()
        if not m.group("dollar") and not suffix:
            continue  # a bare number like "12" is not money
        try:
            value = int(round(float(m.group("num").replace(",", "")) * _MULT.get(suffix, 1)))
        except ValueError:
            continue
        if not keywords:
            continue
        dist = min(
            0 if (ks <= m.start() < ke) else min(abs(m.start() - ke), abs(ks - m.end()))
            for ks, ke in keywords
        )
        if dist <= 60 and (best is None or dist < best[0]):
            best = (dist, value)
    return best[1] if best else None


# ---------------------------------------------------------------- state
_AMBIGUOUS_CODES = {"OR", "IN", "ME", "OK", "HI"}
_STATE_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(n) for n in STATE_NAME_TO_CODE), key=len, reverse=True)) + r")\b",
    re.I,
)
_CODE_AFTER_COMMA_RE = re.compile(r",\s*([A-Z]{2})\b")
_CODE_BARE_RE = re.compile(r"\b([A-Z]{2})\b")


def _state(text: str) -> str | None:
    hits: list[tuple[int, str]] = []
    for m in _STATE_NAME_RE.finditer(text):
        hits.append((m.start(), STATE_NAME_TO_CODE[m.group(1).lower()]))
    for m in _CODE_AFTER_COMMA_RE.finditer(text):
        if m.group(1) in US_STATES:
            hits.append((m.start(1), m.group(1)))
    for m in _CODE_BARE_RE.finditer(text):
        code = m.group(1)
        if code in US_STATES and code not in _AMBIGUOUS_CODES:
            hits.append((m.start(1), code))
    return min(hits)[1] if hits else None


# ---------------------------------------------------------------- industry
_INDUSTRY_KEYWORDS: list[tuple[str, str]] = [
    ("restaurant_food", r"bakery|restaurant|cafe|coffee shop|catering|food truck|pizz|diner|\bbar\b|brewery"),
    ("healthcare", r"dental|dentist|clinic|medical|physician|chiropract|therapy practice|pharmacy"),
    ("technology", r"software|saas|\bapp\b|analytics|it consult|web dev|data (?:science|company)|startup"),
    ("transportation", r"trucking|freight|delivery|logistics|courier|\bfleet\b"),
    ("construction_trades", r"plumb|landscap|construction|builders|roofing|electric(?:al|ian)|hvac|contractor|painting"),
    ("personal_services", r"salon|\bhair\b|stylist|barber|\bspa\b|\bgym\b|fitness|nail"),
    ("manufacturing", r"candles|handmade|manufactur|factory|workshop|fabricat"),
    ("retail", r"retail|\bstores?\b|boutique|\bshop\b|e-?commerce"),
    ("professional_services", r"law firm|\blaw\b|attorney|accounting|\bcpa\b|consult|agency|architect|bookkeep"),
    ("other", r"auto repair|mechanic|garage|body shop"),
]


def _industry(text: str) -> str | None:
    for industry, pattern in _INDUSTRY_KEYWORDS:
        if re.search(pattern, text, re.I):
            return industry
    return None


# ---------------------------------------------------------------- business name
_TOK = r"(?:(?:Inc|Co|Corp|Ltd)\.|[A-Z][\w'’-]*|&)"
_CAPSEQ = rf"[A-Z][\w'’-]*(?:\s+{_TOK})*"
_NAME_KEYWORDS = (
    "Bakery|Plumbing|Heating|Dental|Group|Builders|Repair|Analytics|Freight|"
    "Associates|Law|Cafe|Restaurant|Landscaping|Consulting|Digital|Retail"
)
_NAME_PATTERNS = [
    rf"(?i:called|named|name:|name is)\s+({_CAPSEQ})",
    rf"(?i:owner of|\bown|\brun|operate|founder of|\bfrom)\s+({_CAPSEQ})",
    rf"((?:{_TOK}\s+){{1,5}}(?:LLC|Inc\.?|Co\.?|Corp\.?|Ltd\.?))",
    rf"((?:{_TOK}\s+){{1,4}}(?:{_NAME_KEYWORDS}))\b",
]


def _clean_name(name: str) -> str:
    name = name.strip().rstrip(",;:")
    if name.endswith(".") and not re.search(r"\b(?:Inc|Co|Corp|Ltd)\.$", name):
        name = name[:-1]
    return name


def _business_name(text: str) -> str | None:
    for pat in _NAME_PATTERNS:
        m = re.search(pat, text)
        if m:
            name = _clean_name(m.group(1))
            if len(name) >= 3:
                return name
    return None


# ---------------------------------------------------------------- coverage
_COVERAGE_PATTERNS: list[tuple[str, str]] = [
    ("general_liability", r"general liability|\bGL\b"),
    ("workers_comp", r"workers'? ?comp|workers['’]? compensation|\bWC\b"),
    ("commercial_property", r"commercial property|\bproperty (?:coverage|insurance)|\+ property|and property|\bproperty\b"),
    ("professional_liability", r"professional liability|errors (?:and|&) omissions|\bE&O\b|\bE and O\b"),
    ("cyber", r"cyber"),
    ("commercial_auto", r"commercial auto|business auto|commercial vehicle"),
    ("bop", r"\bBOP\b|business ?owner'?s? policy"),
]


def _coverages(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for cov, pat in _COVERAGE_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            found.append((m.start(), cov))
    return [c for _, c in sorted(found)]


# ---------------------------------------------------------------- public API
def extract(text: str) -> dict[str, Any]:
    """Return a dict shaped like `Submission` with None / [] for anything not found."""
    return {
        "business_name": _business_name(text),
        "industry": _industry(text),
        "state": _state(text),
        "employee_count": _employees(text),
        "annual_revenue": _revenue(text),
        "coverage_types": _coverages(text),
    }
