"""Orchestrator-side calls to the specialists over real uAgents messages, with correlation checks."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Awaitable, Callable

from ..domain.models import (RepairRequest, RepairResult, SCHEMA_VERSION, TypedError, VerificationResult,
                             VerifyRequest)
from ..infrastructure import telemetry
from ..model_client import CallBudget
from ..orchestrator.workflow import StageError
from .messages import PayloadTooLarge, TaskEnvelope, TaskResult, check_size

# send_and_receive(destination, message, response_type, timeout) -> (msg | None, status)
SendAndReceive = Callable[..., Awaitable[tuple[Any, Any]]]


def make_remote(send_and_receive: SendAndReceive, verifier: str, remediator: str, request_id: str,
                mode: str, budget: CallBudget) -> tuple[Callable, Callable]:

    async def call(dest: str, operation: str, req, timeout_cap: float) -> str:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        cand = req.candidate
        last = "no response"
        for attempt in (1, 2):  # one bounded retry; same task_id so the worker dedupes
            remaining = req.deadline_epoch - time.time()
            if remaining < 3:
                raise StageError(TypedError(code="DEADLINE_EXCEEDED", stage=operation.lower(),
                                            message=f"No time left to {operation.lower()}."))
            env = TaskEnvelope(schema_version=SCHEMA_VERSION, audit_id=req.audit_id, task_id=task_id,
                               request_id=request_id, campaign_id=cand.campaign_id, candidate_id=cand.candidate_id,
                               creative_version=cand.creative_version, phase=cand.phase.value, operation=operation,
                               attempt=attempt, deadline_epoch=req.deadline_epoch, execution_mode=mode,
                               model_call_grant=max(0, budget.limit - budget.used),
                               payload_json=req.model_dump_json(), trace_json=json.dumps(telemetry.trace_headers()))
            try:
                check_size(env)
            except PayloadTooLarge as exc:
                raise StageError(TypedError(code="PAYLOAD_TOO_LARGE", stage=operation.lower(), message=str(exc)))
            telemetry.event("task_sent", audit_id=req.audit_id, task_id=task_id, operation=operation, attempt=attempt)
            msg, status = await send_and_receive(dest, env, response_type=TaskResult,
                                                 timeout=int(max(2, min(timeout_cap, remaining - 1))))
            if msg is None:
                last = f"{operation} timed out or was not delivered ({getattr(status, 'status', status)})"
                telemetry.event("task_timed_out", audit_id=req.audit_id, task_id=task_id, operation=operation,
                                attempt=attempt)
                continue
            # correlation: only accept the answer to THIS task for THIS candidate
            if not (isinstance(msg, TaskResult) and msg.task_id == task_id and msg.audit_id == req.audit_id
                    and msg.candidate_id == cand.candidate_id and msg.phase == cand.phase.value
                    and msg.operation == operation):
                telemetry.event("result_rejected", audit_id=req.audit_id, task_id=task_id, result="mismatch")
                raise StageError(TypedError(code="RESPONSE_MISMATCH", stage=operation.lower(),
                                            message="A specialist reply did not match the pending task; rejected."))
            budget.used = min(budget.limit, budget.used + max(0, msg.calls_used))
            if not msg.ok:
                raise StageError(TypedError(code=msg.error_code or "WORKER_ERROR", stage=operation.lower(),
                                            message=msg.error_message or f"{operation} failed."))
            return msg.payload_json
        raise StageError(TypedError(code="SPECIALIST_TIMEOUT", stage=operation.lower(), message=last, retryable=True))

    async def verify(req: VerifyRequest) -> VerificationResult:
        return VerificationResult.model_validate_json(await call(verifier, "VERIFY", req, 45))

    async def remediate(req: RepairRequest) -> RepairResult:
        return RepairResult.model_validate_json(await call(remediator, "REPAIR", req, 25))

    return verify, remediate
