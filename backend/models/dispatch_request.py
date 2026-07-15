from bson import ObjectId


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
        "linked_movement_id": _serialize_reference_id(stop.get("linked_movement_id")),
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
    }


def _serialize_pricing_history(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "action": entry.get("action"),
        "actor_id": _serialize_reference_id(entry.get("actor_id")),
        "acted_at": _serialize_datetime(entry.get("acted_at")),
        "pricing_status": entry.get("pricing_status"),
        "proposed_charge": entry.get("proposed_charge"),
        "approved_charge": entry.get("approved_charge"),
        "distance_estimate_km": entry.get("distance_estimate_km"),
        "fuel_estimate_amount": entry.get("fuel_estimate_amount"),
        "fuel_estimate_cost": entry.get("fuel_estimate_cost"),
        "other_expected_costs": entry.get("other_expected_costs"),
        "expected_net_revenue": entry.get("expected_net_revenue"),
        "pricing_notes": entry.get("pricing_notes"),
    }


def serialize_dispatch_request(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "request_id": document.get("request_id"),
        "source_dispatch_opportunity_id": document.get("source_dispatch_opportunity_id"),
        "source_dispatch_opportunity_record_id": _serialize_reference_id(document.get("source_dispatch_opportunity_record_id")),
        "submitted_by_driver_id": _serialize_reference_id(document.get("submitted_by_driver_id")),
        "request_type": document.get("request_type"),
        "customer_name": document.get("customer_name"),
        "customer_phone": document.get("customer_phone"),
        "customer_company": document.get("customer_company"),
        "pickup_location": document.get("pickup_location"),
        "destination": document.get("destination"),
        "vehicle_type_needed": document.get("vehicle_type_needed"),
        "load_type": document.get("load_type"),
        "load_weight_category": document.get("load_weight_category"),
        "load_size_category": document.get("load_size_category"),
        "load_description": document.get("load_description"),
        "preferred_pickup_date": document.get("preferred_pickup_date"),
        "preferred_pickup_time": document.get("preferred_pickup_time"),
        "expected_delivery_time": _serialize_datetime(document.get("expected_delivery_time")),
        "urgency": document.get("urgency"),
        "proposed_charge": document.get("proposed_charge"),
        "approved_charge": document.get("approved_charge"),
        "pricing_status": document.get("pricing_status"),
        "pricing_notes": document.get("pricing_notes"),
        "distance_estimate_km": document.get("distance_estimate_km"),
        "fuel_estimate_amount": document.get("fuel_estimate_amount"),
        "fuel_estimate_cost": document.get("fuel_estimate_cost"),
        "other_expected_costs": document.get("other_expected_costs"),
        "expected_net_revenue": document.get("expected_net_revenue"),
        "payment_status": document.get("payment_status"),
        "planning_status": document.get("planning_status"),
        "active_dispatch_job_id": _serialize_reference_id(document.get("active_dispatch_job_id")),
        "schedule_type": document.get("schedule_type"),
        "scheduled_start_time": _serialize_datetime(document.get("scheduled_start_time")),
        "scheduled_end_time": _serialize_datetime(document.get("scheduled_end_time")),
        "expected_return_time": _serialize_datetime(document.get("expected_return_time")),
        "recurrence_pattern": document.get("recurrence_pattern"),
        "recurrence_end_date": document.get("recurrence_end_date"),
        "schedule_notes": document.get("schedule_notes"),
        "stops": [_serialize_stop(stop) for stop in (document.get("stops") or [])],
        "stops_count": document.get("stops_count", len(document.get("stops") or [])),
        "pricing_history": [_serialize_pricing_history(entry) for entry in (document.get("pricing_history") or [])],
        "notes": document.get("notes"),
        "status": document.get("status"),
        "rejection_reason": document.get("rejection_reason"),
        "cancellation_reason": document.get("cancellation_reason"),
        "created_by": _serialize_reference_id(document.get("created_by")),
        "reviewed_by": _serialize_reference_id(document.get("reviewed_by")),
        "approved_by": _serialize_reference_id(document.get("approved_by")),
        "rejected_by": _serialize_reference_id(document.get("rejected_by")),
        "cancelled_by": _serialize_reference_id(document.get("cancelled_by")),
        "pricing_reviewed_by": _serialize_reference_id(document.get("pricing_reviewed_by")),
        "reviewed_at": _serialize_datetime(document.get("reviewed_at")),
        "approved_at": _serialize_datetime(document.get("approved_at")),
        "rejected_at": _serialize_datetime(document.get("rejected_at")),
        "cancelled_at": _serialize_datetime(document.get("cancelled_at")),
        "pricing_reviewed_at": _serialize_datetime(document.get("pricing_reviewed_at")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
    }
