"""Run the whole workflow in one process (no agents) — for quick checks and the live smoke test.

  python -m adproof.demo --case aerobeat            # uses ADPROOF_EXECUTION_MODE (LIVE by default)
  python -m adproof.demo --case trap --mode mock    # offline, scripted model, clearly labeled MOCK
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os


async def main_async(case: str, as_json: bool) -> int:
    from .demo_inputs import demo_input
    from .infrastructure import telemetry
    from .infrastructure.settings import get_settings
    from .inspector.inspector import InspectionCache
    from .model_client import CallBudget
    from .orchestrator.report_text import render
    from .orchestrator.workflow import WorkflowDeps, run_audit
    from .remediator.remediate import RemediatorDeps, remediate
    from .runtime import build_fetcher, build_model, execution_mode
    from .verifier.verify import VerifierDeps, verify_campaign

    s = get_settings()
    telemetry.init_telemetry("demo", s.sentry_dsn, s.sentry_environment, s.sentry_traces_sample_rate)
    model, fetcher = build_model(s), build_fetcher(s)
    budget = CallBudget(limit=s.max_model_calls)

    async def verify(req):
        return await verify_campaign(req, VerifierDeps(fetcher=fetcher, model=model, budget=budget))

    async def repair(req):
        return await remediate(req, RemediatorDeps(model=model, budget=budget))

    async def progress(t):
        print(f"… {t}")

    deps = WorkflowDeps(fetcher=fetcher, inspector_model=model, verify=verify, remediate=repair,
                        mode=execution_mode(s), budget=budget,
                        cache=InspectionCache() if s.inspection_cache else None,
                        deadline_s=s.audit_deadline_s, progress=progress)
    with telemetry.transaction("adproof.demo", "adproof.audit", role="demo"):
        report = await run_audit(demo_input(case), deps)
    print(report.model_dump_json(indent=2) if as_json else render(report))
    print(f"\nmodel calls used: {budget.used}/{budget.limit}")
    telemetry.flush()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="aerobeat", choices=["aerobeat", "trap", "clean", "blurry", "audit"])
    ap.add_argument("--mode", choices=["live", "mock"], help="override ADPROOF_EXECUTION_MODE")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.mode:
        os.environ["ADPROOF_EXECUTION_MODE"] = a.mode.upper()
    raise SystemExit(asyncio.run(main_async(a.case, a.json)))


if __name__ == "__main__":
    main()
