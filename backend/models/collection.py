from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_collection(collection_document: dict) -> dict:
    return {
        "id": str(collection_document.get("_id")),
        "driver_id": _serialize_reference_id(collection_document.get("driver_id")),
        "vehicle_id": _serialize_reference_id(collection_document.get("vehicle_id")),
        "assignment_id": _serialize_reference_id(collection_document.get("assignment_id")),
        "amount": collection_document.get("amount"),
        "submitted_amount": collection_document.get("submitted_amount"),
        "admin_received_amount": collection_document.get("admin_received_amount"),
        "collection_date": collection_document.get("collection_date"),
        "payment_method": collection_document.get("payment_method"),
        "reference_number": collection_document.get("reference_number"),
        "notes": collection_document.get("notes"),
        "driver_note": collection_document.get("driver_note"),
        "admin_approval_note": collection_document.get("admin_approval_note"),
        "status": collection_document.get("status"),
        "cycle_key": collection_document.get("cycle_key"),
        "week_start": collection_document.get("week_start"),
        "week_end": collection_document.get("week_end"),
        "payment_deadline": collection_document.get("payment_deadline"),
        "rejection_reason": collection_document.get("rejection_reason"),
        "is_late": bool(collection_document.get("is_late")),
        "received_by_admin_id": _serialize_reference_id(
            collection_document.get("received_by_admin_id")
        ),
        "approved_by_admin_id": _serialize_reference_id(
            collection_document.get("approved_by_admin_id")
        ),
        "submitted_by_driver_id": _serialize_reference_id(
            collection_document.get("submitted_by_driver_id")
        ),
        "rejected_by_admin_id": _serialize_reference_id(
            collection_document.get("rejected_by_admin_id")
        ),
        "submitted_at": collection_document.get("submitted_at").isoformat()
        if collection_document.get("submitted_at")
        else None,
        "approved_at": collection_document.get("approved_at").isoformat()
        if collection_document.get("approved_at")
        else None,
        "rejected_at": collection_document.get("rejected_at").isoformat()
        if collection_document.get("rejected_at")
        else None,
        "created_at": collection_document.get("created_at").isoformat()
        if collection_document.get("created_at")
        else None,
        "updated_at": collection_document.get("updated_at").isoformat()
        if collection_document.get("updated_at")
        else None,
    }
