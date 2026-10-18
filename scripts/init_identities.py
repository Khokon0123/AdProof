"""Create stable private seeds for the three agents (once) and print their public addresses.

Seeds are written to .env (gitignored). Existing seeds are never rotated.
Run: python -m scripts.init_identities
"""
from __future__ import annotations

import secrets
from pathlib import Path

from uagents.crypto import Identity

ENV = Path(__file__).resolve().parents[1] / ".env"
ROLES = ("ORCHESTRATOR", "VERIFIER", "REMEDIATOR")


def main() -> None:
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    values = dict(l.split("=", 1) for l in lines if "=" in l and not l.lstrip().startswith("#"))
    added = []
    for role in ROLES:
        key = f"{role}_SEED"
        if len(values.get(key, "")) < 32:
            values[key] = secrets.token_hex(32)
            added.append(key)
    for role in ROLES:
        values[f"{role}_ADDRESS"] = Identity.from_seed(values[f"{role}_SEED"], 0).address
    kept = [l for l in lines if not any(l.startswith(f"{r}_SEED=") or l.startswith(f"{r}_ADDRESS=") for r in ROLES)]
    kept += [f"{r}_SEED={values[r + '_SEED']}" for r in ROLES] + [f"{r}_ADDRESS={values[r + '_ADDRESS']}" for r in ROLES]
    ENV.write_text("\n".join(kept) + "\n")
    print("Seeds created:" if added else "Seeds already existed (not rotated).", ", ".join(added))
    for role in ROLES:
        print(f"{role.lower():13s} {values[role + '_ADDRESS']}")
    print("Addresses are public; seeds are private and stay in .env.")


if __name__ == "__main__":
    main()
