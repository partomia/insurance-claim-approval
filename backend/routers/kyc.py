from datetime import datetime
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

import schemas
from config import get_settings
from database import get_db
from dependencies import get_current_customer
from models.customer import Customer
from models.platform import CustomerProfile, KYCStatus
from services.kyc_service import effective_kyc_status, gov_id_file_exists, is_kyc_verified

router = APIRouter(prefix="/api/kyc", tags=["KYC"])
settings = get_settings()


async def _save_kyc_file(file: UploadFile, customer_id: int) -> str:
    upload_dir = Path(settings.upload_dir) / "kyc" / str(customer_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file.filename or "gov_id"
    dest = upload_dir / safe_name
    content = await file.read()
    async with aiofiles.open(dest, "wb") as out:
        await out.write(content)
    return str(dest)


def _get_or_create_profile(db: Session, customer: Customer) -> CustomerProfile:
    profile = db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer.id).first()
    if not profile:
        profile = CustomerProfile(customer_id=customer.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.get("/status", response_model=schemas.KYCStatusResponse)
def kyc_status(
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, customer)
    return _status_response(profile)


@router.post("/gov-id", response_model=schemas.KYCStatusResponse)
async def upload_gov_id(
    gov_id: UploadFile = File(...),
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, customer)
    path = await _save_kyc_file(gov_id, customer.id)
    profile.kyc_gov_id_path = path
    profile.kyc_status = KYCStatus.IN_PROGRESS
    db.commit()
    db.refresh(profile)
    return _status_response(profile)


@router.post("/verify-face", response_model=schemas.KYCStatusResponse)
def verify_face(
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, customer)
    if not gov_id_file_exists(profile):
        raise HTTPException(status_code=400, detail="Upload government ID before face verification")
    profile.kyc_face_verified = True
    _maybe_complete_kyc(profile)
    db.commit()
    db.refresh(profile)
    return _status_response(profile)


@router.post("/send-mobile-otp")
def send_mobile_otp(
    payload: schemas.MobileOTPRequest,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, customer)
    profile.phone = payload.phone
    db.commit()
    return {"message": "OTP sent to mobile", "otp_hint": "Use 112233 for demo"}


@router.post("/verify-mobile", response_model=schemas.KYCStatusResponse)
def verify_mobile(
    payload: schemas.MobileOTPVerify,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    if payload.otp != "112233":
        raise HTTPException(status_code=400, detail="Invalid OTP")
    profile = _get_or_create_profile(db, customer)
    profile.phone = payload.phone
    profile.kyc_mobile_verified = True
    _maybe_complete_kyc(profile)
    db.commit()
    db.refresh(profile)
    return _status_response(profile)


@router.get("/profile", response_model=schemas.CustomerProfileResponse)
def get_profile(
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, customer)
    return _profile_response(customer, profile)


@router.patch("/profile", response_model=schemas.CustomerProfileResponse)
def update_profile(
    payload: schemas.CustomerProfileUpdate,
    customer: Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, customer)
    if payload.phone is not None:
        profile.phone = payload.phone
    if payload.date_of_birth is not None:
        profile.date_of_birth = payload.date_of_birth
    if payload.emergency_contacts is not None:
        profile.emergency_contacts = payload.emergency_contacts
    if payload.saved_vehicles is not None:
        profile.saved_vehicles = payload.saved_vehicles
    if payload.saved_garages is not None:
        profile.saved_garages = payload.saved_garages
    if payload.preferred_providers is not None:
        profile.preferred_providers = payload.preferred_providers
    if payload.dependents is not None:
        profile.dependents = payload.dependents
    db.commit()
    db.refresh(profile)
    return _profile_response(customer, profile)


def _maybe_complete_kyc(profile: CustomerProfile) -> None:
    if gov_id_file_exists(profile) and profile.kyc_face_verified and profile.kyc_mobile_verified:
        profile.kyc_status = KYCStatus.VERIFIED
        profile.kyc_verified_at = datetime.utcnow()


def _status_response(profile: CustomerProfile) -> schemas.KYCStatusResponse:
    status = effective_kyc_status(profile)
    return schemas.KYCStatusResponse(
        kyc_status=status.value,
        gov_id_uploaded=gov_id_file_exists(profile),
        face_verified=profile.kyc_face_verified if gov_id_file_exists(profile) else False,
        mobile_verified=profile.kyc_mobile_verified if gov_id_file_exists(profile) else False,
        verified_at=profile.kyc_verified_at if status == KYCStatus.VERIFIED else None,
        phone=profile.phone,
        date_of_birth=profile.date_of_birth,
    )


def _profile_response(customer: Customer, profile: CustomerProfile) -> schemas.CustomerProfileResponse:
    status = effective_kyc_status(profile)
    return schemas.CustomerProfileResponse(
        id=customer.id,
        email=customer.email,
        full_name=customer.full_name,
        kyc_status=status.value,
        gov_id_uploaded=gov_id_file_exists(profile),
        face_verified=profile.kyc_face_verified if gov_id_file_exists(profile) else False,
        mobile_verified=profile.kyc_mobile_verified if gov_id_file_exists(profile) else False,
        verified_at=profile.kyc_verified_at if status == KYCStatus.VERIFIED else None,
        phone=profile.phone,
        date_of_birth=profile.date_of_birth,
        emergency_contacts=profile.emergency_contacts or [],
        saved_vehicles=profile.saved_vehicles or [],
        saved_garages=profile.saved_garages or [],
        preferred_providers=profile.preferred_providers or [],
        dependents=profile.dependents or [],
        risk_profile=profile.risk_profile or {},
    )
