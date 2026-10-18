"""ASI:One Interactive Cards for AdProof. Every card is sent with a full plain-text report beside it."""
from __future__ import annotations

import json

from ..domain.models import AuditReport, ClaimStatus, Decision

LABEL = {Decision.PASS: "PASS", Decision.FIX_REQUIRED: "FIX REQUIRED", Decision.BLOCK: "BLOCK",
         Decision.HUMAN_REVIEW: "HUMAN REVIEW"}
VARIANT = {Decision.PASS: "success", Decision.FIX_REQUIRED: "warning", Decision.BLOCK: "warning",
           Decision.HUMAN_REVIEW: "info"}
STATUS_VARIANT = {ClaimStatus.SUPPORTED: "success", ClaimStatus.CONTRADICTED: "warning",
                  ClaimStatus.INSUFFICIENT_EVIDENCE: "info"}
STATUS_LABEL = {ClaimStatus.SUPPORTED: "Supported", ClaimStatus.CONTRADICTED: "Contradicted",
                ClaimStatus.INSUFFICIENT_EVIDENCE: "No evidence"}


def _short(t: str, n: int = 120) -> str:
    t = " ".join(str(t).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def report_card(r: AuditReport) -> tuple[str, dict, bool]:
    """Returns (card_kind, payload, needs_interaction)."""
    o = r.original_audit
    children: list[dict] = [{"type": "group", "direction": "row", "gap": 8, "children": [
        {"type": "badge", "label": f"Original: {LABEL[o.decision]}" if o else "No audit", "variant": VARIANT[o.decision] if o else "info"},
        *([{"type": "badge", "label": f"Final: {LABEL[r.final_decision]}", "variant": VARIANT[r.final_decision]}]),
        {"type": "text", "value": r.execution_mode.value + (" · scripted model" if r.execution_mode.value != "LIVE" else ""), "style": "muted"},
    ]}]
    if o:
        items = []
        claims = {c.id: c for c in o.claims}
        for i in o.issues[:6]:
            c = claims.get(i.claim_id or "")
            items.append({"children": [
                {"type": "group", "direction": "row", "gap": 6, "children": [
                    {"type": "badge", "label": STATUS_LABEL[c.status] if c else i.action.value,
                     "variant": STATUS_VARIANT[c.status] if c else "info"},
                    {"type": "text", "value": f"{i.id} · {_short(c.claim if c else i.category.value, 70)}", "style": "emphasis"}]},
                {"type": "text", "value": _short(i.explanation, 140), "style": "muted"}],
                "action": {"selection": {"action": "view_finding", "audit_id": r.audit_id, "issue_id": i.id}}})
        children += [{"type": "divider"}, {"type": "heading", "value": "Findings · tap for evidence", "level": 3},
                     {"type": "list", "items": items} if items else
                     {"type": "text", "value": "No issues found in the scoped checks.", "style": "muted"}]
    if r.repair and r.repair.repaired_copy:
        children += [{"type": "divider"},
                     {"type": "heading", "value": "Rewrite " + ("(verified by re-audit)" if r.repair_verified else "(unverified)"), "level": 3},
                     {"type": "text", "value": _short(r.repair.repaired_copy, 600)}]
        if r.repair.image_edit_instructions:
            children.append({"type": "text", "value": "Image still needs editing: " +
                             "; ".join(_short(x, 90) for x in r.repair.image_edit_instructions[:3]), "style": "emphasis"})
    children += [{"type": "divider"}, {"type": "text", "value": _short(r.final_decision_basis, 220)},
                 {"type": "text", "value": "Not legal advice or Google Ads approval.", "style": "muted"}]
    can_repair = (o is not None and o.decision == Decision.FIX_REQUIRED and r.repair is None)
    if can_repair:
        children.append({"type": "button", "label": "Repair and re-audit", "primary": True,
                         "action": {"selection": {"action": "repair_reaudit", "audit_id": r.audit_id}}})
    payload = {"root": {"type": "section", "title": "AdProof preflight", "subtitle": f"Audit {r.audit_id}",
                        "children": children}}
    return "custom", payload, bool(o and o.issues) or can_repair


def finding_card(r: AuditReport, issue_id: str) -> tuple[str, dict] | None:
    for v in (r.original_audit, r.revised_audit):
        if not v:
            continue
        issue = next((i for i in v.issues if i.id == issue_id), None)
        if not issue:
            continue
        c = next((x for x in v.claims if x.id == issue.claim_id), None)
        ev = {e.id: e for e in v.evidence}
        rows = [{"label": "Finding", "value": _short(issue.explanation, 220)},
                {"label": "Category", "value": issue.category.value.replace("_", " ").title()},
                {"label": "Where", "value": "Ad image" if issue.source == "image" else "Ad copy"}]
        if c:
            rows.insert(0, {"label": "Claim", "value": _short(c.claim, 200)})
            rows.append({"label": "Status", "value": STATUS_LABEL[c.status]})
            if c.derivation:
                rows.append({"label": "Math", "value": _short(c.derivation, 200)})
            for eid in c.evidence_ids[:2]:
                if eid in ev:
                    rows.append({"label": f"Evidence {eid}", "value": _short(f"“{ev[eid].excerpt}” — {ev[eid].source_url}", 300)})
        rows.append({"label": "Fix", "value": _short(issue.suggested_fix, 200)})
        return "detail", {"title": f"{issue.id} · {issue.category.value.replace('_', ' ').title()}", "summary_rows": rows,
                          "ctas": [{"label": "Back to report", "primary": True,
                                    "selection": {"action": "show_report", "audit_id": r.audit_id}}]}
    return None


def metadata(kind: str, payload: dict, interactive: bool) -> dict[str, str]:
    data = json.dumps(payload)
    if len(data.encode()) > 64 * 1024:
        raise ValueError("card payload over 64 KiB")
    meta = {"card_protocol_version": "1", "requires_card_interaction": "true" if interactive else "false",
            "card_kind": kind, "card_payload": data, "preferred_drawer_width_px": "600"}
    if not interactive:
        meta["is_terminal"] = "true"
    return meta
