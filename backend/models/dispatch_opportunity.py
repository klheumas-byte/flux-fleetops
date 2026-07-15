from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def serialize_dispatch_opportunity(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "opportunity_id": document.get("opportunity_id"),
        "customer_name": document.get("customer_name"),
        "customer_phone": document.get("customer_phone"),
        "customer_company": document.get("customer_company"),
        "pickup_location": document.get("pickup_location"),
        "destination": document.get("destination"),
        "load_description": document.get("load_description"),
        "load_type": document.get("load_type"),
        "load_weight_category": document.get("load_weight_category"),
        "load_size_category": document.get("load_size_category"),
        "vehicle_type_needed": document.get("vehicle_type_needed"),
        "preferred_pickup_date": document.get("preferred_pickup_date"),
        "preferred_pickup_time": document.get("preferred_pickup_time"),
        "proposed_charge": document.get("proposed_charge"),
        "approved_charge": document.get("approved_charge"),
        "payment_status": document.get("payment_status"),
        "notes": document.get("notes"),
        "review_notes": document.get("review_notes"),
        "clarification_request": document.get("clarification_request"),
        "rejection_reason": document.get("rejection_reason"),
        "withdrawal_reason": document.get("withdrawal_reason"),
        "status": document.get("status"),
        "submitted_by_driver_id": _serialize_reference_id(document.get("submitted_by_driver_id")),
        "reviewed_by": _serialize_reference_id(document.get("reviewed_by")),
        "approved_by": _serialize_reference_id(document.get("approved_by")),
        "rejected_by": _serialize_reference_id(document.get("rejected_by")),
        "withdrawn_by": _serialize_reference_id(document.get("withdrawn_by")),
        "converted_by": _serialize_reference_id(document.get("converted_by")),
        "dispatch_request_id": document.get("dispatch_request_id"),
        "dispatch_request_record_id": _serialize_reference_id(document.get("dispatch_request_record_id")),
        "submitted_at": _serialize_datetime(document.get("submitted_at")),
        "reviewed_at": _serialize_datetime(document.get("reviewed_at")),
        "approved_at": _serialize_datetime(document.get("approved_at")),
        "rejected_at": _serialize_datetime(document.get("rejected_at")),
        "withdrawn_at": _serialize_datetime(document.get("withdrawn_at")),
        "converted_at": _serialize_datetime(document.get("converted_at")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
    }
