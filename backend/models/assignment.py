from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_assignment(assignment_document: dict) -> dict:
    end_date = assignment_document.get("end_date")
    assigned_by = _serialize_reference_id(
        assignment_document.get("assigned_by") or assignment_document.get("created_by")
    )

    return {
        "id": str(assignment_document.get("_id")),
        "driver_id": _serialize_reference_id(assignment_document.get("driver_id")),
        "vehicle_id": _serialize_reference_id(assignment_document.get("vehicle_id")),
        "weekly_target": assignment_document.get("weekly_target"),
        "daily_target": assignment_document.get("daily_target"),
        "start_date": assignment_document.get("start_date"),
        "end_date": end_date,
        "status": assignment_document.get("status"),
        "assigned_by": assigned_by,
        "created_by": assigned_by,
        "created_at": assignment_document.get("created_at").isoformat()
        if assignment_document.get("created_at")
        else None,
        "updated_at": assignment_document.get("updated_at").isoformat()
        if assignment_document.get("updated_at")
        else None,
        "ended_at": end_date,
    }
