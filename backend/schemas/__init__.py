from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


class CustomerCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str


class CustomerLogin(BaseModel):
    email: EmailStr
    password: str


class CustomerResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str

    model_config = {"from_attributes": True}


class CustomerUpdate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=120)


class AgentCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=6)
    invite_code: str = Field(..., min_length=1)
    department: Optional[str] = None


class AgentLogin(BaseModel):
    email: EmailStr
    password: str


class AgentResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    department: Optional[str] = None

    model_config = {"from_attributes": True}


class AgentUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=120)
    department: Optional[str] = None


class InsurerLogin(BaseModel):
    email: EmailStr
    password: str


class InsurerResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    department: Optional[str] = None

    model_config = {"from_attributes": True}


class InsurerUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=120)
    department: Optional[str] = None


class InsurerClaimListItem(BaseModel):
    id: int
    claim_id: str
    status: str
    claim_amount: float
    customer_id: int
    customer_name: str
    customer_email: str
    policy_type: Optional[str] = None
    policy_number: Optional[str] = None
    assigned_agent: Optional[str] = None
    escalation_flags: list[str] = []
    escalation_messages: list[str] = []
    created_at: datetime
    updated_at: datetime
    approval_probability: Optional[float] = None
    fraud_score: Optional[float] = None
    payable_amount: Optional[float] = None
    document_count: int = 0
    has_document_issues: bool = False


class InsurerDashboardStatsResponse(BaseModel):
    pending_decision: int
    approved_total: int
    rejected_total: int
    total_approved_payout: float
    recent_submissions: list[InsurerClaimListItem] = []


# --------------------------------------------------------------------------- #
# Data Lakehouse — Book of Business (Phase 4). Sourced from PolicyRiskSignal,
# ingested from the CDE claims-analytics gold table (cde/README.md) via
# scripts/ingest_lakehouse.py. See services/policy_risk_service.py for the
# single query path shared with the claim-insights risk card below.
# --------------------------------------------------------------------------- #
class PolicyRiskSignalSummary(BaseModel):
    total_claims_count: int
    claims_count_12m: int
    total_claimed_amount: float
    avg_claim_amount: float
    amount_vs_segment_avg_pct: Optional[float] = None
    claim_frequency_percentile: Optional[float] = None
    linked_high_risk_garage: bool
    fraud_risk_score: float
    claim_risk_band: str
    source: str
    ingested_at: datetime


class BookOfBusinessPolicyItem(BaseModel):
    policy_id: int
    policy_number: str
    customer_name: str
    customer_email: str
    provider_name: Optional[str] = None
    policy_type: str
    status: str
    coverage_limit: float
    premium_amount: float
    covered_make: Optional[str] = None
    covered_model: Optional[str] = None
    risk: Optional[PolicyRiskSignalSummary] = None


class BookOfBusinessStatsResponse(BaseModel):
    total_policies: int
    low_count: int
    medium_count: int
    high_count: int
    high_risk_garage_linked_count: int
    avg_fraud_risk_score: float


class InsurerDecisionSubmit(BaseModel):
    action: str = Field(..., description="APPROVED or REJECTED")
    notes: Optional[str] = None
    payable_amount: Optional[float] = Field(None, ge=0)


class AgentPublicResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    department: Optional[str] = None


class AssignAgentRequest(BaseModel):
    agent_name: Optional[str] = Field(None, min_length=1)
    agent_id: Optional[int] = None


class AgentClaimListItem(BaseModel):
    id: int
    claim_id: str
    status: str
    claim_amount: float
    customer_id: int
    customer_name: str
    customer_email: str
    policy_type: Optional[str] = None
    escalation_flags: list[str] = []
    escalation_messages: list[str] = []
    assigned_at: Optional[datetime] = None
    created_at: datetime
    fraud_score: Optional[float] = None
    approval_probability: Optional[float] = None
    document_count: int = 0
    has_document_issues: bool = False


class AgentCustomerSummary(BaseModel):
    id: int
    full_name: str
    email: str
    assigned_claims_count: int


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class OTPVerify(BaseModel):
    email: EmailStr
    otp: str


class ClaimSubmitResponse(BaseModel):
    claim_id: str
    id: int
    status: str
    message: str


