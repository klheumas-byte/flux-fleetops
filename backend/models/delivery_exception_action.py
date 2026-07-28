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


def serialize_return_request(document):
    if not document:
        return None
    return _value({**document, "id": document.get("_id")})


def serialize_replacement_request(document):
    if not document:
        return None
    return _value({**document, "id": document.get("_id")})
