from __future__ import annotations

from bson import ObjectId


def _value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _serialize_mapping(document: dict | None) -> dict | None:
    if document is None:
        return None
    return {key: _value(value) for key, value in document.items()}


def serialize_waybill(document: dict, *, include_audit: bool = False) -> dict:
    payload = {
        "id": str(document.get("_id")),
        "waybill_number": document.get("waybill_number"),
        "source_type": document.get("source_type"),
        "source_id": _value(document.get("source_id")),
        "source_key": document.get("source_key"),
        "source_reference": document.get("source_reference"),
        "movement_id": _value(document.get("movement_id")),
        "vehicle_id": _value(document.get("vehicle_id")),
        "driver_id": _value(document.get("driver_id")),
        "scheduled_at": _value(document.get("scheduled_at")),
        "origin": document.get("origin"),
        "destination": document.get("destination"),
        "recipient": _serialize_mapping(document.get("recipient")),
        "actual_receiver": _serialize_mapping(document.get("actual_receiver")),
        "linked_delivery_exception_id": _value(document.get("linked_delivery_exception_id")),
        "delivery_exception_status": document.get("delivery_exception_status"),
        "delivery_exception_summary": _serialize_mapping(document.get("delivery_exception_summary")),
        "locked_at": _value(document.get("locked_at")),
        "receipt_pending": bool(document.get("receipt_pending")),
        "status": document.get("status"),
        "items": document.get("items") or [],
        "item_count": len(document.get("items") or []),
        "has_variance": bool(document.get("has_variance")),
        "variance_review": _serialize_mapping(document.get("variance_review")),
        "confirmations": [
            _serialize_mapping(item) for item in (document.get("confirmations") or [])
        ],
        "custody_events": [
            _serialize_mapping(item) for item in (document.get("custody_events") or [])
        ],
        "signatures": {
            party: _serialize_mapping(signature)
            for party, signature in (document.get("signatures") or {}).items()
        },
        "notes": document.get("notes"),
        "approved_by": _value(document.get("approved_by")),
        "approved_at": _value(document.get("approved_at")),
        "driver_confirmed_at": _value(document.get("driver_confirmed_at")),
        "loaded_at": _value(document.get("loaded_at")),
        "in_transit_at": _value(document.get("in_transit_at")),
        "delivered_at": _value(document.get("delivered_at")),
        "verified_at": _value(document.get("verified_at")),
        "completed_at": _value(document.get("completed_at")),
        "created_by": _value(document.get("created_by")),
        "created_at": _value(document.get("created_at")),
        "updated_at": _value(document.get("updated_at")),
        "version": int(document.get("version") or 1),
    }
    if include_audit:
        payload["audit_log"] = [
            _serialize_mapping(item) for item in (document.get("audit_log") or [])
        ]
    return payload
