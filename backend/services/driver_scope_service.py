from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING

from extensions import get_collection
from services.branch_access_service import branch_ids_for_user
from services.rbac_service import user_has_permission, user_role_codes
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


OPERATIONAL_SCOPES = {"COMPANY_WIDE", "BRANCH", "PERSONAL_ONLY"}
ACTIVE_ASSIGNMENT_STATUSES = {"scheduled", "active"}


def now_utc():
    return datetime.now(timezone.utc)


def _oid(value, field):
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field}.", status_code=400)
    return ObjectId(str(value))


def _datetime(value, field):
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApiError(f"{field} must be a valid date and time.", status_code=400) from exc
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def operational_scope_for_driver(driver: dict) -> str:
    explicit = str(driver.get("operational_scope") or "").strip().upper()
    if explicit in OPERATIONAL_SCOPES:
        return explicit
    if "personal_vehicle_owner" in user_role_codes(driver):
        return "PERSONAL_ONLY"
    return "BRANCH" if driver.get("home_branch_id") or driver.get("primary_branch_id") else "COMPANY_WIDE"


def ensure_driver_scope_indexes():
    ensure_indexes_for_collection(get_collection("driver_branch_assignments"), [
        {"keys": [("driver_id", ASCENDING), ("start_datetime", ASCENDING), ("end_datetime", ASCENDING)]},
        {"keys": [("branch_id", ASCENDING), ("status", ASCENDING), ("start_datetime", ASCENDING), ("end_datetime", ASCENDING)]},
        {"keys": [("linked_source_type", ASCENDING), ("linked_source_id", ASCENDING)], "options": {"sparse": True}},
    ], collection_name="driver_branch_assignments")


def _serialize(document):
    if not document:
        return None
    return {
        "id": str(document["_id"]), "driver_id": str(document["driver_id"]),
        "branch_id": str(document["branch_id"]),
        "start_datetime": document["start_datetime"].isoformat(),
        "end_datetime": document["end_datetime"].isoformat(),
        "purpose": document.get("purpose"), "linked_source_type": document.get("linked_source_type"),
        "linked_source_id": str(document["linked_source_id"]) if document.get("linked_source_id") else None,
        "assigned_by": str(document["assigned_by"]), "status": document.get("status"),
        "created_at": document["created_at"].isoformat(),
    }


def expire_temporary_assignments(at=None):
    timestamp = at or now_utc()
    return get_collection("driver_branch_assignments").update_many(
        {"status": {"$in": list(ACTIVE_ASSIGNMENT_STATUSES)}, "end_datetime": {"$lte": timestamp}},
        {"$set": {"status": "expired", "updated_at": timestamp}},
    ).modified_count


def active_temporary_driver_ids(branch_ids, *, at=None):
    timestamp = at or now_utc()
    expire_temporary_assignments(timestamp)
    return {
        row["driver_id"] for row in get_collection("driver_branch_assignments").find({
            "branch_id": {"$in": list(branch_ids)}, "status": {"$in": list(ACTIVE_ASSIGNMENT_STATUSES)},
            "start_datetime": {"$lte": timestamp}, "end_datetime": {"$gt": timestamp},
        }, {"driver_id": 1})
    }


