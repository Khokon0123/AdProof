"""Typed uAgents messages between the Orchestrator and its two specialists.

All three agents import THESE classes: uAgents matches messages by schema digest, so a copy with
different fields would silently never be delivered. Business payloads travel as JSON strings and are
parsed into the strict Pydantic domain models at both ends.
"""
from __future__ import annotations

from uagents import Model

ENVELOPE_LIMIT_BYTES = 32 * 1024


class TaskEnvelope(Model):
    schema_version: str
    audit_id: str
    task_id: str
    request_id: str
    campaign_id: str
    candidate_id: str
    creative_version: int
    phase: str            # ORIGINAL | REPAIRED
    operation: str        # VERIFY | REPAIR
    attempt: int
    deadline_epoch: float
    execution_mode: str   # LIVE | MOCK | TRANSPORT_TEST
    model_call_grant: int
    payload_json: str
    trace_json: str = "{}"  # sentry-trace + baggage from a trusted peer


class TaskResult(Model):
    schema_version: str
    audit_id: str
    task_id: str
    candidate_id: str
    phase: str
    operation: str
    attempt: int
    ok: bool
    payload_json: str = ""
    error_code: str = ""
    error_message: str = ""
    calls_used: int = 0


class PayloadTooLarge(Exception):
    pass


def check_size(msg: Model) -> None:
    size = len(msg.model_dump_json().encode())
    if size > ENVELOPE_LIMIT_BYTES:
        raise PayloadTooLarge(f"message is {size} bytes; limit is {ENVELOPE_LIMIT_BYTES}")