class ClaimDecisionResponse(BaseModel):
    claim_id: str
    status: str
    payable_amount: float
    fraud_score: float
    confidence_score: float
    retrieved_clauses: list[str]
    reasoning: str
    human_review_required: bool
    approval_probability: Optional[float] = None
    coverage_estimate: Optional[float] = None
    expected_settlement: Optional[float] = None
    potential_problems: list[str] = []
    recommendations: list[str] = []
    missing_documents: list[str] = []
    policy_clause_matches: list[dict[str, Any]] = []
    fraud_signals: list[dict[str, Any]] = []
    next_best_action: Optional[str] = None
    ai_explanation: Optional[str] = None


class EvidenceIssueResponse(BaseModel):
    field: str
    document_id: int
    filename: str
    reason: str
    issue_code: str
    acknowledged: bool = False


class EvidenceAcknowledgeRequest(BaseModel):
    note: Optional[str] = None


class ExpertRequestedDocumentItem(BaseModel):
    id: str
    label: str
    document_type: str
    fulfilled: bool = False


class ExpertReviewResponse(BaseModel):
    expert_name: str
    message: str
    action: Optional[str] = None
    action_label: Optional[str] = None
    updated_at: Optional[datetime] = None
    requested_documents: list[ExpertRequestedDocumentItem] = []


class ClaimStatusResponse(BaseModel):
    claim_id: str
    id: int
    customer_id: Optional[int] = None
    status: str
    claim_amount: float
    created_at: datetime
    updated_at: datetime
    escalation_flags: list[str] = []
    escalation_messages: list[str] = []
    assigned_agent: Optional[str] = None
    assigned_at: Optional[datetime] = None
    expert_review: Optional[ExpertReviewResponse] = None
    evidence_mismatch: bool = False
    evidence_issues: list[EvidenceIssueResponse] = []
    pipeline_run_id: int = 0
    document_count: int = 0
    has_document_issues: bool = False
    decision: Optional[ClaimDecisionResponse] = None
    submission: Optional["ClaimSubmissionResponse"] = None
    documents: list["ClaimDocumentSummary"] = []


class ClaimSubmissionResponse(BaseModel):
    incident_description: str
    incident_datetime: datetime
    location: str
    policy_number: Optional[str] = None
    policy_type: Optional[str] = None


class HumanReviewSubmit(BaseModel):
    action: str = Field(..., description="SUBMISSION_READY, NEEDS_IMPROVEMENT, or CONTINUE_REVIEW")
    reviewer_notes: str = ""
    checklist: list[str] = []
    internal_notes: Optional[str] = None
    requested_documents: list[str] = Field(
        default_factory=list,
        description="Document type keys (DAMAGE_PHOTO, REPAIR_ESTIMATE, POLICE_REPORT, DRIVER_LICENSE, VEHICLE_REGISTRATION, TOWING_INVOICE, THIRD_PARTY_STATEMENT, POLICY_PAPER, OTHER) or custom labels when requesting more info",
    )


class PolicySummaryResponse(BaseModel):
    id: int
    policy_number: str
    policy_type: str
    status: str
    coverage_limit: float
    deductible: float
    co_pay_pct: float
    exclusions: list[str]
    premium_status: str
    effective_date: datetime
    expiry_date: datetime
    document_count: int = 0
    provider_name: Optional[str] = None
    premium_amount: Optional[float] = None
    coverage_remaining: Optional[float] = None


class PolicyFromDocumentResponse(PolicySummaryResponse):
    rag_chunks_indexed: int = 0
    rag_status: str = "indexed"
    extracted_fields: dict[str, Any] = {}


class PolicyCreateRequest(BaseModel):
    policy_type: str
    coverage_limit: float
    deductible: float = 500.0
    co_pay_pct: float = 10.0
    exclusions: list[str] = []


class DashboardStatusSlice(BaseModel):
    status: str
    label: str
    count: int


class DashboardMonthSlice(BaseModel):
    month: str
    count: int


class DashboardPolicyTypeSlice(BaseModel):
    policy_type: str
    count: int
    total_amount: float


class DashboardCoverageSlice(BaseModel):
    policy_number: str
    policy_type: str
    coverage_limit: float
    claimed_amount: float


class DashboardRecentClaim(BaseModel):
    id: int
    claim_id: str
    status: str
    claim_amount: float
    incident_description: str
    policy_type: Optional[str] = None
    created_at: datetime


