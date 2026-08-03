from datetime import datetime, timezone

from bson import ObjectId
from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from services.rbac_service import (
    DATA_SCOPES, PERMISSION_CATALOG, list_roles, permission_groups,
    permissions_for_user, role_definition, serialize_audit, serialize_role, user_has_permission,
    user_role_codes, validate_role_assignment, write_audit,
)
from models.user import serialize_user
from services.auth_service import create_session_token
from utils.decorators import login_required, permission_required
from utils.responses import error_response, success_response


rbac_bp = Blueprint("rbac", __name__)


def _current_user():
    identity = get_jwt_identity()
    return get_collection("users").find_one({"_id": ObjectId(identity)}) if ObjectId.is_valid(str(identity)) else None


def _page_args(default_limit=50, max_limit=200):
    try:
        page = max(int(request.args.get("page", 1)), 1)
        limit = min(max(int(request.args.get("limit", default_limit)), 1), max_limit)
    except ValueError:
        page, limit = 1, default_limit
    return page, limit


@rbac_bp.get("/roles")
@permission_required("roles.manage")
def roles():
    return success_response(data={"roles": list_roles()})


@rbac_bp.get("/assignable-roles")
@permission_required("users.manage_operational")
def assignable_roles():
    actor_permissions = set(permissions_for_user(_current_user()))
    elevated = "*" in actor_permissions or "permissions.manage" in actor_permissions
    available = [role for role in list_roles(include_inactive=False) if (elevated or set(role["permissions"]).issubset(actor_permissions)) and ("profitability.view" not in role["permissions"] or "profitability.view" in actor_permissions or "*" in actor_permissions)]
    return success_response(data={"roles": available})


def _role_payload(payload, existing=None):
    code = str(payload.get("code") or (existing or {}).get("code") or "").strip().lower().replace(" ", "_")
    name = str(payload.get("name") or (existing or {}).get("name") or "").strip()
    if not code or not name or not all(character.isalnum() or character == "_" for character in code):
        return None, "Role name and a lowercase alphanumeric code are required."
    permissions = sorted(set(payload.get("permissions", (existing or {}).get("permissions", []))))
    invalid = [item for item in permissions if item not in PERMISSION_CATALOG]
    if invalid:
        return None, "One or more permissions are invalid."
    scope = payload.get("default_data_scope", (existing or {}).get("default_data_scope", "OWN_RECORDS"))
    if scope not in DATA_SCOPES:
        return None, "Invalid default data scope."
    status = payload.get("status", (existing or {}).get("status", "active"))
    if status not in {"active", "inactive"}:
        return None, "Role status must be active or inactive."
    return {"code": code, "name": name, "description": str(payload.get("description", (existing or {}).get("description", ""))).strip(), "dashboard": str(payload.get("dashboard", (existing or {}).get("dashboard", "dashboard"))).strip() or "dashboard", "permissions": permissions, "default_data_scope": scope, "status": status}, None


@rbac_bp.post("/roles")
@permission_required("roles.manage")
def create_role():
    actor = _current_user()
    payload = request.get_json(silent=True) or {}
    document, error = _role_payload(payload)
    if error:
        return error_response(error, status_code=400)
    if any(item in {"profitability.view", "permissions.manage", "users.manage", "security.manage"} for item in document["permissions"]) and not str(payload.get("reason") or "").strip():
        return error_response("A reason is required when granting sensitive access.", status_code=400)
    try:
        effective = set() if not actor else set(permissions_for_user(actor))
        if "*" not in effective and "permissions.manage" not in effective and not set(document["permissions"]).issubset(effective):
            return error_response("You cannot create a role containing permissions beyond your authority.", status_code=403)
        if "profitability.view" in document["permissions"] and "*" not in effective and "profitability.view" not in effective:
            return error_response("You are not authorized to grant profitability access.", status_code=403)
        timestamp = datetime.now(timezone.utc)
        document.update({"system": False, "created_at": timestamp, "updated_at": timestamp, "created_by": ObjectId(get_jwt_identity())})
        result = get_collection("roles").insert_one(document)
    except DuplicateKeyError:
        return error_response("Role code already exists.", status_code=409)
    document["_id"] = result.inserted_id
    write_audit("role_created", get_jwt_identity(), "role", document["code"], {"new": document})
    return success_response(data={"role": serialize_role(document["code"], document)}, message="Role created successfully.", status_code=201)


