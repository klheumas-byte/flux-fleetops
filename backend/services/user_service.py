from datetime import datetime, timezone

from bson import ObjectId

from extensions import get_collection
from models.user import serialize_user
from services.notification_service import create_notification
from utils.api_error import ApiError
from utils.validators import normalize_phone


ALLOWED_DRIVER_APPROVAL_STATUSES = {"pending", "approved", "rejected"}
ALLOWED_GUARANTOR_VERIFICATION_STATUSES = {"pending", "verified", "rejected"}
ALLOWED_DRIVER_ACCOUNT_STATUSES = {"active", "inactive", "suspended"}
ALLOWED_DRIVER_OPERATING_MODES = {"operations_only", "target_only", "hybrid"}
ALLOWED_TARGET_FREQUENCIES = {"daily", "weekly"}
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

    if "operating_mode" in driver_profile:
        operating_mode = str(driver_profile.get("operating_mode") or "").strip().lower()
        if operating_mode not in ALLOWED_DRIVER_OPERATING_MODES:
            raise ApiError(
                "operating_mode must be one of: operations_only, target_only, hybrid.",
                status_code=400,
            )
        normalized_data["operating_mode"] = operating_mode

    if "target_enabled" in driver_profile:
        target_enabled = driver_profile.get("target_enabled")
        if not isinstance(target_enabled, bool):
            raise ApiError("target_enabled must be a boolean value.", status_code=400)
        normalized_data["target_enabled"] = target_enabled

    if "private_finance_enabled" in driver_profile:
        private_finance_enabled = driver_profile.get("private_finance_enabled")
        if not isinstance(private_finance_enabled, bool):
            raise ApiError("private_finance_enabled must be a boolean value.", status_code=400)
        normalized_data["private_finance_enabled"] = private_finance_enabled

    if "target_amount" in driver_profile:
        normalized_data["target_amount"] = validate_non_negative_number(
            driver_profile.get("target_amount"),
            "target_amount",
        )

    if "target_frequency" in driver_profile:
        target_frequency = str(driver_profile.get("target_frequency") or "").strip().lower()
        if target_frequency not in ALLOWED_TARGET_FREQUENCIES:
            raise ApiError("target_frequency must be daily or weekly.", status_code=400)
        normalized_data["target_frequency"] = target_frequency

    if "settings_effective_date" in driver_profile:
        effective_date = str(driver_profile.get("settings_effective_date") or "").strip()
        try:
            datetime.fromisoformat(effective_date)
        except ValueError as error:
            raise ApiError("settings_effective_date must be an ISO date.", status_code=400) from error
        normalized_data["settings_effective_date"] = effective_date

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
    change_reason = str(payload.get("change_reason") or "Administrative driver settings update").strip()
    if len(change_reason) > 500:
        raise ApiError("change_reason cannot exceed 500 characters.", status_code=400)

    is_self_update = current_role == "driver" and current_user_id == target_user_id
    if current_role == "driver" and not is_self_update:
        raise ApiError("You do not have permission to update this driver profile.", status_code=403)
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to update this driver profile.", status_code=403)

    requested_profile = payload.get("driver_profile") if isinstance(payload.get("driver_profile"), dict) else payload
    protected_settings = {"operating_mode", "target_enabled", "target_amount", "target_frequency", "private_finance_enabled", "settings_effective_date"}
    if is_self_update and protected_settings.intersection(requested_profile):
        raise ApiError("Only an owner or admin can change driver operating settings.", status_code=403)

    normalized_updates = normalize_driver_profile_payload(
        payload,
        partial=True,
        allow_admin_fields=not is_self_update,
    )
    if not normalized_updates:
        raise ApiError("No driver profile fields provided for update.", status_code=400)

    existing_profile = dict(target_user.get("driver_profile") or {})
    if "assigned_vehicle_id" in normalized_updates:
        raise ApiError(
            "Vehicle allocation must be changed from Vehicle Assignments.",
            status_code=409,
        )

    merged_profile = {**existing_profile, **normalized_updates}
    if "guarantor" in normalized_updates and existing_profile.get("guarantor") and normalized_updates["guarantor"]:
        merged_profile["guarantor"] = {
            **existing_profile["guarantor"],
            **normalized_updates["guarantor"],
        }

    setting_fields = {
        "operating_mode", "target_enabled", "target_amount",
        "target_frequency", "private_finance_enabled", "settings_effective_date",
    }
    if setting_fields.intersection(normalized_updates):
        effective_mode = merged_profile.get("operating_mode") or "hybrid"
        effective_target_enabled = merged_profile.get("target_enabled", True)
        if effective_mode == "operations_only" and effective_target_enabled:
            raise ApiError(
                "Targets must be disabled when the driver is operations_only.",
                status_code=400,
            )
        if effective_target_enabled and not merged_profile.get("target_amount"):
            raise ApiError("target_amount is required when targets are enabled.", status_code=400)
        if merged_profile.get("private_finance_enabled") and (
            effective_mode not in {"target_only", "hybrid"} or not effective_target_enabled
        ):
            raise ApiError(
                "Private finance requires a target-enabled target_only or hybrid driver.",
                status_code=400,
            )

    timestamp = now_utc()
    changed_settings = {
        key: {"before": existing_profile.get(key), "after": merged_profile.get(key)}
        for key in setting_fields
        if key in normalized_updates and existing_profile.get(key) != merged_profile.get(key)
    }
    if changed_settings:
        actor_document = users_collection().find_one({"_id": ObjectId(current_user_id)}, {"full_name": 1})
        history_entry = {
            "changed_by": ObjectId(current_user_id),
            "changed_by_name": (actor_document or {}).get("full_name") or "Unknown user",
            "changed_by_role": current_role,
            "changed_at": timestamp,
            "reason": change_reason,
            "changes": changed_settings,
            "effective_date": merged_profile.get("settings_effective_date"),
        }
        merged_profile["settings_history"] = [
            *(existing_profile.get("settings_history") or []),
            history_entry,
        ][-100:]
    if merged_profile == existing_profile:
        return serialize_user(target_user)
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
    if changed_settings:
        get_collection("fleet_owner_audit").insert_one(
            {
                "actor_id": ObjectId(current_user_id),
                "action": "driver_settings_changed",
                "entity_type": "driver",
                "entity_id": target_user["_id"],
                "before": {key: value["before"] for key, value in changed_settings.items()},
                "after": {key: value["after"] for key, value in changed_settings.items()},
                "reason": change_reason,
                "actor_role": current_role,
                "created_at": timestamp,
                "immutable": True,
            }
        )
        create_notification(
            target_user["_id"],
            "Driver access settings changed",
            "Your operating mode or target configuration has been updated.",
            category="driver_settings",
            priority="medium",
            reference_type="driver_settings",
            reference_id=target_user["_id"],
            dedupe_key=f"driver-settings:{target_user['_id']}:{timestamp.isoformat()}",
            metadata={"changes": list(changed_settings)},
        )
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