class DashboardStatsResponse(BaseModel):
    active_policies: int
    total_policies: int
    total_claims: int
    draft_claims: int
    approved_claims: int
    pending_claims: int
    rejected_claims: int
    total_claim_amount: float
    approved_payout: float
    claims_by_status: list[DashboardStatusSlice]
    claims_by_month: list[DashboardMonthSlice]
    claims_by_policy_type: list[DashboardPolicyTypeSlice]
    coverage_by_policy: list[DashboardCoverageSlice]
    recent_activity: list[DashboardRecentClaim]
    kyc_status: Optional[str] = None
    kyc_complete: bool = False
    connected_policies: list[PolicySummaryResponse] = []
    recent_analyses: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []
    recommended_actions: list[str] = []


class AgentCustomerDetail(BaseModel):
    id: int
    full_name: str
    email: str
    policies: list[PolicySummaryResponse] = []
    assigned_claims: list[AgentClaimListItem] = []
    customer_risk: Optional[dict[str, Any]] = None


class AgentDashboardStatsResponse(BaseModel):
    assigned_total: int
    pending_review: int
    submission_ready: int
    needs_improvement: int
    avg_approval_probability: float
    claims_by_status: list[DashboardStatusSlice]
    claims_by_customer: list[dict[str, Any]]


class ClaimDocumentSummary(BaseModel):
    id: int
    doc_type: str
    filename: str
    uploaded_at: datetime


class ClaimDetailsSummary(BaseModel):
    incident_description: str
    incident_datetime: datetime
    location: str
    claim_amount: float
    customer_name: str
    policy_number: Optional[str] = None
    policy_type: Optional[str] = None


class AuditReportResponse(BaseModel):
    claim_id: str
    claim_number: str
    status: str
    claim_details: Optional[ClaimDetailsSummary] = None
    documents: list[ClaimDocumentSummary] = []
    escalation_flags: list[str] = []
    escalation_messages: list[str] = []
    evidence_issues: list[EvidenceIssueResponse] = []
    decision: Optional[ClaimDecisionResponse] = None
    fraud_assessment: Optional[dict[str, Any]] = None
    evidence_results: list[dict[str, Any]] = []
    retrieved_clauses: list[dict[str, Any]] = []
    audit_trail: list[dict[str, Any]] = []
    generated_at: datetime


class DraftClaimCreate(BaseModel):
    incident_description: str
    incident_datetime: datetime
    location: str
    # Estimated repair or replacement value the customer is claiming.
    claim_amount: float
    # Motor-specific fields (all optional at draft time; validated at submit).
    incident_type: Optional[str] = Field(
        default="COLLISION",
        description="One of COLLISION, THEFT, VANDALISM, FIRE, NATURAL_DISASTER, GLASS_ONLY, THIRD_PARTY_LIABILITY, OTHER",
    )
    third_party_involved: bool = False
    injuries_reported: bool = False
    tow_required: bool = False
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year: Optional[int] = None
    vin: Optional[str] = None
    license_plate: Optional[str] = None
    odometer_km: Optional[int] = None
    driver_license_number: Optional[str] = None
    driver_license_class: Optional[str] = None


class DraftClaimUpdate(BaseModel):
    incident_description: Optional[str] = None
    incident_datetime: Optional[datetime] = None
    location: Optional[str] = None
    claim_amount: Optional[float] = None
    policy_number: Optional[str] = None
    incident_type: Optional[str] = None
    third_party_involved: Optional[bool] = None
    injuries_reported: Optional[bool] = None
    tow_required: Optional[bool] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year: Optional[int] = None
    vin: Optional[str] = None
    license_plate: Optional[str] = None
    odometer_km: Optional[int] = None
    driver_license_number: Optional[str] = None
    driver_license_class: Optional[str] = None


class DraftClaimResponse(BaseModel):
    claim_id: str
    id: int
    status: str
    submission_step: int
    policy_context_ready: bool
    policy_number: Optional[str] = None
    incident_type: Optional[str] = None
    third_party_involved: bool = False
    injuries_reported: bool = False
    tow_required: bool = False
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year: Optional[int] = None
    vin: Optional[str] = None
    license_plate: Optional[str] = None
    odometer_km: Optional[int] = None
    driver_license_number: Optional[str] = None
    driver_license_class: Optional[str] = None


