from collections import Counter
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from flask import current_app

from extensions import get_collection
from models.booking import serialize_booking
from models.customer import serialize_customer
from models.ride import serialize_ride
from models.user import serialize_user
from services.master_data_service import (
    get_active_master_data_items,
    get_active_master_data_values,
    resolve_master_data_item,
)
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached
from utils.validators import normalize_email, normalize_phone, validate_email, validate_phone


CUSTOMER_STATUSES = {"active", "inactive"}
FOLLOW_UP_PRIORITIES = {"low", "medium", "high"}
SOURCE_OPTIONS = {
    "manual_entry": "Manual Entry",
    "ride_customer": "Ride Customer",
    "scheduled_booking": "Scheduled Booking",
    "referral": "Referral",
    "business_lead": "Business Lead",
    "imported_record": "Imported Record",
    "other": "Other",
}
CREATOR_ROLES = {"owner", "admin", "driver"}

MASTER_DATA_FIELD_CONFIG = {
    "customer_category": ("customer_categories", "customer_category_id", "customer_category", True),
    "customer_source": ("customer_sources", "customer_source_id", "customer_source", False),
    "organization_type": ("organization_types", "organization_type_id", "organization_type", False),
    "industry": ("industries", "industry_id", "industry", False),
    "relationship_category": ("relationship_categories", "relationship_category_id", "relationship_category", False),
    "opportunity_level": ("opportunity_levels", "opportunity_level_id", "opportunity_level", False),
    "network_value": ("network_values", "network_value_id", "network_value", False),
    "lead_status": ("lead_statuses", "lead_status_id", "lead_status", False),
    "potential_service": ("potential_services", "potential_service_id", "potential_service", False),
}


def now_utc():
    return datetime.now(timezone.utc)


def customers_collection():
    return get_collection("customers")


def bookings_collection():
    return get_collection("bookings")


def rides_collection():
    return get_collection("rides")


def users_collection():
    return get_collection("users")


