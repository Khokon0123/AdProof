# Policy scope

**Required implemented checks (rule pack `google_ads_us_electronics_v1`, engineering checks, not legal rules):**
price consistency with the landing page, discount arithmetic, ad-vs-page factual consistency, endorsement
substantiation present, image price consistency.

**Platform and legal sources (DRAFT, never used for decisions):** Google Ads Misrepresentation, Dishonest pricing
practices, Unreliable claims; FTC advertising substantiation statement; FTC endorsements guidance. URLs are in
`data/policies/catalog.json`. Sections and excerpts are intentionally empty until a human selects and reviews them.
No rule is ACTIVE, so this build never returns BLOCK on live input; BLOCK precedence is tested with synthetic rules.

**Not implemented:** health/medical substantiation (routed to human review), environmental claims review, AI-content
disclosure rules (disabled: no universal requirement is assumed), multilingual ads, other platforms or countries,
supporting-document reading.
