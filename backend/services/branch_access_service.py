from __future__ import annotations

from bson import ObjectId

from extensions import get_collection
from services.rbac_service import effective_data_scope, normalize_role, user_role_codes
from utils.api_error import ApiError


GLOBAL_BRANCH_ROLES = {"owner", "system_administrator", "operations_administrator", "admin"}


def object_id(value, field="id") -> ObjectId:
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field}.", status_code=400)
    return ObjectId(str(value))


def branch_ids_for_user(user: dict) -> set[ObjectId] | None:
    if effective_data_scope(user) in {"ALL_BRANCHES", "ALL_RECORDS"} or set(user_role_codes(user)) & GLOBAL_BRANCH_ROLES:
        return None
    values = list(user.get("allowed_branch_ids") or [])
    if user.get("primary_branch_id"):
        values.append(user["primary_branch_id"])
    return {object_id(value, "branch id") for value in values if ObjectId.is_valid(str(value))}


def branch_query(user: dict, field="branch_id") -> dict:
    allowed = branch_ids_for_user(user)
    return {} if allowed is None else {field: {"$in": list(allowed)}}


def assert_branch_access(user: dict, branch_id, *, require_active=False) -> ObjectId:
    value = object_id(branch_id, "branch_id")
    allowed = branch_ids_for_user(user)
    if allowed is not None and value not in allowed:
        raise ApiError("You do not have access to this branch.", status_code=403)
    branch = get_collection("branches").find_one({"_id": value})
    if not branch:
        raise ApiError("Branch not found.", status_code=404)
    if require_active and str(branch.get("status") or ("active" if branch.get("active", True) else "inactive")).lower() != "active":
        raise ApiError("Inactive branches cannot receive new operational records.", status_code=409)
    return value


def current_user(user_id: str) -> dict:
    user = get_collection("users").find_one({"_id": object_id(user_id, "user identity")})
    if not user:
        raise ApiError("User not found.", status_code=404)
    return user


def assert_user_in_branch(target_user_id, branch_id, roles=None) -> dict:
    target = get_collection("users").find_one({"_id": object_id(target_user_id, "user id")})
    target_status = str(
        (target or {}).get("status")
        or ("active" if (target or {}).get("active", True) else "inactive")
    ).lower()
    if not target or target_status != "active":
        raise ApiError("Assigned user is unavailable.", status_code=409)
    if roles and not (set(user_role_codes(target)) & set(roles)):
        raise ApiError("Assigned user does not have the required role.", status_code=400)
    allowed = branch_ids_for_user(target)
    branch = object_id(branch_id, "branch_id")
    # Migration compatibility: a legacy operational user with no branch fields
    # is explicitly shown as Unassigned and may be assigned by an authorized
    # branch-scoped actor. Once branch data exists, normal scope enforcement
    # applies.
    if allowed == set() and not target.get("primary_branch_id") and not target.get("allowed_branch_ids"):
        return target
    if allowed is not None and branch not in allowed:
        raise ApiError("Assigned user does not belong to the selected branch.", status_code=409)
    return target
