from __future__ import annotations

from bson import ObjectId


def _value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_value(item) for item in value]
    return value


def serialize_delivery_exception(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "exception_number": document.get("exception_number"),
        "stock_transfer_id": _value(document.get("stock_transfer_id")),
        "waybill_id": _value(document.get("waybill_id")),
        "movement_id": _value(document.get("movement_id")),
        "driver_id": _value(document.get("driver_id")),
        "status": document.get("status"),
        "items": _value(document.get("items") or []),
        "actual_receiver": _value(document.get("actual_receiver")),
        "receiver_acknowledgement": _value(document.get("receiver_acknowledgement")),
        "current_action": _value(document.get("current_action")),
        "action_history": _value(document.get("action_history") or []),
        "linked_return_request_id": _value(document.get("linked_return_request_id")),
        "linked_replacement_request_id": _value(document.get("linked_replacement_request_id")),
        "linked_replacement_transfer_id": _value(document.get("linked_replacement_transfer_id")),
        "linked_replacement_status": document.get("linked_replacement_status"),
        "operational_status": document.get("operational_status"),
        "resolved_at": _value(document.get("resolved_at")),
        "resolved_by": _value(document.get("resolved_by")),
        "resolution": _value(document.get("resolution")),
        "investigation_id": _value(document.get("investigation_id")),
        "investigation_status": document.get("investigation_status"),
        "notes": document.get("notes"),
        "reported_by": _value(document.get("reported_by")),
        "reported_at": _value(document.get("reported_at")),
        "created_at": _value(document.get("created_at")),
        "updated_at": _value(document.get("updated_at")),
    }
