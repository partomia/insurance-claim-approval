from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models.customer import Customer
from models.insurer_user import InsurerUser
from models.policy_agent import PolicyAgent

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(credentials: HTTPAuthorizationCredentials) -> dict:
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload


def get_current_customer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Customer:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = _decode_token(credentials)
    if payload.get("role") in ("agent", "insurer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent token not valid for customer routes")
    email: str = payload["sub"]
    customer = db.query(Customer).filter(Customer.email == email).first()
    if customer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return customer


def get_current_agent(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> PolicyAgent:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = _decode_token(credentials)
    if payload.get("role") != "agent":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer token not valid for agent routes")
    agent_id = payload.get("agent_id")
    if agent_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")
    agent = (
        db.query(PolicyAgent)
        .filter(PolicyAgent.id == int(agent_id), PolicyAgent.is_active.is_(True))
        .first()
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent not found")
    return agent


def get_current_insurer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> InsurerUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = _decode_token(credentials)
    if payload.get("role") != "insurer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer token not valid for insurer routes")
    insurer_id = payload.get("insurer_id")
    if insurer_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid insurer token")
    insurer = (
        db.query(InsurerUser)
        .filter(InsurerUser.id == int(insurer_id), InsurerUser.is_active.is_(True))
        .first()
    )
    if insurer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Insurer not found")
    return insurer


def get_optional_customer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[Customer]:
    if credentials is None:
        return None
    try:
        return get_current_customer(credentials, db)
    except HTTPException:
        return None


def get_customer_flexible(
    token: Optional[str] = Query(None, description="JWT for EventSource streams"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Customer:
    if credentials:
        return get_current_customer(credentials, db)
    if token:
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            if payload.get("role") in ("agent", "insurer"):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent token not valid")
            email: str = payload.get("sub")
            if not email:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
            customer = db.query(Customer).filter(Customer.email == email).first()
            if not customer:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
            return customer
        except JWTError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
