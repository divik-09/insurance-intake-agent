"""Turn an inbound email into an updated `Submission`."""
from __future__ import annotations

from .llm import LLMClient
from .schemas import Submission, safe_submission


def merge(old: Submission, new: Submission) -> Submission:
    """Combine what we knew with what this email says.

    * A newly stated scalar value wins (the customer may be correcting themselves).
    * Coverage types are unioned, keeping first-seen order.
    """
    data = old.model_dump(mode="json")
    for field, value in new.model_dump(mode="json").items():
        if field == "coverage_types":
            data[field] = list(dict.fromkeys([*data[field], *value]))
        elif value is not None:
            data[field] = value
    return Submission.model_validate(data)


def extract_submission(llm: LLMClient, email_text: str, known: Submission | None = None) -> Submission:
    """Run the LLM, validate defensively, and merge into what we already knew."""
    known = known or Submission()
    raw = llm.extract(email_text, known.model_dump(mode="json"))
    return merge(known, safe_submission(raw))
