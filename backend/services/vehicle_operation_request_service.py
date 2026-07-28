from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.vehicle_operation_request import (
    serialize_mongo_value,
    serialize_vehicle_operation_request,
)
from services.movement_source_service import ensure_movement_for_source
from services.notification_service import create_notification, notify_roles, resolve_action_notifications
from services.vehicle_availability_service import resolve_many, resolve_vehicle_availability
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


OPERATION_TYPES = {
    "internal_company_delivery",
    "fuel_station_visit",
    "compliance_inspection_visit",
    "administrative_errand",
    "vehicle_repositioning",
}
REQUEST_STATUSES = {
    "draft",
    "pending_approval",
    "approved",
    "scheduled",
    "movement_in_progress",
    "awaiting_verification",
    "completed",
    "rejected",
    "cancelled",
    "aborted",
}
TERMINAL_STATUSES = {"completed", "rejected", "cancelled", "aborted"}
PRIORITIES = {"low", "normal", "high", "critical"}
JOURNEY_MODES = {"one_way", "round_trip", "multi_stop"}
LIST_PROJECTION = {
    "request_id": 1,
    "operation_type": 1,
    "title": 1,
    "purpose": 1,
    "journey_mode": 1,
    "source_location_id": 1,
    "destination_location_id": 1,
    "origin": 1,
    "destination": 1,
    "origin_snapshot": 1,
    "destination_snapshot": 1,
    "planned_stops": 1,
    "delivery_items": 1,
    "sender_name": 1,
    "intended_receiver_name": 1,
    "business_unit": 1,
    "vehicle_id": 1,
    "driver_id": 1,
    "requested_by": 1,
    "approved_by": 1,
    "approved_at": 1,
    "planned_departure_at": 1,
    "expected_return_at": 1,
    "status": 1,
    "priority": 1,
    "financial_class": 1,
    "cost_responsibility": 1,
    "linked_vehicle_movement_id": 1,
    "related_source_type": 1,
    "related_source_id": 1,
    "receiver_confirmation": 1,
    "task_confirmation": 1,
    "destination_acceptance": 1,
    "no_purchase_reason": 1,
    "fuel_log_id": 1,
    "acknowledged_at": 1,
    "opening_check_completed_at": 1,
    "created_at": 1,
    "updated_at": 1,
    "version": 1,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def requests_collection():
    return get_collection("vehicle_operation_requests")


def movements_collection():
    return get_collection("vehicle_movements")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def _text(value, *, required: bool = False, field: str = "value"):
    normalized = str(value or "").strip() or None
    if required and not normalized:
        raise ApiError(f"{field} is required.", status_code=400)
    return normalized


def _object_id(value, field: str, *, required: bool = True):
    if value in (None, "") and not required:
        return None
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field}.", status_code=400)
    return ObjectId(str(value))


def _datetime(value, field: str):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApiError(f"{field} must be a valid date and time.", status_code=400) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot(value, fallback: str | None):
    if isinstance(value, dict):
        name = _text(value.get("name") or value.get("label") or fallback)
        return {"name": name, "address": _text(value.get("address"))} if name else None
    return {"name": fallback} if fallback else None


