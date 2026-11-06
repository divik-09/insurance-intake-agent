"""Runtime configuration, read from environment variables (and a local .env if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-4o-mini",
    "heuristic": "regex-baseline",
}


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "heuristic"
    llm_model: str = "regex-baseline"
    database_url: str = "sqlite:///./intake.db"
    portal_base_url: str = "http://127.0.0.1:8000"
    portal_driver: str = "auto"  # auto | http | playwright
    portal_failure_rate: float = 0.0
    portal_max_attempts: int = 3
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.environ.get("LLM_PROVIDER", "heuristic").lower()
        return cls(
            llm_provider=provider,
            llm_model=os.environ.get("LLM_MODEL", DEFAULT_MODELS.get(provider, "")),
            database_url=os.environ.get("DATABASE_URL", cls.database_url),
            portal_base_url=os.environ.get("PORTAL_BASE_URL", cls.portal_base_url),
            portal_driver=os.environ.get("PORTAL_DRIVER", cls.portal_driver).lower(),
            portal_failure_rate=float(os.environ.get("PORTAL_FAILURE_RATE", "0")),
            portal_max_attempts=int(os.environ.get("PORTAL_MAX_ATTEMPTS", "3")),
            api_key=os.environ.get("API_KEY") or None,
        )
