from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import schemas
from database import get_db
from models.policy_agent import PolicyAgent

router = APIRouter(prefix="/api/agents", tags=["Policy Agents"])


@router.get("/available", response_model=list[schemas.AgentPublicResponse])
def list_available_agents(db: Session = Depends(get_db)):
    return (
        db.query(PolicyAgent)
        .filter(PolicyAgent.is_active.is_(True))
        .order_by(PolicyAgent.full_name.asc())
        .all()
    )
