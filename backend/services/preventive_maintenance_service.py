from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.preventive_maintenance import (
    serialize_compliance_record,
    serialize_compliance_type,
    serialize_preventive_schedule,
)
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.assignment_service import get_active_assignment_for_driver
from services.maintenance_service import create_maintenance_job
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


ALLOWED_PREVENTIVE_TYPES = {
    "oil_change",
    "general_servicing",
    "brake_inspection",
    "tyre_check",
    "battery_check",
    "belt_check",
    "coolant_check",
    "suspension_check",
    "wheel_alignment",
    "air_filter_check",
    "vehicle_inspection",
    "engine_service",
    "other",
    # Legacy support
    "tyre_rotation",
}
ALLOWED_RECURRENCE_TYPES = {
    "weekly",
    "every_2_weeks",
    "monthly",
    "every_2_months",
    "quarterly",
    "custom_days",
    "mileage_based",
    "both_time_and_mileage",
}
ALLOWED_SCHEDULE_TYPES = {"date_based", "mileage_based", "both"}
ALLOWED_SCHEDULE_STATUSES = {"active", "due_soon", "due", "overdue", "completed", "paused"}
ALLOWED_COMPLIANCE_STATUSES = {"active", "due_soon", "expired", "renewed", "inactive"}
ALLOWED_COMPLIANCE_RENEWAL_FREQUENCIES = {"yearly", "every_6_months", "quarterly", "monthly", "custom"}

DEFAULT_PREVENTIVE_TEMPLATES = [
    {
        "maintenance_type": "oil_change",
        "title": "Oil Change",
        "description": "Recurring oil change schedule for engine health.",
        "recurrence_type": "both_time_and_mileage",
        "interval_days": 30,
        "interval_months": 1,
        "interval_km": 5000,
        "warning_days_before": 5,
        "warning_km_before": 500,
    },
    {
        "maintenance_type": "general_servicing",
        "title": "General Servicing",
        "description": "Routine servicing schedule for the vehicle.",
        "recurrence_type": "every_2_months",
        "interval_days": None,
        "interval_months": 2,
        "interval_km": 10000,
        "warning_days_before": 7,
        "warning_km_before": 1000,
    },
    {
        "maintenance_type": "brake_inspection",
        "title": "Brake Inspection",
        "description": "Routine brake inspection to keep stopping performance safe.",
        "recurrence_type": "monthly",
        "interval_days": None,
        "interval_months": 1,
        "interval_km": None,
        "warning_days_before": 5,
        "warning_km_before": 0,
    },
    {
        "maintenance_type": "tyre_check",
        "title": "Tyre Check",
        "description": "Check tyre wear, pressure, and balance regularly.",
        "recurrence_type": "every_2_weeks",
        "interval_days": 14,
        "interval_months": None,
        "interval_km": 3000,
        "warning_days_before": 3,
        "warning_km_before": 300,
    },
    {
        "maintenance_type": "battery_check",
        "title": "Battery Check",
        "description": "Inspect battery health and terminal condition.",
        "recurrence_type": "monthly",
        "interval_days": None,
        "interval_months": 1,
        "interval_km": None,
        "warning_days_before": 5,
        "warning_km_before": 0,
    },
    {
        "maintenance_type": "belt_check",
        "title": "Belt Check",
        "description": "Check engine belts for wear, slack, and cracking.",
        "recurrence_type": "monthly",
        "interval_days": None,
        "interval_months": 1,
        "interval_km": None,
        "warning_days_before": 5,
        "warning_km_before": 0,
    },
    {
        "maintenance_type": "coolant_check",
        "title": "Coolant Check",
        "description": "Confirm coolant level and system condition.",
        "recurrence_type": "monthly",
        "interval_days": None,
        "interval_months": 1,
        "interval_km": None,
        "warning_days_before": 5,
        "warning_km_before": 0,
    },
    {
        "maintenance_type": "suspension_check",
        "title": "Suspension Check",
        "description": "Inspect shocks, bushings, and ride stability.",
        "recurrence_type": "quarterly",
        "interval_days": None,
        "interval_months": 3,
        "interval_km": None,
        "warning_days_before": 10,
        "warning_km_before": 0,
    },
    {
        "maintenance_type": "wheel_alignment",
        "title": "Wheel Alignment",
        "description": "Maintain stable steering and even tyre wear.",
        "recurrence_type": "both_time_and_mileage",
        "interval_days": 90,
        "interval_months": 3,
        "interval_km": 10000,
        "warning_days_before": 10,
        "warning_km_before": 1000,
    },
    {
        "maintenance_type": "air_filter_check",
        "title": "Air Filter Check",
        "description": "Inspect and replace the air filter when needed.",
        "recurrence_type": "monthly",
        "interval_days": None,
        "interval_months": 1,
        "interval_km": None,
        "warning_days_before": 5,
        "warning_km_before": 0,
    },
]

DEFAULT_COMPLIANCE_TYPES = [
    {"item_name": "Insurance", "category": "renewal"},
    {"item_name": "Roadworthy", "category": "renewal"},
    {"item_name": "Vehicle License", "category": "renewal"},
    {"item_name": "Fire Extinguisher", "category": "compliance"},
    {"item_name": "First Aid Kit", "category": "compliance"},
    {"item_name": "AMA Permit", "category": "permit"},
    {"item_name": "Local Authority Permit", "category": "permit"},
    {"item_name": "Company Permit", "category": "permit"},
    {"item_name": "Other", "category": "other"},
]


def now_utc():
    return datetime.now(timezone.utc)


def preventive_maintenance_collection():
    return get_collection("preventive_maintenance")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def fuel_logs_collection():
    return get_collection("fuel_logs")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def rides_collection():
    return get_collection("rides")


def compliance_item_types_collection():
    return get_collection("compliance_item_types")


def compliance_records_collection():
    return get_collection("vehicle_compliance_records")


