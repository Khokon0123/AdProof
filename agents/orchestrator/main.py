"""AdProof Orchestrator: the public ASI:One agent (Agent Chat Protocol, mailbox)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, EndSessionContent,
                                                 MetadataContent, StartSessionContent, TextContent,
                                                 chat_protocol_spec)

from adproof.infrastructure import telemetry
from adproof.infrastructure.settings import get_settings
from adproof.transport.agent_common import LocalFirstResolver, address_for, local_endpoint, new_loop, seed
from adproof.transport.messages import TaskResult
from adproof.transport.orchestrator_core import OrchestratorCore
from adproof.transport.store import Store

settings = get_settings()
telemetry.init_telemetry("orchestrator", settings.sentry_dsn, settings.sentry_environment,
                         settings.sentry_traces_sample_rate)
VERIFIER, REMEDIATOR = address_for("verifier"), address_for("remediator")
RULES = {VERIFIER: local_endpoint("verifier"), REMEDIATOR: local_endpoint("remediator")}
# Local transport tests only: extra peers as JSON {address: endpoint}. Empty in normal runs.
RULES.update(json.loads(os.environ.get("ADPROOF_TEST_PEERS", "{}") or "{}"))

agent = Agent(
    name="AdProof",
    seed=seed("orchestrator"),
    port=int(local_endpoint("orchestrator").rsplit(":", 1)[1].split("/")[0]),
    mailbox=True,
    loop=new_loop(),
    resolve=LocalFirstResolver(RULES),
    readme_path=str(Path(__file__).with_name("README.md")),
    description="Checks an ad's claims against the product page and image before launch, repairs it once, re-checks it.",
    publish_agent_details=True,
    handle_messages_concurrently=True,
)
core = OrchestratorCore(settings, Store(settings.state_db), VERIFIER, REMEDIATOR)
chat = Protocol(spec=chat_protocol_spec)


def _msg(text: str, meta: dict | None) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if meta:
        content.append(MetadataContent(type="metadata", metadata=meta))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    # Always acknowledge (also for duplicates); never acknowledge acknowledgements.
    await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    if any(isinstance(c, EndSessionContent) for c in msg.content):
        return
    text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    if not text and any(isinstance(c, StartSessionContent) for c in msg.content):
        text = "help"
    if not text:
        return

    async def reply(body: str, meta: dict | None) -> None:
        await ctx.send(sender, _msg(body, meta))

    async def send_and_receive(dest, message, response_type=TaskResult, timeout=30):
        return await ctx.send_and_receive(dest, message, response_type=response_type, timeout=timeout)

    await core.handle(sender, str(msg.msg_id), text, send_and_receive, reply)


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@agent.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"AdProof orchestrator {agent.address} | mode={core.mode.value} | verifier={VERIFIER[:18]}… "
                    f"remediator={REMEDIATOR[:18]}…")


agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
