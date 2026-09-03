from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from .state import ClaimState
from rag.chroma_client import query_policy
from database import SessionLocal
from models import Policy, Claim, ClaimStatus
import json

# Initialize LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0)

def policy_lookup(state: ClaimState) -> ClaimState:
    """Retrieve policy terms from ChromaDB based on incident description"""
    print(f"--- POLICY LOOKUP for Claim {state['claim_id']} ---")
    
    # Query RAG
    policy_context = query_policy(state["incident_description"])
    state["policy_details"] = policy_context
    
    return state

def coverage_check(state: ClaimState) -> ClaimState:
    """Check premium status and limits from the database"""
    print(f"--- COVERAGE CHECK for Claim {state['claim_id']} ---")
    
    db = SessionLocal()
    policy = db.query(Policy).filter(Policy.id == state["policy_id"]).first()
    
    if policy:
        state["coverage_status"] = policy.premium_status
        state["coverage_limit"] = policy.coverage_limit
    else:
        state["coverage_status"] = "Unknown"
        state["coverage_limit"] = 0.0
        
    db.close()
    return state

def incident_validation(state: ClaimState) -> ClaimState:
    """Cross-check details and documents using LLM"""
    print(f"--- INCIDENT VALIDATION for Claim {state['claim_id']} ---")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an insurance claims validator. Determine if the incident is covered under the policy terms. Return ONLY a JSON object with 'is_valid' (boolean) and 'reasoning' (string)."),
        ("user", "Incident: {incident}\nClaim Amount: ${amount}\nPolicy Terms: {policy_terms}\nCoverage Status: {status}\nCoverage Limit: ${limit}")
    ])
    
    chain = prompt | llm
    response = chain.invoke({
        "incident": state["incident_description"],
        "amount": state["claim_amount"],
        "policy_terms": state["policy_details"],
        "status": state["coverage_status"],
        "limit": state["coverage_limit"]
    })
    
    try:
        # Clean markdown code blocks if present
        content = response.content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        state["is_valid"] = result.get("is_valid", False)
        state["validation_reasoning"] = result.get("reasoning", "Failed to parse reasoning.")
    except Exception as e:
        state["is_valid"] = False
        state["validation_reasoning"] = f"Error during validation: {str(e)}"
        
    return state

def fraud_check(state: ClaimState) -> ClaimState:
    """Flag inconsistencies or red flags using LLM"""
    print(f"--- FRAUD CHECK for Claim {state['claim_id']} ---")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a fraud detection agent. Analyze the claim for potential fraud. Return ONLY a JSON object with 'fraud_flag' (High, Medium, Low) and 'reasoning' (string)."),
        ("user", "Incident: {incident}\nClaim Amount: ${amount}\nValidation Reasoning: {validation}")
    ])
    
    chain = prompt | llm
    response = chain.invoke({
        "incident": state["incident_description"],
        "amount": state["claim_amount"],
        "validation": state["validation_reasoning"]
    })
    
    try:
        content = response.content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        state["fraud_flag"] = result.get("fraud_flag", "High")
        state["fraud_reasoning"] = result.get("reasoning", "Failed to parse reasoning.")
    except Exception as e:
        state["fraud_flag"] = "High"
        state["fraud_reasoning"] = f"Error during fraud check: {str(e)}"
        
    return state

def eligibility_decision(state: ClaimState) -> ClaimState:
    """Approve, reject, or escalate based on previous steps"""
    print(f"--- ELIGIBILITY DECISION for Claim {state['claim_id']} ---")
    
    if state["coverage_status"] != "Active":
        state["final_decision"] = "Reject"
        state["decision_reasoning"] = "Policy is not active."
    elif not state["is_valid"]:
        state["final_decision"] = "Reject"
        state["decision_reasoning"] = f"Incident not covered: {state['validation_reasoning']}"
    elif state["fraud_flag"] == "High":
        state["final_decision"] = "Escalate"
        state["decision_reasoning"] = f"High fraud risk detected: {state['fraud_reasoning']}"
    elif state["claim_amount"] > state["coverage_limit"]:
        state["final_decision"] = "Escalate"
        state["decision_reasoning"] = "Claim amount exceeds coverage limit. Manual review required."
    else:
        state["final_decision"] = "Approve"
        state["decision_reasoning"] = "Claim is valid, within limits, and low fraud risk."
        
    # Update Database
    db = SessionLocal()
    claim = db.query(Claim).filter(Claim.id == state["claim_id"]).first()
    if claim:
        if state["final_decision"] == "Approve":
            claim.status = ClaimStatus.APPROVED
        elif state["final_decision"] == "Reject":
            claim.status = ClaimStatus.REJECTED
        else:
            claim.status = ClaimStatus.ESCALATED
            
        claim.fraud_flag = state["fraud_flag"]
        claim.agent_reasoning = state["decision_reasoning"]
        db.commit()
    db.close()
    
    return state

# Build the Graph
workflow = StateGraph(ClaimState)

# Add nodes
workflow.add_node("policy_lookup", policy_lookup)
workflow.add_node("coverage_check", coverage_check)
workflow.add_node("incident_validation", incident_validation)
workflow.add_node("fraud_check", fraud_check)
workflow.add_node("eligibility_decision", eligibility_decision)

# Add edges
workflow.set_entry_point("policy_lookup")
workflow.add_edge("policy_lookup", "coverage_check")
workflow.add_edge("coverage_check", "incident_validation")
workflow.add_edge("incident_validation", "fraud_check")
workflow.add_edge("fraud_check", "eligibility_decision")
workflow.add_edge("eligibility_decision", END)

# Compile graph
claim_agent_executor = workflow.compile()
