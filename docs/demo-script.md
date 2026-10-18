# 3:00 demo script

**0:00–0:20 — Problem and scope.** "AI can generate a thousand ads in a minute. Nobody checks whether they're true.
AdProof is a preflight agent in ASI:One that checks an ad's claims against the product page and the image before
launch. Scope today: Google Ads, US, consumer electronics."

**0:20–1:05 — Audit (ASI:One).** Type `demo audit`. Show the card: waterproof contradicted ("Not waterproof"),
48 hours contradicted ("Up to 30 hours … with noise cancellation off"), athletes: no evidence, $60 supported,
50% off contradicted. Tap the discount finding: "(80 − 60) / 80 × 100 = 25%". "The math is code, not a model."

**1:05–1:40 — One repair, independent re-audit.** Tap **Repair and re-audit**. Show the rewrite and the new decision:
PASS. "The Remediator only proposes. The Verifier re-checks the new version from scratch."

**1:40–2:15 — The $49 trap.** Type `demo trap`. Same copy fix, but the image says "Only $49". Final: still FIX REQUIRED,
with an image-edit instruction. "Rewriting copy can't fix a picture. Most AI checkers would call this fixed."

**2:15–2:40 — Real agents and Sentry.** Show Agentverse (three agents), then the Sentry trace for one audit: spans in
the orchestrator, Verifier and Remediator under one trace, plus the before/after inspection-cache result.

**2:40–3:00 — Honesty and next steps.** "Every finding cites the page; we abstain on blurry images; PASS is scoped,
not legal approval. Built with Devin and Claude during the event. Next: more categories and reviewed policy rules."

Backup: `demo blurry` shows HUMAN REVIEW (no guessing). If Wi-Fi fails, use the recorded video.
