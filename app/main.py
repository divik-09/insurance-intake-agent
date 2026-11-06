"""FastAPI app: the inbound-email webhook, case endpoints, and the mock carrier portal.

Run with:   uvicorn app.main:create_app --factory --port 8000
"""
from __future__ import annotations

import dataclasses
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .db import make_engine, make_session_factory
from .llm import LLMClient, build_llm_from_settings
from .logging_conf import setup_logging
from .portal_app import build_portal_router
from .portal_client import PortalClient, build_portal_client
from .service import CaseNotFound, CaseNotReady, IntakeService


class InboundEmail(BaseModel):
    sender_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", examples=["owner@sweetcrumbs.com"])
    body: str = Field(min_length=1, max_length=20_000)
    case_id: str | None = Field(default=None, description="Optional: force a specific case")


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    portal: PortalClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    setup_logging()

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    service = IntakeService(
        session_factory,
        llm or build_llm_from_settings(settings),
        portal or build_portal_client(settings),
        max_attempts=settings.portal_max_attempts,
    )

    app = FastAPI(title="Insurance Intake Agent", version="1.0.0")
    app.state.settings = settings
    app.state.service = service

    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and not secrets.compare_digest(x_api_key or "", settings.api_key):
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")

    app.include_router(build_portal_router(lambda: settings.portal_failure_rate))

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "llm": service.llm.name,
            "portal_driver": getattr(service.portal, "driver", "unknown"),
        }

    # NOTE: these are sync `def` endpoints on purpose — FastAPI runs them in a thread pool,
    # so the blocking LLM / portal calls inside don't freeze the event loop (and the
    # in-process mock portal can answer while a request is waiting on it).
    @app.post("/inbound", dependencies=[Depends(require_api_key)])
    def inbound(email: InboundEmail) -> dict:
        try:
            result = service.handle_inbound(email.sender_email, email.body, email.case_id)
        except CaseNotFound:
            raise HTTPException(status_code=404, detail="case not found")
        return dataclasses.asdict(result)

    @app.get("/cases", dependencies=[Depends(require_api_key)])
    def list_cases(limit: int = 50) -> list[dict]:
        return service.list_cases(limit=min(max(limit, 1), 200))

    @app.get("/cases/{case_id}", dependencies=[Depends(require_api_key)])
    def get_case(case_id: str) -> dict:
        try:
            return service.get_case(case_id)
        except CaseNotFound:
            raise HTTPException(status_code=404, detail="case not found")

    @app.post("/cases/{case_id}/retry-portal", dependencies=[Depends(require_api_key)])
    def retry_portal(case_id: str) -> dict:
        try:
            return dataclasses.asdict(service.retry_portal(case_id))
        except CaseNotFound:
            raise HTTPException(status_code=404, detail="case not found")
        except CaseNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return app
