from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from math import ceil
from time import perf_counter
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.dispatch_job import serialize_dispatch_job
from models.fault import serialize_fault
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from models.vehicle_movement import serialize_vehicle_movement
from services.fault_service import create_fault, list_fault_options
from services.notification_service import resolve_action_notifications
from utils.api_error import ApiError
from utils.fuel_levels import is_valid_dispatch_fuel_level, normalize_fuel_level_eighths
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import log_db_duration


RETURN_STATUSES = {
    "awaiting_return",
    "returned",
    "inspection_completed",
    "dispatch_closed",
}
ACCESSORY_STATUSES = {"returned", "missing", "damaged"}
VEHICLE_CONDITIONS = {"excellent", "good", "fair", "damaged", "unsafe"}
ACCESSORY_DEFAULTS = [
    "Ignition Key",
    "Spare Key",
    "Jack",
    "Wheel Spanner",
    "Fire Extinguisher",
    "Reflective Triangle",
    "First Aid Kit",
    "Company Documents",
    "Other Assigned Equipment",
]
LIST_JOB_PROJECTION = {
    "dispatch_job_id": 1,
    "status": 1,
    "driver_workflow_status": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "scheduled_start_time": 1,
    "dispatch_date": 1,
    "dispatch_time": 1,
    "completed_at": 1,
    "actual_departure_at": 1,
    "actual_return_at": 1,
    "expected_return_time": 1,
    "linked_vehicle_movement_id": 1,
    "return_status": 1,
    "return_confirmed_at": 1,
    "inspection_completed_at": 1,
    "dispatch_closed_at": 1,
    "linked_fault_id": 1,
}
DETAIL_JOB_PROJECTION = None
USER_SUMMARY_PROJECTION = {"full_name": 1, "email": 1, "phone": 1, "role": 1, "status": 1}
VEHICLE_SUMMARY_PROJECTION = {"registration_number": 1, "vehicle_type": 1, "make": 1, "model": 1, "status": 1, "assigned_driver_id": 1}
FAULT_CANDIDATE_PROJECTION = {"vehicle_id": 1, "driver_id": 1, "severity": 1, "description": 1, "status": 1, "reported_at": 1}
OPEN_RESERVATION_STATUSES = {"reserved", "consumed"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def dispatch_jobs_collection():
    return get_collection("dispatch_jobs")


def dispatch_requests_collection():
    return get_collection("dispatch_requests")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def resource_reservations_collection():
    return get_collection("resource_reservations")


def faults_collection():
    return get_collection("faults")


def ensure_dispatch_return_indexes():
    ensure_indexes_for_collection(
        dispatch_jobs_collection(),
        [
            {"keys": [("return_status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING), ("return_status", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("return_status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("driver_id", ASCENDING), ("return_status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("return_confirmed_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("inspection_completed_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("dispatch_closed_at", DESCENDING)], "options": {"sparse": True}},
        ],
        collection_name="dispatch_jobs_returns",
    )
    ensure_indexes_for_collection(
        vehicle_movements_collection(),
        [
            {"keys": [("dispatch_job_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING), ("actual_return_time", DESCENDING)]},
            {"keys": [("returned_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("closed_at", DESCENDING)], "options": {"sparse": True}},
        ],
        collection_name="vehicle_movements_dispatch_returns",
    )


def _normalize_text(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


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
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError as error:
            raise ApiError(f"{field_name} must be a valid ISO datetime.", status_code=400) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_utc_datetime(value) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, "datetime", required=False)


def _parse_return_datetime(payload: dict) -> tuple[datetime, str, str]:
    return_date_value = _normalize_text((payload or {}).get("return_date"))
    return_time_value = _normalize_text((payload or {}).get("return_time"))
    if not return_date_value:
        raise ApiError("return_date is required.", status_code=400)
    if not return_time_value:
        raise ApiError("return_time is required.", status_code=400)
    try:
        parsed_date = date.fromisoformat(return_date_value)
    except ValueError as error:
        raise ApiError("return_date must use YYYY-MM-DD format.", status_code=400) from error
    try:
        parsed_time = time.fromisoformat(return_time_value)
    except ValueError as error:
        raise ApiError("return_time must be a valid time.", status_code=400) from error

    offset_value = (payload or {}).get("timezone_offset_minutes", 0)
    if isinstance(offset_value, bool) or not isinstance(offset_value, (int, float)):
        raise ApiError("timezone_offset_minutes must be numeric.", status_code=400)
    if abs(float(offset_value)) > 14 * 60:
        raise ApiError("timezone_offset_minutes is invalid.", status_code=400)
    local_timezone = timezone(timedelta(minutes=-float(offset_value)))
    combined_return_at = datetime.combine(parsed_date, parsed_time, tzinfo=local_timezone).astimezone(timezone.utc)

    supplied_return_at = _parse_datetime(
        (payload or {}).get("actual_return_at") or (payload or {}).get("actual_return_time"),
        "actual_return_at",
        required=False,
    )
    if supplied_return_at is not None and abs((supplied_return_at - combined_return_at).total_seconds()) >= 1:
        raise ApiError("actual_return_at does not match the selected return date and time.", status_code=400)
    return combined_return_at, parsed_date.isoformat(), parsed_time.strftime("%H:%M")


def _resolve_actual_departure_at(job_document: dict, movement_document: dict) -> datetime:
    for value in (
        job_document.get("actual_departure_at"),
        movement_document.get("actual_departure_at"),
        job_document.get("started_at"),
    ):
        normalized = _coerce_utc_datetime(value)
        if normalized is not None:
            return normalized
    raise ApiError(
        "The recorded departure time is unavailable. Start the dispatch before confirming vehicle return.",
        status_code=400,
    )


def _format_safe_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%d-%b-%Y %I:%M %p UTC")


def _validate_return_after_departure(*, actual_return_at: datetime, actual_departure_at: datetime):
    if actual_return_at <= actual_departure_at:
        raise ApiError(
            "Return time must be after the recorded departure time.\n"
            f"Recorded departure: {_format_safe_datetime(actual_departure_at)}\n"
            f"Entered return: {_format_safe_datetime(actual_return_at)}",
            status_code=400,
        )


def _validate_non_negative_number(value, field_name: str, *, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _validate_fuel_level(value, field_name: str):
    if value not in (None, "") and not is_valid_dispatch_fuel_level(value):
        raise ApiError(
            f"{field_name} must be E, 1/8 through 7/8, or F.",
            status_code=400,
        )
    normalized, error_message = normalize_fuel_level_eighths(value)
    if normalized is None and value not in (None, ""):
        raise ApiError(
            error_message or f"{field_name} must be a fuel level between 0/8 and 8/8.",
            status_code=400,
        )
    return normalized


def _validate_required_fuel_level(value, field_name: str):
    if value in (None, ""):
        raise ApiError(f"{field_name} is required.", status_code=400)
    return _validate_fuel_level(value, field_name)


def _normalize_return_status(value: str | None, *, default: str = "awaiting_return") -> str:
    normalized = _normalize_text(value) or default
    normalized = normalized.lower()
    if normalized not in RETURN_STATUSES:
        raise ApiError("Invalid return_status.", status_code=400)
    return normalized


def _normalize_vehicle_condition(value: str | None) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        raise ApiError("vehicle_condition is required.", status_code=400)
    normalized = normalized.lower()
    if normalized not in VEHICLE_CONDITIONS:
        raise ApiError("Invalid vehicle_condition.", status_code=400)
    return normalized


def _build_accessory_defaults():
    return [{"name": name, "status": "returned"} for name in ACCESSORY_DEFAULTS]


def _normalize_accessories(value) -> list[dict]:
    items = value if isinstance(value, list) else []
    if not items:
        items = _build_accessory_defaults()
    normalized_items = []
    for item in items:
        if not isinstance(item, dict):
            raise ApiError("accessories must be a list of objects.", status_code=400)
        name = _normalize_text(item.get("name"))
        if not name:
            raise ApiError("Each accessory item requires a name.", status_code=400)
        status = (_normalize_text(item.get("status")) or "returned").lower()
        if status not in ACCESSORY_STATUSES:
            raise ApiError("Invalid accessory return status.", status_code=400)
        normalized_items.append({"name": name, "status": status})
    return normalized_items


def _missing_accessory_warnings(accessories: list[dict]) -> list[str]:
    warnings = []
    for accessory in accessories:
        if accessory.get("status") in {"missing", "damaged"}:
            warnings.append(f"{accessory.get('name')} marked as {accessory.get('status')}.")
    return warnings


def _get_dispatch_job_document(job_id: str, *, projection: dict | None = None) -> dict:
    job_object_id = _to_object_id(job_id, "dispatch_job_id")
    document = dispatch_jobs_collection().find_one({"_id": job_object_id}, projection)
    if not document:
        raise ApiError("Dispatch job not found.", status_code=404)
    return document


def _get_fault_document(fault_id: str | ObjectId) -> dict:
    document = faults_collection().find_one({"_id": _to_object_id(fault_id, "fault_id")})
    if not document:
        raise ApiError("Fault not found.", status_code=404)
    return document


def _get_vehicle_movement_document(movement_id: str | ObjectId) -> dict:
    document = vehicle_movements_collection().find_one({"_id": _to_object_id(movement_id, "movement_id")})
    if not document:
        raise ApiError("Vehicle movement not found.", status_code=404)
    return document


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


def _derive_return_status(job_document: dict, movement_document: dict | None) -> str:
    explicit_status = _normalize_text(job_document.get("return_status"))
    if explicit_status in RETURN_STATUSES:
        return explicit_status.lower()
    movement_status = (movement_document or {}).get("status")
    if movement_status == "closed":
        return "dispatch_closed"
    if movement_status == "returned":
        return "returned"
    return "awaiting_return"


def _set_vehicle_status(vehicle_id: ObjectId, *, next_status: str):
    vehicles_collection().update_one(
        {"_id": vehicle_id},
        {"$set": {"status": next_status, "updated_at": now_utc()}},
    )


def _release_job_reservations(job_document: dict, *, reason: str):
    reservation_ids = [job_document.get("vehicle_reservation_id"), job_document.get("driver_reservation_id")]
    reservation_ids = [item for item in reservation_ids if isinstance(item, ObjectId)]
    if not reservation_ids:
        return
    resource_reservations_collection().update_many(
        {"_id": {"$in": reservation_ids}, "status": {"$in": sorted(OPEN_RESERVATION_STATUSES)}},
        {"$set": {"status": "released", "release_reason": reason, "released_at": now_utc(), "updated_at": now_utc()}},
    )


def _ensure_linked_vehicle_movement(job_document: dict, *, current_user_id: str) -> dict:
    from services.movement_source_service import ensure_dispatch_movement

    result = ensure_dispatch_movement(
        job_document,
        current_user_id=current_user_id,
        initial_status="in_progress",
        departure_at=job_document.get("actual_departure_at") or job_document.get("started_at"),
    )
    return result["movement"]


def _load_lookup_map(collection, ids: set[ObjectId], projection: dict) -> dict[ObjectId, dict]:
    if not ids:
        return {}
    return {item["_id"]: item for item in collection.find({"_id": {"$in": list(ids)}}, projection)}


def _build_return_list_payload(job_documents: list[dict], movement_lookup: dict[ObjectId, dict]) -> list[dict]:
    user_ids = {
        job_document.get("driver_id")
        for job_document in job_documents
        if isinstance(job_document.get("driver_id"), ObjectId)
    }
    vehicle_ids = {
        job_document.get("vehicle_id")
        for job_document in job_documents
        if isinstance(job_document.get("vehicle_id"), ObjectId)
    }
    users = _load_lookup_map(users_collection(), user_ids, USER_SUMMARY_PROJECTION)
    vehicles = _load_lookup_map(vehicles_collection(), vehicle_ids, VEHICLE_SUMMARY_PROJECTION)
    payload = []
    for job_document in job_documents:
        movement_document = None
        if isinstance(job_document.get("linked_vehicle_movement_id"), ObjectId):
            movement_document = movement_lookup.get(job_document.get("linked_vehicle_movement_id"))
        if movement_document is None:
            movement_document = movement_lookup.get(job_document["_id"])
        return_status = _derive_return_status(job_document, movement_document)
        payload.append(
            {
                "id": str(job_document["_id"]),
                "dispatch_job_id": job_document.get("dispatch_job_id"),
                "dispatch_date": job_document.get("dispatch_date"),
                "dispatch_time": job_document.get("dispatch_time"),
                "scheduled_start_time": job_document.get("scheduled_start_time").isoformat() if job_document.get("scheduled_start_time") else None,
                "current_dispatch_status": job_document.get("status"),
                "driver_workflow_status": job_document.get("driver_workflow_status"),
                "return_status": return_status,
                "return_time": (
                    (movement_document.get("actual_return_at") or movement_document.get("actual_return_time")).isoformat()
                    if movement_document and (movement_document.get("actual_return_at") or movement_document.get("actual_return_time"))
                    else (
                        (job_document.get("actual_return_at") or job_document.get("return_confirmed_at")).isoformat()
                        if (job_document.get("actual_return_at") or job_document.get("return_confirmed_at"))
                        else None
                    )
                ),
                "vehicle": serialize_vehicle(vehicles[job_document["vehicle_id"]], include_sensitive=False) if vehicles.get(job_document.get("vehicle_id")) else None,
                "driver": serialize_user(users[job_document["driver_id"]]) if users.get(job_document.get("driver_id")) else None,
                "movement_id": str(movement_document["_id"]) if movement_document else None,
                "movement_status": movement_document.get("status") if movement_document else None,
            }
        )
    return payload


def _list_fault_candidates_for_vehicle(vehicle_id: ObjectId) -> list[dict]:
    documents = list(
        faults_collection().find(
            {"vehicle_id": vehicle_id, "status": {"$in": ["reported", "under_review", "approved", "resolved"]}},
            FAULT_CANDIDATE_PROJECTION,
        ).sort([("reported_at", DESCENDING)]).limit(12)
    )
    return [serialize_fault(document) for document in documents]


def _build_return_detail(job_document: dict) -> dict:
    movement_document = None
    if isinstance(job_document.get("linked_vehicle_movement_id"), ObjectId):
        movement_document = vehicle_movements_collection().find_one({"_id": job_document["linked_vehicle_movement_id"]})
    if movement_document is None:
        movement_document = vehicle_movements_collection().find_one({"dispatch_job_id": job_document["_id"]})
    vehicle_document = vehicles_collection().find_one({"_id": job_document.get("vehicle_id")}) if isinstance(job_document.get("vehicle_id"), ObjectId) else None
    driver_document = users_collection().find_one({"_id": job_document.get("driver_id")}) if isinstance(job_document.get("driver_id"), ObjectId) else None
    linked_fault_document = _get_fault_document(job_document.get("linked_fault_id")) if job_document.get("linked_fault_id") else None
    from services.dispatch_fuel_service import build_dispatch_fuel_summary, list_dispatch_fuel_logs

    fuel_logs = list_dispatch_fuel_logs(job_document["_id"])
    fuel_accountability = build_dispatch_fuel_summary(
        movement_document,
        vehicle=vehicle_document,
        fuel_logs=fuel_logs,
    )
    return {
        "job": serialize_dispatch_job(job_document),
        "movement": _enrich_vehicle_movement_detail(movement_document) if movement_document else None,
        "vehicle": serialize_vehicle(vehicle_document, include_sensitive=False) if vehicle_document else None,
        "driver": serialize_user(driver_document) if driver_document else None,
        "return_status": _derive_return_status(job_document, movement_document),
        "return_checklist": job_document.get("return_checklist") or (movement_document or {}).get("return_checklist") or {
            "accessories": _build_accessory_defaults(),
        },
        "vehicle_conditions": sorted(VEHICLE_CONDITIONS),
        "accessory_statuses": sorted(ACCESSORY_STATUSES),
        "default_accessories": ACCESSORY_DEFAULTS,
        "fault_options": list_fault_options("admin"),
        "existing_faults": _list_fault_candidates_for_vehicle(job_document.get("vehicle_id")) if isinstance(job_document.get("vehicle_id"), ObjectId) else [],
        "linked_fault": serialize_fault(linked_fault_document) if linked_fault_document else None,
        "fuel_accountability": fuel_accountability,
    }


def _enrich_vehicle_movement_detail(movement_document: dict) -> dict:
    if not movement_document:
        return {}
    payload = serialize_vehicle_movement(movement_document)
    if isinstance(movement_document.get("vehicle_id"), ObjectId):
        vehicle_document = vehicles_collection().find_one({"_id": movement_document["vehicle_id"]})
        payload["vehicle"] = serialize_vehicle(vehicle_document, include_sensitive=False) if vehicle_document else None
    if isinstance(movement_document.get("driver_id"), ObjectId):
        driver_document = users_collection().find_one({"_id": movement_document["driver_id"]})
        payload["driver"] = serialize_user(driver_document) if driver_document else None
    return payload


def list_dispatch_returns(*, current_role: str, page: int = 1, page_size: int = 20, search_query: str | None = None, return_status: str | None = None) -> dict:
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role not in {"owner", "admin", "dispatcher"}:
        raise ApiError("You do not have permission to access dispatch returns.", status_code=403)
    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 20, 1), 50)
    query: dict = {
        "$or": [
            {"status": {"$in": ["in_progress", "completed"]}},
            {"return_status": {"$in": sorted(RETURN_STATUSES)}},
        ]
    }
    normalized_search = _normalize_text(search_query)
    if normalized_search:
        query["dispatch_job_id"] = {"$regex": normalized_search, "$options": "i"}
    if return_status:
        query["return_status"] = _normalize_return_status(return_status)
    skip = (normalized_page - 1) * normalized_page_size
    aggregate_started_at = perf_counter()
    aggregate = list(
        dispatch_jobs_collection().aggregate(
            [
                {"$match": query},
                {
                    "$facet": {
                        "records": [
                            {"$sort": {"updated_at": -1, "scheduled_start_time": -1, "_id": -1}},
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
    log_db_duration("dispatch_returns.list.aggregate", aggregate_started_at)
    payload = aggregate[0] if aggregate else {}
    records = payload.get("records") or []
    total = int(((payload.get("counts") or [{}])[0]).get("total") or 0)
    job_ids = [record["_id"] for record in records]
    movement_documents = list(
        vehicle_movements_collection().find(
            {
                "$or": [
                    {"dispatch_job_id": {"$in": job_ids}},
                    {"_id": {"$in": [record.get("linked_vehicle_movement_id") for record in records if isinstance(record.get("linked_vehicle_movement_id"), ObjectId)]}},
                ]
            }
        )
    ) if records else []
    movement_lookup = {}
    for movement_document in movement_documents:
        if isinstance(movement_document.get("_id"), ObjectId):
            movement_lookup[movement_document["_id"]] = movement_document
        if isinstance(movement_document.get("dispatch_job_id"), ObjectId):
            movement_lookup[movement_document["dispatch_job_id"]] = movement_document
    return {
        "returns": _build_return_list_payload(records, movement_lookup),
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "filters": {"q": search_query, "return_status": return_status},
    }


def get_dispatch_return_detail(job_id: str, *, current_role: str) -> dict:
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role not in {"owner", "admin", "dispatcher"}:
        raise ApiError("You do not have permission to access dispatch return details.", status_code=403)
    job_document = _get_dispatch_job_document(job_id, projection=DETAIL_JOB_PROJECTION)
    return _build_return_detail(job_document)


def confirm_dispatch_return(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role not in {"owner", "admin", "dispatcher"}:
        raise ApiError("You do not have permission to confirm dispatch returns.", status_code=403)
    job_document = _get_dispatch_job_document(job_id)
    movement_document = _ensure_linked_vehicle_movement(job_document, current_user_id=current_user_id)
    movement_status = _normalize_text(movement_document.get("status")) or ""
    if movement_status == "closed":
        raise ApiError("Closed dispatch returns cannot be confirmed again.", status_code=400)
    if movement_status == "cancelled":
        raise ApiError("Cancelled vehicle movements cannot be returned.", status_code=400)
    if movement_status == "returned":
        raise ApiError("This dispatch return has already been confirmed.", status_code=400)
    if movement_status not in {"checked_out", "in_progress"}:
        raise ApiError(
            "Vehicle return can only be confirmed after the movement has checked out or started.",
            status_code=400,
        )
    timestamp = now_utc()
    actual_return_at, return_date_value, return_time_value = _parse_return_datetime(payload or {})
    actual_departure_at = _resolve_actual_departure_at(job_document, movement_document)
    _validate_return_after_departure(
        actual_return_at=actual_return_at,
        actual_departure_at=actual_departure_at,
    )
    closing_odometer = _validate_non_negative_number(
        (payload or {}).get("closing_odometer"),
        "closing_odometer",
    )
    recorded_closing_odometer = (
        closing_odometer
        if closing_odometer is not None
        else movement_document.get("closing_odometer")
    )
    opening_odometer = movement_document.get("opening_odometer")
    if (
        opening_odometer is not None
        and recorded_closing_odometer is not None
        and recorded_closing_odometer < opening_odometer
    ):
        raise ApiError("closing_odometer must be greater than or equal to opening_odometer.", status_code=400)
    closing_fuel_level = _validate_required_fuel_level(
        (payload or {}).get("closing_fuel_level"),
        "closing_fuel_level",
    )
    notes = _normalize_text((payload or {}).get("notes")) or movement_document.get("notes")
    return_checklist = {
        **(movement_document.get("return_checklist") or job_document.get("return_checklist") or {}),
        "vehicle_id": str(job_document.get("vehicle_id")) if job_document.get("vehicle_id") else None,
        "driver_id": str(job_document.get("driver_id")) if job_document.get("driver_id") else None,
        "return_date": return_date_value,
        "return_time": return_time_value,
        "actual_return_at": actual_return_at.isoformat(),
        "closing_odometer": recorded_closing_odometer,
        "closing_fuel_level": closing_fuel_level,
    }
    movement_update_fields = {
        "status": "returned",
        "actual_departure_at": actual_departure_at,
        "actual_return_at": actual_return_at,
        "actual_return_time": actual_return_at,
        "closing_odometer": recorded_closing_odometer,
        "closing_fuel_level": closing_fuel_level,
        "closing_fuel_recorded_at": timestamp,
        "closing_fuel_recorded_by": _to_object_id(current_user_id, "current_user_id"),
        "return_note": notes,
        "fuel_summary_status": "closing_confirmed",
        "return_checklist": return_checklist,
        "notes": notes,
        "returned_by": _to_object_id(current_user_id, "current_user_id"),
        "returned_at": timestamp,
        "updated_at": timestamp,
    }
    movement_update_result = vehicle_movements_collection().update_one(
        {"_id": movement_document["_id"], "status": {"$in": ["checked_out", "in_progress"]}},
        {"$set": movement_update_fields},
    )
    if movement_update_result.matched_count != 1:
        raise ApiError("This dispatch return has already been confirmed.", status_code=409)
    _release_job_reservations(job_document, reason="dispatch vehicle returned")
    if isinstance(job_document.get("vehicle_id"), ObjectId):
        _set_vehicle_status(job_document["vehicle_id"], next_status="available")
    job_update_fields = {
        "return_status": "returned",
        "actual_departure_at": actual_departure_at,
        "actual_return_at": actual_return_at,
        "return_confirmed_at": timestamp,
        "return_confirmed_by": _to_object_id(current_user_id, "current_user_id"),
        "linked_vehicle_movement_id": movement_document["_id"],
        "return_checklist": return_checklist,
        "timeline": _append_timeline_entry(
            job_document,
            title="Vehicle returned and received",
            status="returned",
            event_type="vehicle_return_confirmed",
            actor_id=current_user_id,
            note=notes,
            timestamp=timestamp,
        ),
        "updated_at": timestamp,
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
    }
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": job_update_fields})
    job_document.update(job_update_fields)
    movement_document.update(movement_update_fields)
    from services.movement_custody_service import return_movement_custody

    return_movement_custody(
        movement_document["_id"],
        {
            "event_type": "received_by_company",
            "to_location": "Company custody",
            "fuel_level": closing_fuel_level,
            "odometer": recorded_closing_odometer,
            "odometer_available": recorded_closing_odometer is not None,
            "odometer_unavailable_reason": (
                "Odometer was not recorded during dispatch return."
                if recorded_closing_odometer is None
                else None
            ),
            "condition_summary": notes,
            "source_type": "dispatch_job",
            "source_id": job_document["_id"],
            "audit_reason": "Dispatch return received by an authorized administrator.",
        },
        current_user_id=current_user_id,
        current_role=current_role,
        source_event_key=f"dispatch:{job_document['_id']}:returned-to-company",
    )
    from services.dispatch_fuel_service import refresh_dispatch_fuel_summary

    refresh_dispatch_fuel_summary(job_document["_id"])
    resolve_action_notifications("dispatch_job", job_document["_id"], action_type="confirm_vehicle_return", completed_by=current_user_id)
    from services.dispatch_financial_service import ensure_dispatch_financial_record

    ensure_dispatch_financial_record(job_document=job_document)
    return {
        "detail": _build_return_detail(job_document),
        "reservation_release": {
            "vehicle_reservation_released": bool(job_document.get("vehicle_reservation_id")),
            "driver_reservation_released": bool(job_document.get("driver_reservation_id")),
        },
    }


def save_dispatch_return_inspection(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role not in {"owner", "admin", "dispatcher"}:
        raise ApiError("You do not have permission to inspect dispatch returns.", status_code=403)
    job_document = _get_dispatch_job_document(job_id)
    movement_document = _ensure_linked_vehicle_movement(job_document, current_user_id=current_user_id)
    if _derive_return_status(job_document, movement_document) not in {"returned", "inspection_completed"}:
        raise ApiError("Return must be confirmed before inspection can be completed.", status_code=400)
    vehicle_condition = _normalize_vehicle_condition((payload or {}).get("vehicle_condition"))
    accessories = _normalize_accessories((payload or {}).get("accessories"))
    warnings = _missing_accessory_warnings(accessories)
    linked_fault_id = _to_object_id((payload or {}).get("linked_fault_id"), "linked_fault_id", required=False)
    if linked_fault_id is not None:
        linked_fault_document = _get_fault_document(linked_fault_id)
        if linked_fault_document.get("vehicle_id") != job_document.get("vehicle_id"):
            raise ApiError("Linked fault must belong to the same vehicle.", status_code=400)
    timestamp = now_utc()
    actual_return_at = _coerce_utc_datetime(
        movement_document.get("actual_return_at") or movement_document.get("actual_return_time")
    )
    if actual_return_at is None:
        raise ApiError("The confirmed return time is unavailable. Confirm vehicle return again.", status_code=400)
    existing_checklist = movement_document.get("return_checklist") or job_document.get("return_checklist") or {}
    checklist = {
        **existing_checklist,
        "vehicle_id": str(job_document.get("vehicle_id")) if job_document.get("vehicle_id") else None,
        "driver_id": str(job_document.get("driver_id")) if job_document.get("driver_id") else None,
        "return_date": existing_checklist.get("return_date") or actual_return_at.date().isoformat(),
        "return_time": existing_checklist.get("return_time") or actual_return_at.strftime("%H:%M"),
        "actual_return_at": actual_return_at.isoformat(),
        "closing_odometer": _validate_non_negative_number((payload or {}).get("closing_odometer"), "closing_odometer"),
        "closing_fuel_level": _validate_fuel_level((payload or {}).get("closing_fuel_level"), "closing_fuel_level"),
        "vehicle_condition": vehicle_condition,
        "accessories": accessories,
        "existing_damage": _normalize_text((payload or {}).get("existing_damage")),
        "new_damage": _normalize_text((payload or {}).get("new_damage")),
        "driver_remarks": _normalize_text((payload or {}).get("driver_remarks")),
        "admin_remarks": _normalize_text((payload or {}).get("admin_remarks")),
        "photos": (payload or {}).get("photos") or [],
        "linked_fault_id": str(linked_fault_id) if linked_fault_id else None,
        "mark_vehicle_unavailable": bool((payload or {}).get("mark_vehicle_unavailable")),
        "warnings": warnings,
        "recorded_at": timestamp.isoformat(),
    }
    opening_odometer = movement_document.get("opening_odometer")
    if opening_odometer is not None and checklist["closing_odometer"] is not None and checklist["closing_odometer"] < opening_odometer:
        raise ApiError("closing_odometer must be greater than or equal to opening_odometer.", status_code=400)
    movement_update_fields = {
        "return_checklist": checklist,
        "closing_odometer": checklist["closing_odometer"] if checklist["closing_odometer"] is not None else movement_document.get("closing_odometer"),
        "closing_fuel_level": checklist["closing_fuel_level"] if checklist["closing_fuel_level"] is not None else movement_document.get("closing_fuel_level"),
        "updated_at": timestamp,
    }
    job_update_fields = {
        "return_status": "inspection_completed",
        "inspection_completed_at": timestamp,
        "inspection_completed_by": _to_object_id(current_user_id, "current_user_id"),
        "return_checklist": checklist,
        "linked_fault_id": linked_fault_id,
        "timeline": _append_timeline_entry(
            job_document,
            title="Return inspection completed",
            status="inspection_completed",
            event_type="return_inspection_completed",
            actor_id=current_user_id,
            note=checklist.get("admin_remarks") or checklist.get("new_damage"),
            timestamp=timestamp,
        ),
        "updated_at": timestamp,
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
    }
    vehicle_movements_collection().update_one({"_id": movement_document["_id"]}, {"$set": movement_update_fields})
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": job_update_fields})
    movement_document.update(movement_update_fields)
    job_document.update(job_update_fields)
    from services.dispatch_financial_service import ensure_dispatch_financial_record

    ensure_dispatch_financial_record(job_document=job_document)
    should_mark_unavailable = checklist["mark_vehicle_unavailable"] or vehicle_condition in {"damaged", "unsafe"} or bool(checklist.get("new_damage"))
    if isinstance(job_document.get("vehicle_id"), ObjectId):
        _set_vehicle_status(job_document["vehicle_id"], next_status="maintenance" if should_mark_unavailable else "available")
    return {"detail": _build_return_detail(job_document), "warnings": warnings}


def link_or_create_return_fault(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role not in {"owner", "admin", "dispatcher"}:
        raise ApiError("You do not have permission to manage dispatch return faults.", status_code=403)
    job_document = _get_dispatch_job_document(job_id)
    linked_fault_id = _to_object_id((payload or {}).get("fault_id"), "fault_id", required=False)
    created_fault = None
    if linked_fault_id is not None:
        fault_document = _get_fault_document(linked_fault_id)
        if fault_document.get("vehicle_id") != job_document.get("vehicle_id"):
            raise ApiError("Selected fault must belong to the same vehicle.", status_code=400)
    else:
        fault_payload = dict((payload or {}).get("fault_payload") or {})
        if not fault_payload:
            raise ApiError("fault_id or fault_payload is required.", status_code=400)
        fault_payload["vehicle_id"] = str(job_document.get("vehicle_id")) if job_document.get("vehicle_id") else None
        fault_payload["driver_id"] = str(job_document.get("driver_id")) if job_document.get("driver_id") else None
        created_fault = create_fault(fault_payload, current_user_id=current_user_id, current_role="admin")
        linked_fault_id = _to_object_id(created_fault.get("id"), "fault_id")
    timestamp = now_utc()
    dispatch_jobs_collection().update_one(
        {"_id": job_document["_id"]},
        {
            "$set": {
                "linked_fault_id": linked_fault_id,
                "updated_at": timestamp,
                "updated_by": _to_object_id(current_user_id, "current_user_id"),
            }
        },
    )
    job_document["linked_fault_id"] = linked_fault_id
    if isinstance(job_document.get("vehicle_id"), ObjectId) and bool((payload or {}).get("mark_vehicle_unavailable")):
        _set_vehicle_status(job_document["vehicle_id"], next_status="maintenance")
    return {
        "detail": _build_return_detail(job_document),
        "created_fault": created_fault,
    }


def close_dispatch_return(job_id: str, payload: dict | None = None, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role not in {"owner", "admin", "dispatcher"}:
        raise ApiError("You do not have permission to close dispatch returns.", status_code=403)
    job_document = _get_dispatch_job_document(job_id)
    if _normalize_return_status(job_document.get("return_status"), default="awaiting_return") != "inspection_completed":
        raise ApiError("Dispatch cannot be closed until the return inspection is complete.", status_code=400)
    movement_document = _ensure_linked_vehicle_movement(job_document, current_user_id=current_user_id)
    timestamp = now_utc()
    legacy_exception_reason = _normalize_text((payload or {}).get("legacy_fuel_exception_reason"))
    closing_confirmed = (
        movement_document.get("closing_fuel_recorded_at") is not None
        and movement_document.get("closing_fuel_level") is not None
    )
    opening_confirmed = (
        movement_document.get("opening_fuel_recorded_at") is not None
        and movement_document.get("opening_fuel_level") is not None
    )
    if not closing_confirmed and not (not opening_confirmed and legacy_exception_reason):
        raise ApiError(
            "Record closing fuel level before closing this dispatch.",
            status_code=400,
        )
    fuel_summary_status = "complete"
    fuel_exception_audit = None
    if not opening_confirmed:
        if not legacy_exception_reason:
            raise ApiError(
                "Opening fuel was not recorded for this legacy dispatch. Provide an authorized fuel exception reason to close it.",
                status_code=400,
            )
        fuel_summary_status = "legacy_exception"
        fuel_exception_audit = {
            "changed_by": _to_object_id(current_user_id, "current_user_id"),
            "changed_at": timestamp,
            "previous_value": "opening_fuel_missing",
            "new_value": "authorized_legacy_completion",
            "reason": legacy_exception_reason,
        }
    movement_update_fields = {
        "status": "closed",
        "fuel_summary_status": fuel_summary_status,
        "closed_by": _to_object_id(current_user_id, "current_user_id"),
        "closed_at": timestamp,
        "updated_at": timestamp,
    }
    movement_update = {"$set": movement_update_fields}
    if fuel_exception_audit:
        movement_update["$push"] = {"fuel_correction_audit": fuel_exception_audit}
    job_update_fields = {
        "return_status": "dispatch_closed",
        "dispatch_closed_at": timestamp,
        "dispatch_closed_by": _to_object_id(current_user_id, "current_user_id"),
        "closure_note": _normalize_text((payload or {}).get("closure_note")) if payload else None,
        "timeline": _append_timeline_entry(
            job_document,
            title="Dispatch closed after return handover",
            status="dispatch_closed",
            event_type="dispatch_return_closed",
            actor_id=current_user_id,
            note=_normalize_text((payload or {}).get("closure_note")) if payload else None,
            timestamp=timestamp,
        ),
        "updated_at": timestamp,
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
    }
    vehicle_movements_collection().update_one({"_id": movement_document["_id"]}, movement_update)
    dispatch_jobs_collection().update_one({"_id": job_document["_id"]}, {"$set": job_update_fields})
    movement_document.update(movement_update_fields)
    job_document.update(job_update_fields)
    from services.dispatch_financial_service import ensure_dispatch_financial_record

    ensure_dispatch_financial_record(job_document=job_document)
    return {"detail": _build_return_detail(job_document)}
