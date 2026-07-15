from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def serialize_resource_reservation(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "reservation_type": document.get("reservation_type"),
        "resource_id": _serialize_reference_id(document.get("resource_id")),
        "dispatch_job_id": _serialize_reference_id(document.get("dispatch_job_id")),
        "dispatch_request_id": _serialize_reference_id(document.get("dispatch_request_id")),
        "start_time": _serialize_datetime(document.get("start_time")),
        "end_time": _serialize_datetime(document.get("end_time")),
        "status": document.get("status"),
        "created_by": _serialize_reference_id(document.get("created_by")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
        "released_at": _serialize_datetime(document.get("released_at")),
        "release_reason": document.get("release_reason"),
    }
