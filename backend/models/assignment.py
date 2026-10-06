from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_history(items):
    serialized = []
    for item in items or []:
        row = {}
        for key, value in item.items():
            if isinstance(value, ObjectId):
                row[key] = str(value)
            elif hasattr(value, "isoformat"):
                row[key] = value.isoformat()
            else:
                row[key] = value
        serialized.append(row)
    return serialized


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
        "target_enabled": assignment_document.get("target_enabled", True),
        "target_amount": assignment_document.get("target_amount"),
        "target_frequency": assignment_document.get("target_frequency") or "weekly",
        "operating_mode": assignment_document.get("operating_mode") or "hybrid",
        "remittance_weekly_amount": assignment_document.get("remittance_weekly_amount"),
        "remittance_start_date": assignment_document.get("remittance_start_date"),
        "remittance_end_date": assignment_document.get("remittance_end_date"),
        "remittance_week_pattern": assignment_document.get("remittance_week_pattern") or "mon_sat",
        "remittance_payment_deadline": assignment_document.get("remittance_payment_deadline") or "week_end",
        "remittance_status": assignment_document.get("remittance_status"),
        "remittance_rate_history": _serialize_history(assignment_document.get("remittance_rate_history")),
        "remittance_status_history": _serialize_history(assignment_document.get("remittance_status_history")),
        "remittance_agreement_history": _serialize_history(assignment_document.get("remittance_agreement_history")),
        "start_date": assignment_document.get("start_date"),
        "start_time": assignment_document.get("start_time").isoformat()
        if hasattr(assignment_document.get("start_time"), "isoformat")
        else assignment_document.get("start_time"),
        "expected_end_at": assignment_document.get("expected_end_at").isoformat()
        if hasattr(assignment_document.get("expected_end_at"), "isoformat")
        else assignment_document.get("expected_end_at"),
        "end_date": end_date,
        "status": assignment_document.get("status"),
        "handover_status": assignment_document.get("handover_status")
        or ("handover_not_recorded" if assignment_document.get("status") == "active" else None),
        "handover_sequence": assignment_document.get("handover_sequence"),
        "linked_handover_movement_id": _serialize_reference_id(
            assignment_document.get("linked_handover_movement_id")
        ),
        "previous_custodian_id": _serialize_reference_id(
            assignment_document.get("previous_custodian_id")
        ),
        "handover_accepted_at": assignment_document.get("handover_accepted_at").isoformat()
        if hasattr(assignment_document.get("handover_accepted_at"), "isoformat")
        else assignment_document.get("handover_accepted_at"),
        "assigned_by": assigned_by,
        "assignment_reason": assignment_document.get("assignment_reason"),
        "ended_by": _serialize_reference_id(assignment_document.get("ended_by")),
        "end_reason": assignment_document.get("end_reason"),
        "transferred_from_allocation_id": _serialize_reference_id(
            assignment_document.get("transferred_from_allocation_id")
        ),
        "transferred_to_allocation_id": _serialize_reference_id(
            assignment_document.get("transferred_to_allocation_id")
        ),
        "allocation_active": bool(assignment_document.get("allocation_active")),
        "created_by": assigned_by,
        "created_at": assignment_document.get("created_at").isoformat()
        if assignment_document.get("created_at")
        else None,
        "updated_at": assignment_document.get("updated_at").isoformat()
        if assignment_document.get("updated_at")
        else None,
        "ended_at": end_date,
    }