def ensure_customer_indexes():
    ensure_indexes_for_collection(
        customers_collection(),
        [
            {"keys": [("customer_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("normalized_phone_number", ASCENDING)], "options": {"unique": True}},
            {
                "keys": [("normalized_email_address", ASCENDING)],
                "options": {"unique": True, "sparse": True},
            },
            {"keys": [("created_by", ASCENDING)]},
            {"keys": [("created_by_user_id", ASCENDING)]},
            {"keys": [("created_by_role", ASCENDING)]},
            {"keys": [("created_by_driver_id", ASCENDING)]},
            {"keys": [("preferred_driver_id", ASCENDING)]},
            {"keys": [("source", ASCENDING)]},
            {"keys": [("customer_category_id", ASCENDING)]},
            {"keys": [("relationship_category_id", ASCENDING)]},
            {"keys": [("opportunity_level_id", ASCENDING)]},
            {"keys": [("network_value_id", ASCENDING)]},
            {"keys": [("lead_status_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("follow_up_date", ASCENDING)]},
            {"keys": [("next_follow_up_date", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("preferred_driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
        ],
        collection_name="customers",
    )


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


def _normalize_date_string(value: Any, field_name: str):
    normalized = _normalize_text(value)
    if not normalized:
        return None
    try:
        date.fromisoformat(normalized)
    except ValueError as error:
        raise ApiError(f"{field_name} must be a valid YYYY-MM-DD date.", status_code=400) from error
    return normalized


def _date_from_string(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _validate_status(value: str | None):
    normalized = (_normalize_text(value) or "active").lower()
    if normalized not in CUSTOMER_STATUSES:
        raise ApiError("status must be active or inactive.", status_code=400)
    return normalized


def _validate_follow_up_priority(value: str | None):
    normalized = (_normalize_text(value) or "medium").lower()
    if normalized not in FOLLOW_UP_PRIORITIES:
        raise ApiError("follow_up_priority must be low, medium, or high.", status_code=400)
    return normalized


def _validate_boolean(value: Any, field_name: str):
    if isinstance(value, bool):
        return value
    raise ApiError(f"{field_name} must be a boolean value.", status_code=400)


def _validate_money(value, field_name: str):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    return round(float(value), 2)


def _validate_source(value: Any):
    normalized = (_normalize_text(value) or "manual_entry").lower()
    if normalized not in SOURCE_OPTIONS:
        raise ApiError(
            f"source must be one of: {', '.join(sorted(SOURCE_OPTIONS))}.",
            status_code=400,
        )
    return normalized


def _validate_creator_role(value: Any):
    normalized = _normalize_text(value)
    if not normalized:
        return None
    normalized = normalized.lower()
    if normalized not in CREATOR_ROLES:
        raise ApiError("creator_role must be owner, admin, or driver.", status_code=400)
    return normalized


def _build_customer_id():
    sequence = customers_collection().count_documents({}) + 1
    return f"CUS-{sequence:05d}"


def _serialize_audit_event(*, action: str, user_id: str, changes: list[str], note: str | None = None):
    return {
        "action": action,
        "at": now_utc(),
        "by": _to_object_id(user_id, "user_id"),
        "changes": changes,
        "note": note,
    }


def _serialize_follow_up_event(
    *,
    action: str,
    user_id: str,
    follow_up_date: str | None = None,
    next_follow_up_date: str | None = None,
    priority: str | None = None,
    note: str | None = None,
):
    return {
        "action": action,
        "date": follow_up_date,
        "next_follow_up_date": next_follow_up_date,
        "priority": priority,
        "note": note,
        "at": now_utc(),
        "by": _to_object_id(user_id, "user_id"),
    }


def _get_user_document(user_id: str) -> dict:
    user = users_collection().find_one({"_id": _to_object_id(user_id, "user_id")})
    if not user:
        raise ApiError("User not found.", status_code=404)
    return user


def _get_driver_document(driver_id: str | None):
    if driver_id in (None, ""):
        return None
    driver = users_collection().find_one({"_id": _to_object_id(driver_id, "preferred_driver_id"), "role": "driver"})
    if not driver:
        raise ApiError("Preferred driver not found.", status_code=404)
    return driver


def _source_label(source: str | None):
    return SOURCE_OPTIONS.get((source or "").lower())


def _parse_filter_date(value: Any, field_name: str):
    normalized = _normalize_text(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError as error:
        raise ApiError(f"{field_name} must be a valid YYYY-MM-DD date.", status_code=400) from error


def _normalize_customer_filters(filters: dict | None):
    raw = filters or {}
    date_from = _parse_filter_date(raw.get("date_from"), "date_from")
    date_to = _parse_filter_date(raw.get("date_to"), "date_to")
    if date_from and date_to and date_from > date_to:
        raise ApiError("date_from cannot be later than date_to.", status_code=400)
    creator_role = _validate_creator_role(raw.get("creator_role"))
    driver_id = raw.get("driver_id")
    customer_category_id = raw.get("customer_category_id")
    source = _normalize_text(raw.get("source"))
    if source:
        source = _validate_source(source)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "creator_role": creator_role,
        "driver_id": _to_object_id(driver_id, "driver_id", required=False) if driver_id else None,
        "customer_category_id": _to_object_id(customer_category_id, "customer_category_id", required=False)
        if customer_category_id
        else None,
        "source": source,
    }


def _get_customer_document(customer_id: str) -> dict:
    customer = customers_collection().find_one({"_id": _to_object_id(customer_id, "customer_id")})
    if not customer:
        raise ApiError("Customer not found.", status_code=404)
    return customer


def _customer_scope_query(current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return {}
    current_object_id = _to_object_id(current_user_id, "current_user_id")
    return {
        "$or": [
            {"created_by": current_object_id},
            {"preferred_driver_id": current_object_id},
        ]
    }


def _assert_customer_access(customer_document: dict, *, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    current_object_id = _to_object_id(current_user_id, "current_user_id")
    if current_role != "driver" or current_object_id not in {
        customer_document.get("created_by"),
        customer_document.get("preferred_driver_id"),
    }:
        raise ApiError("You do not have permission to access this customer.", status_code=403)


def _serialize_customer_summary(customer_document: dict) -> dict:
    customer = serialize_customer(customer_document)
    preferred_driver = users_collection().find_one({"_id": customer_document.get("preferred_driver_id")})
    created_by_user_id = customer_document.get("created_by_user_id") or customer_document.get("created_by")
    created_by_user = users_collection().find_one({"_id": created_by_user_id}) if created_by_user_id else None
    customer["preferred_driver"] = serialize_user(preferred_driver) if preferred_driver else None
    customer["created_by_user"] = serialize_user(created_by_user) if created_by_user else None
    customer["assigned_driver"] = customer["preferred_driver"]
    if not customer.get("created_by_name"):
        customer["created_by_name"] = created_by_user.get("full_name") if created_by_user else "Unknown / Legacy Record"
    if not customer.get("created_by_role"):
        customer["created_by_role"] = created_by_user.get("role") if created_by_user else "legacy"
    if not customer.get("created_by_driver_id") and (created_by_user or {}).get("role") == "driver":
        customer["created_by_driver_id"] = str(created_by_user["_id"])
    customer["source_label"] = _source_label(customer.get("source")) or customer.get("customer_source") or "Other"
    return customer


def _extract_datetime(value):
    if value:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _resolve_master_data_selection(
    payload: dict,
    *,
    selection_key: str,
    partial: bool,
    normalized: dict[str, Any],
):
    data_type, id_field, name_field, required = MASTER_DATA_FIELD_CONFIG[selection_key]
    id_in_payload = id_field in payload
    name_in_payload = name_field in payload
    legacy_industry_in_payload = selection_key == "industry" and "company_industry" in payload
    if not partial or id_in_payload or name_in_payload or legacy_industry_in_payload:
        identifier = None
        if id_in_payload:
            identifier = payload.get(id_field)
        elif name_in_payload:
            identifier = payload.get(name_field)
        elif legacy_industry_in_payload:
            identifier = payload.get("company_industry")

        if identifier in (None, ""):
            if required and not partial:
                raise ApiError(f"{name_field} is required.", status_code=400)
            if id_in_payload or name_in_payload or legacy_industry_in_payload:
                normalized[id_field] = None
                normalized[name_field] = None
                if selection_key == "industry":
                    normalized["company_industry"] = None
            return

        document = resolve_master_data_item(data_type, identifier, active_only=True)
        normalized[id_field] = document["_id"]
        normalized[name_field] = document["name"]
        if selection_key == "industry":
            normalized["company_industry"] = document["name"]


def _normalized_customer_payload(payload: dict, *, partial: bool = False) -> tuple[dict[str, Any], list[dict]]:
    normalized: dict[str, Any] = {}
    follow_up_events: list[dict] = []

    if not partial or "full_name" in payload:
        full_name = _normalize_text(payload.get("full_name"))
        if not full_name and not partial:
            raise ApiError("full_name is required.", status_code=400)
        if full_name is not None:
            normalized["full_name"] = full_name

    if not partial or "phone_number" in payload:
        phone_number = normalize_phone(payload.get("phone_number"))
        if not phone_number and not partial:
            raise ApiError("phone_number is required.", status_code=400)
        if phone_number is not None and not validate_phone(phone_number):
            raise ApiError("A valid phone_number is required.", status_code=400)
        if phone_number is not None:
            normalized["phone_number"] = phone_number
            normalized["normalized_phone_number"] = phone_number

    if "alternate_phone" in payload:
        alternate_phone = normalize_phone(payload.get("alternate_phone"))
        if alternate_phone and not validate_phone(alternate_phone):
            raise ApiError("alternate_phone must be a valid phone number.", status_code=400)
        normalized["alternate_phone"] = alternate_phone

    if "email_address" in payload:
        email_address = normalize_email(payload.get("email_address"))
        if email_address and not validate_email(email_address):
            raise ApiError("email_address must be a valid email.", status_code=400)
        normalized["email_address"] = email_address
        normalized["normalized_email_address"] = email_address

    for field_name in (
        "date_of_birth",
        "pickup_location",
        "destination_location",
        "notes",
        "occupation",
        "organization_name",
        "position_title",
        "residential_area",
        "work_area",
        "preferred_pickup_location",
        "preferred_dropoff_location",
        "referred_by",
        "relationship_notes",
        "lead_notes",
        "important_notes",
        "company_name",
    ):
        if field_name in payload:
            normalized[field_name] = _normalize_text(payload.get(field_name))

    for selection_key in MASTER_DATA_FIELD_CONFIG:
        _resolve_master_data_selection(
            payload,
            selection_key=selection_key,
            partial=partial,
            normalized=normalized,
        )

    if not partial or "status" in payload:
        normalized["status"] = _validate_status(payload.get("status"))

    assigned_driver_identifier = payload.get("assigned_driver_id") if "assigned_driver_id" in payload else payload.get("preferred_driver_id")
    if "preferred_driver_id" in payload or "assigned_driver_id" in payload:
        preferred_driver = _get_driver_document(assigned_driver_identifier)
        normalized["preferred_driver_id"] = preferred_driver["_id"] if preferred_driver else None

    if not partial or "source" in payload:
        normalized["source"] = _validate_source(payload.get("source"))

    if "is_transport_customer" in payload:
        normalized["is_transport_customer"] = _validate_boolean(payload.get("is_transport_customer"), "is_transport_customer")
    elif not partial:
        normalized["is_transport_customer"] = True

    if "is_business_lead" in payload:
        normalized["is_business_lead"] = _validate_boolean(payload.get("is_business_lead"), "is_business_lead")
    elif not partial:
        normalized["is_business_lead"] = False

    if "lead_value_estimate" in payload:
        normalized["lead_value_estimate"] = _validate_money(payload.get("lead_value_estimate"), "lead_value_estimate")

    if "follow_up_date" in payload:
        normalized["follow_up_date"] = _normalize_date_string(payload.get("follow_up_date"), "follow_up_date")
    elif not partial:
        normalized["follow_up_date"] = None

    if "next_follow_up_date" in payload:
        normalized["next_follow_up_date"] = _normalize_date_string(payload.get("next_follow_up_date"), "next_follow_up_date")
    elif not partial:
        normalized["next_follow_up_date"] = None

    if "follow_up_priority" in payload:
        normalized["follow_up_priority"] = _validate_follow_up_priority(payload.get("follow_up_priority"))
    elif not partial:
        normalized["follow_up_priority"] = "medium"

    follow_up_note = _normalize_text(
        payload.get("follow_up_note")
        or payload.get("follow_up_notes")
        or payload.get("follow_up_completion_note")
    )
    if payload.get("mark_follow_up_completed"):
        next_follow_up_date = normalized.get("next_follow_up_date")
        if "next_follow_up_date" not in payload and "follow_up_date" in payload:
            next_follow_up_date = normalized.get("follow_up_date")
        follow_up_events.append(
            {
                "event_type": "completed",
                "note": follow_up_note,
                "next_follow_up_date": next_follow_up_date,
            }
        )
    elif any(key in payload for key in ("follow_up_date", "next_follow_up_date", "follow_up_priority")):
        follow_up_events.append(
            {
                "event_type": "scheduled",
                "note": follow_up_note,
                "next_follow_up_date": normalized.get("next_follow_up_date"),
            }
        )

    return normalized, follow_up_events


def _find_duplicate_customer(
    *,
    normalized_phone_number: str | None,
    normalized_email_address: str | None,
    exclude_customer_id: ObjectId | None = None,
):
    or_conditions = []
    if normalized_phone_number:
        or_conditions.append({"normalized_phone_number": normalized_phone_number})
    if normalized_email_address:
        or_conditions.append({"normalized_email_address": normalized_email_address})
    if not or_conditions:
        return None, []

    query: dict[str, Any] = {"$or": or_conditions}
    if exclude_customer_id:
        query["_id"] = {"$ne": exclude_customer_id}

    existing = customers_collection().find_one(query)
    if not existing:
        return None, []

    matches = []
    if normalized_phone_number and existing.get("normalized_phone_number") == normalized_phone_number:
        matches.append("phone_number")
    if normalized_email_address and existing.get("normalized_email_address") == normalized_email_address:
        matches.append("email_address")
    return existing, matches


def _customer_duplicate_error_from_exception(error: DuplicateKeyError):
    details = getattr(error, "details", {}) or {}
    index_name = str(details.get("index") or "")
    if "normalized_phone_number" in index_name:
        return ApiError("A customer with this phone number already exists.", status_code=409)
    if "normalized_email_address" in index_name:
        return ApiError("A customer with this email address already exists.", status_code=409)
    if "customer_id" in index_name:
        return ApiError("Customer ID generation conflicted. Please try again.", status_code=409)
    return ApiError("A matching customer already exists.", status_code=409)


def _sanitize_customer_document_for_insert(document: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(document)
    if not sanitized.get("normalized_email_address"):
        sanitized.pop("normalized_email_address", None)
    if not sanitized.get("email_address"):
        sanitized.pop("email_address", None)
    return sanitized


def _raise_duplicate_customer(existing_customer_document: dict, matches: list[str]):
    raise ApiError(
        "Existing customer found.",
        status_code=409,
        errors=[
            {
                "code": "duplicate_customer",
                "matches": matches,
                "existing_customer": _enrich_customer(existing_customer_document),
            }
        ],
    )


def _active_follow_up_date(customer_document: dict):
    return customer_document.get("next_follow_up_date") or customer_document.get("follow_up_date")


def _follow_up_flags(customer_document: dict):
    active_date = _date_from_string(_active_follow_up_date(customer_document))
    today = now_utc().date()
    is_due_today = active_date == today if active_date else False
    is_overdue = active_date < today if active_date else False
    is_high_priority_due = bool(
        active_date
        and active_date <= today
        and (customer_document.get("follow_up_priority") or "medium").lower() == "high"
    )
    if is_overdue:
        status_label = "Follow-up overdue"
    elif is_due_today:
        status_label = "Follow-up due today"
    elif active_date:
        status_label = "Upcoming follow-up"
    else:
        status_label = "No follow-up scheduled"
    return {
        "active_follow_up_date": active_date.isoformat() if active_date else None,
        "is_follow_up_due_today": is_due_today,
        "is_follow_up_overdue": is_overdue,
        "is_high_priority_follow_up": is_high_priority_due,
        "follow_up_status_label": status_label,
    }


def _customer_matches_filters(customer_document: dict, *, filters: dict):
    created_at = _extract_datetime(customer_document.get("created_at"))
    if filters["date_from"] and (not created_at or created_at.date() < filters["date_from"]):
        return False
    if filters["date_to"] and (not created_at or created_at.date() > filters["date_to"]):
        return False
    if filters["creator_role"] and (customer_document.get("created_by_role") or "").lower() != filters["creator_role"]:
        return False
    if filters["driver_id"]:
        driver_id = filters["driver_id"]
        if customer_document.get("preferred_driver_id") != driver_id and customer_document.get("created_by_driver_id") != driver_id:
            return False
    if filters["customer_category_id"] and customer_document.get("customer_category_id") != filters["customer_category_id"]:
        return False
    if filters["source"] and (customer_document.get("source") or "").lower() != filters["source"]:
        return False
    return True


def _creator_display_name(customer_document: dict):
    return customer_document.get("created_by_name") or "Unknown / Legacy Record"


def _customer_analytics_available_filters(customer_documents: list[dict], *, current_role: str):
    creator_roles = sorted(
        {
            role
            for customer in customer_documents
            if (role := (customer.get("created_by_role") or "").lower())
            and (current_role == "owner" or role != "owner")
        }
    )
    driver_ids = {
        customer.get("preferred_driver_id")
        for customer in customer_documents
        if customer.get("preferred_driver_id")
    } | {
        customer.get("created_by_driver_id")
        for customer in customer_documents
        if customer.get("created_by_driver_id")
    }
    drivers = []
    if driver_ids:
        for user in users_collection().find({"_id": {"$in": list(driver_ids)}}).sort("full_name", ASCENDING):
            drivers.append(serialize_user(user))
    category_ids = {customer.get("customer_category_id") for customer in customer_documents if customer.get("customer_category_id")}
    category_documents = []
    if category_ids:
        category_documents = [
            {
                "id": str(item["_id"]),
                "name": item.get("name"),
            }
            for item in get_collection("master_data").find({"_id": {"$in": list(category_ids)}}).sort("name", ASCENDING)
        ]
    return {
        "creator_roles": creator_roles,
        "drivers": drivers,
        "customer_categories": category_documents,
        "sources": [{"value": key, "label": value} for key, value in SOURCE_OPTIONS.items()],
    }


def _customer_booking_stats(customer_document: dict) -> dict:
    customer_id = customer_document.get("_id")
    booking_documents = list(
        bookings_collection().find({"customer_id": customer_id}).sort(
            [("pickup_at", DESCENDING), ("created_at", DESCENDING)]
        )
    )
    now = now_utc()

    upcoming_bookings = [
        booking
        for booking in booking_documents
        if (booking.get("status") or "").lower() in {"scheduled", "acknowledged", "en route", "picked up", "confirmed", "in progress"}
        and (_extract_datetime(booking.get("pickup_at")) or now) >= now
        and not booking.get("is_recurring_template")
    ]
    recurring_templates = [
        booking for booking in booking_documents if booking.get("is_recurring_template")
    ]
    completed_bookings = [
        booking
        for booking in booking_documents
        if (booking.get("status") or "").lower() == "completed"
        and not booking.get("is_recurring_template")
    ]
    missed_bookings = [
        booking
        for booking in booking_documents
        if (booking.get("status") or "").lower() == "missed"
        and not booking.get("is_recurring_template")
    ]

    ride_documents = list(
        rides_collection().find({"customer_id": customer_id}).sort(
            [("end_time", DESCENDING), ("created_at", DESCENDING)]
        )
    )
    completed_rides = [
        ride for ride in ride_documents if (ride.get("status") or "").lower() == "completed"
    ]

    last_ride_date = None
    if completed_rides:
        last_completed_ride = _extract_datetime(completed_rides[0].get("end_time")) or _extract_datetime(completed_rides[0].get("start_time"))
        last_ride_date = last_completed_ride.isoformat() if last_completed_ride else None

    driver_counts = Counter(
        str(ride.get("driver_id"))
        for ride in completed_rides
        if ride.get("driver_id")
    )
    preferred_driver_id = customer_document.get("preferred_driver_id")
    if not preferred_driver_id and driver_counts:
        preferred_driver_id = ObjectId(driver_counts.most_common(1)[0][0])
    preferred_driver = users_collection().find_one({"_id": preferred_driver_id}) if preferred_driver_id else None

    ride_frequency = "New"
    rides_completed = len(completed_rides)
    if rides_completed >= 16:
        ride_frequency = "Daily"
    elif rides_completed >= 8:
        ride_frequency = "Weekly"
    elif rides_completed >= 3:
        ride_frequency = "Monthly"

    return {
        "total_rides": rides_completed,
        "total_bookings": len([booking for booking in booking_documents if not booking.get("is_recurring_template")]),
        "last_ride_date": last_ride_date,
        "upcoming_bookings_count": len(upcoming_bookings),
        "completed_bookings_count": len(completed_bookings),
        "missed_bookings_count": len(missed_bookings),
        "preferred_driver": serialize_user(preferred_driver) if preferred_driver else None,
        "ride_frequency": ride_frequency,
        "ride_history": [serialize_ride(ride) for ride in completed_rides[:10]],
        "upcoming_bookings": [serialize_booking(booking) for booking in upcoming_bookings[:10]],
        "completed_bookings": [serialize_booking(booking) for booking in completed_bookings[:10]],
        "missed_bookings": [serialize_booking(booking) for booking in missed_bookings[:10]],
        "recurring_schedule": [serialize_booking(booking) for booking in recurring_templates[:10]],
    }


def _enrich_customer(customer_document: dict) -> dict:
    customer = _serialize_customer_summary(customer_document)
    stats = _customer_booking_stats(customer_document)
    follow_up = _follow_up_flags(customer_document)
    customer.update(stats)
    customer.update(follow_up)
    customer["profile_summary"] = {
        "full_name": customer.get("full_name"),
        "phone_number": customer.get("phone_number"),
        "occupation": customer.get("occupation"),
        "position": customer.get("position_title"),
        "organization": customer.get("organization_name") or customer.get("company_name"),
        "category": customer.get("customer_category"),
        "relationship_category": customer.get("relationship_category"),
        "opportunity_level": customer.get("opportunity_level"),
        "network_value": customer.get("network_value"),
        "lead_status": customer.get("lead_status"),
        "preferred_driver": stats.get("preferred_driver"),
        "total_rides": stats.get("total_rides"),
        "last_ride_date": stats.get("last_ride_date"),
        "upcoming_bookings": stats.get("upcoming_bookings_count"),
        "completed_bookings": stats.get("completed_bookings_count"),
        "missed_bookings": stats.get("missed_bookings_count"),
        "follow_up_date": follow_up.get("active_follow_up_date"),
    }
    return customer


def list_customer_options(current_user_id: str, current_role: str) -> dict:
    cache_key = build_cache_key("customer_options", current_user_id=current_user_id, current_role=current_role)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    request_started_at = perf_counter()
    driver_filter = {"role": "driver", "status": "active"}
    if current_role == "driver":
        driver_filter["_id"] = _to_object_id(current_user_id, "current_user_id")

    query_started_at = perf_counter()
    drivers = list(
        users_collection().find(
            driver_filter,
            {"full_name": 1, "email": 1, "phone": 1, "role": 1, "status": 1, "created_at": 1},
        ).sort("full_name", ASCENDING)
    )
    log_db_duration("customers.options.drivers", query_started_at)

    result = {
        "drivers": [serialize_user(driver) for driver in drivers],
        "customer_categories": get_active_master_data_values("customer_categories"),
        "customer_category_items": get_active_master_data_items("customer_categories"),
        "customer_sources": get_active_master_data_values("customer_sources"),
        "customer_source_items": get_active_master_data_items("customer_sources"),
        "company_industries": get_active_master_data_values("industries"),
        "industry_items": get_active_master_data_items("industries"),
        "organization_types": get_active_master_data_values("organization_types"),
        "organization_type_items": get_active_master_data_items("organization_types"),
        "relationship_category_items": get_active_master_data_items("relationship_categories"),
        "opportunity_level_items": get_active_master_data_items("opportunity_levels"),
        "network_value_items": get_active_master_data_items("network_values"),
        "lead_status_items": get_active_master_data_items("lead_statuses"),
        "potential_service_items": get_active_master_data_items("potential_services"),
        "follow_up_priorities": sorted(FOLLOW_UP_PRIORITIES),
        "statuses": sorted(CUSTOMER_STATUSES),
        "source_options": [{"value": key, "label": value} for key, value in SOURCE_OPTIONS.items()],
        "creator_roles": sorted(CREATOR_ROLES),
    }
    current_app.logger.info(
        "[Flux Customers] options role=%s duration_ms=%.2f",
        current_role,
        (perf_counter() - request_started_at) * 1000,
    )
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    if total_duration_ms > 2000:
        current_app.logger.warning(
            "SLOW API WARNING endpoint=/api/customers/options role=%s duration_ms=%.2f",
            current_role,
            total_duration_ms,
        )
    return set_ttl_cached(cache_key, result, ttl_seconds=30)


def list_customers(current_user_id: str, current_role: str) -> list[dict]:
    customers = customers_collection().find(_customer_scope_query(current_user_id, current_role)).sort([("created_at", DESCENDING)])
    return [_enrich_customer(customer_document) for customer_document in customers]


def get_customer_by_id(customer_id: str, current_user_id: str, current_role: str) -> dict:
    customer_document = _get_customer_document(customer_id)
    _assert_customer_access(
        customer_document,
        current_user_id=current_user_id,
        current_role=current_role,
    )
    return _enrich_customer(customer_document)


def get_customer_summary(current_user_id: str, current_role: str, filters: dict | None = None) -> dict:
    normalized_filters = _normalize_customer_filters(filters)
    cache_key = build_cache_key(
        "customer_summary",
        current_user_id=current_user_id,
        current_role=current_role,
        **{
            "date_from": normalized_filters["date_from"].isoformat() if normalized_filters["date_from"] else "",
            "date_to": normalized_filters["date_to"].isoformat() if normalized_filters["date_to"] else "",
            "creator_role": normalized_filters["creator_role"] or "",
            "driver_id": str(normalized_filters["driver_id"]) if normalized_filters["driver_id"] else "",
            "customer_category_id": str(normalized_filters["customer_category_id"]) if normalized_filters["customer_category_id"] else "",
            "source": normalized_filters["source"] or "",
        },
    )
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    scoped_customer_documents = list(customers_collection().find(_customer_scope_query(current_user_id, current_role)))
    customer_documents = [
        customer
        for customer in scoped_customer_documents
        if _customer_matches_filters(customer, filters=normalized_filters)
    ]
    today = now_utc().date()

    total_business_leads = len([customer for customer in customer_documents if customer.get("is_business_lead")])
    total_strategic_contacts = len(
        [customer for customer in customer_documents if (customer.get("opportunity_level") or "").lower() == "strategic"]
    )
    total_investors = len(
        [customer for customer in customer_documents if (customer.get("relationship_category") or "").lower() == "investor"]
    )
    total_gatekeepers = len(
        [
            customer
            for customer in customer_documents
            if (customer.get("relationship_category") or "").lower() == "gatekeeper"
            or (customer.get("network_value") or "").lower() == "industry gatekeeper"
        ]
    )

    follow_ups_due_today = 0
    follow_ups_overdue = 0
    high_priority_due = 0
    due_customers: list[dict] = []

    for customer_document in customer_documents:
        follow_up = _follow_up_flags(customer_document)
        active_follow_up_date = follow_up.get("active_follow_up_date")
        if follow_up["is_follow_up_due_today"]:
            follow_ups_due_today += 1
        if follow_up["is_follow_up_overdue"]:
            follow_ups_overdue += 1
        if follow_up["is_high_priority_follow_up"]:
            high_priority_due += 1
        if active_follow_up_date and (
            follow_up["is_follow_up_due_today"]
            or follow_up["is_follow_up_overdue"]
            or follow_up["is_high_priority_follow_up"]
        ):
            enriched = _enrich_customer(customer_document)
            due_customers.append(
                {
                    "id": enriched["id"],
                    "full_name": enriched["full_name"],
                    "phone_number": enriched["phone_number"],
                    "follow_up_date": active_follow_up_date,
                    "follow_up_priority": enriched.get("follow_up_priority"),
                    "follow_up_status_label": enriched.get("follow_up_status_label"),
                    "lead_status": enriched.get("lead_status"),
                    "relationship_category": enriched.get("relationship_category"),
                }
            )

    converted_leads = len(
        [customer for customer in customer_documents if (customer.get("lead_status") or "").lower() == "converted"]
    )
    lead_conversion_rate = round((converted_leads / total_business_leads) * 100, 1) if total_business_leads else 0.0

    seven_days_ago = today - timedelta(days=6)
    month_start = today.replace(day=1)
    trend_map = {
        (seven_days_ago + timedelta(days=offset)).isoformat(): 0
        for offset in range(7)
    }
    customers_by_creator_counter: Counter[str] = Counter()
    customers_by_driver_counter: Counter[str] = Counter()
    customers_by_source_counter: Counter[str] = Counter()
    creator_lookup: dict[str, dict] = {}
    driver_lookup: dict[str, dict] = {}
    new_customers_this_week = 0
    new_customers_this_month = 0
    for customer_document in customer_documents:
        created_at = _extract_datetime(customer_document.get("created_at"))
        if not created_at:
            continue
        day_key = created_at.date().isoformat()
        if day_key in trend_map:
            trend_map[day_key] += 1
        if created_at.date() >= seven_days_ago:
            new_customers_this_week += 1
        if created_at.date() >= month_start:
            new_customers_this_month += 1
        creator_name = _creator_display_name(customer_document)
        creator_role = (customer_document.get("created_by_role") or "legacy").lower()
        if current_role == "owner" or creator_role != "owner":
            creator_key = f"{creator_role}:{creator_name}"
            customers_by_creator_counter[creator_key] += 1
            creator_lookup[creator_key] = {
                "name": creator_name,
                "role": creator_role,
                "user_id": str(customer_document.get("created_by_user_id") or customer_document.get("created_by"))
                if customer_document.get("created_by_user_id") or customer_document.get("created_by")
                else None,
            }
        driver_object_id = customer_document.get("preferred_driver_id") or customer_document.get("created_by_driver_id")
        if driver_object_id:
            driver_key = str(driver_object_id)
            customers_by_driver_counter[driver_key] += 1
        source_key = (customer_document.get("source") or "other").lower()
        customers_by_source_counter[source_key] += 1

    if customers_by_driver_counter:
        for driver in users_collection().find({"_id": {"$in": [ObjectId(item) for item in customers_by_driver_counter.keys() if ObjectId.is_valid(item)]}}):
            driver_lookup[str(driver["_id"])] = serialize_user(driver)

    due_customers.sort(key=lambda item: (item["follow_up_date"], item["full_name"]))

    result = {
        "total_customers": len(customer_documents),
        "new_customers_this_week": new_customers_this_week,
        "new_customers_this_month": new_customers_this_month,
        "total_business_leads": total_business_leads,
        "total_strategic_contacts": total_strategic_contacts,
        "total_investors": total_investors,
        "total_gatekeepers": total_gatekeepers,
        "follow_ups_due_today": follow_ups_due_today,
        "follow_ups_overdue": follow_ups_overdue,
        "high_priority_follow_ups_due": high_priority_due,
        "lead_conversion_rate": lead_conversion_rate,
        "follow_up_due_customers": due_customers[:10],
        "customer_growth_trend": [
            {"label": day_key, "value": value}
            for day_key, value in trend_map.items()
        ],
        "customers_by_creator": [
            {
                "creator_name": creator_lookup[key]["name"],
                "creator_role": creator_lookup[key]["role"],
                "creator_user_id": creator_lookup[key]["user_id"],
                "count": count,
            }
            for key, count in customers_by_creator_counter.most_common()
        ],
        "customers_by_driver": [
            {
                "driver_id": driver_id,
                "driver_name": (driver_lookup.get(driver_id) or {}).get("full_name") or "Unknown Driver",
                "count": count,
            }
            for driver_id, count in customers_by_driver_counter.most_common()
        ],
        "customers_by_source": [
            {
                "source": source,
                "label": SOURCE_OPTIONS.get(source, "Other"),
                "count": count,
            }
            for source, count in customers_by_source_counter.most_common()
        ],
        "top_customer_generators": [
            {
                "creator_name": creator_lookup[key]["name"],
                "creator_role": creator_lookup[key]["role"],
                "creator_user_id": creator_lookup[key]["user_id"],
                "count": count,
            }
            for key, count in customers_by_creator_counter.most_common(5)
        ],
        "available_filters": _customer_analytics_available_filters(scoped_customer_documents, current_role=current_role),
        "applied_filters": {
            "date_from": normalized_filters["date_from"].isoformat() if normalized_filters["date_from"] else None,
            "date_to": normalized_filters["date_to"].isoformat() if normalized_filters["date_to"] else None,
            "creator_role": normalized_filters["creator_role"],
            "driver_id": str(normalized_filters["driver_id"]) if normalized_filters["driver_id"] else None,
            "customer_category_id": str(normalized_filters["customer_category_id"]) if normalized_filters["customer_category_id"] else None,
            "source": normalized_filters["source"],
        },
    }
    return set_ttl_cached(cache_key, result, ttl_seconds=15)


def create_customer(payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to create customers.", status_code=403)

    try:
        creator_user = _get_user_document(current_user_id)
        normalized, follow_up_events = _normalized_customer_payload(payload, partial=False)
        if current_role == "driver":
            normalized["preferred_driver_id"] = creator_user["_id"]
        elif "preferred_driver_id" not in normalized:
            normalized["preferred_driver_id"] = None
        existing_customer, matches = _find_duplicate_customer(
            normalized_phone_number=normalized.get("normalized_phone_number"),
            normalized_email_address=normalized.get("normalized_email_address"),
        )
        if existing_customer:
            _raise_duplicate_customer(existing_customer, matches)

        timestamp = now_utc()
        customer_document = _sanitize_customer_document_for_insert({
            "customer_id": _build_customer_id(),
            **normalized,
            "created_by": _to_object_id(current_user_id, "current_user_id"),
            "created_by_user_id": creator_user["_id"],
            "created_by_name": creator_user.get("full_name"),
            "created_by_role": creator_user.get("role"),
            "created_by_driver_id": creator_user["_id"] if creator_user.get("role") == "driver" else None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "follow_up_completed_at": None,
            "follow_up_history": [],
            "audit_events": [
                _serialize_audit_event(
                    action="created",
                    user_id=current_user_id,
                    changes=sorted(normalized.keys()),
                )
            ],
        })
        if follow_up_events:
            customer_document["follow_up_history"] = [
                _serialize_follow_up_event(
                    action=event["event_type"],
                    user_id=current_user_id,
                    follow_up_date=normalized.get("follow_up_date"),
                    next_follow_up_date=event.get("next_follow_up_date"),
                    priority=normalized.get("follow_up_priority"),
                    note=event.get("note"),
                )
                for event in follow_up_events
            ]

        result = customers_collection().insert_one(customer_document)
    except ApiError as error:
        current_app.logger.warning(
            "[Flux Customers] Validation failed during create customer user_id=%s role=%s message=%s payload_keys=%s",
            current_user_id,
            current_role,
            error.message,
            sorted(payload.keys()),
        )
        raise
    except DuplicateKeyError as error:
        current_app.logger.exception(
            "[Flux Customers] Duplicate key during create customer user_id=%s payload_keys=%s",
            current_user_id,
            sorted(payload.keys()),
        )
        raise _customer_duplicate_error_from_exception(error) from error
    customer_document["_id"] = result.inserted_id
    return _enrich_customer(customer_document)


def update_customer(customer_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to update customers.", status_code=403)

    customer_document = _get_customer_document(customer_id)
    _assert_customer_access(
        customer_document,
        current_user_id=current_user_id,
        current_role=current_role,
    )

    normalized, follow_up_events = _normalized_customer_payload(payload, partial=True)
    if current_role == "driver":
        normalized["preferred_driver_id"] = _to_object_id(current_user_id, "current_user_id")
    if not normalized and not follow_up_events:
        raise ApiError("No customer fields provided for update.", status_code=400)

    existing_customer, matches = _find_duplicate_customer(
        normalized_phone_number=normalized.get("normalized_phone_number", customer_document.get("normalized_phone_number")),
        normalized_email_address=normalized.get("normalized_email_address", customer_document.get("normalized_email_address")),
        exclude_customer_id=customer_document["_id"],
    )
    if existing_customer:
        _raise_duplicate_customer(existing_customer, matches)

    follow_up_history_entries = []
    mark_follow_up_completed = bool(payload.get("mark_follow_up_completed"))
    if mark_follow_up_completed:
        next_follow_up_date = normalized.get("next_follow_up_date")
        current_follow_up_date = normalized.get("follow_up_date", customer_document.get("follow_up_date"))
        promoted_follow_up_date = next_follow_up_date or current_follow_up_date
        normalized["follow_up_date"] = promoted_follow_up_date if next_follow_up_date else None
        normalized["next_follow_up_date"] = None
        normalized["follow_up_completed_at"] = now_utc()
        follow_up_history_entries.append(
            _serialize_follow_up_event(
                action="completed",
                user_id=current_user_id,
                follow_up_date=current_follow_up_date,
                next_follow_up_date=next_follow_up_date,
                priority=normalized.get("follow_up_priority", customer_document.get("follow_up_priority")),
                note=_normalize_text(
                    payload.get("follow_up_completion_note")
                    or payload.get("follow_up_note")
                    or payload.get("follow_up_notes")
                ),
            )
        )
    elif follow_up_events:
        follow_up_history_entries.extend(
            [
                _serialize_follow_up_event(
                    action=event["event_type"],
                    user_id=current_user_id,
                    follow_up_date=normalized.get("follow_up_date", customer_document.get("follow_up_date")),
                    next_follow_up_date=event.get("next_follow_up_date"),
                    priority=normalized.get("follow_up_priority", customer_document.get("follow_up_priority")),
                    note=event.get("note"),
                )
                for event in follow_up_events
            ]
        )

    timestamp = now_utc()
    audit_note = "Follow-up completed" if mark_follow_up_completed else None
    audit_event = _serialize_audit_event(
        action="updated",
        user_id=current_user_id,
        changes=sorted(normalized.keys()) + (["follow_up_history"] if follow_up_history_entries else []),
        note=audit_note,
    )
    update_fields = {
        **normalized,
        "updated_at": timestamp,
    }

    unset_fields: dict[str, str] = {}
    if "email_address" in update_fields and not update_fields.get("email_address"):
        update_fields.pop("email_address", None)
        unset_fields["email_address"] = ""
    if "normalized_email_address" in update_fields and not update_fields.get("normalized_email_address"):
        update_fields.pop("normalized_email_address", None)
        unset_fields["normalized_email_address"] = ""

    update_operation: dict[str, Any] = {
        "$set": update_fields,
        "$push": {"audit_events": audit_event},
    }
    if unset_fields:
        update_operation["$unset"] = unset_fields
    if follow_up_history_entries:
        update_operation["$push"]["follow_up_history"] = {"$each": follow_up_history_entries}

    try:
        customers_collection().update_one(
            {"_id": customer_document["_id"]},
            update_operation,
        )
    except DuplicateKeyError as error:
        current_app.logger.exception(
            "[Flux Customers] Duplicate key during update customer customer_id=%s user_id=%s payload_keys=%s",
            customer_id,
            current_user_id,
            sorted(payload.keys()),
        )
        raise _customer_duplicate_error_from_exception(error) from error

    customer_document.update(update_fields)
    if unset_fields:
        for field_name in unset_fields:
            customer_document.pop(field_name, None)
    customer_document.setdefault("audit_events", []).append(audit_event)
    if follow_up_history_entries:
        customer_document.setdefault("follow_up_history", []).extend(follow_up_history_entries)
    return _enrich_customer(customer_document)
