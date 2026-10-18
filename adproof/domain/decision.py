"""Deterministic decision precedence. No LLM is involved here.

1. BLOCK only when an ACTIVE, reviewed blocking rule's predicate is established.
   (Critical severity alone never blocks.)
2. HUMAN_REVIEW for material uncertainty, failed/incomplete required processing,
   invalid evidence references, unsupported scope, or a REVIEW action.
3. FIX_REQUIRED for established repairable issues.
4. PASS only when every required scoped check completed with no unresolved issue.
"""
from __future__ import annotations

from .models import Action, Coverage, CoverageStatus, Decision, Issue, PolicyCheck, TypedError

# Coverage items that must be CHECKED (or legitimately NOT_APPLICABLE) for a scoped decision.
REQUIRED_COVERAGE = ("ad_text", "landing_page", "supporting_documents", "image")


def decide(*, issues: list[Issue], coverage: Coverage, policy_checks: list[PolicyCheck],
           errors: list[TypedError], scope_supported: bool) -> tuple[Decision, list[str]]:
    reasons: list[str] = []

    blocking = [p for p in policy_checks if p.status == "ACTIVE" and p.applicable and p.violated]
    active_ids = {p.rule_id for p in policy_checks if p.status == "ACTIVE"}
    # An issue may only BLOCK when it cites an ACTIVE rule; otherwise BLOCK degrades to review below.
    rule_blocks = [i for i in issues if i.action == Action.BLOCK and i.policy_reference in active_ids]
    if blocking or rule_blocks:
        reasons.append("An active reviewed blocking rule is established.")
        return Decision.BLOCK, reasons

    if not scope_supported:
        reasons.append("Campaign context is outside the supported scope or incomplete.")
    for name in REQUIRED_COVERAGE:
        item = getattr(coverage, name)
        if item.status not in (CoverageStatus.CHECKED, CoverageStatus.NOT_APPLICABLE):
            reasons.append(f"Required check '{name}' is {item.status.value}: {item.reason or 'no reason given'}.")
    if errors:
        reasons.append(f"{len(errors)} processing error(s): " + "; ".join(e.code for e in errors[:4]))
    review_issues = [i for i in issues if i.action in (Action.REVIEW, Action.BLOCK)]
    if review_issues:
        reasons.append(f"{len(review_issues)} finding(s) need human judgment.")
    if reasons:
        return Decision.HUMAN_REVIEW, reasons

    fixable = [i for i in issues if i.action == Action.FIX]
    if fixable:
        return Decision.FIX_REQUIRED, [f"{len(fixable)} established, repairable issue(s)."]
    return Decision.PASS, ["All required scoped checks completed with no unresolved issues."]
