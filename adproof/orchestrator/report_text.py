"""Plain-text report for ASI:One (always sent; cards are an enhancement on top)."""
from __future__ import annotations

from ..domain.models import AuditReport, ClaimStatus, Decision, ExecutionMode, VerificationResult

LABEL = {Decision.PASS: "PASS", Decision.FIX_REQUIRED: "FIX REQUIRED", Decision.BLOCK: "BLOCK",
         Decision.HUMAN_REVIEW: "HUMAN REVIEW"}
DISCLAIMER = ("PASS means only that AdProof's listed checks found no unresolved issue in the supplied sources. "
              "It is not legal advice or Google Ads approval.")


def _findings(v: VerificationResult, limit: int = 5) -> list[str]:
    ev = {e.id: e for e in v.evidence}
    claims = {c.id: c for c in v.claims}
    lines = []
    for i in v.issues[:limit]:
        c = claims.get(i.claim_id or "")
        line = f"• [{i.category.value.replace('_', ' ').title()}] {i.explanation}"
        if c and c.derivation:
            line += f"\n   Math: {c.derivation}"
        for eid in (c.evidence_ids if c else [])[:2]:
            if eid in ev:
                line += f"\n   Page says: “{ev[eid].excerpt}” ({ev[eid].source_url})"
        if i.source == "image":
            line += "\n   Source: the ad image"
        line += f"\n   Fix: {i.suggested_fix}"
        lines.append(line)
    if len(v.issues) > limit:
        lines.append(f"…and {len(v.issues) - limit} more finding(s). Type `report <audit_id>` for all.")
    return lines


def render(report: AuditReport) -> str:
    out = []
    if report.execution_mode != ExecutionMode.LIVE:
        out.append(f"⚠ {report.execution_mode.value} MODE: scripted model, not live Gemini output.")
    o = report.original_audit
    out.append(f"AdProof audit {report.audit_id}")
    if o is None:
        out.append(f"Result: {LABEL[report.final_decision]}. {report.final_decision_basis}")
        out += [f"Error: {e.message}" for e in report.errors[:3]]
        return "\n".join(out)
    supported = sum(1 for c in o.claims if c.status == ClaimStatus.SUPPORTED)
    out.append(f"Original: {LABEL[o.decision]} · {len(o.claims)} claims checked, {supported} supported, "
               f"{len(o.issues)} issue(s)")
    out += _findings(o)
    if report.repair and report.repair.repaired_copy:
        out.append("")
        out.append(f"Proposed rewrite{' (verified)' if report.repair_verified else ' (UNVERIFIED)'}:")
        out.append(f"“{report.repair.repaired_copy}”")
        if report.repair.image_edit_instructions:
            out.append("Image still needs editing (copy changes cannot fix the picture):")
            out += [f"• {x}" for x in report.repair.image_edit_instructions]
    if report.revised_audit:
        r = report.revised_audit
        out.append(f"Re-audit of the rewrite: {LABEL[r.decision]} · {len(r.issues)} issue(s)")
        out += _findings(r, limit=3)
    out.append("")
    out.append(f"Final: {LABEL[report.final_decision]}. {report.final_decision_basis}")
    cov = (report.revised_audit or o).coverage
    out.append("Coverage: " + ", ".join(f"{k.replace('_', ' ')} {getattr(cov, k).status.value}"
                                        for k in ("ad_text", "landing_page", "image", "platform_policy")))
    out.append(DISCLAIMER)
    return "\n".join(out)


def chunks(text: str, size: int = 3500) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size and cur:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts
