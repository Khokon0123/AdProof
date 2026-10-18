"""Chat handling for the public AdProof agent (network-free core; the agent file wires it to uAgents)."""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable, Optional

from ..demo_inputs import CASE_HELP, demo_input
from ..domain.models import AuditReport, CampaignInput, Decision
from ..infrastructure import telemetry
from ..infrastructure.settings import Settings
from ..inspector.inspector import InspectionCache
from ..model_client import CallBudget
from ..orchestrator.report_text import chunks, render
from ..orchestrator.workflow import WorkflowDeps, continue_with_repair, run_audit
from ..runtime import build_fetcher, build_model, execution_mode
from . import cards
from .intake import EXAMPLE, HELP, parse
from .remote import make_remote
from .store import Store

Reply = Callable[[str, Optional[dict]], Awaitable[None]]  # (text, card metadata or None)
MAX_ACTIVE_AUDITS = 2


class OrchestratorCore:
    def __init__(self, settings: Settings, store: Store, verifier: str, remediator: str):
        self.s, self.store, self.verifier, self.remediator = settings, store, verifier, remediator
        self.mode = execution_mode(settings)
        self.model = build_model(settings)
        self.fetcher = build_fetcher(settings)
        self.cache = InspectionCache() if settings.inspection_cache else None
        self._slots = asyncio.Semaphore(MAX_ACTIVE_AUDITS)
        self._active: set[str] = set()
        self._last: dict[str, str] = {}  # sender -> last audit_id

    def _deps(self, send_and_receive, request_id: str, progress) -> WorkflowDeps:
        budget = CallBudget(limit=self.s.max_model_calls)
        verify, remediate = make_remote(send_and_receive, self.verifier, self.remediator, request_id,
                                        self.mode.value, budget)
        return WorkflowDeps(fetcher=self.fetcher, inspector_model=self.model, verify=verify, remediate=remediate,
                            mode=self.mode, budget=budget, cache=self.cache, deadline_s=self.s.audit_deadline_s,
                            progress=progress)

    async def handle(self, sender: str, msg_id: str, text: str, send_and_receive, reply: Reply) -> None:
        if not self.store.first_time(f"{sender}|{msg_id}"):
            telemetry.event("duplicate_ignored", role="orchestrator")
            return
        intent = parse(text)
        if intent.kind == "help":
            await reply(HELP, None)
        elif intent.kind == "example":
            await reply(EXAMPLE, None)
        elif intent.kind == "invalid":
            await reply(f"I couldn't read that input. {intent.error}\nType `example` to see the format.", None)
        elif intent.kind == "demo":
            note = (f"Demo '{intent.arg}': {CASE_HELP[intent.arg]}.\nSynthetic AeroBeat AB-01 product; context assumed for "
                    "the demo: Google Ads, US, English, adults, consumer electronics.")
            await reply(note, None)
            await self._run(sender, demo_input(intent.arg), send_and_receive, reply)
        elif intent.kind == "audit":
            await self._run(sender, intent.campaign, send_and_receive, reply)
        elif intent.kind in ("status", "report"):
            await self._show(sender, intent.arg, reply, full=intent.kind == "report")
        elif intent.kind == "action":
            await self._action(sender, intent.selection, send_and_receive, reply)
        else:
            await reply("I check ads before launch. Type `demo aerobeat` to see it work, or `help`.", None)

    # ------------------------------------------------------------------ actions
    async def _show(self, sender: str, audit_id: Optional[str], reply: Reply, full: bool) -> None:
        row = self.store.get(audit_id or "", sender) if audit_id else None
        if not row:
            await reply("I can't find that audit for you. Audits are private to the person who started them.", None)
            return
        if not row["report_json"]:
            await reply(f"Audit {audit_id} status: {row['status']}.", None)
            return
        r = AuditReport.model_validate_json(row["report_json"])
        if not full:
            await reply(f"Audit {audit_id}: {row['status']}, final decision {r.final_decision.value}.", None)
            return
        await self._send_report(r, reply)

    async def _action(self, sender: str, sel: dict, send_and_receive, reply: Reply) -> None:
        audit_id = sel.get("audit_id") or self._last.get(sender)
        row = self.store.get(audit_id or "", sender) if audit_id else None
        if not row or not row["report_json"]:
            await reply("That action belongs to an audit I can't find for you. Start a new one with `demo aerobeat`.", None)
            return
        r = AuditReport.model_validate_json(row["report_json"])
        act = sel.get("action")
        if act == "view_finding":
            card = cards.finding_card(r, str(sel.get("issue_id", "")))
            if not card:
                await reply("I can't find that finding in this audit.", None)
                return
            kind, payload = card
            await reply(f"Evidence for {sel.get('issue_id')}: " + payload["summary_rows"][0]["value"],
                        cards.metadata(kind, payload, interactive=True))
        elif act == "show_report":
            await self._send_report(r, reply)
        elif act == "repair_reaudit":
            if row["repaired"] or r.repair is not None:
                await reply("This audit already used its one repair. Start a new audit to try again.", None)
                return
            if not (r.original_audit and r.original_audit.decision == Decision.FIX_REQUIRED):
                await reply("Repair is only offered when the original needs fixes; review/block results need a person.", None)
                return
            inp = CampaignInput.model_validate_json(row["input_json"])
            if sender in self._active:
                await reply("Your previous audit is still running. Please wait for it to finish.", None)
                return
            self._active.add(sender)
            try:
                async with self._slots:
                    deps = self._deps(send_and_receive, inp.request_id, lambda t: reply(t, None))
                    with telemetry.transaction("adproof.repair_continuation", "adproof.audit", role="orchestrator",
                                               audit_id=r.audit_id):
                        new = await continue_with_repair(r, inp.landing_page_url, inp.evidence_documents, deps)
                self.store.finish(r.audit_id, new.model_dump_json(), new.workflow_status.value, repaired=True)
                await self._send_report(new, reply)
            finally:
                self._active.discard(sender)
        else:
            await reply("I don't recognise that action.", None)

    async def _run(self, sender: str, campaign: CampaignInput, send_and_receive, reply: Reply) -> None:
        key = campaign.request_id
        body = campaign.model_dump_json(exclude={"request_id"})
        h = self.store.payload_hash(body)
        existing = self.store.find_request(sender, key)
        if existing:
            audit_id, prev_hash, report_json, status = existing
            if prev_hash != h:
                await reply(f"Request ID '{key}' was already used with different content. Use a new request_id.", None)
            elif report_json:
                await self._send_report(AuditReport.model_validate_json(report_json), reply)
            else:
                await reply(f"Audit {audit_id} for this request is {status}.", None)
            return
        if sender in self._active:
            await reply("Your previous audit is still running. Please wait for it to finish.", None)
            return
        if self._slots.locked():
            await reply("AdProof is busy with other audits right now. Please try again in a minute.", None)
            return
        self._active.add(sender)
        import uuid
        audit_id = f"aud_{uuid.uuid4().hex[:12]}"
        self.store.start(audit_id, sender, key, h, campaign.model_dump_json())
        self._last[sender] = audit_id
        try:
            async with self._slots:
                deps = self._deps(send_and_receive, campaign.request_id, lambda t: reply(t, None))
                with telemetry.transaction("adproof.audit", "adproof.audit", role="orchestrator", audit_id=audit_id,
                                           execution_mode=self.mode.value):
                    report = await run_audit(campaign, deps, audit_id=audit_id)
            self.store.finish(audit_id, report.model_dump_json(), report.workflow_status.value,
                              repaired=report.repair is not None)
            await self._send_report(report, reply)
        except Exception as exc:
            self.store.finish(audit_id, "", "FAILED")
            await reply(f"The audit failed unexpectedly ({type(exc).__name__}). Nothing was approved. "
                        "Please try again.", None)
            raise
        finally:
            self._active.discard(sender)

    async def _send_report(self, r: AuditReport, reply: Reply) -> None:
        parts = chunks(render(r))
        try:
            kind, payload, interactive = cards.report_card(r)
            meta = cards.metadata(kind, payload, interactive)
        except Exception:
            meta = None  # the full plain-text report is always sent anyway
        for i, part in enumerate(parts):
            await reply(part, meta if i == len(parts) - 1 else None)
