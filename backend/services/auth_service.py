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


ALLOWED_ROLES = {"owner", "admin", "driver", "fleet_owner", "personal_vehicle_owner"}
ALLOWED_STATUSES = {"active", "suspended", "inactive"}


def now_utc():
    return datetime.now(timezone.utc)


def users_collection():
    return get_collection("users")


def token_blocklist_collection():
    return get_collection("token_blocklist")


def user_management_audit_collection():
    return get_collection("user_management_audit")


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
            {"keys": [("role", ASCENDING), ("status", ASCENDING), ("full_name", ASCENDING)]},
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
    ensure_indexes_for_collection(
        user_management_audit_collection(),
        [
            {"keys": [("target_user_id", ASCENDING), ("created_at", ASCENDING)]},
            {"keys": [("actor_user_id", ASCENDING), ("created_at", ASCENDING)]},
            {"keys": [("action", ASCENDING), ("created_at", ASCENDING)]},
        ],
        collection_name="user_management_audit",
    )


def _audit_user_management(action: str, actor_user_id: str | None, actor_role: str, target_user_id: ObjectId, changes: dict | None = None):
    actor_id = ObjectId(actor_user_id) if actor_user_id and ObjectId.is_valid(str(actor_user_id)) else None
    user_management_audit_collection().insert_one({
        "action": action,
        "actor_user_id": actor_id,
        "actor_role": normalize_role_value(actor_role),
        "target_user_id": target_user_id,
        "changes": changes or {},
        "created_at": now_utc(),
    })


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
    status = str(payload.get("status", "active" if role in {"owner", "admin", "fleet_owner", "personal_vehicle_owner"} else "inactive")).strip().lower()

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
        "must_change_password": bool(payload.get("temporary_password", False)),
        "temporary_password_issued_at": timestamp if payload.get("temporary_password", False) else None,
        "password_changed_at": None,
        "password_version": 1,
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
            "must_change_password": serialized_user.get("must_change_password", False),
        },
    )
    return {"user": serialized_user, "access_token": access_token}


def get_user_by_id(user_id: str) -> dict:
    return serialize_user(get_user_document_by_id(user_id))


def list_users_for_role(current_role: str) -> list[dict]:
    current_role = normalize_role_value(current_role) or current_role
    query = {} if current_role == "owner" else {"role": {"$in": ["driver", "personal_vehicle_owner"]}}
    users = users_collection().find(query).sort("created_at", ASCENDING)
    return [serialize_user(user) for user in users]


def get_viewable_user(current_user_id: str, current_role: str, target_user_id: str) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    if current_role == "driver" and current_user_id != target_user_id:
        raise ApiError("You do not have permission to access this resource.", status_code=403)

    user = get_user_document_by_id(target_user_id)
    if current_role == "admin" and normalize_role_value(user.get("role")) not in {"driver", "personal_vehicle_owner"}:
        raise ApiError("You do not have permission to access this resource.", status_code=403)

    return serialize_user(user)


def create_user_as(current_role: str, payload: dict, current_user_id: str | None = None) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    requested_role = normalize_role_value(payload.get("role"))
    if requested_role not in ALLOWED_ROLES:
        raise ApiError("Invalid user role.", status_code=400)

    if current_role == "owner" and requested_role not in {"admin", "driver", "fleet_owner", "personal_vehicle_owner"}:
        raise ApiError("Owner cannot create that account role.", status_code=403)
    if current_role == "admin" and requested_role not in {"driver", "fleet_owner", "personal_vehicle_owner"}:
        raise ApiError("Admin cannot create that account role.", status_code=403)

    create_payload = {**payload}
    if requested_role == "personal_vehicle_owner":
        create_payload["temporary_password"] = True
    user = create_user(create_payload, role=requested_role)
    _audit_user_management("user_created", current_user_id, current_role, ObjectId(user["id"]), {
        "role": requested_role, "status": user.get("status"), "temporary_password": bool(user.get("must_change_password")),
    })
    return user


def update_user_status_as(current_role: str, target_user_id: str, status: str, current_user_id: str | None = None) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    status = str(status).strip().lower()
    if status not in ALLOWED_STATUSES:
        raise ApiError("Invalid user status.", status_code=400)

    user = get_user_document_by_id(target_user_id)
    if current_role == "admin" and normalize_role_value(user.get("role")) not in {"driver", "fleet_owner", "personal_vehicle_owner"}:
        raise ApiError("Admin can update Driver, Fleet Owner, or Personal Vehicle Owner status only.", status_code=403)

    previous_status = user.get("status")
    timestamp = now_utc()
    users_collection().update_one(
        {"_id": user["_id"]},
        {"$set": {"status": status, "updated_at": timestamp}},
    )
    user["status"] = status
    user["updated_at"] = timestamp
    _audit_user_management("user_status_changed", current_user_id, current_role, user["_id"], {"from": previous_status, "to": status})
    return serialize_user(user)


