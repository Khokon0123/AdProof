"""Shared, bounded async model adapter.

`GeminiClient` calls Gemini with the official google-genai SDK and validates the
JSON against a Pydantic schema. `ScriptedModel` is the MOCK/test double. Both
charge every call (including the one correction retry) to a shared CallBudget.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .infrastructure import telemetry

T = TypeVar("T", bound=BaseModel)


class ModelError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


@dataclass
class CallBudget:
    """Shared ledger for one audit batch. Reserve before every call; never exceed the cap."""
    limit: int
    used: int = 0
    log: list[str] = field(default_factory=list)

    def reserve(self, what: str) -> None:
        if self.used >= self.limit:
            raise ModelError("MODEL_BUDGET_EXHAUSTED", f"Model call budget of {self.limit} is used up.")
        self.used += 1
        self.log.append(what)


class ModelClient(Protocol):
    name: str

    async def generate(self, *, task: str, prompt: str, schema: type[T], budget: CallBudget,
                       deadline: float, image: Optional[bytes] = None) -> T: ...


def _remaining(deadline: float, cap: float) -> float:
    left = deadline - time.time()
    if left <= 1.0:
        raise ModelError("DEADLINE_EXCEEDED", "No time left for the model call.")
    return min(cap, left)


class GeminiClient:
    def __init__(self, api_key: str, model: str, call_timeout_s: float = 25.0):
        if not api_key:
            raise ModelError("MISSING_API_KEY", "GEMINI_API_KEY is not set; LIVE model calls are unavailable.")
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.name = model
        self.call_timeout_s = call_timeout_s

    async def _call(self, prompt: str, schema: type[T], image: Optional[bytes], timeout: float) -> str:
        from google.genai import types

        contents: list = []
        if image is not None:
            contents.append(types.Part.from_bytes(data=image, mime_type="image/png"))
        contents.append(prompt)
        config = types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json", response_schema=schema,
        )
        resp = await asyncio.wait_for(
            self._client.aio.models.generate_content(model=self.name, contents=contents, config=config),
            timeout=timeout)
        return resp.text or ""

    async def generate(self, *, task, prompt, schema, budget, deadline, image=None):
        last_err: Exception | None = None
        for attempt in (1, 2):  # one bounded correction/transient retry, inside the same deadline
            budget.reserve(f"{task}#{attempt}")
            with telemetry.span("gen_ai.generate", f"gemini.{task}", model=self.name, attempt=attempt):
                try:
                    raw = await self._call(prompt if attempt == 1 else
                                           prompt + "\n\nYour previous reply was not valid JSON for the schema. "
                                           "Reply with JSON only.", schema, image,
                                           _remaining(deadline, self.call_timeout_s))
                    return schema.model_validate(json.loads(raw))
                except (json.JSONDecodeError, ValidationError) as exc:
                    last_err = ModelError("MALFORMED_MODEL_OUTPUT", f"{task}: output failed schema validation.")
                except asyncio.TimeoutError:
                    last_err = ModelError("MODEL_TIMEOUT", f"{task}: model call timed out.", retryable=True)
                except ModelError:
                    raise
                except Exception as exc:  # SDK/auth/network errors
                    msg = str(exc)
                    if any(s in msg for s in ("API key", "401", "403", "PERMISSION", "not found", "404")):
                        raise ModelError("MODEL_AUTH_OR_MODEL_ERROR", f"{task}: {type(exc).__name__}: {msg[:160]}") from exc
                    last_err = ModelError("MODEL_ERROR", f"{task}: {type(exc).__name__}", retryable=True)
            telemetry.event("retry_scheduled", stage=task, attempt=attempt, error_code=getattr(last_err, "code", ""))
            await asyncio.sleep(0.4)
        assert last_err is not None
        raise last_err


class ScriptedModel:
    """Deterministic stand-in used ONLY in MOCK mode and tests. Results are labeled MOCK upstream."""

    def __init__(self, handlers: dict[str, Callable[[str, Optional[bytes]], dict]], name: str = "mock-model"):
        self.handlers, self.name = handlers, name
        self.calls: list[str] = []

    async def generate(self, *, task, prompt, schema, budget, deadline, image=None):
        budget.reserve(task)
        self.calls.append(task)
        if task not in self.handlers:
            raise ModelError("MODEL_ERROR", f"No scripted response for task '{task}'.")
        out = self.handlers[task](prompt, image)
        if isinstance(out, Exception):
            raise out
        return schema.model_validate(out)
