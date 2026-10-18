"""Parse what the user typed in ASI:One: commands, card actions, fenced JSON, or a labeled form."""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

from pydantic import ValidationError

from ..domain.models import CampaignInput

HELP = """AdProof checks an ad before launch: every objective claim against the product page, the image against the copy, then one repair and an independent re-check.

Commands
• demo aerobeat — unsafe copy → findings → one repair → re-audit
• demo trap — image says "Only $49": a copy rewrite cannot fix the picture
• demo clean — already-correct copy → PASS
• demo blurry — unreadable price → HUMAN REVIEW, no guessing
• example — shows the input format
• status <audit_id> / report <audit_id>

Supported scope: Google Ads, US, English, adults, consumer electronics. Public HTTPS image and page URLs on the allowed hosts. Not legal advice or platform approval."""

EXAMPLE = """Send one message in this labeled format (or the same fields as JSON in a ```json block):

image: https://raw.githubusercontent.com/<org>/<repo>/main/data/fixtures/aerobeat_neutral.png
page: https://raw.githubusercontent.com/<org>/<repo>/main/data/fixtures/aerobeat.html
copy: AeroBeat headphones are completely waterproof. Now $60—50% off!
platform: google_ads
jurisdiction: US
language: en
audience: adults
category: electronics
repair: yes

Missing context is not assumed: it is shown in the report and routed to human review."""


@dataclass
class Intent:
    kind: str  # help | example | demo | status | report | audit | action | unknown | invalid
    arg: Optional[str] = None
    campaign: Optional[CampaignInput] = None
    selection: dict = field(default_factory=dict)
    error: Optional[str] = None


_LABELS = {"image": "image_url", "page": "landing_page_url", "landing page": "landing_page_url", "copy": "ad_copy",
           "platform": "platform", "jurisdiction": "jurisdiction", "language": "language", "audience": "audience",
           "category": "product_category", "repair": "repair"}


def _campaign_from_fields(f: dict) -> CampaignInput:
    ctx = {k: f[k] for k in ("platform", "jurisdiction", "language", "audience", "product_category") if f.get(k)}
    return CampaignInput.model_validate({
        "request_id": f.get("request_id") or f"chat-{uuid.uuid4().hex[:10]}",
        "campaign_id": f.get("campaign_id") or "chat-campaign", "creative_version": int(f.get("creative_version") or 1),
        "creative": {"image_url": f.get("image_url"), "ad_copy": f.get("ad_copy", "")},
        "landing_page_url": f.get("landing_page_url", ""), "context": ctx,
        "repair_mode": "repair_once" if str(f.get("repair", "")).lower() in ("yes", "true", "1", "repair_once") else "audit_only",
    })


def parse(text: str) -> Intent:
    t = (text or "").strip()
    low = t.lower()
    # card selections arrive as JSON (direct @mention) or as planner prose
    try:
        data = json.loads(t)
        if isinstance(data, dict) and "action" in data:
            return Intent("action", selection=data)
        if isinstance(data, dict) and ("creative" in data or "ad_copy" in data):
            return _json_campaign(data)
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if m:
        try:
            return _json_campaign(json.loads(m.group(1)))
        except json.JSONDecodeError:
            return Intent("invalid", error="The JSON block could not be read.")
    for act in ("repair_reaudit", "view_finding", "show_report"):
        if act in low:
            sel = {"action": act}
            if a := re.search(r"\b(aud_[0-9a-f]{12})\b", t):
                sel["audit_id"] = a.group(1)
            if i := re.search(r"\b(I\d{1,3})\b", t):
                sel["issue_id"] = i.group(1)
            return Intent("action", selection=sel)
    if low in ("help", "hi", "hello", "start", "?") or low.startswith("help"):
        return Intent("help")
    if low.startswith("example"):
        return Intent("example")
    if m := re.match(r"demo\s*(aerobeat|trap|clean|blurry|audit)?", low):
        return Intent("demo", arg=m.group(1) or "aerobeat")
    if m := re.match(r"(status|report)\s+(aud_[0-9a-f]{12})", low):
        return Intent(m.group(1), arg=m.group(2))
    fields = {}
    for line in t.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            key = _LABELS.get(k.strip().lower())
            if key:
                fields[key] = v.strip()
    if "ad_copy" in fields and "landing_page_url" in fields:
        try:
            return Intent("audit", campaign=_campaign_from_fields(fields))
        except ValidationError as exc:
            return Intent("invalid", error="Some fields are invalid: " + "; ".join(e["msg"] for e in exc.errors()[:3]))
    if "repair" in low and "audit" in low:
        return Intent("action", selection={"action": "repair_reaudit"})
    return Intent("unknown")


def _json_campaign(data: dict) -> Intent:
    try:
        if "creative" in data:
            data.setdefault("request_id", f"chat-{uuid.uuid4().hex[:10]}")
            data.setdefault("campaign_id", "chat-campaign")
            data.setdefault("creative_version", 1)
            return Intent("audit", campaign=CampaignInput.model_validate(data))
        return Intent("audit", campaign=_campaign_from_fields(data))
    except ValidationError as exc:
        return Intent("invalid", error="Some fields are invalid: " + "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3]))
