from typing import TypedDict, Optional, List

class ClaimState(TypedDict):
    claim_id: int
    user_id: int
    policy_id: int
    incident_description: str
    claim_amount: float
    
    # Context gathered by agents
    policy_details: Optional[str]
    coverage_status: Optional[str] # "Active", "Lapsed", etc.
    coverage_limit: Optional[float]
    
    # Validation results
    is_valid: Optional[bool]
    validation_reasoning: Optional[str]
    
    # Fraud check results
    fraud_flag: Optional[str] # "High", "Medium", "Low"
    fraud_reasoning: Optional[str]
    
    # Final decision
    final_decision: Optional[str] # "Approve", "Reject", "Escalate"
    decision_reasoning: Optional[str]
