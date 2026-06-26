from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _normalize_role(value):
    if value is None:
        return None
    return str(value).strip().lower() or None


def serialize_driver_profile(user_document: dict) -> dict | None:
    if _normalize_role(user_document.get("role")) != "driver":
        return None

    driver_profile = user_document.get("driver_profile") or {}
    legacy_guarantor = user_document.get("guarantor")
    guarantor = driver_profile.get("guarantor") if isinstance(driver_profile, dict) else None

    if guarantor is None and legacy_guarantor is not None:
        guarantor = legacy_guarantor

    if not driver_profile and guarantor is None:
        return None

    return {
        "ghana_card_number": driver_profile.get("ghana_card_number"),
        "license_number": driver_profile.get("license_number"),
        "license_expiry": driver_profile.get("license_expiry"),
        "license_class": driver_profile.get("license_class"),
        "years_experience": driver_profile.get("years_experience"),
        "can_drive_manual": driver_profile.get("can_drive_manual"),
        "can_drive_automatic": driver_profile.get("can_drive_automatic"),
        "emergency_contact_name": driver_profile.get("emergency_contact_name"),
        "emergency_contact_phone": driver_profile.get("emergency_contact_phone"),
        "deposit_required": driver_profile.get("deposit_required"),
        "deposit_paid": driver_profile.get("deposit_paid"),
        "deposit_balance": driver_profile.get("deposit_balance"),
        "approval_status": driver_profile.get("approval_status"),
        "assigned_vehicle_id": _serialize_reference_id(driver_profile.get("assigned_vehicle_id")),
        "guarantor": guarantor,
    }


def serialize_user(user_document: dict) -> dict:
    return {
        "id": str(user_document.get("_id")),
        "full_name": user_document.get("full_name"),
        "email": user_document.get("email"),
        "phone": user_document.get("phone"),
        "role": _normalize_role(user_document.get("role")),
        "status": user_document.get("status"),
        "last_login": user_document.get("last_login").isoformat() if user_document.get("last_login") else None,
        "created_at": user_document.get("created_at").isoformat() if user_document.get("created_at") else None,
        "updated_at": user_document.get("updated_at").isoformat() if user_document.get("updated_at") else None,
        "driver_profile": serialize_driver_profile(user_document),
    }
