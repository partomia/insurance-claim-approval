from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import schemas
from config import get_settings
from database import get_db
from dependencies import create_access_token, get_current_agent, get_password_hash, verify_password
from models.agent_auth_session import AgentAuthSession
from models.policy_agent import PolicyAgent

router = APIRouter(prefix="/agent/auth", tags=["Agent Authentication"])
settings = get_settings()


def _create_agent_session(db: Session, agent_id: int) -> AgentAuthSession:
    session = AgentAuthSession(
        agent_id=agent_id,
        refresh_token=AgentAuthSession.generate_token(),
        expires_at=AgentAuthSession.default_expiry(settings.jwt_refresh_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _issue_agent_tokens(db: Session, agent: PolicyAgent) -> schemas.Token:
    session = _create_agent_session(db, agent.id)
    access_token = create_access_token(
        data={"sub": agent.email, "role": "agent", "agent_id": agent.id},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return schemas.Token(access_token=access_token, refresh_token=session.refresh_token)


@router.post("/signup", response_model=schemas.AgentResponse)
def agent_signup(body: schemas.AgentCreate, db: Session = Depends(get_db)):
    if body.invite_code != settings.agent_invite_code:
        raise HTTPException(status_code=403, detail="Invalid invite code")
    existing = db.query(PolicyAgent).filter(PolicyAgent.email == body.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    agent = PolicyAgent(
        email=body.email,
        full_name=body.full_name.strip(),
        hashed_password=get_password_hash(body.password),
        department=body.department,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/me", response_model=schemas.AgentResponse)
def agent_me(agent: PolicyAgent = Depends(get_current_agent)):
    return agent


@router.patch("/me", response_model=schemas.AgentResponse)
def update_agent_me(
    body: schemas.AgentUpdate,
    agent: PolicyAgent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    if body.full_name is not None:
        agent.full_name = body.full_name.strip()
    if body.department is not None:
        agent.department = body.department.strip() or None
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/login")
def agent_login(body: schemas.AgentLogin, db: Session = Depends(get_db)):
    agent = db.query(PolicyAgent).filter(PolicyAgent.email == body.email, PolicyAgent.is_active.is_(True)).first()
    if not agent or not verify_password(body.password, agent.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "OTP sent to email. Please verify.", "email": body.email}


@router.post("/verify-otp", response_model=schemas.Token)
def agent_verify_otp(body: schemas.OTPVerify, db: Session = Depends(get_db)):
    agent = db.query(PolicyAgent).filter(PolicyAgent.email == body.email, PolicyAgent.is_active.is_(True)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if body.otp != "112233":
        raise HTTPException(status_code=401, detail="Invalid OTP")
    return _issue_agent_tokens(db, agent)


@router.post("/refresh", response_model=schemas.Token)
def agent_refresh(body: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    session = (
        db.query(AgentAuthSession)
        .filter(AgentAuthSession.refresh_token == body.refresh_token, AgentAuthSession.revoked.is_(False))
        .first()
    )
    if not session:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if session.expires_at < datetime.utcnow():
        session.revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired")
    agent = db.query(PolicyAgent).filter(PolicyAgent.id == session.agent_id, PolicyAgent.is_active.is_(True)).first()
    if not agent:
        raise HTTPException(status_code=401, detail="Agent not found")
    session.last_used_at = datetime.utcnow()
    db.commit()
    access_token = create_access_token(
        data={"sub": agent.email, "role": "agent", "agent_id": agent.id},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return schemas.Token(access_token=access_token, refresh_token=session.refresh_token)


@router.post("/logout")
def agent_logout(body: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    session = db.query(AgentAuthSession).filter(AgentAuthSession.refresh_token == body.refresh_token).first()
    if session:
        session.revoked = True
        db.commit()
    return {"message": "Logged out"}
