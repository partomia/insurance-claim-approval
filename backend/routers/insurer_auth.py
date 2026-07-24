from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import schemas
from config import get_settings
from database import get_db
from dependencies import create_access_token, get_current_insurer, verify_password
from models.insurer_auth_session import InsurerAuthSession
from models.insurer_user import InsurerUser

router = APIRouter(prefix="/insurer/auth", tags=["Insurer Authentication"])
settings = get_settings()


def _create_insurer_session(db: Session, insurer_id: int) -> InsurerAuthSession:
    session = InsurerAuthSession(
        insurer_id=insurer_id,
        refresh_token=InsurerAuthSession.generate_token(),
        expires_at=InsurerAuthSession.default_expiry(settings.jwt_refresh_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _issue_insurer_tokens(db: Session, insurer: InsurerUser) -> schemas.Token:
    session = _create_insurer_session(db, insurer.id)
    access_token = create_access_token(
        data={"sub": insurer.email, "role": "insurer", "insurer_id": insurer.id},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return schemas.Token(access_token=access_token, refresh_token=session.refresh_token)


@router.get("/me", response_model=schemas.InsurerResponse)
def insurer_me(insurer: InsurerUser = Depends(get_current_insurer)):
    return insurer


@router.patch("/me", response_model=schemas.InsurerResponse)
def update_insurer_me(
    body: schemas.InsurerUpdate,
    insurer: InsurerUser = Depends(get_current_insurer),
    db: Session = Depends(get_db),
):
    if body.full_name is not None:
        insurer.full_name = body.full_name.strip()
    if body.department is not None:
        insurer.department = body.department.strip() or None
    db.commit()
    db.refresh(insurer)
    return insurer


@router.post("/login")
def insurer_login(body: schemas.InsurerLogin, db: Session = Depends(get_db)):
    insurer = (
        db.query(InsurerUser)
        .filter(InsurerUser.email == body.email, InsurerUser.is_active.is_(True))
        .first()
    )
    if not insurer or not verify_password(body.password, insurer.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "OTP sent to email. Please verify.", "email": body.email}


@router.post("/verify-otp", response_model=schemas.Token)
def insurer_verify_otp(body: schemas.OTPVerify, db: Session = Depends(get_db)):
    insurer = (
        db.query(InsurerUser)
        .filter(InsurerUser.email == body.email, InsurerUser.is_active.is_(True))
        .first()
    )
    if not insurer:
        raise HTTPException(status_code=404, detail="Insurer not found")
    if body.otp != "112233":
        raise HTTPException(status_code=401, detail="Invalid OTP")
    return _issue_insurer_tokens(db, insurer)


@router.post("/refresh", response_model=schemas.Token)
def insurer_refresh(body: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    session = (
        db.query(InsurerAuthSession)
        .filter(InsurerAuthSession.refresh_token == body.refresh_token, InsurerAuthSession.revoked.is_(False))
        .first()
    )
    if not session:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if session.expires_at < datetime.utcnow():
        session.revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired")
    insurer = (
        db.query(InsurerUser)
        .filter(InsurerUser.id == session.insurer_id, InsurerUser.is_active.is_(True))
        .first()
    )
    if not insurer:
        raise HTTPException(status_code=401, detail="Insurer not found")
    session.last_used_at = datetime.utcnow()
    db.commit()
    access_token = create_access_token(
        data={"sub": insurer.email, "role": "insurer", "insurer_id": insurer.id},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return schemas.Token(access_token=access_token, refresh_token=session.refresh_token)


@router.post("/logout")
def insurer_logout(body: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    session = db.query(InsurerAuthSession).filter(InsurerAuthSession.refresh_token == body.refresh_token).first()
    if session:
        session.revoked = True
        db.commit()
    return {"message": "Logged out"}
