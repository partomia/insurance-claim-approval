from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import schemas
from database import get_db
from dependencies import get_current_agent
from models.policy_agent import PolicyAgent
from services.agent_assistant_service import agent_assistant_service

router = APIRouter(prefix="/api/agent/assistant", tags=["Agent Assistant"])


@router.get("/chat", response_model=list[schemas.ChatMessageResponse])
def get_agent_assistant_history(
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    return agent_assistant_service.get_history(db, agent.id)


@router.post("/chat", response_model=schemas.AssistantChatResponse)
def send_agent_assistant_message(
    body: schemas.AgentChatRequest,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    reply = agent_assistant_service.chat(
        db,
        agent,
        body.message.strip(),
        claim_id=body.claim_id,
        customer_id=body.customer_id,
        document_id=body.document_id,
    )
    return schemas.AssistantChatResponse(role="assistant", content=reply)
