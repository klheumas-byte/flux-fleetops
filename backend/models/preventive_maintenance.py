from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_preventive_schedule(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "vehicle_id": _serialize_reference_id(document.get("vehicle_id")),
        "maintenance_type": document.get("maintenance_type"),
        "maintenance_item": document.get("maintenance_item") or document.get("maintenance_type"),
        "title": document.get("title"),
        "description": document.get("description"),
        "notes": document.get("notes"),
        "recurrence_type": document.get("recurrence_type"),
        "schedule_type": document.get("schedule_type"),
        "interval_days": document.get("interval_days"),
        "interval_months": document.get("interval_months"),
        "interval_km": document.get("interval_km"),
        "last_done_date": document.get("last_done_date"),
        "last_done_odometer": document.get("last_done_odometer"),
        "next_due_date": document.get("next_due_date"),
        "next_due_odometer": document.get("next_due_odometer"),
        "warning_days_before": document.get("warning_days_before"),
        "warning_km_before": document.get("warning_km_before"),
        "assigned_admin_id": _serialize_reference_id(document.get("assigned_admin_id")),
        "status": document.get("status"),
        "generated_maintenance_job_id": _serialize_reference_id(document.get("generated_maintenance_job_id")),
        "last_notification_status": document.get("last_notification_status"),
        "completed_date": document.get("completed_date"),
        "completed_odometer": document.get("completed_odometer"),
        "mechanic_name": document.get("mechanic_name"),
        "work_done": document.get("work_done"),
        "parts_changed": document.get("parts_changed"),
        "condition_notes": document.get("condition_notes"),
        "completed_by": _serialize_reference_id(document.get("completed_by")),
        "completion_history": [
            {
                **entry,
                "completed_by": _serialize_reference_id(entry.get("completed_by")),
                "completed_at": entry.get("completed_at").isoformat() if hasattr(entry.get("completed_at"), "isoformat") else entry.get("completed_at"),
            }
            for entry in (document.get("completion_history") or [])
        ],
        "created_by": _serialize_reference_id(document.get("created_by")),
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


def serialize_compliance_type(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "item_name": document.get("item_name"),
        "normalized_name": document.get("normalized_name"),
        "category": document.get("category"),
        "status": document.get("status"),
        "created_by": _serialize_reference_id(document.get("created_by")),
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


def serialize_compliance_record(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "vehicle_id": _serialize_reference_id(document.get("vehicle_id")),
        "compliance_type_id": _serialize_reference_id(document.get("compliance_type_id")),
        "compliance_item_name": document.get("compliance_item_name"),
        "provider_or_authority_name": document.get("provider_or_authority_name"),
        "policy_or_reference_number": document.get("policy_or_reference_number"),
        "issue_date": document.get("issue_date"),
        "expiry_date": document.get("expiry_date"),
        "renewal_frequency": document.get("renewal_frequency"),
        "custom_interval_days": document.get("custom_interval_days"),
        "warning_days_before": document.get("warning_days_before"),
        "document_upload": document.get("document_upload"),
        "status": document.get("status"),
        "notes": document.get("notes"),
        "last_notification_marker": document.get("last_notification_marker"),
        "history": [
            {
                **entry,
                "renewed_by": _serialize_reference_id(entry.get("renewed_by")),
                "renewed_at": entry.get("renewed_at").isoformat() if hasattr(entry.get("renewed_at"), "isoformat") else entry.get("renewed_at"),
            }
            for entry in (document.get("history") or [])
        ],
        "created_by": _serialize_reference_id(document.get("created_by")),
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }
