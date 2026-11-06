"""The heart of the system: one inbound email in -> case updated -> reply out.

Flow for every email:
  1. find (or open) the case for this sender and store the inbound message
  2. ask the LLM what the email says, validate it, merge it into the case
  3. still missing fields?  -> store + return a follow-up email asking for exactly those
     complete?             -> submit to the carrier portal (with retries) -> store the quote

Design notes worth knowing for an interview:
  * No database transaction is held open while we wait on the LLM or the portal.
  * An LLM outage degrades gracefully: we keep what we knew and ask the customer again.
  * Portal failures are recorded (PortalRun) and the case moves to `portal_failed`
    so it can be retried later instead of being silently lost.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .db import COLLECTING, PORTAL_FAILED, READY, SUBMITTED, Case, Message, PortalRun
from .extraction import extract_submission
from .followup import draft_confirmation, draft_followup, draft_holding_message
from .llm import ExtractionError, LLMClient
from .portal_client import PortalClient, PortalError
from .retry import RetryExhausted, retry_call
from .schemas import Submission, safe_submission

log = logging.getLogger("intake.service")

OPEN_STATUSES = (COLLECTING, PORTAL_FAILED)


class CaseNotFound(LookupError):
    pass


class CaseNotReady(ValueError):
    pass


@dataclass
class InboundResult:
    case_id: str
    status: str
    submission: dict[str, Any]
    missing: list[str]
    reply: str
    quote: dict[str, Any] | None = None


class IntakeService:
    def __init__(
        self,
        session_factory: sessionmaker,
        llm: LLMClient,
        portal: PortalClient,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._sf = session_factory
        self.llm = llm
        self.portal = portal
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._sleep = sleep

    # ------------------------------------------------------------------ public
    def handle_inbound(self, sender_email: str, body: str, case_id: str | None = None) -> InboundResult:
        sender = sender_email.strip().lower()

        with self._sf() as s:
            case = self._resolve_case(s, sender, case_id)
            s.add(Message(case_id=case.id, direction="inbound", body=body))
            cid = case.id

            if case.status == SUBMITTED:  # never submit the same case twice
                quote = self._latest_quote(case)
                reply = (
                    f"Hi,\n\nWe already issued quote {quote['quote_id']} for this request. "
                    "Reply here if any details have changed.\n\nBest,\nThe Intake Team"
                    if quote else "Hi,\n\nWe already have this request and are working on it.\n\nBest,\nThe Intake Team"
                )
                s.add(Message(case_id=cid, direction="outbound", body=reply))
                s.commit()
                return InboundResult(cid, case.status, case.submission, [], reply, quote)

            known = safe_submission(case.submission)
            s.commit()  # release the transaction before the slow LLM call

        try:
            updated = extract_submission(self.llm, body, known)
        except ExtractionError as exc:
            log.error("extraction failed; keeping previous state", extra={"case_id": cid, "error": str(exc)})
            updated = known

        with self._sf() as s:
            case = s.get(Case, cid)
            case.submission = updated.model_dump(mode="json")
            missing = updated.missing_fields()
            log.info("case updated", extra={"case_id": cid, "missing": missing})
            if missing:
                case.status = COLLECTING
                reply = draft_followup(missing)
                s.add(Message(case_id=cid, direction="outbound", body=reply))
                s.commit()
                return InboundResult(cid, case.status, case.submission, missing, reply)
            case.status = READY
            s.commit()

        return self._submit_to_portal(cid)

    def retry_portal(self, case_id: str) -> InboundResult:
        """Re-run the portal step for a case that is complete but not yet quoted."""
        with self._sf() as s:
            case = s.get(Case, case_id)
            if case is None:
                raise CaseNotFound(case_id)
            if case.status == SUBMITTED:
                return InboundResult(case.id, case.status, case.submission, [], "", self._latest_quote(case))
            sub = safe_submission(case.submission)
            if not sub.is_complete():
                raise CaseNotReady(f"case is missing: {sub.missing_fields()}")
        return self._submit_to_portal(case_id)

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self._sf() as s:
            case = s.get(Case, case_id)
            if case is None:
                raise CaseNotFound(case_id)
            return self._serialize(case, detail=True)

    def list_cases(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._sf() as s:
            rows = s.scalars(select(Case).order_by(Case.created_at.desc()).limit(limit)).all()
            return [self._serialize(c) for c in rows]

    # ----------------------------------------------------------------- private
    def _resolve_case(self, s: Session, sender: str, case_id: str | None) -> Case:
        if case_id:
            case = s.get(Case, case_id)
            if case is None:
                raise CaseNotFound(case_id)
            return case
        # continue the sender's open conversation if there is one
        case = s.scalars(
            select(Case)
            .where(Case.contact_email == sender, Case.status.in_(OPEN_STATUSES))
            .order_by(Case.created_at.desc())
        ).first()
        if case is None:
            case = Case(contact_email=sender, status=COLLECTING, submission={})
            s.add(case)
            s.flush()  # assigns the id
            log.info("case opened", extra={"case_id": case.id})
        return case

    def _submit_to_portal(self, cid: str) -> InboundResult:
        with self._sf() as s:
            case = s.get(Case, cid)
            sub: Submission = safe_submission(case.submission)
            email = case.contact_email
        driver = getattr(self.portal, "driver", "")

        try:
            quote, attempts = retry_call(
                lambda: self.portal.submit(sub, email),
                attempts=self.max_attempts,
                base_delay=self.base_delay,
                retry_on=(PortalError,),
                sleep=self._sleep,
            )
        except RetryExhausted as exc:
            log.error("portal failed", extra={"case_id": cid, "attempts": exc.attempts})
            with self._sf() as s:
                case = s.get(Case, cid)
                case.status = PORTAL_FAILED
                reply = draft_holding_message()
                s.add(PortalRun(case_id=cid, status="failed", attempts=exc.attempts, driver=driver,
                                error=str(exc.last_error)))
                s.add(Message(case_id=cid, direction="outbound", body=reply))
                s.commit()
                return InboundResult(cid, case.status, case.submission, [], reply)

        quote_dict = {"quote_id": quote.quote_id, "premium": quote.premium}
        with self._sf() as s:
            case = s.get(Case, cid)
            case.status = SUBMITTED
            reply = draft_confirmation(sub, quote.quote_id, quote.premium)
            s.add(PortalRun(case_id=cid, status="ok", attempts=attempts, driver=driver, quote=quote_dict))
            s.add(Message(case_id=cid, direction="outbound", body=reply))
            s.commit()
            log.info("quote received", extra={"case_id": cid, "attempts": attempts, **quote_dict})
            return InboundResult(cid, case.status, case.submission, [], reply, quote_dict)

    @staticmethod
    def _latest_quote(case: Case) -> dict[str, Any] | None:
        for run in reversed(case.portal_runs):
            if run.status == "ok":
                return run.quote
        return None

    def _serialize(self, case: Case, detail: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": case.id,
            "contact_email": case.contact_email,
            "status": case.status,
            "submission": case.submission,
            "missing": safe_submission(case.submission).missing_fields(),
            "quote": self._latest_quote(case),
            "created_at": case.created_at.isoformat(),
            "updated_at": case.updated_at.isoformat(),
        }
        if detail:
            out["messages"] = [
                {"direction": m.direction, "body": m.body, "created_at": m.created_at.isoformat()}
                for m in case.messages
            ]
            out["portal_runs"] = [
                {"status": r.status, "attempts": r.attempts, "driver": r.driver,
                 "quote": r.quote, "error": r.error, "created_at": r.created_at.isoformat()}
                for r in case.portal_runs
            ]
        return out
