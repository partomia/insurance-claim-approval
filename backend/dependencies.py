from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Query, status
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
# Some Cloudera AI workspaces front the Application with an Istio ingress
# that runs its own JWT-style check on incoming requests (expecting a
# Knox/OIDC-issued token) and silently rejects (empty 401, before it ever
# reaches this app) our own app-issued JWT wherever it looks for one.
# Confirmed it inspects the `Authorization` header; moving our token to a
# custom `X-Auth-Token` header instead is the first line of defense. As a
# second, independent line of defense — in case that mesh policy (or a
# similar one) inspects *any* header carrying a JWT-shaped value rather
# than being keyed to a specific header name — the frontend also mirrors
# the token into a plain (non-HttpOnly) cookie, which this class of
# header-focused policy essentially never inspects. All three (cookie,
# X-Auth-Token, Authorization: Bearer) are accepted here; `Authorization`
# is kept purely so this still works unchanged on deployments without any
# such mesh policy (plain uvicorn, docker, non-Istio clusters).
security = HTTPBearer(auto_error=False)

# Distinct cookie name per portal (customer/agent/insurer) — cookies, unlike
# our explicit per-request headers, are auto-attached by the browser to
# *every* same-origin request regardless of which JS module made the call,
# so a single shared cookie name would let an insurer/agent login silently
# clobber a customer session's cookie (and vice versa) in the same browser.
CUSTOMER_AUTH_COOKIE = "app_auth_token"
AGENT_AUTH_COOKIE = "app_agent_auth_token"
INSURER_AUTH_COOKIE = "app_insurer_auth_token"


def _make_token_extractor(cookie_name: str):
    def _extract(
        auth_cookie: Optional[str] = Cookie(default=None, alias=cookie_name),
        x_auth_token: Optional[str] = Header(default=None, alias="X-Auth-Token"),
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> Optional[str]:
        if auth_cookie:
            return auth_cookie
        if x_auth_token:
            return x_auth_token
        if credentials:
            return credentials.credentials
        return None

    return _extract


_extract_customer_token = _make_token_extractor(CUSTOMER_AUTH_COOKIE)
_extract_agent_token = _make_token_extractor(AGENT_AUTH_COOKIE)
_extract_insurer_token = _make_token_extractor(INSURER_AUTH_COOKIE)


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


def _decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
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
    token: Optional[str] = Depends(_extract_customer_token),
    db: Session = Depends(get_db),
) -> Customer:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = _decode_token(token)
    if payload.get("role") in ("agent", "insurer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent token not valid for customer routes")
    email: str = payload["sub"]
    customer = db.query(Customer).filter(Customer.email == email).first()
    if customer is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return customer


def get_current_agent(
    token: Optional[str] = Depends(_extract_agent_token),
    db: Session = Depends(get_db),
) -> PolicyAgent:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = _decode_token(token)
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
    token: Optional[str] = Depends(_extract_insurer_token),
    db: Session = Depends(get_db),
) -> InsurerUser:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = _decode_token(token)
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
    token: Optional[str] = Depends(_extract_customer_token),
    db: Session = Depends(get_db),
) -> Optional[Customer]:
    if token is None:
        return None
    try:
        return get_current_customer(token, db)
    except HTTPException:
        return None


def get_customer_flexible(
    token_param: Optional[str] = Query(None, alias="token", description="JWT for EventSource streams"),
    token: Optional[str] = Depends(_extract_customer_token),
    db: Session = Depends(get_db),
) -> Customer:
    if token:
        return get_current_customer(token, db)
    if token_param:
        try:
            payload = jwt.decode(token_param, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
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
