# Validation status

Only executed checks are marked PASS. Date: 2026-10-17 (PDT).

| Gate | Status | Evidence |
|---|---|---|
| Offline tests (43) | PASS | `python -m pytest` in the build sandbox, Python 3.13 |
| Workflow cases 1–5, 7, 8, 10, 13, 15, 16, 18, 22, 23 offline | PASS | `tests/test_workflow.py`, `tests/test_core_units.py` |
| Chat flow: audit → card → Repair and re-audit → PASS; duplicate message ignored; other users can't read/act; request-ID conflict (cases 11, 20, 24) | PASS | `tests/test_orchestrator_core.py` |
| SafeFetcher live HTTPS fetch from raw.githubusercontent.com | PASS | fetched a public README (text/plain) from the build sandbox |
| Real 3-agent uAgents transport on localhost (MOCK model) | PASS | `python -m scripts.transport_test`: help, demo aerobeat → PASS, demo trap → FIX REQUIRED, verifier received 4 tasks |
| Gemini response schemas accepted by google-genai | PASS | converted with the SDK schema transformer offline |
| Gemini adapter request/validation/retry logic | PASS (mocked SDK) | `tests/test_adapters.py` |
| **Live Gemini image + JSON** | PENDING | needs `GEMINI_API_KEY`: run `python -m adproof.demo --case trap` and record the model name and result here |
| Sentry init, spans, trace propagation, log scrubbing | PASS (offline, fake DSN) | `tests/test_adapters.py` |
| **Sentry Tracing + Logs received in a real project** | PENDING | needs `SENTRY_DSN`; see observability-improvement.md |
| **Agentverse registration + ASI:One discoverability** | PENDING | run `scripts/run_all.sh`, connect mailbox, screenshot |
| **Full workflow inside ASI:One** | PENDING | `demo aerobeat` in asi1.ai; screenshot or shared chat link |
| Judging runtime stays alive without the build session | PENDING | laptop runs `scripts/run_all.sh` |
| Docker/Compose | NOT BUILT | `scripts/run_all.sh` is the supported runtime |
| Restart recovery | PARTIAL | running audits marked `WORKFLOW_INTERRUPTED` on start; no auto-repeat |
