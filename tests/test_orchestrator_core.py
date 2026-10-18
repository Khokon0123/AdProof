"""Chat-level behaviour of the public agent, with specialists wired in-process (cases 11, 20, 24)."""
import asyncio
import json
import tempfile

import tests.helpers  # noqa: F401
from adproof.domain.models import RepairRequest, VerifyRequest
from adproof.infrastructure.settings import get_settings
from adproof.model_client import CallBudget
from adproof.remediator.remediate import RemediatorDeps, remediate
from adproof.runtime import build_fetcher, build_model
from adproof.transport.orchestrator_core import OrchestratorCore
from adproof.transport.store import Store
from adproof.transport.worker import WorkerCore
from adproof.verifier.verify import VerifierDeps, verify_campaign

ORCH = "agent1orchestrator"


def build():
    s = get_settings()
    model, fetcher = build_model(s), build_fetcher(s)

    async def v(payload, budget: CallBudget):
        return (await verify_campaign(VerifyRequest.model_validate_json(payload),
                                      VerifierDeps(fetcher=fetcher, model=model, budget=budget))).model_dump_json()

    async def r(payload, budget: CallBudget):
        return (await remediate(RepairRequest.model_validate_json(payload),
                                RemediatorDeps(model=model, budget=budget))).model_dump_json()

    workers = {"agent1verifier": WorkerCore("verifier", "VERIFY", ORCH, v),
               "agent1remediator": WorkerCore("remediator", "REPAIR", ORCH, r)}

    async def send_and_receive(dest, env, response_type=None, timeout=30):
        return await workers[dest].handle(ORCH, env), "delivered"

    db = tempfile.mktemp(suffix=".sqlite3")
    core = OrchestratorCore(s, Store(db), "agent1verifier", "agent1remediator")
    return core, send_and_receive


def chat(core, sar, sender, text, msg_id):
    out = []

    async def reply(body, meta):
        out.append((body, meta))

    asyncio.run(core.handle(sender, msg_id, text, sar, reply))
    return out


def test_audit_then_click_repair_then_evidence_and_privacy():
    core, sar = build()
    out = chat(core, sar, "alice", "demo audit", "m1")
    final = [b for b, _ in out if "Final:" in b][0]
    assert "FIX REQUIRED" in final
    card = [m for _, m in out if m][-1]
    payload = json.loads(card["card_payload"])
    assert card["requires_card_interaction"] == "true" and "repair_reaudit" in card["card_payload"]
    audit_id = payload["root"]["subtitle"].split()[-1]

    # duplicate delivery of the same message: acknowledged by the agent, but no second audit
    assert chat(core, sar, "alice", "demo audit", "m1") == []

    # someone else cannot read or act on Alice's audit
    other = chat(core, sar, "mallory", f"report {audit_id}", "x1")
    assert "can't find" in other[0][0]
    other = chat(core, sar, "mallory", json.dumps({"action": "repair_reaudit", "audit_id": audit_id}), "x2")
    assert "can't find" in other[0][0]

    # Alice clicks Repair and re-audit: one repair, independent re-audit -> PASS
    out = chat(core, sar, "alice", json.dumps({"action": "repair_reaudit", "audit_id": audit_id}), "m2")
    assert any("Final: PASS" in b for b, _ in out)
    # second repair on the same audit is refused
    again = chat(core, sar, "alice", json.dumps({"action": "repair_reaudit", "audit_id": audit_id}), "m3")
    assert "already used its one repair" in again[0][0]

    # evidence detail card for a finding
    ev = chat(core, sar, "alice", json.dumps({"action": "view_finding", "audit_id": audit_id, "issue_id": "I1"}), "m4")
    assert ev[0][1]["card_kind"] == "detail"


def test_request_id_conflict_is_reported_not_reused():
    core, sar = build()
    base = ("```json\n" + json.dumps({
        "request_id": "same-id", "campaign_id": "c", "creative_version": 1,
        "creative": {"image_url": "https://raw.githubusercontent.com/Khokon0123/AdProof/main/data/fixtures/aerobeat_neutral.png",
                     "ad_copy": "Meet AeroBeat AB-01 headphones: splash-resistant, with up to 30 hours of battery life when noise cancellation is off. Now $60, down from $80—25% off."},
        "landing_page_url": "https://raw.githubusercontent.com/Khokon0123/AdProof/main/data/fixtures/aerobeat.html",
        "context": {"platform": "google_ads", "jurisdiction": "US", "language": "en", "audience": "adults",
                    "product_category": "electronics"}}) + "\n```")
    first = chat(core, sar, "bob", base, "b1")
    assert any("Final: PASS" in b for b, _ in first)
    changed = chat(core, sar, "bob", base.replace("25% off", "30% off"), "b2")
    assert "already used with different content" in changed[0][0]
