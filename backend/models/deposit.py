from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_deposit(deposit_document: dict) -> dict:
    return {
        "id": str(deposit_document.get("_id")),
        "admin_id": _serialize_reference_id(deposit_document.get("admin_id")),
        "finance_account_id": _serialize_reference_id(deposit_document.get("finance_account_id")),
        "amount": deposit_document.get("amount"),
        "deposit_date": deposit_document.get("deposit_date"),
        "deposit_method": deposit_document.get("deposit_method"),
        "destination_name": deposit_document.get("destination_name"),
        "finance_account_snapshot": deposit_document.get("finance_account_snapshot"),
        "reference_number": deposit_document.get("reference_number"),
        "receipt_image": deposit_document.get("receipt_image"),
        "notes": deposit_document.get("notes"),
        "status": deposit_document.get("status"),
        "submitted_by": _serialize_reference_id(deposit_document.get("submitted_by")),
        "verified_by": _serialize_reference_id(deposit_document.get("verified_by")),
        "rejected_by": _serialize_reference_id(deposit_document.get("rejected_by")),
        "rejection_reason": deposit_document.get("rejection_reason"),
        "submitted_at": deposit_document.get("submitted_at").isoformat()
        if deposit_document.get("submitted_at")
        else None,
        "verified_at": deposit_document.get("verified_at").isoformat()
        if deposit_document.get("verified_at")
        else None,
        "rejected_at": deposit_document.get("rejected_at").isoformat()
        if deposit_document.get("rejected_at")
        else None,
        "created_at": deposit_document.get("created_at").isoformat()
        if deposit_document.get("created_at")
        else None,
        "updated_at": deposit_document.get("updated_at").isoformat()
        if deposit_document.get("updated_at")
        else None,
    }