@rbac_bp.patch("/roles/<role_code>")
@permission_required("roles.manage")
def update_role(role_code):
    stored = get_collection("roles").find_one({"code": role_code})
    base = stored or role_definition(role_code)
    if not base:
        return error_response("Role not found.", status_code=404)
    payload = request.get_json(silent=True) or {}
    if base.get("system") and any(key in payload for key in ("code", "status")):
        return error_response("System and legacy roles cannot be renamed or deactivated.", status_code=409)
    document, error = _role_payload(payload, {**base, "code": role_code})
    if error:
        return error_response(error, status_code=400)
    sensitive = {"profitability.view", "permissions.manage", "users.manage", "security.manage"}
    if (set(document["permissions"]) ^ set(base.get("permissions", []))) & sensitive and not str(payload.get("reason") or "").strip():
        return error_response("A reason is required when changing sensitive access.", status_code=400)
    document["code"] = role_code
    actor = _current_user()
    effective = set(permissions_for_user(actor))
    if "*" not in effective and "permissions.manage" not in effective and not set(document["permissions"]).issubset(effective):
        return error_response("You cannot grant permissions beyond your authority.", status_code=403)
    timestamp = datetime.now(timezone.utc)
    document.update({"system": bool(base.get("system")), "legacy": bool(base.get("legacy")), "updated_at": timestamp})
    if stored:
        get_collection("roles").update_one({"_id": stored["_id"]}, {"$set": document})
    else:
        document.update({"created_at": timestamp, "created_by": ObjectId(get_jwt_identity())})
        get_collection("roles").insert_one(document)
    write_audit("role_updated", get_jwt_identity(), "role", role_code, {"old": {key: base.get(key) for key in document}, "new": document, "reason": payload.get("reason")})
    return success_response(data={"role": serialize_role(role_code, document)}, message="Role updated successfully.")


@rbac_bp.post("/roles/<role_code>/clone")
@permission_required("roles.manage")
def clone_role(role_code):
    source = role_definition(role_code)
    if not source:
        return error_response("Role not found.", status_code=404)
    payload = request.get_json(silent=True) or {}
    payload.setdefault("permissions", source.get("permissions", []))
    payload.setdefault("default_data_scope", source.get("default_data_scope", "OWN_RECORDS"))
    payload.setdefault("dashboard", source.get("dashboard", "dashboard"))
    document, error = _role_payload(payload)
    if error:
        return error_response(error, status_code=400)
    timestamp = datetime.now(timezone.utc)
    document.update({"system": False, "created_at": timestamp, "updated_at": timestamp, "created_by": ObjectId(get_jwt_identity())})
    try:
        get_collection("roles").insert_one(document)
    except DuplicateKeyError:
        return error_response("Role code already exists.", status_code=409)
    write_audit("role_cloned", get_jwt_identity(), "role", document["code"], {"source": role_code, "new": document})
    return success_response(data={"role": serialize_role(document["code"], document)}, message="Role cloned successfully.", status_code=201)


@rbac_bp.get("/roles/<role_code>/users")
@permission_required("roles.manage")
def assigned_role_users(role_code):
    from models.user import serialize_user
    users = [serialize_user(item) for item in get_collection("users").find({"$or": [{"role": role_code}, {"role_ids": role_code}]}).sort("full_name", 1)]
    return success_response(data={"users": users})


@rbac_bp.get("/permissions")
@permission_required("permissions.manage")
def permissions():
    return success_response(data={"permissions": sorted(PERMISSION_CATALOG), "groups": permission_groups()})


