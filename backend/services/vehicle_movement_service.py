from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from math import ceil
import re
from time import perf_counter
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.assignment import serialize_assignment
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from models.vehicle_movement import serialize_vehicle_movement
from utils.api_error import ApiError
from utils.fuel_levels import normalize_fuel_level_eighths
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.operational_request_types import PERSONAL_USE_TYPE, normalize_type_token, personal_use_query_values
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached
from services.notification_service import create_notification, notify_roles, resolve_action_notifications
from services.dispatch_planner_service import detect_dispatch_conflicts
from services.movement_source_service import (
    SOURCE_MANAGED_MOVEMENT_TYPES,
    SOURCE_OWNERSHIP_FIELDS,
    get_movement_source_ownership,
    source_ownership_error,
)
from services.vehicle_availability_service import resolve_driver_availability, resolve_vehicle_availability


ALLOWED_MOVEMENT_TYPES = {
    "customer_dispatch",
    PERSONAL_USE_TYPE,
    "fuel_purchase",
    "maintenance",
    "workshop",
    "maintenance_transport",
    "workshop_transport",
    "assignment_handover",
    "internal_company_delivery",
    "stock_transfer",
    "supplier_pickup",
    "stock_return",
    "fuel_station_visit",
    "compliance_inspection_visit",
    "administrative_errand",
    "vehicle_repositioning",
    "vehicle_transfer",
    "internal_company_movement",
    "emergency",
    "other",
}
ALLOWED_MOVEMENT_STATUSES = {
    "draft",
    "pending_approval",
    "approved",
    "checked_out",
    "in_progress",
    "returned",
    "closed",
    "cancelled",
}
OPEN_MOVEMENT_STATUSES = {
    "draft",
    "pending_approval",
    "approved",
    "checked_out",
    "in_progress",
}
DELIVERY_CONFIRMABLE_STATUSES = {"checked_out", "in_progress"}
ALLOWED_DELIVERY_STATUSES = {"pending", "delivered"}
LIST_PROJECTION = {
    "movement_id": 1,
    "source_type": 1,
    "source_id": 1,
    "source_key": 1,
    "source_module": 1,
    "source_reference": 1,
    "vehicle_id": 1,
    "driver_id": 1,
    "movement_custodian_id": 1,
    "custody_state": 1,
    "current_custody_location": 1,
    "custody_version": 1,
    "pending_custody_transfer": 1,
    "permanent_driver_id": 1,
    "maintenance_job_id": 1,
    "preventive_schedule_id": 1,
    "maintenance_assignee_id": 1,
    "assignment_id": 1,
    "primary_assignment_id": 1,
    "dispatch_job_id": 1,
    "dispatch_request_id": 1,
    "reservation_id": 1,
    "stock_transfer_id": 1,
    "operation_request_id": 1,
    "related_source_type": 1,
    "related_source_id": 1,
    "movement_type": 1,
    "movement_category": 1,
    "financial_class": 1,
    "journey_mode": 1,
    "planned_stops": 1,
    "status": 1,
    "requested_departure_time": 1,
    "actual_departure_at": 1,
    "departure_time": 1,
    "expected_return_time": 1,
    "actual_return_time": 1,
    "origin": 1,
    "destination": 1,
    "origin_location_id": 1,
    "destination_location_id": 1,
    "origin_snapshot": 1,
    "destination_snapshot": 1,
    "purpose": 1,
    "opening_odometer": 1,
    "closing_odometer": 1,
    "opening_fuel_level": 1,
    "closing_fuel_level": 1,
    "delivery_status": 1,
    "custodian_response_status": 1,
    "completion_status": 1,
    "delivered_at": 1,
    "created_by": 1,
    "approved_by": 1,
    "checked_out_by": 1,
    "returned_by": 1,
    "closed_by": 1,
    "created_at": 1,
    "started_at": 1,
    "completed_at": 1,
    "updated_at": 1,
}
DETAIL_PROJECTION = {
    **LIST_PROJECTION,
    "delivery_note": 1,
    "delivered_by": 1,
    "notes": 1,
    "instructions": 1,
    "custodian_response_reason": 1,
    "workshop_name": 1,
    "mechanic_name": 1,
    "work_performed": 1,
    "parts_changed": 1,
    "test_result": 1,
    "cancellation_reason": 1,
    "approved_by": 1,
    "approved_at": 1,
    "checked_out_by": 1,
    "checked_out_at": 1,
    "returned_by": 1,
    "returned_at": 1,
    "closed_by": 1,
    "closed_at": 1,
    "opening_fuel_recorded_at": 1,
    "opening_fuel_recorded_by": 1,
    "opening_fuel_photo": 1,
    "opening_inspection_note": 1,
    "closing_fuel_recorded_at": 1,
    "closing_fuel_recorded_by": 1,
    "total_fuel_litres_added": 1,
    "total_fuel_cost": 1,
    "estimated_fuel_consumed": 1,
    "estimated_fuel_efficiency": 1,
    "distance_travelled": 1,
    "duration_minutes": 1,
    "late_return": 1,
    "fuel_difference": 1,
    "fuel_summary_status": 1,
    "custody_events": 1,
    "physical_completion_status": 1,
    "handover_kind": 1,
    "handover_sequence": 1,
    "transport_direction": 1,
    "transport_mode": 1,
    "opening_condition_summary": 1,
    "closing_condition_summary": 1,
    "status_history": 1,
    "audit_log": 1,
}
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
DRIVER_PATCHABLE_FIELDS = {"notes"}
ADMIN_PATCHABLE_FIELDS = {
    "vehicle_id",
    "driver_id",
    "movement_custodian_id",
    "maintenance_job_id",
    "preventive_schedule_id",
    "maintenance_assignee_id",
    "assignment_id",
    "primary_assignment_id",
    "dispatch_job_id",
    "dispatch_request_id",
    "reservation_id",
    "movement_type",
    "requested_departure_time",
    "departure_time",
    "expected_return_time",
    "actual_return_time",
    "origin",
    "destination",
    "purpose",
    "instructions",
    "workshop_name",
    "mechanic_name",
    "work_performed",
    "parts_changed",
    "test_result",
    "opening_odometer",
    "closing_odometer",
    "opening_fuel_level",
    "closing_fuel_level",
    "notes",
    "cancellation_reason",
}


def now_utc():
    return datetime.now(timezone.utc)


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def resource_reservations_collection():
    return get_collection("resource_reservations")


def assignments_collection():
    return get_collection("assignments")


def dispatch_jobs_collection():
    return get_collection("dispatch_jobs")


