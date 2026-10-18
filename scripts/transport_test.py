"""Real three-agent transport test on this machine (no Agentverse needed).

Starts the Verifier, Remediator and Orchestrator as separate processes with throwaway identities, then a
test client agent sends Agent Chat Protocol messages to the orchestrator and checks the replies.
The orchestrator reaches the specialists through actual uAgents messages over localhost.

  python -m scripts.transport_test            # MOCK model (offline, labeled)
  ADPROOF_EXECUTION_MODE=LIVE python -m scripts.transport_test   # real Gemini (needs GEMINI_API_KEY)
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from uagents.crypto import Identity

    env = dict(os.environ)
    env.setdefault("ADPROOF_EXECUTION_MODE", "MOCK")
    tmp = tempfile.mkdtemp(prefix="adproof-transport-")
    env["ADPROOF_STATE_DB"] = f"{tmp}/state.sqlite3"
    env["SENTRY_DSN"] = env.get("SENTRY_DSN", "")
    for role in ("ORCHESTRATOR", "VERIFIER", "REMEDIATOR"):
        env[f"{role}_SEED"] = secrets.token_hex(32)
    client_seed = secrets.token_hex(32)
    client_addr = Identity.from_seed(client_seed, 0).address
    env["ADPROOF_TEST_PEERS"] = json.dumps({client_addr: "http://127.0.0.1:8019/submit"})
    orch_addr = Identity.from_seed(env["ORCHESTRATOR_SEED"], 0).address

    procs = [subprocess.Popen([sys.executable, "-m", f"agents.{r}.main"], cwd=ROOT, env=env,
                              stdout=open(f"{tmp}/{r}.log", "w"), stderr=subprocess.STDOUT)
             for r in ("verifier", "remediator", "orchestrator")]
    try:
        time.sleep(6)
        ok = asyncio.run(_client(client_seed, orch_addr, env["ADPROOF_EXECUTION_MODE"]))
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    for r in ("verifier", "remediator"):
        log = Path(f"{tmp}/{r}.log").read_text()
        handled = log.count("stage_finished") if r == "verifier" else log.count("copy repair") + log.count("Remediator")
        print(f"[{r} log] {len(log.splitlines())} lines; tail:")
        print("\n".join("   " + l for l in log.splitlines()[-4:]))
    print(f"logs: {tmp}")
    return 0 if ok else 1


async def _client(seed: str, orch: str, mode: str) -> bool:
    from uagents import Agent, Context, Protocol
    from uagents.resolver import RulesBasedResolver
    from uagents_core.contrib.protocols.chat import (ChatAcknowledgement, ChatMessage, MetadataContent, TextContent,
                                                     chat_protocol_spec)

    replies: list[tuple[str, dict | None]] = []
    done = asyncio.Event()
    script = ["help", "demo aerobeat", "demo trap"]
    finals_needed = 2

    client = Agent(name="transport_test_client", seed=seed, port=8019, endpoint=["http://127.0.0.1:8019/submit"],
                   resolve=RulesBasedResolver({orch: "http://127.0.0.1:8010/submit"}), publish_agent_details=False)
    proto = Protocol(spec=chat_protocol_spec)
    state = {"finals": 0, "acks": 0}

    def chat(text: str) -> ChatMessage:
        return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=[TextContent(type="text", text=text)])

    @proto.on_message(ChatMessage)
    async def got(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent))
        meta = next((c.metadata for c in msg.content if isinstance(c, MetadataContent)), None)
        replies.append((text, meta))
        if text.startswith("Final:") or "\nFinal:" in text:
            state["finals"] += 1
            if state["finals"] >= finals_needed:
                done.set()

    @proto.on_message(ChatAcknowledgement)
    async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        state["acks"] += 1

    client.include(proto)

    @client.on_event("startup")
    async def start(ctx: Context):
        for text in script:
            await ctx.send(orch, chat(text))
            await asyncio.sleep(1.5 if text == "help" else 0.2)

    async def runner():
        task = asyncio.create_task(client.run_async())
        try:
            await asyncio.wait_for(done.wait(), timeout=150)
        except asyncio.TimeoutError:
            pass
        await client.shutdown() if hasattr(client, "shutdown") else None
        task.cancel()

    try:
        await runner()
    except Exception as exc:
        print("client error:", type(exc).__name__, exc)

    print(f"\n=== transport test ({mode}) — {len(replies)} replies, {state['acks']} acks from orchestrator ===")
    for text, meta in replies:
        first = text.strip().splitlines()[0][:110] if text.strip() else ""
        finals = [l for l in text.splitlines() if l.startswith("Final:")]
        card = f"  [card: {meta.get('card_kind')}]" if meta else ""
        print(f"- {first}{card}")
        for f in finals:
            print(f"    {f[:150]}")
    finals = [l for t, _ in replies for l in t.splitlines() if l.startswith("Final:")]
    ok = len(finals) >= 2 and finals[0].startswith("Final: PASS") and finals[1].startswith("Final: FIX REQUIRED")
    print("RESULT:", "PASS — real agent messages, expected decisions" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