class PolicyDocumentItem(BaseModel):
    id: str | int
    title: str
    section_ref: str
    content_preview: str
    source: str


class PolicyContextResponse(BaseModel):
    coverage_summary: str = ""
    exclusions: list[str] = []
    key_sections: list[dict[str, Any]] = []
    llm_analysis: str = ""
    source: str = ""
    document_count: int = 0
    sections_loaded: list[str] = []
    policy_number: Optional[str] = None


class ChatMessageRequest(BaseModel):
    message: str


class ChatMessageResponse(BaseModel):
    role: str
    content: str
    created_at: Optional[datetime] = None


class InsightsResponse(BaseModel):
    claim_id: str
    status: str
    coverage_utilization: dict[str, Any]
    score_gauges: dict[str, float]
    payout_breakdown: dict[str, Any]
    policy_sections: list[dict[str, Any]] = []
    policy_context_summary: str = ""
    policy_summary: dict[str, Any] = {}
    timeline: list[dict[str, Any]] = []
    ai_analysis: dict[str, Any] = {}
    # Phase 4: present only when the claim's policy has a lakehouse-ingested
    # risk signal (i.e. it's an LH-POL-* policy from ingest_lakehouse.py).
    # Most claims won't have one — that's expected, not an error.
    policy_risk_signal: Optional[PolicyRiskSignalSummary] = None


class KYCStatusResponse(BaseModel):
    kyc_status: str
    gov_id_uploaded: bool
    face_verified: bool
    mobile_verified: bool
    verified_at: Optional[datetime] = None
    phone: Optional[str] = None
    date_of_birth: Optional[datetime] = None


class MobileOTPRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)


class MobileOTPVerify(BaseModel):
    phone: str = Field(..., min_length=10, max_length=15)
    otp: str = Field(..., min_length=4, max_length=8)


class CustomerProfileResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    kyc_status: str
    gov_id_uploaded: bool
    face_verified: bool
    mobile_verified: bool
    verified_at: Optional[datetime] = None
    phone: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    emergency_contacts: list[dict[str, Any]] = []
    saved_vehicles: list[dict[str, Any]] = []
    saved_garages: list[dict[str, Any]] = []
    preferred_providers: list[str] = []
    dependents: list[dict[str, Any]] = []
    risk_profile: dict[str, Any] = {}


class CustomerProfileUpdate(BaseModel):
    phone: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    emergency_contacts: Optional[list[dict[str, Any]]] = None
    saved_vehicles: Optional[list[dict[str, Any]]] = None
    saved_garages: Optional[list[dict[str, Any]]] = None
    preferred_providers: Optional[list[str]] = None
    dependents: Optional[list[dict[str, Any]]] = None


class InsuranceProviderResponse(BaseModel):
    id: int
    name: str
    slug: str
    logo_url: Optional[str] = None


class PolicyConnectInitiate(BaseModel):
    provider_slug: str
    policy_number: str
    date_of_birth: datetime


class PolicyConnectVerify(BaseModel):
    provider_slug: str
    policy_number: str
    date_of_birth: datetime
    otp: str
    policy_type: Optional[str] = None
    sum_insured: Optional[float] = None
    annual_premium: Optional[float] = None


class PolicyRagStatusResponse(BaseModel):
    policy_number: str
    policy_id: int
    rag_chunks_indexed: int
    chroma_total: int = 0


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    claim_id: Optional[int] = None
    policy_number: Optional[str] = None
    thread_id: Optional[int] = None


class AssistantChatResponse(BaseModel):
    role: str
    content: str
    created_at: Optional[datetime] = None


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    claim_id: Optional[int] = None
    customer_id: Optional[int] = None
    document_id: Optional[int] = None


class AgentClaimDocumentSummary(BaseModel):
    id: int
    doc_type: str
    filename: str
    uploaded_at: datetime
    has_issue: bool = False
    issue_reason: Optional[str] = None


class AgentPolicyRequirementsResponse(BaseModel):
    claim_id: str
    policy_number: Optional[str] = None
    policy_type: Optional[str] = None
    coverage_summary: str = ""
    exclusions: list[str] = []
    key_sections: list[dict[str, Any]] = []
    key_clauses: list[dict[str, Any]] = []
    missing_documents: list[str] = []
    policy_clause_matches: list[dict[str, Any]] = []
