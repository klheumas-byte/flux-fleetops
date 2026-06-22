from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_expense(expense_document: dict) -> dict:
    return {
        "id": str(expense_document.get("_id")),
        "expense_title": expense_document.get("expense_title"),
        "expense_category": expense_document.get("expense_category"),
        "amount": expense_document.get("amount"),
        "expense_date": expense_document.get("expense_date"),
        "vehicle_id": _serialize_reference_id(expense_document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(expense_document.get("driver_id")),
        "finance_account_id": _serialize_reference_id(expense_document.get("finance_account_id")),
        "finance_account_snapshot": expense_document.get("finance_account_snapshot"),
        "payment_method": expense_document.get("payment_method"),
        "reference_number": expense_document.get("reference_number"),
        "receipt_image": expense_document.get("receipt_image"),
        "notes": expense_document.get("notes"),
        "status": expense_document.get("status"),
        "requested_by": _serialize_reference_id(expense_document.get("requested_by")),
        "approved_by": _serialize_reference_id(expense_document.get("approved_by")),
        "paid_by": _serialize_reference_id(expense_document.get("paid_by")),
        "rejected_by": _serialize_reference_id(expense_document.get("rejected_by")),
        "approved_at": expense_document.get("approved_at").isoformat()
        if expense_document.get("approved_at")
        else None,
        "rejected_at": expense_document.get("rejected_at").isoformat()
        if expense_document.get("rejected_at")
        else None,
        "paid_at": expense_document.get("paid_at").isoformat() if expense_document.get("paid_at") else None,
        "rejection_reason": expense_document.get("rejection_reason"),
        "created_at": expense_document.get("created_at").isoformat()
        if expense_document.get("created_at")
        else None,
        "updated_at": expense_document.get("updated_at").isoformat()
        if expense_document.get("updated_at")
        else None,
    }
