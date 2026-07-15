from bson import ObjectId
from datetime import date, datetime


def _serialize_datetime(value):
    """Serialize both current BSON datetimes and legacy string/date values safely."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_fault(fault_document: dict) -> dict:
    return {
        "id": str(fault_document.get("_id")),
        "vehicle_id": _serialize_reference_id(fault_document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(fault_document.get("driver_id")),
        "category_id": _serialize_reference_id(fault_document.get("category_id")),
        "component_id": _serialize_reference_id(fault_document.get("component_id")),
        "severity": fault_document.get("severity"),
        "description": fault_document.get("description"),
        "photos": fault_document.get("photos") or [],
        "vehicle_unsafe": bool(fault_document.get("vehicle_unsafe")),
        "status": fault_document.get("status"),
        "admin_notes": fault_document.get("admin_notes"),
        "owner_notes": fault_document.get("owner_notes"),
        "resolution_notes": fault_document.get("resolution_notes"),
        "maintenance_job_id": _serialize_reference_id(fault_document.get("maintenance_job_id")),
        "reported_at": _serialize_datetime(fault_document.get("reported_at")),
        "reviewed_by": _serialize_reference_id(fault_document.get("reviewed_by")),
        "reviewed_at": _serialize_datetime(fault_document.get("reviewed_at")),
        "approved_at": _serialize_datetime(fault_document.get("approved_at")),
        "rejected_at": _serialize_datetime(fault_document.get("rejected_at")),
        "rejection_reason": fault_document.get("rejection_reason"),
        "requested_info_at": _serialize_datetime(fault_document.get("requested_info_at")),
        "request_info_note": fault_document.get("request_info_note"),
        "clarification_responded_at": _serialize_datetime(fault_document.get("clarification_responded_at")),
        "converted_to_maintenance_by": _serialize_reference_id(
            fault_document.get("converted_to_maintenance_by")
        ),
        "converted_to_maintenance_at": _serialize_datetime(fault_document.get("converted_to_maintenance_at")),
        "resolved_at": _serialize_datetime(fault_document.get("resolved_at")),
        "created_by": _serialize_reference_id(fault_document.get("created_by")),
        "updated_by": _serialize_reference_id(fault_document.get("updated_by")),
        "approved_by": _serialize_reference_id(fault_document.get("approved_by")),
        "rejected_by": _serialize_reference_id(fault_document.get("rejected_by")),
        "requested_info_by": _serialize_reference_id(fault_document.get("requested_info_by")),
        "converted_by": _serialize_reference_id(fault_document.get("converted_by")),
        "created_at": _serialize_datetime(fault_document.get("created_at")),
        "updated_at": _serialize_datetime(fault_document.get("updated_at")),
    }