def update_user_account_as(current_user_id: str, current_role: str, target_user_id: str, payload: dict) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    user = get_user_document_by_id(target_user_id)
    target_role = normalize_role_value(user.get("role"))
    if current_role == "admin" and target_role != "personal_vehicle_owner":
        raise ApiError("Admin can edit Personal Vehicle Owner accounts only.", status_code=403)
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to edit this account.", status_code=403)

    updates = {}
    if "full_name" in payload:
        full_name = str(payload.get("full_name") or "").strip()
        if not full_name:
            raise ApiError("Full name is required.", status_code=400)
        updates["full_name"] = full_name
    if "email" in payload:
        email = normalize_email(payload.get("email"))
        if not email or not validate_email(email):
            raise ApiError("A valid email address is required.", status_code=400)
        updates["email"] = email
    if "phone" in payload:
        phone = normalize_phone(payload.get("phone"))
        if not phone or not validate_phone(phone):
            raise ApiError("A valid phone number is required.", status_code=400)
        updates["phone"] = phone
    if not updates:
        raise ApiError("No editable account fields were provided.", status_code=400)
    duplicate_query = {"_id": {"$ne": user["_id"]}, "$or": []}
    if "email" in updates:
        duplicate_query["$or"].append({"email": updates["email"]})
    if "phone" in updates:
        duplicate_query["$or"].append({"phone": updates["phone"]})
    if duplicate_query["$or"] and users_collection().find_one(duplicate_query, {"_id": 1}):
        raise ApiError("A user with this email or phone already exists.", status_code=409)
    before = {key: user.get(key) for key in updates}
    updates["updated_at"] = now_utc()
    try:
        users_collection().update_one({"_id": user["_id"]}, {"$set": updates})
    except DuplicateKeyError:
        raise ApiError("A user with this email or phone already exists.", status_code=409) from None
    user.update(updates)
    _audit_user_management("user_profile_changed", current_user_id, current_role, user["_id"], {"before": before, "after": {key: updates[key] for key in before}})
    return serialize_user(user)


def reset_user_password_as(current_user_id: str, current_role: str, target_user_id: str, temporary_password: str) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    user = get_user_document_by_id(target_user_id)
    target_role = normalize_role_value(user.get("role"))
    if current_role == "admin" and target_role != "personal_vehicle_owner":
        raise ApiError("Admin can reset Personal Vehicle Owner passwords only.", status_code=403)
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to reset this password.", status_code=403)
    if not temporary_password or len(temporary_password) < 6:
        raise ApiError("Temporary password must be at least 6 characters long.", status_code=400)
    timestamp = now_utc()
    users_collection().update_one({"_id": user["_id"]}, {"$set": {
        "password_hash": generate_password_hash(temporary_password),
        "must_change_password": True,
        "temporary_password_issued_at": timestamp,
        "updated_at": timestamp,
    }, "$inc": {"password_version": 1}})
    user.update({"must_change_password": True, "temporary_password_issued_at": timestamp, "updated_at": timestamp})
    _audit_user_management("temporary_password_reset", current_user_id, current_role, user["_id"], {"must_change_password": True})
    return serialize_user(user)


def change_own_password(current_user_id: str, current_password: str, new_password: str) -> dict:
    user = get_user_document_by_id(current_user_id)
    if not current_password or not check_password_hash(user.get("password_hash") or "", current_password):
        raise ApiError("Current password is incorrect.", status_code=400)
    if not new_password or len(new_password) < 8:
        raise ApiError("New password must be at least 8 characters long.", status_code=400)
    if check_password_hash(user.get("password_hash") or "", new_password):
        raise ApiError("New password must be different from the temporary password.", status_code=400)
    timestamp = now_utc()
    users_collection().update_one({"_id": user["_id"]}, {"$set": {
        "password_hash": generate_password_hash(new_password),
        "must_change_password": False,
        "password_changed_at": timestamp,
        "updated_at": timestamp,
    }, "$unset": {"temporary_password_issued_at": ""}, "$inc": {"password_version": 1}})
    user.update({"must_change_password": False, "password_changed_at": timestamp, "updated_at": timestamp})
    user.pop("temporary_password_issued_at", None)
    _audit_user_management("first_login_password_changed", current_user_id, user.get("role"), user["_id"], {"must_change_password": False})
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
