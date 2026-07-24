from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import schemas
from database import get_db
from dependencies import get_current_customer
from models.customer import Customer
from services.universal_assistant_service import universal_assistant_service

router = APIRouter(prefix="/api/assistant", tags=["Assistant"])


@router.get("/chat", response_model=list[schemas.ChatMessageResponse])
def get_assistant_history(
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return universal_assistant_service.get_history(db, customer.id)


@router.post("/chat", response_model=schemas.AssistantChatResponse)
def send_assistant_message(
    body: schemas.AssistantChatRequest,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    reply = universal_assistant_service.chat(
        db,
        customer,
        body.message.strip(),
        claim_id=body.claim_id,
        policy_number=body.policy_number,
    )
    return schemas.AssistantChatResponse(role="assistant", content=reply)
