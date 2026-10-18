"""Builds the model/fetcher pair for the configured execution mode. LIVE never falls back to MOCK."""
from __future__ import annotations

from .domain.models import ExecutionMode
from .infrastructure.safe_http import SafeFetcher
from .infrastructure.settings import Settings
from .model_client import GeminiClient, ModelClient, ModelError


class UnavailableModel:
    """LIVE without a working key: every call fails honestly (no fabricated output)."""

    def __init__(self, reason: str, name: str):
        self.reason, self.name = reason, name

    async def generate(self, **_):
        raise ModelError("MISSING_API_KEY", self.reason)


def execution_mode(s: Settings) -> ExecutionMode:
    return ExecutionMode.MOCK if s.execution_mode == "MOCK" else ExecutionMode.LIVE


def build_model(s: Settings) -> ModelClient:
    if execution_mode(s) == ExecutionMode.MOCK:
        from .mock_model import build_mock_model
        return build_mock_model()
    try:
        return GeminiClient(s.gemini_api_key, s.gemini_model)
    except ModelError as exc:
        return UnavailableModel(exc.message, s.gemini_model)


def build_fetcher(s: Settings):
    if execution_mode(s) == ExecutionMode.MOCK:
        from .demo_inputs import local_fixture_fetcher
        return local_fixture_fetcher()
    return SafeFetcher(s.allowed_hosts, s.allow_public_hosts)
