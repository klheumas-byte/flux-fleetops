from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_maintenance_job(maintenance_document: dict) -> dict:
    return {
        "id": str(maintenance_document.get("_id")),
        "vehicle_id": _serialize_reference_id(maintenance_document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(maintenance_document.get("driver_id")),
        "fault_report_id": _serialize_reference_id(maintenance_document.get("fault_report_id")),
        "maintenance_type": maintenance_document.get("maintenance_type"),
        "title": maintenance_document.get("title"),
        "description": maintenance_document.get("description"),
        "priority": maintenance_document.get("priority"),
        "vendor_name": maintenance_document.get("vendor_name"),
        "vendor_contact": maintenance_document.get("vendor_contact"),
        "estimated_cost": maintenance_document.get("estimated_cost"),
        "actual_cost": maintenance_document.get("actual_cost"),
        "expense_id": _serialize_reference_id(maintenance_document.get("expense_id")),
        "odometer_reading": maintenance_document.get("odometer_reading"),
        "start_date": maintenance_document.get("start_date"),
        "target_completion_date": maintenance_document.get("target_completion_date"),
        "completion_date": maintenance_document.get("completion_date"),
        "status": maintenance_document.get("status"),
        "notes": maintenance_document.get("notes"),
        "maintenance_coordinator_id": _serialize_reference_id(
            maintenance_document.get("maintenance_coordinator_id")
        ),
        "assigned_admin_name": maintenance_document.get("assigned_admin_name"),
        "assigned_at": maintenance_document.get("assigned_at").isoformat()
        if maintenance_document.get("assigned_at")
        else None,
        "current_stage": maintenance_document.get("current_stage"),
        "next_action": maintenance_document.get("next_action"),
        "next_follow_up_date": maintenance_document.get("next_follow_up_date"),
        "follow_up_overdue": bool(maintenance_document.get("follow_up_overdue")),
        "is_overdue": bool(maintenance_document.get("is_overdue")),
        "last_progress_updated_at": maintenance_document.get("last_progress_updated_at").isoformat()
        if maintenance_document.get("last_progress_updated_at")
        else None,
        "created_by": _serialize_reference_id(maintenance_document.get("created_by")),
        "approved_by": _serialize_reference_id(maintenance_document.get("approved_by")),
        "completed_by": _serialize_reference_id(maintenance_document.get("completed_by")),
        "created_at": maintenance_document.get("created_at").isoformat()
        if maintenance_document.get("created_at")
        else None,
        "updated_at": maintenance_document.get("updated_at").isoformat()
        if maintenance_document.get("updated_at")
        else None,
    }


def serialize_maintenance_progress_log(progress_document: dict) -> dict:
    return {
        "id": str(progress_document.get("_id")),
        "maintenance_job_id": _serialize_reference_id(progress_document.get("maintenance_job_id")),
        "update_type": progress_document.get("update_type"),
        "progress_note": progress_document.get("progress_note"),
        "current_stage": progress_document.get("current_stage"),
        "next_action": progress_document.get("next_action"),
        "next_follow_up_date": progress_document.get("next_follow_up_date"),
        "updated_by": _serialize_reference_id(progress_document.get("updated_by")),
        "updated_at": progress_document.get("updated_at").isoformat()
        if progress_document.get("updated_at")
        else None,
    }