def ensure_vehicle_movement_indexes():
    ensure_indexes_for_collection(
        vehicle_movements_collection(),
        [
            {"keys": [("movement_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("movement_custodian_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("custody_state", ASCENDING), ("status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("custody_events.event_key", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("permanent_driver_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("maintenance_job_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("assignment_id", ASCENDING)], "options": {"sparse": True}},
            {
                "keys": [("source_key", ASCENDING)],
                "options": {
                    "name": "source_key_unique",
                    "unique": True,
                    "partialFilterExpression": {"source_key": {"$type": "string"}},
                },
            },
            {
                "keys": [("source_type", ASCENDING), ("dispatch_job_id", ASCENDING)],
                "options": {
                    "name": "dispatch_job_id_source_unique",
                    "unique": True,
                    "partialFilterExpression": {
                        "source_type": "dispatch_job",
                        "dispatch_job_id": {"$type": "objectId"},
                    },
                },
            },
            {"keys": [("status", ASCENDING)]},
            {"keys": [("movement_type", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("requested_departure_time", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("expected_return_time", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("expected_return_time", ASCENDING)]},
            {"keys": [("source_type", ASCENDING), ("source_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("movement_type", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("delivery_status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("completion_status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("custodian_response_status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("delivered_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("driver_id", ASCENDING), ("delivery_status", ASCENDING), ("updated_at", DESCENDING)], "options": {"sparse": True}},
            {
                "keys": [("vehicle_id", ASCENDING)],
                "options": {
                    "name": "vehicle_id_open_movement_unique",
                    "unique": True,
                    "partialFilterExpression": {
                        "status": {"$in": sorted(OPEN_MOVEMENT_STATUSES)},
                    },
                },
            },
        ],
        collection_name="vehicle_movements",
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


def _validate_status(value: str | None) -> str:
    normalized = _normalize_text(value) or "draft"
    if normalized not in ALLOWED_MOVEMENT_STATUSES:
        raise ApiError("Invalid vehicle movement status.", status_code=400)
    return normalized


def _validate_movement_type(value: str | None) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        raise ApiError("movement_type is required.", status_code=400)
    normalized = normalize_type_token(normalized)
    if normalized not in ALLOWED_MOVEMENT_TYPES:
        raise ApiError("Invalid vehicle movement type.", status_code=400)
    return normalized


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


def _validate_non_negative_number(value, field_name: str):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _validate_fuel_level(value, field_name: str):
    normalized, error_message = normalize_fuel_level_eighths(value)
    if normalized is None and value not in (None, ""):
        raise ApiError(
            error_message or f"{field_name} must be a fuel level between 0/8 and 8/8.",
            status_code=400,
        )
    return normalized


def _validate_delivery_status(value: str | None) -> str:
    normalized = _normalize_text(value) or "pending"
    normalized = normalized.lower()
    if normalized not in ALLOWED_DELIVERY_STATUSES:
        raise ApiError("Invalid delivery status.", status_code=400)
    return normalized


def _serialize_summary_datetime(value: datetime | None):
    return value.isoformat() if value else None


def _vehicle_movement_scope_query(*, current_user_id: str, current_role: str) -> dict:
    if current_role in {"owner", "admin"}:
        return {}
    if current_role != "driver":
        raise ApiError("You do not have permission to access vehicle movements.", status_code=403)
    user_id = _to_object_id(current_user_id, "current_user_id")
    return {"$or": [{"driver_id": user_id}, {"movement_custodian_id": user_id}, {"permanent_driver_id": user_id}]}


def _get_vehicle_document(vehicle_id) -> dict:
    vehicle = vehicles_collection().find_one({"_id": _to_object_id(vehicle_id, "vehicle_id")})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _get_driver_document(driver_id) -> dict:
    driver = users_collection().find_one({"_id": _to_object_id(driver_id, "driver_id"), "role": "driver"})
    if not driver:
        raise ApiError("Driver not found.", status_code=404)
    if driver.get("status") != "active":
        raise ApiError("Driver must be active to be assigned to a movement.", status_code=400)
    approval_status = ((driver.get("driver_profile") or {}).get("approval_status") or "").strip().lower()
    if approval_status and approval_status != "approved":
        raise ApiError("Driver must be approved before being assigned to a movement.", status_code=400)
    profile = driver.get("driver_profile") or {}
    licence_expiry = profile.get("license_expiry")
    if licence_expiry:
        try:
            expiry_date = date.fromisoformat(str(licence_expiry)[:10])
        except ValueError as error:
            raise ApiError("Driver licence expiry is invalid.", status_code=400) from error
        if expiry_date < date.today():
            raise ApiError("Driver licence has expired.", status_code=400)
    return driver


def _get_assignment_document(assignment_id) -> dict:
    assignment = assignments_collection().find_one({"_id": _to_object_id(assignment_id, "assignment_id")})
    if not assignment:
        raise ApiError("Assignment not found.", status_code=404)
    return assignment


def _get_vehicle_movement_document(movement_id: str, *, projection: dict | None = None) -> dict:
    if not ObjectId.is_valid(movement_id):
        raise ApiError("Vehicle movement not found.", status_code=404)
    document = vehicle_movements_collection().find_one({"_id": ObjectId(movement_id)}, projection)
    if not document:
        raise ApiError("Vehicle movement not found.", status_code=404)
    return document


def _assert_vehicle_movement_access(document: dict, *, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    if current_role == "dispatcher" and document.get("movement_type") == "customer_dispatch":
        return
    if current_role != "driver":
        raise ApiError("You do not have permission to access vehicle movements.", status_code=403)
    user_id = _to_object_id(current_user_id, "current_user_id")
    if user_id not in {document.get("driver_id"), document.get("movement_custodian_id"), document.get("permanent_driver_id")}:
        raise ApiError("You do not have permission to access this vehicle movement.", status_code=403)


def _assert_vehicle_movement_mutation_access(document: dict, *, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    if current_role == "dispatcher" and document.get("movement_type") == "customer_dispatch":
        return
    if current_role != "driver":
        raise ApiError("You do not have permission to modify vehicle movements.", status_code=403)
    user_id = _to_object_id(current_user_id, "current_user_id")
    if user_id not in {document.get("driver_id"), document.get("movement_custodian_id")}:
        raise ApiError("You do not have permission to modify this vehicle movement.", status_code=403)


def _build_document_lookup(collection, ids: set[ObjectId], projection: dict) -> dict[ObjectId, dict]:
    if not ids:
        return {}
    return {
        document["_id"]: document
        for document in collection.find({"_id": {"$in": list(ids)}}, projection)
    }


def _load_related_maps(movement_documents: list[dict]) -> dict[str, dict[ObjectId, dict]]:
    user_ids = {
        value
        for document in movement_documents
        for value in (
            document.get("driver_id"),
            document.get("movement_custodian_id"),
            document.get("permanent_driver_id"),
            document.get("maintenance_assignee_id"),
            document.get("created_by"),
            document.get("approved_by"),
            document.get("checked_out_by"),
            document.get("returned_by"),
            document.get("closed_by"),
            document.get("delivered_by"),
        )
        if isinstance(value, ObjectId)
    }
    vehicle_ids = {
        document.get("vehicle_id")
        for document in movement_documents
        if isinstance(document.get("vehicle_id"), ObjectId)
    }
    assignment_ids = {
        document.get("assignment_id")
        for document in movement_documents
        if isinstance(document.get("assignment_id"), ObjectId)
    }
    assignment_ids.update(
        document.get("primary_assignment_id")
        for document in movement_documents
        if isinstance(document.get("primary_assignment_id"), ObjectId)
    )
    dispatch_job_ids = {
        document.get("dispatch_job_id")
        for document in movement_documents
        if isinstance(document.get("dispatch_job_id"), ObjectId)
    }
    with ThreadPoolExecutor(max_workers=3) as executor:
        users_future = executor.submit(_build_document_lookup, users_collection(), user_ids, USER_SUMMARY_PROJECTION)
        vehicles_future = executor.submit(_build_document_lookup, vehicles_collection(), vehicle_ids, VEHICLE_SUMMARY_PROJECTION)
        assignments_future = executor.submit(_build_document_lookup, assignments_collection(), assignment_ids, ASSIGNMENT_SUMMARY_PROJECTION)
        jobs_lookup = _build_document_lookup(
            dispatch_jobs_collection(),
            dispatch_job_ids,
            {"dispatch_request_id": 1, "primary_assignment_id": 1},
        )
        return {
            "users": users_future.result(),
            "vehicles": vehicles_future.result(),
            "assignments": assignments_future.result(),
            "jobs": jobs_lookup,
        }


def _enrich_vehicle_movement(
    movement_document: dict,
    *,
    user_lookup: dict[ObjectId, dict] | None = None,
    vehicle_lookup: dict[ObjectId, dict] | None = None,
    assignment_lookup: dict[ObjectId, dict] | None = None,
    job_lookup: dict[ObjectId, dict] | None = None,
) -> dict:
    payload = serialize_vehicle_movement(movement_document)
    job_document = (job_lookup or {}).get(movement_document.get("dispatch_job_id"))
    if payload.get("dispatch_request_id") is None and job_document and isinstance(job_document.get("dispatch_request_id"), ObjectId):
        payload["dispatch_request_id"] = str(job_document["dispatch_request_id"])
    if payload.get("primary_assignment_id") is None and job_document and isinstance(job_document.get("primary_assignment_id"), ObjectId):
        payload["primary_assignment_id"] = str(job_document["primary_assignment_id"])
    vehicle_document = (vehicle_lookup or {}).get(movement_document.get("vehicle_id"))
    driver_document = (user_lookup or {}).get(movement_document.get("driver_id"))
    custodian_document = (user_lookup or {}).get(movement_document.get("movement_custodian_id") or movement_document.get("driver_id"))
    permanent_driver_document = (user_lookup or {}).get(movement_document.get("permanent_driver_id"))
    maintenance_assignee_document = (user_lookup or {}).get(movement_document.get("maintenance_assignee_id"))
    assignment_document = (assignment_lookup or {}).get(movement_document.get("assignment_id"))
    primary_assignment_id = movement_document.get("primary_assignment_id") or (job_document or {}).get("primary_assignment_id")
    primary_assignment_document = (assignment_lookup or {}).get(primary_assignment_id)
    created_by_document = (user_lookup or {}).get(movement_document.get("created_by"))
    approved_by_document = (user_lookup or {}).get(movement_document.get("approved_by"))
    checked_out_by_document = (user_lookup or {}).get(movement_document.get("checked_out_by"))
    returned_by_document = (user_lookup or {}).get(movement_document.get("returned_by"))
    closed_by_document = (user_lookup or {}).get(movement_document.get("closed_by"))
    delivered_by_document = (user_lookup or {}).get(movement_document.get("delivered_by"))

    payload["vehicle"] = serialize_vehicle(vehicle_document, include_sensitive=False) if vehicle_document else None
    payload["driver"] = serialize_user(driver_document) if driver_document else None
    payload["movement_custodian"] = serialize_user(custodian_document) if custodian_document else None
    payload["permanent_driver"] = serialize_user(permanent_driver_document) if permanent_driver_document else None
    payload["maintenance_assignee"] = serialize_user(maintenance_assignee_document) if maintenance_assignee_document else None
    payload["assignment"] = serialize_assignment(assignment_document) if assignment_document else None
    payload["primary_assignment"] = serialize_assignment(primary_assignment_document) if primary_assignment_document else None
    payload["created_by_user"] = serialize_user(created_by_document) if created_by_document else None
    payload["approved_by_user"] = serialize_user(approved_by_document) if approved_by_document else None
    payload["checked_out_by_user"] = serialize_user(checked_out_by_document) if checked_out_by_document else None
    payload["returned_by_user"] = serialize_user(returned_by_document) if returned_by_document else None
    payload["closed_by_user"] = serialize_user(closed_by_document) if closed_by_document else None
    payload["delivered_by_user"] = serialize_user(delivered_by_document) if delivered_by_document else None
    return payload


def _batch_enrich_vehicle_movements(movement_documents: list[dict]) -> list[dict]:
    if not movement_documents:
        return []
    related = _load_related_maps(movement_documents)
    return [
        _enrich_vehicle_movement(
            movement_document,
            user_lookup=related["users"],
            vehicle_lookup=related["vehicles"],
            assignment_lookup=related["assignments"],
            job_lookup=related["jobs"],
        )
        for movement_document in movement_documents
    ]


def _generate_movement_id() -> str:
    timestamp = now_utc().strftime("%Y%m%d%H%M%S")
    return f"VM-{timestamp}-{uuid4().hex[:6].upper()}"


def _resolve_movement_times(document: dict) -> tuple[datetime | None, datetime | None, datetime | None]:
    requested_departure_time = _parse_datetime(document.get("requested_departure_time"), "requested_departure_time")
    departure_time = _parse_datetime(document.get("departure_time"), "departure_time")
    expected_return_time = _parse_datetime(document.get("expected_return_time"), "expected_return_time")
    return requested_departure_time, departure_time, expected_return_time


def _validate_time_relationships(document: dict):
    requested_departure_time, departure_time, expected_return_time = _resolve_movement_times(document)
    reference_departure_time = departure_time or requested_departure_time
    if reference_departure_time is None:
        raise ApiError("departure_time or requested_departure_time is required.", status_code=400)
    if expected_return_time and expected_return_time <= reference_departure_time:
        raise ApiError("expected_return_time must be after the departure time.", status_code=400)
    actual_return_time = _parse_datetime(document.get("actual_return_time"), "actual_return_time")
    if actual_return_time and departure_time and actual_return_time <= departure_time:
        raise ApiError("actual_return_time must be after departure_time.", status_code=400)
    if actual_return_time and not departure_time:
        raise ApiError("departure_time is required before setting actual_return_time.", status_code=400)


def _validate_odometer_relationships(document: dict):
    opening_odometer = document.get("opening_odometer")
    closing_odometer = document.get("closing_odometer")
    if (
        opening_odometer is not None
        and closing_odometer is not None
        and closing_odometer < opening_odometer
    ):
        raise ApiError("closing_odometer cannot be lower than opening_odometer.", status_code=400)


def _assert_vehicle_is_not_blocked(vehicle_id: ObjectId, *, exclude_movement_id: ObjectId | None = None, exclude_reservation_id: ObjectId | None = None, source_type: str | None = None):
    availability = resolve_vehicle_availability(
        vehicle_id,
        context={"movement_type": source_type, "exclude_movement_id": exclude_movement_id, "exclude_reservation_id": exclude_reservation_id},
    )
    allowed_codes = set()
    if source_type in {"maintenance", "workshop", "maintenance_transport", "workshop_transport"}:
        allowed_codes.add("active_maintenance_job")
    if source_type == "customer_dispatch":
        allowed_codes.add("active_dispatch")
    if source_type == "compliance_inspection_visit":
        # The source workflow already validated that the linked compliance
        # record belongs to this vehicle before movement creation.
        allowed_codes.add("expired_mandatory_compliance")
    for reason in availability.get("blocking_reasons", []):
        if reason.get("code") not in allowed_codes:
            raise ApiError(reason.get("message") or "Vehicle is unavailable for movement.", status_code=409)
    query = {
        "vehicle_id": vehicle_id,
        "status": {"$in": sorted(OPEN_MOVEMENT_STATUSES)},
    }
    if exclude_movement_id is not None:
        query["_id"] = {"$ne": exclude_movement_id}
    existing = vehicle_movements_collection().find_one(query, {"_id": 1, "movement_id": 1, "status": 1})
    if existing:
        raise ApiError(
            f"Vehicle already has an open movement ({existing.get('movement_id') or 'unknown'}).",
            status_code=409,
        )


def _assert_driver_is_not_blocked(document: dict):
    driver_id = document.get("driver_id")
    if not isinstance(driver_id, ObjectId):
        return
    availability = resolve_driver_availability(driver_id, context={
        "exclude_movement_id": document.get("_id"),
        "exclude_reservation_id": document.get("reservation_id"),
        "exclude_dispatch_job_id": document.get("dispatch_job_id"),
    })
    if not availability.get("is_available"):
        raise ApiError(availability.get("primary_reason") or "Driver is unavailable for movement.", status_code=409)


def _normalize_vehicle_movement_payload(payload: dict, *, partial: bool = False) -> dict:
    normalized: dict = {}
    if "vehicle_id" in payload or not partial:
        normalized["vehicle_id"] = _to_object_id(payload.get("vehicle_id"), "vehicle_id", required=not partial)
    if "driver_id" in payload:
        normalized["driver_id"] = _to_object_id(payload.get("driver_id"), "driver_id", required=False)
    elif "movement_custodian_id" in payload:
        normalized["driver_id"] = _to_object_id(payload.get("movement_custodian_id"), "movement_custodian_id", required=False)
    elif not partial:
        normalized["driver_id"] = None
    for field_name in ("maintenance_job_id", "preventive_schedule_id", "maintenance_assignee_id"):
        if field_name in payload:
            normalized[field_name] = _to_object_id(payload.get(field_name), field_name, required=False)
        elif not partial:
            normalized[field_name] = None
    if "assignment_id" in payload:
        normalized["assignment_id"] = _to_object_id(payload.get("assignment_id"), "assignment_id", required=False)
    elif not partial:
        normalized["assignment_id"] = None
    if "primary_assignment_id" in payload:
        normalized["primary_assignment_id"] = _to_object_id(payload.get("primary_assignment_id"), "primary_assignment_id", required=False)
    elif not partial:
        normalized["primary_assignment_id"] = None
    if "dispatch_job_id" in payload:
        normalized["dispatch_job_id"] = _to_object_id(payload.get("dispatch_job_id"), "dispatch_job_id", required=False)
    elif not partial:
        normalized["dispatch_job_id"] = None
    if "dispatch_request_id" in payload:
        normalized["dispatch_request_id"] = _to_object_id(payload.get("dispatch_request_id"), "dispatch_request_id", required=False)
    elif not partial:
        normalized["dispatch_request_id"] = None
    if "reservation_id" in payload:
        normalized["reservation_id"] = _to_object_id(payload.get("reservation_id"), "reservation_id", required=False)
    elif not partial:
        normalized["reservation_id"] = None
    if "movement_type" in payload or not partial:
        normalized["movement_type"] = _validate_movement_type(payload.get("movement_type"))
    if "status" in payload or not partial:
        normalized["status"] = _validate_status(payload.get("status"))
    if "requested_departure_time" in payload or not partial:
        normalized["requested_departure_time"] = _parse_datetime(
            payload.get("requested_departure_time"),
            "requested_departure_time",
            required=False,
        )
    if "departure_time" in payload or not partial:
        normalized["departure_time"] = _parse_datetime(payload.get("departure_time"), "departure_time", required=False)
    if "expected_return_time" in payload or not partial:
        normalized["expected_return_time"] = _parse_datetime(
            payload.get("expected_return_time"),
            "expected_return_time",
            required=False,
        )
    if "actual_return_time" in payload or not partial:
        normalized["actual_return_time"] = _parse_datetime(
            payload.get("actual_return_time"),
            "actual_return_time",
            required=False,
        )
    for field_name in ("origin", "destination", "purpose", "notes", "cancellation_reason", "instructions", "workshop_name", "mechanic_name", "work_performed", "test_result"):
        if field_name in payload:
            normalized[field_name] = _normalize_text(payload.get(field_name))
        elif not partial:
            normalized[field_name] = None
    if "parts_changed" in payload:
        parts = payload.get("parts_changed")
        if isinstance(parts, str):
            parts = [item.strip() for item in parts.split(",") if item.strip()]
        if parts is not None and not isinstance(parts, list):
            raise ApiError("parts_changed must be a string or list.", status_code=400)
        normalized["parts_changed"] = parts or None
    elif not partial:
        normalized["parts_changed"] = None
    for field_name in ("opening_odometer", "closing_odometer"):
        if field_name in payload:
            normalized[field_name] = _validate_non_negative_number(payload.get(field_name), field_name)
        elif not partial:
            normalized[field_name] = None
    for field_name in ("opening_fuel_level", "closing_fuel_level"):
        if field_name in payload:
            normalized[field_name] = _validate_fuel_level(payload.get(field_name), field_name)
        elif not partial:
            normalized[field_name] = None
    return {key: value for key, value in normalized.items() if partial or value is not None or key in {"driver_id", "assignment_id", "primary_assignment_id", "dispatch_job_id", "dispatch_request_id", "reservation_id", "notes", "origin", "destination", "purpose", "cancellation_reason", "requested_departure_time", "departure_time", "expected_return_time", "actual_return_time", "opening_odometer", "closing_odometer", "opening_fuel_level", "closing_fuel_level"}}


def _validate_relationships(document: dict):
    vehicle = _get_vehicle_document(document.get("vehicle_id"))
    driver = None
    assignment = None
    if document.get("driver_id"):
        driver = _get_driver_document(document.get("driver_id"))
    if document.get("assignment_id"):
        assignment = _get_assignment_document(document.get("assignment_id"))
    primary_assignment = None
    if document.get("primary_assignment_id"):
        primary_assignment = (
            assignment
            if assignment and assignment.get("_id") == document.get("primary_assignment_id")
            else _get_assignment_document(document.get("primary_assignment_id"))
        )
    if assignment:
        if assignment.get("vehicle_id") != vehicle["_id"]:
            raise ApiError("assignment_id does not belong to the selected vehicle.", status_code=400)
        if not driver and assignment.get("driver_id"):
            driver = _get_driver_document(str(assignment.get("driver_id")))
        if driver and assignment.get("driver_id") != driver["_id"]:
            raise ApiError("assignment_id does not belong to the selected driver.", status_code=400)
    if primary_assignment:
        if primary_assignment.get("vehicle_id") != vehicle["_id"]:
            raise ApiError("primary_assignment_id does not belong to the selected vehicle.", status_code=400)
        if driver and primary_assignment.get("driver_id") != driver["_id"]:
            raise ApiError("primary_assignment_id does not belong to the selected driver.", status_code=400)
    dispatch_job = None
    if document.get("dispatch_job_id"):
        dispatch_job = dispatch_jobs_collection().find_one(
            {"_id": document["dispatch_job_id"]},
            {
                "vehicle_id": 1,
                "driver_id": 1,
                "dispatch_request_id": 1,
                "primary_assignment_id": 1,
                "vehicle_reservation_id": 1,
            },
        )
        if not dispatch_job:
            raise ApiError("Dispatch job not found.", status_code=404)
        if dispatch_job.get("vehicle_id") != vehicle["_id"]:
            raise ApiError("dispatch_job_id does not belong to the selected vehicle.", status_code=400)
        if driver and dispatch_job.get("driver_id") != driver["_id"]:
            raise ApiError("dispatch_job_id does not belong to the selected driver.", status_code=400)
        for movement_field, job_field in (
            ("dispatch_request_id", "dispatch_request_id"),
            ("primary_assignment_id", "primary_assignment_id"),
            ("reservation_id", "vehicle_reservation_id"),
        ):
            if document.get(movement_field) and dispatch_job.get(job_field) != document.get(movement_field):
                raise ApiError(f"{movement_field} does not belong to the selected dispatch job.", status_code=400)
    if document.get("dispatch_request_id"):
        request_document = get_collection("dispatch_requests").find_one(
            {"_id": document["dispatch_request_id"]},
            {"_id": 1},
        )
        if not request_document:
            raise ApiError("Dispatch request not found.", status_code=404)
    if document.get("reservation_id"):
        reservation = resource_reservations_collection().find_one(
            {"_id": document["reservation_id"]},
            {"resource_id": 1, "dispatch_job_id": 1},
        )
        if not reservation:
            raise ApiError("Reservation not found.", status_code=404)
        if reservation.get("resource_id") != vehicle["_id"]:
            raise ApiError("reservation_id does not belong to the selected vehicle.", status_code=400)
        if dispatch_job and reservation.get("dispatch_job_id") != dispatch_job["_id"]:
            raise ApiError("reservation_id does not belong to the selected dispatch job.", status_code=400)
    if document.get("maintenance_job_id"):
        job = maintenance_jobs_collection().find_one({"_id": document["maintenance_job_id"]}, {"vehicle_id": 1, "preventive_schedule_id": 1, "maintenance_coordinator_id": 1})
        if not job:
            raise ApiError("Maintenance job not found.", status_code=404)
        if job.get("vehicle_id") != vehicle["_id"]:
            raise ApiError("maintenance_job_id does not belong to the selected vehicle.", status_code=400)
        if not document.get("preventive_schedule_id"):
            document["preventive_schedule_id"] = job.get("preventive_schedule_id")
        if not document.get("maintenance_assignee_id"):
            document["maintenance_assignee_id"] = job.get("maintenance_coordinator_id")
    return vehicle, driver, assignment


def _notify_movement_participants(document: dict, *, event: str, message: str, actionable_for_custodian: bool = False):
    recipients: dict[ObjectId, str] = {}
    custodian_id = document.get("movement_custodian_id") or document.get("driver_id")
    permanent_driver_id = document.get("permanent_driver_id")
    if isinstance(custodian_id, ObjectId):
        recipients[custodian_id] = "action" if actionable_for_custodian else "visibility"
    if isinstance(permanent_driver_id, ObjectId):
        recipients.setdefault(permanent_driver_id, "visibility")
    for recipient_id, recipient_kind in recipients.items():
        title = f"Maintenance movement {event}"
        if recipient_kind == "action" and recipient_id == permanent_driver_id:
            title = f"Maintenance movement {event} - action required"
        create_notification(
            recipient_user_id=recipient_id,
            title=title,
            message=message,
            category="maintenance",
            priority="high" if actionable_for_custodian and recipient_id == custodian_id else "medium",
            reference_type="vehicle_movement",
            reference_id=document["_id"],
            action_type="resubmit_maintenance_completion" if actionable_for_custodian and recipient_id == custodian_id else None,
            action_url="my-vehicle" if actionable_for_custodian and recipient_id == custodian_id else None,
            action_label="Correct and resubmit" if actionable_for_custodian and recipient_id == custodian_id else None,
        )


def list_vehicle_movements(
    *,
    current_user_id: str,
    current_role: str,
    page: int = 1,
    page_size: int = 25,
    vehicle_id: str | None = None,
    driver_id: str | None = None,
    branch_id: str | None = None,
    status: str | None = None,
    movement_type: str | None = None,
    search_query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    request_started_at = perf_counter()
    normalized_role = _normalize_role(current_role) or current_role
    query = _vehicle_movement_scope_query(current_user_id=current_user_id, current_role=normalized_role)
    if vehicle_id:
        query["vehicle_id"] = _to_object_id(vehicle_id, "vehicle_id")
    if driver_id:
        driver_object_id = _to_object_id(driver_id, "driver_id")
        if normalized_role == "driver" and driver_object_id != _to_object_id(current_user_id, "current_user_id"):
            raise ApiError("Drivers can only view their own vehicle movements.", status_code=403)
        query["driver_id"] = driver_object_id
    if branch_id:
        branch_object_id = _to_object_id(branch_id, "branch_id")
        branch_vehicle_ids = [item["_id"] for item in vehicles_collection().find(
            {"$or": [{"branch_id": branch_object_id}, {"primary_branch_id": branch_object_id}, {"home_branch_id": branch_object_id}]},
            {"_id": 1},
        )]
        if vehicle_id and _to_object_id(vehicle_id, "vehicle_id") not in branch_vehicle_ids:
            query["vehicle_id"] = {"$in": []}
        elif not vehicle_id:
            query["vehicle_id"] = {"$in": branch_vehicle_ids}
    if status:
        normalized_status = _validate_status(status)
        query["status"] = normalized_status
    if movement_type:
        normalized_movement_type = _validate_movement_type(movement_type)
        query["movement_type"] = (
            {"$in": personal_use_query_values()}
            if normalized_movement_type == PERSONAL_USE_TYPE
            else normalized_movement_type
        )
    normalized_search_query = _normalize_text(search_query)
    if normalized_search_query:
        escaped_search = re.escape(normalized_search_query)
        query["$or"] = [
            {"movement_id": {"$regex": escaped_search, "$options": "i"}},
            {"origin": {"$regex": escaped_search, "$options": "i"}},
            {"destination": {"$regex": escaped_search, "$options": "i"}},
            {"purpose": {"$regex": escaped_search, "$options": "i"}},
            {"notes": {"$regex": escaped_search, "$options": "i"}},
        ]
    date_filters = {}
    if date_from:
        date_filters["$gte"] = _parse_datetime(date_from, "date_from")
    if date_to:
        date_filters["$lte"] = _parse_datetime(date_to, "date_to")
    if date_filters:
        date_query = [
            {"requested_departure_time": date_filters},
            {"departure_time": date_filters},
            {"created_at": date_filters},
        ]
        if "$or" in query:
            query["$and"] = [{"$or": query.pop("$or")}, {"$or": date_query}]
        else:
            query["$or"] = date_query

    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 25, 1), 100)
    skip = (normalized_page - 1) * normalized_page_size

    aggregate_started_at = perf_counter()
    pipeline = [
        {"$match": query},
        {
            "$facet": {
                "records": [
                    {"$sort": {"created_at": -1, "_id": -1}},
                    {"$skip": skip},
                    {"$limit": normalized_page_size},
                    {"$project": LIST_PROJECTION},
                ],
                "counts": [{"$count": "total"}],
            }
        },
    ]
    aggregate_result = list(vehicle_movements_collection().aggregate(pipeline))
    log_db_duration("vehicle_movements.list.aggregate", aggregate_started_at)
    aggregate_payload = aggregate_result[0] if aggregate_result else {}
    documents = aggregate_payload.get("records") or []
    total = int(((aggregate_payload.get("counts") or [{}])[0]).get("total") or 0)

    enrich_started_at = perf_counter()
    movements = _batch_enrich_vehicle_movements(documents)
    duration_ms = round((perf_counter() - enrich_started_at) * 1000, 2)
    if duration_ms > 250:
        from flask import current_app

        current_app.logger.warning("[Flux VehicleMovements] slow_section=list.enrich_page duration_ms=%.2f", duration_ms)

    return {
        "movements": movements,
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "filters": {
            "vehicle_id": vehicle_id,
            "driver_id": driver_id,
            "branch_id": branch_id,
            "status": status,
            "movement_type": movement_type,
            "q": search_query,
            "date_from": date_from,
            "date_to": date_to,
        },
        "generated_at": _serialize_summary_datetime(now_utc()),
        "duration_ms": round((perf_counter() - request_started_at) * 1000, 2),
    }


def get_vehicle_movement_by_id(movement_id: str, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    document = _get_vehicle_movement_document(movement_id, projection=DETAIL_PROJECTION)
    _assert_vehicle_movement_access(document, current_user_id=current_user_id, current_role=normalized_role)
    return _batch_enrich_vehicle_movements([document])[0]


def create_vehicle_movement(payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    if normalized_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to create vehicle movements.", status_code=403)

    request_payload = payload or {}
    normalized_payload = _normalize_vehicle_movement_payload(request_payload, partial=False)
    if normalized_payload["movement_type"] in SOURCE_MANAGED_MOVEMENT_TYPES:
        raise source_ownership_error(
            normalized_payload["movement_type"],
            code="source_managed_movement_required",
            message="Source-managed vehicle movements must be created by their owning module.",
            status_code=400,
        )
    protected_fields = sorted(SOURCE_OWNERSHIP_FIELDS.intersection(request_payload))
    if protected_fields:
        message = "Source ownership fields cannot be set through the generic Vehicle Movement API."
        raise ApiError(
            message,
            status_code=400,
            errors=[
                {
                    "code": "source_ownership_fields_forbidden",
                    "message": message,
                    "movement_type": normalized_payload["movement_type"],
                    "owning_module": None,
                    "fields": protected_fields,
                }
            ],
        )
    if normalized_payload["status"] not in {"draft", "pending_approval", "approved"}:
        raise ApiError(
            "New vehicle movements must start as draft, pending_approval, or approved.",
            status_code=400,
        )
    vehicle, driver, assignment = _validate_relationships(normalized_payload)
    _validate_time_relationships(normalized_payload)
    _validate_odometer_relationships(normalized_payload)
    if normalized_payload["status"] in OPEN_MOVEMENT_STATUSES:
        _assert_vehicle_is_not_blocked(vehicle["_id"], source_type=normalized_payload.get("movement_type"))
    movement_start = normalized_payload.get("departure_time") or normalized_payload.get("requested_departure_time")
    movement_end = normalized_payload.get("expected_return_time")
    if movement_start and movement_end and resource_reservations_collection().find_one({
        "reservation_type": "vehicle",
        "resource_id": vehicle["_id"],
        "status": {"$in": ["reserved", "consumed"]},
        "start_time": {"$lt": movement_end},
        "end_time": {"$gt": movement_start},
    }, {"_id": 1}):
        raise ApiError("Vehicle is reserved elsewhere during the selected time window.", status_code=409)
    if driver and normalized_payload.get("expected_return_time"):
        conflicts = detect_dispatch_conflicts(
            vehicle_id=None,
            driver_id=str(driver["_id"]),
            scheduled_start_time=normalized_payload.get("departure_time") or normalized_payload.get("requested_departure_time"),
            expected_return_time=normalized_payload.get("expected_return_time"),
        )
        if conflicts.get("driver_conflicts"):
            raise ApiError("; ".join(conflicts["driver_conflicts"]), status_code=409)

    timestamp = now_utc()
    document = {
        "movement_id": _generate_movement_id(),
        "vehicle_id": vehicle["_id"],
        "driver_id": driver["_id"] if driver else None,
        "movement_custodian_id": driver["_id"] if driver else None,
        "permanent_driver_id": vehicle.get("assigned_driver_id"),
        "maintenance_job_id": normalized_payload.get("maintenance_job_id"),
        "preventive_schedule_id": normalized_payload.get("preventive_schedule_id"),
        "maintenance_assignee_id": normalized_payload.get("maintenance_assignee_id"),
        "assignment_id": assignment["_id"] if assignment else None,
        "primary_assignment_id": normalized_payload.get("primary_assignment_id") or (assignment["_id"] if assignment else None),
        "dispatch_job_id": normalized_payload.get("dispatch_job_id"),
        "dispatch_request_id": normalized_payload.get("dispatch_request_id"),
        "reservation_id": normalized_payload.get("reservation_id"),
        "movement_type": normalized_payload["movement_type"],
        "status": normalized_payload["status"],
        "requested_departure_time": normalized_payload.get("requested_departure_time"),
        "departure_time": normalized_payload.get("departure_time"),
        "expected_return_time": normalized_payload.get("expected_return_time"),
        "actual_return_time": normalized_payload.get("actual_return_time"),
        "origin": normalized_payload.get("origin"),
        "destination": normalized_payload.get("destination"),
        "purpose": normalized_payload.get("purpose"),
        "instructions": normalized_payload.get("instructions"),
        "workshop_name": normalized_payload.get("workshop_name"),
        "mechanic_name": normalized_payload.get("mechanic_name"),
        "work_performed": normalized_payload.get("work_performed"),
        "parts_changed": normalized_payload.get("parts_changed"),
        "test_result": normalized_payload.get("test_result"),
        "custodian_response_status": "pending" if driver and normalized_payload["movement_type"] in {"maintenance", "workshop"} else None,
        "custodian_response_reason": None,
        "completion_status": None,
        "opening_odometer": normalized_payload.get("opening_odometer"),
        "closing_odometer": normalized_payload.get("closing_odometer"),
        "opening_fuel_level": normalized_payload.get("opening_fuel_level"),
        "closing_fuel_level": normalized_payload.get("closing_fuel_level"),
        "delivery_status": "pending" if normalized_payload["movement_type"] == "customer_dispatch" else None,
        "delivered_at": None,
        "delivery_note": None,
        "delivered_by": None,
        "notes": normalized_payload.get("notes"),
        "cancellation_reason": normalized_payload.get("cancellation_reason"),
        "approved_by": _to_object_id(current_user_id, "current_user_id") if normalized_payload["status"] == "approved" else None,
        "approved_at": timestamp if normalized_payload["status"] == "approved" else None,
        "checked_out_by": None,
        "checked_out_at": None,
        "returned_by": None,
        "returned_at": None,
        "closed_by": None,
        "closed_at": None,
        "created_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        result = vehicle_movements_collection().insert_one(document)
    except DuplicateKeyError:
        raise ApiError("Vehicle already has another open movement.", status_code=409) from None
    document["_id"] = result.inserted_id
    if document.get("movement_type") in {"maintenance", "workshop"}:
        _notify_movement_participants(
            document,
            event="assigned",
            message=f"A {document.get('movement_type')} movement was created for {vehicle.get('registration_number') or 'the vehicle'} to {document.get('destination') or 'the workshop'}.",
            actionable_for_custodian=True,
        )
    return _batch_enrich_vehicle_movements([document])[0]


def update_vehicle_movement(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    document = _get_vehicle_movement_document(movement_id)
    _assert_vehicle_movement_mutation_access(document, current_user_id=current_user_id, current_role=normalized_role)
    if document.get("status") in {"closed", "cancelled"}:
        raise ApiError("Closed or cancelled vehicle movements cannot be updated.", status_code=400)
    if "status" in (payload or {}):
        raise ApiError("Use the dedicated lifecycle endpoints to change status.", status_code=400)

    request_payload = payload or {}
    protected_fields = sorted(SOURCE_OWNERSHIP_FIELDS.intersection(request_payload))
    if protected_fields:
        ownership = get_movement_source_ownership(document.get("movement_type"))
        message = "Source ownership fields cannot be modified through the generic Vehicle Movement API."
        raise ApiError(
            message,
            status_code=409,
            errors=[
                {
                    "code": "source_ownership_fields_immutable",
                    "message": message,
                    "movement_type": document.get("movement_type"),
                    "owning_module": ownership["owning_module"] if ownership else document.get("source_module"),
                    "fields": protected_fields,
                }
            ],
        )

    requested_movement_type = request_payload.get("movement_type")
    existing_ownership = get_movement_source_ownership(document.get("movement_type"))
    requested_ownership = get_movement_source_ownership(requested_movement_type)
    if requested_movement_type is not None and (existing_ownership or requested_ownership):
        managed_type = document.get("movement_type") if existing_ownership else requested_movement_type
        raise source_ownership_error(
            managed_type,
            code="source_managed_movement_type_immutable",
            message="Source-managed movement types cannot be changed through generic updates.",
            status_code=409,
        )

    allowed_fields = ADMIN_PATCHABLE_FIELDS if normalized_role in {"owner", "admin"} else DRIVER_PATCHABLE_FIELDS
    filtered_payload = {key: value for key, value in request_payload.items() if key in allowed_fields}
    if not filtered_payload:
        raise ApiError("No valid vehicle movement fields provided for update.", status_code=400)

    normalized_payload = _normalize_vehicle_movement_payload(filtered_payload, partial=True)
    updated_document = {**document, **normalized_payload}
    vehicle, driver, assignment = _validate_relationships(updated_document)
    _validate_time_relationships(updated_document)
    _validate_odometer_relationships(updated_document)
    if updated_document.get("status") in OPEN_MOVEMENT_STATUSES:
        _assert_vehicle_is_not_blocked(vehicle["_id"], exclude_movement_id=document["_id"], source_type=document.get("movement_type"))

    timestamp = now_utc()
    update_fields = {
        **normalized_payload,
        "vehicle_id": vehicle["_id"],
        "driver_id": driver["_id"] if driver else None,
        "assignment_id": assignment["_id"] if assignment else None,
        "updated_at": timestamp,
    }
    if "driver_id" in normalized_payload:
        update_fields["movement_custodian_id"] = driver["_id"] if driver else None
    try:
        vehicle_movements_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    except DuplicateKeyError:
        raise ApiError("Vehicle already has another open movement.", status_code=409) from None
    document.update(update_fields)
    return _batch_enrich_vehicle_movements([document])[0]


def confirm_vehicle_movement_delivery(
    movement_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    document = _get_vehicle_movement_document(movement_id)
    _assert_vehicle_movement_mutation_access(document, current_user_id=current_user_id, current_role=normalized_role)
    if normalized_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to confirm delivery for vehicle movements.", status_code=403)
    if document.get("movement_type") != "customer_dispatch":
        raise ApiError("Only customer dispatch movements support delivery confirmation.", status_code=400)
    if document.get("status") not in DELIVERY_CONFIRMABLE_STATUSES:
        raise ApiError("Delivery can only be confirmed after check-out or while in progress.", status_code=400)

    delivery_status = _validate_delivery_status((payload or {}).get("delivery_status"))
    if delivery_status != "delivered":
        raise ApiError("delivery_status must be delivered for delivery confirmation.", status_code=400)

    delivered_at = _parse_datetime((payload or {}).get("delivered_at"), "delivered_at", required=False) or now_utc()
    delivery_note = _normalize_text((payload or {}).get("delivery_note"))
    timestamp = now_utc()
    update_fields = {
        "delivery_status": "delivered",
        "delivered_at": delivered_at,
        "delivery_note": delivery_note,
        "delivered_by": _to_object_id(current_user_id, "current_user_id"),
        "updated_at": timestamp,
    }
    vehicle_movements_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_vehicle_movements([document])[0]


def _apply_status_transition(
    movement_id: str,
    *,
    next_status: str,
    allowed_current_statuses: set[str],
    current_user_id: str,
    current_role: str,
    payload: dict | None = None,
) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    document = _get_vehicle_movement_document(movement_id)
    _assert_vehicle_movement_mutation_access(document, current_user_id=current_user_id, current_role=normalized_role)
    current_status = document.get("status")
    if current_status not in allowed_current_statuses:
        raise ApiError(f"Vehicle movement cannot transition from {current_status} to {next_status}.", status_code=400)

    payload = payload or {}
    timestamp = now_utc()
    update_fields = {"status": next_status, "updated_at": timestamp}
    actor_id = _to_object_id(current_user_id, "current_user_id")
    if next_status == "approved":
        update_fields["approved_by"] = _to_object_id(current_user_id, "current_user_id")
        update_fields["approved_at"] = timestamp
    elif next_status == "checked_out":
        departure_time = _parse_datetime(payload.get("departure_time"), "departure_time", required=False) or now_utc()
        update_fields["checked_out_by"] = _to_object_id(current_user_id, "current_user_id")
        update_fields["checked_out_at"] = timestamp
        update_fields["departure_time"] = departure_time
        if "opening_odometer" in payload:
            update_fields["opening_odometer"] = _validate_non_negative_number(payload.get("opening_odometer"), "opening_odometer")
        if "opening_fuel_level" in payload:
            update_fields["opening_fuel_level"] = _validate_fuel_level(payload.get("opening_fuel_level"), "opening_fuel_level")
    elif next_status == "in_progress":
        opening_fuel = payload.get("opening_fuel_level", document.get("opening_fuel_level"))
        if opening_fuel in (None, ""):
            raise ApiError("Opening fuel level is required before starting movement.", status_code=400)
        update_fields["opening_fuel_level"] = _validate_fuel_level(opening_fuel, "opening_fuel_level")
        if "opening_odometer" in payload and payload.get("opening_odometer") not in (None, ""):
            update_fields["opening_odometer"] = _validate_non_negative_number(payload.get("opening_odometer"), "opening_odometer")
        if "notes" in payload:
            update_fields["opening_inspection_note"] = _normalize_text(payload.get("notes"))
        update_fields["opening_fuel_recorded_at"] = document.get("opening_fuel_recorded_at") or timestamp
        update_fields["opening_fuel_recorded_by"] = document.get("opening_fuel_recorded_by") or actor_id
        update_fields["started_at"] = document.get("started_at") or timestamp
        update_fields["actual_departure_at"] = document.get("actual_departure_at") or document.get("departure_time") or timestamp
        if document.get("checked_out_at") is None:
            update_fields["checked_out_by"] = actor_id
            update_fields["checked_out_at"] = timestamp
        if document.get("departure_time") is None:
            update_fields["departure_time"] = _parse_datetime(payload.get("departure_time"), "departure_time", required=False) or now_utc()
    elif next_status == "returned":
        closing_fuel = payload.get("closing_fuel_level", document.get("closing_fuel_level"))
        if closing_fuel in (None, ""):
            raise ApiError("Closing fuel level is required when returning movement.", status_code=400)
        actual_return_time = _parse_datetime(payload.get("actual_return_time"), "actual_return_time", required=False) or now_utc()
        update_fields["returned_by"] = actor_id
        update_fields["returned_at"] = timestamp
        update_fields["actual_return_time"] = actual_return_time
        if "closing_odometer" in payload:
            update_fields["closing_odometer"] = _validate_non_negative_number(payload.get("closing_odometer"), "closing_odometer")
        update_fields["closing_fuel_level"] = _validate_fuel_level(closing_fuel, "closing_fuel_level")
        update_fields["closing_fuel_recorded_at"] = document.get("closing_fuel_recorded_at") or timestamp
        update_fields["closing_fuel_recorded_by"] = document.get("closing_fuel_recorded_by") or actor_id
        update_fields["completed_at"] = document.get("completed_at") or timestamp
        if "notes" in payload:
            update_fields["notes"] = _normalize_text(payload.get("notes"))
        opening_odometer = document.get("opening_odometer")
        closing_odometer = update_fields.get("closing_odometer", document.get("closing_odometer"))
        if opening_odometer is not None and closing_odometer is not None:
            update_fields["distance_travelled"] = round(float(closing_odometer) - float(opening_odometer), 2)
        else:
            update_fields["distance_travelled"] = None
        departure_time = document.get("departure_time")
        if isinstance(departure_time, datetime):
            comparison_return = actual_return_time.replace(tzinfo=None) if departure_time.tzinfo is None else actual_return_time.astimezone(departure_time.tzinfo)
            update_fields["duration_minutes"] = round((comparison_return - departure_time).total_seconds() / 60, 1)
        expected_return = document.get("expected_return_time")
        if isinstance(expected_return, datetime):
            comparison_return = actual_return_time.replace(tzinfo=None) if expected_return.tzinfo is None else actual_return_time.astimezone(expected_return.tzinfo)
            update_fields["late_return"] = comparison_return > expected_return
        else:
            update_fields["late_return"] = False
        opening_fuel = document.get("opening_fuel_level")
        closing_fuel = update_fields["closing_fuel_level"]
        if opening_fuel is not None and closing_fuel is not None:
            update_fields["fuel_difference"] = int(closing_fuel) - int(opening_fuel)
    elif next_status == "closed":
        update_fields["closed_by"] = _to_object_id(current_user_id, "current_user_id")
        update_fields["closed_at"] = timestamp
        update_fields["completed_at"] = document.get("completed_at") or timestamp
    elif next_status == "cancelled":
        cancellation_reason = _normalize_text(payload.get("cancellation_reason"))
        if not cancellation_reason:
            raise ApiError("cancellation_reason is required when cancelling a vehicle movement.", status_code=400)
        update_fields["cancellation_reason"] = cancellation_reason

    updated_document = {**document, **update_fields}
    _validate_time_relationships(updated_document)
    _validate_odometer_relationships(updated_document)
    if updated_document.get("status") in OPEN_MOVEMENT_STATUSES:
        _assert_vehicle_is_not_blocked(updated_document["vehicle_id"], exclude_movement_id=document["_id"], exclude_reservation_id=updated_document.get("reservation_id"), source_type=updated_document.get("movement_type"))
    if next_status == "in_progress":
        _assert_driver_is_not_blocked(updated_document)
    history_event = {"status": next_status, "timestamp": timestamp, "actor_id": actor_id}
    audit_event = {"event": f"movement_{next_status}", "timestamp": timestamp, "actor_id": actor_id, "actor_role": normalized_role, "immutable": True}
    try:
        transition_result = vehicle_movements_collection().update_one(
            {"_id": document["_id"], "status": current_status},
            {"$set": update_fields, "$push": {"status_history": history_event, "audit_log": audit_event}},
        )
    except DuplicateKeyError:
        raise ApiError("Vehicle already has another open movement.", status_code=409) from None
    if transition_result.matched_count != 1:
        raise ApiError("Vehicle movement changed while this transition was being recorded.", status_code=409)
    document.update(update_fields)
    document.setdefault("status_history", []).append(history_event)
    document.setdefault("audit_log", []).append(audit_event)
    if next_status == "returned" and isinstance(document.get("reservation_id"), ObjectId):
        get_collection("resource_reservations").update_one(
            {"_id": document["reservation_id"], "status": {"$in": ["reserved", "consumed"]}},
            {"$set": {"status": "released", "released_at": timestamp, "release_reason": "Vehicle movement returned", "updated_at": timestamp}},
        )
    if document.get("movement_type") in {"maintenance", "workshop"}:
        if next_status in {"checked_out", "in_progress"}:
            vehicles_collection().update_one(
                {"_id": document["vehicle_id"]},
                {"$set": {"status": "maintenance", "updated_at": timestamp}},
            )
        elif next_status in {"closed", "cancelled"}:
            vehicle_document = vehicles_collection().find_one(
                {"_id": document["vehicle_id"]},
                {"assigned_driver_id": 1},
            ) or {}
            vehicles_collection().update_one(
                {"_id": document["vehicle_id"]},
                {
                    "$set": {
                        "status": "assigned" if vehicle_document.get("assigned_driver_id") else "available",
                        "updated_at": timestamp,
                    }
                },
            )
        event_label = {
            "approved": "approved",
            "checked_out": "checked out",
            "in_progress": "in progress",
            "returned": "returned",
            "closed": "closed",
            "cancelled": "cancelled",
        }.get(next_status, next_status.replace("_", " "))
        _notify_movement_participants(
            document,
            event=event_label,
            message=f"Maintenance movement {document.get('movement_id')} is now {event_label}.",
        )
    return _batch_enrich_vehicle_movements([document])[0]


def approve_vehicle_movement(movement_id: str, *, current_user_id: str, current_role: str) -> dict:
    if _normalize_role(current_role) not in {"owner", "admin"}:
        raise ApiError("You do not have permission to approve vehicle movements.", status_code=403)
    return _apply_status_transition(
        movement_id,
        next_status="approved",
        allowed_current_statuses={"draft", "pending_approval"},
        current_user_id=current_user_id,
        current_role=current_role,
    )


def check_out_vehicle_movement(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if _normalize_role(current_role) not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to check out vehicle movements.", status_code=403)
    return _apply_status_transition(
        movement_id,
        next_status="checked_out",
        allowed_current_statuses={"approved"},
        current_user_id=current_user_id,
        current_role=current_role,
        payload=payload,
    )


def start_vehicle_movement(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    document = _get_vehicle_movement_document(movement_id, projection=DETAIL_PROJECTION)
    normalized_role = _normalize_role(current_role) or current_role
    _assert_vehicle_movement_access(document, current_user_id=current_user_id, current_role=normalized_role)
    if normalized_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to start vehicle movements.", status_code=403)
    if document.get("status") == "in_progress" and document.get("opening_fuel_level") is not None:
        return _batch_enrich_vehicle_movements([document])[0]
    return _apply_status_transition(
        movement_id,
        next_status="in_progress",
        allowed_current_statuses={"approved", "checked_out"},
        current_user_id=current_user_id,
        current_role=current_role,
        payload=payload,
    )


def return_vehicle_movement(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    document = _get_vehicle_movement_document(movement_id, projection=DETAIL_PROJECTION)
    normalized_role = _normalize_role(current_role) or current_role
    _assert_vehicle_movement_access(document, current_user_id=current_user_id, current_role=normalized_role)
    dispatcher_return = normalized_role == "dispatcher" and document.get("movement_type") == "customer_dispatch"
    if normalized_role not in {"owner", "admin", "driver"} and not dispatcher_return:
        raise ApiError("You do not have permission to return vehicle movements.", status_code=403)
    if document.get("status") == "returned" and document.get("closing_fuel_level") is not None:
        return _batch_enrich_vehicle_movements([document])[0]
    return _apply_status_transition(
        movement_id,
        next_status="returned",
        allowed_current_statuses={"checked_out", "in_progress"},
        current_user_id=current_user_id,
        current_role=current_role,
        payload=payload,
    )


def close_vehicle_movement(movement_id: str, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    if normalized_role not in {"owner", "admin"}:
        document = _get_vehicle_movement_document(movement_id, projection=DETAIL_PROJECTION)
        assigned_source_driver = (
            normalized_role == "driver"
            and document.get("movement_type") in {"stock_transfer", "stock_return", "supplier_pickup", PERSONAL_USE_TYPE}
            and document.get("driver_id") == _to_object_id(current_user_id, "current_user_id")
        )
        if not assigned_source_driver:
            raise ApiError("You do not have permission to close vehicle movements.", status_code=403)
    return _apply_status_transition(
        movement_id,
        next_status="closed",
        allowed_current_statuses={"returned"},
        current_user_id=current_user_id,
        current_role=current_role,
    )


def cancel_vehicle_movement(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if _normalize_role(current_role) not in {"owner", "admin"}:
        raise ApiError("You do not have permission to cancel vehicle movements.", status_code=403)
    return _apply_status_transition(
        movement_id,
        next_status="cancelled",
        allowed_current_statuses={"draft", "pending_approval", "approved"},
        current_user_id=current_user_id,
        current_role=current_role,
        payload=payload,
    )


def respond_to_maintenance_movement(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if _normalize_role(current_role) != "driver":
        raise ApiError("Only the assigned movement custodian can respond.", status_code=403)
    document = _get_vehicle_movement_document(movement_id)
    user_id = _to_object_id(current_user_id, "current_user_id")
    if (document.get("movement_custodian_id") or document.get("driver_id")) != user_id:
        raise ApiError("You are not the assigned movement custodian.", status_code=403)
    if document.get("movement_type") not in {"maintenance", "workshop"}:
        raise ApiError("This action is only available for maintenance movements.", status_code=400)
    response = (_normalize_text((payload or {}).get("response")) or "").lower()
    if response not in {"accepted", "rejected"}:
        raise ApiError("response must be accepted or rejected.", status_code=400)
    reason = _normalize_text((payload or {}).get("reason"))
    if response == "rejected" and not reason:
        raise ApiError("A rejection reason is required.", status_code=400)
    update_fields = {
        "custodian_response_status": response,
        "custodian_response_reason": reason,
        "custodian_responded_at": now_utc(),
        "updated_at": now_utc(),
    }
    vehicle_movements_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    notify_roles(
        ["owner", "admin"],
        title=f"Maintenance custodian {response}",
        message=f"Movement {document.get('movement_id')} was {response} by its custodian.{f' Reason: {reason}' if reason else ''}",
        category="maintenance",
        priority="high" if response == "rejected" else "medium",
        reference_type="vehicle_movement",
        reference_id=document["_id"],
    )
    return _batch_enrich_vehicle_movements([document])[0]


def submit_maintenance_completion(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    document = _get_vehicle_movement_document(movement_id)
    _assert_vehicle_movement_access(document, current_user_id=current_user_id, current_role=_normalize_role(current_role) or current_role)
    user_id = _to_object_id(current_user_id, "current_user_id")
    if _normalize_role(current_role) == "driver" and (document.get("movement_custodian_id") or document.get("driver_id")) != user_id:
        raise ApiError("Only the movement custodian can submit completion.", status_code=403)
    if document.get("movement_type") not in {"maintenance", "workshop"}:
        raise ApiError("This action is only available for maintenance movements.", status_code=400)
    if document.get("status") != "returned":
        raise ApiError("Return the vehicle before submitting maintenance completion.", status_code=400)
    normalized = _normalize_vehicle_movement_payload(payload or {}, partial=True)
    allowed = {key: normalized.get(key) for key in ("workshop_name", "mechanic_name", "work_performed", "parts_changed", "test_result", "notes") if key in normalized}
    allowed.update({"completion_status": "awaiting_admin_verification", "completion_submitted_at": now_utc(), "completion_submitted_by": user_id, "updated_at": now_utc()})
    vehicle_movements_collection().update_one({"_id": document["_id"]}, {"$set": allowed})
    document.update(allowed)
    resolve_action_notifications("vehicle_movement", document["_id"], action_type="resubmit_maintenance_completion", completed_by=current_user_id)
    notify_roles(
        ["owner", "admin"],
        title="Maintenance completion awaiting review",
        message=f"Movement {document.get('movement_id')} has maintenance work awaiting verification.",
        category="maintenance",
        priority="high",
        reference_type="vehicle_movement",
        reference_id=document["_id"],
        action_type="approve_maintenance_completion",
        action_url="vehicle-movements",
        action_label="Review completion",
    )
    _notify_movement_participants(document, event="submitted", message="Maintenance completion was submitted for admin verification.")
    return _batch_enrich_vehicle_movements([document])[0]


def review_maintenance_completion(movement_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if _normalize_role(current_role) not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can review maintenance completion.", status_code=403)
    document = _get_vehicle_movement_document(movement_id)
    if document.get("completion_status") != "awaiting_admin_verification":
        raise ApiError("This maintenance completion is not awaiting verification.", status_code=400)
    decision = (_normalize_text((payload or {}).get("decision")) or "").lower()
    if decision not in {"approved", "returned_for_correction", "rejected"}:
        raise ApiError("Invalid maintenance review decision.", status_code=400)
    reason = _normalize_text((payload or {}).get("reason"))
    if decision != "approved" and not reason:
        raise ApiError("A reason is required for this decision.", status_code=400)
    timestamp = now_utc()
    update_fields = {"completion_status": decision, "completion_review_reason": reason, "completion_reviewed_by": _to_object_id(current_user_id, "current_user_id"), "completion_reviewed_at": timestamp, "updated_at": timestamp}
    vehicle_movements_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    resolve_action_notifications(
        "vehicle_movement",
        document["_id"],
        action_type="approve_maintenance_completion",
        resolution="completed" if decision == "approved" else "cancelled",
        completed_by=current_user_id,
    )
    if decision == "approved" and document.get("maintenance_job_id"):
        from services.maintenance_service import update_maintenance_status
        update_maintenance_status(
            str(document["maintenance_job_id"]),
            "completed",
            {
                "completion_date": timestamp.date().isoformat(),
                "completion_odometer": document.get("closing_odometer"),
                "work_performed": document.get("work_performed"),
                "parts_changed": document.get("parts_changed"),
                "notes": document.get("notes"),
            },
            current_user_id,
            _normalize_role(current_role) or current_role,
        )
        document = {**document, "status": "closed", "closed_by": _to_object_id(current_user_id, "current_user_id"), "closed_at": timestamp, "updated_at": timestamp}
        vehicle_movements_collection().update_one({"_id": document["_id"]}, {"$set": {"status": "closed", "closed_by": document["closed_by"], "closed_at": timestamp, "updated_at": timestamp}})
    _notify_movement_participants(document, event=decision.replace("_", " "), message=f"Maintenance completion was {decision.replace('_', ' ')}.{f' {reason}' if reason else ''}", actionable_for_custodian=decision == "returned_for_correction")
    return _batch_enrich_vehicle_movements([document])[0]


def list_vehicle_movement_options(*, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    cache_key = build_cache_key("vehicle_movements:options", role=normalized_role, user_id=current_user_id if normalized_role == "driver" else None)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    if normalized_role == "driver":
        driver = _get_driver_document(current_user_id)
        assignments = list(
            assignments_collection().find(
                {"driver_id": driver["_id"], "status": {"$in": ["active", "suspended"]}},
                ASSIGNMENT_SUMMARY_PROJECTION,
            )
        )
        vehicle_ids = {assignment.get("vehicle_id") for assignment in assignments if isinstance(assignment.get("vehicle_id"), ObjectId)}
        vehicles = list(vehicles_collection().find({"_id": {"$in": list(vehicle_ids)}}, VEHICLE_SUMMARY_PROJECTION)) if vehicle_ids else []
        payload = {
            "movement_types": sorted(ALLOWED_MOVEMENT_TYPES),
            "statuses": sorted(ALLOWED_MOVEMENT_STATUSES),
            "open_statuses": sorted(OPEN_MOVEMENT_STATUSES),
            "drivers": [serialize_user(driver)],
            "vehicles": [serialize_vehicle(vehicle, include_sensitive=False) for vehicle in vehicles],
            "assignments": [serialize_assignment(item) for item in assignments],
        }
        return set_ttl_cached(cache_key, payload, ttl_seconds=15)

    drivers_started_at = perf_counter()
    drivers = list(
        users_collection().find(
            {"role": "driver", "status": "active", "driver_profile.approval_status": "approved"},
            USER_SUMMARY_PROJECTION,
        ).sort("full_name", ASCENDING)
    )
    eligible_drivers = []
    for driver in drivers:
        try:
            _get_driver_document(driver["_id"])
            eligible_drivers.append(driver)
        except ApiError:
            continue
    drivers = eligible_drivers
    log_db_duration("vehicle_movements.options.drivers", drivers_started_at)

    vehicles_started_at = perf_counter()
    vehicles = list(
        vehicles_collection().find(
            {"status": {"$in": ["available", "assigned", "active"]}},
            VEHICLE_SUMMARY_PROJECTION,
        ).sort("registration_number", ASCENDING)
    )
    log_db_duration("vehicle_movements.options.vehicles", vehicles_started_at)

    assignments_started_at = perf_counter()
    assignments = list(
        assignments_collection().find(
            {"status": {"$in": ["active", "suspended"]}},
            ASSIGNMENT_SUMMARY_PROJECTION,
        ).sort("created_at", DESCENDING)
    )
    log_db_duration("vehicle_movements.options.assignments", assignments_started_at)

    payload = {
        "movement_types": sorted(ALLOWED_MOVEMENT_TYPES),
        "creatable_movement_types": sorted(
            ALLOWED_MOVEMENT_TYPES - SOURCE_MANAGED_MOVEMENT_TYPES
        ),
        "statuses": sorted(ALLOWED_MOVEMENT_STATUSES),
        "open_statuses": sorted(OPEN_MOVEMENT_STATUSES),
        "drivers": [serialize_user(driver) for driver in drivers],
        "vehicles": [serialize_vehicle(vehicle, include_sensitive=False) for vehicle in vehicles],
        "assignments": [serialize_assignment(item) for item in assignments],
        "branches": [
            {"id": str(item["_id"]), "name": item.get("name"), "code": item.get("code")}
            for item in get_collection("branches").find({"active": {"$ne": False}}, {"name": 1, "code": 1}).sort("name", ASCENDING)
        ],
    }
    return set_ttl_cached(cache_key, payload, ttl_seconds=15)
