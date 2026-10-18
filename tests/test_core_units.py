"""Units: decision precedence, Decimal math, SSRF guards, image freezing, intake, cards, worker, remote."""
import asyncio
import io
import json
import time
from decimal import Decimal

import pytest
from PIL import Image

import tests.helpers  # noqa: F401  (sets MOCK + no Sentry)
from adproof.domain.decision import decide
from adproof.domain.models import (Action, Coverage, CoverageItem, CoverageStatus, Decision, Issue, IssueCategory,
                                   PolicyCheck, Severity)
from adproof.domain.pricing import check_discount, discount_percent, find_prices
from adproof.infrastructure.content import ContentError, freeze_image, quote_in_source
from adproof.infrastructure.safe_http import FetchError, validate_url
from adproof.model_client import CallBudget
from adproof.transport import cards
from adproof.transport.intake import parse
from adproof.transport.messages import TaskEnvelope, TaskResult
from adproof.transport.worker import WorkerCore

OK = CoverageItem(status=CoverageStatus.CHECKED)


def cov(**over):
    base = dict(ad_text=OK, landing_page=OK, supporting_documents=CoverageItem(status=CoverageStatus.NOT_APPLICABLE),
                image=OK, platform_policy=CoverageItem(status=CoverageStatus.PARTIAL))
    base.update(over)
    return Coverage(**base)


def issue(action, ref=None):
    return Issue(id="I1", claim_id=None, category=IssueCategory.PRICE_DISCOUNT_MISMATCH, severity=Severity.critical,
                 explanation="x", suggested_fix="y", action=action, policy_reference=ref)


# ---------------------------------------------------------------- decision precedence (case 22)
def test_critical_severity_alone_never_blocks():
    d, _ = decide(issues=[issue(Action.FIX)], coverage=cov(), policy_checks=[], errors=[], scope_supported=True)
    assert d == Decision.FIX_REQUIRED


def test_block_requires_active_rule():
    active = [PolicyCheck(rule_id="SYN-1", applicable=True, violated=True, status="ACTIVE", note="synthetic")]
    assert decide(issues=[], coverage=cov(), policy_checks=active, errors=[], scope_supported=True)[0] == Decision.BLOCK
    draft = [PolicyCheck(rule_id="SYN-1", applicable=True, violated=True, status="DRAFT", note="draft")]
    assert decide(issues=[], coverage=cov(), policy_checks=draft, errors=[], scope_supported=True)[0] == Decision.PASS
    # an issue citing a non-ACTIVE rule degrades to review instead of BLOCK
    assert decide(issues=[issue(Action.BLOCK, "SYN-1")], coverage=cov(), policy_checks=draft, errors=[],
                  scope_supported=True)[0] == Decision.HUMAN_REVIEW


def test_incomplete_coverage_or_scope_forces_review_and_pass_needs_everything():
    assert decide(issues=[], coverage=cov(image=CoverageItem(status=CoverageStatus.PARTIAL, reason="blur")),
                  policy_checks=[], errors=[], scope_supported=True)[0] == Decision.HUMAN_REVIEW
    assert decide(issues=[], coverage=cov(), policy_checks=[], errors=[], scope_supported=False)[0] == Decision.HUMAN_REVIEW
    assert decide(issues=[], coverage=cov(), policy_checks=[], errors=[], scope_supported=True)[0] == Decision.PASS


# ---------------------------------------------------------------- arithmetic
def test_discount_math_is_decimal_and_exact():
    assert discount_percent(Decimal("80"), Decimal("60")) == Decimal("25.00")
    assert not check_discount(Decimal("50"), Decimal("80"), Decimal("60")).supported
    assert check_discount(Decimal("25"), Decimal("80"), Decimal("60")).supported
    assert check_discount(Decimal("33"), Decimal("75"), Decimal("50")).supported  # 33.33 within ±0.5 tolerance
    assert [(a, c) for a, c, _ in find_prices("Now $60—was US$80, or €55")] == [
        (Decimal("60.00"), "USD"), (Decimal("80.00"), "USD"), (Decimal("55.00"), "EUR")]


def test_quote_must_be_verbatim():
    page = "Splash-resistant (IPX4).  Not waterproof: do not swim."
    assert quote_in_source("not   WATERPROOF", page)
    assert not quote_in_source("Certified waterproof", page)


# ---------------------------------------------------------------- SSRF (case 16)
@pytest.mark.parametrize("url,code", [
    ("http://raw.githubusercontent.com/x.png", "UNSAFE_URL"),
    ("https://user:pw@raw.githubusercontent.com/x", "UNSAFE_URL"),
    ("https://127.0.0.1/x", "UNSAFE_URL"),
    ("https://169.254.169.254/latest/meta-data", "UNSAFE_URL"),
    ("https://localhost/x", "UNSAFE_URL"),
    ("https://raw.githubusercontent.com:8443/x", "UNSAFE_URL"),
    ("https://evil.example.com/x", "HOST_NOT_ALLOWED"),
])
def test_unsafe_urls_rejected(url, code):
    with pytest.raises(FetchError) as e:
        validate_url(url, ("raw.githubusercontent.com",), allow_public=False)
    assert e.value.code == code


def test_allowlisted_https_url_accepted():
    assert validate_url("https://raw.githubusercontent.com/a/b/main/x.png", ("raw.githubusercontent.com",), False)


def _png(w, h, fmt="PNG"):
    b = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(b, format=fmt)
    return b.getvalue()


