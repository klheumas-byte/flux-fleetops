"""Controlled, auditable availability exceptions for maintenance/fault issues."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from services.fleet_owner_service import notify_linked_owner
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


ACTIVE_ISSUE_STATUSES = {"reported", "under_review", "approved", "converted_to_maintenance", "pending", "in_progress", "waiting_parts"}
TERMINAL_STATUSES = {"expired", "resolved", "revoked"}


def now_utc():
    return datetime.now(timezone.utc)


def overrides_collection():
    return get_collection("maintenance_availability_overrides")


def override_history_collection():
    return get_collection("maintenance_availability_override_history")


def ensure_maintenance_override_indexes():
    ensure_indexes_for_collection(overrides_collection(), [
        {"keys": [("linked_record_type", ASCENDING), ("linked_record_id", ASCENDING)], "options": {
            "unique": True, "partialFilterExpression": {"status": "active"}, "name": "uniq_active_linked_issue"
        }},
        {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING), ("repair_deadline", ASCENDING)]},
        {"keys": [("status", ASCENDING), ("repair_deadline", ASCENDING)]},
    ], collection_name="maintenance_availability_overrides")
    ensure_indexes_for_collection(override_history_collection(), [
        {"keys": [("override_id", ASCENDING), ("changed_at", DESCENDING)]},
    ], collection_name="maintenance_availability_override_history")


def _oid(value, field):
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field}.", status_code=400)
    return ObjectId(str(value))


def _datetime(value, field, *, required=True):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field} is required.", status_code=400)
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ApiError(f"{field} must be an ISO date-time.", status_code=400) from error
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _text(payload, field, max_length, *, required=True):
    value = str(payload.get(field) or "").strip()
    if required and not value:
        raise ApiError(f"{field} is required.", status_code=400)
    if len(value) > max_length:
        raise ApiError(f"{field} cannot exceed {max_length} characters.", status_code=400)
    return value or None


def _number(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ApiError(f"{field} must be a positive number.", status_code=400)
    return round(float(value), 2)


def _linked_issue(record_type, record_id):
    normalized_type = str(record_type or "").strip().lower()
    if normalized_type not in {"fault", "maintenance"}:
        raise ApiError("linked_record_type must be fault or maintenance.", status_code=400)
    object_id = _oid(record_id, "linked_record_id")
    collection_name = "faults" if normalized_type == "fault" else "maintenance_jobs"
    issue = get_collection(collection_name).find_one({"_id": object_id})
    if not issue:
        raise ApiError("Linked fault or maintenance record not found.", status_code=404)
    if issue.get("status") not in ACTIVE_ISSUE_STATUSES:
        raise ApiError("Only an active fault or maintenance obligation can be overridden.", status_code=409)
    severity = str(issue.get("severity") or issue.get("priority") or "medium").strip().lower()
    if severity == "critical" or bool(issue.get("vehicle_unsafe")):
        raise ApiError("Critical or non-operable issues cannot be overridden.", status_code=409)
    if normalized_type == "maintenance" and issue.get("fault_report_id"):
        linked_fault = get_collection("faults").find_one({"_id": issue["fault_report_id"]}, {"severity": 1, "vehicle_unsafe": 1})
        if linked_fault and (linked_fault.get("severity") == "critical" or linked_fault.get("vehicle_unsafe")):
            raise ApiError("Maintenance linked to a critical or unsafe fault cannot be overridden.", status_code=409)
    return normalized_type, issue, severity


def _serialize(document):
    def iso(value): return value.isoformat() if hasattr(value, "isoformat") else value
    return {
        "id": str(document["_id"]), "vehicle_id": str(document["vehicle_id"]),
        "linked_record_type": document["linked_record_type"], "linked_record_id": str(document["linked_record_id"]),
        "fault_severity": document.get("fault_severity"), "operational_restriction": document.get("operational_restriction"),
        "business_justification": document.get("business_justification"), "approved_by": str(document.get("approved_by")) if document.get("approved_by") else None,
        "approved_at": iso(document.get("approved_at")), "start_at": iso(document.get("start_at")),
        "repair_deadline": iso(document.get("repair_deadline")), "expires_at": iso(document.get("expires_at")),
        "reminder_hours_before": document.get("reminder_hours_before"), "maximum_mileage": document.get("maximum_mileage"),
        "maximum_hours": document.get("maximum_hours"), "notes": document.get("notes"), "status": document.get("status"),
        "is_overdue": bool(document.get("is_overdue")),
        "requires_operational_review": bool(document.get("requires_operational_review")),
        "active_operation_id": str(document.get("active_operation_id")) if document.get("active_operation_id") else None,
        "acknowledgements": [
            {"driver_id": str(item["driver_id"]), "acknowledged_at": iso(item["acknowledged_at"])}
            for item in document.get("acknowledgements", [])
        ], "created_at": iso(document.get("created_at")), "updated_at": iso(document.get("updated_at")),
    }


def _audit(document, action, actor_id=None, details=None):
    override_history_collection().insert_one({
        "override_id": document["_id"], "vehicle_id": document["vehicle_id"], "action": action,
        "actor_id": _oid(actor_id, "actor_id") if actor_id else None, "details": details or {},
        "status": document.get("status"), "changed_at": now_utc(), "immutable": True,
    })


def _notify_change(document, event, title, message, priority="high"):
    reference_id = document["_id"]
    notify_linked_owner(document["vehicle_id"], f"maintenance_override_{event}", title=title, message=message, priority=priority, reference_id=reference_id)
    notify_roles(["owner", "admin"], title=title, message=message, category="maintenance", priority=priority,
                 reference_type="maintenance_override", reference_id=reference_id,
                 dedupe_key=f"maintenance-override:{reference_id}:{event}", action_url="maintenance")
    vehicle = get_collection("vehicles").find_one({"_id": document["vehicle_id"]}, {"assigned_driver_id": 1})
    if vehicle and vehicle.get("assigned_driver_id"):
        create_notification(vehicle["assigned_driver_id"], title, message, category="maintenance", priority=priority,
                            reference_type="maintenance_override", reference_id=reference_id,
                            dedupe_key=f"maintenance-override:{reference_id}:{event}:driver")


def create_override(payload, current_user_id, current_role):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to approve maintenance overrides.", status_code=403)
    linked_type, issue, severity = _linked_issue(payload.get("linked_record_type"), payload.get("linked_record_id"))
    vehicle_id = _oid(payload.get("vehicle_id") or issue.get("vehicle_id"), "vehicle_id")
    if issue.get("vehicle_id") != vehicle_id or not get_collection("vehicles").find_one({"_id": vehicle_id}):
        raise ApiError("The linked issue does not belong to this vehicle.", status_code=409)
    timestamp = now_utc()
    start_at = _datetime(payload.get("start_at"), "start_at", required=False) or timestamp
    deadline = _datetime(payload.get("repair_deadline"), "repair_deadline")
    expires_at = _datetime(payload.get("expires_at"), "expires_at", required=False) or deadline
    if deadline <= start_at or expires_at <= start_at:
        raise ApiError("Repair deadline and expiry must be after the override start.", status_code=400)
    reminder_hours = payload.get("reminder_hours_before", 24)
    if isinstance(reminder_hours, bool) or not isinstance(reminder_hours, (int, float)) or reminder_hours < 0:
        raise ApiError("reminder_hours_before must be a non-negative number.", status_code=400)
    document = {
        "vehicle_id": vehicle_id, "linked_record_type": linked_type, "linked_record_id": issue["_id"],
        "fault_severity": severity, "operational_restriction": _text(payload, "operational_restriction", 1000),
        "business_justification": _text(payload, "business_justification", 1000),
        "approved_by": _oid(current_user_id, "approved_by"), "approved_at": timestamp,
        "start_at": start_at, "repair_deadline": deadline, "expires_at": expires_at,
        "reminder_hours_before": float(reminder_hours), "maximum_mileage": _number(payload.get("maximum_mileage"), "maximum_mileage"),
        "maximum_hours": _number(payload.get("maximum_hours"), "maximum_hours"), "notes": _text(payload, "notes", 1000, required=False),
        "status": "active", "is_overdue": False, "acknowledgements": [], "version": 1,
        "created_at": timestamp, "updated_at": timestamp,
    }
    try:
        document["_id"] = overrides_collection().insert_one(document).inserted_id
    except DuplicateKeyError:
        raise ApiError("An active override already exists for this issue.", status_code=409) from None
    _audit(document, "approved", current_user_id)
    _notify_change(document, "approved", "Vehicle available with restriction", document["operational_restriction"])
    reminder_at = deadline - timedelta(hours=float(reminder_hours))
    for recipient in get_collection("users").find({"role": {"$in": ["owner", "admin"]}, "status": "active"}, {"_id": 1}):
        create_notification(recipient["_id"], "Restricted vehicle repair deadline approaching",
                            "A maintenance override is approaching its mandatory repair deadline.", category="maintenance", priority="high",
                            reference_type="maintenance_override", reference_id=document["_id"], scheduled_for=reminder_at,
                            due_at=deadline, dedupe_key=f"maintenance-override:{document['_id']}:deadline-reminder:{recipient['_id']}")
    return _serialize(document)


def reconcile_expired_overrides(vehicle_id=None, *, collection=None):
    collection = overrides_collection() if collection is None else collection
    timestamp = now_utc()
    query = {"status": "active", "$or": [{"repair_deadline": {"$lte": timestamp}}, {"expires_at": {"$lte": timestamp}}]}
    if vehicle_id:
        query["vehicle_id"] = _oid(vehicle_id, "vehicle_id")
    expired = list(collection.find(query))
    for document in expired:
        active_operation = get_collection("dispatch_jobs").find_one({
            "vehicle_id": document["vehicle_id"],
            "status": {"$in": ["reserved", "assigned", "accepted", "clarification_requested", "in_progress"]},
        }, {"_id": 1})
        result = collection.update_one({"_id": document["_id"], "status": "active"}, {"$set": {
            "status": "expired", "is_overdue": document.get("repair_deadline") <= timestamp,
            "requires_operational_review": bool(active_operation),
            "active_operation_id": active_operation.get("_id") if active_operation else None,
            "expired_at": timestamp, "updated_at": timestamp,
        }})
        if result.modified_count:
            document.update({"status": "expired", "is_overdue": document.get("repair_deadline") <= timestamp})
            _audit(document, "expired")
            _notify_change(document, "expired", "Maintenance override expired", "The vehicle restriction expired; new assignments are blocked.", "critical")
    return len(expired)


def active_overrides_for_vehicle(vehicle_id, *, collection=None):
    collection = overrides_collection() if collection is None else collection
    reconcile_expired_overrides(vehicle_id, collection=collection)
    timestamp = now_utc()
    return list(collection.find({
        "vehicle_id": _oid(vehicle_id, "vehicle_id"), "status": "active",
        "start_at": {"$lte": timestamp}, "repair_deadline": {"$gt": timestamp}, "expires_at": {"$gt": timestamp},
    }).sort("repair_deadline", ASCENDING))


def active_overrides_for_vehicles(vehicle_ids, *, collection=None):
    object_ids = [_oid(item, "vehicle_id") for item in vehicle_ids]
    if not object_ids:
        return {}
    collection = overrides_collection() if collection is None else collection
    reconcile_expired_overrides(collection=collection)
    timestamp = now_utc()
    grouped = {}
    for document in collection.find({
        "vehicle_id": {"$in": object_ids}, "status": "active", "start_at": {"$lte": timestamp},
        "repair_deadline": {"$gt": timestamp}, "expires_at": {"$gt": timestamp},
    }).sort("repair_deadline", ASCENDING):
        grouped.setdefault(document["vehicle_id"], []).append(document)
    return grouped


def transition_override(override_id, action, current_user_id, current_role, notes=None):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to manage maintenance overrides.", status_code=403)
    if action not in {"revoked", "resolved"}:
        raise ApiError("Invalid override transition.", status_code=400)
    document = overrides_collection().find_one({"_id": _oid(override_id, "override_id")})
    if not document:
        raise ApiError("Maintenance override not found.", status_code=404)
    if document.get("status") == action:
        return _serialize(document)
    if document.get("status") != "active":
        raise ApiError("Only an active override can be changed.", status_code=409)
    timestamp = now_utc()
    result = overrides_collection().update_one({"_id": document["_id"], "status": "active"}, {"$set": {
        "status": action, f"{action}_at": timestamp, f"{action}_by": _oid(current_user_id, "actor_id"),
        "transition_notes": str(notes or "").strip() or None, "updated_at": timestamp,
    }})
    if result.modified_count != 1:
        refreshed = overrides_collection().find_one({"_id": document["_id"]})
        if refreshed and refreshed.get("status") == action:
            return _serialize(refreshed)
        raise ApiError("The override changed in another request.", status_code=409)
    document["status"] = action
    _audit(document, action, current_user_id, {"notes": str(notes or "").strip() or None})
    _notify_change(document, action, f"Maintenance override {action}", "The vehicle restriction changed; new work availability was recalculated.")
    return _serialize(document)


def close_overrides_for_issue(record_type, record_id, actor_id=None):
    document = overrides_collection().find_one({
        "linked_record_type": record_type, "linked_record_id": _oid(record_id, "linked_record_id"), "status": "active"
    })
    if not document:
        return None
    timestamp = now_utc()
    result = overrides_collection().update_one({"_id": document["_id"], "status": "active"}, {"$set": {
        "status": "resolved", "resolved_at": timestamp, "resolved_by": _oid(actor_id, "actor_id") if actor_id else None,
        "resolution_source": "linked_issue", "updated_at": timestamp,
    }})
    if result.modified_count:
        document["status"] = "resolved"; _audit(document, "resolved", actor_id, {"source": "linked_issue"})
    return document


def acknowledge_override(override_id, current_user_id):
    driver_id = _oid(current_user_id, "driver_id")
    document = overrides_collection().find_one({"_id": _oid(override_id, "override_id"), "status": "active"})
    if not document:
        raise ApiError("Active maintenance override not found.", status_code=404)
    vehicle = get_collection("vehicles").find_one({"_id": document["vehicle_id"]}, {"assigned_driver_id": 1})
    assignment = get_collection("assignments").find_one({"vehicle_id": document["vehicle_id"], "driver_id": driver_id, "allocation_active": True})
    if not vehicle or (vehicle.get("assigned_driver_id") != driver_id and not assignment):
        raise ApiError("You can acknowledge restrictions only for your assigned vehicle.", status_code=403)
    if any(item.get("driver_id") == driver_id for item in document.get("acknowledgements", [])):
        return _serialize(document)
    acknowledgement = {"driver_id": driver_id, "acknowledged_at": now_utc()}
    overrides_collection().update_one({"_id": document["_id"], "acknowledgements.driver_id": {"$ne": driver_id}}, {"$push": {"acknowledgements": acknowledgement}, "$set": {"updated_at": now_utc()}})
    document.setdefault("acknowledgements", []).append(acknowledgement); _audit(document, "acknowledged", current_user_id)
    return _serialize(document)


def list_overrides(current_user_id, current_role, *, vehicle_id=None, status=None, page=1, page_size=50):
    reconcile_expired_overrides(vehicle_id)
    query = {}
    if vehicle_id: query["vehicle_id"] = _oid(vehicle_id, "vehicle_id")
    if status: query["status"] = status
    if current_role == "fleet_owner":
        profile = get_collection("fleet_owners").find_one({"account_id": _oid(current_user_id, "current_user_id")})
        vehicle_ids = [item["_id"] for item in get_collection("vehicles").find({"fleet_owner_id": (profile or {}).get("_id")}, {"_id": 1})]
        query["vehicle_id"] = {"$in": vehicle_ids}
    elif current_role == "driver":
        assignment = get_collection("assignments").find_one({"driver_id": _oid(current_user_id, "current_user_id"), "allocation_active": True})
        query["vehicle_id"] = (assignment or {}).get("vehicle_id", ObjectId())
    elif current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to view maintenance overrides.", status_code=403)
    page = max(int(page or 1), 1); page_size = min(max(int(page_size or 50), 1), 100)
    total = overrides_collection().count_documents(query)
    rows = overrides_collection().find(query).sort("created_at", DESCENDING).skip((page - 1) * page_size).limit(page_size)
    return {"records": [_serialize(item) for item in rows], "pagination": {"page": page, "page_size": page_size, "total": total}}


def override_history(override_id, current_user_id, current_role):
    scoped = list_overrides(current_user_id, current_role, page=1, page_size=100)
    if str(override_id) not in {item["id"] for item in scoped["records"]}:
        raise ApiError("Maintenance override not found.", status_code=404)
    rows = override_history_collection().find({"override_id": _oid(override_id, "override_id")}).sort("changed_at", DESCENDING).limit(100)
    return [{"action": row["action"], "status": row.get("status"), "changed_at": row["changed_at"].isoformat()} for row in rows]
