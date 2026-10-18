"""Orchestrator workflow: freeze -> inspect -> verify -> (one repair) -> independent re-verify -> report.

`verify` and `remediate` are injected: in production they send real uAgents messages to the Verifier and
Remediator agents; in tests they call the business functions directly.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from ..domain.models import (AuditReport, CampaignInput, CreativeCandidate, Decision, ExecutionMode, InspectionResult,
                             Phase, RepairRequest, RepairResult, TypedError, VerificationResult, VerifyRequest,
                             WorkflowStatus)
from ..infrastructure import telemetry
from ..infrastructure.content import ContentError, freeze_image
from ..infrastructure.safe_http import FetchError, Fetcher
from ..inspector.inspector import InspectionCache, inspect_image
from ..model_client import CallBudget, ModelClient
from ..verifier.verify import EVIDENCE_SCOPE, load_catalog

VerifyFn = Callable[[VerifyRequest], Awaitable[VerificationResult]]
RepairFn = Callable[[RepairRequest], Awaitable[RepairResult]]


class StageError(Exception):
    def __init__(self, err: TypedError):
        super().__init__(err.message)
        self.err = err


@dataclass
class WorkflowDeps:
    fetcher: Fetcher
    inspector_model: ModelClient
    verify: VerifyFn
    remediate: RepairFn
    mode: ExecutionMode
    budget: CallBudget
    cache: Optional[InspectionCache] = None
    deadline_s: int = 120
    progress: Optional[Callable[[str], Awaitable[None]]] = None


@dataclass
class _Frozen:
    candidate: CreativeCandidate
    model_bytes: Optional[bytes]


async def _say(deps: WorkflowDeps, text: str) -> None:
    if deps.progress:
        try:
            await deps.progress(text)
        except Exception:
            pass


async def _freeze_original(inp: CampaignInput, deps: WorkflowDeps, deadline: float) -> _Frozen:
    frozen, model_bytes = None, None
    if inp.creative.image_url:
        with telemetry.span("adproof.image", "image fetch + decode"):
            try:
                res = await deps.fetcher.fetch(inp.creative.image_url, "image", min(deadline, time.time() + 10))
                frozen, model_bytes = freeze_image(res.body, res.final_url)
            except (FetchError, ContentError) as exc:
                raise StageError(TypedError(code=exc.code, message=exc.message, stage="image",
                                            retryable=getattr(exc, "retryable", False)))
    cand = CreativeCandidate(campaign_id=inp.campaign_id, candidate_id=f"cand_{uuid.uuid4().hex[:10]}",
                             creative_version=inp.creative_version, phase=Phase.ORIGINAL, ad_copy=inp.creative.ad_copy,
                             image=frozen, context=inp.context, product_context=inp.product_context)
    return _Frozen(cand, model_bytes)


async def run_audit(inp: CampaignInput, deps: WorkflowDeps, audit_id: Optional[str] = None,
                    force_repair: bool = False) -> AuditReport:
    audit_id = audit_id or f"aud_{uuid.uuid4().hex[:12]}"
    started_dt, started = datetime.now(timezone.utc), time.time()
    deadline = started + deps.deadline_s - 5  # reserve 5 s for formatting and delivery
    catalog_version = load_catalog().get("catalog_version", "missing")
    errors: list[TypedError] = []
    telemetry.event("audit_started", audit_id=audit_id, execution_mode=deps.mode.value)

    def report(**kw) -> AuditReport:
        r = AuditReport(audit_id=audit_id, execution_mode=deps.mode, scope=EVIDENCE_SCOPE,
                        policy_catalog_version=catalog_version, started_at=started_dt,
                        finished_at=datetime.now(timezone.utc), duration_ms=int((time.time() - started) * 1000),
                        model_calls=deps.budget.used, model=deps.inspector_model.name, errors=errors, **kw)
        telemetry.event("audit_completed", audit_id=audit_id, decision=r.final_decision.value,
                        result=r.workflow_status.value, duration_ms=r.duration_ms, calls_used=deps.budget.used,
                        execution_mode=deps.mode.value)
        return r

    # 1. freeze + inspect the original
    await _say(deps, "Reading the ad image and freezing the original version…")
    try:
        frozen = await _freeze_original(inp, deps, deadline)
    except StageError as exc:
        errors.append(exc.err)
        return report(workflow_status=WorkflowStatus.FAILED, original_candidate=None, original_inspection=None,
                      original_audit=None, selected_candidate_id=None, final_decision=Decision.HUMAN_REVIEW,
                      final_decision_basis=f"The image could not be loaded ({exc.err.message}), so no audit ran.")
    original = frozen.candidate
    inspection = await inspect_image(original, frozen.model_bytes, deps.inspector_model, deps.budget, deadline, deps.cache)

    # 2. verify the original (Verifier agent)
    await _say(deps, "Checking every claim against the landing page…")
    try:
        with telemetry.span("adproof.dispatch", "verify original", audit_id=audit_id, phase="ORIGINAL"):
            orig_audit = await deps.verify(VerifyRequest(audit_id=audit_id, candidate=original, inspection=inspection,
                                                         landing_page_url=inp.landing_page_url,
                                                         evidence_documents=inp.evidence_documents,
                                                         deadline_epoch=deadline))
    except StageError as exc:
        errors.append(exc.err)
        return report(workflow_status=WorkflowStatus.FAILED, original_candidate=original, original_inspection=inspection,
                      original_audit=None, selected_candidate_id=original.candidate_id,
                      final_decision=Decision.HUMAN_REVIEW,
                      final_decision_basis="The original audit did not complete, so a person must review the ad.")

    wants_repair = inp.repair_mode == "repair_once" or force_repair
    if not wants_repair or orig_audit.decision != Decision.FIX_REQUIRED:
        basis = {Decision.PASS: "Original passed all scoped checks; no repair needed.",
                 Decision.FIX_REQUIRED: "Original needs fixes; repair was not requested.",
                 Decision.HUMAN_REVIEW: "Original needs human review; a rewrite cannot resolve missing evidence or uncertainty.",
                 Decision.BLOCK: "Original is blocked by an active rule."}[orig_audit.decision]
        return report(workflow_status=WorkflowStatus.COMPLETED, original_candidate=original,
                      original_inspection=inspection, original_audit=orig_audit,
                      selected_candidate_id=original.candidate_id, final_decision=orig_audit.decision,
                      final_decision_basis=basis)

    # The repair + re-audit gets its own time window: a slow live audit must not starve the one repair.
    repair_deadline = max(deadline, time.time() + deps.deadline_s - 5)
    return await _repair_phase(audit_id, inp.landing_page_url, inp.evidence_documents, original, inspection,
                               orig_audit, frozen.model_bytes, deps, repair_deadline, report, errors)


async def _repair_phase(audit_id, landing_page_url, evidence_documents, original, inspection, orig_audit,
                        model_bytes, deps: WorkflowDeps, deadline, report, errors) -> AuditReport:
    # 3. one repair (Remediator agent) — proposes, never decides
    await _say(deps, "Proposing the smallest safe rewrite…")
    try:
        with telemetry.span("adproof.dispatch", "repair", audit_id=audit_id):
            repair = await deps.remediate(RepairRequest(audit_id=audit_id, candidate=original,
                                                        verification=orig_audit, deadline_epoch=deadline))
    except StageError as exc:
        errors.append(exc.err)
        repair = None
    if repair is None or not repair.repaired_copy:
        if repair:
            errors.extend(repair.errors)
        return report(workflow_status=WorkflowStatus.PARTIAL, original_candidate=original, original_inspection=inspection,
                      original_audit=orig_audit, repair=repair, selected_candidate_id=original.candidate_id,
                      final_decision=orig_audit.decision,
                      final_decision_basis="Repair failed; the original remains the last verified version.")

    revised = original.model_copy(update={"candidate_id": repair.candidate_id, "phase": Phase.REPAIRED,
                                          "ad_copy": repair.repaired_copy, "created_at": datetime.now(timezone.utc)})
    # Same image bytes -> same hash. Image-only observations may be reused from cache; all checks re-run.
    if model_bytes is not None:
        rev_inspection = await inspect_image(revised, model_bytes, deps.inspector_model, deps.budget, deadline, deps.cache)
    else:  # continuation after a restart or a later click: same frozen image hash -> reuse image-only observations
        rev_inspection = inspection.model_copy(update={"candidate_id": revised.candidate_id, "cache_hit": True})

    # 4. independent re-audit of the revised candidate (Verifier agent again)
    await _say(deps, "Re-checking the rewritten ad from scratch…")
    try:
        with telemetry.span("adproof.dispatch", "verify revised", audit_id=audit_id, phase="REPAIRED"):
            rev_audit = await deps.verify(VerifyRequest(audit_id=audit_id, candidate=revised, inspection=rev_inspection,
                                                        landing_page_url=landing_page_url,
                                                        evidence_documents=evidence_documents,
                                                        deadline_epoch=deadline))
    except StageError as exc:
        errors.append(exc.err)
        return report(workflow_status=WorkflowStatus.PARTIAL, original_candidate=original, original_inspection=inspection,
                      original_audit=orig_audit, repair=repair, revised_candidate=revised, revised_audit=None,
                      selected_candidate_id=original.candidate_id, final_decision=orig_audit.decision,
                      repair_verified=False,
                      final_decision_basis="Re-audit failed; the rewrite is unverified and the original remains "
                                           "the last verified version.")
    if rev_audit.audit_complete:
        basis = ("Revised version independently re-audited: "
                 + {Decision.PASS: "it passes all scoped checks.",
                    Decision.FIX_REQUIRED: "issues remain (for example in the image), so it still needs fixes.",
                    Decision.HUMAN_REVIEW: "it needs human review.",
                    Decision.BLOCK: "it is blocked by an active rule."}[rev_audit.decision])
        return report(workflow_status=WorkflowStatus.COMPLETED, original_candidate=original, original_inspection=inspection,
                      original_audit=orig_audit, repair=repair, revised_candidate=revised, revised_audit=rev_audit,
                      selected_candidate_id=revised.candidate_id, final_decision=rev_audit.decision,
                      repair_verified=True, final_decision_basis=basis)
    return report(workflow_status=WorkflowStatus.PARTIAL, original_candidate=original, original_inspection=inspection,
                  original_audit=orig_audit, repair=repair, revised_candidate=revised, revised_audit=rev_audit,
                  selected_candidate_id=revised.candidate_id,
                  final_decision=rev_audit.decision if rev_audit.decision in (Decision.BLOCK, Decision.HUMAN_REVIEW)
                  else Decision.HUMAN_REVIEW, repair_verified=False,
                  final_decision_basis="The re-audit of the rewrite was incomplete; it is not a verified improvement.")


async def continue_with_repair(stored: AuditReport, landing_page_url: str, evidence_documents, deps: WorkflowDeps) -> AuditReport:
    """User clicked 'Repair and re-audit' on an audit-only result. Exactly one repair per original audit."""
    started_dt, started = datetime.now(timezone.utc), time.time()
    deadline = started + deps.deadline_s - 5
    errors: list[TypedError] = []

    def report(**kw) -> AuditReport:
        return AuditReport(audit_id=stored.audit_id, execution_mode=deps.mode, scope=stored.scope,
                           policy_catalog_version=stored.policy_catalog_version, started_at=started_dt,
                           finished_at=datetime.now(timezone.utc), duration_ms=int((time.time() - started) * 1000),
                           model_calls=deps.budget.used, model=deps.inspector_model.name, errors=errors, **kw)

    if stored.original_audit is None or stored.original_candidate is None or stored.original_inspection is None:
        return stored
    return await _repair_phase(stored.audit_id, landing_page_url, evidence_documents, stored.original_candidate,
                               stored.original_inspection, stored.original_audit, None, deps, deadline, report, errors)
