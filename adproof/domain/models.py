"""Canonical AdProof data contracts (Pydantic v2).

One source of truth: every agent, the transport layer, the cards and the
JSON Schema export use these models.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ enums
class Decision(str, Enum):
    PASS = "PASS"
    FIX_REQUIRED = "FIX_REQUIRED"
    BLOCK = "BLOCK"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ClaimType(str, Enum):
    price = "price"
    discount = "discount"
    quantitative_specification = "quantitative_specification"
    performance = "performance"
    health = "health"
    comparison = "comparison"
    endorsement = "endorsement"
    guarantee = "guarantee"
    environmental = "environmental"
    urgency_scarcity = "urgency_scarcity"
    other_objective = "other_objective"


class IssueCategory(str, Enum):
    UNSUPPORTED_OBJECTIVE_CLAIM = "UNSUPPORTED_OBJECTIVE_CLAIM"
    PRICE_DISCOUNT_MISMATCH = "PRICE_DISCOUNT_MISMATCH"
    UNVERIFIED_ENDORSEMENT = "UNVERIFIED_ENDORSEMENT"
    MISSING_REQUIRED_DISCLOSURE = "MISSING_REQUIRED_DISCLOSURE"
    AD_LANDING_PAGE_CONTRADICTION = "AD_LANDING_PAGE_CONTRADICTION"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Action(str, Enum):
    FIX = "FIX"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class CoverageStatus(str, Enum):
    CHECKED = "CHECKED"
    PARTIAL = "PARTIAL"
    NOT_CHECKED = "NOT_CHECKED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class InspectionStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_PROVIDED = "NOT_PROVIDED"


class Phase(str, Enum):
    ORIGINAL = "ORIGINAL"
    REPAIRED = "REPAIRED"


class ExecutionMode(str, Enum):
    LIVE = "LIVE"
    MOCK = "MOCK"
    TRANSPORT_TEST = "TRANSPORT_TEST"


class WorkflowStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# ------------------------------------------------------------------ intake
class Creative(Strict):
    image_url: Optional[str] = None
    ad_copy: str = Field(min_length=1, max_length=4096)


class CampaignContext(Strict):
    platform: Optional[str] = None
    jurisdiction: Optional[str] = None
    language: Optional[str] = None
    audience: Optional[str] = None
    product_category: Optional[str] = None


class EvidenceDocument(Strict):
    document_id: str
    name: str
    url: str
    source_type: Literal["html", "text"] = "html"


class ProductContext(Strict):
    model: Optional[str] = None
    variant: Optional[str] = None
    currency: Optional[str] = None
    quantity: Optional[int] = None


class CampaignInput(Strict):
    schema_version: str = SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    campaign_id: str = Field(min_length=1, max_length=128)
    creative_version: int = Field(ge=1)
    creative: Creative
    landing_page_url: str
    context: CampaignContext = CampaignContext()
    evidence_documents: list[EvidenceDocument] = Field(default_factory=list, max_length=3)
    product_context: ProductContext = ProductContext()
    repair_mode: Literal["audit_only", "repair_once"] = "audit_only"

    @field_validator("evidence_documents")
    @classmethod
    def unique_doc_ids(cls, v):
        ids = [d.document_id for d in v]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence document IDs must be unique")
        return v


# ------------------------------------------------------------------ candidates + inspection
class FrozenImage(Strict):
    source_image_sha256: str
    model_input_sha256: str
    source_url: str
    width: int
    height: int
    source_format: str
    transformation: str = "decoded, metadata stripped, re-encoded as PNG"


class CreativeCandidate(Strict):
    campaign_id: str
    candidate_id: str
    creative_version: int
    phase: Phase
    ad_copy: str
    image: Optional[FrozenImage] = None
    context: CampaignContext
    product_context: ProductContext = ProductContext()
    created_at: datetime = Field(default_factory=utcnow)


class Observation(Strict):
    observation_id: str
    kind: Literal["visible_text", "visual_observation", "inferred_claim"]
    text: str
    region: Optional[str] = None
    uncertainty: Optional[str] = None


class TypedError(Strict):
    code: str
    message: str
    stage: str
    retryable: bool = False


class InspectionResult(Strict):
    candidate_id: str
    image_sha256: Optional[str]
    model: Optional[str]
    prompt_version: str
    status: InspectionStatus
    observations: list[Observation] = Field(default_factory=list)
    readable: Optional[bool] = None
    uncertainty: Optional[str] = None
    errors: list[TypedError] = Field(default_factory=list)
    cache_hit: bool = False


# ------------------------------------------------------------------ verification
class Evidence(Strict):
    id: str
    source_url: str
    excerpt: str
    source_type: Literal["seller_product_information", "substantiation", "policy_text"]
    retrieved_at: datetime
    document_id: Optional[str] = None
    snapshot_id: str
    content_sha256: str
    locator: Optional[str] = None


class Claim(Strict):
    id: str
    claim: str
    source: Literal["ad_text", "image"]
    claim_type: ClaimType
    status: ClaimStatus
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str
    observation_id: Optional[str] = None
    conditions: Optional[str] = None
    uncertainty: Optional[str] = None
    derivation: Optional[str] = None
    landing_page_consistency: Literal["MATCH", "MISMATCH", "NOT_FOUND", "NOT_ASSESSED"] = "NOT_ASSESSED"
    evidence_quality: Literal["DIRECT", "QUALIFIED", "WEAK", "NONE"] = "NONE"
    confidence: Optional[float] = None


class Issue(Strict):
    id: str
    claim_id: Optional[str]
    category: IssueCategory
    subtype: Optional[str] = None
    severity: Severity
    explanation: str
    suggested_fix: str
    action: Action
    source: Literal["ad_text", "image", "process"] = "ad_text"
    policy_reference: Optional[str] = None


class CoverageItem(Strict):
    status: CoverageStatus
    reason: Optional[str] = None


class Coverage(Strict):
    ad_text: CoverageItem
    landing_page: CoverageItem
    supporting_documents: CoverageItem
    image: CoverageItem
    platform_policy: CoverageItem


class PolicyCheck(Strict):
    rule_id: str
    applicable: bool
    violated: Optional[bool]
    status: Literal["ACTIVE", "DRAFT", "DISABLED"]
    note: str


class IgnoredStatement(Strict):
    text: str
    reason: str


class Metrics(Strict):
    model_calls: int = 0
    cache_hits: int = 0
    fetches: int = 0
    duration_ms: int = 0


class VerificationResult(Strict):
    schema_version: str = SCHEMA_VERSION
    audit_id: str
    campaign_id: str
    candidate_id: str
    creative_version: int
    phase: Phase
    decision: Decision
    audit_complete: bool
    evidence_scope: str
    scope_notes: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    coverage: Coverage
    policy_checks: list[PolicyCheck] = Field(default_factory=list)
    policy_catalog_version: str
    errors: list[TypedError] = Field(default_factory=list)
    ignored_statements: list[IgnoredStatement] = Field(default_factory=list)
    metrics: Metrics = Metrics()


class VerifyRequest(Strict):
    audit_id: str
    candidate: CreativeCandidate
    landing_page_url: str
    evidence_documents: list[EvidenceDocument] = Field(default_factory=list)
    inspection: InspectionResult
    deadline_epoch: float


# ------------------------------------------------------------------ repair + report
class CopyChange(Strict):
    issue_ids: list[str]
    before: str
    after: str


class RepairRequest(Strict):
    audit_id: str
    candidate: CreativeCandidate
    verification: VerificationResult
    deadline_epoch: float


class RepairResult(Strict):
    audit_id: str
    original_candidate_id: str
    candidate_id: str
    repaired_copy: Optional[str]
    changes: list[CopyChange] = Field(default_factory=list)
    unresolved_issue_ids: list[str] = Field(default_factory=list)
    image_edit_instructions: list[str] = Field(default_factory=list)
    model: Optional[str] = None
    prompt_version: str
    errors: list[TypedError] = Field(default_factory=list)


class AuditReport(Strict):
    schema_version: str = SCHEMA_VERSION
    audit_id: str
    execution_mode: ExecutionMode
    workflow_status: WorkflowStatus
    scope: str
    original_candidate: Optional[CreativeCandidate]
    original_inspection: Optional[InspectionResult]
    original_audit: Optional[VerificationResult]
    repair: Optional[RepairResult] = None
    revised_candidate: Optional[CreativeCandidate] = None
    revised_audit: Optional[VerificationResult] = None
    selected_candidate_id: Optional[str]
    final_decision: Decision
    final_decision_basis: str
    repair_verified: bool = False
    errors: list[TypedError] = Field(default_factory=list)
    model: Optional[str] = None
    policy_catalog_version: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    model_calls: int = 0
