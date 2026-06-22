from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_finance_account(account_document: dict) -> dict:
    return {
        "id": str(account_document.get("_id")),
        "account_name": account_document.get("account_name"),
        "account_type": account_document.get("account_type"),
        "provider_name": account_document.get("provider_name"),
        "account_number": account_document.get("account_number"),
        "branch": account_document.get("branch"),
        "opening_balance": account_document.get("opening_balance"),
        "current_balance": account_document.get("current_balance"),
        "status": account_document.get("status"),
        "created_by": _serialize_reference_id(account_document.get("created_by")),
        "created_at": account_document.get("created_at").isoformat()
        if account_document.get("created_at")
        else None,
        "updated_at": account_document.get("updated_at").isoformat()
        if account_document.get("updated_at")
        else None,
    }


def serialize_finance_account_snapshot(account_document: dict) -> dict:
    return {
        "id": str(account_document.get("_id")) if account_document.get("_id") else None,
        "account_name": account_document.get("account_name"),
        "account_type": account_document.get("account_type"),
        "provider_name": account_document.get("provider_name"),
        "account_number": account_document.get("account_number"),
        "branch": account_document.get("branch"),
        "status": account_document.get("status"),
    }
