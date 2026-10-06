from bson import ObjectId

from utils.operational_request_types import normalize_type_token

from utils.fuel_levels import build_fuel_level_details, normalize_fuel_level_eighths


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_datetime(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _serialize_custody_event(event_document: dict) -> dict:
    return {
        "event_id": event_document.get("event_id"),
        "event_key": event_document.get("event_key"),
        "event_type": event_document.get("event_type"),
        "from_user_id": _serialize_reference_id(event_document.get("from_user_id")),
        "from_location": event_document.get("from_location"),
        "to_user_id": _serialize_reference_id(event_document.get("to_user_id")),
        "to_location": event_document.get("to_location"),
        "initiated_by": _serialize_reference_id(event_document.get("initiated_by")),
        "accepted_by": _serialize_reference_id(event_document.get("accepted_by")),
        "occurred_at": _serialize_datetime(event_document.get("occurred_at")),
        "accepted_at": _serialize_datetime(event_document.get("accepted_at")),
        "condition_summary": event_document.get("condition_summary"),
        "fuel_level": event_document.get("fuel_level"),
        "odometer": event_document.get("odometer"),
        "odometer_available": bool(event_document.get("odometer_available")),
        "odometer_unavailable_reason": event_document.get("odometer_unavailable_reason"),
        "notes": event_document.get("notes"),
        "evidence": event_document.get("evidence") or [],
        "source_type": event_document.get("source_type"),
        "source_id": _serialize_reference_id(event_document.get("source_id")),
        "is_correction": bool(event_document.get("is_correction")),
        "correction_reason": event_document.get("correction_reason"),
    }


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
        "source_type": movement_document.get("source_type"),
        "source_id": _serialize_reference_id(movement_document.get("source_id")),
        "source_key": movement_document.get("source_key"),
        "source_module": movement_document.get("source_module"),
        "source_reference": movement_document.get("source_reference"),
        "canonical_source_key": movement_document.get("canonical_source_key"),
        "replaces_movement_id": _serialize_reference_id(movement_document.get("replaces_movement_id")),
        "superseded_by_movement_id": _serialize_reference_id(movement_document.get("superseded_by_movement_id")),
        "superseded_at": _serialize_datetime(movement_document.get("superseded_at")),
        "supersession_reason": movement_document.get("supersession_reason"),
        "replacement_created_at": _serialize_datetime(movement_document.get("replacement_created_at")),
        "replacement_reason": movement_document.get("replacement_reason"),
        "vehicle_id": _serialize_reference_id(movement_document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(movement_document.get("driver_id")),
        "movement_custodian_id": _serialize_reference_id(movement_document.get("movement_custodian_id") or movement_document.get("driver_id")),
        "custody_state": movement_document.get("custody_state"),
        "current_custody_location": movement_document.get("current_custody_location"),
        "custody_version": movement_document.get("custody_version", 0),
        "pending_custody_transfer": {
            **movement_document.get("pending_custody_transfer"),
            "to_user_id": _serialize_reference_id(
                (movement_document.get("pending_custody_transfer") or {}).get("to_user_id")
            ),
            "initiated_by": _serialize_reference_id(
                (movement_document.get("pending_custody_transfer") or {}).get("initiated_by")
            ),
            "initiated_at": _serialize_datetime(
                (movement_document.get("pending_custody_transfer") or {}).get("initiated_at")
            ),
        }
        if movement_document.get("pending_custody_transfer")
        else None,
        "custody_events": [
            _serialize_custody_event(event)
            for event in movement_document.get("custody_events") or []
        ]
        if "custody_events" in movement_document
        else None,
        "permanent_driver_id": _serialize_reference_id(movement_document.get("permanent_driver_id")),
        "maintenance_job_id": _serialize_reference_id(movement_document.get("maintenance_job_id")),
        "preventive_schedule_id": _serialize_reference_id(movement_document.get("preventive_schedule_id")),
        "maintenance_assignee_id": _serialize_reference_id(movement_document.get("maintenance_assignee_id")),
        "assignment_id": _serialize_reference_id(movement_document.get("assignment_id")),
        "primary_assignment_id": _serialize_reference_id(movement_document.get("primary_assignment_id")),
        "dispatch_job_id": _serialize_reference_id(movement_document.get("dispatch_job_id")),
        "dispatch_request_id": _serialize_reference_id(movement_document.get("dispatch_request_id")),
        "reservation_id": _serialize_reference_id(movement_document.get("reservation_id")),
        "movement_type": normalize_type_token(movement_document.get("movement_type")),
        "movement_category": movement_document.get("movement_category") or str(movement_document.get("movement_type") or "").upper(),
        "status": movement_document.get("status"),
        "force_close_reason": movement_document.get("force_close_reason"),
        "force_closed_at": _serialize_datetime(movement_document.get("force_closed_at")),
        "force_closed_by": _serialize_reference_id(movement_document.get("force_closed_by")),
        "physical_vehicle_confirmed": bool(movement_document.get("physical_vehicle_confirmed")),
        "requested_departure_time": _serialize_datetime(movement_document.get("requested_departure_time")),
        "actual_departure_at": _serialize_datetime(movement_document.get("actual_departure_at") or movement_document.get("departure_time")),
        "departure_time": _serialize_datetime(movement_document.get("departure_time")),
        "expected_return_time": _serialize_datetime(movement_document.get("expected_return_time")),
        "actual_return_at": _serialize_datetime(movement_document.get("actual_return_at") or movement_document.get("actual_return_time")),
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
        "physical_completion_status": movement_document.get("physical_completion_status"),
        "handover_kind": movement_document.get("handover_kind"),
        "handover_sequence": movement_document.get("handover_sequence"),
        "transport_direction": movement_document.get("transport_direction"),
        "transport_mode": movement_document.get("transport_mode"),
        "financial_class": movement_document.get("financial_class"),
        "journey_mode": movement_document.get("journey_mode"),
        "planned_stops": movement_document.get("planned_stops") or [],
        "origin_location_id": _serialize_reference_id(movement_document.get("origin_location_id")),
        "destination_location_id": _serialize_reference_id(movement_document.get("destination_location_id")),
        "origin_snapshot": movement_document.get("origin_snapshot"),
        "destination_snapshot": movement_document.get("destination_snapshot"),
        "stock_transfer_id": _serialize_reference_id(movement_document.get("stock_transfer_id")),
        "operation_request_id": _serialize_reference_id(movement_document.get("operation_request_id")),
        "related_source_type": movement_document.get("related_source_type"),
        "related_source_id": _serialize_reference_id(movement_document.get("related_source_id")),
        "opening_odometer": movement_document.get("opening_odometer"),
        "opening_condition_summary": movement_document.get("opening_condition_summary"),
        "closing_odometer": movement_document.get("closing_odometer"),
        "closing_condition_summary": movement_document.get("closing_condition_summary"),
        "opening_fuel_level": opening_fuel_level,
        "opening_fuel_level_details": build_fuel_level_details(opening_fuel_level),
        "opening_fuel_level_legacy_value": movement_document.get("opening_fuel_level")
        if opening_fuel_level is None and movement_document.get("opening_fuel_level") not in (None, "")
        else None,
        "opening_fuel_level_warning": opening_fuel_warning,
        "opening_fuel_recorded_at": _serialize_datetime(movement_document.get("opening_fuel_recorded_at")),
        "opening_fuel_recorded_by": _serialize_reference_id(movement_document.get("opening_fuel_recorded_by")),
        "opening_fuel_photo": movement_document.get("opening_fuel_photo"),
        "opening_inspection_note": movement_document.get("opening_inspection_note"),
        "closing_fuel_level": closing_fuel_level,
        "closing_fuel_level_details": build_fuel_level_details(closing_fuel_level),
        "closing_fuel_level_legacy_value": movement_document.get("closing_fuel_level")
        if closing_fuel_level is None and movement_document.get("closing_fuel_level") not in (None, "")
        else None,
        "closing_fuel_level_warning": closing_fuel_warning,
        "closing_fuel_recorded_at": _serialize_datetime(movement_document.get("closing_fuel_recorded_at")),
        "closing_fuel_recorded_by": _serialize_reference_id(movement_document.get("closing_fuel_recorded_by")),
        "total_fuel_litres_added": movement_document.get("total_fuel_litres_added"),
        "total_fuel_cost": movement_document.get("total_fuel_cost"),
        "estimated_fuel_consumed": movement_document.get("estimated_fuel_consumed"),
        "estimated_fuel_efficiency": movement_document.get("estimated_fuel_efficiency"),
        "fuel_summary_status": movement_document.get("fuel_summary_status"),
        "fuel_advance": _serialize_value(movement_document.get("fuel_advance")) if movement_document.get("fuel_advance") else None,
        "distance_travelled": movement_document.get("distance_travelled"),
        "duration_minutes": movement_document.get("duration_minutes"),
        "late_return": movement_document.get("late_return"),
        "fuel_difference": movement_document.get("fuel_difference"),
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
        "started_at": _serialize_datetime(movement_document.get("started_at") or movement_document.get("departure_time")),
        "completed_at": _serialize_datetime(movement_document.get("completed_at") or movement_document.get("closed_at")),
        "status_history": _serialize_value(movement_document.get("status_history") or []),
        "audit_log": _serialize_value(movement_document.get("audit_log") or []),
        "return_checklist": movement_document.get("return_checklist"),
        "created_by": _serialize_reference_id(movement_document.get("created_by")),
        "created_at": _serialize_datetime(movement_document.get("created_at")),
        "updated_at": _serialize_datetime(movement_document.get("updated_at")),
    }
