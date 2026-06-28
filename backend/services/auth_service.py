from datetime import datetime, timezone

from bson import ObjectId
from flask_jwt_extended import create_access_token
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo import ASCENDING
from pymongo.read_preferences import ReadPreference
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import get_collection
from models.user import serialize_user
from services.user_service import normalize_driver_profile_payload
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.validators import (
    normalize_email,
    normalize_phone,
    validate_email,
    validate_phone,
)


ALLOWED_ROLES = {"owner", "admin", "driver"}
ALLOWED_STATUSES = {"active", "suspended", "inactive"}


def now_utc():
    return datetime.now(timezone.utc)


def users_collection():
    return get_collection("users")


def token_blocklist_collection():
    return get_collection("token_blocklist")


def users_read_collection():
    return users_collection().with_options(read_preference=ReadPreference.SECONDARY_PREFERRED)


def normalize_role_value(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def ensure_indexes():
    ensure_indexes_for_collection(
        users_collection(),
        [
            {"keys": [("email", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("phone", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("role", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("created_at", ASCENDING)]},
            {"keys": [("updated_at", ASCENDING)]},
            {"keys": [("driver_profile.approval_status", ASCENDING)]},
            {
                "keys": [("driver_profile.approval_status", ASCENDING), ("created_at", ASCENDING)],
            },
        ],
        collection_name="users",
    )
    ensure_indexes_for_collection(
        token_blocklist_collection(),
        [
            {"keys": [("jti", ASCENDING)], "options": {"unique": True}},
            {"keys": [("expires_at", ASCENDING)], "options": {"expireAfterSeconds": 0}},
        ],
        collection_name="token_blocklist",
    )


def build_auth_payload(user: dict, access_token: str) -> dict:
    return {
        "access_token": access_token,
        "user": user,
    }


def get_user_document_by_id(user_id: str) -> dict:
    if not ObjectId.is_valid(user_id):
        raise ApiError("User not found.", status_code=404)

    user = users_read_collection().find_one({"_id": ObjectId(user_id)})
    if not user:
        raise ApiError("User not found.", status_code=404)
    return user


def create_user(payload: dict, role: str) -> dict:
    role = normalize_role_value(role)
    if role not in ALLOWED_ROLES:
        raise ApiError("Invalid user role.", status_code=400)

    full_name = (payload.get("full_name") or "").strip()
    email = normalize_email(payload.get("email"))
    phone = normalize_phone(payload.get("phone"))
    password = payload.get("password")
    status = str(payload.get("status", "active" if role in {"owner", "admin"} else "inactive")).strip().lower()

    if not full_name:
        raise ApiError("Full name is required.", status_code=400)
    if not email:
        raise ApiError("Email is required.", status_code=400)
    if not validate_email(email):
        raise ApiError("A valid email address is required.", status_code=400)
    if not phone:
        raise ApiError("Phone number is required.", status_code=400)
    if not validate_phone(phone):
        raise ApiError("A valid phone number is required.", status_code=400)
    if not password or len(password) < 6:
        raise ApiError("Password must be at least 6 characters long.", status_code=400)
    if status not in ALLOWED_STATUSES:
        raise ApiError("Invalid user status.", status_code=400)

    existing_user = users_read_collection().find_one({"$or": [{"email": email}, {"phone": phone}]})
    if existing_user:
        raise ApiError("A user with this email or phone already exists.", status_code=409)

    driver_profile = normalize_driver_profile_payload(payload) if role == "driver" else None

    timestamp = now_utc()
    user_document = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password_hash": generate_password_hash(password),
        "role": role,
        "status": status,
        "last_login": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "driver_profile": driver_profile,
    }
    try:
        insert_result = users_collection().insert_one(user_document)
    except DuplicateKeyError:
        raise ApiError("A user with this email or phone already exists.", status_code=409) from None

    user_document["_id"] = insert_result.inserted_id
    return serialize_user(user_document)


def authenticate_user(identifier: str, password: str) -> dict:
    normalized_email = normalize_email(identifier)
    normalized_phone = normalize_phone(identifier)

    filters = []
    if normalized_email:
        filters.append({"email": normalized_email})
    if normalized_phone:
        filters.append({"phone": normalized_phone})
    if not filters:
        raise ApiError("A valid email or phone number is required.", status_code=400)

    user = users_read_collection().find_one({"$or": filters})
    if not user or not check_password_hash(user["password_hash"], password):
        raise ApiError("Invalid login credentials.", status_code=401)

    if str(user["status"]).strip().lower() != "active":
        raise ApiError("This account is not active.", status_code=403)

    timestamp = now_utc()
    try:
        users_collection().update_one(
            {"_id": user["_id"]},
            {"$set": {"last_login": timestamp, "updated_at": timestamp}},
        )
    except PyMongoError:
        # Authentication should not fail just because telemetry fields could not be updated.
        pass
    user["last_login"] = timestamp
    user["updated_at"] = timestamp

    serialized_user = serialize_user(user)
    access_token = create_access_token(
        identity=serialized_user["id"],
        additional_claims={
            "role": normalize_role_value(serialized_user["role"]),
            "email": serialized_user["email"],
            "full_name": serialized_user["full_name"],
        },
    )
    return {"user": serialized_user, "access_token": access_token}


def get_user_by_id(user_id: str) -> dict:
    return serialize_user(get_user_document_by_id(user_id))


def list_users_for_role(current_role: str) -> list[dict]:
    current_role = normalize_role_value(current_role) or current_role
    query = {} if current_role == "owner" else {"role": "driver"}
    users = users_collection().find(query).sort("created_at", ASCENDING)
    return [serialize_user(user) for user in users]


def get_viewable_user(current_user_id: str, current_role: str, target_user_id: str) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    if current_role == "driver" and current_user_id != target_user_id:
        raise ApiError("You do not have permission to access this resource.", status_code=403)

    user = get_user_document_by_id(target_user_id)
    if current_role == "admin" and normalize_role_value(user.get("role")) != "driver":
        raise ApiError("You do not have permission to access this resource.", status_code=403)

    return serialize_user(user)


def create_user_as(current_role: str, payload: dict) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    requested_role = normalize_role_value(payload.get("role"))
    if requested_role not in ALLOWED_ROLES:
        raise ApiError("Invalid user role.", status_code=400)

    if current_role == "owner" and requested_role not in {"admin", "driver"}:
        raise ApiError("Owner can create only admin or driver accounts.", status_code=403)
    if current_role == "admin" and requested_role != "driver":
        raise ApiError("Admin can create driver accounts only.", status_code=403)

    return create_user(payload, role=requested_role)


def update_user_status_as(current_role: str, target_user_id: str, status: str) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    status = str(status).strip().lower()
    if status not in ALLOWED_STATUSES:
        raise ApiError("Invalid user status.", status_code=400)

    user = get_user_document_by_id(target_user_id)
    if current_role == "admin" and normalize_role_value(user.get("role")) != "driver":
        raise ApiError("Admin can update driver status only.", status_code=403)

    timestamp = now_utc()
    users_collection().update_one(
        {"_id": user["_id"]},
        {"$set": {"status": status, "updated_at": timestamp}},
    )
    user["status"] = status
    user["updated_at"] = timestamp
    return serialize_user(user)


def update_user_role_as(current_user_id: str, target_user_id: str, role: str) -> dict:
    role = normalize_role_value(role)
    if role not in ALLOWED_ROLES:
        raise ApiError("Invalid user role.", status_code=400)
    if current_user_id == target_user_id:
        raise ApiError("You cannot change your own role.", status_code=400)

    user = get_user_document_by_id(target_user_id)
    timestamp = now_utc()
    users_collection().update_one(
        {"_id": user["_id"]},
        {"$set": {"role": role, "updated_at": timestamp}},
    )
    user["role"] = role
    user["updated_at"] = timestamp
    return serialize_user(user)


def revoke_token(jti: str, exp_timestamp: int) -> None:
    token_blocklist_collection().update_one(
        {"jti": jti},
        {
            "$set": {
                "jti": jti,
                "expires_at": datetime.fromtimestamp(exp_timestamp, tz=timezone.utc),
                "created_at": now_utc(),
            }
        },
        upsert=True,
    )


def ensure_demo_users():
    demo_users = [
        {
            "full_name": "Fleet Owner",
            "email": "owner@fluxfleet.com",
            "phone": "+233500000001",
            "password": "Owner@12345",
            "role": "owner",
            "status": "active",
        },
        {
            "full_name": "Flux Admin",
            "email": "admin@fluxfleet.com",
            "phone": "+233500000002",
            "password": "Admin@12345",
            "role": "admin",
            "status": "active",
        },
        {
            "full_name": "Demo Driver",
            "email": "driver@fluxfleet.com",
            "phone": "+233500000003",
            "password": "Driver12345",
            "role": "driver",
            "status": "active",
            "driver_profile": {
                "ghana_card_number": "GHA-123456789-0",
                "license_number": "GH-DRV-0001",
                "license_expiry": "2028-12-31",
                "license_class": "C",
                "years_experience": 4,
                "can_drive_manual": True,
                "can_drive_automatic": True,
                "emergency_contact_name": "Akosua Mensah",
                "emergency_contact_phone": "+233500000055",
                "deposit_required": True,
                "deposit_paid": False,
                "deposit_balance": 1500,
                "approval_status": "approved",
                "assigned_vehicle_id": None,
                "guarantor": {
                    "full_name": "Sample Guarantor",
                    "phone": "+233500000099",
                    "relationship": "Brother",
                    "address": "Accra, Ghana",
                    "occupation": "Teacher",
                    "ghana_card_number": "GHA-123456789-0",
                    "verification_status": "pending",
                },
            },
        },
    ]

    for demo_user in demo_users:
        existing_user = users_collection().find_one(
            {"$or": [{"email": demo_user["email"]}, {"phone": demo_user["phone"]}]}
        )
        if not existing_user:
            create_user(demo_user, role=demo_user["role"])
