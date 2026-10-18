"""Synthetic AeroBeat demo campaigns and a local resolver for their public URLs."""
from __future__ import annotations

import uuid
from pathlib import Path

from .domain.models import CampaignInput
from .infrastructure.safe_http import StaticFetcher
from .infrastructure.settings import get_settings

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"
UNSAFE_COPY = ("AeroBeat headphones are completely waterproof. Get 48-hour battery life with noise cancellation off. "
               "Recommended by 1,000 athletes. Now $60—50% off!")
SAFE_COPY = ("Meet AeroBeat AB-01 headphones: splash-resistant, with up to 30 hours of battery life when noise "
             "cancellation is off. Now $60, down from $80—25% off.")
DEMO_CONTEXT = {"platform": "google_ads", "jurisdiction": "US", "language": "en", "audience": "adults",
                "product_category": "electronics"}

CASES = {
    #  name      image file               copy         repair
    "aerobeat": ("aerobeat_neutral.png", UNSAFE_COPY, "repair_once"),
    "trap":     ("aerobeat_price49.png", UNSAFE_COPY, "repair_once"),
    "clean":    ("aerobeat_neutral.png", SAFE_COPY, "repair_once"),
    "blurry":   ("aerobeat_blurry.png", SAFE_COPY, "repair_once"),
    "audit":    ("aerobeat_neutral.png", UNSAFE_COPY, "audit_only"),
}
CASE_HELP = {
    "aerobeat": "unsafe copy + neutral image → FIX REQUIRED → one repair → re-audit",
    "trap": "unsafe copy + image saying 'Only $49' → copy repair cannot fix the image",
    "clean": "already-correct copy → PASS, no repair needed",
    "blurry": "unreadable price in the image → HUMAN REVIEW, no guessing",
    "audit": "audit only, then choose 'Repair and re-audit' yourself",
}


def fixture_url(name: str) -> str:
    return f"{get_settings().fixture_base_url}/{name}"


def demo_input(case: str = "aerobeat") -> CampaignInput:
    image, copy, repair = CASES[case]
    return CampaignInput.model_validate({
        "request_id": f"demo-{case}-{uuid.uuid4().hex[:8]}", "campaign_id": f"aerobeat-{case}", "creative_version": 1,
        "creative": {"image_url": fixture_url(image), "ad_copy": copy},
        "landing_page_url": fixture_url("aerobeat.html"),
        "context": DEMO_CONTEXT,
        "product_context": {"model": "AB-01", "variant": "standard", "currency": "USD", "quantity": 1},
        "repair_mode": repair,
    })


def local_fixture_fetcher() -> StaticFetcher:
    """MOCK/test only: serve the fixture URLs from disk instead of the network."""
    table = {fixture_url("aerobeat.html"): ("text/html", (FIXTURES / "aerobeat.html").read_bytes())}
    for f in ("aerobeat_neutral.png", "aerobeat_price49.png", "aerobeat_blurry.png"):
        table[fixture_url(f)] = ("image/png", (FIXTURES / f).read_bytes())
    return StaticFetcher(table)
