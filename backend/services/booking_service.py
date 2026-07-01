from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from bson import ObjectId
from flask import current_app
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.booking import serialize_booking
from models.customer import serialize_customer
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.master_data_service import assert_master_data_value, get_active_master_data_values
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached


BOOKING_STATUSES = {
    "Scheduled",
    "Acknowledged",
    "En Route",
    "Picked Up",
    "Completed",
    "Cancelled",
    "Missed",
}
BOOKING_PRIORITIES = {"Low", "Medium", "High", "Critical"}
REMINDER_BOOKING_TYPES = {
    "Follow-Up Reminder",
    "Personal Reminder",
    "Maintenance Reminder",
    "Insurance Renewal Reminder",
    "Vehicle Inspection Reminder",
}
FOLLOW_UP_BOOKING_TYPES = {"Follow-Up Reminder"}
PERSONAL_REMINDER_BOOKING_TYPES = {"Personal Reminder"}
COMPANY_EVENT_BOOKING_TYPES = {"Staff Assignment"}
CUSTOMER_REQUIRED_BOOKING_TYPES = {
    "Customer Booking",
    "Airport Pickup",
    "Corporate Booking",
    "Church Pickup",
    "School Pickup",
    "VIP Booking",
}
CORPORATE_BOOKING_TYPES = {"Corporate Booking"}
VIP_BOOKING_TYPES = {"VIP Booking"}
STRATEGIC_BOOKING_TYPES = {"Follow-Up Reminder", "VIP Booking", "Corporate Booking"}
DRIVER_ACTIONABLE_BOOKING_STATUSES = {"Scheduled", "Acknowledged", "En Route", "Picked Up"}
IN_PROGRESS_BOOKING_STATUSES = {"Acknowledged", "En Route", "Picked Up"}
ACTIVE_BOOKING_STATUSES = {"Scheduled", "Acknowledged", "En Route", "Picked Up"}
ISSUE_TYPES = {
    "customer cancelled",
    "customer not reachable",
    "pickup delayed",
    "vehicle issue",
    "other",
}
RECURRENCE_TYPES = {"Daily", "Weekly", "Monthly", "Custom", "One Time"}
CALENDAR_VIEWS = {"today", "tomorrow", "this-week", "upcoming", "overdue", "completed"}
WEEKDAY_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}
WEEKDAY_BY_INDEX = {value: key for key, value in WEEKDAY_INDEX.items()}
BOOKING_LIST_PROJECTION = {
    "booking_id": 1,
    "customer_id": 1,
    "driver_id": 1,
    "assigned_to": 1,
    "vehicle_id": 1,
    "booking_type": 1,
    "title": 1,
    "description": 1,
    "pickup_date": 1,
    "pickup_time": 1,
    "reminder_date": 1,
    "reminder_time": 1,
    "pickup_location": 1,
    "destination": 1,
    "expected_fare": 1,
    "priority": 1,
    "notes": 1,
    "status": 1,
    "created_by": 1,
    "created_at": 1,
    "updated_at": 1,
    "pickup_at": 1,
    "recurrence": 1,
    "source_booking_id": 1,
    "is_recurring_template": 1,
    "generated_from_recurring": 1,
    "activity_kind": 1,
    "activity_color": 1,
    "is_overdue": 1,
    "is_personal_reminder": 1,
    "is_follow_up_reminder": 1,
    "is_company_event": 1,
    "overdue_notified_at": 1,
    "missed_notified_at": 1,
    "acknowledged_by": 1,
    "acknowledged_at": 1,
    "en_route_at": 1,
    "picked_up_at": 1,
    "completed_at": 1,
    "completed_by": 1,
    "completion_note": 1,
    "issue_type": 1,
    "issue_note": 1,
    "issue_reported_at": 1,
    "trip_log_id": 1,
}


def now_utc():
    return datetime.now(timezone.utc)


def _as_utc_datetime(value: Any):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def bookings_collection():
    return get_collection("bookings")


