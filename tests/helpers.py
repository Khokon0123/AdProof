"""Offline test helpers: scripted model, local fixtures, direct (non-network) verify/repair calls."""
from __future__ import annotations

import os

os.environ.setdefault("ADPROOF_EXECUTION_MODE", "MOCK")
os.environ["SENTRY_DSN"] = ""

from adproof.demo_inputs import demo_input, local_fixture_fetcher  # noqa: E402
from adproof.domain.models import ExecutionMode  # noqa: E402
from adproof.inspector.inspector import InspectionCache  # noqa: E402
from adproof.mock_model import build_mock_model  # noqa: E402
from adproof.model_client import CallBudget  # noqa: E402
from adproof.orchestrator.workflow import WorkflowDeps  # noqa: E402
from adproof.remediator.remediate import RemediatorDeps, remediate  # noqa: E402
from adproof.verifier.verify import VerifierDeps, verify_campaign  # noqa: E402


def make_deps(model=None, fetcher=None, verify=None, repair=None, limit=20, cache=True):
    model = model or build_mock_model()
    fetcher = fetcher or local_fixture_fetcher()
    budget = CallBudget(limit=limit)

    async def _verify(req):
        return await verify_campaign(req, VerifierDeps(fetcher=fetcher, model=model, budget=budget))

    async def _repair(req):
        return await remediate(req, RemediatorDeps(model=model, budget=budget))

    return WorkflowDeps(fetcher=fetcher, inspector_model=model, verify=verify or _verify, remediate=repair or _repair,
                        mode=ExecutionMode.MOCK, budget=budget, cache=InspectionCache() if cache else None), model, fetcher


__all__ = ["make_deps", "demo_input", "build_mock_model", "local_fixture_fetcher"]