def test_image_freezing_strips_and_validates():
    frozen, data = freeze_image(_png(64, 48), "https://x/y.png")
    assert frozen.width == 64 and frozen.model_input_sha256 and data[:4] == b"\x89PNG"
    with pytest.raises(ContentError):
        freeze_image(_png(10, 10, "GIF"), "u")
    with pytest.raises(ContentError):
        freeze_image(b"<!doctype html><html>", "u")
    with pytest.raises(ContentError):
        freeze_image(_png(9000, 10), "u")


# ---------------------------------------------------------------- intake
def test_intake_commands_and_forms():
    assert parse("help").kind == "help"
    assert parse("demo trap").arg == "trap"
    assert parse("report aud_0123456789ab").kind == "report"
    sel = parse('{"action": "view_finding", "audit_id": "aud_0123456789ab", "issue_id": "I2"}')
    assert sel.kind == "action" and sel.selection["issue_id"] == "I2"
    prose = parse("The user selected view_finding for I3 in aud_0123456789ab")
    assert prose.selection == {"action": "view_finding", "audit_id": "aud_0123456789ab", "issue_id": "I3"}
    form = parse("image: https://raw.githubusercontent.com/a/x.png\npage: https://raw.githubusercontent.com/a/p.html\n"
                 "copy: Now $60\nrepair: yes")
    assert form.kind == "audit" and form.campaign.repair_mode == "repair_once"
    assert form.campaign.context.audience is None  # unknown context is never assumed


# ---------------------------------------------------------------- worker: auth, dedupe, deadline (cases 11, 12)
def _env(task="t1", **kw):
    base = dict(schema_version="1.0", audit_id="aud_x", task_id=task, request_id="r", campaign_id="c", candidate_id="cand",
                creative_version=1, phase="ORIGINAL", operation="VERIFY", attempt=1, deadline_epoch=time.time() + 60,
                execution_mode="MOCK", model_call_grant=5, payload_json="{}")
    base.update(kw)
    return TaskEnvelope(**base)


def test_worker_ignores_unknown_sender_and_dedupes():
    calls = []

    async def handler(payload, budget: CallBudget):
        calls.append(payload)
        budget.reserve("x")
        return json.dumps({"ok": True})

    core = WorkerCore("verifier", "VERIFY", "agent1orchestrator", handler)
    assert asyncio.run(core.handle("agent1stranger", _env())) is None and not calls
    r1 = asyncio.run(core.handle("agent1orchestrator", _env()))
    r2 = asyncio.run(core.handle("agent1orchestrator", _env(attempt=2)))
    assert r1.ok and r2 == r1 and len(calls) == 1 and r1.calls_used == 1
    late = asyncio.run(core.handle("agent1orchestrator", _env(task="t2", deadline_epoch=time.time() - 5)))
    assert late.error_code == "DEADLINE_EXCEEDED"


def test_remote_rejects_mismatched_reply_and_retries_on_timeout():
    from adproof.domain.models import (CampaignContext, CreativeCandidate, InspectionResult, InspectionStatus, Phase,
                                       VerifyRequest)
    from adproof.orchestrator.workflow import StageError
    from adproof.transport.remote import make_remote

    cand = CreativeCandidate(campaign_id="c", candidate_id="cand1", creative_version=1, phase=Phase.ORIGINAL,
                             ad_copy="x", context=CampaignContext())
    req = VerifyRequest(audit_id="aud_1", candidate=cand, landing_page_url="https://x", deadline_epoch=time.time() + 60,
                        inspection=InspectionResult(candidate_id="cand1", image_sha256=None, model=None,
                                                    prompt_version="v", status=InspectionStatus.NOT_PROVIDED))
    sent = []

    async def forged(dest, env, response_type, timeout):
        sent.append(env.task_id)
        return TaskResult(schema_version="1.0", audit_id="aud_1", task_id="someone-else", candidate_id="cand1",
                          phase="ORIGINAL", operation="VERIFY", attempt=1, ok=True, payload_json="{}"), None

    verify, _ = make_remote(forged, "v", "r", "req", "MOCK", CallBudget(limit=5))
    with pytest.raises(StageError) as e:
        asyncio.run(verify(req))
    assert e.value.err.code == "RESPONSE_MISMATCH"

    async def silent(dest, env, response_type, timeout):
        sent.append(env.task_id)
        return None, "timeout"

    sent.clear()
    verify, _ = make_remote(silent, "v", "r", "req", "MOCK", CallBudget(limit=5))
    with pytest.raises(StageError) as e:
        asyncio.run(verify(req))
    assert e.value.err.code == "SPECIALIST_TIMEOUT" and len(sent) == 2 and sent[0] == sent[1]


# ---------------------------------------------------------------- cards
def test_report_and_finding_cards_are_valid():
    from tests.helpers import demo_input, make_deps
    from adproof.orchestrator.workflow import run_audit

    deps, _, _ = make_deps()
    r = asyncio.run(run_audit(demo_input("audit"), deps))
    kind, payload, interactive = cards.report_card(r)
    meta = cards.metadata(kind, payload, interactive)
    assert all(isinstance(v, str) for v in meta.values()) and meta["card_protocol_version"] == "1"
    assert interactive and "repair_reaudit" in meta["card_payload"]
    fk, fp = cards.finding_card(r, r.original_audit.issues[0].id)
    assert fk == "detail" and fp["summary_rows"]
