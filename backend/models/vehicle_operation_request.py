from bson import ObjectId
from datetime import datetime, timezone

from utils.operational_request_types import normalize_type_token


def serialize_mongo_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, dict):
        return {str(key): serialize_mongo_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [serialize_mongo_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def serialize_vehicle_operation_request(document: dict, *, include_evidence: bool = False) -> dict:
    expected_return = document.get("expected_return_at")
    actual_start = document.get("started_at")
    actual_return = document.get("returned_at")
    now = datetime.now(expected_return.tzinfo or timezone.utc) if expected_return else datetime.now(timezone.utc)
    if expected_return and expected_return.tzinfo is None:
        now = now.replace(tzinfo=None)
    is_overdue = bool(expected_return and not actual_return and document.get("status") in {"scheduled", "movement_in_progress"} and expected_return < now)
    comparable_return = actual_return
    comparable_expected = expected_return
    if isinstance(comparable_return, datetime) and isinstance(comparable_expected, datetime):
        if comparable_return.tzinfo is None:
            comparable_return = comparable_return.replace(tzinfo=timezone.utc)
        if comparable_expected.tzinfo is None:
            comparable_expected = comparable_expected.replace(tzinfo=timezone.utc)
    payload = {
        "id": str(document.get("_id")),
        "request_id": document.get("request_id"),
        "operation_type": normalize_type_token(document.get("operation_type")),
        "title": document.get("title"),
        "purpose": document.get("purpose"),
        "journey_mode": document.get("journey_mode"),
        "source_location_id": serialize_mongo_value(document.get("source_location_id")),
        "destination_location_id": serialize_mongo_value(document.get("destination_location_id")),
        "origin": document.get("origin"),
        "destination": document.get("destination"),
        "origin_snapshot": document.get("origin_snapshot"),
        "destination_snapshot": document.get("destination_snapshot"),
        "planned_stops": document.get("planned_stops") or [],
        "delivery_items": document.get("delivery_items") or [],
        "sender_name": document.get("sender_name"),
        "intended_receiver_name": document.get("intended_receiver_name"),
        "business_unit": document.get("business_unit"),
        "vehicle_id": serialize_mongo_value(document.get("vehicle_id")),
        "driver_id": serialize_mongo_value(document.get("driver_id")),
        "requested_by": serialize_mongo_value(document.get("requested_by")),
        "approved_by": serialize_mongo_value(document.get("approved_by")),
        "approved_at": serialize_mongo_value(document.get("approved_at")),
        "rejected_by": serialize_mongo_value(document.get("rejected_by")),
        "rejected_at": serialize_mongo_value(document.get("rejected_at")),
        "rejection_reason": document.get("rejection_reason"),
        "planned_departure_at": serialize_mongo_value(document.get("planned_departure_at")),
        "expected_return_at": serialize_mongo_value(document.get("expected_return_at")),
        "status": document.get("status"),
        "priority": document.get("priority"),
        "financial_class": document.get("financial_class") or "non_revenue",
        "cost_responsibility": document.get("cost_responsibility"),
        "notes": document.get("notes"),
        "linked_vehicle_movement_id": serialize_mongo_value(document.get("linked_vehicle_movement_id")),
        "vehicle_reservation_id": serialize_mongo_value(document.get("vehicle_reservation_id")),
        "related_source_type": document.get("related_source_type"),
        "related_source_id": serialize_mongo_value(document.get("related_source_id")),
        "receiver_confirmation": document.get("receiver_confirmation"),
        "task_confirmation": document.get("task_confirmation"),
        "destination_acceptance": document.get("destination_acceptance"),
        "no_purchase_reason": document.get("no_purchase_reason"),
        "fuel_log_id": serialize_mongo_value(document.get("fuel_log_id")),
        "acknowledged_at": serialize_mongo_value(document.get("acknowledged_at")),
        "opening_check_completed_at": serialize_mongo_value(document.get("opening_check_completed_at")),
        "actual_start": serialize_mongo_value(actual_start),
        "actual_return": serialize_mongo_value(actual_return),
        "started_at": serialize_mongo_value(actual_start),
        "returned_at": serialize_mongo_value(actual_return),
        "is_overdue": is_overdue,
        "late_return": bool(comparable_return and comparable_expected and comparable_return > comparable_expected),
        "target_vehicle_at_request": document.get("target_vehicle_at_request"),
        "distance": document.get("distance"),
        "distance_travelled": document.get("distance"),
        "duration_minutes": document.get("duration_minutes"),
        "fuel_difference": document.get("fuel_difference"),
        "return_fault_id": serialize_mongo_value(document.get("return_fault_id")),
        "status_history": serialize_mongo_value(document.get("status_history") or []),
        "created_at": serialize_mongo_value(document.get("created_at")),
        "updated_at": serialize_mongo_value(document.get("updated_at")),
        "version": int(document.get("version") or 1),
    }
    if include_evidence:
        payload["attachments"] = document.get("attachments") or []
    else:
        payload["attachment_count"] = len(document.get("attachments") or [])
    return serialize_mongo_value(payload)
