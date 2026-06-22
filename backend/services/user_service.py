from datetime import datetime, timezone

from bson import ObjectId

from extensions import get_collection
from models.user import serialize_user
from utils.api_error import ApiError
from utils.validators import normalize_phone


ALLOWED_DRIVER_APPROVAL_STATUSES = {"pending", "approved", "rejected"}
ALLOWED_GUARANTOR_VERIFICATION_STATUSES = {"pending", "verified", "rejected"}
ALLOWED_DRIVER_ACCOUNT_STATUSES = {"active", "inactive", "suspended"}
DRIVER_SELF_EDITABLE_FIELDS = {
    "ghana_card_number",
    "license_number",
    "license_expiry",
    "license_class",
    "years_experience",
    "can_drive_manual",
    "can_drive_automatic",
    "emergency_contact_name",
    "emergency_contact_phone",
    "guarantor",
}


def now_utc():
    return datetime.now(timezone.utc)


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def get_driver_user_document(user_id: str) -> dict:
    if not ObjectId.is_valid(user_id):
        raise ApiError("User not found.", status_code=404)

    user = users_collection().find_one({"_id": ObjectId(user_id)})
    if not user or user.get("role") != "driver":
        raise ApiError("Driver not found.", status_code=404)
    return user


def list_driver_user_documents():
    return users_collection().find({"role": "driver"}).sort("created_at", 1)


