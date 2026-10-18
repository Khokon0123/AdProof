"""Gemini adapter and Sentry telemetry, exercised offline (no network, no real keys)."""
import asyncio
import json
import time
from pathlib import Path

import pytest

import tests.helpers  # noqa: F401
from adproof.inspector.inspector import InspectorOutput
from adproof.model_client import CallBudget, GeminiClient, ModelError


class _Resp:
    def __init__(self, text):
        self.text = text


def _client_with(replies):
    c = GeminiClient(api_key="offline-test-key", model="gemini-test")
    seen = []

    async def fake_generate_content(model, contents, config):
        seen.append((model, contents, config))
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Resp(r)

    c._client.aio.models.generate_content = fake_generate_content
    return c, seen


def test_gemini_adapter_validates_and_charges_budget():
    good = json.dumps({"readable": True, "items": [{"kind": "visible_text", "text": "Only $49"}]})
    c, seen = _client_with([good])
    b = CallBudget(limit=3)
    out = asyncio.run(c.generate(task="inspect", prompt="p", schema=InspectorOutput, budget=b,
                                 deadline=time.time() + 30, image=b"\x89PNG fake"))
    assert out.items[0].text == "Only $49" and b.used == 1
    model, contents, config = seen[0]
    assert model == "gemini-test" and config.response_mime_type == "application/json" and config.temperature == 0


def test_gemini_adapter_one_correction_then_typed_error():
    c, seen = _client_with(["not json", "{\"still\": \"wrong\"}"])
    b = CallBudget(limit=5)
    with pytest.raises(ModelError) as e:
        asyncio.run(c.generate(task="inspect", prompt="p", schema=InspectorOutput, budget=b, deadline=time.time() + 30))
    assert e.value.code == "MALFORMED_MODEL_OUTPUT" and b.used == 2 and len(seen) == 2


def test_gemini_auth_error_is_not_retried():
    c, seen = _client_with([RuntimeError("403 PERMISSION_DENIED: API key not valid")])
    with pytest.raises(ModelError) as e:
        asyncio.run(c.generate(task="inspect", prompt="p", schema=InspectorOutput, budget=CallBudget(limit=5),
                               deadline=time.time() + 30))
    assert e.value.code == "MODEL_AUTH_OR_MODEL_ERROR" and len(seen) == 1


def test_missing_key_raises():
    with pytest.raises(ModelError):
        GeminiClient(api_key="", model="x")


def test_sentry_telemetry_is_safe_and_propagates_trace():
    from adproof.infrastructure import telemetry

    # Fake DSN: initialises locally; nothing is sent during the test.
    assert telemetry.init_telemetry("test", "https://public@o0.ingest.sentry.io/0", "test", 1.0)
    with telemetry.transaction("t", "adproof.audit", audit_id="aud_1", ad_copy="SECRET COPY"):
        with telemetry.span("adproof.verify", "verify", audit_id="aud_1"):
            headers = telemetry.trace_headers()
            telemetry.event("stage_finished", stage="verify", audit_id="aud_1", ad_copy="SECRET COPY")
    assert "sentry-trace" in headers
    record = {"attributes": {"audit_id": "aud_1", "ad_copy": "SECRET", "api_key": "x", "sentry.environment": "t"}}
    scrubbed = telemetry._scrub_log(record, {})["attributes"]
    assert "ad_copy" not in scrubbed and "api_key" not in scrubbed and scrubbed["audit_id"] == "aud_1"
    import sentry_sdk
    sentry_sdk.get_client().close(timeout=0)  # drop the fake-DSN queue; nothing leaves the machine
    telemetry._enabled = False


def test_schema_exports_are_current():
    from scripts.export_schemas import render_all

    for name, text in render_all().items():
        path = Path(__file__).resolve().parents[1] / "schemas" / name
        assert path.exists() and path.read_text() == text, f"{name} is stale: run python -m scripts.export_schemas"
