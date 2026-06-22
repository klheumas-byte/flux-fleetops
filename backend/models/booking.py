from datetime import timezone

from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def serialize_booking(booking_document: dict) -> dict:
    reminder_flags = booking_document.get("reminder_flags") or {}
    recurrence = booking_document.get("recurrence") or {}
    issue_history = booking_document.get("issue_history") or []

    return {
        "id": str(booking_document.get("_id")),
        "booking_id": booking_document.get("booking_id"),
        "customer_id": _serialize_reference_id(booking_document.get("customer_id")),
        "driver_id": _serialize_reference_id(booking_document.get("driver_id")),
        "vehicle_id": _serialize_reference_id(booking_document.get("vehicle_id")),
        "booking_type": booking_document.get("booking_type"),
        "pickup_date": booking_document.get("pickup_date"),
        "pickup_time": booking_document.get("pickup_time"),
        "pickup_location": booking_document.get("pickup_location"),
        "destination": booking_document.get("destination"),
        "expected_fare": booking_document.get("expected_fare"),
        "title": booking_document.get("title"),
        "description": booking_document.get("description"),
        "notes": booking_document.get("notes"),
        "status": booking_document.get("status"),
        "priority": booking_document.get("priority"),
        "assigned_to": _serialize_reference_id(booking_document.get("assigned_to")),
        "completed_by": _serialize_reference_id(booking_document.get("completed_by")),
        "reminder_date": booking_document.get("reminder_date"),
        "reminder_time": booking_document.get("reminder_time"),
        "reminder_sent": any(bool(value) for value in reminder_flags.values()),
        "reminder_flags": reminder_flags,
        "created_by": _serialize_reference_id(booking_document.get("created_by")),
        "created_at": _serialize_datetime(booking_document.get("created_at")),
        "updated_at": _serialize_datetime(booking_document.get("updated_at")),
        "source_booking_id": _serialize_reference_id(booking_document.get("source_booking_id")),
        "is_recurring_template": bool(booking_document.get("is_recurring_template")),
        "generated_from_recurring": bool(booking_document.get("generated_from_recurring")),
        "recurrence_type": recurrence.get("recurrence_type"),
        "recurrence_frequency": recurrence.get("recurrence_frequency"),
        "recurrence_days": recurrence.get("recurrence_days") or [],
        "monthly_week_of_month": recurrence.get("monthly_week_of_month"),
        "monthly_day_of_week": recurrence.get("monthly_day_of_week"),
        "custom_rule_text": recurrence.get("custom_rule_text"),
        "recurrence_end_date": recurrence.get("recurrence_end_date"),
        "pickup_at": _serialize_datetime(booking_document.get("pickup_at")),
        "acknowledged_by": _serialize_reference_id(booking_document.get("acknowledged_by")),
        "acknowledged_at": _serialize_datetime(booking_document.get("acknowledged_at")),
        "en_route_at": _serialize_datetime(booking_document.get("en_route_at")),
        "picked_up_at": _serialize_datetime(booking_document.get("picked_up_at")),
        "completed_at": _serialize_datetime(booking_document.get("completed_at")),
        "completion_note": booking_document.get("completion_note"),
        "issue_type": booking_document.get("issue_type"),
        "issue_note": booking_document.get("issue_note"),
        "issue_reported_at": _serialize_datetime(booking_document.get("issue_reported_at")),
        "trip_log_id": _serialize_reference_id(booking_document.get("trip_log_id")),
        "issue_history": [
            {
                "issue_type": event.get("issue_type"),
                "issue_note": event.get("issue_note"),
                "reported_at": _serialize_datetime(event.get("reported_at")),
                "reported_by": _serialize_reference_id(event.get("reported_by")),
            }
            for event in issue_history
        ],
        "activity_kind": booking_document.get("activity_kind"),
        "activity_color": booking_document.get("activity_color"),
        "is_overdue": bool(booking_document.get("is_overdue")),
        "is_personal_reminder": bool(booking_document.get("is_personal_reminder")),
        "is_follow_up_reminder": bool(booking_document.get("is_follow_up_reminder")),
        "is_company_event": bool(booking_document.get("is_company_event")),
        "audit_events": [
            {
                "action": event.get("action"),
                "at": _serialize_datetime(event.get("at")),
                "by": _serialize_reference_id(event.get("by")),
                "changes": event.get("changes") or [],
                "note": event.get("note"),
            }
            for event in booking_document.get("audit_events", [])
        ],
    }
