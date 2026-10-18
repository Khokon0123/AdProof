# Observability-driven improvement (Sentry Tracing + Logs)

Status: **instrumentation done and tested offline; live evidence PENDING** until a real Sentry project receives data.
Fill in the links below only from real Sentry data. Do not invent numbers.

## What is instrumented

- **Tracing:** one transaction per audit in the orchestrator, continued in the Verifier and Remediator via
  `sentry-trace` + `baggage` carried in the task envelope (`trace_json`). Spans: image fetch/decode, Gemini inspection
  (`gen_ai.generate`), dispatch to specialists, landing page fetch, price facts, claim extraction, entailment, repair.
- **Logs (Sentry Logs product):** `audit_started`, `stage_finished`, `task_sent`, `retry_scheduled`,
  `duplicate_ignored`, `task_timed_out`, `result_rejected`, `audit_completed`. Only safe fields (IDs, stage, decision,
  durations). Ad copy, prompts, page text, image bytes and keys are never sent (`_scrub_log` + allowlisted keys).

## The improvement to verify: repeated image inspection during re-audit

A repaired candidate keeps the **same image bytes** (same SHA-256). Without caching, the re-audit sends the same image
to Gemini again: a second `gemini.inspect` span inside the same audit trace, adding seconds and a paid call while the
image-only observations cannot have changed. With `ADPROOF_INSPECTION_CACHE=1`, image-only observations are reused by
exact hash + model + prompt version, while every copy check is recomputed.

### Procedure (run on the laptop, LIVE, SENTRY_DSN set)

1. `ADPROOF_INSPECTION_CACHE=0 python -m adproof.demo --case aerobeat`
2. `ADPROOF_INSPECTION_CACHE=1 python -m adproof.demo --case aerobeat`
3. In Sentry → Traces, open both `adproof.demo` traces. Count `gen_ai.generate gemini.inspect` spans and note the
   total duration. In Sentry → Logs, filter `stage_finished stage:inspect` and compare `cache_hit`.

### Evidence (fill in from real data)

| | Before (cache off) | After (cache on) |
|---|---|---|
| Trace link | PENDING | PENDING |
| `gemini.inspect` spans per audit | PENDING | PENDING |
| Total audit duration | PENDING | PENDING |
| Model calls (`model calls used`) | PENDING | PENDING |

Regression test: `tests/test_workflow.py::test_case2_one_repair_then_independent_reaudit_passes` asserts one
inspection call per audit with the same image.

Caveat: we built the cache while designing the re-audit, and Sentry is used here to measure and confirm the effect,
not to claim an incident we did not have.
