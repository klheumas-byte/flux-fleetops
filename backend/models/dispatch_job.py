from bson import ObjectId
from utils.dispatch_payment_classification import resolve_dispatch_financial_type


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def _serialize_stop(stop: dict) -> dict:
    return {
        "stop_id": stop.get("stop_id"),
        "stop_sequence": stop.get("stop_sequence"),
        "stop_type": stop.get("stop_type"),
        "location": stop.get("location"),
        "contact_name": stop.get("contact_name"),
        "contact_phone": stop.get("contact_phone"),
        "load_note": stop.get("load_note"),
        "planned_arrival_time": _serialize_datetime(stop.get("planned_arrival_time")),
        "planned_departure_time": _serialize_datetime(stop.get("planned_departure_time")),
        "stop_charge": stop.get("stop_charge"),
        "stop_status": stop.get("stop_status"),
        "delivery_status": stop.get("delivery_status"),
        "delivered_at": _serialize_datetime(stop.get("delivered_at")),
        "delivery_note": stop.get("delivery_note"),
        "delivered_by": _serialize_reference_id(stop.get("delivered_by")),
        "completed_at": _serialize_datetime(stop.get("completed_at")),
        "completed_by": _serialize_reference_id(stop.get("completed_by")),
        "completion_note": stop.get("completion_note"),
    }


def _serialize_timeline_entry(entry: dict) -> dict:
    return {
        "event_id": entry.get("event_id"),
        "event_type": entry.get("event_type"),
        "title": entry.get("title"),
        "status": entry.get("status"),
        "note": entry.get("note"),
        "updated_by": _serialize_reference_id(entry.get("updated_by")),
        "timestamp": _serialize_datetime(entry.get("timestamp")),
    }


def serialize_dispatch_job(document: dict) -> dict:
    financial_type, is_legacy = resolve_dispatch_financial_type(document)
    return {
        "id": str(document.get("_id")),
        "dispatch_job_id": document.get("dispatch_job_id"),
        "dispatch_request_id": _serialize_reference_id(document.get("dispatch_request_id")),
        "dispatch_financial_type": financial_type,
        "dispatch_financial_type_is_legacy": is_legacy,
        "partner_organization_reference": document.get("partner_organization_reference"),
        "partner_billing_method": document.get("partner_billing_method"),
        "approved_charge": document.get("approved_charge"),
        "proposed_charge": document.get("proposed_charge"),
        "payment_status": document.get("payment_status"),
        "payment_method": document.get("payment_method"),
        "amount_paid": document.get("amount_paid", 0),
        "outstanding_balance": document.get("outstanding_balance", 0),
        "driver_compensation_type": document.get("driver_compensation_type") or "none",
        "driver_compensation_value": document.get("driver_compensation_value", 0),
        "driver_compensation_amount": document.get("driver_compensation_amount", 0),
        "financial_type_changed_by": _serialize_reference_id(document.get("financial_type_changed_by")),
        "financial_type_changed_at": _serialize_datetime(document.get("financial_type_changed_at")),
        "driver_compensation_approved_by": _serialize_reference_id(document.get("driver_compensation_approved_by")),
        "driver_compensation_approved_at": _serialize_datetime(document.get("driver_compensation_approved_at")),
        "status": document.get("status"),
        "driver_workflow_status": document.get("driver_workflow_status"),
        "is_paused": bool(document.get("is_paused")),
        "paused_at": _serialize_datetime(document.get("paused_at")),
        "paused_reason": document.get("paused_reason"),
        "driver_response_status": document.get("driver_response_status"),
        "driver_response_reason": document.get("driver_response_reason"),
        "driver_responded_at": _serialize_datetime(document.get("driver_responded_at")),
        "return_status": document.get("return_status"),
        "actual_departure_at": _serialize_datetime(document.get("actual_departure_at") or document.get("started_at")),
        "actual_return_at": _serialize_datetime(document.get("actual_return_at")),
        "return_confirmed_at": _serialize_datetime(document.get("return_confirmed_at")),
        "return_confirmed_by": _serialize_reference_id(document.get("return_confirmed_by")),
        "inspection_completed_at": _serialize_datetime(document.get("inspection_completed_at")),
        "inspection_completed_by": _serialize_reference_id(document.get("inspection_completed_by")),
        "dispatch_closed_at": _serialize_datetime(document.get("dispatch_closed_at")),
        "dispatch_closed_by": _serialize_reference_id(document.get("dispatch_closed_by")),
        "linked_fault_id": _serialize_reference_id(document.get("linked_fault_id")),
        "return_checklist": document.get("return_checklist"),
        "closure_note": document.get("closure_note"),
        "vehicle_id": _serialize_reference_id(document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(document.get("driver_id")),
        "assistant_id": _serialize_reference_id(document.get("assistant_id")),
        "dispatcher_id": _serialize_reference_id(document.get("dispatcher_id")),
        "primary_assignment_id": _serialize_reference_id(document.get("primary_assignment_id")),
        "vehicle_reservation_id": _serialize_reference_id(document.get("vehicle_reservation_id")),
        "driver_reservation_id": _serialize_reference_id(document.get("driver_reservation_id")),
        "linked_vehicle_movement_id": _serialize_reference_id(document.get("linked_vehicle_movement_id")),
        "pickup": document.get("pickup"),
        "destination": document.get("destination"),
        "stops": [_serialize_stop(stop) for stop in (document.get("stops") or [])],
        "dispatch_date": document.get("dispatch_date"),
        "dispatch_time": document.get("dispatch_time"),
        "scheduled_start_time": _serialize_datetime(document.get("scheduled_start_time")),
        "expected_arrival_time": _serialize_datetime(document.get("expected_arrival_time")),
        "expected_return_time": _serialize_datetime(document.get("expected_return_time")),
        "distance_estimate_km": document.get("distance_estimate_km"),
        "goods_description": document.get("goods_description"),
        "quantity": document.get("quantity"),
        "weight_category": document.get("weight_category"),
        "fragile": document.get("fragile"),
        "refrigerated": document.get("refrigerated"),
        "hazardous": document.get("hazardous"),
        "loading_notes": document.get("loading_notes"),
        "customer_contact": document.get("customer_contact"),
        "receiver_contact": document.get("receiver_contact"),
        "dispatch_instructions": document.get("dispatch_instructions"),
        "internal_notes": document.get("internal_notes"),
        "conflict_summary": document.get("conflict_summary") or [],
        "reservation_window": document.get("reservation_window") or {},
        "created_by": _serialize_reference_id(document.get("created_by")),
        "updated_by": _serialize_reference_id(document.get("updated_by")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
        "assigned_at": _serialize_datetime(document.get("assigned_at")),
        "started_at": _serialize_datetime(document.get("started_at")),
        "completed_at": _serialize_datetime(document.get("completed_at")),
        "cancelled_at": _serialize_datetime(document.get("cancelled_at")),
        "timeline": [_serialize_timeline_entry(entry) for entry in (document.get("timeline") or [])],
    }
