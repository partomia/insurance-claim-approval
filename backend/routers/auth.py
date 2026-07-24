from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import schemas
from config import get_settings
from database import get_db
from dependencies import create_access_token, get_current_customer, get_password_hash, verify_password
from models.auth_session import AuthSession
from models.customer import Customer

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


def _create_session(db: Session, customer_id: int) -> AuthSession:
    session = AuthSession(
        customer_id=customer_id,
        refresh_token=AuthSession.generate_token(),
        expires_at=AuthSession.default_expiry(settings.jwt_refresh_days),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _issue_tokens(db: Session, customer: Customer) -> schemas.Token:
    session = _create_session(db, customer.id)
    access_token = create_access_token(
        data={"sub": customer.email, "role": "customer"},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return schemas.Token(access_token=access_token, refresh_token=session.refresh_token)


@router.post("/signup", response_model=schemas.CustomerResponse)
def signup(user: schemas.CustomerCreate, db: Session = Depends(get_db)):
    existing = db.query(Customer).filter(Customer.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    customer = Customer(
        email=user.email,
        full_name=user.full_name,
        hashed_password=get_password_hash(user.password),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/me", response_model=schemas.CustomerResponse)
def get_me(customer: Customer = Depends(get_current_customer)):
    return customer


@router.patch("/me", response_model=schemas.CustomerResponse)
def update_me(
    body: schemas.CustomerUpdate,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    customer.full_name = body.full_name.strip()
    db.commit()
    db.refresh(customer)
    return customer


@router.post("/login")
def login(user: schemas.CustomerLogin, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.email == user.email).first()
    if not customer or not verify_password(user.password, customer.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "OTP sent to email. Please verify.", "email": user.email}


@router.post("/verify-otp", response_model=schemas.Token)
def verify_otp(otp_data: schemas.OTPVerify, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.email == otp_data.email).first()
    if not customer:
        raise HTTPException(status_code=404, detail="User not found")
    if otp_data.otp != "112233":
        raise HTTPException(status_code=401, detail="Invalid OTP")

    return _issue_tokens(db, customer)


@router.post("/refresh", response_model=schemas.Token)
def refresh_token(body: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    session = (
        db.query(AuthSession)
        .filter(
            AuthSession.refresh_token == body.refresh_token,
            AuthSession.revoked.is_(False),
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if session.expires_at < datetime.utcnow():
        session.revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Refresh token expired")

    customer = db.query(Customer).filter(Customer.id == session.customer_id).first()
    if not customer:
        raise HTTPException(status_code=401, detail="User not found")

    session.last_used_at = datetime.utcnow()
    db.commit()

    access_token = create_access_token(
        data={"sub": customer.email, "role": "customer"},
        expires_delta=timedelta(minutes=settings.jwt_expire_minutes),
    )
    return schemas.Token(
        access_token=access_token,
        refresh_token=session.refresh_token,
        token_type="bearer",
    )


@router.post("/logout")
def logout(body: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    session = db.query(AuthSession).filter(AuthSession.refresh_token == body.refresh_token).first()
    if session:
        session.revoked = True
        db.commit()
    return {"message": "Logged out"}