def ensure_preventive_maintenance_indexes():
    ensure_indexes_for_collection(
        preventive_maintenance_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("maintenance_type", ASCENDING)]},
            {"keys": [("recurrence_type", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("assigned_admin_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("next_due_date", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("next_due_odometer", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("maintenance_type", ASCENDING)], "options": {"unique": True}},
        ],
        collection_name="preventive_maintenance",
    )
    ensure_indexes_for_collection(
        compliance_item_types_collection(),
        [
            {"keys": [("normalized_name", ASCENDING)], "options": {"unique": True}},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
        ],
        collection_name="compliance_item_types",
    )
    ensure_indexes_for_collection(
        compliance_records_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("compliance_type_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("expiry_date", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="vehicle_compliance_records",
    )


def _to_object_id(value, field_name: str, required: bool = True):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _parse_date(value, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        raise ApiError(f"{field_name} must be a valid YYYY-MM-DD date.", status_code=400)
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ApiError(f"{field_name} must be a valid YYYY-MM-DD date.", status_code=400) from exc


def _serialize_date(value: date | None):
    return value.isoformat() if value else None


def _validate_positive_int(value, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"{field_name} must be an integer.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return value


def _validate_positive_number(value, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _validate_maintenance_type(value: str | None):
    maintenance_type = (value or "").strip().lower()
    if maintenance_type not in ALLOWED_PREVENTIVE_TYPES:
        raise ApiError(
            "maintenance_type must be a supported preventive maintenance item.",
            status_code=400,
        )
    return maintenance_type


def _validate_recurrence_type(value: str | None):
    recurrence_type = (value or "").strip().lower()
    if recurrence_type not in ALLOWED_RECURRENCE_TYPES:
        raise ApiError(
            "recurrence_type must be one of: weekly, every_2_weeks, monthly, every_2_months, quarterly, custom_days, mileage_based, both_time_and_mileage.",
            status_code=400,
        )
    return recurrence_type


def _validate_schedule_type(value: str | None):
    schedule_type = (value or "").strip().lower()
    if schedule_type not in ALLOWED_SCHEDULE_TYPES:
        raise ApiError("schedule_type must be one of: date_based, mileage_based, both.", status_code=400)
    return schedule_type


def _validate_status(value: str | None, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError("status is required.", status_code=400)
        return None
    status = str(value).strip().lower()
    if status not in ALLOWED_SCHEDULE_STATUSES:
        raise ApiError("status must be one of: active, due_soon, due, overdue, completed, paused.", status_code=400)
    return status


def _normalize_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_parts_changed(value):
    if value in (None, ""):
        return None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return parts or None
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",") if item.strip()]
        return parts or None
    raise ApiError("parts_changed must be a string or list.", status_code=400)


def _normalize_item_name(value, field_name: str):
    text = _normalize_text(value)
    if not text:
        raise ApiError(f"{field_name} is required.", status_code=400)
    return text


def _normalized_key(value: str):
    return " ".join(value.strip().lower().split())


def _validate_compliance_status(value: str | None, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError("status is required.", status_code=400)
        return None
    status = str(value).strip().lower()
    if status not in ALLOWED_COMPLIANCE_STATUSES:
        raise ApiError("status must be one of: active, due_soon, expired, renewed, inactive.", status_code=400)
    return status


def _validate_renewal_frequency(value: str | None, required: bool = True):
    if value in (None, ""):
        if required:
            raise ApiError("renewal_frequency is required.", status_code=400)
        return None
    renewal_frequency = str(value).strip().lower()
    if renewal_frequency not in ALLOWED_COMPLIANCE_RENEWAL_FREQUENCIES:
        raise ApiError(
            "renewal_frequency must be one of: yearly, every_6_months, quarterly, monthly, custom.",
            status_code=400,
        )
    return renewal_frequency


def _get_vehicle_document(vehicle_id: str | ObjectId):
    vehicle_object_id = _to_object_id(vehicle_id, "vehicle_id")
    document = vehicles_collection().find_one({"_id": vehicle_object_id})
    if not document:
        raise ApiError("Vehicle not found.", status_code=404)
    return document


def _get_user_document(user_id: str | ObjectId, field_name: str = "user_id"):
    user_object_id = _to_object_id(user_id, field_name)
    document = users_collection().find_one({"_id": user_object_id})
    if not document:
        raise ApiError("User not found.", status_code=404)
    return document


def _get_schedule_document(schedule_id: str | ObjectId):
    schedule_object_id = _to_object_id(schedule_id, "preventive_maintenance_id")
    document = preventive_maintenance_collection().find_one({"_id": schedule_object_id})
    if not document:
        raise ApiError("Preventive maintenance schedule not found.", status_code=404)
    return document


def _resolve_driver_vehicle_for_driver(current_user_id: str):
    assignment = get_active_assignment_for_driver(current_user_id)
    if not assignment:
        return None
    return _to_object_id(assignment.get("vehicle_id"), "vehicle_id")


def _pick_assigned_admin(vehicle_document: dict, created_by: ObjectId):
    creator = users_collection().find_one({"_id": created_by})
    if creator and creator.get("role") in {"owner", "admin"} and creator.get("status") == "active":
        return creator["_id"]
    admin = users_collection().find_one({"role": "admin", "status": "active"})
    if admin:
        return admin["_id"]
    owner = users_collection().find_one({"role": "owner", "status": "active"})
    return owner["_id"] if owner else None


def _infer_recurrence_type(document: dict):
    recurrence_type = (document.get("recurrence_type") or "").strip().lower()
    if recurrence_type in ALLOWED_RECURRENCE_TYPES:
        return recurrence_type

    schedule_type = document.get("schedule_type")
    interval_days = document.get("interval_days")
    interval_months = document.get("interval_months")
    interval_km = document.get("interval_km")

    if schedule_type == "mileage_based":
        return "mileage_based"
    if schedule_type == "both":
        return "both_time_and_mileage"
    if interval_months == 1:
        return "monthly"
    if interval_months == 2:
        return "every_2_months"
    if interval_months == 3:
        return "quarterly"
    if interval_days == 7:
        return "weekly"
    if interval_days == 14:
        return "every_2_weeks"
    if interval_km is not None and interval_days is None and interval_months is None:
        return "mileage_based"
    return "custom_days"


def _infer_schedule_type_from_recurrence(recurrence_type: str):
    if recurrence_type == "mileage_based":
        return "mileage_based"
    if recurrence_type == "both_time_and_mileage":
        return "both"
    return "date_based"


def _resolve_recurrence_defaults(recurrence_type: str, interval_days, interval_months, interval_km):
    resolved_days = interval_days
    resolved_months = interval_months
    resolved_km = interval_km

    if recurrence_type == "weekly":
        resolved_days = 7
        resolved_months = None
    elif recurrence_type == "every_2_weeks":
        resolved_days = 14
        resolved_months = None
    elif recurrence_type == "monthly":
        resolved_months = 1
        resolved_days = None
    elif recurrence_type == "every_2_months":
        resolved_months = 2
        resolved_days = None
    elif recurrence_type == "quarterly":
        resolved_months = 3
        resolved_days = None
    elif recurrence_type == "mileage_based":
        resolved_days = None
        resolved_months = None
    elif recurrence_type == "custom_days" and resolved_days is None:
        raise ApiError("interval_days is required for custom_days recurrence.", status_code=400)
    elif recurrence_type == "both_time_and_mileage":
        if resolved_months is None and resolved_days is None:
            raise ApiError(
                "both_time_and_mileage recurrence requires interval_days or interval_months.",
                status_code=400,
            )
        if resolved_km is None:
            raise ApiError("both_time_and_mileage recurrence requires interval_km.", status_code=400)

    if recurrence_type == "mileage_based" and resolved_km is None:
        raise ApiError("interval_km is required for mileage_based recurrence.", status_code=400)

    return resolved_days, resolved_months, resolved_km


def _add_months(base_date: date, months: int):
    year = base_date.year + ((base_date.month - 1 + months) // 12)
    month = ((base_date.month - 1 + months) % 12) + 1
    month_lengths = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(base_date.day, month_lengths[month - 1])
    return date(year, month, day)


def _calculate_next_due_values(base_date, base_odometer, recurrence_type, interval_days, interval_months, interval_km):
    next_due_date = None
    next_due_odometer = None

    if recurrence_type in {"weekly", "every_2_weeks", "custom_days"} and interval_days:
        next_due_date = base_date + timedelta(days=int(interval_days))
    elif recurrence_type in {"monthly", "every_2_months", "quarterly"} and interval_months:
        next_due_date = _add_months(base_date, int(interval_months))
    elif recurrence_type == "both_time_and_mileage":
        if interval_months:
            next_due_date = _add_months(base_date, int(interval_months))
        elif interval_days:
            next_due_date = base_date + timedelta(days=int(interval_days))

    if recurrence_type in {"mileage_based", "both_time_and_mileage"} and interval_km is not None and base_odometer is not None:
        next_due_odometer = round(float(base_odometer) + float(interval_km), 2)

    return _serialize_date(next_due_date), next_due_odometer


def _extract_vehicle_current_odometer(vehicle_id: ObjectId, fallback_odometer=None):
    candidates = []
    if isinstance(fallback_odometer, (int, float)):
        candidates.append(float(fallback_odometer))

    latest_fuel = fuel_logs_collection().find(
        {"vehicle_id": vehicle_id, "odometer_reading": {"$ne": None}},
        {"odometer_reading": 1},
    ).sort([("fuel_date", DESCENDING), ("created_at", DESCENDING)]).limit(10)
    for item in latest_fuel:
        if isinstance(item.get("odometer_reading"), (int, float)):
            candidates.append(float(item["odometer_reading"]))

    latest_jobs = maintenance_jobs_collection().find(
        {"vehicle_id": vehicle_id, "odometer_reading": {"$ne": None}},
        {"odometer_reading": 1},
    ).sort([("updated_at", DESCENDING), ("created_at", DESCENDING)]).limit(10)
    for item in latest_jobs:
        if isinstance(item.get("odometer_reading"), (int, float)):
            candidates.append(float(item["odometer_reading"]))

    latest_rides = rides_collection().find(
        {"vehicle_id": vehicle_id},
        {"odometer_start": 1, "odometer_end": 1},
    ).sort([("trip_date", DESCENDING), ("created_at", DESCENDING)]).limit(20)
    for item in latest_rides:
        for field_name in ("odometer_end", "odometer_start"):
            if isinstance(item.get(field_name), (int, float)):
                candidates.append(float(item[field_name]))

    return max(candidates) if candidates else None


def _determine_status(document: dict):
    if document.get("status") == "paused":
        return "paused"

    today = date.today()
    due_by_date = False
    overdue_by_date = False
    due_soon_by_date = False

    next_due_date = _parse_date(document.get("next_due_date"), "next_due_date", required=False)
    warning_days_before = document.get("warning_days_before") or 0
    if next_due_date:
        if next_due_date < today:
            overdue_by_date = True
        elif next_due_date == today:
            due_by_date = True
        elif next_due_date <= today + timedelta(days=int(warning_days_before)):
            due_soon_by_date = True

    current_odometer = _extract_vehicle_current_odometer(
        document.get("vehicle_id"),
        fallback_odometer=document.get("last_done_odometer"),
    )
    next_due_odometer = document.get("next_due_odometer")
    warning_km_before = float(document.get("warning_km_before") or 0)
    overdue_by_km = False
    due_by_km = False
    due_soon_by_km = False

    if next_due_odometer is not None and current_odometer is not None:
        if current_odometer > float(next_due_odometer):
            overdue_by_km = True
        elif current_odometer == float(next_due_odometer):
            due_by_km = True
        elif current_odometer >= max(float(next_due_odometer) - warning_km_before, 0):
            due_soon_by_km = True

    if overdue_by_date or overdue_by_km:
        return "overdue"
    if due_by_date or due_by_km:
        return "due"
    if due_soon_by_date or due_soon_by_km:
        return "due_soon"
    return "active"


def _sync_status(document: dict):
    next_status = _determine_status(document)
    if document.get("status") != next_status:
        preventive_maintenance_collection().update_one(
            {"_id": document["_id"]},
            {"$set": {"status": next_status, "updated_at": now_utc()}},
        )
        document["status"] = next_status
        document["updated_at"] = now_utc()
    return document


def _notify_schedule_status(document: dict):
    today = date.today().isoformat()
    status = document.get("status")
    if status not in {"due_soon", "due", "overdue"}:
        return
    if document.get("last_notification_status") == f"{status}:{today}":
        return

    vehicle_document = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
    assigned_driver_id = vehicle_document.get("assigned_driver_id") if vehicle_document else None
    vehicle_label = vehicle_document.get("registration_number") if vehicle_document else "vehicle"
    message = f"{vehicle_label} is {status.replace('_', ' ')} for {document.get('title')}."
    priority = "high" if status in {"due", "overdue"} else "medium"

    if assigned_driver_id:
        create_notification(
            recipient_user_id=assigned_driver_id,
            title="Vehicle Maintenance Reminder",
            message=message,
            category="maintenance",
            priority=priority,
            reference_type="preventive_maintenance",
            reference_id=document["_id"],
        )

    notify_roles(
        ["admin", "owner"],
        title="Preventive Maintenance Alert",
        message=message,
        category="maintenance",
        priority=priority,
        reference_type="preventive_maintenance",
        reference_id=document["_id"],
    )

    preventive_maintenance_collection().update_one(
        {"_id": document["_id"]},
        {"$set": {"last_notification_status": f"{status}:{today}", "updated_at": now_utc()}},
    )
    document["last_notification_status"] = f"{status}:{today}"
    document["updated_at"] = now_utc()


def _enrich_schedule(document: dict):
    schedule = serialize_preventive_schedule(document)
    vehicle_document = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
    assigned_admin_document = users_collection().find_one({"_id": document.get("assigned_admin_id")}) if document.get("assigned_admin_id") else None
    schedule["vehicle"] = serialize_vehicle(vehicle_document) if vehicle_document else None
    schedule["assigned_admin"] = serialize_user(assigned_admin_document) if assigned_admin_document else None
    schedule["current_odometer"] = _extract_vehicle_current_odometer(document.get("vehicle_id"), document.get("last_done_odometer"))
    return schedule


def _build_default_schedule_document(template: dict, vehicle_document: dict, created_by: ObjectId, assigned_admin_id: ObjectId | None):
    today = date.today()
    recurrence_type = template["recurrence_type"]
    interval_days, interval_months, interval_km = _resolve_recurrence_defaults(
        recurrence_type,
        template.get("interval_days"),
        template.get("interval_months"),
        template.get("interval_km"),
    )
    next_due_date, next_due_odometer = _calculate_next_due_values(
        base_date=today,
        base_odometer=None,
        recurrence_type=recurrence_type,
        interval_days=interval_days,
        interval_months=interval_months,
        interval_km=interval_km,
    )

    return {
        "vehicle_id": vehicle_document["_id"],
        "maintenance_type": template["maintenance_type"],
        "maintenance_item": template["maintenance_type"],
        "title": template["title"],
        "description": template["description"],
        "recurrence_type": recurrence_type,
        "schedule_type": _infer_schedule_type_from_recurrence(recurrence_type),
        "interval_days": interval_days,
        "interval_months": interval_months,
        "interval_km": interval_km,
        "last_done_date": None,
        "last_done_odometer": None,
        "next_due_date": next_due_date,
        "next_due_odometer": next_due_odometer,
        "warning_days_before": template.get("warning_days_before", 0),
        "warning_km_before": template.get("warning_km_before", 0),
        "status": "active",
        "assigned_admin_id": assigned_admin_id,
        "notes": None,
        "completed_date": None,
        "completed_odometer": None,
        "mechanic_name": None,
        "work_done": None,
        "parts_changed": None,
        "condition_notes": None,
        "completed_by": None,
        "completion_history": [],
        "generated_maintenance_job_id": None,
        "last_notification_status": None,
        "created_by": created_by,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }


def generate_default_preventive_schedules_for_vehicle(vehicle_id: str | ObjectId, current_user_id: str | ObjectId):
    vehicle_document = _get_vehicle_document(vehicle_id)
    creator_id = _to_object_id(current_user_id, "current_user_id")
    assigned_admin_id = _pick_assigned_admin(vehicle_document, creator_id)

    created_schedules = []
    for template in DEFAULT_PREVENTIVE_TEMPLATES:
        existing = preventive_maintenance_collection().find_one(
            {
                "vehicle_id": vehicle_document["_id"],
                "maintenance_type": template["maintenance_type"],
            }
        )
        if existing:
            document = _sync_status(existing)
            created_schedules.append(_enrich_schedule(document))
            continue

        document = _build_default_schedule_document(template, vehicle_document, creator_id, assigned_admin_id)
        insert_result = preventive_maintenance_collection().insert_one(document)
        document["_id"] = insert_result.inserted_id
        document = _sync_status(document)
        _notify_schedule_status(document)
        created_schedules.append(_enrich_schedule(document))

    return created_schedules


def seed_preventive_schedules_for_existing_vehicles():
    vehicles = vehicles_collection().find({})
    owner_or_admin = users_collection().find_one({"role": {"$in": ["owner", "admin"]}, "status": "active"})
    current_user_id = owner_or_admin["_id"] if owner_or_admin else ObjectId()
    for vehicle in vehicles:
        generate_default_preventive_schedules_for_vehicle(vehicle["_id"], current_user_id)


def _ensure_default_schedules(current_user_id: str, current_role: str, vehicle_id: str | None = None):
    if current_role == "driver":
        assigned_vehicle_id = _resolve_driver_vehicle_for_driver(current_user_id)
        if assigned_vehicle_id is not None:
            generate_default_preventive_schedules_for_vehicle(assigned_vehicle_id, current_user_id)
        return

    if vehicle_id:
        generate_default_preventive_schedules_for_vehicle(vehicle_id, current_user_id)
        return


def list_preventive_maintenance(current_user_id: str, current_role: str, vehicle_id: str | None = None):
    _ensure_default_schedules(current_user_id, current_role, vehicle_id=vehicle_id)

    query = {}
    if current_role == "driver":
        assigned_vehicle_id = _resolve_driver_vehicle_for_driver(current_user_id)
        if assigned_vehicle_id is None:
            return []
        query["vehicle_id"] = assigned_vehicle_id
    elif vehicle_id:
        query["vehicle_id"] = _to_object_id(vehicle_id, "vehicle_id")

    documents = list(
        preventive_maintenance_collection()
        .find(query)
        .sort([("status", ASCENDING), ("next_due_date", ASCENDING), ("created_at", DESCENDING)])
    )
    schedules = []
    for document in documents:
        document = _sync_status(document)
        _notify_schedule_status(document)
        schedules.append(_enrich_schedule(document))
    return schedules


def get_preventive_schedule_by_id(schedule_id: str, current_user_id: str, current_role: str):
    document = _get_schedule_document(schedule_id)
    if current_role == "driver":
        assigned_vehicle_id = _resolve_driver_vehicle_for_driver(current_user_id)
        if assigned_vehicle_id is None or document.get("vehicle_id") != assigned_vehicle_id:
            raise ApiError("You do not have permission to view this schedule.", status_code=403)
    document = _sync_status(document)
    _notify_schedule_status(document)
    return _enrich_schedule(document)


def list_due_soon_schedules(current_user_id: str, current_role: str, vehicle_id: str | None = None):
    schedules = list_preventive_maintenance(current_user_id, current_role, vehicle_id=vehicle_id)
    return [schedule for schedule in schedules if schedule.get("status") == "due_soon"]


def list_overdue_schedules(current_user_id: str, current_role: str, vehicle_id: str | None = None):
    schedules = list_preventive_maintenance(current_user_id, current_role, vehicle_id=vehicle_id)
    return [schedule for schedule in schedules if schedule.get("status") == "overdue"]


def _validate_schedule_payload(payload: dict, partial: bool = False, existing_document: dict | None = None):
    update_fields = {}

    if "vehicle_id" in payload or not partial:
        vehicle_document = _get_vehicle_document(payload.get("vehicle_id") if partial else payload.get("vehicle_id"))
        update_fields["vehicle_id"] = vehicle_document["_id"]
    else:
        vehicle_document = _get_vehicle_document(existing_document.get("vehicle_id"))

    maintenance_value = payload.get("maintenance_type", payload.get("maintenance_item"))
    if "maintenance_type" in payload or "maintenance_item" in payload or not partial:
        maintenance_type = _validate_maintenance_type(maintenance_value)
        update_fields["maintenance_type"] = maintenance_type
        update_fields["maintenance_item"] = maintenance_type

    if "title" in payload or not partial:
        title = (payload.get("title") or "").strip()
        if not title:
            raise ApiError("title is required.", status_code=400)
        update_fields["title"] = title

    if "description" in payload or not partial:
        update_fields["description"] = _normalize_text(payload.get("description"))
    if "notes" in payload or not partial:
        update_fields["notes"] = _normalize_text(payload.get("notes"))

    if "recurrence_type" in payload or not partial:
        recurrence_type = _validate_recurrence_type(payload.get("recurrence_type"))
        update_fields["recurrence_type"] = recurrence_type
        update_fields["schedule_type"] = _infer_schedule_type_from_recurrence(recurrence_type)
    elif "schedule_type" in payload:
        schedule_type = _validate_schedule_type(payload.get("schedule_type"))
        update_fields["schedule_type"] = schedule_type
        recurrence_type = existing_document.get("recurrence_type") if existing_document else None
    else:
        recurrence_type = _infer_recurrence_type(existing_document or {})

    if "interval_days" in payload or not partial:
        update_fields["interval_days"] = _validate_positive_int(payload.get("interval_days"), "interval_days")
    if "interval_months" in payload or not partial:
        update_fields["interval_months"] = _validate_positive_int(payload.get("interval_months"), "interval_months")
    if "interval_km" in payload or not partial:
        update_fields["interval_km"] = _validate_positive_number(payload.get("interval_km"), "interval_km")

    effective_days = update_fields.get("interval_days", existing_document.get("interval_days") if existing_document else None)
    effective_months = update_fields.get("interval_months", existing_document.get("interval_months") if existing_document else None)
    effective_km = update_fields.get("interval_km", existing_document.get("interval_km") if existing_document else None)
    resolved_days, resolved_months, resolved_km = _resolve_recurrence_defaults(
        update_fields.get("recurrence_type", recurrence_type),
        effective_days,
        effective_months,
        effective_km,
    )
    update_fields["interval_days"] = resolved_days
    update_fields["interval_months"] = resolved_months
    update_fields["interval_km"] = resolved_km
    update_fields["schedule_type"] = _infer_schedule_type_from_recurrence(update_fields.get("recurrence_type", recurrence_type))

    if "last_done_date" in payload:
        update_fields["last_done_date"] = _serialize_date(_parse_date(payload.get("last_done_date"), "last_done_date", required=False))
    if "last_done_odometer" in payload:
        update_fields["last_done_odometer"] = _validate_positive_number(payload.get("last_done_odometer"), "last_done_odometer")
    if "next_due_date" in payload:
        update_fields["next_due_date"] = _serialize_date(_parse_date(payload.get("next_due_date"), "next_due_date", required=False))
    if "next_due_odometer" in payload:
        update_fields["next_due_odometer"] = _validate_positive_number(payload.get("next_due_odometer"), "next_due_odometer")
    if "warning_days_before" in payload or not partial:
        update_fields["warning_days_before"] = _validate_positive_int(payload.get("warning_days_before"), "warning_days_before") or 0
    if "warning_km_before" in payload or not partial:
        update_fields["warning_km_before"] = _validate_positive_number(payload.get("warning_km_before"), "warning_km_before") or 0
    if "assigned_admin_id" in payload or not partial:
        assigned_admin_id = _to_object_id(payload.get("assigned_admin_id"), "assigned_admin_id", required=False)
        if assigned_admin_id:
            admin_document = _get_user_document(assigned_admin_id, "assigned_admin_id")
            if admin_document.get("role") not in {"owner", "admin"}:
                raise ApiError("assigned_admin_id must belong to an owner or admin.", status_code=400)
        update_fields["assigned_admin_id"] = assigned_admin_id
    if "status" in payload:
        update_fields["status"] = _validate_status(payload.get("status"), required=True)

    return vehicle_document, update_fields


def create_preventive_schedule(payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to create preventive maintenance schedules.", status_code=403)

    vehicle_document, update_fields = _validate_schedule_payload(payload, partial=False)
    existing = preventive_maintenance_collection().find_one(
        {
            "vehicle_id": vehicle_document["_id"],
            "maintenance_type": update_fields["maintenance_type"],
        }
    )
    if existing:
        raise ApiError("This vehicle already has a schedule for that maintenance type.", status_code=409)

    timestamp = now_utc()
    document = {
        **update_fields,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "completed_date": None,
        "completed_odometer": None,
        "mechanic_name": None,
        "work_done": None,
        "parts_changed": None,
        "condition_notes": None,
        "completed_by": None,
        "completion_history": [],
        "generated_maintenance_job_id": None,
        "last_notification_status": None,
    }
    if document.get("status") is None:
        document["status"] = "active"

    result = preventive_maintenance_collection().insert_one(document)
    document["_id"] = result.inserted_id
    document = _sync_status(document)
    _notify_schedule_status(document)
    return _enrich_schedule(document)


def update_preventive_schedule(schedule_id: str, payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update preventive maintenance schedules.", status_code=403)

    document = _get_schedule_document(schedule_id)
    vehicle_document, update_fields = _validate_schedule_payload(payload, partial=True, existing_document=document)
    del vehicle_document
    if not update_fields:
        raise ApiError("No valid schedule fields provided for update.", status_code=400)

    duplicate = None
    if "maintenance_type" in update_fields or "vehicle_id" in update_fields:
        duplicate = preventive_maintenance_collection().find_one(
            {
                "vehicle_id": update_fields.get("vehicle_id", document.get("vehicle_id")),
                "maintenance_type": update_fields.get("maintenance_type", document.get("maintenance_type")),
                "_id": {"$ne": document["_id"]},
            }
        )
    if duplicate:
        raise ApiError("This vehicle already has a schedule for that maintenance type.", status_code=409)

    update_fields["updated_at"] = now_utc()
    preventive_maintenance_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    document = _sync_status(document)
    _notify_schedule_status(document)
    return _enrich_schedule(document)


def complete_preventive_schedule(schedule_id: str, payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to complete preventive maintenance schedules.", status_code=403)

    document = _get_schedule_document(schedule_id)
    vehicle_document = _get_vehicle_document(document.get("vehicle_id"))
    completion_date = _parse_date(payload.get("completed_date") or payload.get("last_done_date") or date.today().isoformat(), "completed_date", required=True)
    completion_odometer = _validate_positive_number(
        payload.get("completed_odometer", payload.get("last_done_odometer")),
        "completed_odometer",
        required=False,
    )
    recurrence_type = _infer_recurrence_type(document)
    timestamp = now_utc()

    next_due_date, next_due_odometer = _calculate_next_due_values(
        base_date=completion_date,
        base_odometer=completion_odometer,
        recurrence_type=recurrence_type,
        interval_days=document.get("interval_days"),
        interval_months=document.get("interval_months"),
        interval_km=document.get("interval_km"),
    )
    override_next_due_date = _parse_date(payload.get("next_due_date"), "next_due_date", required=False)
    override_next_due_odometer = _validate_positive_number(payload.get("next_due_odometer"), "next_due_odometer", required=False)
    if override_next_due_date is not None:
        next_due_date = _serialize_date(override_next_due_date)
    if override_next_due_odometer is not None:
        next_due_odometer = override_next_due_odometer

    history_entry = {
        "completed_date": completion_date.isoformat(),
        "completed_odometer": completion_odometer,
        "mechanic_name": _normalize_text(payload.get("mechanic_name")),
        "work_done": _normalize_text(payload.get("work_done")),
        "parts_changed": _normalize_parts_changed(payload.get("parts_changed")),
        "condition_notes": _normalize_text(payload.get("condition_notes")),
        "next_due_date": next_due_date,
        "next_due_odometer": next_due_odometer,
        "completed_by": _to_object_id(current_user_id, "completed_by"),
        "completed_at": timestamp,
    }

    update_fields = {
        "last_done_date": completion_date.isoformat(),
        "last_done_odometer": completion_odometer,
        "completed_date": completion_date.isoformat(),
        "completed_odometer": completion_odometer,
        "mechanic_name": history_entry["mechanic_name"],
        "work_done": history_entry["work_done"],
        "parts_changed": history_entry["parts_changed"],
        "condition_notes": history_entry["condition_notes"],
        "next_due_date": next_due_date,
        "next_due_odometer": next_due_odometer,
        "completed_by": history_entry["completed_by"],
        "status": "active",
        "updated_at": timestamp,
        "last_notification_status": None,
        "generated_maintenance_job_id": None,
    }
    preventive_maintenance_collection().update_one(
        {"_id": document["_id"]},
        {
            "$set": update_fields,
            "$push": {"completion_history": history_entry},
        },
    )
    document.update(update_fields)
    completion_history = list(document.get("completion_history") or [])
    completion_history.append(history_entry)
    document["completion_history"] = completion_history
    document = _sync_status(document)
    _notify_schedule_status(document)

    vehicles_collection().update_one(
        {"_id": vehicle_document["_id"]},
        {
            "$push": {
                "maintenance_history": {
                    "preventive_schedule_id": document["_id"],
                    "maintenance_type": document.get("maintenance_type"),
                    "title": document.get("title"),
                    **history_entry,
                }
            },
            "$set": {"updated_at": timestamp},
        },
    )
    return _enrich_schedule(document)


def generate_maintenance_job_from_schedule(schedule_id: str, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to generate maintenance jobs from schedules.", status_code=403)

    document = _get_schedule_document(schedule_id)
    vehicle_document = _get_vehicle_document(document.get("vehicle_id"))
    payload = {
        "vehicle_id": str(document.get("vehicle_id")),
        "maintenance_type": "servicing" if document.get("maintenance_type") != "other" else "other",
        "title": document.get("title"),
        "description": document.get("description") or f"Generated from preventive maintenance schedule for {document.get('title')}.",
        "priority": "critical" if document.get("status") == "overdue" else "medium",
        "vendor_name": None,
        "vendor_contact": None,
        "estimated_cost": None,
        "odometer_reading": _extract_vehicle_current_odometer(document.get("vehicle_id"), document.get("last_done_odometer")),
        "start_date": date.today().isoformat(),
        "target_completion_date": document.get("next_due_date") or (date.today() + timedelta(days=7)).isoformat(),
        "maintenance_coordinator_id": str(document.get("assigned_admin_id")) if document.get("assigned_admin_id") else None,
        "current_stage": "assigned_to_mechanic",
        "next_action": f"Carry out preventive maintenance: {document.get('title')}.",
        "next_follow_up_date": date.today().isoformat(),
        "notes": f"Generated from preventive maintenance schedule for vehicle {vehicle_document.get('registration_number')}.",
    }
    if vehicle_document.get("assigned_driver_id"):
        payload["driver_id"] = str(vehicle_document.get("assigned_driver_id"))

    job = create_maintenance_job(payload, current_user_id=current_user_id, current_role=current_role)
    preventive_maintenance_collection().update_one(
        {"_id": document["_id"]},
        {"$set": {"generated_maintenance_job_id": ObjectId(job["id"]), "updated_at": now_utc()}},
    )
    return job


def seed_default_compliance_item_types():
    owner_or_admin = users_collection().find_one({"role": {"$in": ["owner", "admin"]}, "status": "active"})
    created_by = owner_or_admin["_id"] if owner_or_admin else ObjectId()
    for item in DEFAULT_COMPLIANCE_TYPES:
        normalized_name = _normalized_key(item["item_name"])
        existing = compliance_item_types_collection().find_one({"normalized_name": normalized_name})
        if existing:
            continue
        compliance_item_types_collection().insert_one(
            {
                "item_name": item["item_name"],
                "normalized_name": normalized_name,
                "category": item["category"],
                "status": "active",
                "created_by": created_by,
                "created_at": now_utc(),
                "updated_at": now_utc(),
            }
        )


def _compliance_notification_offsets(warning_days_before: int):
    offsets = {30, 14, 7, 3, 1}
    if warning_days_before > 0:
        offsets.add(int(warning_days_before))
    return sorted(offsets, reverse=True)


def _renewal_frequency_interval(renewal_frequency: str, custom_interval_days):
    if renewal_frequency == "yearly":
        return {"months": 12, "days": None}
    if renewal_frequency == "every_6_months":
        return {"months": 6, "days": None}
    if renewal_frequency == "quarterly":
        return {"months": 3, "days": None}
    if renewal_frequency == "monthly":
        return {"months": 1, "days": None}
    return {"months": None, "days": custom_interval_days}


def _calculate_compliance_status(document: dict):
    status = document.get("status")
    if status == "inactive":
        return "inactive"

    expiry_date = _parse_date(document.get("expiry_date"), "expiry_date", required=False)
    if not expiry_date:
        return "active"

    today = date.today()
    if expiry_date < today:
        return "expired"
    if expiry_date == today:
        return "due_soon"

    days_until_expiry = (expiry_date - today).days
    warning_days_before = int(document.get("warning_days_before") or 0)
    if days_until_expiry <= warning_days_before or days_until_expiry in _compliance_notification_offsets(warning_days_before):
        return "due_soon"
    return "active"


def _sync_compliance_status(document: dict):
    next_status = _calculate_compliance_status(document)
    if document.get("status") != next_status:
        compliance_records_collection().update_one(
            {"_id": document["_id"]},
            {"$set": {"status": next_status, "updated_at": now_utc()}},
        )
        document["status"] = next_status
        document["updated_at"] = now_utc()
    return document


def _notify_compliance_status(document: dict):
    status = document.get("status")
    if status not in {"due_soon", "expired"}:
        return

    expiry_date = _parse_date(document.get("expiry_date"), "expiry_date", required=False)
    if not expiry_date:
        return

    today = date.today()
    days_until_expiry = (expiry_date - today).days
    marker = f"{status}:expired" if days_until_expiry < 0 else f"{status}:{days_until_expiry}"
    if document.get("last_notification_marker") == marker:
        return

    vehicle_document = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
    vehicle_label = vehicle_document.get("registration_number") if vehicle_document else "vehicle"
    assigned_driver_id = vehicle_document.get("assigned_driver_id") if vehicle_document else None
    item_name = document.get("compliance_item_name") or "Compliance item"
    if days_until_expiry < 0:
        message = f"{item_name} for {vehicle_label} has expired."
        priority = "critical"
    else:
        message = f"{item_name} for {vehicle_label} expires in {days_until_expiry} day{'s' if days_until_expiry != 1 else ''}."
        priority = "high" if days_until_expiry <= 7 else "medium"

    if assigned_driver_id:
        create_notification(
            recipient_user_id=assigned_driver_id,
            title="Vehicle Compliance Alert",
            message=message,
            category="maintenance",
            priority=priority,
            reference_type="compliance_record",
            reference_id=document["_id"],
        )

    notify_roles(
        ["admin", "owner"],
        title="Compliance Renewal Alert",
        message=message,
        category="maintenance",
        priority=priority,
        reference_type="compliance_record",
        reference_id=document["_id"],
    )
    compliance_records_collection().update_one(
        {"_id": document["_id"]},
        {"$set": {"last_notification_marker": marker, "updated_at": now_utc()}},
    )
    document["last_notification_marker"] = marker
    document["updated_at"] = now_utc()


def _serialize_compliance_record_with_relations(document: dict):
    record = serialize_compliance_record(document)
    vehicle_document = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
    compliance_type = compliance_item_types_collection().find_one({"_id": document.get("compliance_type_id")}) if document.get("compliance_type_id") else None
    record["vehicle"] = serialize_vehicle(vehicle_document) if vehicle_document else None
    record["compliance_type"] = serialize_compliance_type(compliance_type) if compliance_type else None
    return record


def list_compliance_item_types(current_role: str, active_only: bool = False):
    seed_default_compliance_item_types()
    query = {}
    if active_only or current_role == "driver":
        query["status"] = "active"
    documents = compliance_item_types_collection().find(query).sort([("item_name", ASCENDING)])
    return [serialize_compliance_type(document) for document in documents]


def create_compliance_item_type(payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to manage compliance item types.", status_code=403)
    item_name = _normalize_item_name(payload.get("item_name"), "item_name")
    normalized_name = _normalized_key(item_name)
    duplicate = compliance_item_types_collection().find_one({"normalized_name": normalized_name})
    if duplicate:
        raise ApiError("A compliance item type with that name already exists.", status_code=409)
    document = {
        "item_name": item_name,
        "normalized_name": normalized_name,
        "category": _normalize_text(payload.get("category")) or "other",
        "status": "active" if payload.get("status") in (None, "", "active") else "inactive",
        "created_by": _to_object_id(current_user_id, "created_by"),
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    result = compliance_item_types_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return serialize_compliance_type(document)


def update_compliance_item_type(type_id: str, payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to manage compliance item types.", status_code=403)
    del current_user_id
    type_object_id = _to_object_id(type_id, "compliance_type_id")
    document = compliance_item_types_collection().find_one({"_id": type_object_id})
    if not document:
        raise ApiError("Compliance item type not found.", status_code=404)

    update_fields = {}
    if "item_name" in payload:
        item_name = _normalize_item_name(payload.get("item_name"), "item_name")
        normalized_name = _normalized_key(item_name)
        duplicate = compliance_item_types_collection().find_one({"normalized_name": normalized_name, "_id": {"$ne": type_object_id}})
        if duplicate:
            raise ApiError("A compliance item type with that name already exists.", status_code=409)
        update_fields["item_name"] = item_name
        update_fields["normalized_name"] = normalized_name
    if "category" in payload:
        update_fields["category"] = _normalize_text(payload.get("category")) or "other"
    if "status" in payload:
        next_status = str(payload.get("status")).strip().lower()
        if next_status not in {"active", "inactive"}:
            raise ApiError("status must be active or inactive.", status_code=400)
        update_fields["status"] = next_status
    if not update_fields:
        raise ApiError("No valid compliance item type fields provided.", status_code=400)
    update_fields["updated_at"] = now_utc()
    compliance_item_types_collection().update_one({"_id": type_object_id}, {"$set": update_fields})
    document.update(update_fields)
    return serialize_compliance_type(document)


def _validate_compliance_record_payload(payload: dict, partial: bool = False, existing_document: dict | None = None):
    update_fields = {}

    if "vehicle_id" in payload or not partial:
        vehicle_document = _get_vehicle_document(payload.get("vehicle_id"))
        update_fields["vehicle_id"] = vehicle_document["_id"]
    else:
        vehicle_document = _get_vehicle_document(existing_document.get("vehicle_id"))

    compliance_item_name = payload.get("compliance_item_name")
    compliance_type_id = payload.get("compliance_type_id")
    compliance_type_document = None
    if compliance_type_id not in (None, ""):
        compliance_type_document = compliance_item_types_collection().find_one({"_id": _to_object_id(compliance_type_id, "compliance_type_id")})
        if not compliance_type_document:
            raise ApiError("Compliance item type not found.", status_code=404)
        if compliance_type_document.get("status") != "active" and not partial:
            raise ApiError("Selected compliance item type is inactive.", status_code=400)
        update_fields["compliance_type_id"] = compliance_type_document["_id"]
        update_fields["compliance_item_name"] = compliance_type_document.get("item_name")
    elif compliance_item_name not in (None, "") or not partial:
        update_fields["compliance_type_id"] = None
        update_fields["compliance_item_name"] = _normalize_item_name(compliance_item_name, "compliance_item_name")

    if "provider_or_authority_name" in payload or not partial:
        update_fields["provider_or_authority_name"] = _normalize_text(payload.get("provider_or_authority_name"))
    if "policy_or_reference_number" in payload or not partial:
        update_fields["policy_or_reference_number"] = _normalize_text(payload.get("policy_or_reference_number"))
    if "issue_date" in payload or not partial:
        update_fields["issue_date"] = _serialize_date(_parse_date(payload.get("issue_date"), "issue_date", required=not partial))
    if "expiry_date" in payload or not partial:
        update_fields["expiry_date"] = _serialize_date(_parse_date(payload.get("expiry_date"), "expiry_date", required=not partial))
    if "renewal_frequency" in payload or not partial:
        update_fields["renewal_frequency"] = _validate_renewal_frequency(payload.get("renewal_frequency"), required=not partial)
    if "custom_interval_days" in payload or not partial:
        update_fields["custom_interval_days"] = _validate_positive_int(payload.get("custom_interval_days"), "custom_interval_days")
    if "warning_days_before" in payload or not partial:
        update_fields["warning_days_before"] = _validate_positive_int(payload.get("warning_days_before"), "warning_days_before") or 30
    if "document_upload" in payload or not partial:
        update_fields["document_upload"] = payload.get("document_upload")
    if "notes" in payload or not partial:
        update_fields["notes"] = _normalize_text(payload.get("notes"))
    if "status" in payload:
        update_fields["status"] = _validate_compliance_status(payload.get("status"), required=True)

    renewal_frequency = update_fields.get("renewal_frequency", existing_document.get("renewal_frequency") if existing_document else None)
    custom_interval_days = update_fields.get("custom_interval_days", existing_document.get("custom_interval_days") if existing_document else None)
    if renewal_frequency == "custom" and custom_interval_days is None:
        raise ApiError("custom_interval_days is required when renewal_frequency is custom.", status_code=400)

    return vehicle_document, update_fields


def create_compliance_record(payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to create compliance records.", status_code=403)
    vehicle_document, update_fields = _validate_compliance_record_payload(payload, partial=False)
    del vehicle_document
    timestamp = now_utc()
    document = {
        **update_fields,
        "status": update_fields.get("status") or "active",
        "last_notification_marker": None,
        "history": [],
        "created_by": _to_object_id(current_user_id, "created_by"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = compliance_records_collection().insert_one(document)
    document["_id"] = result.inserted_id
    document = _sync_compliance_status(document)
    _notify_compliance_status(document)
    return _serialize_compliance_record_with_relations(document)


def list_compliance_records(current_user_id: str, current_role: str, vehicle_id: str | None = None):
    seed_default_compliance_item_types()
    query = {}
    if current_role == "driver":
        assigned_vehicle_id = _resolve_driver_vehicle_for_driver(current_user_id)
        if assigned_vehicle_id is None:
            return []
        query["vehicle_id"] = assigned_vehicle_id
    elif vehicle_id:
        query["vehicle_id"] = _to_object_id(vehicle_id, "vehicle_id")
    documents = list(
        compliance_records_collection()
        .find(query)
        .sort([("status", ASCENDING), ("expiry_date", ASCENDING), ("created_at", DESCENDING)])
    )
    records = []
    for document in documents:
        document = _sync_compliance_status(document)
        _notify_compliance_status(document)
        records.append(_serialize_compliance_record_with_relations(document))
    return records


def update_compliance_record(record_id: str, payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update compliance records.", status_code=403)
    del current_user_id
    record_object_id = _to_object_id(record_id, "compliance_record_id")
    document = compliance_records_collection().find_one({"_id": record_object_id})
    if not document:
        raise ApiError("Compliance record not found.", status_code=404)
    vehicle_document, update_fields = _validate_compliance_record_payload(payload, partial=True, existing_document=document)
    del vehicle_document
    if not update_fields:
        raise ApiError("No valid compliance record fields provided.", status_code=400)
    update_fields["updated_at"] = now_utc()
    compliance_records_collection().update_one({"_id": record_object_id}, {"$set": update_fields})
    document.update(update_fields)
    document = _sync_compliance_status(document)
    _notify_compliance_status(document)
    return _serialize_compliance_record_with_relations(document)


def renew_compliance_record(record_id: str, payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to renew compliance records.", status_code=403)
    record_object_id = _to_object_id(record_id, "compliance_record_id")
    document = compliance_records_collection().find_one({"_id": record_object_id})
    if not document:
        raise ApiError("Compliance record not found.", status_code=404)

    issue_date = _parse_date(payload.get("issue_date"), "issue_date", required=True)
    expiry_date = _parse_date(payload.get("expiry_date"), "expiry_date", required=True)
    if expiry_date <= issue_date:
        raise ApiError("expiry_date must be after issue_date.", status_code=400)

    renewal_frequency = _validate_renewal_frequency(payload.get("renewal_frequency", document.get("renewal_frequency")), required=True)
    custom_interval_days = _validate_positive_int(payload.get("custom_interval_days", document.get("custom_interval_days")), "custom_interval_days")
    if renewal_frequency == "custom" and custom_interval_days is None:
        raise ApiError("custom_interval_days is required when renewal_frequency is custom.", status_code=400)

    history_entry = {
        "previous_issue_date": document.get("issue_date"),
        "previous_expiry_date": document.get("expiry_date"),
        "previous_status": document.get("status"),
        "document_upload": document.get("document_upload"),
        "notes": document.get("notes"),
        "renewed_at": now_utc(),
        "renewed_by": _to_object_id(current_user_id, "renewed_by"),
    }
    update_fields = {
        "issue_date": issue_date.isoformat(),
        "expiry_date": expiry_date.isoformat(),
        "renewal_frequency": renewal_frequency,
        "custom_interval_days": custom_interval_days,
        "provider_or_authority_name": _normalize_text(payload.get("provider_or_authority_name")) or document.get("provider_or_authority_name"),
        "policy_or_reference_number": _normalize_text(payload.get("policy_or_reference_number")) or document.get("policy_or_reference_number"),
        "warning_days_before": _validate_positive_int(payload.get("warning_days_before", document.get("warning_days_before")), "warning_days_before") or 30,
        "document_upload": payload.get("document_upload", document.get("document_upload")),
        "notes": _normalize_text(payload.get("notes")) if "notes" in payload else document.get("notes"),
        "status": "renewed",
        "last_notification_marker": None,
        "updated_at": now_utc(),
    }
    compliance_records_collection().update_one(
        {"_id": record_object_id},
        {"$set": update_fields, "$push": {"history": history_entry}},
    )
    document.update(update_fields)
    history = list(document.get("history") or [])
    history.append(history_entry)
    document["history"] = history
    document = _sync_compliance_status(document)
    _notify_compliance_status(document)
    return _serialize_compliance_record_with_relations(document)


def get_compliance_dashboard_summary(current_user_id: str, current_role: str):
    records = list_compliance_records(current_user_id, current_role)
    today = date.today()
    expiring_soon = [record for record in records if record.get("status") == "due_soon"]
    expired = [record for record in records if record.get("status") == "expired"]
    renewed_this_month = [
        record for record in records
        if record.get("updated_at") and datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00")).date().year == today.year
        and datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00")).date().month == today.month
        and (record.get("history") or [])
    ]
    active_types = list_compliance_item_types(current_role=current_role, active_only=True)
    vehicles = list(vehicles_collection().find({}).sort("registration_number", ASCENDING)) if current_role in {"owner", "admin"} else []
    missing = []
    compliance_by_vehicle = []
    if current_role in {"owner", "admin"}:
        active_type_names = {entry["item_name"] for entry in active_types}
        records_by_vehicle = {}
        for record in records:
            records_by_vehicle.setdefault(record["vehicle_id"], set()).add(record["compliance_item_name"])
        for vehicle in vehicles:
            vehicle_record_names = records_by_vehicle.get(str(vehicle["_id"]), set())
            missing_items = sorted(active_type_names - vehicle_record_names)
            if missing_items:
                missing.append({
                    "vehicle_id": str(vehicle["_id"]),
                    "vehicle_registration_number": vehicle.get("registration_number"),
                    "missing_items": missing_items,
                })
            compliance_by_vehicle.append({
                "vehicle_id": str(vehicle["_id"]),
                "vehicle_registration_number": vehicle.get("registration_number"),
                "total_records": len(vehicle_record_names),
                "missing_count": len(missing_items),
            })
    return {
        "expiring_soon": len(expiring_soon),
        "expired": len(expired),
        "renewed_this_month": len(renewed_this_month),
        "vehicles_with_missing_compliance": missing,
        "compliance_by_vehicle": compliance_by_vehicle,
    }
