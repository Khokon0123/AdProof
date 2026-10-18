"""Runtime settings from environment variables (python-dotenv loads .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

DEFAULT_ALLOWED_HOSTS = ("raw.githubusercontent.com",)
FIXTURE_BASE_DEFAULT = "https://raw.githubusercontent.com/Khokon0123/AdProof/main/data/fixtures"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    execution_mode: str = field(default_factory=lambda: os.environ.get("ADPROOF_EXECUTION_MODE", "LIVE").upper())
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    sentry_dsn: str = field(default_factory=lambda: os.environ.get("SENTRY_DSN", ""))
    sentry_environment: str = field(default_factory=lambda: os.environ.get("SENTRY_ENVIRONMENT", "local"))
    sentry_traces_sample_rate: float = field(default_factory=lambda: float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "1.0")))
    allowed_hosts: tuple[str, ...] = field(default_factory=lambda: tuple(
        h.strip().lower() for h in os.environ.get("ADPROOF_ALLOWED_HOSTS", ",".join(DEFAULT_ALLOWED_HOSTS)).split(",") if h.strip()))
    allow_public_hosts: bool = field(default_factory=lambda: os.environ.get("ADPROOF_ALLOW_PUBLIC_HOSTS", "0") == "1")
    fixture_base_url: str = field(default_factory=lambda: os.environ.get("ADPROOF_FIXTURE_BASE_URL", FIXTURE_BASE_DEFAULT).rstrip("/"))
    max_model_calls: int = field(default_factory=lambda: _int("ADPROOF_MAX_MODEL_CALLS", 20))
    audit_deadline_s: int = field(default_factory=lambda: _int("ADPROOF_AUDIT_DEADLINE_S", 180))
    inspection_cache: bool = field(default_factory=lambda: os.environ.get("ADPROOF_INSPECTION_CACHE", "1") == "1")
    state_db: str = field(default_factory=lambda: os.environ.get("ADPROOF_STATE_DB", "runtime/adproof_state.sqlite3"))


def get_settings() -> Settings:
    return Settings()
