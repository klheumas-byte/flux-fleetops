from bson import ObjectId


def _value(value):
    return str(value) if isinstance(value, ObjectId) else value


def _datetime(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def serialize_funding_contribution(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "funding_source_id": _value(document.get("funding_source_id")),
        "funding_source_snapshot": document.get("funding_source_snapshot"),
        "funding_source_description": document.get("funding_source_description"),
        "finance_account_id": _value(document.get("finance_account_id")),
        "finance_account_snapshot": document.get("finance_account_snapshot"),
        "amount": document.get("amount"),
        "contribution_date": document.get("contribution_date"),
        "description": document.get("description"),
        "reference_number": document.get("reference_number"),
        "receipt_image": document.get("receipt_image"),
        "notes": document.get("notes"),
        "recorded_by": _value(document.get("recorded_by")),
        "idempotency_key": document.get("idempotency_key"),
        "created_at": _datetime(document.get("created_at")),
        "updated_at": _datetime(document.get("updated_at")),
        "audit_log": [
            {**item, "actor_id": _value(item.get("actor_id")), "at": _datetime(item.get("at"))}
            for item in document.get("audit_log", [])
        ],
    }
