from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import ceil
from time import perf_counter
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.assignment import serialize_assignment
from models.dispatch_job import serialize_dispatch_job
from models.dispatch_request import serialize_dispatch_request
from models.resource_reservation import serialize_resource_reservation
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.dispatch_request_service import confirm_dispatch_request_stop_delivery
from services.notification_service import create_notification, notify_roles, resolve_action_notifications
from services.vehicle_availability_service import resolve_vehicle_availability
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached


PLANNER_ROLES = {"owner", "admin", "dispatcher", "customer_service"}
OWNER_ADMIN_ROLES = {"owner", "admin"}
JOB_STATUSES = {
    "draft",
    "reserved",
    "assigned",
    "accepted",
    "clarification_requested",
    "rejected",
    "cancelled",
    "in_progress",
    "completed",
}
ACTIVE_JOB_STATUSES = {"reserved", "assigned", "accepted", "clarification_requested", "in_progress"}
RESERVATION_STATUSES = {"reserved", "released", "consumed", "cancelled"}
ACTIVE_RESERVATION_STATUSES = {"reserved", "consumed"}
REQUEST_PLANNING_STATUSES = {
    "unplanned",
    "draft",
    "reserved",
    "assigned",
    "accepted",
    "clarification_requested",
    "rejected",
    "in_progress",
    "completed",
    "cancelled",
}
DRIVER_RESPONSE_STATUSES = {"pending", "accepted", "clarification_requested", "rejected"}
DRIVER_WORKFLOW_STATUSES = {
    "assigned",
    "accepted",
    "travelling_to_pickup",
    "goods_loaded",
    "in_transit",
    "delivered",
    "returning",
    "returned",
}
MAINTENANCE_BLOCKING_STATUSES = {"pending", "approved", "in_progress", "waiting_parts"}
MOVEMENT_BLOCKING_STATUSES = {"draft", "pending_approval", "approved", "checked_out", "in_progress"}
DRIVER_LIST_SECTIONS = {"upcoming", "active", "completed", "cancelled"}
LIST_REQUEST_PROJECTION = {
    "request_id": 1,
    "customer_name": 1,
    "pickup_location": 1,
    "destination": 1,
    "vehicle_type_needed": 1,
    "urgency": 1,
    "status": 1,
    "planning_status": 1,
    "scheduled_start_time": 1,
    "pricing_status": 1,
    "load_description": 1,
    "customer_phone": 1,
    "stops": 1,
    "created_at": 1,
    "updated_at": 1,
}
LIST_JOB_PROJECTION = {
    "dispatch_job_id": 1,
    "dispatch_request_id": 1,
    "status": 1,
    "driver_workflow_status": 1,
    "is_paused": 1,
    "paused_at": 1,
    "paused_reason": 1,
    "driver_response_status": 1,
    "driver_response_reason": 1,
    "driver_responded_at": 1,
    "vehicle_id": 1,
    "driver_id": 1,
    "assistant_id": 1,
    "dispatcher_id": 1,
    "primary_assignment_id": 1,
    "linked_vehicle_movement_id": 1,
    "pickup": 1,
    "destination": 1,
    "stops": 1,
    "scheduled_start_time": 1,
    "expected_arrival_time": 1,
    "expected_return_time": 1,
    "dispatch_instructions": 1,
    "goods_description": 1,
    "quantity": 1,
    "weight_category": 1,
    "loading_notes": 1,
    "customer_contact": 1,
    "receiver_contact": 1,
    "started_at": 1,
    "actual_departure_at": 1,
    "completed_at": 1,
    "created_at": 1,
    "updated_at": 1,
}
DETAIL_JOB_PROJECTION = None
USER_SUMMARY_PROJECTION = {"full_name": 1, "email": 1, "phone": 1, "role": 1, "status": 1, "driver_profile": 1}
VEHICLE_SUMMARY_PROJECTION = {"registration_number": 1, "vehicle_type": 1, "make": 1, "model": 1, "status": 1}
ASSIGNMENT_SUMMARY_PROJECTION = {
    "driver_id": 1,
    "vehicle_id": 1,
    "status": 1,
    "weekly_target": 1,
    "daily_target": 1,
    "start_date": 1,
    "end_date": 1,
    "assigned_by": 1,
    "created_at": 1,
    "updated_at": 1,
}


def now_utc():
    return datetime.now(timezone.utc)


def dispatch_requests_collection():
    return get_collection("dispatch_requests")


def dispatch_jobs_collection():
    return get_collection("dispatch_jobs")


