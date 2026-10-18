# Setup on the judging laptop

Everything runs on one machine: three Python processes. Agentverse's mailbox routes ASI:One messages to the
orchestrator, but it does **not** keep your processes alive, so the laptop must stay on, online and awake.

## 1. Install

```bash
git clone https://github.com/Khokon0123/AdProof && cd AdProof
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

macOS with python.org Python: if you see `CERTIFICATE_VERIFY_FAILED`, run
`open "/Applications/Python 3.14/Install Certificates.command"` once (use your version number).

## 2. Keys (in `.env`, never committed)

- `GEMINI_API_KEY` from aistudio.google.com. Set `GEMINI_MODEL` to a current Flash model with image input.
- `SENTRY_DSN` from a new Sentry **Python** project (optional but needed for the Sentry track).
- Generate agent identities once: `python -m scripts.init_identities`. Keep `.env` safe: the seeds are the agents'
  identities. Don't paste them anywhere.

Check: `python -m adproof.preflight` (prints READY; shows key status, never values).

## 3. Publish the demo assets

LIVE mode fetches the synthetic page and images from GitHub. After the repo is public on `main`, these must open:
`https://raw.githubusercontent.com/Khokon0123/AdProof/main/data/fixtures/aerobeat.html` (and the three PNGs).
If you use a fork, change `ADPROOF_FIXTURE_BASE_URL` in `.env`.

## 4. Smoke tests

```bash
python -m pytest                               # offline, 43 tests
python -m adproof.demo --case aerobeat         # LIVE Gemini, one process (~6 model calls)
python -m adproof.demo --case trap             # the $49 image trap
python -m scripts.transport_test               # three agents talking over localhost (MOCK model)
```

## 5. Run the agents and connect to Agentverse

```bash
./scripts/run_all.sh
```

1. In the orchestrator log, open the **Agent inspector** link (use normal Chrome; allow local network access if asked).
2. Click **Connect → Mailbox → Finish**. The log should say `Successfully registered as mailbox agent`.
3. Agentverse → My Agents shows **AdProof** as Active / ASI Available.
4. In asi1.ai, chat with the agent and type `demo aerobeat`.

The "not enough funds to register on Almanac contract" warning is harmless; never send funds.

## 6. Sentry evidence

With `SENTRY_DSN` set, run `demo aerobeat` once with `ADPROOF_INSPECTION_CACHE=0` and once with `=1`, then follow
[observability-improvement.md](observability-improvement.md) to record the real trace and log links.
