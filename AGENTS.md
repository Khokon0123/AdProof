# Conventions for anyone (human or AI) changing this repo

- Domain contracts live in `adproof/domain/models.py`. Change them with tests and re-run `python -m scripts.export_schemas`.
- Decisions are made only by `adproof/domain/decision.py`. Models extract and rephrase; they never decide.
- Every cited quote must pass `quote_in_source`; prices and discounts use `adproof/domain/pricing.py` (Decimal).
- LIVE never falls back to MOCK, fixtures or canned repairs. Failures become typed errors and HUMAN REVIEW.
- All three agents import `adproof/transport/messages.py`; do not copy those classes.
- No secrets in git. Seeds come from `scripts/init_identities`; do not rotate them.
- `python -m pytest` must stay offline and green.
