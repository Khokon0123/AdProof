"""Sentry Tracing + Logs, shared by all three agents.

* Never sends ad copy, prompts, page text, image bytes, keys or user IDs.
* If SENTRY_DSN is missing or Sentry fails, AdProof keeps working (no-op).
* Trace context crosses agents inside our task envelope (sentry-trace + baggage).
"""
from __future__ import annotations

import contextlib
import logging
import re
from typing import Any, Iterator

log = logging.getLogger("adproof")
_enabled = False

_SAFE_KEYS = {"audit_id", "task_id", "candidate_id", "phase", "role", "stage", "duration_ms", "result",
              "decision", "execution_mode", "attempt", "operation", "cache_hit", "model", "error_code",
              "issues", "claims", "calls_used", "host"}
_SECRETish = re.compile(r"(key|token|secret|dsn|authorization|password)", re.I)


def _scrub_log(log_record: dict, hint: dict):
    attrs = log_record.get("attributes") or {}
    for k in list(attrs):
        if _SECRETish.search(k) or (not k.startswith("sentry.") and k not in _SAFE_KEYS):
            attrs.pop(k, None)
    return log_record


def init_telemetry(role: str, dsn: str, environment: str, traces_sample_rate: float = 1.0) -> bool:
    global _enabled
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not dsn:
        log.info("Sentry disabled (no SENTRY_DSN). Product works without telemetry.")
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn, environment=environment, traces_sample_rate=traces_sample_rate,
            enable_logs=True, before_send_log=_scrub_log,
            server_name=f"adproof-{role}", release="adproof@1.0.0", shutdown_timeout=2,
        )
        sentry_sdk.set_tag("role", role)
        _enabled = True
        log.info("Sentry tracing + logs enabled for role=%s", role)
    except Exception as exc:  # telemetry must never break the product
        log.warning("Sentry init failed (%s); continuing without telemetry.", type(exc).__name__)
        _enabled = False
    return _enabled


def enabled() -> bool:
    return _enabled


def _safe(attrs: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if isinstance(v, (int, float, bool)) else str(v)[:120]) for k, v in attrs.items() if k in _SAFE_KEYS}


def event(name: str, **attrs: Any) -> None:
    """Structured log line -> Sentry Logs (and stdout)."""
    safe = _safe(attrs)
    log.info("%s %s", name, safe)
    if _enabled:
        try:
            from sentry_sdk import logger as sentry_logger

            sentry_logger.info(name, event_name=name, **safe)
        except Exception:
            pass


@contextlib.contextmanager
def span(op: str, name: str, **data: Any) -> Iterator[None]:
    if not _enabled:
        yield
        return
    import sentry_sdk

    with sentry_sdk.start_span(op=op, name=name) as s:
        for k, v in _safe(data).items():
            s.set_data(k, v)
        yield


@contextlib.contextmanager
def transaction(name: str, op: str, headers: dict[str, str] | None = None, **tags: Any) -> Iterator[None]:
    """Start (or continue, when headers carry sentry-trace/baggage) a trace for one task."""
    if not _enabled:
        yield
        return
    import sentry_sdk

    with sentry_sdk.isolation_scope() as scope:  # per-task scope: no tag leakage between audits
        for k, v in _safe(tags).items():
            scope.set_tag(k, v)
        tx = sentry_sdk.continue_trace(headers or {}, op=op, name=name)
        with sentry_sdk.start_transaction(tx):
            yield


def trace_headers() -> dict[str, str]:
    if not _enabled:
        return {}
    import sentry_sdk

    out = {}
    tp, bg = sentry_sdk.get_traceparent(), sentry_sdk.get_baggage()
    if tp:
        out["sentry-trace"] = tp
    if bg:
        out["baggage"] = bg
    return out


def flush() -> None:
    if _enabled:
        try:
            import sentry_sdk

            sentry_sdk.flush(timeout=2)
        except Exception:
            pass
