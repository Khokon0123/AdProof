"""Shared handler logic for the Verifier and Remediator agents (testable without the network)."""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Awaitable, Callable

from pydantic import ValidationError

from ..infrastructure import telemetry
from ..model_client import CallBudget
from .messages import PayloadTooLarge, TaskEnvelope, TaskResult, check_size

Handler = Callable[[str, CallBudget], Awaitable[str]]  # payload_json, budget -> result payload_json


class WorkerCore:
    def __init__(self, role: str, operation: str, allowed_sender: str, handler: Handler):
        self.role, self.operation, self.allowed_sender, self.handler = role, operation, allowed_sender, handler
        self._done: OrderedDict[str, TaskResult] = OrderedDict()  # task_id -> result (dedupe/replay)

    def _result(self, env: TaskEnvelope, ok: bool, **kw) -> TaskResult:
        return TaskResult(schema_version=env.schema_version, audit_id=env.audit_id, task_id=env.task_id,
                          candidate_id=env.candidate_id, phase=env.phase, operation=env.operation,
                          attempt=env.attempt, ok=ok, **kw)

    async def handle(self, sender: str, env: TaskEnvelope) -> TaskResult | None:
        # 1. authenticate the transport sender before touching business content or paid APIs
        if not self.allowed_sender or sender != self.allowed_sender:
            telemetry.event("unauthorized_sender", role=self.role, result="ignored")
            return None
        if env.operation != self.operation:
            return self._result(env, False, error_code="WRONG_OPERATION", error_message=f"{self.role} only does {self.operation}.")
        # 2. idempotency: a retried task returns the same answer, no second model call
        if env.task_id in self._done:
            telemetry.event("duplicate_ignored", role=self.role, task_id=env.task_id, audit_id=env.audit_id)
            return self._done[env.task_id]
        if time.time() > env.deadline_epoch - 1:
            return self._result(env, False, error_code="DEADLINE_EXCEEDED", error_message="Task arrived after its deadline.")
        budget = CallBudget(limit=max(0, env.model_call_grant))
        try:
            trace = json.loads(env.trace_json or "{}")
        except json.JSONDecodeError:
            trace = {}
        with telemetry.transaction(f"adproof.{self.role}", f"adproof.{self.operation.lower()}", headers=trace,
                                   role=self.role, audit_id=env.audit_id, phase=env.phase, attempt=env.attempt):
            try:
                payload = await self.handler(env.payload_json, budget)
                res = self._result(env, True, payload_json=payload, calls_used=budget.used)
                check_size(res)
            except PayloadTooLarge as exc:
                res = self._result(env, False, error_code="PAYLOAD_TOO_LARGE", error_message=str(exc), calls_used=budget.used)
            except ValidationError as exc:
                res = self._result(env, False, error_code="INVALID_PAYLOAD", error_message=str(exc)[:300], calls_used=budget.used)
            except Exception as exc:  # never crash the agent; report a typed error
                res = self._result(env, False, error_code="WORKER_ERROR", error_message=f"{type(exc).__name__}: {str(exc)[:200]}",
                                   calls_used=budget.used)
        self._done[env.task_id] = res
        while len(self._done) > 500:
            self._done.popitem(last=False)
        return res
