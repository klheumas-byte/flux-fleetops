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


def serialize_investigation_action(document):
    if not document:
        return None
    return _value({**document, "id": document.get("_id")})


def serialize_delivery_exception_investigation(document, *, actions=None):
    if not document:
        return None
    payload = _value({**document, "id": document.get("_id")})
    payload["linked_actions"] = [serialize_investigation_action(item) for item in (actions or [])]
    return payload
