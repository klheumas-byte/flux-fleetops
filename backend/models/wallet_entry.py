from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_wallet_entry(wallet_entry_document: dict) -> dict:
    return {
        "id": str(wallet_entry_document.get("_id")),
        "driver_id": _serialize_reference_id(wallet_entry_document.get("driver_id")),
        "vehicle_id": _serialize_reference_id(wallet_entry_document.get("vehicle_id")),
        "assignment_id": _serialize_reference_id(wallet_entry_document.get("assignment_id")),
        "type": wallet_entry_document.get("type"),
        "description": wallet_entry_document.get("description"),
        "debit": wallet_entry_document.get("debit"),
        "credit": wallet_entry_document.get("credit"),
        "balance_after": wallet_entry_document.get("balance_after"),
        "reference_id": _serialize_reference_id(wallet_entry_document.get("reference_id")),
        "created_by": _serialize_reference_id(wallet_entry_document.get("created_by")),
        "created_at": wallet_entry_document.get("created_at").isoformat()
        if wallet_entry_document.get("created_at")
        else None,
    }
