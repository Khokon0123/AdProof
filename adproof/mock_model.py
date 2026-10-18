"""MOCK model: deterministic stand-in for Gemini, for offline tests and the clearly labeled MOCK demo.

It knows the three synthetic AeroBeat images by hash and applies simple keyword rules to text.
It is NOT a model benchmark and is never used in LIVE mode.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .model_client import ScriptedModel

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"

_IMAGE_OBS = {
    "aerobeat_neutral.png": {"readable": True, "items": [
        {"kind": "visible_text", "text": "AeroBeat AB-01", "region": "top-left"},
        {"kind": "visible_text", "text": "Wireless noise-cancelling headphones", "region": "bottom"},
        {"kind": "visible_text", "text": "Splash-resistant · Foldable · Bluetooth 5.3", "region": "bottom"},
        {"kind": "visual_observation", "text": "Illustration of over-ear headphones", "region": "center"}]},
    "aerobeat_price49.png": {"readable": True, "items": [
        {"kind": "visible_text", "text": "AeroBeat AB-01", "region": "top-left"},
        {"kind": "visible_text", "text": "Only $49", "region": "top-right"},
        {"kind": "inferred_claim", "text": "The headphones cost $49", "region": "top-right"},
        {"kind": "visible_text", "text": "Wireless noise-cancelling headphones", "region": "bottom"}]},
    "aerobeat_blurry.png": {"readable": False, "unreadable_reason": "The red price badge is too blurry to read.",
                            "items": [{"kind": "visible_text", "text": "AeroBeat AB-01", "region": "top-left"},
                                      {"kind": "visual_observation", "text": "A red badge with unreadable text",
                                       "region": "top-right", "uncertainty": "text not legible"}]},
}


def _image_table() -> dict[str, dict]:
    """Map model-input hash (after our PNG re-encode) -> observations."""
    from .infrastructure.content import freeze_image

    table = {}
    for name, obs in _IMAGE_OBS.items():
        p = FIXTURES / name
        if p.exists():
            _, model_bytes = freeze_image(p.read_bytes(), name)
            table[hashlib.sha256(model_bytes).hexdigest()] = obs
    return table


def _between(prompt: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.S)
    return m.group(1) if m else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def build_mock_model() -> ScriptedModel:
    images = _image_table()

    def inspect(prompt, image):
        h = hashlib.sha256(image or b"").hexdigest()
        if h not in images:
            from .model_client import ModelError
            return ModelError("MODEL_ERROR", "MOCK model only knows the synthetic AeroBeat images.")
        return images[h]

    def page_facts(prompt, image):
        page = _between(prompt, "page")
        cur = re.search(r"(Now \$(\d+(?:\.\d{2})?))", page)
        ref = re.search(r"(regular price \$(\d+(?:\.\d{2})?))", page)
        return {"current_price": {"found": bool(cur), "amount": cur.group(2) if cur else "", "currency": "USD",
                                  "quote": cur.group(1) if cur else ""},
                "reference_price": {"found": bool(ref), "amount": ref.group(2) if ref else "", "currency": "USD",
                                    "quote": ref.group(1) if ref else ""},
                "product_model": "AB-01" if "AB-01" in page else ""}

    def extract_claims(prompt, image):
        ad = _between(prompt, "ad")
        claims = []
        for s in _sentences(ad):
            low = s.lower()
            if re.search(r"\$\d|% off", low) and not re.search(r"hour|waterproof|recommend", low):
                continue  # prices/discounts are checked deterministically
            if "recommended by" in low or "athlete" in low or "endorsed" in low:
                t = "endorsement"
            elif "clinically" in low or "health" in low:
                t = "health"
            elif "hour" in low or "battery" in low:
                t = "quantitative_specification"
            elif "waterproof" in low or "splash" in low:
                t = "performance"
            elif "best" in low or "amazing" in low or "meet " in low:
                claims.append({"text": s, "claim_type": "other_objective", "puffery": True, "reason": "Subjective or introductory."})
                continue
            else:
                t = "other_objective"
            # strip any trailing price fragment from mixed sentences
            claims.append({"text": re.sub(r"\s*(now|only)?\s*\$\d.*$", "", s, flags=re.I).strip(" ,—-") or s,
                           "claim_type": t})
        return {"claims": claims}

    def entail(prompt, image):
        page = _between(prompt, "page")
        lines = [l for l in _between(prompt, "claims").splitlines() if l.strip()]
        results = []
        for line in lines:
            m = re.match(r"(\d+)\.\s*\[(\w+)\]\s*(.*)", line)
            if not m:
                continue
            idx, text = int(m.group(1)), m.group(3).lower()
            r = {"index": idx, "status": "INSUFFICIENT_EVIDENCE", "quote": "", "conditions": "",
                 "explanation": "The page does not establish this."}
            if "waterproof" in text and "not waterproof" in page.lower() and "not waterproof" not in text:
                r.update(status="CONTRADICTED", quote="Not waterproof", explanation="The page says the headphones are not waterproof.")
            elif "splash" in text and "Splash-resistant" in page:
                r.update(status="SUPPORTED", quote="Splash-resistant (IPX4)", explanation="The page states splash resistance.")
            elif "hour" in text:
                hours = re.search(r"(\d+)[- ]hour", text)
                q = "Up to 30 hours of battery life with noise cancellation off"
                if q.lower() in page.lower():
                    if hours and hours.group(1) == "30" and "noise cancellation off" in text:
                        r.update(status="SUPPORTED", quote=q, conditions="up to; noise cancellation off",
                                 explanation="Matches the page under the same condition.")
                    elif hours and hours.group(1) != "30":
                        r.update(status="CONTRADICTED", quote=q, conditions="up to; noise cancellation off",
                                 explanation=f"The page says up to 30 hours, not {hours.group(1)} hours.")
            results.append(r)
        return {"results": results}

    def repair(prompt, image):
        issues = _between(prompt, "issues")
        ids = re.findall(r"^(I\d+)", issues, re.M)
        return {"repaired_copy": "Meet AeroBeat AB-01 headphones: splash-resistant, with up to 30 hours of battery "
                                 "life when noise cancellation is off. Now $60, down from $80—25% off.",
                "changes": [{"issue_ids": ids, "before": _between(prompt, "ad")[:200],
                             "after": "Meet AeroBeat AB-01 headphones: splash-resistant, with up to 30 hours..."}]}

    return ScriptedModel({"inspect": inspect, "page_facts": page_facts, "extract_claims": extract_claims,
                          "entail": entail, "repair": repair}, name="mock-model")