@rbac_bp.patch("/users/<user_id>/permissions")
@permission_required("permissions.manage")
def update_user_permissions(user_id: str):
    if not ObjectId.is_valid(user_id):
        return error_response("User not found.", status_code=404)
    payload = request.get_json(silent=True) or {}
    grants = sorted(set(payload.get("grants") or [])); denials = sorted(set(payload.get("denials") or []))
    if any(item not in PERMISSION_CATALOG for item in grants + denials):
        return error_response("One or more permissions are invalid.", status_code=400)
    actor = _current_user(); effective = set(permissions_for_user(actor))
    if "*" not in effective and "permissions.manage" not in effective and not set(grants).issubset(effective):
        return error_response("You cannot grant permissions beyond your authority.", status_code=403)
    if "profitability.view" in grants and "profitability.view" not in effective and "*" not in effective:
        return error_response("You are not authorized to grant profitability access.", status_code=403)
    previous = get_collection("users").find_one({"_id": ObjectId(user_id)}, {"permission_grants": 1, "permission_denials": 1})
    if not previous:
        return error_response("User not found.", status_code=404)
    get_collection("users").update_one({"_id": ObjectId(user_id)}, {"$set": {"permission_grants": grants, "permission_denials": denials, "updated_at": datetime.now(timezone.utc)}})
    write_audit("permission_changed", get_jwt_identity(), "user", user_id, {"old": previous, "new": {"grants": grants, "denials": denials}, "reason": payload.get("reason")})
    return success_response(message="User permissions updated successfully.")


def _branch(document):
    def value(item): return item.isoformat() if hasattr(item, "isoformat") else str(item) if isinstance(item, ObjectId) else item
    status = document.get("status") or ("active" if document.get("active", True) else "inactive")
    keys = ("code", "name", "location", "manager_id", "manager_name", "phone", "email", "notes", "is_head_office", "created_by", "created_at", "updated_at")
    return {key: value(document.get(key)) for key in keys} | {"id": str(document["_id"]), "status": status, "active": status == "active"}


@rbac_bp.get("/branches")
@permission_required("branches.view")
def branches():
    query = {}
    if request.args.get("active") == "true": query["status"] = "active"
    return success_response(data={"branches": [_branch(item) for item in get_collection("branches").find(query).sort("name", 1)]})


def _branch_payload(payload, existing=None):
    source = existing or {}
    code = str(payload.get("code", source.get("code", ""))).strip().upper()
    name = str(payload.get("name", source.get("name", ""))).strip()
    if not code or not name:
        return None, "Branch name and code are required."
    status = payload.get("status", source.get("status", "active"))
    if status not in {"active", "inactive"}: return None, "Branch status must be active or inactive."
    manager_id = payload.get("manager_id", source.get("manager_id"))
    if manager_id and not ObjectId.is_valid(str(manager_id)): return None, "Select a valid branch manager."
    return {"code": code, "name": name, "location": str(payload.get("location", source.get("location", ""))).strip(), "manager_id": ObjectId(str(manager_id)) if manager_id else None, "manager_name": str(payload.get("manager_name", source.get("manager_name", ""))).strip(), "phone": str(payload.get("phone", source.get("phone", ""))).strip(), "email": str(payload.get("email", source.get("email", ""))).strip(), "notes": str(payload.get("notes", source.get("notes", ""))).strip(), "status": status, "active": status == "active", "is_head_office": bool(payload.get("is_head_office", source.get("is_head_office", False)))}, None


@rbac_bp.post("/branches")
@permission_required("branches.manage")
def create_branch():
    document, error = _branch_payload(request.get_json(silent=True) or {})
    if error: return error_response(error, status_code=400)
    if document["is_head_office"] and get_collection("branches").find_one({"is_head_office": True, "status": "active"}):
        return error_response("Only one active head office is allowed.", status_code=409)
    timestamp = datetime.now(timezone.utc); document.update({"created_by": ObjectId(get_jwt_identity()), "created_at": timestamp, "updated_at": timestamp})
    try: result = get_collection("branches").insert_one(document)
    except DuplicateKeyError: return error_response("Branch code already exists.", status_code=409)
    document["_id"] = result.inserted_id; write_audit("branch_created", get_jwt_identity(), "branch", result.inserted_id, {"new": document})
    return success_response(data={"branch": _branch(document)}, status_code=201)


@rbac_bp.get("/branches/<branch_id>")
@permission_required("branches.view")
def branch_detail(branch_id):
    if not ObjectId.is_valid(branch_id): return error_response("Branch not found.", status_code=404)
    branch = get_collection("branches").find_one({"_id": ObjectId(branch_id)})
    if not branch: return error_response("Branch not found.", status_code=404)
    linked = {
        "users": get_collection("users").count_documents({"$or": [{"primary_branch_id": branch["_id"]}, {"allowed_branch_ids": branch["_id"]}]}),
        "vehicles": get_collection("vehicles").count_documents({"branch_id": branch["_id"]}),
        "drivers": get_collection("users").count_documents({"$and": [{"$or": [{"role": "driver"}, {"role_ids": "driver"}]}, {"$or": [{"primary_branch_id": branch["_id"]}, {"allowed_branch_ids": branch["_id"]}]}]}),
        "deliveries": get_collection("delivery_orders").count_documents({"branch_id": branch["_id"]}),
        "operational_records": get_collection("delivery_batches").count_documents({"branch_id": branch["_id"]}),
    }
    return success_response(data={"branch": {**_branch(branch), "linked_records": linked}})