def _planned_stops(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ApiError("planned_stops must be a list with at most 20 stops.", status_code=400)
    stops = []
    for raw in value:
        if isinstance(raw, str):
            name = _text(raw)
            if name:
                stops.append({"name": name})
        elif isinstance(raw, dict):
            name = _text(raw.get("name") or raw.get("label"), required=True, field="planned stop name")
            stops.append({"name": name, "address": _text(raw.get("address")), "notes": _text(raw.get("notes"))})
        else:
            raise ApiError("Each planned stop must be text or an object.", status_code=400)
    return stops


def _attachments(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ApiError("attachments must be a list with at most 20 metadata records.", status_code=400)
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise ApiError("Attachment entries must be metadata objects.", status_code=400)
        if item.get("data") or item.get("base64"):
            raise ApiError("Embedded attachment payloads are not supported.", status_code=400)
        result.append({
            "name": _text(item.get("name"), required=True, field="attachment name"),
            "url": _text(item.get("url"), required=True, field="attachment URL"),
            "content_type": _text(item.get("content_type")),
        })
    return result


def _delivery_items(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > 100:
        raise ApiError("delivery_items must be a list with at most 100 items.", status_code=400)
    result = []
    for item in value:
        if isinstance(item, str):
            result.append({"description": _text(item, required=True, field="delivery item")})
            continue
        if not isinstance(item, dict):
            raise ApiError("Delivery items must be text or metadata objects.", status_code=400)
        result.append({
            "description": _text(item.get("description") or item.get("name"), required=True, field="delivery item description"),
            "quantity": item.get("quantity"),
            "reference": _text(item.get("reference")),
        })
    return result


def ensure_vehicle_operation_request_indexes():
    ensure_indexes_for_collection(
        requests_collection(),
        [
            {"keys": [("request_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("operation_type", ASCENDING), ("status", ASCENDING), ("planned_departure_at", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING), ("planned_departure_at", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("linked_vehicle_movement_id", ASCENDING)], "options": {"sparse": True}},
            {
                "keys": [("related_source_key", ASCENDING)],
                "options": {"sparse": True},
            },
        ],
        collection_name="vehicle_operation_requests",
    )


def _get_request(request_id: str, projection=None) -> dict:
    object_id = _object_id(request_id, "request_id")
    document = requests_collection().find_one({"_id": object_id}, projection)
    if not document:
        raise ApiError("Operational request not found.", status_code=404)
    return document


def _assert_access(document: dict, *, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    if current_role == "driver" and str(document.get("driver_id")) == str(current_user_id):
        return
    raise ApiError("You do not have permission to access this operational request.", status_code=403)


def _validate_vehicle_driver(vehicle_id, driver_id, *, driver_required: bool = True):
    vehicle = vehicles_collection().find_one({"_id": vehicle_id}, {"registration_number": 1, "status": 1, "assigned_driver_id": 1})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    driver = None
    if driver_id:
        driver = users_collection().find_one({"_id": driver_id, "role": "driver", "status": "active"}, {"full_name": 1, "role": 1, "status": 1, "driver_profile": 1})
        if not driver:
            raise ApiError("Active driver not found.", status_code=404)
        approval = str((driver.get("driver_profile") or {}).get("approval_status") or "approved").lower()
        if approval != "approved":
            raise ApiError("Selected driver is not approved.", status_code=400)
    elif driver_required:
        raise ApiError("driver_id is required.", status_code=400)
    return vehicle, driver


def _serialize_with_relations(documents: list[dict], *, include_evidence: bool = False):
    vehicle_ids = {item.get("vehicle_id") for item in documents if isinstance(item.get("vehicle_id"), ObjectId)}
    user_ids = {
        value
        for item in documents
        for value in (item.get("driver_id"), item.get("requested_by"), item.get("approved_by"))
        if isinstance(value, ObjectId)
    }
    vehicles = {item["_id"]: item for item in vehicles_collection().find({"_id": {"$in": list(vehicle_ids)}}, {"registration_number": 1, "make": 1, "model": 1, "vehicle_type": 1})} if vehicle_ids else {}
    users = {item["_id"]: item for item in users_collection().find({"_id": {"$in": list(user_ids)}}, {"full_name": 1, "role": 1})} if user_ids else {}
    result = []
    for document in documents:
        payload = serialize_vehicle_operation_request(document, include_evidence=include_evidence)
        vehicle = vehicles.get(document.get("vehicle_id"))
        payload["vehicle"] = ({"id": str(vehicle["_id"]), "registration_number": vehicle.get("registration_number"), "make": vehicle.get("make"), "model": vehicle.get("model"), "vehicle_type": vehicle.get("vehicle_type")} if vehicle else None)
        for field in ("driver", "requester", "approver"):
            source_field = {"driver": "driver_id", "requester": "requested_by", "approver": "approved_by"}[field]
            user = users.get(document.get(source_field))
            payload[field] = {"id": str(user["_id"]), "full_name": user.get("full_name"), "role": user.get("role")} if user else None
        result.append(serialize_mongo_value(payload))
    return result


def _normalize_create(payload: dict) -> dict:
    operation_type = _text(payload.get("operation_type"), required=True, field="operation_type").lower()
    if operation_type not in OPERATION_TYPES:
        raise ApiError("Invalid operational request type.", status_code=400)
    purpose = _text(payload.get("purpose"), required=True, field="purpose")
    origin = _text(payload.get("origin"))
    destination = _text(payload.get("destination"))
    if operation_type in {"administrative_errand", "vehicle_repositioning", "internal_company_delivery", "compliance_inspection_visit", "fuel_station_visit"} and not destination:
        raise ApiError("destination is required for this operation.", status_code=400)
    if operation_type == "vehicle_repositioning" and not origin:
        raise ApiError("origin is required for vehicle repositioning.", status_code=400)
    source_location_id = _object_id(payload.get("source_location_id"), "source_location_id", required=False)
    destination_location_id = _object_id(payload.get("destination_location_id"), "destination_location_id", required=False)
    related_source_type = _text(payload.get("related_source_type"))
    related_source_id = _object_id(payload.get("related_source_id"), "related_source_id", required=False)
    if operation_type == "compliance_inspection_visit" and related_source_type and related_source_type != "compliance_record":
        raise ApiError("Compliance visits may only link to a compliance_record.", status_code=400)
    journey_mode = (_text(payload.get("journey_mode")) or "round_trip").lower()
    if journey_mode not in JOURNEY_MODES:
        raise ApiError("journey_mode must be one_way, round_trip, or multi_stop.", status_code=400)
    priority = (_text(payload.get("priority")) or "normal").lower()
    if priority not in PRIORITIES:
        raise ApiError("Invalid priority.", status_code=400)
    planned_departure_at = _datetime(payload.get("planned_departure_at"), "planned_departure_at")
    expected_return_at = _datetime(payload.get("expected_return_at"), "expected_return_at")
    if planned_departure_at and expected_return_at and expected_return_at <= planned_departure_at:
        raise ApiError("expected_return_at must be after planned_departure_at.", status_code=400)
    transport_mode = (_text(payload.get("transport_mode")) or "company_driver").lower()
    if transport_mode not in {"company_driver", "tow", "third_party"}:
        raise ApiError("transport_mode must be company_driver, tow, or third_party.", status_code=400)
    return {
        "operation_type": operation_type,
        "title": _text(payload.get("title")) or purpose,
        "purpose": purpose,
        "journey_mode": journey_mode,
        "source_location_id": source_location_id,
        "destination_location_id": destination_location_id,
        "origin": origin,
        "destination": destination,
        "origin_snapshot": _snapshot(payload.get("origin_snapshot"), origin),
        "destination_snapshot": _snapshot(payload.get("destination_snapshot"), destination),
        "planned_stops": _planned_stops(payload.get("planned_stops")),
        "delivery_items": _delivery_items(payload.get("delivery_items")) if operation_type == "internal_company_delivery" else [],
        "sender_name": _text(payload.get("sender_name")),
        "intended_receiver_name": _text(payload.get("intended_receiver_name")),
        "business_unit": _text(payload.get("business_unit")),
        "planned_departure_at": planned_departure_at,
        "expected_return_at": expected_return_at,
        "priority": priority,
        "cost_responsibility": _text(payload.get("cost_responsibility")) or "company",
        "notes": _text(payload.get("notes")),
        "attachments": _attachments(payload.get("attachments")),
        "related_source_type": related_source_type,
        "related_source_id": related_source_id,
        "related_source_key": f"{related_source_type}:{related_source_id}" if related_source_type and related_source_id else None,
        "transport_mode": transport_mode,
    }


def create_operational_request(payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can create operational requests.", status_code=403)
    normalized = _normalize_create(payload or {})
    timestamp = now_utc()
    status = "pending_approval" if bool(payload.get("submit_for_approval")) else "draft"
    document = {
        **normalized,
        "request_id": f"OR-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
        "vehicle_id": None,
        "driver_id": None,
        "requested_by": _object_id(current_user_id, "current_user_id"),
        "approved_by": None,
        "approved_at": None,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "status": status,
        "financial_class": "non_revenue",
        "linked_vehicle_movement_id": None,
        "receiver_confirmation": None,
        "task_confirmation": None,
        "destination_acceptance": None,
        "no_purchase_reason": None,
        "fuel_log_id": None,
        "version": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if document.get("related_source_key") and requests_collection().find_one(
        {"related_source_key": document["related_source_key"], "status": {"$nin": sorted(TERMINAL_STATUSES)}},
        {"_id": 1},
    ):
        raise ApiError("An open operational request already exists for this source event.", status_code=409)
    try:
        document["_id"] = requests_collection().insert_one(document).inserted_id
    except DuplicateKeyError:
        raise ApiError("An operational request already exists for this source event.", status_code=409) from None
    if status == "pending_approval":
        _notify_approval_needed(document)
    return _serialize_with_relations([document], include_evidence=True)[0]


def list_operational_requests(*, current_user_id: str, current_role: str, page=1, page_size=25, status=None, operation_type=None) -> dict:
    query = {}
    if current_role == "driver":
        query["driver_id"] = _object_id(current_user_id, "current_user_id")
    elif current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to list operational requests.", status_code=403)
    if status:
        if status not in REQUEST_STATUSES:
            raise ApiError("Invalid operational request status.", status_code=400)
        query["status"] = status
    if operation_type:
        if operation_type not in OPERATION_TYPES:
            raise ApiError("Invalid operational request type.", status_code=400)
        query["operation_type"] = operation_type
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 25), 1), 100)
    total = requests_collection().count_documents(query)
    documents = list(requests_collection().find(query, LIST_PROJECTION).sort([("created_at", DESCENDING), ("_id", DESCENDING)]).skip((page - 1) * page_size).limit(page_size))
    return {"requests": _serialize_with_relations(documents), "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": max(1, ceil(total / page_size))}}


def get_operational_request(request_id: str, *, current_user_id: str, current_role: str) -> dict:
    document = _get_request(request_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    return _serialize_with_relations([document], include_evidence=True)[0]


def update_operational_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can edit operational requests.", status_code=403)
    document = _get_request(request_id)
    if document.get("status") != "draft":
        raise ApiError("Only draft operational requests can be edited.", status_code=400)
    merged = {**document, **(payload or {})}
    normalized = _normalize_create(merged)
    related_key = normalized.get("related_source_key")
    if related_key and requests_collection().find_one(
        {"_id": {"$ne": document["_id"]}, "related_source_key": related_key, "status": {"$nin": sorted(TERMINAL_STATUSES)}},
        {"_id": 1},
    ):
        raise ApiError("An open operational request already exists for this source event.", status_code=409)
    normalized.update({"updated_at": now_utc(), "version": int(document.get("version") or 1) + 1})
    requests_collection().update_one({"_id": document["_id"], "status": "draft"}, {"$set": normalized})
    document.update(normalized)
    return _serialize_with_relations([document], include_evidence=True)[0]


def submit_operational_request(request_id: str, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can submit operational requests.", status_code=403)
    document = _get_request(request_id)
    if document.get("status") == "pending_approval":
        return _serialize_with_relations([document])[0]
    if document.get("status") != "draft":
        raise ApiError("Only draft requests can be submitted.", status_code=400)
    updates = {"status": "pending_approval", "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    requests_collection().update_one({"_id": document["_id"], "status": "draft"}, {"$set": updates})
    document.update(updates)
    _notify_approval_needed(document)
    return _serialize_with_relations([document])[0]


def _notify_approval_needed(document: dict):
    notify_roles(
        ["owner", "admin"],
        title="Operational request awaiting approval",
        message=f"{document.get('request_id')} · {document.get('title')}",
        category="operational_requests",
        module="operational-requests",
        priority="high" if document.get("priority") in {"high", "critical"} else "medium",
        reference_type="vehicle_operation_request",
        reference_id=document["_id"],
        action_type="approve_operational_request",
        action_url="operational-requests",
        action_label="Review request",
        dedupe_key=f"operation:{document['_id']}:approval",
    )


def approve_operational_request(request_id: str, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can approve operational requests.", status_code=403)
    document = _get_request(request_id)
    if document.get("status") in {"approved", "scheduled", "movement_in_progress", "awaiting_verification", "completed"}:
        return _serialize_with_relations([document])[0]
    if document.get("status") != "pending_approval":
        raise ApiError("This request is not awaiting approval.", status_code=400)
    actor = _object_id(current_user_id, "current_user_id")
    timestamp = now_utc()
    updates = {"status": "approved", "approved_by": actor, "approved_at": timestamp, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    requests_collection().update_one({"_id": document["_id"], "status": "pending_approval"}, {"$set": updates})
    document.update(updates)
    resolve_action_notifications("vehicle_operation_request", document["_id"], action_type="approve_operational_request", completed_by=current_user_id)
    return _serialize_with_relations([document])[0]


def reject_operational_request(request_id: str, reason: str, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can reject operational requests.", status_code=403)
    document = _get_request(request_id)
    if document.get("status") == "rejected":
        return _serialize_with_relations([document])[0]
    if document.get("status") not in {"pending_approval", "approved"}:
        raise ApiError("This request cannot be rejected now.", status_code=400)
    timestamp = now_utc()
    updates = {"status": "rejected", "rejected_by": _object_id(current_user_id, "current_user_id"), "rejected_at": timestamp, "rejection_reason": _text(reason, required=True, field="rejection_reason"), "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    requests_collection().update_one({"_id": document["_id"]}, {"$set": updates})
    document.update(updates)
    resolve_action_notifications("vehicle_operation_request", document["_id"], resolution="cancelled", completed_by=current_user_id)
    return _serialize_with_relations([document])[0]


def _assert_availability(document: dict, vehicle_id: ObjectId):
    availability = resolve_vehicle_availability(
        vehicle_id,
        context={
            "movement_type": document.get("operation_type"),
            "related_source_type": document.get("related_source_type"),
            "related_source_id": document.get("related_source_id"),
            "exclude_movement_id": document.get("linked_vehicle_movement_id"),
        },
    )
    if not availability.get("is_available"):
        reasons = availability.get("blocking_reasons") or []
        raise ApiError("; ".join(item.get("message") for item in reasons) or "Vehicle is unavailable.", status_code=409)


def _ensure_request_movement(document: dict, *, current_user_id: str) -> dict:
    existing = None
    linked_id = document.get("linked_vehicle_movement_id")
    if isinstance(linked_id, ObjectId):
        existing = movements_collection().find_one({"_id": linked_id})
        if existing and (existing.get("vehicle_id") != document.get("vehicle_id") or existing.get("source_id") not in {None, document["_id"]}):
            raise ApiError("Linked movement does not belong to this request and vehicle.", status_code=409)
    if existing is None:
        existing = movements_collection().find_one({"source_key": f"vehicle_operation_request:{document['_id']}"})
    if existing is None:
        _assert_availability(document, document["vehicle_id"])
    actor = _object_id(current_user_id, "current_user_id")
    timestamp = now_utc()
    result = ensure_movement_for_source(
        source_type="vehicle_operation_request",
        source_record_id=document["_id"],
        source_reference=document.get("request_id"),
        existing_movement=existing,
        movement_defaults={
            "vehicle_id": document["vehicle_id"],
            "driver_id": document.get("driver_id"),
            "movement_custodian_id": None,
            "operation_request_id": document["_id"],
            "related_source_type": document.get("related_source_type"),
            "related_source_id": document.get("related_source_id"),
            "movement_type": document["operation_type"],
            "financial_class": "non_revenue",
            "status": "approved",
            "requested_departure_time": document.get("planned_departure_at"),
            "expected_return_time": document.get("expected_return_at"),
            "origin": document.get("origin"),
            "destination": document.get("destination"),
            "origin_location_id": document.get("source_location_id"),
            "destination_location_id": document.get("destination_location_id"),
            "origin_snapshot": document.get("origin_snapshot"),
            "destination_snapshot": document.get("destination_snapshot"),
            "journey_mode": document.get("journey_mode"),
            "planned_stops": document.get("planned_stops") or [],
            "purpose": document.get("purpose"),
            "notes": document.get("notes"),
            "delivery_status": "pending" if document.get("operation_type") == "internal_company_delivery" else None,
            "custody_state": "pending_acceptance" if document.get("driver_id") else "company_custody",
            "custody_events": [],
            "custody_version": 0,
            "approved_by": actor,
            "approved_at": timestamp,
            "created_by": actor,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    movement = result["movement"]
    if movement.get("vehicle_id") != document.get("vehicle_id"):
        raise ApiError("Operational request movement belongs to another vehicle.", status_code=409)
    if document.get("linked_vehicle_movement_id") != movement["_id"]:
        requests_collection().update_one({"_id": document["_id"]}, {"$set": {"linked_vehicle_movement_id": movement["_id"], "updated_at": now_utc()}})
        document["linked_vehicle_movement_id"] = movement["_id"]
    return movement


def _reassign_scheduled_operational_request(
    document: dict,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    if document.get("acknowledged_at"):
        raise ApiError(
            "An Operational Request cannot be reassigned after the driver acknowledges it.",
            status_code=409,
        )
    vehicle_id = _object_id(payload.get("vehicle_id") or document.get("vehicle_id"), "vehicle_id")
    driver_id = _object_id(payload.get("driver_id") or document.get("driver_id"), "driver_id", required=False)
    third_party = document.get("operation_type") == "compliance_inspection_visit" and document.get("transport_mode") in {"tow", "third_party"}
    _validate_vehicle_driver(vehicle_id, driver_id, driver_required=not third_party)
    _assert_availability(document, vehicle_id)
    departure = _datetime(payload.get("planned_departure_at"), "planned_departure_at") or document.get("planned_departure_at")
    expected_return = _datetime(payload.get("expected_return_at"), "expected_return_at") or document.get("expected_return_at")
    if not departure:
        raise ApiError("planned_departure_at is required before reassignment.", status_code=400)
    if expected_return and expected_return <= departure:
        raise ApiError("expected_return_at must be after planned_departure_at.", status_code=400)
    movement_id = document.get("linked_vehicle_movement_id")
    movement = movements_collection().find_one({"_id": movement_id}) if isinstance(movement_id, ObjectId) else None
    if not movement or movement.get("status") != "approved":
        raise ApiError(
            "Operational Request movement cannot be reassigned after physical checkout.",
            status_code=409,
        )
    timestamp = now_utc()
    movement_result = movements_collection().update_one(
        {
            "_id": movement["_id"],
            "source_key": f"vehicle_operation_request:{document['_id']}",
            "status": "approved",
        },
        {"$set": {
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "requested_departure_time": departure,
            "expected_return_time": expected_return,
            "updated_at": timestamp,
        }},
    )
    if movement_result.modified_count != 1:
        raise ApiError("Operational Request movement could not be reassigned.", status_code=409)
    updates = {
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "planned_departure_at": departure,
        "expected_return_at": expected_return,
        "scheduled_by": _object_id(current_user_id, "current_user_id"),
        "updated_at": timestamp,
        "version": int(document.get("version") or 1) + 1,
    }
    requests_collection().update_one(
        {"_id": document["_id"], "status": "scheduled", "acknowledged_at": None},
        {"$set": updates},
    )
    document.update(updates)
    if driver_id:
        from services.movement_custody_service import transfer_movement_custody
        transfer_movement_custody(
            movement["_id"],
            {
                "to_user_id": str(driver_id),
                "event_type": "transferred_between_drivers",
                "audit_reason": _text(payload.get("reason")) or "Operations Planner reassignment.",
            },
            current_user_id=current_user_id,
            current_role=current_role,
            source_event_key=f"operation:{document['_id']}:reassigned:{driver_id}",
        )
        resolve_action_notifications(
            "vehicle_operation_request",
            document["_id"],
            action_type="acknowledge_operational_request",
            completed_by=current_user_id,
        )
        create_notification(
            driver_id,
            "Operational task assigned",
            f"{document.get('request_id')} · {document.get('title')}",
            category="operational_requests",
            module="my-operational-tasks",
            priority="high",
            reference_type="vehicle_operation_request",
            reference_id=document["_id"],
            action_type="acknowledge_operational_request",
            action_url="my-operational-tasks",
            action_label="Review task",
            dedupe_key=f"operation:{document['_id']}:driver:{driver_id}",
        )
    return _serialize_with_relations([document])[0]


def schedule_operational_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can schedule operational requests.", status_code=403)
    document = _get_request(request_id)
    if document.get("status") == "scheduled" and document.get("linked_vehicle_movement_id"):
        requested_vehicle = _object_id(payload.get("vehicle_id"), "vehicle_id", required=False)
        requested_driver = _object_id(payload.get("driver_id"), "driver_id", required=False)
        requested_departure = _datetime(payload.get("planned_departure_at"), "planned_departure_at")
        requested_return = _datetime(payload.get("expected_return_at"), "expected_return_at")
        if (
            (requested_vehicle and requested_vehicle != document.get("vehicle_id"))
            or (requested_driver and requested_driver != document.get("driver_id"))
            or (requested_departure and requested_departure != document.get("planned_departure_at"))
            or (requested_return and requested_return != document.get("expected_return_at"))
        ):
            return _reassign_scheduled_operational_request(
                document,
                payload,
                current_user_id=current_user_id,
                current_role=current_role,
            )
        movement = _ensure_request_movement(document, current_user_id=current_user_id)
        if document.get("driver_id") and not document.get("acknowledged_at"):
            from services.movement_custody_service import transfer_movement_custody
            transfer_movement_custody(movement["_id"], {"to_user_id": str(document["driver_id"]), "event_type": "released_to_driver"}, current_user_id=current_user_id, current_role=current_role, source_event_key=f"operation:{document['_id']}:release-to-driver")
        return _serialize_with_relations([document])[0]
    if document.get("status") != "approved":
        raise ApiError("Approve the request before scheduling it.", status_code=400)
    vehicle_id = _object_id(payload.get("vehicle_id") or document.get("vehicle_id"), "vehicle_id")
    driver_id = _object_id(payload.get("driver_id") or document.get("driver_id"), "driver_id", required=False)
    third_party = document.get("operation_type") == "compliance_inspection_visit" and document.get("transport_mode") in {"tow", "third_party"}
    _validate_vehicle_driver(vehicle_id, driver_id, driver_required=not third_party)
    if document.get("operation_type") == "compliance_inspection_visit" and document.get("related_source_id"):
        compliance_record = get_collection("vehicle_compliance_records").find_one(
            {"_id": document["related_source_id"]}, {"vehicle_id": 1}
        )
        if not compliance_record:
            raise ApiError("Linked compliance record not found.", status_code=404)
        if compliance_record.get("vehicle_id") != vehicle_id:
            raise ApiError("Compliance record belongs to another vehicle.", status_code=409)
    departure = _datetime(payload.get("planned_departure_at"), "planned_departure_at") or document.get("planned_departure_at")
    expected_return = _datetime(payload.get("expected_return_at"), "expected_return_at") or document.get("expected_return_at")
    if not departure:
        raise ApiError("planned_departure_at is required before scheduling.", status_code=400)
    if expected_return and expected_return <= departure:
        raise ApiError("expected_return_at must be after planned_departure_at.", status_code=400)
    if document.get("operation_type") == "vehicle_repositioning":
        same_id = document.get("source_location_id") and document.get("source_location_id") == document.get("destination_location_id")
        same_text = document.get("origin") and document.get("origin").casefold() == str(document.get("destination") or "").casefold()
        if (same_id or same_text) and not _text(payload.get("override_reason")):
            raise ApiError("Repositioning to the same location requires an audited override reason.", status_code=400)
    updates = {"vehicle_id": vehicle_id, "driver_id": driver_id, "planned_departure_at": departure, "expected_return_at": expected_return, "scheduled_by": _object_id(current_user_id, "current_user_id"), "scheduled_at": now_utc(), "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    if payload.get("override_reason"):
        updates["schedule_override_reason"] = _text(payload.get("override_reason"))
    document.update(updates)
    movement = _ensure_request_movement(document, current_user_id=current_user_id)
    if driver_id:
        from services.movement_custody_service import transfer_movement_custody
        transfer_movement_custody(
            movement["_id"],
            {"to_user_id": str(driver_id), "event_type": "released_to_driver"},
            current_user_id=current_user_id,
            current_role=current_role,
            source_event_key=f"operation:{document['_id']}:release-to-driver",
        )
    updates.update({"status": "scheduled", "linked_vehicle_movement_id": movement["_id"]})
    requests_collection().update_one({"_id": document["_id"], "status": "approved"}, {"$set": updates})
    document.update(updates)
    resolve_action_notifications("vehicle_operation_request", document["_id"], action_type="assign_operational_request", completed_by=current_user_id)
    if driver_id:
        create_notification(
            driver_id,
            "Operational task assigned",
            f"{document.get('request_id')} · {document.get('title')}",
            category="operational_requests",
            module="my-operational-tasks",
            priority="high",
            reference_type="vehicle_operation_request",
            reference_id=document["_id"],
            action_type="acknowledge_operational_request",
            action_url="my-operational-tasks",
            action_label="Review task",
            dedupe_key=f"operation:{document['_id']}:driver:{driver_id}",
        )
    return _serialize_with_relations([document])[0]


def acknowledge_operational_request(request_id: str, *, current_user_id: str, current_role: str) -> dict:
    if current_role != "driver":
        raise ApiError("Only the assigned driver can acknowledge this task.", status_code=403)
    document = _get_request(request_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if document.get("acknowledged_at"):
        return _serialize_with_relations([document])[0]
    if document.get("status") != "scheduled":
        raise ApiError("This task is not awaiting acknowledgement.", status_code=400)
    from services.movement_custody_service import accept_movement_custody
    accept_movement_custody(
        document["linked_vehicle_movement_id"],
        {},
        current_user_id=current_user_id,
        current_role=current_role,
        source_event_key=f"operation:{document['_id']}:driver-acceptance",
    )
    updates = {"acknowledged_at": now_utc(), "acknowledged_by": _object_id(current_user_id, "current_user_id"), "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    requests_collection().update_one({"_id": document["_id"]}, {"$set": updates})
    document.update(updates)
    resolve_action_notifications("vehicle_operation_request", document["_id"], action_type="acknowledge_operational_request", completed_by=current_user_id)
    return _serialize_with_relations([document])[0]


def open_operational_movement(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    document = _get_request(request_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if current_role == "driver" and not document.get("acknowledged_at"):
        raise ApiError("Acknowledge the task before the opening check.", status_code=400)
    movement = _ensure_request_movement(document, current_user_id=current_user_id)
    if movement.get("status") == "checked_out":
        return _serialize_with_relations([document])[0]
    from services.vehicle_movement_service import check_out_vehicle_movement
    check_out_vehicle_movement(str(movement["_id"]), payload or {}, current_user_id=current_user_id, current_role=current_role)
    updates = {
        "opening_check_completed_at": now_utc(),
        "opening_check_completed_by": _object_id(current_user_id, "current_user_id"),
        "updated_at": now_utc(),
        "version": int(document.get("version") or 1) + 1,
    }
    requests_collection().update_one({"_id": document["_id"]}, {"$set": updates})
    document.update(updates)
    return _serialize_with_relations([document])[0]


def start_operational_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    document = _get_request(request_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if document.get("status") == "movement_in_progress":
        return _serialize_with_relations([document])[0]
    if document.get("status") != "scheduled":
        raise ApiError("This task is not scheduled for movement.", status_code=400)
    movement = _ensure_request_movement(document, current_user_id=current_user_id)
    if movement.get("status") != "checked_out":
        raise ApiError("Complete the opening check before starting movement.", status_code=400)
    from services.vehicle_movement_service import start_vehicle_movement
    start_vehicle_movement(str(movement["_id"]), payload or {}, current_user_id=current_user_id, current_role=current_role)
    updates = {"status": "movement_in_progress", "started_at": now_utc(), "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    requests_collection().update_one({"_id": document["_id"]}, {"$set": updates})
    document.update(updates)
    return _serialize_with_relations([document])[0]


def confirm_operational_task(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    document = _get_request(request_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if document.get("status") not in {"movement_in_progress", "awaiting_verification"}:
        raise ApiError("Start the movement before confirming the task.", status_code=400)
    timestamp = now_utc()
    confirmation = {"confirmed_at": timestamp, "confirmed_by": _object_id(current_user_id, "current_user_id"), "notes": _text(payload.get("notes"))}
    operation_type = document.get("operation_type")
    updates = {}
    if operation_type == "internal_company_delivery":
        confirmation["receiver_name"] = _text(payload.get("receiver_name"), required=True, field="receiver_name")
        updates["receiver_confirmation"] = confirmation
    elif operation_type == "fuel_station_visit":
        fuel_log_id = _object_id(payload.get("fuel_log_id"), "fuel_log_id", required=False)
        no_purchase_reason = _text(payload.get("no_purchase_reason"))
        if not fuel_log_id and not no_purchase_reason:
            raise ApiError("Provide a linked fuel log or a no-purchase reason.", status_code=400)
        if fuel_log_id:
            fuel_log = get_collection("fuel_logs").find_one({"_id": fuel_log_id})
            if not fuel_log or fuel_log.get("vehicle_id") != document.get("vehicle_id"):
                raise ApiError("Fuel log does not belong to this vehicle.", status_code=409)
            movement_id = document.get("linked_vehicle_movement_id")
            if fuel_log.get("movement_id") not in {None, movement_id}:
                raise ApiError("Fuel log is already linked to another movement.", status_code=409)
            get_collection("fuel_logs").update_one({"_id": fuel_log_id}, {"$set": {"movement_id": movement_id, "updated_at": timestamp}})
            updates["fuel_log_id"] = fuel_log_id
        updates["no_purchase_reason"] = no_purchase_reason
        updates["task_confirmation"] = confirmation
    elif operation_type == "compliance_inspection_visit":
        confirmation["outcome"] = _text(payload.get("outcome"), required=True, field="inspection outcome")
        confirmation["compliance_record_id"] = document.get("related_source_id")
        updates["task_confirmation"] = confirmation
    elif operation_type == "vehicle_repositioning":
        confirmation["accepted_by_name"] = _text(payload.get("accepted_by_name"), required=True, field="accepted_by_name")
        updates["destination_acceptance"] = confirmation
    else:
        confirmation["task_completed"] = True
        updates["task_confirmation"] = confirmation
    updates.update({"updated_at": timestamp, "version": int(document.get("version") or 1) + 1})
    requests_collection().update_one({"_id": document["_id"]}, {"$set": updates})
    document.update(updates)
    return _serialize_with_relations([document])[0]


def return_operational_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    document = _get_request(request_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if document.get("status") == "awaiting_verification":
        return _serialize_with_relations([document])[0]
    if document.get("status") != "movement_in_progress":
        raise ApiError("This movement is not in progress.", status_code=400)
    movement = _ensure_request_movement(document, current_user_id=current_user_id)
    from services.vehicle_movement_service import return_vehicle_movement
    return_vehicle_movement(str(movement["_id"]), payload or {}, current_user_id=current_user_id, current_role=current_role)
    from services.movement_custody_service import return_movement_custody
    destination_custody = (
        document.get("destination")
        if document.get("operation_type") == "vehicle_repositioning" or document.get("journey_mode") == "one_way"
        else "Company custody"
    )
    return_movement_custody(
        movement["_id"],
        {**(payload or {}), "to_location": destination_custody},
        current_user_id=current_user_id,
        current_role=current_role,
        source_event_key=f"operation:{document['_id']}:custody-return",
    )
    updates = {"status": "awaiting_verification", "returned_at": now_utc(), "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    requests_collection().update_one({"_id": document["_id"]}, {"$set": updates})
    document.update(updates)
    notify_roles(["owner", "admin"], title="Operational task awaiting verification", message=f"{document.get('request_id')} has physically returned.", category="operational_requests", module="operational-requests", priority="high", reference_type="vehicle_operation_request", reference_id=document["_id"], action_type="verify_operational_request", action_url="operational-requests", action_label="Verify completion", dedupe_key=f"operation:{document['_id']}:verification")
    return _serialize_with_relations([document])[0]


def _assert_completion_evidence(document: dict):
    operation_type = document.get("operation_type")
    if operation_type == "internal_company_delivery" and not document.get("receiver_confirmation"):
        raise ApiError("Receiver confirmation is required before verification.", status_code=400)
    if operation_type == "fuel_station_visit" and not (document.get("fuel_log_id") or document.get("no_purchase_reason")):
        raise ApiError("Fuel log or no-purchase reason is required before verification.", status_code=400)
    if operation_type == "fuel_station_visit" and document.get("fuel_log_id"):
        fuel_log = get_collection("fuel_logs").find_one(
            {"_id": document["fuel_log_id"]}, {"status": 1, "movement_id": 1}
        )
        if not fuel_log or fuel_log.get("movement_id") != document.get("linked_vehicle_movement_id"):
            raise ApiError("Linked fuel log does not belong to this movement.", status_code=409)
        if fuel_log.get("status") not in {"approved", "rejected"}:
            raise ApiError("Fuel log review must finish before operational verification.", status_code=400)
    if operation_type in {"compliance_inspection_visit", "administrative_errand"} and not document.get("task_confirmation"):
        raise ApiError("Task or inspection confirmation is required before verification.", status_code=400)
    if operation_type == "vehicle_repositioning" and not document.get("destination_acceptance"):
        raise ApiError("Destination acceptance is required before verification.", status_code=400)


def _get_linked_movement_for_verification(document: dict) -> dict:
    movement_id = _object_id(
        document.get("linked_vehicle_movement_id"),
        "linked_vehicle_movement_id",
        required=False,
    )
    if movement_id is None:
        raise ApiError(
            "Operational request does not have a linked vehicle movement.",
            status_code=409,
        )
    movement = movements_collection().find_one({"_id": movement_id})
    if movement is None:
        raise ApiError("Linked vehicle movement not found.", status_code=404)
    expected_source_key = f"vehicle_operation_request:{document['_id']}"
    if (
        movement.get("vehicle_id") != document.get("vehicle_id")
        or movement.get("source_id") not in {None, document["_id"]}
        or movement.get("source_key") not in {None, expected_source_key}
    ):
        raise ApiError(
            "Linked movement does not belong to this operational request.",
            status_code=409,
        )
    return movement


def verify_operational_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can verify completion.", status_code=403)
    document = _get_request(request_id)
    if document.get("status") == "completed":
        return _serialize_with_relations([document])[0]
    if document.get("status") != "awaiting_verification":
        raise ApiError("This request is not awaiting verification.", status_code=400)
    _assert_completion_evidence(document)
    movement = _get_linked_movement_for_verification(document)
    movement_status = movement.get("status")
    if movement_status == "returned":
        from services.vehicle_movement_service import close_vehicle_movement
        try:
            close_vehicle_movement(
                str(movement["_id"]),
                current_user_id=current_user_id,
                current_role=current_role,
            )
        except ApiError:
            # A concurrent/retried verification may have closed the physical
            # movement after this request read it. Only that terminal state is
            # safe to treat as success.
            latest_movement = movements_collection().find_one(
                {"_id": movement["_id"]},
                {"status": 1},
            )
            if not latest_movement or latest_movement.get("status") != "closed":
                raise
    elif movement_status != "closed":
        raise ApiError(
            "Linked vehicle movement must be returned before completion can be verified.",
            status_code=409,
        )
    timestamp = now_utc()
    updates = {"status": "completed", "verified_by": _object_id(current_user_id, "current_user_id"), "verified_at": timestamp, "verification_notes": _text(payload.get("notes")), "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    update_result = requests_collection().update_one(
        {"_id": document["_id"], "status": "awaiting_verification"},
        {"$set": updates},
    )
    if update_result.modified_count == 0:
        latest_request = _get_request(request_id)
        if latest_request.get("status") == "completed":
            return _serialize_with_relations([latest_request])[0]
        raise ApiError(
            "Operational request completion state changed. Refresh and try again.",
            status_code=409,
        )
    document.update(updates)
    if document.get("operation_type") == "vehicle_repositioning":
        vehicles_collection().update_one({"_id": document["vehicle_id"]}, {"$set": {"current_operational_location_id": document.get("destination_location_id"), "current_operational_location": document.get("destination"), "current_operational_location_snapshot": document.get("destination_snapshot"), "updated_at": timestamp}})
    resolve_action_notifications("vehicle_operation_request", document["_id"], resolution="completed", completed_by=current_user_id)
    return _serialize_with_relations([document])[0]


def cancel_operational_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can cancel operational requests.", status_code=403)
    document = _get_request(request_id)
    if document.get("status") == "cancelled":
        return _serialize_with_relations([document])[0]
    if document.get("status") in {"movement_in_progress", "awaiting_verification", "completed", "rejected", "aborted"}:
        raise ApiError("This request cannot be cancelled at its current stage.", status_code=400)
    reason = _text(payload.get("reason"), required=True, field="cancellation reason")
    movement_id = document.get("linked_vehicle_movement_id")
    if movement_id:
        movement = movements_collection().find_one({"_id": movement_id}, {"status": 1})
        if movement and movement.get("status") in {"draft", "pending_approval", "approved"}:
            from services.vehicle_movement_service import cancel_vehicle_movement
            cancel_vehicle_movement(str(movement_id), {"cancellation_reason": reason}, current_user_id=current_user_id, current_role=current_role)
    updates = {"status": "cancelled", "cancelled_by": _object_id(current_user_id, "current_user_id"), "cancelled_at": now_utc(), "cancellation_reason": reason, "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    requests_collection().update_one({"_id": document["_id"]}, {"$set": updates})
    document.update(updates)
    resolve_action_notifications("vehicle_operation_request", document["_id"], resolution="cancelled", completed_by=current_user_id)
    return _serialize_with_relations([document])[0]


def list_operational_request_options(*, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to view operational request options.", status_code=403)
    vehicles = list(vehicles_collection().find({"status": {"$nin": ["retired"]}}, {"registration_number": 1, "make": 1, "model": 1, "vehicle_type": 1}).sort("registration_number", ASCENDING))
    availability_by_vehicle = resolve_many([item["_id"] for item in vehicles])
    drivers = list(users_collection().find({"role": "driver", "status": "active", "driver_profile.approval_status": "approved"}, {"full_name": 1}).sort("full_name", ASCENDING))
    return {
        "operation_types": sorted(OPERATION_TYPES),
        "statuses": sorted(REQUEST_STATUSES),
        "vehicles": [{"id": str(item["_id"]), "registration_number": item.get("registration_number"), "make": item.get("make"), "model": item.get("model"), "vehicle_type": item.get("vehicle_type"), "is_available": availability_by_vehicle.get(str(item["_id"]), {}).get("is_available", False), "primary_reason": availability_by_vehicle.get(str(item["_id"]), {}).get("primary_reason")} for item in vehicles],
        "drivers": [{"id": str(item["_id"]), "full_name": item.get("full_name")} for item in drivers],
    }
