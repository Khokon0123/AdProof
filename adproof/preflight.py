"""Preflight: shows what is ready without printing any secret.  python -m adproof.preflight"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    from .infrastructure.settings import get_settings

    s = get_settings()
    ok = True
    print(f"Python {sys.version.split()[0]}")
    for mod in ("uagents", "uagents_core", "google.genai", "sentry_sdk", "httpx", "bs4", "PIL", "pydantic"):
        try:
            importlib.import_module(mod)
            print(f"  ✓ {mod}")
        except ImportError:
            ok = False
            print(f"  ✗ {mod} missing (pip install -r requirements.txt)")
    for f in ("aerobeat.html", "aerobeat_neutral.png", "aerobeat_price49.png", "aerobeat_blurry.png"):
        present = (ROOT / "data" / "fixtures" / f).exists()
        ok &= present
        print(f"  {'✓' if present else '✗'} fixture {f}")
    print(f"Execution mode: {s.execution_mode}")
    print(f"  GEMINI_API_KEY: {'set' if s.gemini_api_key else 'NOT SET (LIVE model calls will fail honestly)'}")
    print(f"  GEMINI_MODEL: {s.gemini_model}")
    print(f"  SENTRY_DSN: {'set' if s.sentry_dsn else 'not set (telemetry off; product still works)'}")
    print(f"  Fixture base URL: {s.fixture_base_url}")
    print(f"  Allowed hosts: {', '.join(s.allowed_hosts)}{' (+ any public host)' if s.allow_public_hosts else ''}")
    try:
        from .transport.agent_common import address_for
        for role in ("orchestrator", "verifier", "remediator"):
            print(f"  {role:12s} {address_for(role)}")
    except SystemExit as exc:
        ok = False
        print(f"  ✗ {exc}")
    print("READY" if ok else "NOT READY: fix the ✗ items above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
