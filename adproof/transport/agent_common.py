"""Shared uAgents bootstrap: event loop (needed on Python 3.12+), identities, local-first resolver."""
from __future__ import annotations

import asyncio
import os
import sys

from uagents.crypto import Identity
from uagents.resolver import GlobalResolver, Resolver

PORTS = {"orchestrator": 8010, "verifier": 8011, "remediator": 8012}


def new_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def seed(role: str) -> str:
    value = os.environ.get(f"{role.upper()}_SEED", "")
    if len(value) < 32:
        sys.exit(f"{role.upper()}_SEED is missing or too short. Run `python -m scripts.init_identities` once; "
                 "it writes private seeds into .env (never commit it).")
    return value


def address_for(role: str) -> str:
    return Identity.from_seed(seed(role), 0).address


def local_endpoint(role: str) -> str:
    host = os.environ.get("ADPROOF_LOCAL_HOST", "127.0.0.1")
    port = int(os.environ.get(f"{role.upper()}_PORT", PORTS[role]))
    return f"http://{host}:{port}/submit"


class LocalFirstResolver(Resolver):
    """Team agents on this machine resolve to localhost; everyone else (ASI:One users) via Agentverse/Almanac."""

    def __init__(self, rules: dict[str, str]):
        self._rules = rules
        self._global = GlobalResolver()

    async def resolve(self, destination: str) -> tuple[str | None, list[str]]:
        if destination in self._rules:
            return destination, [self._rules[destination]]
        return await self._global.resolve(destination)
