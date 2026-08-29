from bson import ObjectId


def _value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    return value


def serialize_integration_record(document: dict) -> dict:
    return _value({**document, "id": document.get("_id")})