def resource_reservations_collection():
    return get_collection("resource_reservations")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def assignments_collection():
    return get_collection("assignments")


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def notifications_collection():
    return get_collection("notifications")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def ensure_dispatch_planner_indexes():
    ensure_indexes_for_collection(
        dispatch_jobs_collection(),
        [
            {"keys": [("dispatch_job_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("dispatch_request_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("driver_response_status", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("driver_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("scheduled_start_time", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("expected_return_time", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING), ("scheduled_start_time", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING), ("scheduled_start_time", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING), ("scheduled_start_time", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("created_at", DESCENDING)]},
        ],
        collection_name="dispatch_jobs",
    )
    ensure_indexes_for_collection(
        resource_reservations_collection(),
        [
            {"keys": [("reservation_type", ASCENDING)]},
            {"keys": [("resource_id", ASCENDING)]},
            {"keys": [("dispatch_job_id", ASCENDING)]},
            {"keys": [("dispatch_request_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("start_time", ASCENDING)]},
            {"keys": [("end_time", ASCENDING)]},
            {"keys": [("reservation_type", ASCENDING), ("resource_id", ASCENDING), ("status", ASCENDING), ("start_time", ASCENDING)]},
            {"keys": [("status", ASCENDING), ("start_time", ASCENDING), ("end_time", ASCENDING)]},
        ],
        collection_name="resource_reservations",
    )
    ensure_indexes_for_collection(
        dispatch_requests_collection(),
        [
            {"keys": [("planning_status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("active_dispatch_job_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING), ("planning_status", ASCENDING), ("scheduled_start_time", ASCENDING)]},
        ],
        collection_name="dispatch_requests_planner",
    )


def _normalize_role(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _normalize_text(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_phone(value):
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return "".join(normalized.split())


def _to_object_id(value, field_name: str, *, required: bool = True) -> ObjectId | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _parse_datetime(value, field_name: str, *, required: bool = False) -> datetime | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as error:
        raise ApiError(f"{field_name} must be a valid ISO datetime.", status_code=400) from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_date(value, field_name: str, *, required: bool = False) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as error:
        raise ApiError(f"{field_name} must be a valid ISO date.", status_code=400) from error


def _parse_time(value, field_name: str, *, required: bool = False) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    candidate = normalized[:5]
    if len(candidate) != 5 or candidate[2] != ":":
        raise ApiError(f"{field_name} must be a valid HH:MM time.", status_code=400)
    return candidate


def _validate_non_negative_number(value, field_name: str):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} must be zero or greater.", status_code=400)
    return round(float(value), 2)


def _validate_status(value, field_name: str, allowed: set[str], *, required: bool = False, default: str | None = None):
    normalized = _normalize_text(value)
    if not normalized:
        if default is not None:
            return default
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    normalized = normalized.lower()
    if normalized not in allowed:
        raise ApiError(f"Invalid {field_name}.", status_code=400)
    return normalized


def _assert_planner_role(current_role: str):
    if current_role not in PLANNER_ROLES:
        raise ApiError("You do not have permission to access dispatch planning.", status_code=403)


def _assert_driver_role(current_role: str):
    if current_role != "driver":
        raise ApiError("You do not have permission to access driver dispatch assignments.", status_code=403)


def _get_dispatch_request_document(request_id: str, *, projection: dict | None = None) -> dict:
    request_object_id = _to_object_id(request_id, "dispatch_request_id")
    document = dispatch_requests_collection().find_one({"_id": request_object_id}, projection)
    if not document:
        raise ApiError("Dispatch request not found.", status_code=404)
    return document


def _get_dispatch_job_document(job_id: str, *, projection: dict | None = None) -> dict:
    job_object_id = _to_object_id(job_id, "dispatch_job_id")
    document = dispatch_jobs_collection().find_one({"_id": job_object_id}, projection)
    if not document:
        raise ApiError("Dispatch job not found.", status_code=404)
    return document


def _get_user_document(user_id: str | ObjectId, *, role: str | None = None) -> dict:
    query = {"_id": _to_object_id(user_id, "user_id")}
    if role:
        query["role"] = role
    document = users_collection().find_one(query)
    if not document:
        raise ApiError(f"{role.title() if role else 'User'} not found.", status_code=404)
    return document


def _get_vehicle_document(vehicle_id: str | ObjectId) -> dict:
    document = vehicles_collection().find_one({"_id": _to_object_id(vehicle_id, "vehicle_id")})
    if not document:
        raise ApiError("Vehicle not found.", status_code=404)
    return document


def _get_primary_assignment_for_vehicle_driver(vehicle_id: ObjectId, driver_id: ObjectId | None) -> dict | None:
    query = {"vehicle_id": vehicle_id, "status": {"$in": ["active", "suspended"]}}
    if driver_id is not None:
        query["driver_id"] = driver_id
    return assignments_collection().find_one(query)


def _build_user_lookup(documents: list[dict]) -> dict[ObjectId, dict]:
    user_ids = {
        value
        for document in documents
        for value in (
            document.get("driver_id"),
            document.get("assistant_id"),
            document.get("dispatcher_id"),
            document.get("created_by"),
            document.get("updated_by"),
        )
        if isinstance(value, ObjectId)
    }
    if not user_ids:
        return {}
    return {
        item["_id"]: item
        for item in users_collection().find({"_id": {"$in": list(user_ids)}}, USER_SUMMARY_PROJECTION)
    }


def _build_vehicle_lookup(documents: list[dict]) -> dict[ObjectId, dict]:
    vehicle_ids = {document.get("vehicle_id") for document in documents if isinstance(document.get("vehicle_id"), ObjectId)}
    if not vehicle_ids:
        return {}
    return {
        item["_id"]: item
        for item in vehicles_collection().find({"_id": {"$in": list(vehicle_ids)}}, VEHICLE_SUMMARY_PROJECTION)
    }


def _build_assignment_lookup(documents: list[dict]) -> dict[ObjectId, dict]:
    assignment_ids = {document.get("primary_assignment_id") for document in documents if isinstance(document.get("primary_assignment_id"), ObjectId)}
    if not assignment_ids:
        return {}
    return {
        item["_id"]: item
        for item in assignments_collection().find({"_id": {"$in": list(assignment_ids)}}, ASSIGNMENT_SUMMARY_PROJECTION)
    }


def _enrich_dispatch_job(document: dict, *, user_lookup: dict | None = None, vehicle_lookup: dict | None = None, assignment_lookup: dict | None = None) -> dict:
    payload = serialize_dispatch_job(document)
    users = user_lookup or {}
    vehicles = vehicle_lookup or {}
    assignments = assignment_lookup or {}
    payload["driver"] = serialize_user(users[document["driver_id"]]) if users.get(document.get("driver_id")) else None
    payload["assistant"] = serialize_user(users[document["assistant_id"]]) if users.get(document.get("assistant_id")) else None
    payload["dispatcher"] = serialize_user(users[document["dispatcher_id"]]) if users.get(document.get("dispatcher_id")) else None
    payload["created_by_user"] = serialize_user(users[document["created_by"]]) if users.get(document.get("created_by")) else None
    payload["updated_by_user"] = serialize_user(users[document["updated_by"]]) if users.get(document.get("updated_by")) else None
    payload["vehicle"] = serialize_vehicle(vehicles[document["vehicle_id"]]) if vehicles.get(document.get("vehicle_id")) else None
    payload["primary_assignment"] = serialize_assignment(assignments[document["primary_assignment_id"]]) if assignments.get(document.get("primary_assignment_id")) else None
    return payload


def _batch_enrich_dispatch_jobs(documents: list[dict]) -> list[dict]:
    if not documents:
        return []
    user_lookup = _build_user_lookup(documents)
    vehicle_lookup = _build_vehicle_lookup(documents)
    assignment_lookup = _build_assignment_lookup(documents)
    return [
        _enrich_dispatch_job(
            document,
            user_lookup=user_lookup,
            vehicle_lookup=vehicle_lookup,
            assignment_lookup=assignment_lookup,
        )
        for document in documents
    ]


def _serialize_request_list_item(document: dict) -> dict:
    payload = serialize_dispatch_request(document)
    payload["stops_count"] = len(document.get("stops") or [])
    return payload


def _generate_dispatch_job_id() -> str:
    timestamp = now_utc().strftime("%Y%m%d%H%M%S")
    return f"DJ-{timestamp}-{uuid4().hex[:6].upper()}"


def _normalize_stop(stop: dict) -> dict:
    return {
        "stop_id": stop.get("stop_id") or uuid4().hex,
        "stop_sequence": stop.get("stop_sequence"),
        "stop_type": stop.get("stop_type"),
        "location": stop.get("location"),
        "contact_name": _normalize_text(stop.get("contact_name")),
        "contact_phone": _normalize_phone(stop.get("contact_phone")),
        "load_note": _normalize_text(stop.get("load_note")),
        "planned_arrival_time": _parse_datetime(stop.get("planned_arrival_time"), "planned_arrival_time", required=False),
        "planned_departure_time": _parse_datetime(stop.get("planned_departure_time"), "planned_departure_time", required=False),
        "stop_charge": _validate_non_negative_number(stop.get("stop_charge"), "stop_charge"),
        "stop_status": _validate_status(stop.get("stop_status"), "stop_status", {"pending", "ready", "completed", "skipped", "cancelled"}, default="pending"),
        "delivery_status": stop.get("delivery_status") or "pending",
        "delivered_at": stop.get("delivered_at"),
        "delivery_note": stop.get("delivery_note"),
        "delivered_by": stop.get("delivered_by"),
        "completed_at": stop.get("completed_at"),
        "completed_by": stop.get("completed_by"),
        "completion_note": stop.get("completion_note"),
    }


def _serialize_timeline_actor(actor_id: str | ObjectId | None) -> ObjectId | None:
    if actor_id is None:
        return None
    if isinstance(actor_id, ObjectId):
        return actor_id
    return _to_object_id(actor_id, "actor_id")


def _build_timeline_entry(*, title: str, status: str, event_type: str, actor_id: str | ObjectId | None, note: str | None = None, timestamp: datetime | None = None) -> dict:
    return {
        "event_id": uuid4().hex,
        "event_type": event_type,
        "title": title,
        "status": status,
        "note": note,
        "updated_by": _serialize_timeline_actor(actor_id),
        "timestamp": timestamp or now_utc(),
    }


def _append_timeline_entry(job_document: dict, *, title: str, status: str, event_type: str, actor_id: str | ObjectId | None, note: str | None = None, timestamp: datetime | None = None) -> list[dict]:
    timeline = list(job_document.get("timeline") or [])
    timeline.append(
        _build_timeline_entry(
            title=title,
            status=status,
            event_type=event_type,
            actor_id=actor_id,
            note=note,
            timestamp=timestamp,
        )
    )
    return timeline


def _get_driver_workflow_status(job_document: dict) -> str:
    workflow_status = _normalize_text(job_document.get("driver_workflow_status"))
    if workflow_status in DRIVER_WORKFLOW_STATUSES:
        return workflow_status
    status = job_document.get("status")
    if status == "completed":
        return "returned"
    if status == "in_progress":
        return "in_transit"
    if status == "accepted":
        return "accepted"
    return "assigned"


def _create_job_notification_once(*, recipient_user_id: ObjectId | None, title: str, message: str, category: str, priority: str, job_document: dict, action_type: str | None = None, action_url: str | None = None, action_label: str | None = None, due_at=None):
    if not isinstance(recipient_user_id, ObjectId):
        return
    if notifications_collection().find_one(
        {
            "recipient_user_id": recipient_user_id,
            "category": category,
            "reference_type": "dispatch_job",
            "reference_id": job_document["_id"],
        },
        {"_id": 1},
    ):
        return
    create_notification(
        recipient_user_id=recipient_user_id,
        title=title,
        message=message,
        category=category,
        priority=priority,
        reference_type="dispatch_job",
        reference_id=job_document["_id"],
        action_type=action_type,
        action_url=action_url,
        action_label=action_label,
        due_at=due_at,
    )


def _sync_upcoming_dispatch_reminders(documents: list[dict]):
    reminder_cutoff = now_utc()
    reminder_window_end = reminder_cutoff + timedelta(hours=6)
    for document in documents:
        if document.get("status") not in {"assigned", "accepted"}:
            continue
        scheduled_start = document.get("scheduled_start_time")
        if not isinstance(scheduled_start, datetime):
            continue
        if scheduled_start.tzinfo is None:
            scheduled_start = scheduled_start.replace(tzinfo=timezone.utc)
        if scheduled_start < reminder_cutoff or scheduled_start > reminder_window_end:
            continue
        _create_job_notification_once(
            recipient_user_id=document.get("driver_id"),
            title="Upcoming dispatch reminder",
            message=f"Dispatch {document.get('dispatch_job_id')} starts at {scheduled_start.astimezone(timezone.utc).strftime('%H:%M UTC')}.",
            category="dispatch_reminder",
            priority="medium",
            job_document=document,
        )


def _normalize_planning_payload(payload: dict, *, partial: bool = False) -> dict:
    normalized: dict = {}
    object_fields = ("vehicle_id", "driver_id", "assistant_id", "dispatcher_id")
    for field_name in object_fields:
        if field_name in payload or not partial:
            normalized[field_name] = _to_object_id(payload.get(field_name), field_name, required=False)

    if "pickup" in payload or not partial:
        normalized["pickup"] = _normalize_text(payload.get("pickup"))
    if "destination" in payload or not partial:
        normalized["destination"] = _normalize_text(payload.get("destination"))
    if "dispatch_date" in payload or not partial:
        normalized["dispatch_date"] = _parse_date(payload.get("dispatch_date"), "dispatch_date", required=not partial)
    if "dispatch_time" in payload or not partial:
        normalized["dispatch_time"] = _parse_time(payload.get("dispatch_time"), "dispatch_time", required=not partial)
    if "scheduled_start_time" in payload or not partial:
        normalized["scheduled_start_time"] = _parse_datetime(payload.get("scheduled_start_time"), "scheduled_start_time", required=False)
    if "expected_arrival_time" in payload or not partial:
        normalized["expected_arrival_time"] = _parse_datetime(payload.get("expected_arrival_time"), "expected_arrival_time", required=False)
    if "expected_return_time" in payload or not partial:
        normalized["expected_return_time"] = _parse_datetime(payload.get("expected_return_time"), "expected_return_time", required=False)
    if "distance_estimate_km" in payload or not partial:
        normalized["distance_estimate_km"] = _validate_non_negative_number(payload.get("distance_estimate_km"), "distance_estimate_km")
    if "quantity" in payload or not partial:
        normalized["quantity"] = _normalize_text(payload.get("quantity"))
    if "weight_category" in payload or not partial:
        normalized["weight_category"] = _normalize_text(payload.get("weight_category"))
    boolean_fields = ("fragile", "refrigerated", "hazardous")
    for field_name in boolean_fields:
        if field_name in payload or not partial:
            normalized[field_name] = bool(payload.get(field_name)) if payload.get(field_name) is not None else False
    text_fields = (
        "goods_description",
        "loading_notes",
        "customer_contact",
        "receiver_contact",
        "dispatch_instructions",
        "internal_notes",
    )
    for field_name in text_fields:
        if field_name in payload or not partial:
            normalized[field_name] = _normalize_text(payload.get(field_name))
    if "stops" in payload or not partial:
        raw_stops = payload.get("stops") or []
        if not isinstance(raw_stops, list):
            raise ApiError("stops must be a list.", status_code=400)
        normalized["stops"] = [_normalize_stop(stop or {}) for stop in raw_stops]
    return normalized


def _build_scheduled_start(planning_payload: dict) -> datetime:
    explicit = planning_payload.get("scheduled_start_time")
    if explicit:
        return explicit
    dispatch_date = planning_payload.get("dispatch_date")
    dispatch_time = planning_payload.get("dispatch_time")
    if not dispatch_date or not dispatch_time:
        raise ApiError("dispatch_date and dispatch_time are required.", status_code=400)
    return _parse_datetime(f"{dispatch_date}T{dispatch_time}:00", "scheduled_start_time", required=True)


def _validate_planning_payload(request_document: dict, planning_payload: dict):
    if not planning_payload.get("pickup"):
        raise ApiError("pickup is required.", status_code=400)
    if not planning_payload.get("destination"):
        raise ApiError("destination is required.", status_code=400)
    if not planning_payload.get("dispatcher_id"):
        raise ApiError("dispatcher_id is required.", status_code=400)
    scheduled_start_time = _build_scheduled_start(planning_payload)
    planning_payload["scheduled_start_time"] = scheduled_start_time
    if planning_payload.get("expected_arrival_time") and planning_payload["expected_arrival_time"] <= scheduled_start_time:
        raise ApiError("expected_arrival_time must be after scheduled_start_time.", status_code=400)
    if planning_payload.get("expected_return_time") and planning_payload["expected_return_time"] <= scheduled_start_time:
        raise ApiError("expected_return_time must be after scheduled_start_time.", status_code=400)
    if request_document.get("status") != "approved":
        raise ApiError("Only approved dispatch requests can be planned.", status_code=400)
    stop_sequences = [stop.get("stop_sequence") for stop in (planning_payload.get("stops") or []) if stop.get("stop_sequence") is not None]
    if len(stop_sequences) != len(set(stop_sequences)):
        raise ApiError("Stop sequence values must be unique.", status_code=400)


def _build_overlap_query(start_time: datetime, end_time: datetime) -> dict:
    return {
        "start_time": {"$lt": end_time},
        "end_time": {"$gt": start_time},
    }


def _build_job_overlap_query(start_time: datetime, end_time: datetime) -> dict:
    return {
        "scheduled_start_time": {"$lt": end_time},
        "expected_return_time": {"$gt": start_time},
    }


def _vehicle_conflicts(*, vehicle_id: ObjectId, start_time: datetime, end_time: datetime, exclude_job_id: ObjectId | None = None) -> list[str]:
    conflicts: list[str] = []
    availability = resolve_vehicle_availability(vehicle_id)
    conflicts.extend(
        reason["message"] for reason in availability.get("blocking_reasons", [])
        if reason.get("code") not in {"active_reservation", "active_dispatch"}
    )
    reservation_query = {
        "reservation_type": "vehicle",
        "resource_id": vehicle_id,
        "status": {"$in": sorted(ACTIVE_RESERVATION_STATUSES)},
        **_build_overlap_query(start_time, end_time),
    }
    if exclude_job_id:
        reservation_query["dispatch_job_id"] = {"$ne": exclude_job_id}
    if resource_reservations_collection().find_one(reservation_query, {"_id": 1}):
        conflicts.append("Vehicle is already reserved for another dispatch in the selected time window.")

    movement_query = {
        "vehicle_id": vehicle_id,
        "status": {"$in": sorted(MOVEMENT_BLOCKING_STATUSES)},
    }
    if vehicle_movements_collection().find_one(movement_query, {"_id": 1, "movement_type": 1}) and not any("active vehicle movement" in item.lower() for item in conflicts):
        conflicts.append("Vehicle already has an active movement and is not available for dispatch planning.")

    maintenance_query = {
        "vehicle_id": vehicle_id,
        "status": {"$in": sorted(MAINTENANCE_BLOCKING_STATUSES)},
    }
    maintenance_job = maintenance_jobs_collection().find_one(maintenance_query, {"status": 1})
    if maintenance_job and not any("active maintenance job" in item.lower() for item in conflicts):
        conflicts.append("Vehicle is under maintenance or workshop handling and cannot be assigned.")

    vehicle = vehicles_collection().find_one({"_id": vehicle_id}, {"status": 1})
    if not vehicle:
        conflicts.append("Vehicle not found.")
    elif (vehicle.get("status") or "").strip().lower() not in {"available"} and not conflicts:
        conflicts.append(f"Vehicle is currently marked as {vehicle.get('status') or 'unavailable'}.")
    return conflicts


def _driver_conflicts(*, driver_id: ObjectId, start_time: datetime, end_time: datetime, exclude_job_id: ObjectId | None = None) -> list[str]:
    conflicts: list[str] = []
    reservation_query = {
        "reservation_type": "driver",
        "resource_id": driver_id,
        "status": {"$in": sorted(ACTIVE_RESERVATION_STATUSES)},
        **_build_overlap_query(start_time, end_time),
    }
    if exclude_job_id:
        reservation_query["dispatch_job_id"] = {"$ne": exclude_job_id}
    if resource_reservations_collection().find_one(reservation_query, {"_id": 1}):
        conflicts.append("Driver is already reserved for another dispatch in the selected time window.")

    movement_query = {
        "driver_id": driver_id,
        "status": {"$in": sorted(MOVEMENT_BLOCKING_STATUSES)},
    }
    if vehicle_movements_collection().find_one(movement_query, {"_id": 1}):
        conflicts.append("Driver is already on another vehicle movement and is not available.")

    job_query = {
        "driver_id": driver_id,
        "status": {"$in": sorted(ACTIVE_JOB_STATUSES)},
        **_build_job_overlap_query(start_time, end_time),
    }
    if exclude_job_id:
        job_query["_id"] = {"$ne": exclude_job_id}
    if dispatch_jobs_collection().find_one(job_query, {"_id": 1}):
        conflicts.append("Driver already has another active dispatch assignment in the selected time window.")

    driver = users_collection().find_one({"_id": driver_id}, {"status": 1, "driver_profile.approval_status": 1})
    if not driver:
        conflicts.append("Driver not found.")
    else:
        status = (driver.get("status") or "").strip().lower()
        approval_status = (((driver.get("driver_profile") or {}).get("approval_status")) or "").strip().lower()
        if status == "suspended":
            conflicts.append("Driver is suspended and cannot be assigned.")
        elif status != "active":
            conflicts.append("Driver is currently unavailable.")
        if approval_status and approval_status != "approved":
            conflicts.append("Driver is not approved for dispatch assignment.")
    return conflicts


def detect_dispatch_conflicts(
    *,
    vehicle_id: str | None,
    driver_id: str | None,
    scheduled_start_time,
    expected_return_time,
    exclude_job_id: str | None = None,
) -> dict:
    start_time = _parse_datetime(scheduled_start_time, "scheduled_start_time", required=True)
    end_time = _parse_datetime(expected_return_time, "expected_return_time", required=True)
    if end_time <= start_time:
        raise ApiError("expected_return_time must be after scheduled_start_time.", status_code=400)
    exclude_job_object_id = _to_object_id(exclude_job_id, "exclude_job_id", required=False) if exclude_job_id else None

    vehicle_conflicts = []
    driver_conflicts = []
    if vehicle_id:
        vehicle_conflicts = _vehicle_conflicts(
            vehicle_id=_to_object_id(vehicle_id, "vehicle_id"),
            start_time=start_time,
            end_time=end_time,
            exclude_job_id=exclude_job_object_id,
        )
    if driver_id:
        driver_conflicts = _driver_conflicts(
            driver_id=_to_object_id(driver_id, "driver_id"),
            start_time=start_time,
            end_time=end_time,
            exclude_job_id=exclude_job_object_id,
        )
    return {
        "has_conflicts": bool(vehicle_conflicts or driver_conflicts),
        "vehicle_conflicts": vehicle_conflicts,
        "driver_conflicts": driver_conflicts,
    }


def list_planner_requests(
    *,
    current_role: str,
    page: int = 1,
    page_size: int = 20,
    search_query: str | None = None,
    planning_status: str | None = None,
    urgency: str | None = None,
) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    query = {"status": "approved"}
    if planning_status:
        query["planning_status"] = planning_status
    else:
        query["planning_status"] = {"$in": [None, "unplanned", "draft", "rejected", "clarification_requested"]}
    if urgency:
        query["urgency"] = urgency
    if search_query:
        escaped = search_query.strip()
        query["$or"] = [
            {"request_id": {"$regex": escaped, "$options": "i"}},
            {"customer_name": {"$regex": escaped, "$options": "i"}},
            {"pickup_location": {"$regex": escaped, "$options": "i"}},
            {"destination": {"$regex": escaped, "$options": "i"}},
        ]
    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 20, 1), 100)
    skip = (normalized_page - 1) * normalized_page_size
    started_at = perf_counter()
    aggregate = list(
        dispatch_requests_collection().aggregate(
            [
                {"$match": query},
                {
                    "$facet": {
                        "records": [
                            {"$sort": {"scheduled_start_time": 1, "updated_at": -1, "_id": -1}},
                            {"$skip": skip},
                            {"$limit": normalized_page_size},
                            {"$project": LIST_REQUEST_PROJECTION},
                        ],
                        "counts": [{"$count": "total"}],
                    }
                },
            ]
        )
    )
    log_db_duration("dispatch_planner.requests.aggregate", started_at)
    payload = aggregate[0] if aggregate else {}
    records = payload.get("records") or []
    total = int(((payload.get("counts") or [{}])[0]).get("total") or 0)
    return {
        "requests": [_serialize_request_list_item(record) for record in records],
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
    }


def list_dispatch_jobs(*, current_role: str, page: int = 1, page_size: int = 20, status: str | None = None) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    query = {}
    if status:
        query["status"] = _validate_status(status, "status", JOB_STATUSES, required=True)
    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 20, 1), 100)
    skip = (normalized_page - 1) * normalized_page_size
    aggregate = list(
        dispatch_jobs_collection().aggregate(
            [
                {"$match": query},
                {
                    "$facet": {
                        "records": [
                            {"$sort": {"scheduled_start_time": 1, "updated_at": -1, "_id": -1}},
                            {"$skip": skip},
                            {"$limit": normalized_page_size},
                            {"$project": LIST_JOB_PROJECTION},
                        ],
                        "counts": [{"$count": "total"}],
                    }
                },
            ]
        )
    )
    payload = aggregate[0] if aggregate else {}
    records = payload.get("records") or []
    total = int(((payload.get("counts") or [{}])[0]).get("total") or 0)
    return {
        "jobs": _batch_enrich_dispatch_jobs(records),
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
    }


def get_dispatch_job(job_id: str, *, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    return _batch_enrich_dispatch_jobs([_get_dispatch_job_document(job_id, projection=DETAIL_JOB_PROJECTION)])[0]


def list_planner_options(*, current_role: str, current_user_id: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    cache_key = build_cache_key("dispatch_planner.options", role=normalized_role, user_id=current_user_id)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    started_at = perf_counter()
    vehicles = list(
        vehicles_collection().find(
            {"status": "available"},
            {"registration_number": 1, "vehicle_type": 1, "make": 1, "model": 1, "status": 1},
        ).sort("registration_number", ASCENDING)
    )
    drivers = list(
        users_collection().find(
            {"role": "driver", "status": "active", "driver_profile.approval_status": "approved"},
            USER_SUMMARY_PROJECTION,
        ).sort("full_name", ASCENDING)
    )
    dispatchers = list(
        users_collection().find(
            {"role": {"$in": ["owner", "admin", "dispatcher", "customer_service"]}, "status": "active"},
            USER_SUMMARY_PROJECTION,
        ).sort("full_name", ASCENDING)
    )
    assistants = list(
        users_collection().find(
            {"role": "driver", "status": "active"},
            USER_SUMMARY_PROJECTION,
        ).sort("full_name", ASCENDING)
    )
    log_db_duration("dispatch_planner.options.lookup", started_at)
    payload = {
        "vehicles": [serialize_vehicle(item) for item in vehicles],
        "drivers": [serialize_user(item) for item in drivers],
        "assistants": [serialize_user(item) for item in assistants],
        "dispatchers": [serialize_user(item) for item in dispatchers],
        "job_statuses": sorted(JOB_STATUSES),
        "planning_statuses": sorted(REQUEST_PLANNING_STATUSES),
        "driver_response_statuses": sorted(DRIVER_RESPONSE_STATUSES),
    }
    return set_ttl_cached(cache_key, payload, ttl_seconds=20)


def get_fleet_availability(*, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    started_at = perf_counter()
    now_value = now_utc()

    active_vehicle_reservations = resource_reservations_collection().count_documents(
        {
            "reservation_type": "vehicle",
            "status": {"$in": sorted(ACTIVE_RESERVATION_STATUSES)},
            "end_time": {"$gte": now_value},
        }
    )
    active_driver_reservations = resource_reservations_collection().count_documents(
        {
            "reservation_type": "driver",
            "status": {"$in": sorted(ACTIVE_RESERVATION_STATUSES)},
            "end_time": {"$gte": now_value},
        }
    )
    active_dispatches = dispatch_jobs_collection().count_documents({"status": {"$in": ["assigned", "accepted", "clarification_requested", "in_progress"]}})
    scheduled_today = dispatch_jobs_collection().count_documents(
        {
            "scheduled_start_time": {
                "$gte": datetime.combine(now_value.date(), datetime.min.time(), tzinfo=timezone.utc),
                "$lte": datetime.combine(now_value.date(), datetime.max.time(), tzinfo=timezone.utc),
            }
        }
    )
    overdue_dispatches = dispatch_jobs_collection().count_documents(
        {
            "status": {"$in": ["assigned", "accepted", "clarification_requested", "in_progress"]},
            "expected_return_time": {"$lt": now_value},
        }
    )
    pending_requests = dispatch_requests_collection().count_documents({"status": "approved", "planning_status": {"$in": [None, "unplanned", "draft", "rejected", "clarification_requested"]}})
    waiting_assignment = dispatch_jobs_collection().count_documents({"status": {"$in": ["draft", "reserved"]}})

    vehicle_movements = list(
        vehicle_movements_collection().aggregate(
            [
                {"$match": {"status": {"$in": sorted(MOVEMENT_BLOCKING_STATUSES)}}},
                {"$group": {"_id": "$movement_type", "count": {"$sum": 1}}},
            ]
        )
    )
    movement_counts = {item["_id"]: item["count"] for item in vehicle_movements}
    maintenance_count = maintenance_jobs_collection().count_documents({"status": {"$in": sorted(MAINTENANCE_BLOCKING_STATUSES)}})

    available_vehicle_count = vehicles_collection().count_documents({"status": "available"})
    driver_status_counts = list(
        users_collection().aggregate(
            [
                {"$match": {"role": "driver"}},
                {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            ]
        )
    )
    driver_counts = {item["_id"]: item["count"] for item in driver_status_counts}
    on_dispatch_drivers = dispatch_jobs_collection().count_documents({"status": {"$in": ["assigned", "accepted", "clarification_requested", "in_progress"]}})

    duration_started = perf_counter()
    payload = {
        "vehicles": {
            "available": available_vehicle_count,
            "reserved": active_vehicle_reservations,
            "on_dispatch": movement_counts.get("customer_dispatch", 0),
            "under_maintenance": maintenance_count,
            "workshop": movement_counts.get("workshop", 0),
            "personal_use": movement_counts.get("personal_use", 0),
            "fuel_purchase": movement_counts.get("fuel_purchase", 0),
            "internal_movement": movement_counts.get("internal_company_movement", 0),
        },
        "drivers": {
            "available": max(0, driver_counts.get("active", 0) - active_driver_reservations - on_dispatch_drivers),
            "reserved": active_driver_reservations,
            "on_dispatch": on_dispatch_drivers,
            "off_duty": 0,
            "leave": 0,
            "suspended": driver_counts.get("suspended", 0),
        },
        "dispatch": {
            "pending_requests": pending_requests,
            "waiting_assignment": waiting_assignment,
            "scheduled_today": scheduled_today,
            "active_dispatches": active_dispatches,
            "overdue_dispatches": overdue_dispatches,
        },
        "generated_at": now_value.isoformat(),
        "duration_ms": round((perf_counter() - duration_started) * 1000, 2),
    }
    log_db_duration("dispatch_planner.availability.summary", started_at)
    return payload


def _set_request_planning_state(request_document: dict, *, planning_status: str, active_dispatch_job_id: ObjectId | None):
    dispatch_requests_collection().update_one(
        {"_id": request_document["_id"]},
        {"$set": {"planning_status": planning_status, "active_dispatch_job_id": active_dispatch_job_id, "updated_at": now_utc()}},
    )


def _release_reservations(job_document: dict, *, reason: str):
    reservation_ids = [job_document.get("vehicle_reservation_id"), job_document.get("driver_reservation_id")]
    reservation_ids = [item for item in reservation_ids if isinstance(item, ObjectId)]
    if not reservation_ids:
        return {
            "reservation_ids": [],
            "released_count": 0,
            "reason": reason,
        }
    result = resource_reservations_collection().update_many(
        {"_id": {"$in": reservation_ids}, "status": {"$in": sorted(ACTIVE_RESERVATION_STATUSES)}},
        {"$set": {"status": "released", "release_reason": reason, "released_at": now_utc(), "updated_at": now_utc()}},
    )
    return {
        "reservation_ids": [str(item) for item in reservation_ids],
        "released_count": result.modified_count,
        "reason": reason,
    }


def _consume_reservations(job_document: dict):
    reservation_ids = [job_document.get("vehicle_reservation_id"), job_document.get("driver_reservation_id")]
    reservation_ids = [item for item in reservation_ids if isinstance(item, ObjectId)]
    if not reservation_ids:
        return
    resource_reservations_collection().update_many(
        {"_id": {"$in": reservation_ids}, "status": "reserved"},
        {"$set": {"status": "consumed", "updated_at": now_utc()}},
    )


def _ensure_linked_vehicle_movement(job_document: dict, *, current_user_id: str) -> ObjectId:
    linked_movement_id = job_document.get("linked_vehicle_movement_id")
    timestamp = now_utc()
    if isinstance(linked_movement_id, ObjectId):
        movement_document = vehicle_movements_collection().find_one({"_id": linked_movement_id})
        if movement_document:
            update_fields = {
                "dispatch_job_id": job_document["_id"],
                "dispatch_request_id": job_document.get("dispatch_request_id"),
                "reservation_id": job_document.get("vehicle_reservation_id"),
                "driver_id": job_document.get("driver_id"),
                "assignment_id": job_document.get("primary_assignment_id"),
                "primary_assignment_id": job_document.get("primary_assignment_id"),
                "requested_departure_time": job_document.get("scheduled_start_time"),
                "actual_departure_at": movement_document.get("actual_departure_at") or job_document.get("actual_departure_at") or job_document.get("started_at") or timestamp,
                "departure_time": movement_document.get("actual_departure_at") or movement_document.get("departure_time") or job_document.get("actual_departure_at") or job_document.get("started_at") or timestamp,
                "expected_return_time": job_document.get("expected_return_time"),
                "origin": job_document.get("pickup"),
                "destination": job_document.get("destination"),
                "purpose": job_document.get("dispatch_job_id"),
                "notes": job_document.get("dispatch_instructions"),
                "status": "in_progress",
                "checked_out_by": movement_document.get("checked_out_by") or _to_object_id(current_user_id, "current_user_id"),
                "checked_out_at": movement_document.get("checked_out_at") or timestamp,
                "updated_at": timestamp,
            }
            vehicle_movements_collection().update_one({"_id": movement_document["_id"]}, {"$set": update_fields})
            return movement_document["_id"]

    existing_movement = vehicle_movements_collection().find_one({"dispatch_job_id": job_document["_id"]})
    if existing_movement:
        update_fields = {
            "dispatch_job_id": job_document["_id"],
            "dispatch_request_id": job_document.get("dispatch_request_id"),
            "reservation_id": job_document.get("vehicle_reservation_id"),
            "driver_id": job_document.get("driver_id"),
            "assignment_id": job_document.get("primary_assignment_id"),
            "primary_assignment_id": job_document.get("primary_assignment_id"),
            "requested_departure_time": job_document.get("scheduled_start_time"),
            "actual_departure_at": existing_movement.get("actual_departure_at") or job_document.get("actual_departure_at") or job_document.get("started_at") or timestamp,
            "departure_time": existing_movement.get("actual_departure_at") or existing_movement.get("departure_time") or job_document.get("actual_departure_at") or job_document.get("started_at") or timestamp,
            "expected_return_time": job_document.get("expected_return_time"),
            "origin": job_document.get("pickup"),
            "destination": job_document.get("destination"),
            "purpose": job_document.get("dispatch_job_id"),
            "notes": job_document.get("dispatch_instructions"),
            "status": "in_progress",
            "checked_out_by": existing_movement.get("checked_out_by") or _to_object_id(current_user_id, "current_user_id"),
            "checked_out_at": existing_movement.get("checked_out_at") or timestamp,
            "updated_at": timestamp,
        }
        vehicle_movements_collection().update_one({"_id": existing_movement["_id"]}, {"$set": update_fields})
        dispatch_jobs_collection().update_one(
            {"_id": job_document["_id"]},
            {"$set": {"linked_vehicle_movement_id": existing_movement["_id"], "updated_at": timestamp}},
        )
        return existing_movement["_id"]

    movement_document = {
        "movement_id": f"VM-{timestamp.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6].upper()}",
        "vehicle_id": job_document.get("vehicle_id"),
        "driver_id": job_document.get("driver_id"),
        "assignment_id": job_document.get("primary_assignment_id"),
        "primary_assignment_id": job_document.get("primary_assignment_id"),
        "dispatch_job_id": job_document["_id"],
        "dispatch_request_id": job_document.get("dispatch_request_id"),
        "reservation_id": job_document.get("vehicle_reservation_id"),
        "movement_type": "customer_dispatch",
        "status": "in_progress",
        "requested_departure_time": job_document.get("scheduled_start_time"),
        "actual_departure_at": job_document.get("actual_departure_at") or job_document.get("started_at") or timestamp,
        "departure_time": job_document.get("actual_departure_at") or job_document.get("started_at") or timestamp,
        "expected_return_time": job_document.get("expected_return_time"),
        "actual_return_at": None,
        "actual_return_time": None,
        "origin": job_document.get("pickup"),
        "destination": job_document.get("destination"),
        "purpose": job_document.get("dispatch_job_id"),
        "opening_odometer": None,
        "closing_odometer": None,
        "opening_fuel_level": None,
        "closing_fuel_level": None,
        "delivery_status": "pending",
        "delivered_at": None,
        "delivery_note": None,
        "delivered_by": None,
        "notes": job_document.get("dispatch_instructions"),
        "cancellation_reason": None,
        "approved_by": None,
        "approved_at": None,
        "checked_out_by": _to_object_id(current_user_id, "current_user_id"),
        "checked_out_at": timestamp,
        "returned_by": None,
        "returned_at": None,
        "closed_by": None,
        "closed_at": None,
        "return_checklist": None,
        "created_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    movement_id = vehicle_movements_collection().insert_one(movement_document).inserted_id
    dispatch_jobs_collection().update_one(
        {"_id": job_document["_id"]},
        {"$set": {"linked_vehicle_movement_id": movement_id, "updated_at": timestamp}},
    )
    return movement_id


def _create_reservation(*, reservation_type: str, resource_id: ObjectId, dispatch_job_id: ObjectId, dispatch_request_id: ObjectId, start_time: datetime, end_time: datetime, current_user_id: str) -> ObjectId:
    timestamp = now_utc()
    document = {
        "reservation_type": reservation_type,
        "resource_id": resource_id,
        "dispatch_job_id": dispatch_job_id,
        "dispatch_request_id": dispatch_request_id,
        "start_time": start_time,
        "end_time": end_time,
        "status": "reserved",
        "created_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "released_at": None,
        "release_reason": None,
    }
    return resource_reservations_collection().insert_one(document).inserted_id


def _build_job_document(*, request_document: dict, planning_payload: dict, current_user_id: str, status: str, existing_job: dict | None = None) -> dict:
    scheduled_start_time = planning_payload["scheduled_start_time"]
    vehicle_id = planning_payload.get("vehicle_id")
    driver_id = planning_payload.get("driver_id")
    primary_assignment = None
    if vehicle_id:
        primary_assignment = _get_primary_assignment_for_vehicle_driver(vehicle_id, driver_id)
    base_document = existing_job or {}
    created_at = base_document.get("created_at") or now_utc()
    base_timeline = list(base_document.get("timeline") or [])
    if not base_timeline:
        base_timeline = [
            _build_timeline_entry(
                title="Assignment created",
                status="draft",
                event_type="assignment_created",
                actor_id=current_user_id,
                timestamp=created_at,
            )
        ]
    return {
        "dispatch_job_id": base_document.get("dispatch_job_id") or _generate_dispatch_job_id(),
        "dispatch_request_id": request_document["_id"],
        "dispatch_financial_type": request_document.get("dispatch_financial_type"),
        "partner_organization_reference": request_document.get("partner_organization_reference"),
        "partner_billing_method": request_document.get("partner_billing_method"),
        "approved_charge": request_document.get("approved_charge"),
        "proposed_charge": request_document.get("proposed_charge"),
        "payment_status": request_document.get("payment_status"),
        "payment_method": request_document.get("payment_method"),
        "amount_paid": request_document.get("amount_paid", 0),
        "outstanding_balance": request_document.get("outstanding_balance", 0),
        "driver_compensation_type": request_document.get("driver_compensation_type") or "none",
        "driver_compensation_value": request_document.get("driver_compensation_value", 0),
        "driver_compensation_amount": request_document.get("driver_compensation_amount", 0),
        "financial_type_changed_by": request_document.get("financial_type_changed_by"),
        "financial_type_changed_at": request_document.get("financial_type_changed_at"),
        "driver_compensation_approved_by": request_document.get("driver_compensation_approved_by"),
        "driver_compensation_approved_at": request_document.get("driver_compensation_approved_at"),
        "status": status,
        "driver_workflow_status": base_document.get("driver_workflow_status") or "assigned",
        "is_paused": bool(base_document.get("is_paused")),
        "paused_at": base_document.get("paused_at"),
        "paused_reason": base_document.get("paused_reason"),
        "driver_response_status": base_document.get("driver_response_status") or "pending",
        "driver_response_reason": base_document.get("driver_response_reason"),
        "driver_responded_at": base_document.get("driver_responded_at"),
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "assistant_id": planning_payload.get("assistant_id"),
        "dispatcher_id": planning_payload.get("dispatcher_id"),
        "primary_assignment_id": primary_assignment["_id"] if primary_assignment else None,
        "vehicle_reservation_id": base_document.get("vehicle_reservation_id"),
        "driver_reservation_id": base_document.get("driver_reservation_id"),
        "linked_vehicle_movement_id": base_document.get("linked_vehicle_movement_id"),
        "pickup": planning_payload.get("pickup"),
        "destination": planning_payload.get("destination"),
        "stops": planning_payload.get("stops") or [],
        "dispatch_date": planning_payload.get("dispatch_date"),
        "dispatch_time": planning_payload.get("dispatch_time"),
        "scheduled_start_time": scheduled_start_time,
        "expected_arrival_time": planning_payload.get("expected_arrival_time"),
        "expected_return_time": planning_payload.get("expected_return_time"),
        "distance_estimate_km": planning_payload.get("distance_estimate_km"),
        "goods_description": planning_payload.get("goods_description") or request_document.get("load_description"),
        "quantity": planning_payload.get("quantity"),
        "weight_category": planning_payload.get("weight_category") or request_document.get("load_weight_category"),
        "fragile": planning_payload.get("fragile", False),
        "refrigerated": planning_payload.get("refrigerated", False),
        "hazardous": planning_payload.get("hazardous", False),
        "loading_notes": planning_payload.get("loading_notes"),
        "customer_contact": planning_payload.get("customer_contact") or request_document.get("customer_phone"),
        "receiver_contact": planning_payload.get("receiver_contact"),
        "dispatch_instructions": planning_payload.get("dispatch_instructions"),
        "internal_notes": planning_payload.get("internal_notes"),
        "conflict_summary": [],
        "reservation_window": {
            "start_time": scheduled_start_time,
            "end_time": planning_payload.get("expected_return_time"),
        },
        "timeline": base_timeline,
        "created_by": base_document.get("created_by") or _to_object_id(current_user_id, "current_user_id"),
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": created_at,
        "updated_at": now_utc(),
        "assigned_at": base_document.get("assigned_at"),
        "started_at": base_document.get("started_at"),
        "completed_at": base_document.get("completed_at"),
        "cancelled_at": base_document.get("cancelled_at"),
    }


def save_dispatch_job_draft(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    request_document = _get_dispatch_request_document(request_id)
    planning_payload = _normalize_planning_payload(payload or {}, partial=False)
    _validate_planning_payload(request_document, planning_payload)
    existing_job_id = payload.get("job_id")
    existing_job = _get_dispatch_job_document(existing_job_id) if existing_job_id else None
    if existing_job and existing_job.get("status") not in {"draft", "reserved", "assigned", "clarification_requested", "rejected"}:
        raise ApiError("This dispatch job can no longer be updated as a draft.", status_code=400)
    document = _build_job_document(
        request_document=request_document,
        planning_payload=planning_payload,
        current_user_id=current_user_id,
        status="draft",
        existing_job=existing_job,
    )
    if existing_job:
        dispatch_jobs_collection().update_one({"_id": existing_job["_id"]}, {"$set": document})
        document["_id"] = existing_job["_id"]
    else:
        document["_id"] = dispatch_jobs_collection().insert_one(document).inserted_id
    _set_request_planning_state(request_document, planning_status="draft", active_dispatch_job_id=document["_id"])
    return _batch_enrich_dispatch_jobs([document])[0]


def reserve_dispatch_resources(job_id: str, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    job_document = _get_dispatch_job_document(job_id)
    if job_document.get("status") not in {"draft", "reserved", "rejected", "clarification_requested"}:
        raise ApiError("Only draft-style dispatch jobs can reserve resources.", status_code=400)
    if not job_document.get("vehicle_id") or not job_document.get("driver_id"):
        raise ApiError("Vehicle and driver are required before reserving resources.", status_code=400)
    start_time = job_document.get("scheduled_start_time")
    end_time = job_document.get("expected_return_time")
    if not start_time or not end_time:
        raise ApiError("Scheduling window is required before reserving resources.", status_code=400)
    conflict_summary = detect_dispatch_conflicts(
        vehicle_id=str(job_document["vehicle_id"]),
        driver_id=str(job_document["driver_id"]),
        scheduled_start_time=start_time,
        expected_return_time=end_time,
        exclude_job_id=str(job_document["_id"]),
    )
    if conflict_summary["has_conflicts"]:
        raise ApiError("Resource conflict detected. Resolve conflicts before reserving resources.", status_code=409)
    _release_reservations(job_document, reason="replaced during reservation refresh")
    vehicle_reservation_id = _create_reservation(
        reservation_type="vehicle",
        resource_id=job_document["vehicle_id"],
        dispatch_job_id=job_document["_id"],
        dispatch_request_id=job_document["dispatch_request_id"],
        start_time=start_time,
        end_time=end_time,
        current_user_id=current_user_id,
    )
    driver_reservation_id = _create_reservation(
        reservation_type="driver",
        resource_id=job_document["driver_id"],
        dispatch_job_id=job_document["_id"],
        dispatch_request_id=job_document["dispatch_request_id"],
        start_time=start_time,
        end_time=end_time,
        current_user_id=current_user_id,
    )
    timestamp = now_utc()
    update_fields = {
        "status": "reserved",
        "vehicle_reservation_id": vehicle_reservation_id,
        "driver_reservation_id": driver_reservation_id,
        "conflict_summary": [],
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
        "updated_at": timestamp,
    }
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": update_fields})
    job_document.update(update_fields)
    request_document = _get_dispatch_request_document(str(job_document["dispatch_request_id"]))
    _set_request_planning_state(request_document, planning_status="reserved", active_dispatch_job_id=job_document["_id"])
    return _batch_enrich_dispatch_jobs([job_document])[0]


def assign_dispatch_job(job_id: str, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    job_document = _get_dispatch_job_document(job_id)
    if job_document.get("status") not in {"reserved", "draft", "rejected", "clarification_requested"}:
        raise ApiError("This dispatch job cannot be assigned from its current state.", status_code=400)
    if not job_document.get("vehicle_reservation_id") or not job_document.get("driver_reservation_id"):
        job_document = reserve_dispatch_resources(job_id, current_user_id=current_user_id, current_role=current_role)
        job_document = _get_dispatch_job_document(job_id)
    timestamp = now_utc()
    was_previously_assigned = job_document.get("status") in {"assigned", "accepted", "clarification_requested"} and job_document.get("assigned_at")
    update_fields = {
        "status": "assigned",
        "driver_workflow_status": "assigned",
        "is_paused": False,
        "paused_at": None,
        "paused_reason": None,
        "driver_response_status": "pending",
        "driver_response_reason": None,
        "driver_responded_at": None,
        "assigned_at": timestamp,
        "timeline": _append_timeline_entry(
            job_document,
            title="Dispatch assigned to driver",
            status="assigned",
            event_type="dispatch_assigned",
            actor_id=current_user_id,
            timestamp=timestamp,
        ),
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
        "updated_at": timestamp,
    }
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": update_fields})
    job_document.update(update_fields)
    request_document = _get_dispatch_request_document(str(job_document["dispatch_request_id"]))
    _set_request_planning_state(request_document, planning_status="assigned", active_dispatch_job_id=job_document["_id"])
    if isinstance(job_document.get("driver_id"), ObjectId):
        _create_job_notification_once(
            recipient_user_id=job_document["driver_id"],
            title="Dispatch updated" if was_previously_assigned else "New dispatch assignment",
            message=(
                f"Dispatch {job_document.get('dispatch_job_id')} has been updated."
                if was_previously_assigned
                else f"You have a dispatch assignment {job_document.get('dispatch_job_id')} scheduled for {job_document.get('dispatch_date') or 'today'}."
            ),
            category="dispatch_update" if was_previously_assigned else "dispatch_assignment",
            priority="high",
            job_document=job_document,
            action_type="accept_dispatch",
            action_url="my-dispatches",
            action_label="Review dispatch",
            due_at=job_document.get("scheduled_start_time"),
        )
    return _batch_enrich_dispatch_jobs([job_document])[0]


def reassign_dispatch_job(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_planner_role(normalized_role)
    job_document = _get_dispatch_job_document(job_id)
    previous_driver_id = job_document.get("driver_id")
    if job_document.get("status") in {"in_progress", "completed", "cancelled"}:
        raise ApiError("Dispatch jobs cannot be reassigned after they start or close.", status_code=400)
    request_document = _get_dispatch_request_document(str(job_document["dispatch_request_id"]))
    planning_payload = _normalize_planning_payload({**serialize_dispatch_job(job_document), **(payload or {})}, partial=False)
    _validate_planning_payload(request_document, planning_payload)
    next_document = _build_job_document(
        request_document=request_document,
        planning_payload=planning_payload,
        current_user_id=current_user_id,
        status="draft",
        existing_job=job_document,
    )
    next_document["timeline"] = _append_timeline_entry(
        job_document,
        title="Dispatch reassigned for replanning",
        status="draft",
        event_type="dispatch_reassigned",
        actor_id=current_user_id,
        note=_normalize_text((payload or {}).get("reassignment_reason")),
    )
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": next_document})
    job_document.update(next_document)
    _release_reservations(job_document, reason="reassigned before dispatch start")
    dispatch_jobs_collection().update_one(
        {"_id": job_document["_id"]},
        {"$set": {"vehicle_reservation_id": None, "driver_reservation_id": None, "status": "draft", "updated_at": now_utc()}},
    )
    job_document["vehicle_reservation_id"] = None
    job_document["driver_reservation_id"] = None
    job_document["status"] = "draft"
    _set_request_planning_state(request_document, planning_status="draft", active_dispatch_job_id=job_document["_id"])
    if isinstance(previous_driver_id, ObjectId):
        _create_job_notification_once(
            recipient_user_id=previous_driver_id,
            title="Dispatch reassigned",
            message=f"Dispatch {job_document.get('dispatch_job_id')} has been reassigned by operations.",
            category="dispatch_reassigned",
            priority="high",
            job_document=job_document,
        )
    return _batch_enrich_dispatch_jobs([job_document])[0]


def _normalize_driver_list_section(section: str | None) -> str | None:
    normalized = _normalize_text(section)
    if not normalized:
        return None
    normalized = normalized.lower()
    if normalized not in DRIVER_LIST_SECTIONS:
        raise ApiError("Invalid dispatch list section.", status_code=400)
    return normalized


def _build_driver_dispatch_query(*, driver_id: ObjectId, section: str | None) -> dict:
    base_query = {"driver_id": driver_id}
    if section == "upcoming":
        base_query["status"] = {"$in": ["assigned", "accepted", "clarification_requested"]}
    elif section == "active":
        base_query["status"] = "in_progress"
    elif section == "completed":
        base_query["status"] = "completed"
    elif section == "cancelled":
        base_query["status"] = {"$in": ["cancelled", "rejected"]}
    else:
        base_query["status"] = {"$in": ["assigned", "accepted", "clarification_requested", "in_progress"]}
    return base_query


def _build_driver_dispatch_summary(*, driver_id: ObjectId) -> dict:
    today_start = now_utc().astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    active_job_document = dispatch_jobs_collection().find_one(
        {"driver_id": driver_id, "status": "in_progress"},
        DETAIL_JOB_PROJECTION,
        sort=[("updated_at", DESCENDING), ("scheduled_start_time", ASCENDING)],
    )
    active_job = _batch_enrich_dispatch_jobs([active_job_document])[0] if active_job_document else None
    return {
        "todays_dispatches": dispatch_jobs_collection().count_documents(
            {
                "driver_id": driver_id,
                "scheduled_start_time": {"$gte": today_start, "$lt": today_end},
                "status": {"$nin": ["cancelled", "rejected"]},
            }
        ),
        "upcoming_dispatches": dispatch_jobs_collection().count_documents(
            {"driver_id": driver_id, "status": {"$in": ["assigned", "accepted", "clarification_requested"]}}
        ),
        "current_active_dispatch": active_job,
        "pending_acceptance": dispatch_jobs_collection().count_documents(
            {"driver_id": driver_id, "status": "assigned", "driver_response_status": "pending"}
        ),
        "completed_today": dispatch_jobs_collection().count_documents(
            {"driver_id": driver_id, "completed_at": {"$gte": today_start, "$lt": today_end}, "status": "completed"}
        ),
    }


def list_driver_dispatch_jobs(*, current_user_id: str, section: str | None = None, page: int = 1, page_size: int = 10, include_summary: bool = False) -> dict:
    driver_id = _to_object_id(current_user_id, "current_user_id")
    normalized_section = _normalize_driver_list_section(section)
    query = _build_driver_dispatch_query(driver_id=driver_id, section=normalized_section)
    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 10, 1), 25)
    skip = (normalized_page - 1) * normalized_page_size
    aggregate = list(
        dispatch_jobs_collection().aggregate(
            [
                {"$match": query},
                {
                    "$facet": {
                        "records": [
                            {"$sort": {"scheduled_start_time": 1, "updated_at": -1, "_id": -1}},
                            {"$skip": skip},
                            {"$limit": normalized_page_size},
                            {"$project": DETAIL_JOB_PROJECTION or LIST_JOB_PROJECTION},
                        ],
                        "counts": [{"$count": "total"}],
                    }
                },
            ]
        )
    )
    payload = aggregate[0] if aggregate else {}
    records = payload.get("records") or []
    _sync_upcoming_dispatch_reminders(records)
    enriched_jobs = _batch_enrich_dispatch_jobs(records)
    total = int(((payload.get("counts") or [{}])[0]).get("total") or 0)
    response = {
        "jobs": enriched_jobs,
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "section": normalized_section or "overview",
    }
    if include_summary:
        response["summary"] = _build_driver_dispatch_summary(driver_id=driver_id)
    return response


def get_driver_dispatch_job(job_id: str, *, current_user_id: str) -> dict:
    job_document = _get_dispatch_job_document(job_id, projection=DETAIL_JOB_PROJECTION)
    _assert_driver_job_access(job_document, current_user_id=current_user_id)
    _sync_upcoming_dispatch_reminders([job_document])
    return _batch_enrich_dispatch_jobs([job_document])[0]


def _assert_driver_job_access(job_document: dict, *, current_user_id: str):
    if job_document.get("driver_id") != _to_object_id(current_user_id, "current_user_id"):
        raise ApiError("You do not have permission to update this dispatch assignment.", status_code=403)


def accept_driver_dispatch_job(job_id: str, *, current_user_id: str) -> dict:
    job_document = _get_dispatch_job_document(job_id)
    _assert_driver_job_access(job_document, current_user_id=current_user_id)
    if job_document.get("status") not in {"assigned", "clarification_requested"}:
        raise ApiError("This dispatch assignment can no longer be accepted.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "status": "accepted",
        "driver_workflow_status": "accepted",
        "is_paused": False,
        "paused_at": None,
        "paused_reason": None,
        "driver_response_status": "accepted",
        "driver_response_reason": None,
        "driver_responded_at": timestamp,
        "timeline": _append_timeline_entry(
            job_document,
            title="Driver accepted dispatch",
            status="accepted",
            event_type="driver_accepted",
            actor_id=current_user_id,
            timestamp=timestamp,
        ),
        "updated_at": timestamp,
    }
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": update_fields})
    job_document.update(update_fields)
    request_document = _get_dispatch_request_document(str(job_document["dispatch_request_id"]))
    _set_request_planning_state(request_document, planning_status="accepted", active_dispatch_job_id=job_document["_id"])
    resolve_action_notifications("dispatch_job", job_document["_id"], action_type="accept_dispatch", completed_by=current_user_id)
    return _batch_enrich_dispatch_jobs([job_document])[0]


def request_dispatch_clarification(job_id: str, payload: dict, *, current_user_id: str) -> dict:
    job_document = _get_dispatch_job_document(job_id)
    _assert_driver_job_access(job_document, current_user_id=current_user_id)
    if job_document.get("status") not in {"assigned", "accepted"}:
        raise ApiError("Clarification can only be requested before dispatch starts.", status_code=400)
    reason = _normalize_text((payload or {}).get("reason"))
    if not reason:
        raise ApiError("reason is required when requesting clarification.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "status": "clarification_requested",
        "driver_response_status": "clarification_requested",
        "driver_response_reason": reason,
        "driver_responded_at": timestamp,
        "timeline": _append_timeline_entry(
            job_document,
            title="Driver requested clarification",
            status="clarification_requested",
            event_type="clarification_requested",
            actor_id=current_user_id,
            note=reason,
            timestamp=timestamp,
        ),
        "updated_at": timestamp,
    }
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": update_fields})
    job_document.update(update_fields)
    request_document = _get_dispatch_request_document(str(job_document["dispatch_request_id"]))
    _set_request_planning_state(request_document, planning_status="clarification_requested", active_dispatch_job_id=job_document["_id"])
    return _batch_enrich_dispatch_jobs([job_document])[0]


def reject_driver_dispatch_job(job_id: str, payload: dict, *, current_user_id: str) -> dict:
    job_document = _get_dispatch_job_document(job_id)
    _assert_driver_job_access(job_document, current_user_id=current_user_id)
    if job_document.get("status") not in {"assigned", "accepted", "clarification_requested"}:
        raise ApiError("This dispatch assignment can no longer be rejected.", status_code=400)
    reason = _normalize_text((payload or {}).get("reason"))
    if not reason:
        raise ApiError("reason is required when rejecting a dispatch assignment.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "status": "rejected",
        "driver_response_status": "rejected",
        "driver_response_reason": reason,
        "driver_responded_at": timestamp,
        "timeline": _append_timeline_entry(
            job_document,
            title="Driver rejected dispatch",
            status="rejected",
            event_type="driver_rejected",
            actor_id=current_user_id,
            note=reason,
            timestamp=timestamp,
        ),
        "updated_at": timestamp,
    }
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": update_fields})
    job_document.update(update_fields)
    _release_reservations(job_document, reason="driver rejected assignment")
    request_document = _get_dispatch_request_document(str(job_document["dispatch_request_id"]))
    _set_request_planning_state(request_document, planning_status="rejected", active_dispatch_job_id=job_document["_id"])
    resolve_action_notifications("dispatch_job", job_document["_id"], action_type="accept_dispatch", resolution="cancelled", completed_by=current_user_id)
    return _batch_enrich_dispatch_jobs([job_document])[0]


def update_driver_dispatch_job_workflow(job_id: str, payload: dict, *, current_user_id: str) -> dict:
    job_document = _get_dispatch_job_document(job_id)
    _assert_driver_job_access(job_document, current_user_id=current_user_id)
    action = _normalize_text((payload or {}).get("action"))
    if not action:
        raise ApiError("action is required.", status_code=400)
    action = action.lower()
    timestamp = now_utc()
    note = _normalize_text((payload or {}).get("note"))
    workflow_status = _get_driver_workflow_status(job_document)
    update_fields = {
        "updated_at": timestamp,
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
    }
    next_request_state = None

    if action == "start":
        if job_document.get("status") != "accepted":
            raise ApiError("Only accepted dispatches can be started.", status_code=400)
        update_fields.update(
            {
                "status": "in_progress",
                "driver_workflow_status": "travelling_to_pickup",
                "started_at": job_document.get("started_at") or timestamp,
                "actual_departure_at": job_document.get("actual_departure_at") or job_document.get("started_at") or timestamp,
                "is_paused": False,
                "paused_at": None,
                "paused_reason": None,
                "timeline": _append_timeline_entry(
                    job_document,
                    title="Travelling to pickup",
                    status="travelling_to_pickup",
                    event_type="dispatch_started",
                    actor_id=current_user_id,
                    note=note,
                    timestamp=timestamp,
                ),
            }
        )
        next_request_state = "in_progress"
    elif action == "pause":
        if job_document.get("status") != "in_progress" or job_document.get("is_paused"):
            raise ApiError("Only active dispatches can be paused.", status_code=400)
        update_fields.update(
            {
                "is_paused": True,
                "paused_at": timestamp,
                "paused_reason": note,
                "timeline": _append_timeline_entry(
                    job_document,
                    title="Dispatch paused",
                    status=workflow_status,
                    event_type="dispatch_paused",
                    actor_id=current_user_id,
                    note=note,
                    timestamp=timestamp,
                ),
            }
        )
    elif action == "resume":
        if job_document.get("status") != "in_progress" or not job_document.get("is_paused"):
            raise ApiError("Only paused dispatches can be resumed.", status_code=400)
        resumed_status = "in_transit" if workflow_status == "goods_loaded" else workflow_status
        update_fields.update(
            {
                "driver_workflow_status": resumed_status,
                "is_paused": False,
                "paused_at": None,
                "paused_reason": None,
                "timeline": _append_timeline_entry(
                    job_document,
                    title="Dispatch resumed",
                    status=resumed_status,
                    event_type="dispatch_resumed",
                    actor_id=current_user_id,
                    note=note,
                    timestamp=timestamp,
                ),
            }
        )
    elif action == "goods_loaded":
        if job_document.get("status") != "in_progress" or workflow_status not in {"travelling_to_pickup", "accepted"}:
            raise ApiError("Goods can only be marked loaded after the dispatch starts.", status_code=400)
        update_fields.update(
            {
                "driver_workflow_status": "goods_loaded",
                "timeline": _append_timeline_entry(
                    job_document,
                    title="Goods loaded",
                    status="goods_loaded",
                    event_type="goods_loaded",
                    actor_id=current_user_id,
                    note=note,
                    timestamp=timestamp,
                ),
            }
        )
    elif action == "stop_completed":
        if job_document.get("status") != "in_progress":
            raise ApiError("Stops can only be completed during an active dispatch.", status_code=400)
        stop_id = _normalize_text((payload or {}).get("stop_id"))
        if not stop_id:
            raise ApiError("stop_id is required when completing a stop.", status_code=400)
        stops = list(job_document.get("stops") or [])
        stop_index = next((index for index, stop in enumerate(stops) if stop.get("stop_id") == stop_id), None)
        if stop_index is None:
            raise ApiError("Dispatch stop not found.", status_code=404)
        stop = dict(stops[stop_index])
        stop["stop_status"] = "completed"
        stop["completed_at"] = timestamp
        stop["completed_by"] = _to_object_id(current_user_id, "current_user_id")
        stop["completion_note"] = note
        stops[stop_index] = stop
        update_fields.update(
            {
                "stops": stops,
                "timeline": _append_timeline_entry(
                    job_document,
                    title=f"Stop {stop.get('stop_sequence') or stop_id} completed",
                    status=_get_driver_workflow_status(job_document),
                    event_type="stop_completed",
                    actor_id=current_user_id,
                    note=note or stop.get("location"),
                    timestamp=timestamp,
                ),
            }
        )
    elif action == "delivery_completed":
        if job_document.get("status") != "in_progress":
            raise ApiError("Delivery can only be completed during an active dispatch.", status_code=400)
        stop_id = _normalize_text((payload or {}).get("stop_id"))
        movement_id = _normalize_text((payload or {}).get("movement_id"))
        stops = list(job_document.get("stops") or [])
        if stop_id:
            if not movement_id:
                movement_id = str(job_document.get("linked_vehicle_movement_id")) if job_document.get("linked_vehicle_movement_id") else None
            if not movement_id and isinstance(job_document.get("vehicle_id"), ObjectId):
                movement_id = str(_ensure_linked_vehicle_movement(job_document, current_user_id=current_user_id))
            confirm_dispatch_request_stop_delivery(
                str(job_document["dispatch_request_id"]),
                stop_id,
                {"movement_id": movement_id, "delivery_note": note, "delivered_at": timestamp.isoformat()},
                current_user_id=current_user_id,
                current_role="driver",
            )
            stop_index = next((index for index, stop in enumerate(stops) if stop.get("stop_id") == stop_id), None)
            if stop_index is None:
                raise ApiError("Dispatch stop not found.", status_code=404)
            stop = dict(stops[stop_index])
            stop["delivery_status"] = "delivered"
            stop["delivered_at"] = timestamp
            stop["delivery_note"] = note
            stop["delivered_by"] = _to_object_id(current_user_id, "current_user_id")
            stops[stop_index] = stop
            update_fields["stops"] = stops
        update_fields.update(
            {
                "driver_workflow_status": "delivered",
                "timeline": _append_timeline_entry(
                    job_document,
                    title="Delivery completed",
                    status="delivered",
                    event_type="delivery_completed",
                    actor_id=current_user_id,
                    note=note,
                    timestamp=timestamp,
                ),
            }
        )
    elif action == "end":
        if job_document.get("status") != "in_progress":
            raise ApiError("Only active dispatches can be ended.", status_code=400)
        timeline = _append_timeline_entry(
            job_document,
            title="Returning to base",
            status="returning",
            event_type="returning",
            actor_id=current_user_id,
            note=note,
            timestamp=timestamp,
        )
        timeline.append(
            _build_timeline_entry(
                title="Dispatch returned",
                status="returned",
                event_type="dispatch_completed",
                actor_id=current_user_id,
                note=note,
                timestamp=timestamp,
            )
        )
        update_fields.update(
            {
                "status": "completed",
                "driver_workflow_status": "returned",
                "completed_at": timestamp,
                "is_paused": False,
                "paused_at": None,
                "paused_reason": None,
                "timeline": timeline,
            }
        )
        next_request_state = "completed"
    else:
        raise ApiError("Unsupported dispatch action.", status_code=400)

    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": update_fields})
    job_document.update(update_fields)
    if action == "delivery_completed":
        notify_roles(
            ["owner", "admin", "dispatcher"],
            title="Vehicle return awaiting confirmation",
            message=f"Dispatch {job_document.get('dispatch_job_id')} completed delivery and requires vehicle return confirmation.",
            category="dispatch_return",
            priority="high",
            reference_type="dispatch_job",
            reference_id=job_document["_id"],
            action_type="confirm_vehicle_return",
            action_url="dispatch-returns",
            action_label="Confirm vehicle return",
            due_at=job_document.get("expected_return_time"),
        )
    if action == "start":
        _consume_reservations(job_document)
        if isinstance(job_document.get("vehicle_id"), ObjectId):
            movement_id = _ensure_linked_vehicle_movement(job_document, current_user_id=current_user_id)
            job_document["linked_vehicle_movement_id"] = movement_id
    elif action == "delivery_completed" and isinstance(job_document.get("linked_vehicle_movement_id"), ObjectId):
        vehicle_movements_collection().update_one(
            {"_id": job_document["linked_vehicle_movement_id"]},
            {
                "$set": {
                    "delivery_status": "delivered",
                    "delivered_at": timestamp,
                    "delivery_note": note,
                    "delivered_by": _to_object_id(current_user_id, "current_user_id"),
                    "updated_at": timestamp,
                }
            },
        )
    if next_request_state:
        request_document = _get_dispatch_request_document(str(job_document["dispatch_request_id"]))
        _set_request_planning_state(request_document, planning_status=next_request_state, active_dispatch_job_id=job_document["_id"])
    return _batch_enrich_dispatch_jobs([job_document])[0]