def customers_collection():
    return get_collection("customers")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def ensure_booking_indexes():
    ensure_indexes_for_collection(
        bookings_collection(),
        [
            {"keys": [("booking_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("customer_id", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("pickup_at", ASCENDING)]},
            {"keys": [("pickup_date", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("is_recurring_template", ASCENDING), ("pickup_at", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("pickup_at", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("pickup_at", ASCENDING)]},
            {"keys": [("customer_id", ASCENDING), ("pickup_at", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("source_booking_id", ASCENDING)]},
            {"keys": [("is_recurring_template", ASCENDING)]},
            {"keys": [("created_by", ASCENDING)]},
            {"keys": [("is_recurring_template", ASCENDING), ("status", ASCENDING), ("pickup_at", ASCENDING)]},
            {"keys": [("is_recurring_template", ASCENDING), ("driver_id", ASCENDING), ("status", ASCENDING), ("pickup_at", ASCENDING)]},
            {"keys": [("is_recurring_template", ASCENDING), ("booking_type", ASCENDING), ("status", ASCENDING), ("pickup_at", ASCENDING)]},
        ],
        collection_name="bookings",
    )


def _empty_booking_dashboard_summary() -> dict:
    return {
        "upcoming_bookings": 0,
        "missed_bookings": 0,
        "active_recurring_customers": 0,
        "total_customers": 0,
        "total_recurring_customers": 0,
        "today_schedule": 0,
        "upcoming_pickups": 0,
        "recent_customers": 0,
        "customer_growth_trend": [
            {"label": "Last 30 days", "value": 0},
            {"label": "Last 90 days", "value": 0},
        ],
        "scheduled_today": 0,
        "total_scheduled_bookings": 0,
        "pending_acknowledgement": 0,
        "in_progress_bookings": 0,
        "completed_today": 0,
        "overdue_reminders": 0,
        "follow_ups_due_today": 0,
        "upcoming_corporate_bookings": 0,
        "total_future_bookings": 0,
        "vip_bookings": 0,
        "strategic_meetings": 0,
        "driver_schedules": 0,
        "follow_up_completion_rate": 0.0,
        "bookings_by_status": {status: 0 for status in BOOKING_STATUSES},
    }


def _to_object_id(value, field_name: str, *, required: bool = True):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _normalize_text(value: Any):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_booking_status(value: str | None):
    normalized = _normalize_text(value) or "Scheduled"
    legacy_status_map = {
        "Confirmed": "Acknowledged",
        "In Progress": "En Route",
    }
    normalized = legacy_status_map.get(normalized, normalized)
    if normalized not in BOOKING_STATUSES:
        raise ApiError("Invalid booking status.", status_code=400)
    return normalized


def _normalize_booking_type(value: str | None):
    normalized = _normalize_text(value)
    if not normalized:
        raise ApiError("booking_type is required.", status_code=400)
    return assert_master_data_value("booking_types", normalized)


def _normalize_booking_priority(value: str | None):
    normalized = _normalize_text(value) or "Medium"
    normalized = normalized.title()
    if normalized not in BOOKING_PRIORITIES:
        raise ApiError("priority must be Low, Medium, High, or Critical.", status_code=400)
    return normalized


def _parse_pickup_datetime(pickup_date: str | None, pickup_time: str | None):
    if not pickup_date:
        raise ApiError("pickup_date is required.", status_code=400)
    if not pickup_time:
        raise ApiError("pickup_time is required.", status_code=400)
    try:
        parsed = datetime.fromisoformat(f"{pickup_date}T{pickup_time}")
    except ValueError as error:
        raise ApiError("pickup_date and pickup_time must be valid ISO values.", status_code=400) from error
    return parsed.replace(tzinfo=timezone.utc)


def _activity_kind_for_booking_type(booking_type: str):
    if booking_type in PERSONAL_REMINDER_BOOKING_TYPES:
        return "personal_reminder"
    if booking_type in FOLLOW_UP_BOOKING_TYPES:
        return "follow_up"
    if booking_type in REMINDER_BOOKING_TYPES:
        return "reminder"
    if booking_type in COMPANY_EVENT_BOOKING_TYPES:
        return "company_event"
    return "customer_booking"


def _activity_color(booking_type: str, status: str | None, priority: str | None):
    normalized_status = _map_booking_status_for_display(status)
    if normalized_status == "Completed":
        return "green"
    if priority == "Critical":
        return "red"
    if booking_type in PERSONAL_REMINDER_BOOKING_TYPES:
        return "purple"
    if booking_type in FOLLOW_UP_BOOKING_TYPES:
        return "orange"
    return "blue"


def _serialize_audit_event(*, action: str, user_id: str, changes: list[str], note: str | None = None):
    return {
        "action": action,
        "at": now_utc(),
        "by": _to_object_id(user_id, "user_id"),
        "changes": changes,
        "note": note,
    }


def _normalize_issue_type(value: Any):
    normalized = _normalize_text(value)
    if not normalized:
        raise ApiError("issue_type is required.", status_code=400)
    lowered = normalized.lower()
    if lowered not in ISSUE_TYPES:
        raise ApiError("Invalid issue_type.", status_code=400)
    return lowered


def _map_booking_status_for_display(status: str | None):
    if status == "Confirmed":
        return "Acknowledged"
    if status == "In Progress":
        return "En Route"
    return status or "Scheduled"


def _build_booking_id():
    sequence = bookings_collection().count_documents({}) + 1
    return f"BKG-{sequence:05d}"


def _get_driver_document(driver_id: str | None):
    if driver_id in (None, ""):
        return None
    driver = users_collection().find_one({"_id": _to_object_id(driver_id, "driver_id"), "role": "driver"})
    if not driver:
        raise ApiError("Driver not found.", status_code=404)
    return driver


def _get_vehicle_document(vehicle_id: str | None):
    if vehicle_id in (None, ""):
        return None
    vehicle = vehicles_collection().find_one({"_id": _to_object_id(vehicle_id, "vehicle_id")})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _get_customer_document(customer_id: str):
    customer = customers_collection().find_one({"_id": _to_object_id(customer_id, "customer_id")})
    if not customer:
        raise ApiError("Customer not found.", status_code=404)
    return customer


def _get_booking_document(booking_id: str):
    booking = bookings_collection().find_one({"_id": _to_object_id(booking_id, "booking_id")})
    if not booking:
        raise ApiError("Booking not found.", status_code=404)
    return booking


def _assert_customer_visibility(customer_document: dict, *, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    if current_role != "driver" or str(customer_document.get("created_by")) != current_user_id:
        raise ApiError("You do not have permission to book this customer.", status_code=403)


def _assert_booking_access(booking_document: dict, *, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    driver_id = str(booking_document.get("driver_id")) if booking_document.get("driver_id") else None
    created_by = str(booking_document.get("created_by")) if booking_document.get("created_by") else None
    if current_role != "driver" or current_user_id not in {driver_id, created_by}:
        raise ApiError("You do not have permission to access this booking.", status_code=403)


def _enrich_booking(
    booking_document: dict,
    *,
    customer_map: dict[str, dict] | None = None,
    driver_map: dict[str, dict] | None = None,
    vehicle_map: dict[str, dict] | None = None,
    user_map: dict[str, dict] | None = None,
) -> dict:
    if booking_document.get("status") in {"Confirmed", "In Progress"}:
        booking_document = {**booking_document, "status": _map_booking_status_for_display(booking_document.get("status"))}
    pickup_at = _as_utc_datetime(booking_document.get("pickup_at"))
    normalized_status = _map_booking_status_for_display(booking_document.get("status"))
    booking_type = booking_document.get("booking_type") or "Customer Booking"
    priority = booking_document.get("priority") or "Medium"
    booking_document = {
        **booking_document,
        "assigned_to": booking_document.get("assigned_to") or booking_document.get("driver_id"),
        "activity_kind": booking_document.get("activity_kind") or _activity_kind_for_booking_type(booking_type),
        "activity_color": _activity_color(booking_type, normalized_status, priority),
        "is_overdue": bool(pickup_at and pickup_at < now_utc() and normalized_status not in {"Completed", "Cancelled", "Missed"}),
        "is_personal_reminder": booking_type in PERSONAL_REMINDER_BOOKING_TYPES,
        "is_follow_up_reminder": booking_type in FOLLOW_UP_BOOKING_TYPES,
        "is_company_event": booking_type in COMPANY_EVENT_BOOKING_TYPES,
    }
    booking = serialize_booking(booking_document)
    customer = None
    driver = None
    vehicle = None
    created_by_user = None
    if customer_map is not None and booking_document.get("customer_id"):
        customer = customer_map.get(str(booking_document.get("customer_id")))
    elif booking_document.get("customer_id"):
        customer = customers_collection().find_one({"_id": booking_document.get("customer_id")})
    if driver_map is not None and booking_document.get("driver_id"):
        driver = driver_map.get(str(booking_document.get("driver_id")))
    elif booking_document.get("driver_id"):
        driver = users_collection().find_one({"_id": booking_document.get("driver_id")})
    if vehicle_map is not None and booking_document.get("vehicle_id"):
        vehicle = vehicle_map.get(str(booking_document.get("vehicle_id")))
    elif booking_document.get("vehicle_id"):
        vehicle = vehicles_collection().find_one({"_id": booking_document.get("vehicle_id")})
    if user_map is not None and booking_document.get("created_by"):
        created_by_user = user_map.get(str(booking_document.get("created_by")))
    elif booking_document.get("created_by"):
        created_by_user = users_collection().find_one({"_id": booking_document.get("created_by")})
    booking["customer"] = serialize_customer(customer) if customer else None
    booking["driver"] = serialize_user(driver) if driver else None
    booking["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
    booking["created_by_user"] = serialize_user(created_by_user) if created_by_user else None
    return booking


def _load_booking_relationship_maps(booking_documents: list[dict]) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict]]:
    customer_ids = {document.get("customer_id") for document in booking_documents if document.get("customer_id")}
    driver_ids = {document.get("driver_id") for document in booking_documents if document.get("driver_id")}
    vehicle_ids = {document.get("vehicle_id") for document in booking_documents if document.get("vehicle_id")}
    user_ids = {document.get("created_by") for document in booking_documents if document.get("created_by")}

    customer_map = {}
    driver_map = {}
    vehicle_map = {}
    user_map = {}

    if customer_ids:
        started_at = perf_counter()
        customer_map = {
            str(item["_id"]): item
            for item in customers_collection().find({"_id": {"$in": list(customer_ids)}})
        }
        log_db_duration("bookings.load_customers", started_at)
    if driver_ids:
        started_at = perf_counter()
        driver_map = {
            str(item["_id"]): item
            for item in users_collection().find({"_id": {"$in": list(driver_ids)}})
        }
        log_db_duration("bookings.load_drivers", started_at)
    if vehicle_ids:
        started_at = perf_counter()
        vehicle_map = {
            str(item["_id"]): item
            for item in vehicles_collection().find({"_id": {"$in": list(vehicle_ids)}})
        }
        log_db_duration("bookings.load_vehicles", started_at)
    if user_ids:
        started_at = perf_counter()
        user_map = {
            str(item["_id"]): item
            for item in users_collection().find({"_id": {"$in": list(user_ids)}})
        }
        log_db_duration("bookings.load_created_by_users", started_at)

    return customer_map, driver_map, vehicle_map, user_map


def _normalize_recurrence(payload: dict):
    recurrence_type = _normalize_text(payload.get("recurrence_type"))
    if not recurrence_type:
        return None
    if recurrence_type == "One Time":
        return None
    if recurrence_type not in RECURRENCE_TYPES:
        raise ApiError("Invalid recurrence_type.", status_code=400)

    recurrence_frequency = payload.get("recurrence_interval", payload.get("recurrence_frequency", 1))
    if isinstance(recurrence_frequency, bool) or not isinstance(recurrence_frequency, int) or recurrence_frequency <= 0:
        raise ApiError("recurrence_frequency must be a positive integer.", status_code=400)

    recurrence_days = payload.get("recurrence_days") or []
    normalized_days = []
    if recurrence_days:
        if not isinstance(recurrence_days, list):
            raise ApiError("recurrence_days must be an array.", status_code=400)
        for day in recurrence_days:
            normalized_day = _normalize_text(day)
            if normalized_day not in WEEKDAY_INDEX:
                raise ApiError("recurrence_days must contain valid weekday names.", status_code=400)
            normalized_days.append(normalized_day)

    monthly_week_of_month = payload.get("monthly_week_of_month")
    if monthly_week_of_month is not None:
        if isinstance(monthly_week_of_month, bool) or not isinstance(monthly_week_of_month, int):
            raise ApiError("monthly_week_of_month must be numeric.", status_code=400)
        if monthly_week_of_month < 1 or monthly_week_of_month > 5:
            raise ApiError("monthly_week_of_month must be between 1 and 5.", status_code=400)

    monthly_day_of_week = _normalize_text(payload.get("monthly_day_of_week"))
    if monthly_day_of_week and monthly_day_of_week not in WEEKDAY_INDEX:
        raise ApiError("monthly_day_of_week must be a valid weekday.", status_code=400)

    return {
        "recurrence_type": recurrence_type,
        "recurrence_frequency": recurrence_frequency,
        "recurrence_interval": recurrence_frequency,
        "recurrence_days": normalized_days,
        "monthly_week_of_month": monthly_week_of_month,
        "monthly_day_of_week": monthly_day_of_week,
        "custom_rule_text": _normalize_text(payload.get("custom_rule_text")),
        "recurrence_end_date": _normalize_text(payload.get("recurrence_end_date")),
    }


def _normalized_booking_payload(payload: dict, *, partial: bool = False) -> dict:
    normalized: dict[str, Any] = {}
    booking_type = None
    if "booking_type" in payload or not partial:
        booking_type = _normalize_booking_type(payload.get("booking_type"))
        if booking_type is not None:
            normalized["booking_type"] = booking_type

    if not partial or "customer_id" in payload:
        customer_id = payload.get("customer_id")
        requires_customer = not booking_type or booking_type in CUSTOMER_REQUIRED_BOOKING_TYPES
        if not partial and requires_customer and not customer_id:
            raise ApiError("customer_id is required.", status_code=400)
        if customer_id:
            normalized["customer_id"] = _to_object_id(customer_id, "customer_id")

    if "driver_id" in payload:
        driver = _get_driver_document(payload.get("driver_id"))
        normalized["driver_id"] = driver["_id"] if driver else None

    if "vehicle_id" in payload:
        vehicle = _get_vehicle_document(payload.get("vehicle_id"))
        normalized["vehicle_id"] = vehicle["_id"] if vehicle else None

    pickup_date = payload.get("pickup_date") if "pickup_date" in payload else None
    pickup_time = payload.get("pickup_time") if "pickup_time" in payload else None
    reminder_date = payload.get("reminder_date") if "reminder_date" in payload else None
    reminder_time = payload.get("reminder_time") if "reminder_time" in payload else None
    effective_date = pickup_date if pickup_date is not None else reminder_date
    effective_time = pickup_time if pickup_time is not None else reminder_time
    if not partial or "pickup_date" in payload or "pickup_time" in payload:
        if partial and (effective_date is None or effective_time is None):
            pass
        else:
            normalized["pickup_date"] = _normalize_text(effective_date)
            normalized["pickup_time"] = _normalize_text(effective_time)
            normalized["pickup_at"] = _parse_pickup_datetime(normalized["pickup_date"], normalized["pickup_time"])
    if "reminder_date" in payload or (not partial and booking_type in REMINDER_BOOKING_TYPES):
        normalized["reminder_date"] = _normalize_text(reminder_date or effective_date)
    if "reminder_time" in payload or (not partial and booking_type in REMINDER_BOOKING_TYPES):
        normalized["reminder_time"] = _normalize_text(reminder_time or effective_time)

    if not partial or "pickup_location" in payload:
        pickup_location = _normalize_text(payload.get("pickup_location"))
        requires_location = booking_type not in REMINDER_BOOKING_TYPES
        if not pickup_location and not partial and requires_location:
            raise ApiError("pickup_location is required.", status_code=400)
        if pickup_location is not None:
            normalized["pickup_location"] = pickup_location

    if not partial or "destination" in payload:
        destination = _normalize_text(payload.get("destination"))
        requires_destination = booking_type not in REMINDER_BOOKING_TYPES
        if not destination and not partial and requires_destination:
            raise ApiError("destination is required.", status_code=400)
        if destination is not None:
            normalized["destination"] = destination

    if "expected_fare" in payload:
        expected_fare = payload.get("expected_fare")
        if expected_fare is not None:
            if isinstance(expected_fare, bool) or not isinstance(expected_fare, (int, float)):
                raise ApiError("expected_fare must be numeric.", status_code=400)
            normalized["expected_fare"] = round(float(expected_fare), 2)

    if "notes" in payload:
        normalized["notes"] = _normalize_text(payload.get("notes"))
    if "title" in payload or (not partial and booking_type in REMINDER_BOOKING_TYPES):
        title = _normalize_text(payload.get("title")) or booking_type
        normalized["title"] = title
    if "description" in payload:
        normalized["description"] = _normalize_text(payload.get("description"))
    if "priority" in payload or (not partial and booking_type in REMINDER_BOOKING_TYPES):
        normalized["priority"] = _normalize_booking_priority(payload.get("priority"))

    if not partial or "status" in payload:
        normalized["status"] = _normalize_booking_status(payload.get("status"))

    recurrence = _normalize_recurrence(payload) if any(key in payload for key in (
        "recurrence_type",
        "recurrence_frequency",
        "recurrence_interval",
        "recurrence_days",
        "monthly_week_of_month",
        "monthly_day_of_week",
        "custom_rule_text",
        "recurrence_end_date",
    )) else None
    if recurrence is not None:
        normalized["recurrence"] = recurrence
    return normalized


def _next_daily_occurrence(base_datetime: datetime, candidate: datetime, frequency: int):
    if candidate <= base_datetime:
        candidate += timedelta(days=frequency)
    return candidate


def _next_weekly_occurrences(base_datetime: datetime, recurrence: dict, count: int):
    days = recurrence.get("recurrence_days") or [WEEKDAY_BY_INDEX[base_datetime.weekday()]]
    selected_days = sorted({WEEKDAY_INDEX[day] for day in days})
    occurrences = []
    cursor = base_datetime
    while len(occurrences) < count:
        for weekday in selected_days:
            delta = (weekday - cursor.weekday()) % 7
            candidate = cursor + timedelta(days=delta)
            if candidate <= base_datetime:
                candidate += timedelta(days=7 * recurrence["recurrence_frequency"])
            occurrences.append(candidate)
            if len(occurrences) == count:
                break
        cursor = cursor + timedelta(days=7 * recurrence["recurrence_frequency"])
    unique_occurrences = sorted({occurrence for occurrence in occurrences})
    return unique_occurrences[:count]


def _nth_weekday_of_month(year: int, month: int, weekday: int, week_of_month: int, hour: int, minute: int):
    first_day = datetime(year, month, 1, hour, minute, tzinfo=timezone.utc)
    delta = (weekday - first_day.weekday()) % 7
    candidate = first_day + timedelta(days=delta + (week_of_month - 1) * 7)
    if candidate.month != month:
        return None
    return candidate


def _generate_recurrence_occurrences(base_datetime: datetime, recurrence: dict, count: int = 12):
    recurrence_type = recurrence.get("recurrence_type")
    frequency = recurrence.get("recurrence_frequency") or 1
    occurrences: list[datetime] = []

    if recurrence_type == "Daily":
        candidate = base_datetime
        for _ in range(count):
            candidate = _next_daily_occurrence(base_datetime, candidate, frequency)
            occurrences.append(candidate)
    elif recurrence_type in {"Weekly", "Custom"}:
        occurrences = _next_weekly_occurrences(base_datetime, recurrence, count)
    elif recurrence_type == "Monthly":
        week_of_month = recurrence.get("monthly_week_of_month") or ((base_datetime.day - 1) // 7) + 1
        weekday = WEEKDAY_INDEX[recurrence.get("monthly_day_of_week") or WEEKDAY_BY_INDEX[base_datetime.weekday()]]
        year = base_datetime.year
        month = base_datetime.month
        for _ in range(count * 2):
            month += frequency
            year += (month - 1) // 12
            normalized_month = ((month - 1) % 12) + 1
            candidate = _nth_weekday_of_month(
                year,
                normalized_month,
                weekday,
                week_of_month,
                base_datetime.hour,
                base_datetime.minute,
            )
            if candidate is None:
                continue
            if candidate > base_datetime:
                occurrences.append(candidate)
            if len(occurrences) == count:
                break
    return occurrences[:count]


def _generate_recurring_child_bookings(template_document: dict):
    recurrence = template_document.get("recurrence")
    if not recurrence:
        return

    base_datetime = _as_utc_datetime(template_document.get("pickup_at"))
    if not base_datetime:
        return

    end_date_raw = recurrence.get("recurrence_end_date")
    end_date = None
    if end_date_raw:
        try:
            end_date = datetime.fromisoformat(end_date_raw).replace(tzinfo=timezone.utc)
        except ValueError:
            end_date = None

    for occurrence in _generate_recurrence_occurrences(base_datetime, recurrence):
        if end_date and occurrence.date() > end_date.date():
            continue
        existing = bookings_collection().find_one(
            {
                "source_booking_id": template_document["_id"],
                "pickup_at": occurrence,
            }
        )
        if existing:
            continue

        child_document = {
            **template_document,
            "_id": ObjectId(),
            "booking_id": _build_booking_id(),
            "pickup_date": occurrence.date().isoformat(),
            "pickup_time": occurrence.strftime("%H:%M"),
            "pickup_at": occurrence,
            "source_booking_id": template_document["_id"],
            "generated_from_recurring": True,
            "is_recurring_template": False,
            "reminder_flags": {},
            "overdue_notified_at": None,
            "missed_notified_at": None,
            "updated_at": now_utc(),
            "created_at": now_utc(),
            "audit_events": [
                {
                    "action": "generated",
                    "at": now_utc(),
                    "by": template_document.get("created_by"),
                    "changes": ["pickup_date", "pickup_time"],
                    "note": "Generated from recurring booking template.",
                }
            ],
        }
        bookings_collection().insert_one(child_document)


def _create_booking_notifications(booking_document: dict):
    title = "Booking scheduled"
    customer = customers_collection().find_one({"_id": booking_document.get("customer_id")})
    customer_name = customer.get("full_name") if customer else "Customer"
    booking_type = booking_document.get("booking_type")
    if booking_type in REMINDER_BOOKING_TYPES:
        title = booking_document.get("title") or booking_type
        message = (
            f"{title} is scheduled for {booking_document.get('pickup_date')} at {booking_document.get('pickup_time')}."
        )
    else:
        message = (
            f"{customer_name} has a {booking_type} on "
            f"{booking_document.get('pickup_date')} at {booking_document.get('pickup_time')}."
        )
    if booking_document.get("driver_id"):
        create_notification(
            recipient_user_id=booking_document["driver_id"],
            title=title,
            message=message,
            category="trip",
            priority="medium",
            reference_type="booking",
            reference_id=booking_document["_id"],
        )
    notify_roles(
        ["owner", "admin"],
        title,
        message,
        category="trip",
        priority="medium",
        reference_type="booking",
        reference_id=booking_document["_id"],
    )


def _notify_booking_progress(booking_document: dict, *, title: str, message: str, priority: str = "medium"):
    notify_roles(
        ["owner", "admin"],
        title,
        message,
        category="trip",
        priority=priority,
        reference_type="booking",
        reference_id=booking_document["_id"],
    )


def _ensure_due_booking_reminders():
    cache_key = "bookings:due_reminders:last_run"
    if get_ttl_cached(cache_key) is not None:
        return
    run_started_at = perf_counter()
    now = now_utc()
    booking_documents = bookings_collection().find(
        {
            "status": {"$in": list(ACTIVE_BOOKING_STATUSES | {"Confirmed", "In Progress"})},
            "is_recurring_template": False,
            "pickup_at": {"$gte": now - timedelta(hours=2)},
        }
    )
    for booking_document in booking_documents:
        pickup_at = _as_utc_datetime(booking_document.get("pickup_at"))
        if not pickup_at:
            continue
        booking_type = booking_document.get("booking_type")
        is_reminder = booking_type in REMINDER_BOOKING_TYPES

        reminder_flags = dict(booking_document.get("reminder_flags") or {})
        thresholds = [
            ("day_before", timedelta(hours=24), "You have a scheduled pickup tomorrow."),
            ("hour_before", timedelta(hours=1), "Upcoming pickup in 1 hour."),
            ("pickup_time", timedelta(seconds=0), "Scheduled pickup due now."),
        ]
        if is_reminder:
            title = booking_document.get("title") or booking_type
            thresholds = [
                ("day_before", timedelta(hours=24), f"Reminder tomorrow: {title}."),
                ("hour_before", timedelta(hours=1), f"Reminder in 1 hour: {title}."),
                ("pickup_time", timedelta(seconds=0), f"Reminder due now: {title}."),
            ]
        next_flags = {}
        for key, threshold, text in thresholds:
            already_sent = reminder_flags.get(key)
            if already_sent:
                next_flags[key] = already_sent
                continue
            if now >= pickup_at - threshold:
                if booking_document.get("driver_id"):
                    create_notification(
                        recipient_user_id=booking_document["driver_id"],
                        title="Scheduled pickup reminder",
                        message=text,
                        category="trip",
                        priority="high" if key == "pickup_time" else "medium",
                        reference_type="booking",
                        reference_id=booking_document["_id"],
                    )
                notify_roles(
                    ["owner", "admin"],
                    "Scheduled pickup reminder",
                    text,
                    category="trip",
                    priority="high" if key == "pickup_time" else "medium",
                    reference_type="booking",
                    reference_id=booking_document["_id"],
                )
                next_flags[key] = now.isoformat()

        if is_reminder and pickup_at < now and not booking_document.get("overdue_notified_at"):
            reminder_text = f"Reminder overdue: {booking_document.get('title') or booking_type}."
            if booking_document.get("driver_id"):
                create_notification(
                    recipient_user_id=booking_document["driver_id"],
                    title="Overdue reminder",
                    message=reminder_text,
                    category="trip",
                    priority="high" if booking_document.get("priority") == "Critical" else "medium",
                    reference_type="booking",
                    reference_id=booking_document["_id"],
                )
            notify_roles(
                ["owner", "admin"],
                "Overdue reminder",
                reminder_text,
                category="trip",
                priority="high" if booking_document.get("priority") == "Critical" else "medium",
                reference_type="booking",
                reference_id=booking_document["_id"],
            )
            next_flags["overdue"] = now.isoformat()
            bookings_collection().update_one(
                {"_id": booking_document["_id"]},
                {"$set": {"overdue_notified_at": now, "updated_at": now}},
            )

        if booking_type not in REMINDER_BOOKING_TYPES and pickup_at + timedelta(hours=2) < now and booking_document.get("status") in ACTIVE_BOOKING_STATUSES and not booking_document.get("missed_notified_at"):
            missed_text = f"Missed booking: {booking_document.get('booking_id')} for {customer_name if (customer_name := (customers_collection().find_one({'_id': booking_document.get('customer_id')}) or {}).get('full_name')) else 'customer'}."
            bookings_collection().update_one(
                {"_id": booking_document["_id"]},
                {"$set": {"status": "Missed", "missed_notified_at": now, "updated_at": now}},
            )
            if booking_document.get("driver_id"):
                create_notification(
                    recipient_user_id=booking_document["driver_id"],
                    title="Missed booking",
                    message=missed_text,
                    category="trip",
                    priority="high",
                    reference_type="booking",
                    reference_id=booking_document["_id"],
                )
            notify_roles(
                ["owner", "admin"],
                "Missed booking",
                missed_text,
                category="trip",
                priority="high",
                reference_type="booking",
                reference_id=booking_document["_id"],
            )
            booking_document["status"] = "Missed"

        if next_flags != reminder_flags:
            bookings_collection().update_one(
                {"_id": booking_document["_id"]},
                {"$set": {"reminder_flags": next_flags, "updated_at": now}},
            )
    current_app.logger.info(
        "[Flux Bookings] due reminder sweep duration_ms=%.2f",
        (perf_counter() - run_started_at) * 1000,
    )
    set_ttl_cached(cache_key, True, ttl_seconds=60)


def list_booking_options(current_user_id: str, current_role: str) -> dict:
    cache_key = build_cache_key("booking_options", current_user_id=current_user_id, current_role=current_role)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    request_started_at = perf_counter()
    customer_query = {}
    driver_query = {"role": "driver", "status": "active"}
    if current_role == "driver":
        customer_query["created_by"] = _to_object_id(current_user_id, "current_user_id")
        driver_query["_id"] = _to_object_id(current_user_id, "current_user_id")

    query_started_at = perf_counter()
    customers = list(
        customers_collection().find(
            customer_query,
            {
                "customer_id": 1,
                "full_name": 1,
                "phone_number": 1,
                "status": 1,
                "created_by": 1,
                "created_at": 1,
            },
        ).sort("full_name", ASCENDING)
    )
    drivers = list(
        users_collection().find(
            driver_query,
            {"full_name": 1, "email": 1, "role": 1, "status": 1, "phone": 1, "created_at": 1},
        ).sort("full_name", ASCENDING)
    )
    vehicles = list(
        vehicles_collection().find(
            {},
            {
                "vehicle_id": 1,
                "registration_number": 1,
                "vehicle_type": 1,
                "make": 1,
                "model": 1,
                "status": 1,
                "year": 1,
                "assigned_driver_id": 1,
                "current_odometer": 1,
                "created_at": 1,
            },
        ).sort("registration_number", ASCENDING)
    )
    log_db_duration("bookings.options.query", query_started_at)
    result = {
        "customers": [serialize_customer(customer) for customer in customers],
        "drivers": [serialize_user(driver) for driver in drivers],
        "vehicles": [serialize_vehicle(vehicle) for vehicle in vehicles],
        "booking_types": get_active_master_data_values("booking_types"),
        "statuses": sorted(BOOKING_STATUSES),
        "recurrence_types": sorted(RECURRENCE_TYPES),
        "priorities": sorted(BOOKING_PRIORITIES),
    }
    current_app.logger.info(
        "[Flux Bookings] options generated role=%s duration_ms=%.2f",
        current_role,
        (perf_counter() - request_started_at) * 1000,
    )
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    if total_duration_ms > 2000:
        current_app.logger.warning(
            "SLOW API WARNING endpoint=/api/bookings/options role=%s duration_ms=%.2f",
            current_role,
            total_duration_ms,
        )
    return set_ttl_cached(cache_key, result, ttl_seconds=30)


def list_bookings(current_user_id: str, current_role: str) -> list[dict]:
    request_started_at = perf_counter()
    current_app.logger.info("[Flux Bookings] list requested role=%s user_id=%s", current_role, current_user_id)

    reminder_started_at = perf_counter()
    _ensure_due_booking_reminders()
    current_app.logger.info(
        "[Flux Bookings] reminder_gate duration_ms=%.2f",
        (perf_counter() - reminder_started_at) * 1000,
    )

    query = {}
    if current_role == "driver":
        current_object_id = _to_object_id(current_user_id, "current_user_id")
        query["$or"] = [{"driver_id": current_object_id}, {"created_by": current_object_id}]
    query_started_at = perf_counter()
    booking_documents = list(
        bookings_collection()
        .find(query, BOOKING_LIST_PROJECTION)
        .sort([("pickup_at", ASCENDING), ("created_at", DESCENDING)])
    )
    log_db_duration("bookings.list.query", query_started_at)

    enrichment_started_at = perf_counter()
    customer_map, driver_map, vehicle_map, user_map = _load_booking_relationship_maps(booking_documents)
    result = [
        _enrich_booking(
            booking_document,
            customer_map=customer_map,
            driver_map=driver_map,
            vehicle_map=vehicle_map,
            user_map=user_map,
        )
        for booking_document in booking_documents
    ]
    current_app.logger.info(
        "[Flux Bookings] list role=%s count=%s enrichment_ms=%.2f total_ms=%.2f",
        current_role,
        len(result),
        (perf_counter() - enrichment_started_at) * 1000,
        (perf_counter() - request_started_at) * 1000,
    )
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    if total_duration_ms > 2000:
        current_app.logger.warning(
            "SLOW API WARNING endpoint=/api/bookings role=%s duration_ms=%.2f",
            current_role,
            total_duration_ms,
        )
    return result


def create_booking(payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to create bookings.", status_code=403)

    normalized = _normalized_booking_payload(payload, partial=False)
    customer_document = None
    if normalized.get("customer_id"):
        customer_document = _get_customer_document(str(normalized["customer_id"]))
        _assert_customer_visibility(
            customer_document,
            current_user_id=current_user_id,
            current_role=current_role,
        )

    if current_role == "driver":
        current_driver_id = _to_object_id(current_user_id, "current_user_id")
        selected_driver_id = normalized.get("driver_id")
        if selected_driver_id and selected_driver_id != current_driver_id:
            raise ApiError("Drivers can only assign bookings to themselves.", status_code=403)
        normalized["driver_id"] = selected_driver_id or current_driver_id

    timestamp = now_utc()
    recurrence = normalized.get("recurrence")
    is_recurring_template = bool(recurrence)
    booking_document = {
        "booking_id": _build_booking_id(),
        "customer_id": normalized.get("customer_id"),
        "driver_id": normalized.get("driver_id"),
        "assigned_to": normalized.get("driver_id"),
        "vehicle_id": normalized.get("vehicle_id"),
        "booking_type": normalized["booking_type"],
        "title": normalized.get("title") or normalized["booking_type"],
        "description": normalized.get("description"),
        "pickup_date": normalized["pickup_date"],
        "pickup_time": normalized["pickup_time"],
        "reminder_date": normalized.get("reminder_date") or normalized["pickup_date"],
        "reminder_time": normalized.get("reminder_time") or normalized["pickup_time"],
        "pickup_location": normalized.get("pickup_location"),
        "destination": normalized.get("destination"),
        "expected_fare": normalized.get("expected_fare"),
        "priority": normalized.get("priority", "Medium"),
        "notes": normalized.get("notes"),
        "status": normalized.get("status", "Scheduled"),
        "reminder_flags": {},
        "created_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "pickup_at": normalized["pickup_at"],
        "recurrence": recurrence,
        "source_booking_id": None,
        "is_recurring_template": is_recurring_template,
        "generated_from_recurring": False,
        "activity_kind": _activity_kind_for_booking_type(normalized["booking_type"]),
        "activity_color": _activity_color(normalized["booking_type"], normalized.get("status", "Scheduled"), normalized.get("priority", "Medium")),
        "is_overdue": False,
        "is_personal_reminder": normalized["booking_type"] in PERSONAL_REMINDER_BOOKING_TYPES,
        "is_follow_up_reminder": normalized["booking_type"] in FOLLOW_UP_BOOKING_TYPES,
        "is_company_event": normalized["booking_type"] in COMPANY_EVENT_BOOKING_TYPES,
        "overdue_notified_at": None,
        "missed_notified_at": None,
        "acknowledged_by": None,
        "acknowledged_at": None,
        "en_route_at": None,
        "picked_up_at": None,
        "completed_at": None,
        "completed_by": None,
        "completion_note": None,
        "issue_type": None,
        "issue_note": None,
        "issue_reported_at": None,
        "issue_history": [],
        "trip_log_id": None,
        "audit_events": [
            _serialize_audit_event(
                action="created",
                user_id=current_user_id,
                changes=sorted(normalized.keys()),
            )
        ],
    }
    result = bookings_collection().insert_one(booking_document)
    booking_document["_id"] = result.inserted_id

    if is_recurring_template:
        _generate_recurring_child_bookings(booking_document)

    _create_booking_notifications(booking_document)
    return _enrich_booking(booking_document)


def get_booking_by_id(booking_id: str, current_user_id: str, current_role: str) -> dict:
    _ensure_due_booking_reminders()
    booking_document = _get_booking_document(booking_id)
    _assert_booking_access(
        booking_document,
        current_user_id=current_user_id,
        current_role=current_role,
    )
    return _enrich_booking(booking_document)


def update_booking(booking_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to update bookings.", status_code=403)

    booking_document = _get_booking_document(booking_id)
    _assert_booking_access(
        booking_document,
        current_user_id=current_user_id,
        current_role=current_role,
    )

    normalized = _normalized_booking_payload(payload, partial=True)
    if not normalized:
        raise ApiError("No booking fields provided for update.", status_code=400)

    if "customer_id" in normalized:
        customer_document = _get_customer_document(str(normalized["customer_id"]))
        _assert_customer_visibility(
            customer_document,
            current_user_id=current_user_id,
            current_role=current_role,
        )

    if current_role == "driver" and "driver_id" in normalized:
        current_driver_id = _to_object_id(current_user_id, "current_user_id")
        if normalized.get("driver_id") and normalized["driver_id"] != current_driver_id:
            raise ApiError("Drivers can only assign bookings to themselves.", status_code=403)

    if "pickup_date" in normalized or "pickup_time" in normalized:
        pickup_date = normalized.get("pickup_date", booking_document.get("pickup_date"))
        pickup_time = normalized.get("pickup_time", booking_document.get("pickup_time"))
        normalized["pickup_date"] = pickup_date
        normalized["pickup_time"] = pickup_time
        normalized["pickup_at"] = _parse_pickup_datetime(pickup_date, pickup_time)

    timestamp = now_utc()
    audit_event = _serialize_audit_event(
        action="updated",
        user_id=current_user_id,
        changes=sorted(normalized.keys()),
    )
    update_fields = {
        **normalized,
        "assigned_to": normalized.get("driver_id", booking_document.get("driver_id")),
        "updated_at": timestamp,
    }
    next_type = normalized.get("booking_type", booking_document.get("booking_type"))
    next_status = normalized.get("status", booking_document.get("status"))
    next_priority = normalized.get("priority", booking_document.get("priority", "Medium"))
    update_fields["activity_kind"] = _activity_kind_for_booking_type(next_type)
    update_fields["activity_color"] = _activity_color(next_type, next_status, next_priority)
    update_fields["is_personal_reminder"] = next_type in PERSONAL_REMINDER_BOOKING_TYPES
    update_fields["is_follow_up_reminder"] = next_type in FOLLOW_UP_BOOKING_TYPES
    update_fields["is_company_event"] = next_type in COMPANY_EVENT_BOOKING_TYPES
    bookings_collection().update_one(
        {"_id": booking_document["_id"]},
        {"$set": update_fields, "$push": {"audit_events": audit_event}},
    )

    booking_document.update(update_fields)
    booking_document.setdefault("audit_events", []).append(audit_event)

    if booking_document.get("is_recurring_template"):
        bookings_collection().delete_many(
            {
                "source_booking_id": booking_document["_id"],
                "pickup_at": {"$gte": now_utc()},
                "status": {"$in": ["Scheduled", "Confirmed"]},
            }
        )
        _generate_recurring_child_bookings(booking_document)

    return _enrich_booking(booking_document)


def _assert_driver_booking_action_access(booking_document: dict, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    if current_role != "driver":
        raise ApiError("You do not have permission to update bookings.", status_code=403)
    driver_id = str(booking_document.get("driver_id")) if booking_document.get("driver_id") else None
    if driver_id != current_user_id:
        raise ApiError("Drivers can only act on bookings assigned to them.", status_code=403)


def _complete_trip_log_from_booking(booking_document: dict, current_user_id: str, current_role: str):
    from services.ride_service import convert_booking_to_ride

    existing_trip_id = booking_document.get("trip_log_id")
    if existing_trip_id:
        return existing_trip_id

    ride = convert_booking_to_ride(
        str(booking_document["_id"]),
        {
            "trip_date": booking_document.get("pickup_date"),
            "start_time": booking_document.get("pickup_time"),
            "end_time": booking_document.get("pickup_time"),
            "pickup_area": booking_document.get("pickup_location"),
            "destination_area": booking_document.get("destination"),
            "notes": booking_document.get("notes"),
            "status": "Completed",
        },
        current_user_id,
        current_role,
    )
    trip_log_id = ride.get("id")
    if trip_log_id:
        bookings_collection().update_one(
            {"_id": booking_document["_id"]},
            {"$set": {"trip_log_id": _to_object_id(trip_log_id, "trip_log_id", required=False), "updated_at": now_utc()}},
        )
    return trip_log_id


def _apply_booking_action(
    booking_id: str,
    *,
    current_user_id: str,
    current_role: str,
    next_status: str,
    allowed_statuses: set[str],
    action: str,
    field_updates: dict[str, Any] | None = None,
    issue_history_entry: dict[str, Any] | None = None,
    note: str | None = None,
):
    booking_document = _get_booking_document(booking_id)
    _assert_driver_booking_action_access(booking_document, current_user_id, current_role)

    current_status = _map_booking_status_for_display(booking_document.get("status"))
    if current_status not in allowed_statuses:
        raise ApiError(f"Booking cannot be marked as {next_status.lower()} from {current_status.lower()}.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": next_status,
        "updated_at": timestamp,
        **(field_updates or {}),
    }
    update_fields["activity_color"] = _activity_color(
        booking_document.get("booking_type") or "Customer Booking",
        next_status,
        booking_document.get("priority") or "Medium",
    )
    audit_event = _serialize_audit_event(
        action=action,
        user_id=current_user_id,
        changes=sorted(update_fields.keys()),
        note=note,
    )
    update_operation: dict[str, Any] = {
        "$set": update_fields,
        "$push": {"audit_events": audit_event},
    }
    if issue_history_entry:
        update_operation["$push"]["issue_history"] = issue_history_entry
    bookings_collection().update_one({"_id": booking_document["_id"]}, update_operation)

    booking_document.update(update_fields)
    booking_document.setdefault("audit_events", []).append(audit_event)
    if issue_history_entry:
        booking_document.setdefault("issue_history", []).append(issue_history_entry)
    return booking_document


def acknowledge_booking(booking_id: str, current_user_id: str, current_role: str) -> dict:
    booking_document = _apply_booking_action(
        booking_id,
        current_user_id=current_user_id,
        current_role=current_role,
        next_status="Acknowledged",
        allowed_statuses={"Scheduled"},
        action="acknowledged",
        field_updates={
            "acknowledged_by": _to_object_id(current_user_id, "current_user_id"),
            "acknowledged_at": now_utc(),
        },
        note="Booking acknowledged by driver.",
    )
    customer_name = booking_document.get("customer_id")
    customer = customers_collection().find_one({"_id": customer_name}) if customer_name else None
    _notify_booking_progress(
        booking_document,
        title="Booking acknowledged",
        message=f"{customer.get('full_name') if customer else 'A customer'} booking has been acknowledged by the assigned driver.",
    )
    return _enrich_booking(booking_document)


def start_pickup(booking_id: str, current_user_id: str, current_role: str) -> dict:
    booking_document = _apply_booking_action(
        booking_id,
        current_user_id=current_user_id,
        current_role=current_role,
        next_status="En Route",
        allowed_statuses={"Acknowledged"},
        action="started_pickup",
        field_updates={"en_route_at": now_utc()},
        note="Driver started pickup.",
    )
    customer = customers_collection().find_one({"_id": booking_document.get("customer_id")}) if booking_document.get("customer_id") else None
    _notify_booking_progress(
        booking_document,
        title="Driver en route",
        message=f"{customer.get('full_name') if customer else 'A customer'} pickup is now en route.",
    )
    return _enrich_booking(booking_document)


def mark_booking_picked_up(booking_id: str, current_user_id: str, current_role: str) -> dict:
    booking_document = _apply_booking_action(
        booking_id,
        current_user_id=current_user_id,
        current_role=current_role,
        next_status="Picked Up",
        allowed_statuses={"En Route"},
        action="picked_up",
        field_updates={"picked_up_at": now_utc()},
        note="Customer picked up.",
    )
    return _enrich_booking(booking_document)


def complete_booking(booking_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    completion_note = _normalize_text(payload.get("completion_note"))
    booking_document = _apply_booking_action(
        booking_id,
        current_user_id=current_user_id,
        current_role=current_role,
        next_status="Completed",
        allowed_statuses={"Picked Up"},
        action="completed",
        field_updates={
            "completed_at": now_utc(),
            "completed_by": _to_object_id(current_user_id, "current_user_id"),
            "completion_note": completion_note,
        },
        note=completion_note or "Booking completed.",
    )
    customer = customers_collection().find_one({"_id": booking_document.get("customer_id")}) if booking_document.get("customer_id") else None
    _notify_booking_progress(
        booking_document,
        title="Booking completed",
        message=f"{customer.get('full_name') if customer else 'A customer'} booking has been completed.",
        priority="high",
    )
    if payload.get("create_trip_log"):
        trip_log_id = _complete_trip_log_from_booking(booking_document, current_user_id, current_role)
        if trip_log_id:
            booking_document["trip_log_id"] = trip_log_id
    return _enrich_booking(booking_document)


def report_booking_issue(booking_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    issue_type = _normalize_issue_type(payload.get("issue_type"))
    issue_note = _normalize_text(payload.get("issue_note"))
    timestamp = now_utc()
    issue_entry = {
        "issue_type": issue_type,
        "issue_note": issue_note,
        "reported_at": timestamp,
        "reported_by": _to_object_id(current_user_id, "current_user_id"),
    }
    booking_document = _apply_booking_action(
        booking_id,
        current_user_id=current_user_id,
        current_role=current_role,
        next_status="Cancelled" if issue_type == "customer cancelled" else _map_booking_status_for_display(_get_booking_document(booking_id).get("status")),
        allowed_statuses=DRIVER_ACTIONABLE_BOOKING_STATUSES | {"Cancelled", "Missed"},
        action="issue_reported",
        field_updates={
            "issue_type": issue_type,
            "issue_note": issue_note,
            "issue_reported_at": timestamp,
        },
        issue_history_entry=issue_entry,
        note=issue_note or f"Issue reported: {issue_type}.",
    )
    _notify_booking_progress(
        booking_document,
        title="Booking issue reported",
        message=f"Booking {booking_document.get('booking_id')} has a reported issue: {issue_type}.",
        priority="high" if issue_type in {"customer not reachable", "vehicle issue"} else "medium",
    )
    return _enrich_booking(booking_document)


def _calendar_window(view: str):
    now = now_utc()
    start_of_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    if view == "today":
        return start_of_today, start_of_today + timedelta(days=1)
    if view == "tomorrow":
        return start_of_today + timedelta(days=1), start_of_today + timedelta(days=2)
    if view == "this-week":
        weekday_start = start_of_today - timedelta(days=start_of_today.weekday())
        return weekday_start, weekday_start + timedelta(days=7)
    if view == "upcoming":
        return start_of_today, start_of_today + timedelta(days=30)
    if view == "overdue":
        return start_of_today - timedelta(days=3650), start_of_today
    if view == "completed":
        return start_of_today - timedelta(days=30), start_of_today + timedelta(days=1)
    raise ApiError("Invalid calendar view.", status_code=400)


def _booking_summary_metrics_pipeline(base_query: dict[str, Any], *, now: datetime, today_start: datetime, today_end: datetime):
    active_statuses = list(ACTIVE_BOOKING_STATUSES)
    in_progress_statuses = list(IN_PROGRESS_BOOKING_STATUSES)
    reminder_types = list(REMINDER_BOOKING_TYPES)
    follow_up_types = list(FOLLOW_UP_BOOKING_TYPES)
    corporate_types = list(CORPORATE_BOOKING_TYPES)
    vip_types = list(VIP_BOOKING_TYPES)
    strategic_types = list(STRATEGIC_BOOKING_TYPES)

    return [
        {"$match": base_query},
        {
            "$facet": {
                "counts": [
                    {
                        "$group": {
                            "_id": None,
                            "upcoming_bookings": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$pickup_at", today_start]},
                                                {"$lt": ["$pickup_at", today_end]},
                                                {"$in": ["$status", active_statuses]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "missed_bookings": {"$sum": {"$cond": [{"$eq": ["$status", "Missed"]}, 1, 0]}},
                            "today_schedule": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$pickup_at", today_start]},
                                                {"$lt": ["$pickup_at", today_end]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "upcoming_pickups": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$pickup_at", now]},
                                                {"$in": ["$status", active_statuses]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "total_scheduled_bookings": {
                                "$sum": {"$cond": [{"$in": ["$status", active_statuses]}, 1, 0]}
                            },
                            "pending_acknowledgement": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$pickup_at", today_start]},
                                                {"$lt": ["$pickup_at", today_end]},
                                                {"$eq": ["$status", "Scheduled"]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "in_progress_bookings": {
                                "$sum": {"$cond": [{"$in": ["$status", in_progress_statuses]}, 1, 0]}
                            },
                            "completed_today": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$pickup_at", today_start]},
                                                {"$lt": ["$pickup_at", today_end]},
                                                {"$eq": ["$status", "Completed"]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "overdue_reminders": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$lt": ["$pickup_at", now]},
                                                {"$in": ["$booking_type", reminder_types]},
                                                {"$not": [{"$in": ["$status", ["Completed", "Cancelled", "Missed"]]}]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "follow_ups_due_today": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$pickup_at", today_start]},
                                                {"$lt": ["$pickup_at", today_end]},
                                                {"$in": ["$booking_type", follow_up_types]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "upcoming_corporate_bookings": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$in": ["$booking_type", corporate_types]},
                                                {"$in": ["$status", active_statuses]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "total_future_bookings": {
                                "$sum": {"$cond": [{"$gte": ["$pickup_at", now]}, 1, 0]}
                            },
                            "vip_bookings": {
                                "$sum": {"$cond": [{"$in": ["$booking_type", vip_types]}, 1, 0]}
                            },
                            "strategic_meetings": {
                                "$sum": {"$cond": [{"$in": ["$booking_type", strategic_types]}, 1, 0]}
                            },
                            "follow_up_total": {
                                "$sum": {"$cond": [{"$in": ["$booking_type", follow_up_types]}, 1, 0]}
                            },
                            "follow_up_completed": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$in": ["$booking_type", follow_up_types]},
                                                {"$eq": ["$status", "Completed"]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    }
                ],
                "recent_customers": [
                    {"$match": {"pickup_at": {"$gte": now - timedelta(days=7)}, "customer_id": {"$ne": None}}},
                    {"$group": {"_id": "$customer_id"}},
                    {"$count": "count"},
                ],
                "driver_schedules": [
                    {"$match": {"driver_id": {"$ne": None}}},
                    {"$group": {"_id": "$driver_id"}},
                    {"$count": "count"},
                ],
                "bookings_by_status": [
                    {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                ],
            }
        },
    ]


def _customer_growth_counts(now: datetime) -> dict[str, int]:
    rows = list(
        customers_collection().aggregate(
            [
                {
                    "$group": {
                        "_id": None,
                        "last_30_days": {
                            "$sum": {"$cond": [{"$gte": ["$created_at", now - timedelta(days=30)]}, 1, 0]}
                        },
                        "last_90_days": {
                            "$sum": {"$cond": [{"$gte": ["$created_at", now - timedelta(days=90)]}, 1, 0]}
                        },
                        "total_customers": {"$sum": 1},
                    }
                }
            ]
        )
    )
    if not rows:
        return {"last_30_days": 0, "last_90_days": 0, "total_customers": 0}
    row = rows[0]
    return {
        "last_30_days": int(row.get("last_30_days") or 0),
        "last_90_days": int(row.get("last_90_days") or 0),
        "total_customers": int(row.get("total_customers") or 0),
    }


def list_calendar_entries(current_user_id: str, current_role: str, view: str = "upcoming") -> dict:
    normalized_view = (view or "upcoming").strip().lower()
    if normalized_view not in CALENDAR_VIEWS:
        raise ApiError("Invalid calendar view.", status_code=400)

    _ensure_due_booking_reminders()
    window_start, window_end = _calendar_window(normalized_view)
    query = {
        "status": {"$in": list(BOOKING_STATUSES | {"Confirmed", "In Progress"})},
        "is_recurring_template": False,
    }
    if normalized_view == "overdue":
        query["pickup_at"] = {"$lt": now_utc()}
        query["status"] = {"$nin": ["Completed", "Cancelled", "Missed"]}
    elif normalized_view == "completed":
        query["pickup_at"] = {"$gte": window_start, "$lt": window_end}
        query["status"] = "Completed"
    else:
        query["pickup_at"] = {"$gte": window_start, "$lt": window_end}
    if current_role == "driver":
        query["driver_id"] = _to_object_id(current_user_id, "current_user_id")

    bookings = list(bookings_collection().find(query).sort([("pickup_at", ASCENDING)]))
    entries = []
    for booking_document in bookings:
        booking = _enrich_booking(booking_document)
        entries.append(
            {
                "booking": booking,
                "time": booking.get("pickup_time"),
                "customer": booking.get("customer", {}).get("full_name"),
                "pickup": booking.get("pickup_location"),
                "destination": booking.get("destination"),
                "status": booking.get("status"),
                "color": booking.get("activity_color"),
                "is_overdue": bool(booking.get("pickup_at") and _as_utc_datetime(booking_document.get("pickup_at")) and _as_utc_datetime(booking_document.get("pickup_at")) < now_utc() and booking.get("status") not in {"Completed", "Cancelled", "Missed"}),
            }
        )

    return {
        "view": normalized_view,
        "entries": entries,
    }


def get_booking_dashboard_summary(current_role: str, current_user_id: str) -> dict:
    cache_key = build_cache_key(
        "booking_dashboard_summary",
        current_role=current_role,
        current_user_id=current_user_id,
    )
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    request_started_at = perf_counter()
    base_query: dict[str, Any] = {"is_recurring_template": False}
    recurring_query: dict[str, Any] = {"is_recurring_template": True}
    if current_role == "driver":
        driver_object_id = _to_object_id(current_user_id, "current_user_id")
        base_query["driver_id"] = driver_object_id
        recurring_query["driver_id"] = driver_object_id

    now = now_utc()
    today_start, today_end = _calendar_window("today")
    active_statuses = list(ACTIVE_BOOKING_STATUSES)
    result = _empty_booking_dashboard_summary()

    try:
        bookings_started_at = perf_counter()
        summary_rows = list(
            bookings_collection().aggregate(
                _booking_summary_metrics_pipeline(
                    base_query,
                    now=now,
                    today_start=today_start,
                    today_end=today_end,
                )
            )
        )
        summary = summary_rows[0] if summary_rows else {}
        counts = (summary.get("counts") or [{}])[0]
        recurring_rows = list(
            bookings_collection().aggregate(
                [
                    {"$match": {**recurring_query, "customer_id": {"$ne": None}}},
                    {"$group": {"_id": "$customer_id"}},
                    {"$count": "count"},
                ]
            )
        )
        recurring_count = int((recurring_rows[0] or {}).get("count") or 0) if recurring_rows else 0
        growth_counts = _customer_growth_counts(now)

        scalar_fields = [
            "upcoming_bookings",
            "missed_bookings",
            "today_schedule",
            "upcoming_pickups",
            "total_scheduled_bookings",
            "pending_acknowledgement",
            "in_progress_bookings",
            "completed_today",
            "overdue_reminders",
            "follow_ups_due_today",
            "upcoming_corporate_bookings",
            "total_future_bookings",
            "vip_bookings",
            "strategic_meetings",
        ]
        for field in scalar_fields:
            result[field] = int(counts.get(field) or 0)

        result["scheduled_today"] = result["today_schedule"]
        result["recent_customers"] = int(((summary.get("recent_customers") or [{}])[0].get("count") or 0))
        result["driver_schedules"] = int(((summary.get("driver_schedules") or [{}])[0].get("count") or 0))
        result["active_recurring_customers"] = recurring_count
        result["total_recurring_customers"] = recurring_count
        result["total_customers"] = growth_counts["total_customers"]
        result["customer_growth_trend"] = [
            {"label": "Last 30 days", "value": growth_counts["last_30_days"]},
            {"label": "Last 90 days", "value": growth_counts["last_90_days"]},
        ]
        follow_up_total = int(counts.get("follow_up_total") or 0)
        follow_up_completed = int(counts.get("follow_up_completed") or 0)
        result["follow_up_completion_rate"] = round((follow_up_completed / max(1, follow_up_total)) * 100, 1)
        result["bookings_by_status"] = {status: 0 for status in BOOKING_STATUSES}
        for item in summary.get("bookings_by_status") or []:
            status = item.get("_id")
            if status in result["bookings_by_status"]:
                result["bookings_by_status"][status] = int(item.get("count") or 0)
        log_db_duration("bookings.summary.fast_counts", bookings_started_at)
        current_app.logger.info(
            "[Flux Section] section=booking_summary endpoint=/api/bookings/summary duration_ms=%.2f success=true records_count=%s",
            (perf_counter() - request_started_at) * 1000,
            result["total_scheduled_bookings"],
        )
    except Exception:
        current_app.logger.exception(
            "[Flux Section] section=booking_summary endpoint=/api/bookings/summary success=false"
        )
        result = _empty_booking_dashboard_summary()

    total_duration_ms = (perf_counter() - request_started_at) * 1000
    if total_duration_ms > 2000:
        current_app.logger.warning(
            "SLOW API WARNING endpoint=/api/bookings/summary role=%s duration_ms=%.2f",
            current_role,
            total_duration_ms,
        )
    return set_ttl_cached(cache_key, result, ttl_seconds=30)