@rbac_bp.patch("/branches/<branch_id>")
@permission_required("branches.manage")
def branch_update(branch_id):
    if not ObjectId.is_valid(branch_id): return error_response("Branch not found.", status_code=404)
    branch = get_collection("branches").find_one({"_id": ObjectId(branch_id)})
    if not branch: return error_response("Branch not found.", status_code=404)
    payload = request.get_json(silent=True) or {}; updates, error = _branch_payload(payload, branch)
    if error: return error_response(error, status_code=400)
    if updates["is_head_office"] and updates["status"] == "active" and get_collection("branches").find_one({"_id": {"$ne": branch["_id"]}, "is_head_office": True, "status": "active"}):
        return error_response("Only one active head office is allowed.", status_code=409)
    updates["updated_at"] = datetime.now(timezone.utc)
    try: get_collection("branches").update_one({"_id": branch["_id"]}, {"$set": updates})
    except DuplicateKeyError: return error_response("Branch code already exists.", status_code=409)
    write_audit("branch_changed", get_jwt_identity(), "branch", branch_id, {"old": {key: branch.get(key) for key in updates}, "new": updates, "reason": payload.get("reason")}, {"branch_id": branch_id})
    branch.update(updates); return success_response(data={"branch": _branch(branch)}, message="Branch updated successfully.")


@rbac_bp.get("/audit-logs")
@permission_required("audit.view")
def audit_logs():
    page, limit = _page_args(); query = {}
    if request.args.get("action"): query["action"] = request.args["action"]
    total = get_collection("audit_logs").count_documents(query)
    logs = [serialize_audit(item) for item in get_collection("audit_logs").find(query).sort("created_at", -1).skip((page - 1) * limit).limit(limit)]
    return success_response(data={"logs": logs, "pagination": {"page": page, "limit": limit, "total": total}})


@rbac_bp.get("/login-history")
@permission_required("users.manage_operational")
def all_login_history():
    page, limit = _page_args(); query = {"action": {"$in": ["login", "failed_login", "logout"]}}
    total = get_collection("audit_logs").count_documents(query)
    logs = [serialize_audit(item) for item in get_collection("audit_logs").find(query).sort("created_at", -1).skip((page - 1) * limit).limit(limit)]
    return success_response(data={"logs": logs, "pagination": {"page": page, "limit": limit, "total": total}})


@rbac_bp.get("/users/<user_id>/login-history")
@permission_required("users.manage_operational")
def login_history(user_id: str):
    if not ObjectId.is_valid(user_id): return error_response("User not found.", status_code=404)
    query = {"action": {"$in": ["login", "failed_login", "logout"]}, "$or": [{"actor_user_id": ObjectId(user_id)}, {"target_id": user_id}]}
    return success_response(data={"logs": [serialize_audit(item) for item in get_collection("audit_logs").find(query).sort("created_at", -1).limit(100)]})


@rbac_bp.post("/workspace")
@login_required
def switch_workspace():
    payload = request.get_json(silent=True) or {}; role_code = str(payload.get("role") or "").strip().lower(); user = _current_user()
    role_codes = user_role_codes(user)
    if role_code not in role_codes or role_definition(role_code).get("status") != "active":
        return error_response("That workspace is not assigned to your account.", status_code=403)
    previous = user.get("selected_workspace") or user.get("role")
    get_collection("users").update_one({"_id": user["_id"]}, {"$set": {"selected_workspace": role_code, "updated_at": datetime.now(timezone.utc)}})
    write_audit("workspace_changed", user["_id"], "user", user["_id"], {"old": {"workspace": previous}, "new": {"workspace": role_code}})
    user["selected_workspace"] = role_code
    serialized = serialize_user(user)
    return success_response(data={"workspace": role_code, "dashboard": serialized["dashboard"], "user": serialized, "access_token": create_session_token(serialized)}, message="Workspace changed.")
