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


from services.rbac_service import ROLE_DEFINITIONS, role_definition, user_has_permission, user_role_codes, validate_role_assignment, write_audit

ALLOWED_ROLES = set(ROLE_DEFINITIONS)
ALLOWED_STATUSES = {"active", "disabled", "suspended", "inactive"}


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
            {"keys": [("username", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("branch", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("role", ASCENDING)]},
            {"keys": [("role_ids", ASCENDING), ("status", ASCENDING)]},
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
    try:
        write_audit(action, actor_user_id, "user", target_user_id, changes or {}, {"actor_role": normalize_role_value(actor_role)})
    except Exception:
        pass


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


BRANCH_SCOPED_OPERATIONAL_ROLES = {"branch_manager", "branch_warehouse_coordinator"}
DRIVER_OPERATIONAL_SCOPES = {"COMPANY_WIDE", "BRANCH", "PERSONAL_ONLY"}


def _driver_scope_fields(payload, role_ids, primary_branch_id, existing=None):
    existing = existing or {}
    if "driver" not in set(role_ids or []):
        return {}
    scope = str(payload.get("operational_scope", existing.get("operational_scope") or ("BRANCH" if primary_branch_id else "COMPANY_WIDE"))).strip().upper()
    if scope not in DRIVER_OPERATIONAL_SCOPES:
        raise ApiError("Invalid operational_scope.", status_code=400)
    home_value = payload.get("home_branch_id", existing.get("home_branch_id") or primary_branch_id)
    if home_value and not ObjectId.is_valid(str(home_value)):
        raise ApiError("Invalid home_branch_id.", status_code=400)
    if scope == "BRANCH" and not home_value:
        raise ApiError("A BRANCH driver requires a home branch.", status_code=400)
    return {"operational_scope": scope, "home_branch_id": ObjectId(str(home_value)) if home_value else None}


def _require_primary_branch_for_roles(role_ids, primary_branch_id):
    if set(role_ids or []) & BRANCH_SCOPED_OPERATIONAL_ROLES and not primary_branch_id:
        raise ApiError("Primary Branch is required for Branch Manager and Branch Warehouse Coordinator roles.", status_code=400)
    if primary_branch_id and not ObjectId.is_valid(str(primary_branch_id)):
        raise ApiError("Invalid primary_branch_id.", status_code=400)


def create_user(payload: dict, role: str) -> dict:
    role = normalize_role_value(role)
    role_ids = user_role_codes({"role_ids": payload.get("role_ids") or [], "roles": payload.get("roles") or [], "role": role, "user_type": payload.get("user_type")})
    if role and role not in role_ids:
        role_ids.insert(0, role)
    if not role_ids or any(not role_definition(item) for item in role_ids):
        raise ApiError("Invalid user role.", status_code=400)
    role = role or role_ids[0]
    _require_primary_branch_for_roles(role_ids, payload.get("primary_branch_id"))

    full_name = (payload.get("full_name") or "").strip()
    email = normalize_email(payload.get("email"))
    username = str(payload.get("username") or "").strip().lower() or None
    phone = normalize_phone(payload.get("phone"))
    password = payload.get("password")
    status = str(payload.get("status", "active" if role in {"owner", "admin", "fleet_owner", "personal_vehicle_owner"} else "inactive")).strip().lower()

    if not full_name:
        raise ApiError("Full name is required.", status_code=400)
    if email and not validate_email(email):
        raise ApiError("A valid email address is required.", status_code=400)
    if not username and not email:
        raise ApiError("Username or email is required.", status_code=400)
    if not phone:
        raise ApiError("Phone number is required.", status_code=400)
    if not validate_phone(phone):
        raise ApiError("A valid phone number is required.", status_code=400)
    if not password or len(password) < 6:
        raise ApiError("Password must be at least 6 characters long.", status_code=400)
    if status not in ALLOWED_STATUSES:
        raise ApiError("Invalid user status.", status_code=400)

    identity_filters = [{"phone": phone}]
    if email:
        identity_filters.append({"email": email})
    if username:
        identity_filters.append({"username": username})
    existing_user = users_read_collection().find_one({"$or": identity_filters})
    if existing_user:
        raise ApiError("A user with this email or phone already exists.", status_code=409)

    driver_profile = normalize_driver_profile_payload(payload) if "driver" in role_ids else None
    primary_branch_id = ObjectId(str(payload["primary_branch_id"])) if payload.get("primary_branch_id") and ObjectId.is_valid(str(payload["primary_branch_id"])) else None
    driver_scope_fields = _driver_scope_fields(payload, role_ids, primary_branch_id)
    branch_values = [payload.get("primary_branch_id"), payload.get("home_branch_id"), *(payload.get("allowed_branch_ids") or [])]
    branch_ids = {ObjectId(str(value)) for value in branch_values if value and ObjectId.is_valid(str(value))}
    if branch_ids and get_collection("branches").count_documents({"_id": {"$in": list(branch_ids)}, "status": "active"}) != len(branch_ids):
        raise ApiError("All assigned branches must exist and be active.", status_code=409)

    timestamp = now_utc()
    user_document = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "username": username,
        "branch": str(payload.get("branch") or "").strip() or None,
        "primary_branch_id": primary_branch_id,
        "allowed_branch_ids": [ObjectId(str(value)) for value in payload.get("allowed_branch_ids", []) if ObjectId.is_valid(str(value))],
        "created_by": ObjectId(str(payload["created_by"])) if payload.get("created_by") and ObjectId.is_valid(str(payload["created_by"])) else None,
        "password_hash": generate_password_hash(password),
        "role": role,
        "role_ids": role_ids,
        "status": status,
        "last_login": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "driver_profile": driver_profile,
        **driver_scope_fields,
        "must_change_password": bool(payload.get("temporary_password", False)),
        "temporary_password_issued_at": timestamp if payload.get("temporary_password", False) else None,
        "password_changed_at": None,
        "password_version": 1,
    }
    if not email:
        user_document.pop("email", None)
    try:
        insert_result = users_collection().insert_one(user_document)
    except DuplicateKeyError:
        raise ApiError("A user with this email or phone already exists.", status_code=409) from None

    user_document["_id"] = insert_result.inserted_id
    return serialize_user(user_document)


def create_session_token(user: dict) -> str:
    role_codes = user_role_codes(user)
    workspace = str(user.get("selected_workspace") or user.get("role") or (role_codes[0] if role_codes else "")).strip().lower()
    return create_access_token(
        identity=str(user.get("id") or user.get("_id")),
        additional_claims={
            "role": workspace,
            "roles": role_codes,
            "selected_workspace": workspace,
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "must_change_password": bool(user.get("must_change_password", False)),
        },
    )


def authenticate_user(identifier: str, password: str) -> dict:
    normalized_email = normalize_email(identifier)
    normalized_phone = normalize_phone(identifier)
    normalized_username = str(identifier or "").strip().lower()

    filters = []
    if normalized_email:
        filters.append({"email": normalized_email})
    if normalized_phone:
        filters.append({"phone": normalized_phone})
    if normalized_username:
        filters.append({"username": normalized_username})
    if not filters:
        raise ApiError("A valid username, email, or phone number is required.", status_code=400)

    user = users_read_collection().find_one({"$or": filters})
    if not user or not check_password_hash(user["password_hash"], password):
        try:
            write_audit("failed_login", metadata={"identifier": str(identifier or "")})
        except Exception:
            pass
        raise ApiError("Invalid login credentials.", status_code=401)

    if str(user["status"]).strip().lower() != "active":
        try:
            write_audit("failed_login", target_type="user", target_id=user["_id"], changes={"reason": "account_inactive"}, metadata={"identifier": str(identifier or "")})
        except Exception:
            pass
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
    try:
        write_audit("login", actor_user_id=user["_id"], target_type="user", target_id=user["_id"])
    except Exception:
        pass
    access_token = create_session_token(serialized_user)
    return {"user": serialized_user, "access_token": access_token}


def get_user_by_id(user_id: str) -> dict:
    return serialize_user(get_user_document_by_id(user_id))


def list_users_for_role(current_role: str) -> list[dict]:
    current_role = normalize_role_value(current_role) or current_role
    operational_roles = ["operations_manager", "driver", "field_agent", "issuing_receiving_officer", "branch_manager", "branch_warehouse_coordinator", "personal_vehicle_owner", "fleet_owner"]
    query = {} if current_role in {"owner", "system_administrator"} else {"$or": [{"role": {"$in": operational_roles}}, {"role_ids": {"$in": operational_roles}}]}
    users = users_collection().find(query).sort("created_at", ASCENDING)
    return [serialize_user(user) for user in users]


def list_users_for_actor(actor: dict) -> list[dict]:
    """List accounts from the actor's live, multi-role RBAC authority.

    The access-control route must not scope this decision from the JWT's legacy
    single-role claim: role assignments and explicit grants can change while a
    token remains valid.
    """
    if user_has_permission(actor, "users.manage"):
        documents = users_collection().find({}).sort("created_at", ASCENDING)
    elif user_has_permission(actor, "users.manage_operational"):
        operational_roles = {
            "operations_manager", "driver", "field_agent",
            "issuing_receiving_officer", "branch_manager", "branch_warehouse_coordinator", "personal_vehicle_owner", "fleet_owner",
        }
        documents = (
            user for user in users_collection().find({}).sort("created_at", ASCENDING)
            if operational_roles.intersection(user_role_codes(user))
        )
    else:
        raise ApiError("You do not have permission to access this resource.", status_code=403)
    return [serialize_user(user) for user in documents]


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
    requested_roles = user_role_codes(payload)
    primary_values = user_role_codes({"role": payload.get("role"), "user_type": payload.get("user_type")})
    requested_role = (primary_values[0] if primary_values else None) or (requested_roles[0] if requested_roles else None)
    if requested_role and requested_role not in requested_roles:
        requested_roles.insert(0, requested_role)
    if not requested_roles or any(not role_definition(item) for item in requested_roles):
        raise ApiError("Invalid user role.", status_code=400)

    operational_delegation = {"operations_manager", "driver", "field_agent", "issuing_receiving_officer", "branch_manager", "branch_warehouse_coordinator", "fleet_owner", "personal_vehicle_owner"}
    if current_role in {"admin", "operations_administrator"} and not set(requested_roles).issubset(operational_delegation):
        raise ApiError("Admin cannot create that account role.", status_code=403)
    actor = get_user_document_by_id(current_user_id) if current_user_id else {"role": current_role}
    if current_role not in {"admin", "operations_administrator"}:
        validate_role_assignment(actor, requested_roles)

    create_payload = {**payload}
    if requested_role == "personal_vehicle_owner":
        create_payload["temporary_password"] = True
    create_payload["created_by"] = current_user_id
    create_payload["role_ids"] = requested_roles
    user = create_user(create_payload, role=requested_role)
    _audit_user_management("user_created", current_user_id, current_role, ObjectId(user["id"]), {
        "role": requested_role, "role_ids": requested_roles, "status": user.get("status"), "temporary_password": bool(user.get("must_change_password")),
    })
    return user


def update_user_status_as(current_role: str, target_user_id: str, status: str, current_user_id: str | None = None) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    status = str(status).strip().lower()
    if status not in ALLOWED_STATUSES:
        raise ApiError("Invalid user status.", status_code=400)

    user = get_user_document_by_id(target_user_id)
    if current_role in {"admin", "operations_administrator"} and normalize_role_value(user.get("role")) not in {"operations_manager", "driver", "field_agent", "issuing_receiving_officer", "branch_manager", "branch_warehouse_coordinator", "fleet_owner", "personal_vehicle_owner"}:
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
    if current_role in {"admin", "operations_administrator"} and target_role not in {"operations_manager", "driver", "field_agent", "issuing_receiving_officer", "branch_manager", "branch_warehouse_coordinator", "personal_vehicle_owner"}:
        raise ApiError("Operations administrators can edit operational accounts only.", status_code=403)
    if current_role not in {"owner", "system_administrator", "admin", "operations_administrator"}:
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
    if "username" in payload:
        username = str(payload.get("username") or "").strip().lower()
        if not username:
            raise ApiError("Username is required.", status_code=400)
        updates["username"] = username
    if "role_ids" in payload or "roles" in payload:
        role_ids = user_role_codes({"role_ids": payload.get("role_ids") or [], "roles": payload.get("roles") or []})
        if not role_ids:
            raise ApiError("Select at least one role.", status_code=400)
        actor = get_user_document_by_id(current_user_id)
        if current_role not in {"admin", "operations_administrator"}:
            validate_role_assignment(actor, role_ids)
        if current_user_id == target_user_id and set(role_ids) != set(user_role_codes(user)):
            raise ApiError("You cannot change your own roles.", status_code=400)
        if current_role in {"admin", "operations_administrator"} and not set(role_ids).issubset({"operations_manager", "driver", "field_agent", "issuing_receiving_officer", "branch_manager", "branch_warehouse_coordinator", "fleet_owner", "personal_vehicle_owner"}):
            raise ApiError("Operations administrators can assign operational roles only.", status_code=403)
        updates["role_ids"] = role_ids
        primary_values = user_role_codes({"role": payload.get("role"), "user_type": payload.get("user_type")})
        primary_role = primary_values[0] if primary_values else None
        updates["role"] = primary_role if primary_role in role_ids else role_ids[0]
        if user.get("selected_workspace") not in role_ids:
            updates["selected_workspace"] = updates["role"]
    if "primary_branch_id" in payload:
        value = payload.get("primary_branch_id")
        updates["primary_branch_id"] = ObjectId(str(value)) if value and ObjectId.is_valid(str(value)) else None
    if "allowed_branch_ids" in payload:
        updates["allowed_branch_ids"] = [ObjectId(str(value)) for value in payload.get("allowed_branch_ids") or [] if ObjectId.is_valid(str(value))]
    effective_role_ids = updates.get("role_ids", user_role_codes(user))
    effective_primary_branch_id = updates.get("primary_branch_id", user.get("primary_branch_id"))
    _require_primary_branch_for_roles(effective_role_ids, effective_primary_branch_id)
    if "operational_scope" in payload or "home_branch_id" in payload or "driver" in effective_role_ids:
        updates.update(_driver_scope_fields(payload, effective_role_ids, effective_primary_branch_id, user))
    assigned_branch_ids = {value for value in [updates.get("primary_branch_id"), updates.get("home_branch_id"), *(updates.get("allowed_branch_ids", []))] if isinstance(value, ObjectId)}
    if assigned_branch_ids and get_collection("branches").count_documents({"_id":{"$in":list(assigned_branch_ids)},"status":"active"}) != len(assigned_branch_ids):
        raise ApiError("All assigned branches must exist and be active.", status_code=409)
    if not updates:
        raise ApiError("No editable account fields were provided.", status_code=400)
    duplicate_query = {"_id": {"$ne": user["_id"]}, "$or": []}
    if "email" in updates:
        duplicate_query["$or"].append({"email": updates["email"]})
    if "phone" in updates:
        duplicate_query["$or"].append({"phone": updates["phone"]})
    if "username" in updates:
        duplicate_query["$or"].append({"username": updates["username"]})
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
    if "role_ids" in updates:
        _audit_user_management("user_roles_changed", current_user_id, current_role, user["_id"], {"before": before.get("role_ids") or user_role_codes({"role": target_role}), "after": updates["role_ids"], "reason": payload.get("reason")})
    return serialize_user(user)


def reset_user_password_as(current_user_id: str, current_role: str, target_user_id: str, temporary_password: str) -> dict:
    current_role = normalize_role_value(current_role) or current_role
    user = get_user_document_by_id(target_user_id)
    target_role = normalize_role_value(user.get("role"))
    if current_role in {"admin", "operations_administrator"} and target_role not in {"operations_manager", "driver", "field_agent", "issuing_receiving_officer", "branch_manager", "branch_warehouse_coordinator", "personal_vehicle_owner"}:
        raise ApiError("Operations administrators can reset operational account passwords only.", status_code=403)
    if current_role not in {"owner", "system_administrator", "admin", "operations_administrator"}:
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
    if not role_definition(role):
        raise ApiError("Invalid user role.", status_code=400)
    if current_user_id == target_user_id:
        raise ApiError("You cannot change your own role.", status_code=400)

    user = get_user_document_by_id(target_user_id)
    validate_role_assignment(get_user_document_by_id(current_user_id), [role])
    timestamp = now_utc()
    users_collection().update_one(
        {"_id": user["_id"]},
        {"$set": {"role": role, "role_ids": [role], "selected_workspace": role, "updated_at": timestamp}},
    )
    user["role"] = role
    user["role_ids"] = [role]
    user["selected_workspace"] = role
    user["updated_at"] = timestamp
    _audit_user_management("role_changed", current_user_id, "system_administrator", user["_id"], {"to": role})
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
