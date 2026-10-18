![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# AdProof — check an ad before launch

AdProof is a preflight agent for AI-generated advertising. Send it an ad image, the ad copy and the product page. It:

- splits the copy into objective claims and checks each one against the product page, with exact quotes
- reads the image with Gemini and checks prices and claims in the picture against the page
- does price and discount math deterministically (for example $80 → $60 is 25% off, not 50%)
- proposes one minimal rewrite, then independently re-audits the rewritten ad
- tells you when a copy rewrite cannot fix the problem because the image itself is wrong

Try: `demo aerobeat`, `demo trap`, `demo clean`, `demo blurry`, `help`, `example`.
Ask things like "check my ad before launch", "verify the claims in this ad", "is this discount correct".

Supported scope: Google Ads, US, English, adult audiences, consumer electronics. Public HTTPS sources on allowed hosts.
Decisions: PASS, FIX REQUIRED, BLOCK, HUMAN REVIEW. PASS covers only the listed checks; it is not legal advice or Google Ads approval.

Works with two specialist agents: AdProof Verifier (claims and evidence) and AdProof Remediator (minimal rewrites).
