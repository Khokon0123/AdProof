"""Export JSON Schemas and a valid example from the Pydantic models (single source of truth).
Run: python -m scripts.export_schemas   (a test fails if the committed files are stale)
"""
from __future__ import annotations

import json
from pathlib import Path

from adproof.domain.models import AuditReport, CampaignInput, RepairResult, VerificationResult

OUT = Path(__file__).resolve().parents[1] / "schemas"
EXAMPLE = {
    "schema_version": "1.0", "request_id": "client-generated-id", "campaign_id": "aerobeat-demo", "creative_version": 1,
    "creative": {"image_url": "https://raw.githubusercontent.com/Khokon0123/AdProof/main/data/fixtures/aerobeat_neutral.png",
                 "ad_copy": "AeroBeat headphones are completely waterproof. Get 48-hour battery life with noise "
                            "cancellation off. Recommended by 1,000 athletes. Now $60—50% off!"},
    "landing_page_url": "https://raw.githubusercontent.com/Khokon0123/AdProof/main/data/fixtures/aerobeat.html",
    "context": {"platform": "google_ads", "jurisdiction": "US", "language": "en", "audience": "adults",
                "product_category": "electronics"},
    "evidence_documents": [],
    "product_context": {"model": "AB-01", "variant": "standard", "currency": "USD", "quantity": 1},
    "repair_mode": "repair_once",
}


def render_all() -> dict[str, str]:
    CampaignInput.model_validate(EXAMPLE)
    out = {f"{m.__name__}.schema.json": json.dumps(m.model_json_schema(), indent=2, sort_keys=True) + "\n"
           for m in (CampaignInput, VerificationResult, RepairResult, AuditReport)}
    out["CampaignInput.example.json"] = json.dumps(EXAMPLE, indent=2, ensure_ascii=False) + "\n"
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, text in render_all().items():
        (OUT / name).write_text(text)
        print("wrote", name)


if __name__ == "__main__":
    main()
