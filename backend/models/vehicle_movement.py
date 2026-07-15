from bson import ObjectId

from utils.fuel_levels import build_fuel_level_details, normalize_fuel_level_eighths


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def serialize_vehicle_movement(movement_document: dict) -> dict:
    opening_fuel_level, opening_fuel_warning = normalize_fuel_level_eighths(
        movement_document.get("opening_fuel_level")
    )
    closing_fuel_level, closing_fuel_warning = normalize_fuel_level_eighths(
        movement_document.get("closing_fuel_level")
    )
    return {
        "id": str(movement_document.get("_id")),
        "movement_id": movement_document.get("movement_id"),
        "vehicle_id": _serialize_reference_id(movement_document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(movement_document.get("driver_id")),
        "movement_custodian_id": _serialize_reference_id(movement_document.get("movement_custodian_id") or movement_document.get("driver_id")),
        "permanent_driver_id": _serialize_reference_id(movement_document.get("permanent_driver_id")),
        "maintenance_job_id": _serialize_reference_id(movement_document.get("maintenance_job_id")),
        "preventive_schedule_id": _serialize_reference_id(movement_document.get("preventive_schedule_id")),
        "maintenance_assignee_id": _serialize_reference_id(movement_document.get("maintenance_assignee_id")),
        "assignment_id": _serialize_reference_id(movement_document.get("assignment_id")),
        "primary_assignment_id": _serialize_reference_id(movement_document.get("primary_assignment_id")),
        "dispatch_job_id": _serialize_reference_id(movement_document.get("dispatch_job_id")),
        "dispatch_request_id": _serialize_reference_id(movement_document.get("dispatch_request_id")),
        "reservation_id": _serialize_reference_id(movement_document.get("reservation_id")),
        "movement_type": movement_document.get("movement_type"),
        "status": movement_document.get("status"),
        "requested_departure_time": _serialize_datetime(movement_document.get("requested_departure_time")),
        "departure_time": _serialize_datetime(movement_document.get("departure_time")),
        "expected_return_time": _serialize_datetime(movement_document.get("expected_return_time")),
        "actual_return_time": _serialize_datetime(movement_document.get("actual_return_time")),
        "origin": movement_document.get("origin"),
        "destination": movement_document.get("destination"),
        "purpose": movement_document.get("purpose"),
        "instructions": movement_document.get("instructions"),
        "custodian_response_status": movement_document.get("custodian_response_status"),
        "custodian_response_reason": movement_document.get("custodian_response_reason"),
        "workshop_name": movement_document.get("workshop_name"),
        "mechanic_name": movement_document.get("mechanic_name"),
        "work_performed": movement_document.get("work_performed"),
        "parts_changed": movement_document.get("parts_changed"),
        "test_result": movement_document.get("test_result"),
        "completion_status": movement_document.get("completion_status"),
        "opening_odometer": movement_document.get("opening_odometer"),
        "closing_odometer": movement_document.get("closing_odometer"),
        "opening_fuel_level": opening_fuel_level,
        "opening_fuel_level_details": build_fuel_level_details(opening_fuel_level),
        "opening_fuel_level_legacy_value": movement_document.get("opening_fuel_level")
        if opening_fuel_level is None and movement_document.get("opening_fuel_level") not in (None, "")
        else None,
        "opening_fuel_level_warning": opening_fuel_warning,
        "closing_fuel_level": closing_fuel_level,
        "closing_fuel_level_details": build_fuel_level_details(closing_fuel_level),
        "closing_fuel_level_legacy_value": movement_document.get("closing_fuel_level")
        if closing_fuel_level is None and movement_document.get("closing_fuel_level") not in (None, "")
        else None,
        "closing_fuel_level_warning": closing_fuel_warning,
        "delivery_status": movement_document.get("delivery_status"),
        "delivered_at": _serialize_datetime(movement_document.get("delivered_at")),
        "delivery_note": movement_document.get("delivery_note"),
        "delivered_by": _serialize_reference_id(movement_document.get("delivered_by")),
        "notes": movement_document.get("notes"),
        "cancellation_reason": movement_document.get("cancellation_reason"),
        "approved_by": _serialize_reference_id(movement_document.get("approved_by")),
        "approved_at": _serialize_datetime(movement_document.get("approved_at")),
        "checked_out_by": _serialize_reference_id(movement_document.get("checked_out_by")),
        "checked_out_at": _serialize_datetime(movement_document.get("checked_out_at")),
        "returned_by": _serialize_reference_id(movement_document.get("returned_by")),
        "returned_at": _serialize_datetime(movement_document.get("returned_at")),
        "closed_by": _serialize_reference_id(movement_document.get("closed_by")),
        "closed_at": _serialize_datetime(movement_document.get("closed_at")),
        "return_checklist": movement_document.get("return_checklist"),
        "created_by": _serialize_reference_id(movement_document.get("created_by")),
        "created_at": _serialize_datetime(movement_document.get("created_at")),
        "updated_at": _serialize_datetime(movement_document.get("updated_at")),
    }