def create_temporary_branch_assignment(payload, *, current_user_id, current_role):
    actor = get_collection("users").find_one({"_id": _oid(current_user_id, "user identity")}) or {"role": current_role}
    if not user_has_permission(actor, "driver.assign") and not set(user_role_codes(actor)) & {"owner", "admin", "system_administrator", "operations_administrator"}:
        raise ApiError("You do not have permission to assign drivers.", status_code=403)
    driver_id, branch_id = _oid(payload.get("driver_id"), "driver_id"), _oid(payload.get("branch_id"), "branch_id")
    driver = get_collection("users").find_one({"_id": driver_id})
    if not driver or "driver" not in user_role_codes(driver):
        raise ApiError("Driver not found.", status_code=404)
    if operational_scope_for_driver(driver) == "PERSONAL_ONLY" and not payload.get("explicit_personal_authorization"):
        raise ApiError("Personal-only drivers cannot be assigned to company operations.", status_code=409)
    if not get_collection("branches").find_one({"_id": branch_id}):
        raise ApiError("Branch not found.", status_code=404)
    start, end = _datetime(payload.get("start_datetime"), "start_datetime"), _datetime(payload.get("end_datetime"), "end_datetime")
    if end <= start:
        raise ApiError("end_datetime must be after start_datetime.", status_code=400)
    overlap = {"driver_id": driver_id, "status": {"$in": list(ACTIVE_ASSIGNMENT_STATUSES)}, "start_datetime": {"$lt": end}, "end_datetime": {"$gt": start}}
    if get_collection("driver_branch_assignments").find_one(overlap):
        raise ApiError("Driver already has an overlapping temporary branch assignment.", status_code=409)
    # Reuse the planner's cross-module reservation/movement/job conflict engine.
    from services.dispatch_planner_service import detect_dispatch_conflicts
    conflicts = detect_dispatch_conflicts(driver_id=str(driver_id), vehicle_id=None, scheduled_start_time=start, expected_return_time=end)
    if conflicts.get("driver_conflicts"):
        raise ApiError("; ".join(conflicts["driver_conflicts"]), status_code=409)
    timestamp = now_utc()
    document = {
        "driver_id": driver_id, "branch_id": branch_id, "start_datetime": start, "end_datetime": end,
        "purpose": str(payload.get("purpose") or "").strip() or None,
        "linked_source_type": str(payload.get("linked_source_type") or "").strip() or None,
        "linked_source_id": _oid(payload["linked_source_id"], "linked_source_id") if payload.get("linked_source_id") else None,
        "assigned_by": _oid(current_user_id, "user identity"), "status": "active" if start <= timestamp < end else "scheduled",
        "audit_log": [{"event": "temporary_branch_assignment_created", "actor_id": _oid(current_user_id, "user identity"), "timestamp": timestamp, "immutable": True}],
        "created_at": timestamp, "updated_at": timestamp,
    }
    document["_id"] = get_collection("driver_branch_assignments").insert_one(document).inserted_id
    return _serialize(document)


def list_temporary_branch_assignments(*, current_user_id, current_role):
    actor = get_collection("users").find_one({"_id": _oid(current_user_id, "user identity")}) or {"role": current_role}
    expire_temporary_assignments()
    allowed = branch_ids_for_user(actor)
    query = {} if allowed is None else {"branch_id": {"$in": list(allowed)}}
    if allowed is not None and not user_has_permission(actor, "driver.view"):
        raise ApiError("You do not have permission to view driver assignments.", status_code=403)
    return [_serialize(row) for row in get_collection("driver_branch_assignments").find(query).sort("start_datetime", ASCENDING)]


def driver_ids_visible_to_branch_user(user: dict, *, warehouse_only=False):
    allowed = branch_ids_for_user(user)
    if allowed is None:
        return None
    visible = set(active_temporary_driver_ids(allowed))
    if not warehouse_only:
        visible.update(row["_id"] for row in get_collection("users").find({
            "$and": [{"$or": [{"home_branch_id": {"$in": list(allowed)}}, {"primary_branch_id": {"$in": list(allowed)}}]}, {"$or": [{"role": "driver"}, {"role_ids": "driver"}]}]
        }, {"_id": 1}))
    for collection_name in ("stock_transfers", "delivery_batches", "delivery_runs"):
        branch_clauses = [{"destination_branch_id": {"$in": list(allowed)}}, {"receiving_location_id": {"$in": list(allowed)}}, {"branch_id": {"$in": list(allowed)}}]
        for row in get_collection(collection_name).find({"$or": branch_clauses, "driver_id": {"$exists": True}}, {"driver_id": 1}):
            if isinstance(row.get("driver_id"), ObjectId):
                visible.add(row["driver_id"])
    return visible
