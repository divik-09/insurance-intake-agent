"""Domain schema for a commercial-insurance quote submission.

The LLM is *not trusted* to return clean data, so everything it produces goes
through these models. `safe_submission` validates field by field so one bad
value (say, state="Narnia") drops that field instead of losing the whole email.
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

log = logging.getLogger("intake.schemas")


class Industry(str, Enum):
    restaurant_food = "restaurant_food"
    retail = "retail"
    construction_trades = "construction_trades"
    professional_services = "professional_services"
    healthcare = "healthcare"
    technology = "technology"
    transportation = "transportation"
    personal_services = "personal_services"
    manufacturing = "manufacturing"
    other = "other"


class Coverage(str, Enum):
    general_liability = "general_liability"
    workers_comp = "workers_comp"
    commercial_property = "commercial_property"
    professional_liability = "professional_liability"
    cyber = "cyber"
    commercial_auto = "commercial_auto"
    bop = "bop"  # business owner's policy


US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}
STATE_NAME_TO_CODE: dict[str, str] = {v.lower(): k for k, v in US_STATES.items()}

# Fields that must be present before we can submit to a carrier portal.
REQUIRED_FIELDS: tuple[str, ...] = (
    "business_name",
    "industry",
    "state",
    "employee_count",
    "annual_revenue",
    "coverage_types",
)


def _to_int(value: Any) -> Any:
    """Accept 1200000, '1,200,000', 1200000.0 — reject anything else."""
    if value is None or isinstance(value, bool):
        return None if value is None else value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        if re.fullmatch(r"\d+", cleaned):
            return int(cleaned)
    return value


class Submission(BaseModel):
    """What we know so far about a business that wants a quote."""

    business_name: str | None = None
    industry: Industry | None = None
    state: str | None = None
    employee_count: int | None = Field(default=None, ge=0, le=100_000)
    annual_revenue: int | None = Field(default=None, ge=0)
    coverage_types: list[Coverage] = Field(default_factory=list)

    @field_validator("business_name", mode="before")
    @classmethod
    def _clean_name(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("state", mode="before")
    @classmethod
    def _norm_state(cls, v: Any) -> Any:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("state must be a string")
        s = v.strip()
        if s.upper() in US_STATES:
            return s.upper()
        code = STATE_NAME_TO_CODE.get(s.lower())
        if code:
            return code
        raise ValueError(f"unknown US state: {v!r}")

    @field_validator("employee_count", "annual_revenue", mode="before")
    @classmethod
    def _coerce_int(cls, v: Any) -> Any:
        return _to_int(v)

    def missing_fields(self) -> list[str]:
        missing = []
        for name in REQUIRED_FIELDS:
            value = getattr(self, name)
            if value is None or value == []:
                missing.append(name)
        return missing

    def is_complete(self) -> bool:
        return not self.missing_fields()


def safe_submission(raw: dict[str, Any] | None) -> Submission:
    """Build a Submission from untrusted data, dropping only the invalid fields."""
    raw = raw or {}
    try:
        return Submission.model_validate(raw)
    except ValidationError:
        pass
    good: dict[str, Any] = {}
    for key in Submission.model_fields:
        if key not in raw:
            continue
        try:
            Submission.model_validate({key: raw[key]})
        except ValidationError as exc:
            log.warning("dropping invalid field", extra={"field": key, "error": str(exc.errors()[0]["msg"])})
        else:
            good[key] = raw[key]
    return Submission.model_validate(good)
