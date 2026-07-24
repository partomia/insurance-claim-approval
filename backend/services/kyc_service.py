from pathlib import Path

from models.platform import CustomerProfile, KYCStatus


def gov_id_file_exists(profile: CustomerProfile | None) -> bool:
    if not profile or not profile.kyc_gov_id_path:
        return False
    return Path(profile.kyc_gov_id_path).is_file()


def effective_kyc_status(profile: CustomerProfile | None) -> KYCStatus:
    if not profile:
        return KYCStatus.PENDING
    if not gov_id_file_exists(profile):
        return KYCStatus.PENDING
    if profile.kyc_face_verified and profile.kyc_mobile_verified:
        return KYCStatus.VERIFIED
    if profile.kyc_gov_id_path or profile.kyc_face_verified or profile.kyc_mobile_verified:
        return KYCStatus.IN_PROGRESS
    return KYCStatus.PENDING


def is_kyc_verified(profile: CustomerProfile | None) -> bool:
    return effective_kyc_status(profile) == KYCStatus.VERIFIED