def validate_non_negative_number(value, field_name: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return value


def normalize_driver_profile_payload(
    payload: dict,
    *,
    partial: bool = False,
    allow_admin_fields: bool = True,
) -> dict:
    driver_profile = payload.get("driver_profile") if "driver_profile" in payload else payload
    if driver_profile is None or not isinstance(driver_profile, dict):
        raise ApiError("Driver profile must be an object.", status_code=400)

    normalized_data = {}

    simple_fields = (
        "ghana_card_number",
        "license_number",
        "license_expiry",
        "license_class",
        "emergency_contact_name",
    )
    for field_name in simple_fields:
        if field_name in driver_profile:
            value = driver_profile.get(field_name)
            normalized_data[field_name] = str(value).strip() if value is not None else None

    if "emergency_contact_phone" in driver_profile:
        phone_value = driver_profile.get("emergency_contact_phone")
        normalized_data["emergency_contact_phone"] = normalize_phone(phone_value)

    if "years_experience" in driver_profile:
        years_experience = driver_profile.get("years_experience")
        if years_experience is not None and (isinstance(years_experience, bool) or not isinstance(years_experience, int) or years_experience < 0):
            raise ApiError("Years of experience must be a non-negative integer.", status_code=400)
        normalized_data["years_experience"] = years_experience

    for field_name in ("can_drive_manual", "can_drive_automatic", "deposit_required", "deposit_paid"):
        if field_name in driver_profile:
            field_value = driver_profile.get(field_name)
            if field_value is not None and not isinstance(field_value, bool):
                raise ApiError(f"{field_name} must be a boolean value.", status_code=400)
            normalized_data[field_name] = field_value

    if "deposit_balance" in driver_profile:
        normalized_data["deposit_balance"] = validate_non_negative_number(
            driver_profile.get("deposit_balance"),
            "deposit_balance",
        )

    if "approval_status" in driver_profile:
        approval_status = driver_profile.get("approval_status")
        if approval_status is not None and approval_status not in ALLOWED_DRIVER_APPROVAL_STATUSES:
            raise ApiError("Invalid driver approval status.", status_code=400)
        normalized_data["approval_status"] = approval_status

    if "assigned_vehicle_id" in driver_profile:
        assigned_vehicle_id = driver_profile.get("assigned_vehicle_id")
        if assigned_vehicle_id in (None, ""):
            normalized_data["assigned_vehicle_id"] = None
        else:
            if not ObjectId.is_valid(assigned_vehicle_id):
                raise ApiError("Invalid assigned_vehicle_id.", status_code=400)

            vehicle = vehicles_collection().find_one({"_id": ObjectId(assigned_vehicle_id)})
            if not vehicle:
                raise ApiError("Assigned vehicle not found.", status_code=404)
            normalized_data["assigned_vehicle_id"] = ObjectId(assigned_vehicle_id)

    if "guarantor" in driver_profile:
        guarantor = driver_profile.get("guarantor")
        if guarantor is not None and not isinstance(guarantor, dict):
            raise ApiError("Guarantor must be an object.", status_code=400)

        if guarantor is None:
            normalized_data["guarantor"] = None
        else:
            verification_status = guarantor.get("verification_status")
            if (
                verification_status is not None
                and verification_status not in ALLOWED_GUARANTOR_VERIFICATION_STATUSES
            ):
                raise ApiError("Invalid guarantor verification status.", status_code=400)

            normalized_data["guarantor"] = {
                "full_name": guarantor.get("full_name"),
                "phone": normalize_phone(guarantor.get("phone")),
                "relationship": guarantor.get("relationship"),
                "address": guarantor.get("address"),
                "occupation": guarantor.get("occupation"),
                "ghana_card_number": guarantor.get("ghana_card_number"),
                "verification_status": verification_status,
            }

    if not allow_admin_fields:
        disallowed_fields = set(normalized_data) - DRIVER_SELF_EDITABLE_FIELDS
        if disallowed_fields:
            raise ApiError(
                "Drivers can update only limited personal and guarantor profile fields.",
                status_code=403,
            )

    if not partial:
        return normalized_data or None

    return normalized_data


def sync_user_vehicle_assignment(
    *,
    user_id: ObjectId,
    previous_vehicle_id: ObjectId | None,
    new_vehicle_id: ObjectId | None,
):
    if new_vehicle_id:
        vehicle = vehicles_collection().find_one({"_id": new_vehicle_id})
        assigned_driver_id = vehicle.get("assigned_driver_id") if vehicle else None
        if assigned_driver_id and assigned_driver_id != user_id:
            raise ApiError("Vehicle is already assigned to another driver.", status_code=409)

    if previous_vehicle_id and previous_vehicle_id != new_vehicle_id:
        vehicles_collection().update_one(
            {
                "_id": previous_vehicle_id,
                "assigned_driver_id": user_id,
            },
            {"$set": {"assigned_driver_id": None}},
        )

    if new_vehicle_id:
        vehicles_collection().update_one(
            {"_id": new_vehicle_id},
            {"$set": {"assigned_driver_id": user_id, "updated_at": now_utc()}},
        )


def update_driver_profile_as(
    current_user_id: str,
    current_role: str,
    target_user_id: str,
    payload: dict,
) -> dict:
    target_user = get_driver_user_document(target_user_id)

    is_self_update = current_role == "driver" and current_user_id == target_user_id
    if current_role == "driver" and not is_self_update:
        raise ApiError("You do not have permission to update this driver profile.", status_code=403)
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to update this driver profile.", status_code=403)

    normalized_updates = normalize_driver_profile_payload(
        payload,
        partial=True,
        allow_admin_fields=not is_self_update,
    )
    if not normalized_updates:
        raise ApiError("No driver profile fields provided for update.", status_code=400)

    existing_profile = dict(target_user.get("driver_profile") or {})
    previous_vehicle_id = existing_profile.get("assigned_vehicle_id")
    new_vehicle_id = normalized_updates.get("assigned_vehicle_id", previous_vehicle_id)

    merged_profile = {**existing_profile, **normalized_updates}
    if "guarantor" in normalized_updates and existing_profile.get("guarantor") and normalized_updates["guarantor"]:
        merged_profile["guarantor"] = {
            **existing_profile["guarantor"],
            **normalized_updates["guarantor"],
        }

    sync_user_vehicle_assignment(
        user_id=target_user["_id"],
        previous_vehicle_id=previous_vehicle_id,
        new_vehicle_id=new_vehicle_id,
    )

    timestamp = now_utc()
    users_collection().update_one(
        {"_id": target_user["_id"]},
        {
            "$set": {
                "driver_profile": merged_profile,
                "updated_at": timestamp,
            }
        },
    )
    target_user["driver_profile"] = merged_profile
    target_user["updated_at"] = timestamp
    return serialize_user(target_user)


def list_drivers_for_role(current_user_id: str, current_role: str) -> list[dict]:
    if current_role in {"owner", "admin"}:
        return [serialize_user(driver) for driver in list_driver_user_documents()]

    if current_role == "driver":
        return [serialize_user(get_driver_user_document(current_user_id))]

    raise ApiError("You do not have permission to access this resource.", status_code=403)


def get_driver_for_role(current_user_id: str, current_role: str, driver_id: str) -> dict:
    if current_role == "driver" and current_user_id != driver_id:
        raise ApiError("You do not have permission to access this resource.", status_code=403)

    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to access this resource.", status_code=403)

    return serialize_user(get_driver_user_document(driver_id))


def update_driver_approval_status_as(current_role: str, driver_id: str, approval_status: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update driver approval status.", status_code=403)
    if approval_status not in ALLOWED_DRIVER_APPROVAL_STATUSES:
        raise ApiError("Invalid driver approval status.", status_code=400)

    driver = get_driver_user_document(driver_id)
    profile = dict(driver.get("driver_profile") or {})
    profile["approval_status"] = approval_status

    timestamp = now_utc()
    users_collection().update_one(
        {"_id": driver["_id"]},
        {"$set": {"driver_profile": profile, "updated_at": timestamp}},
    )
    driver["driver_profile"] = profile
    driver["updated_at"] = timestamp
    return serialize_user(driver)


def update_driver_status_as(current_role: str, driver_id: str, status: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update driver status.", status_code=403)
    if status not in ALLOWED_DRIVER_ACCOUNT_STATUSES:
        raise ApiError("Invalid user status.", status_code=400)

    driver = get_driver_user_document(driver_id)
    timestamp = now_utc()
    users_collection().update_one(
        {"_id": driver["_id"]},
        {"$set": {"status": status, "updated_at": timestamp}},
    )
    driver["status"] = status
    driver["updated_at"] = timestamp
    return serialize_user(driver)
