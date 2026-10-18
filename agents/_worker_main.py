"""Shared entry for the two specialist agents. They accept tasks ONLY from the configured orchestrator."""
from __future__ import annotations

from pathlib import Path

from uagents import Agent, Context

from adproof.domain.models import RepairRequest, VerifyRequest
from adproof.infrastructure import telemetry
from adproof.infrastructure.settings import get_settings
from adproof.model_client import CallBudget
from adproof.remediator.remediate import RemediatorDeps, remediate
from adproof.runtime import build_fetcher, build_model
from adproof.transport.agent_common import LocalFirstResolver, address_for, local_endpoint, new_loop, seed
from adproof.transport.messages import TaskEnvelope
from adproof.transport.worker import WorkerCore
from adproof.verifier.verify import VerifierDeps, verify_campaign


def build(role: str) -> Agent:
    s = get_settings()
    telemetry.init_telemetry(role, s.sentry_dsn, s.sentry_environment, s.sentry_traces_sample_rate)
    model, fetcher = build_model(s), build_fetcher(s)
    orchestrator = address_for("orchestrator")

    if role == "verifier":
        async def handler(payload: str, budget: CallBudget) -> str:
            req = VerifyRequest.model_validate_json(payload)
            return (await verify_campaign(req, VerifierDeps(fetcher=fetcher, model=model, budget=budget))).model_dump_json()
        core = WorkerCore("verifier", "VERIFY", orchestrator, handler)
    else:
        async def handler(payload: str, budget: CallBudget) -> str:
            req = RepairRequest.model_validate_json(payload)
            return (await remediate(req, RemediatorDeps(model=model, budget=budget))).model_dump_json()
        core = WorkerCore("remediator", "REPAIR", orchestrator, handler)

    endpoint = local_endpoint(role)
    agent = Agent(name=f"adproof_{role}", seed=seed(role), port=int(endpoint.rsplit(":", 1)[1].split("/")[0]),
                  endpoint=[endpoint], loop=new_loop(),
                  resolve=LocalFirstResolver({orchestrator: local_endpoint("orchestrator")}),
                  readme_path=str(Path(__file__).parent / role / "README.md"), publish_agent_details=False,
                  handle_messages_concurrently=True)

    @agent.on_message(model=TaskEnvelope)
    async def on_task(ctx: Context, sender: str, env: TaskEnvelope):
        result = await core.handle(sender, env)
        if result is not None:
            await ctx.send(sender, result)

    @agent.on_event("startup")
    async def startup(ctx: Context):
        ctx.logger.info(f"AdProof {role} {agent.address} | accepts tasks only from {orchestrator[:18]}…")

    return agent
