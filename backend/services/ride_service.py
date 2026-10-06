from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite
from time import perf_counter
from typing import Any
import re

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from flask import current_app

from extensions import get_collection
from models.booking import serialize_booking
from models.customer import serialize_customer
from models.ride import serialize_ride
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.master_data_service import get_active_master_data_items, resolve_master_data_item
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError
from utils.performance import build_cache_key, get_ttl_cached, invalidate_ttl_cache, log_db_duration, set_ttl_cached


TRIP_STATUSES = {
    "Logged",
    "Scheduled",
    "Completed",
    "Cancelled",
}

PAYMENT_METHODS = {"Cash", "MoMo"}

ACTIVE_BOOKING_STATUSES = ["Scheduled", "Acknowledged", "En Route", "Picked Up", "Confirmed"]

RIDE_LIST_PROJECTION = {
    "trip_id": 1,
    "ride_id": 1,
    "customer_id": 1,
    "customer_name_snapshot": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "trip_source_id": 1,
    "trip_purpose_id": 1,
    "trip_source": 1,
    "trip_purpose": 1,
    "trip_date": 1,
    "start_time": 1,
    "end_time": 1,
    "pickup_area": 1,
    "destination_area": 1,
    "odometer_start": 1,
    "odometer_end": 1,
    "notes": 1,
    "status": 1,
    "created_by": 1,
    "created_at": 1,
    "updated_at": 1,
    "source_booking_id": 1,
    "actual_fare": 1,
    "payment_method": 1,
    "platform_fee": 1,
    "net_earnings": 1,
}

RIDE_SUMMARY_PROJECTION = {
    "trip_date": 1,
    "status": 1,
    "vehicle_id": 1,
    "trip_source": 1,
    "trip_purpose": 1,
    "driver_id": 1,
    "customer_id": 1,
    "actual_fare": 1,
    "payment_method": 1,
    "platform_fee": 1,
    "net_earnings": 1,
}


def now_utc():
    return datetime.now(timezone.utc)


def _as_utc_datetime(value: Any):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def rides_collection():
    return get_collection("rides")


def customers_collection():
    return get_collection("customers")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def bookings_collection():
    return get_collection("bookings")


def assignments_collection():
    return get_collection("assignments")


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def _driver_vehicle_ids(current_user_id: str) -> set[ObjectId]:
    driver_id = _to_object_id(current_user_id, "current_user_id")
    vehicle_ids = {
        item["vehicle_id"]
        for item in assignments_collection().find(
            {"driver_id": driver_id, "status": "active"},
            {"vehicle_id": 1},
        )
        if isinstance(item.get("vehicle_id"), ObjectId)
    }
    vehicle_ids.update(
        item["vehicle_id"]
        for item in vehicle_movements_collection().find(
            {
                "status": {"$in": ["approved", "checked_out", "in_progress"]},
                "$or": [{"driver_id": driver_id}, {"movement_custodian_id": driver_id}],
            },
            {"vehicle_id": 1},
        )
        if isinstance(item.get("vehicle_id"), ObjectId)
    )
    return vehicle_ids


def _assert_driver_vehicle_access(current_user_id: str, vehicle_id: ObjectId):
    if vehicle_id not in _driver_vehicle_ids(current_user_id):
        raise ApiError(
            "Drivers can only log trips for an assigned or active movement-linked vehicle.",
            status_code=403,
        )


def _index_keys_match(existing_index: dict, keys: list[tuple[str, int]]) -> bool:
    return list(existing_index.get("key", {}).items()) == keys


def _ensure_index_if_missing(keys: list[tuple[str, int]], **options):
    collection = rides_collection()
    for existing_index in collection.list_indexes():
        if _index_keys_match(existing_index, keys):
            return existing_index.get("name")
    return collection.create_index(keys, **options)


def ensure_ride_indexes():
    _ensure_index_if_missing([("trip_id", ASCENDING)], unique=True, sparse=True)
    _ensure_index_if_missing([("ride_id", ASCENDING)], unique=True)
    _ensure_index_if_missing([("customer_id", ASCENDING)])
    _ensure_index_if_missing([("driver_id", ASCENDING)])
    _ensure_index_if_missing([("vehicle_id", ASCENDING)])
    _ensure_index_if_missing([("trip_date", DESCENDING)])
    _ensure_index_if_missing([("status", ASCENDING)])
    _ensure_index_if_missing([("created_at", DESCENDING)])
    _ensure_index_if_missing([("driver_id", ASCENDING), ("created_at", DESCENDING)])
    _ensure_index_if_missing([("vehicle_id", ASCENDING), ("created_at", DESCENDING)])
    _ensure_index_if_missing([("vehicle_id", ASCENDING), ("trip_date", DESCENDING), ("created_at", DESCENDING)])
    _ensure_index_if_missing([("status", ASCENDING), ("created_at", DESCENDING)])
    _ensure_index_if_missing([("status", ASCENDING), ("vehicle_id", ASCENDING), ("created_at", DESCENDING)])
    _ensure_index_if_missing([("status", ASCENDING), ("driver_id", ASCENDING), ("created_at", DESCENDING)])
    _ensure_index_if_missing([("driver_id", ASCENDING), ("status", ASCENDING), ("trip_date", DESCENDING)])
    _ensure_index_if_missing([("trip_source_id", ASCENDING)])
    _ensure_index_if_missing([("trip_purpose_id", ASCENDING)])
    _ensure_index_if_missing([("source_booking_id", ASCENDING)])
    _ensure_index_if_missing([("created_by", ASCENDING)])


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


def _merge_queries(*queries: dict | None):
    normalized = [query for query in queries if query]
    if not normalized:
        return {}
    if len(normalized) == 1:
        return normalized[0]
    return {"$and": normalized}


def _parse_trip_date(value, field_name: str, *, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    try:
        return datetime.fromisoformat(str(value).strip()).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise ApiError(f"{field_name} must be a valid YYYY-MM-DD date.", status_code=400) from error


def _parse_time_value(value, field_name: str, *, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None

    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed.strftime("%H:%M")
    except ValueError:
        pass

    for pattern in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern).strftime("%H:%M")
        except ValueError:
            continue
    raise ApiError(f"{field_name} must be a valid time.", status_code=400)


def _validate_number(value, field_name: str, *, required: bool = False, non_negative: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    parsed = round(float(value), 2)
    if not isfinite(parsed):
        raise ApiError(f"{field_name} must be a finite number.", status_code=400)
    if non_negative and parsed < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return parsed


def _validate_payment_method(value):
    normalized = _normalize_text(value)
    if normalized is None:
        return None
    match = next((item for item in PAYMENT_METHODS if item.lower() == normalized.lower()), None)
    if match is None:
        raise ApiError("payment_method must be one of: Cash, MoMo.", status_code=400)
    return match


def _apply_earnings_values(normalized: dict, existing: dict | None = None):
    existing = existing or {}
    amount = normalized.get("actual_fare", existing.get("actual_fare"))
    fee = normalized.get("platform_fee", existing.get("platform_fee"))
    if amount is None:
        if fee not in (None, 0, 0.0):
            raise ApiError("platform_fee requires an amount charged.", status_code=400)
        if "actual_fare" in normalized or "platform_fee" in normalized:
            normalized["platform_fee"] = None
            normalized["net_earnings"] = None
        return
    fee = round(float(fee or 0), 2)
    if fee > amount:
        raise ApiError("platform_fee cannot exceed amount charged.", status_code=400)
    normalized["platform_fee"] = fee
    normalized["net_earnings"] = round(amount - fee, 2)


def _validate_status(value: str | None):
    normalized = _normalize_text(value) or "Logged"
    if normalized not in TRIP_STATUSES:
        raise ApiError("Invalid trip status.", status_code=400)
    return normalized


def _build_trip_id():
    sequence = rides_collection().count_documents({}) + 1
    return f"TRP-{sequence:05d}"


def _serialize_audit_event(*, action: str, user_id: str, changes: list[str], note: str | None = None):
    return {
        "action": action,
        "at": now_utc(),
        "by": _to_object_id(user_id, "user_id"),
        "changes": changes,
        "note": note,
    }


def _get_customer_document(customer_id: str | None):
    if customer_id in (None, ""):
        return None
    customer = customers_collection().find_one({"_id": _to_object_id(customer_id, "customer_id")})
    if not customer:
        raise ApiError("Customer not found.", status_code=404)
    return customer


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


def _get_booking_document(booking_id: str | None):
    if booking_id in (None, ""):
        return None
    booking = bookings_collection().find_one({"_id": _to_object_id(booking_id, "booking_id")})
    if not booking:
        raise ApiError("Booking not found.", status_code=404)
    return booking


def _assert_customer_access(customer_document: dict | None, *, current_user_id: str, current_role: str):
    if customer_document is None or current_role in {"owner", "admin"}:
        return
    if current_role != "driver" or str(customer_document.get("created_by")) != current_user_id:
        raise ApiError("You do not have permission to use this customer.", status_code=403)


def _assert_ride_access(ride_document: dict, *, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return
    driver_id = str(ride_document.get("driver_id")) if ride_document.get("driver_id") else None
    created_by = str(ride_document.get("created_by")) if ride_document.get("created_by") else None
    if current_role != "driver" or current_user_id not in {driver_id, created_by}:
        raise ApiError("You do not have permission to access this trip log.", status_code=403)


def _enrich_ride(ride_document: dict, *, include_earnings: bool = False):
    ride = serialize_ride(ride_document, include_earnings=include_earnings)
    customer = customers_collection().find_one({"_id": ride_document.get("customer_id")})
    driver = users_collection().find_one({"_id": ride_document.get("driver_id")})
    vehicle = vehicles_collection().find_one({"_id": ride_document.get("vehicle_id")})
    booking = bookings_collection().find_one({"_id": ride_document.get("source_booking_id")})
    trip_source_document = None
    if ride_document.get("trip_source_id"):
        trip_source_document = resolve_master_data_item(
            "ride_sources",
            ride_document.get("trip_source_id"),
            active_only=False,
        )
    trip_purpose_document = None
    if ride_document.get("trip_purpose_id"):
        trip_purpose_document = resolve_master_data_item(
            "ride_purposes",
            ride_document.get("trip_purpose_id"),
            active_only=False,
        )

    ride["customer"] = serialize_customer(customer) if customer else None
    ride["driver"] = serialize_user(driver) if driver else None
    ride["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
    ride["source_booking"] = serialize_booking(booking) if booking else None
    ride["trip_source_item"] = {
        "id": str(trip_source_document.get("_id")),
        "name": trip_source_document.get("name"),
        "active": bool(trip_source_document.get("active")),
    } if trip_source_document else None
    ride["trip_purpose_item"] = {
        "id": str(trip_purpose_document.get("_id")),
        "name": trip_purpose_document.get("name"),
        "active": bool(trip_purpose_document.get("active")),
    } if trip_purpose_document else None
    return ride


def _serialize_ride_option_customer(customer_document: dict) -> dict:
    return {
        "id": str(customer_document.get("_id")),
        "full_name": customer_document.get("full_name"),
        "phone_number": customer_document.get("phone_number"),
    }


def _serialize_ride_option_driver(user_document: dict) -> dict:
    return {
        "id": str(user_document.get("_id")),
        "full_name": user_document.get("full_name"),
        "role": "driver",
        "status": user_document.get("status"),
    }


def _serialize_ride_option_vehicle(vehicle_document: dict) -> dict:
    registration_number = vehicle_document.get("registration_number")
    vehicle_name = " ".join(
        part for part in [
            vehicle_document.get("make"),
            vehicle_document.get("model"),
            vehicle_document.get("vehicle_type"),
        ] if part
    ) or registration_number
    return {
        "id": str(vehicle_document.get("_id")),
        "registration_number": registration_number,
        "plate_number": registration_number,
        "vehicle_name": vehicle_name,
        "status": vehicle_document.get("status"),
    }


def _serialize_ride_option_booking(booking_document: dict) -> dict:
    pickup_at = booking_document.get("pickup_at")
    return {
        "id": str(booking_document.get("_id")),
        "booking_id": booking_document.get("booking_id"),
        "customer_id": str(booking_document.get("customer_id")) if booking_document.get("customer_id") else None,
        "driver_id": str(booking_document.get("driver_id")) if booking_document.get("driver_id") else None,
        "vehicle_id": str(booking_document.get("vehicle_id")) if booking_document.get("vehicle_id") else None,
        "booking_type": booking_document.get("booking_type"),
        "pickup_location": booking_document.get("pickup_location"),
        "destination": booking_document.get("destination"),
        "pickup_date": booking_document.get("pickup_date"),
        "pickup_time": booking_document.get("pickup_time"),
        "pickup_at": pickup_at.isoformat() if pickup_at else None,
        "status": booking_document.get("status"),
        "expected_fare": booking_document.get("expected_fare"),
    }


def _serialize_ride_list_customer(customer_document: dict | None) -> dict | None:
    if not customer_document:
        return None
    return {
        "id": str(customer_document.get("_id")),
        "full_name": customer_document.get("full_name"),
        "phone_number": customer_document.get("phone_number"),
    }


def _serialize_ride_list_driver(user_document: dict | None) -> dict | None:
    if not user_document:
        return None
    return {
        "id": str(user_document.get("_id")),
        "full_name": user_document.get("full_name"),
        "role": str(user_document.get("role")).strip().lower() if user_document.get("role") else None,
        "status": user_document.get("status"),
    }


def _serialize_ride_list_vehicle(vehicle_document: dict | None) -> dict | None:
    if not vehicle_document:
        return None
    return {
        "id": str(vehicle_document.get("_id")),
        "registration_number": vehicle_document.get("registration_number"),
        "vehicle_type": vehicle_document.get("vehicle_type"),
        "make": vehicle_document.get("make"),
        "model": vehicle_document.get("model"),
        "status": vehicle_document.get("status"),
    }


def _serialize_ride_list_booking(booking_document: dict | None) -> dict | None:
    if not booking_document:
        return None
    return _serialize_ride_option_booking(booking_document)


def _collection_freshness_token(collection, query: dict | None = None) -> str:
    scoped_query = query or {}
    latest_document = collection.find_one(
        scoped_query,
        {"updated_at": 1, "created_at": 1},
        sort=[("updated_at", DESCENDING), ("created_at", DESCENDING)],
    )
    latest_marker = None
    if latest_document:
        latest_value = latest_document.get("updated_at") or latest_document.get("created_at")
        latest_marker = latest_value.isoformat() if isinstance(latest_value, datetime) else str(latest_value)
    count = collection.count_documents(scoped_query)
    return f"{count}:{latest_marker or 'none'}"


def _cached_collection_freshness_token(cache_namespace: str, collection, query: dict | None = None) -> str:
    cache_key = build_cache_key("ride_options_freshness", scope=cache_namespace, query=str(query or {}))
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    return set_ttl_cached(cache_key, _collection_freshness_token(collection, query), ttl_seconds=5)


def _log_slow_endpoint(endpoint: str, *, role: str, duration_ms: float, query_metrics: list[dict]):
    if duration_ms <= 1000:
        return
    largest_query = max(query_metrics, key=lambda item: item.get("duration_ms", 0), default=None)
    current_app.logger.warning(
        "SLOW API WARNING endpoint=%s role=%s duration_ms=%.2f largest_query=%s query_duration_ms=%s collection=%s",
        endpoint,
        role,
        duration_ms,
        (largest_query or {}).get("label"),
        (largest_query or {}).get("duration_ms"),
        (largest_query or {}).get("collection"),
    )


def _load_ride_relationship_maps(ride_documents: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    driver_ids = {
        ride_document.get("driver_id")
        for ride_document in ride_documents
        if isinstance(ride_document.get("driver_id"), ObjectId)
    }
    vehicle_ids = {
        ride_document.get("vehicle_id")
        for ride_document in ride_documents
        if isinstance(ride_document.get("vehicle_id"), ObjectId)
    }
    driver_map = {
        str(user_document["_id"]): user_document
        for user_document in users_collection().find(
            {"_id": {"$in": list(driver_ids)}},
            {"full_name": 1, "role": 1, "status": 1},
        )
    } if driver_ids else {}
    vehicle_map = {
        str(vehicle_document["_id"]): vehicle_document
        for vehicle_document in vehicles_collection().find(
            {"_id": {"$in": list(vehicle_ids)}},
            {"registration_number": 1, "vehicle_type": 1, "make": 1, "model": 1, "status": 1},
        )
    } if vehicle_ids else {}
    return driver_map, vehicle_map


def _enrich_ride_list_item(
    ride_document: dict,
    *,
    driver_map: dict[str, dict],
    vehicle_map: dict[str, dict],
    include_earnings: bool = False,
) -> dict:
    ride = serialize_ride(ride_document, include_earnings=include_earnings)
    driver = driver_map.get(str(ride_document.get("driver_id"))) if ride_document.get("driver_id") else None
    vehicle = vehicle_map.get(str(ride_document.get("vehicle_id"))) if ride_document.get("vehicle_id") else None
    ride["customer"] = {
        "id": str(ride_document.get("customer_id")),
        "full_name": ride_document.get("customer_name_snapshot"),
        "phone_number": None,
    } if ride_document.get("customer_id") and ride_document.get("customer_name_snapshot") else None
    ride["driver"] = _serialize_ride_list_driver(driver)
    ride["vehicle"] = _serialize_ride_list_vehicle(vehicle)
    ride["source_booking"] = None
    ride["trip_source_item"] = (
        {"id": str(ride_document.get("trip_source_id")), "name": ride_document.get("trip_source"), "active": True}
        if ride_document.get("trip_source_id") or ride_document.get("trip_source")
        else None
    )
    ride["trip_purpose_item"] = (
        {"id": str(ride_document.get("trip_purpose_id")), "name": ride_document.get("trip_purpose"), "active": True}
        if ride_document.get("trip_purpose_id") or ride_document.get("trip_purpose")
        else None
    )
    return ride


def _normalize_page_limit(page: int | None, limit: int | None) -> tuple[int, int]:
    normalized_page = max(int(page or 1), 1)
    normalized_limit = max(1, min(int(limit or 20), 50))
    return normalized_page, normalized_limit


def _build_ride_search_query(search_query: str | None) -> dict:
    normalized_search_query = _normalize_text(search_query)
    if not normalized_search_query:
        return {}

    regex = {"$regex": re.escape(normalized_search_query), "$options": "i"}
    driver_ids = [
        driver_document["_id"]
        for driver_document in users_collection().find(
            {"role": "driver", "full_name": regex},
            {"_id": 1},
        ).limit(25)
    ]
    vehicle_ids = [
        vehicle_document["_id"]
        for vehicle_document in vehicles_collection().find(
            {"registration_number": regex},
            {"_id": 1},
        ).limit(25)
    ]
    customer_ids = [
        customer_document["_id"]
        for customer_document in customers_collection().find(
            {"full_name": regex},
            {"_id": 1},
        ).limit(25)
    ]
    or_conditions = [
        {"trip_id": regex},
        {"ride_id": regex},
        {"customer_name_snapshot": regex},
        {"destination_area": regex},
    ]
    if driver_ids:
        or_conditions.append({"driver_id": {"$in": driver_ids}})
    if vehicle_ids:
        or_conditions.append({"vehicle_id": {"$in": vehicle_ids}})
    if customer_ids:
        or_conditions.append({"customer_id": {"$in": customer_ids}})
    return {"$or": or_conditions}


def _sync_booking_status_from_ride(ride_document: dict):
    booking_id = ride_document.get("source_booking_id")
    if not booking_id:
        return

    status_map = {
        "Logged": "Completed",
        "Scheduled": "Scheduled",
        "Completed": "Completed",
        "Cancelled": "Cancelled",
    }
    bookings_collection().update_one(
        {"_id": booking_id},
        {
            "$set": {
                "status": status_map.get(ride_document.get("status"), "Scheduled"),
                "updated_at": now_utc(),
            }
        },
    )


def _create_ride_notifications(ride_document: dict, title: str, message: str, *, priority: str = "medium"):
    if ride_document.get("driver_id"):
        create_notification(
            recipient_user_id=ride_document["driver_id"],
            title=title,
            message=message,
            category="trip",
            priority=priority,
            reference_type="ride",
            reference_id=ride_document["_id"],
        )
    notify_roles(
        ["owner", "admin"],
        title,
        message,
        category="trip",
        priority=priority,
        reference_type="ride",
        reference_id=ride_document["_id"],
    )


def _resolve_trip_source(value: str | None):
    document = resolve_master_data_item("ride_sources", value, active_only=True)
    if document is None:
        raise ApiError("trip_source_id is required.", status_code=400)
    return document


def _resolve_trip_purpose(value: str | None):
    document = resolve_master_data_item("ride_purposes", value, active_only=True)
    if document is None:
        raise ApiError("trip_purpose_id is required.", status_code=400)
    return document


def _normalized_ride_payload(payload: dict, *, partial: bool = False) -> dict:
    normalized: dict[str, Any] = {}
    customer_document = None

    if "customer_id" in payload or not partial:
        customer_document = _get_customer_document(payload.get("customer_id"))
        normalized["customer_id"] = customer_document["_id"] if customer_document else None
        normalized["customer_name_snapshot"] = customer_document.get("full_name") if customer_document else None

    if "driver_id" in payload:
        driver = _get_driver_document(payload.get("driver_id"))
        normalized["driver_id"] = driver["_id"] if driver else None
    elif not partial:
        normalized["driver_id"] = None

    if "vehicle_id" in payload or not partial:
        vehicle = _get_vehicle_document(payload.get("vehicle_id"))
        if not vehicle:
            raise ApiError("vehicle_id is required.", status_code=400)
        normalized["vehicle_id"] = vehicle["_id"]

    if "trip_source_id" in payload or "ride_source" in payload or not partial:
        source_document = _resolve_trip_source(payload.get("trip_source_id") or payload.get("ride_source"))
        normalized["trip_source_id"] = source_document["_id"]
        normalized["trip_source"] = source_document["name"]

    if "trip_purpose_id" in payload or "ride_purpose" in payload or not partial:
        purpose_document = _resolve_trip_purpose(payload.get("trip_purpose_id") or payload.get("ride_purpose"))
        normalized["trip_purpose_id"] = purpose_document["_id"]
        normalized["trip_purpose"] = purpose_document["name"]

    if "trip_date" in payload or not partial:
        normalized["trip_date"] = _parse_trip_date(payload.get("trip_date"), "trip_date", required=not partial)

    for field_name in ("start_time", "end_time"):
        if field_name in payload:
            normalized[field_name] = _parse_time_value(payload.get(field_name), field_name)
        elif not partial:
            normalized[field_name] = None

    for field_name in ("pickup_area", "destination_area", "notes"):
        legacy_field = "pickup_location" if field_name == "pickup_area" else "destination" if field_name == "destination_area" else field_name
        if field_name in payload or legacy_field in payload or not partial:
            value = _normalize_text(payload.get(field_name) if field_name in payload else payload.get(legacy_field))
            if not partial and field_name in {"pickup_area", "destination_area"} and not value:
                raise ApiError(f"{field_name} is required.", status_code=400)
            normalized[field_name] = value

    for field_name in ("odometer_start", "odometer_end"):
        if field_name in payload:
            normalized[field_name] = _validate_number(payload.get(field_name), field_name)
        elif not partial:
            normalized[field_name] = None

    if "actual_fare" in payload or "amount_charged" in payload:
        normalized["actual_fare"] = _validate_number(
            payload.get("actual_fare") if "actual_fare" in payload else payload.get("amount_charged"),
            "actual_fare",
            non_negative=True,
        )
    elif not partial:
        normalized["actual_fare"] = None

    if "platform_fee" in payload:
        normalized["platform_fee"] = _validate_number(
            payload.get("platform_fee"), "platform_fee", non_negative=True
        )
    elif not partial:
        normalized["platform_fee"] = 0.0 if normalized.get("actual_fare") is not None else None

    if "payment_method" in payload:
        normalized["payment_method"] = _validate_payment_method(payload.get("payment_method"))
    elif not partial:
        normalized["payment_method"] = None

    _apply_earnings_values(normalized)

    if "status" in payload or not partial:
        normalized["status"] = _validate_status(payload.get("status"))

    if "source_booking_id" in payload:
        booking = _get_booking_document(payload.get("source_booking_id"))
        normalized["source_booking_id"] = booking["_id"] if booking else None

    if normalized.get("odometer_start") is not None and normalized.get("odometer_end") is not None:
        if normalized["odometer_end"] < normalized["odometer_start"]:
            raise ApiError("odometer_end cannot be less than odometer_start.", status_code=400)

    return normalized


def list_ride_options(current_user_id: str, current_role: str) -> dict:
    request_started_at = perf_counter()
    customer_query = {}
    driver_query = {"role": "driver", "status": "active"}
    if current_role == "driver":
        customer_query["created_by"] = _to_object_id(current_user_id, "current_user_id")
        driver_query["_id"] = _to_object_id(current_user_id, "current_user_id")
    bookings_query = {
        "status": {"$in": ACTIVE_BOOKING_STATUSES},
        "is_recurring_template": False,
        "trip_log_id": None,
    }
    if current_role == "driver":
        current_object_id = _to_object_id(current_user_id, "current_user_id")
        bookings_query["$or"] = [{"driver_id": current_object_id}, {"created_by": current_object_id}]

    cache_key = build_cache_key(
        "ride_options",
        current_user_id=current_user_id,
        current_role=current_role,
        customers=_cached_collection_freshness_token("customers", customers_collection(), customer_query),
        drivers=_cached_collection_freshness_token("drivers", users_collection(), driver_query),
        vehicles=_cached_collection_freshness_token("vehicles", vehicles_collection()),
        bookings=_cached_collection_freshness_token("bookings", bookings_collection(), bookings_query),
    )
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    query_metrics: list[dict] = []

    customers_started_at = perf_counter()
    customers = list(
        customers_collection().find(
            customer_query,
            {"full_name": 1, "phone_number": 1},
        ).sort("full_name", ASCENDING)
    )
    query_metrics.append({
        "label": "rides.options.customers",
        "collection": "customers",
        "duration_ms": log_db_duration("rides.options.customers", customers_started_at),
    })

    drivers_started_at = perf_counter()
    drivers = list(
        users_collection().find(
            driver_query,
            {"full_name": 1, "status": 1},
        ).sort("full_name", ASCENDING)
    )
    query_metrics.append({
        "label": "rides.options.drivers",
        "collection": "users",
        "duration_ms": log_db_duration("rides.options.drivers", drivers_started_at),
    })

    vehicles_started_at = perf_counter()
    vehicle_query = {}
    if current_role == "driver":
        vehicle_query["_id"] = {"$in": list(_driver_vehicle_ids(current_user_id))}
    vehicles = list(
        vehicles_collection().find(
            vehicle_query,
            {"registration_number": 1, "make": 1, "model": 1, "vehicle_type": 1, "status": 1},
        ).sort("registration_number", ASCENDING)
    )
    query_metrics.append({
        "label": "rides.options.vehicles",
        "collection": "vehicles",
        "duration_ms": log_db_duration("rides.options.vehicles", vehicles_started_at),
    })

    bookings_started_at = perf_counter()
    bookings = list(
        bookings_collection().find(
            bookings_query,
            {
                "booking_id": 1,
                "customer_id": 1,
                "driver_id": 1,
                "vehicle_id": 1,
                "booking_type": 1,
                "pickup_location": 1,
                "destination": 1,
                "pickup_date": 1,
                "pickup_time": 1,
                "pickup_at": 1,
                "status": 1,
                "expected_fare": 1,
            },
        ).sort([("pickup_at", ASCENDING)])
    )
    query_metrics.append({
        "label": "rides.options.bookings",
        "collection": "bookings",
        "duration_ms": log_db_duration("rides.options.bookings", bookings_started_at),
    })

    result = {
        "customers": [_serialize_ride_option_customer(customer) for customer in customers],
        "drivers": [_serialize_ride_option_driver(driver) for driver in drivers],
        "vehicles": [_serialize_ride_option_vehicle(vehicle) for vehicle in vehicles],
        "bookings": [_serialize_ride_option_booking(booking) for booking in bookings],
        "trip_sources": get_active_master_data_items("ride_sources"),
        "trip_purposes": get_active_master_data_items("ride_purposes"),
        "statuses": sorted(TRIP_STATUSES),
    }
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    current_app.logger.info(
        "[Flux Rides] options role=%s duration_ms=%.2f",
        current_role,
        total_duration_ms,
    )
    _log_slow_endpoint("/api/rides/options", role=current_role, duration_ms=total_duration_ms, query_metrics=query_metrics)
    return set_ttl_cached(cache_key, result, ttl_seconds=30)


def list_rides(
    current_user_id: str,
    current_role: str,
    *,
    page: int | None = None,
    limit: int | None = None,
    search_query: str | None = None,
) -> dict:
    request_started_at = perf_counter()
    normalized_page, normalized_limit = _normalize_page_limit(page, limit)
    query = _merge_queries(
        _in_scope_query(current_user_id, current_role),
        _build_ride_search_query(search_query),
    )

    query_metrics: list[dict] = []

    find_started_at = perf_counter()
    ride_documents_page = list(
        rides_collection().find(query, RIDE_LIST_PROJECTION)
        .sort([("trip_date", DESCENDING), ("created_at", DESCENDING)])
        .skip((normalized_page - 1) * normalized_limit)
        .limit(normalized_limit + 1)
    )
    query_metrics.append({
        "label": "rides.list.find",
        "collection": "rides",
        "duration_ms": log_db_duration("rides.list.find", find_started_at),
    })

    has_next = len(ride_documents_page) > normalized_limit
    ride_documents = ride_documents_page[:normalized_limit]
    if normalized_page == 1 and not has_next:
        total = len(ride_documents)
    else:
        count_started_at = perf_counter()
        total = rides_collection().count_documents(query)
        query_metrics.append({
            "label": "rides.list.count",
            "collection": "rides",
            "duration_ms": log_db_duration("rides.list.count", count_started_at),
        })

    enrichment_started_at = perf_counter()
    driver_map, vehicle_map = _load_ride_relationship_maps(ride_documents)
    rides = [
        _enrich_ride_list_item(
            ride_document,
            driver_map=driver_map,
            vehicle_map=vehicle_map,
            include_earnings=current_role == "driver",
        )
        for ride_document in ride_documents
    ]
    query_metrics.append({
        "label": "rides.list.enrichment",
        "collection": "relationships",
        "duration_ms": round((perf_counter() - enrichment_started_at) * 1000, 2),
    })

    total_pages = max((total + normalized_limit - 1) // normalized_limit, 1)
    result = {
        "rides": rides,
        "pagination": {
            "page": normalized_page,
            "limit": normalized_limit,
            "total": total,
            "total_pages": total_pages,
            "has_next": has_next if normalized_page == 1 and total <= normalized_limit else normalized_page < total_pages,
            "has_prev": normalized_page > 1,
        },
        "query": {
            "q": _normalize_text(search_query),
        },
    }
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    current_app.logger.info(
        "[Flux Rides] list role=%s page=%s limit=%s total=%s duration_ms=%.2f",
        current_role,
        normalized_page,
        normalized_limit,
        total,
        total_duration_ms,
    )
    _log_slow_endpoint("/api/rides", role=current_role, duration_ms=total_duration_ms, query_metrics=query_metrics)
    return result


def create_ride(payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to create trip logs.", status_code=403)

    normalized = _normalized_ride_payload(payload, partial=False)
    customer_document = _get_customer_document(str(normalized["customer_id"])) if normalized.get("customer_id") else None
    _assert_customer_access(
        customer_document,
        current_user_id=current_user_id,
        current_role=current_role,
    )

    booking_document = None
    if normalized.get("source_booking_id"):
        booking_document = _get_booking_document(str(normalized["source_booking_id"]))
        if customer_document and booking_document.get("customer_id") != customer_document["_id"]:
            raise ApiError("Booking does not belong to the selected customer.", status_code=400)
        if booking_document.get("trip_log_id") or rides_collection().find_one({"source_booking_id": booking_document["_id"]}, {"_id": 1}):
            raise ApiError("This booking already has a trip log.", status_code=409)

    if current_role == "driver":
        current_driver_id = _to_object_id(current_user_id, "current_user_id")
        normalized["driver_id"] = normalized.get("driver_id") or current_driver_id
        if normalized["driver_id"] != current_driver_id:
            raise ApiError("Drivers can only assign trip logs to themselves.", status_code=403)
        _assert_driver_vehicle_access(current_user_id, normalized["vehicle_id"])

    if normalized.get("end_time"):
        normalized["status"] = "Completed"

    timestamp = now_utc()
    trip_identifier = _build_trip_id()
    ride_document = {
        "_id": ObjectId(),
        "trip_id": trip_identifier,
        "ride_id": trip_identifier,
        "customer_id": normalized.get("customer_id"),
        "customer_name_snapshot": normalized.get("customer_name_snapshot"),
        "driver_id": normalized.get("driver_id"),
        "vehicle_id": normalized["vehicle_id"],
        "trip_source_id": normalized["trip_source_id"],
        "trip_purpose_id": normalized["trip_purpose_id"],
        "trip_source": normalized["trip_source"],
        "trip_purpose": normalized["trip_purpose"],
        "trip_date": normalized["trip_date"],
        "start_time": normalized.get("start_time"),
        "end_time": normalized.get("end_time"),
        "pickup_area": normalized["pickup_area"],
        "destination_area": normalized["destination_area"],
        "odometer_start": normalized.get("odometer_start"),
        "odometer_end": normalized.get("odometer_end"),
        "actual_fare": normalized.get("actual_fare"),
        "payment_method": normalized.get("payment_method"),
        "platform_fee": normalized.get("platform_fee"),
        "net_earnings": normalized.get("net_earnings"),
        "notes": normalized.get("notes"),
        "status": normalized.get("status", "Logged"),
        "created_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "source_booking_id": normalized.get("source_booking_id"),
        "audit_events": [
            _serialize_audit_event(
                action="created",
                user_id=current_user_id,
                changes=sorted(normalized.keys()),
            )
        ],
    }
    if booking_document:
        reserved = bookings_collection().update_one(
            {"_id": booking_document["_id"], "trip_log_id": None},
            {"$set": {"trip_log_id": ride_document["_id"], "updated_at": timestamp}},
        )
        if reserved.matched_count != 1:
            raise ApiError("This booking already has a trip log.", status_code=409)
    try:
        rides_collection().insert_one(ride_document)
    except Exception:
        if booking_document:
            bookings_collection().update_one(
                {"_id": booking_document["_id"], "trip_log_id": ride_document["_id"]},
                {"$unset": {"trip_log_id": ""}},
            )
        raise
    _sync_booking_status_from_ride(ride_document)
    invalidate_ttl_cache("ride_summary", "ride_options")

    customer_name = customer_document.get("full_name") if customer_document else "Trip log"
    _create_ride_notifications(
        ride_document,
        "Trip logged",
        f"{customer_name} trip has been logged for {ride_document['trip_date']}.",
    )
    return _enrich_ride(ride_document, include_earnings=current_role == "driver")


def convert_booking_to_ride(booking_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    booking_document = _get_booking_document(booking_id)
    pickup_at = _as_utc_datetime(booking_document.get("pickup_at"))
    pickup_date = pickup_at.date().isoformat() if pickup_at else booking_document.get("pickup_date")
    pickup_time = pickup_at.strftime("%H:%M") if pickup_at else booking_document.get("pickup_time")

    source_payload = {
        "customer_id": str(booking_document.get("customer_id")) if booking_document.get("customer_id") else None,
        "driver_id": str(booking_document.get("driver_id")) if booking_document.get("driver_id") else None,
        "vehicle_id": str(booking_document.get("vehicle_id")) if booking_document.get("vehicle_id") else None,
        "trip_source_id": "Flux Booking",
        "trip_purpose_id": payload.get("trip_purpose_id") or payload.get("ride_purpose") or "Company Ride",
        "trip_date": payload.get("trip_date") or pickup_date,
        "start_time": payload.get("start_time") or pickup_time,
        "end_time": payload.get("end_time"),
        "pickup_area": payload.get("pickup_area") or payload.get("pickup_location") or booking_document.get("pickup_location"),
        "destination_area": payload.get("destination_area") or payload.get("destination") or booking_document.get("destination"),
        "notes": payload.get("notes") or booking_document.get("notes"),
        "actual_fare": booking_document.get("expected_fare") if booking_document.get("expected_fare") is not None else (payload.get("actual_fare") if "actual_fare" in payload else payload.get("amount_charged")),
        "payment_method": payload.get("payment_method"),
        "platform_fee": payload.get("platform_fee"),
        "status": payload.get("status") or "Scheduled",
        "source_booking_id": booking_id,
        "odometer_start": payload.get("odometer_start"),
        "odometer_end": payload.get("odometer_end"),
    }
    return create_ride(source_payload, current_user_id, current_role)


def get_ride_by_id(ride_id: str, current_user_id: str, current_role: str) -> dict:
    ride_document = rides_collection().find_one({"_id": _to_object_id(ride_id, "ride_id")})
    if not ride_document:
        raise ApiError("Trip log not found.", status_code=404)
    _assert_ride_access(
        ride_document,
        current_user_id=current_user_id,
        current_role=current_role,
    )
    return _enrich_ride(ride_document, include_earnings=current_role == "driver")


def update_ride(ride_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    ride_document = rides_collection().find_one({"_id": _to_object_id(ride_id, "ride_id")})
    if not ride_document:
        raise ApiError("Trip log not found.", status_code=404)
    _assert_ride_access(
        ride_document,
        current_user_id=current_user_id,
        current_role=current_role,
    )

    normalized = _normalized_ride_payload(payload, partial=True)
    if not normalized:
        raise ApiError("No trip log fields provided for update.", status_code=400)
    _apply_earnings_values(normalized, ride_document)

    if current_role == "driver" and "driver_id" in normalized:
        current_driver_id = _to_object_id(current_user_id, "current_user_id")
        if normalized.get("driver_id") and normalized["driver_id"] != current_driver_id:
            raise ApiError("Drivers can only assign trip logs to themselves.", status_code=403)
    if current_role == "driver" and "vehicle_id" in normalized:
        _assert_driver_vehicle_access(current_user_id, normalized["vehicle_id"])

    odometer_start = normalized.get("odometer_start", ride_document.get("odometer_start"))
    odometer_end = normalized.get("odometer_end", ride_document.get("odometer_end"))
    if odometer_start is not None and odometer_end is not None and odometer_end < odometer_start:
        raise ApiError("odometer_end cannot be less than odometer_start.", status_code=400)

    if "end_time" in normalized and normalized.get("end_time"):
        normalized["status"] = "Completed"

    timestamp = now_utc()
    next_status = normalized.get("status", ride_document.get("status"))
    audit_event = _serialize_audit_event(
        action="updated",
        user_id=current_user_id,
        changes=sorted(normalized.keys()),
        note=f"Trip moved to {next_status}" if "status" in normalized else None,
    )
    update_fields = {
        **normalized,
        "updated_at": timestamp,
    }
    rides_collection().update_one(
        {"_id": ride_document["_id"]},
        {"$set": update_fields, "$push": {"audit_events": audit_event}},
    )
    ride_document.update(update_fields)
    ride_document.setdefault("audit_events", []).append(audit_event)
    _sync_booking_status_from_ride(ride_document)
    invalidate_ttl_cache("ride_summary", "ride_options")

    if "status" in normalized:
        customer_document = customers_collection().find_one({"_id": ride_document.get("customer_id")})
        customer_name = customer_document.get("full_name") if customer_document else "Trip"
        _create_ride_notifications(
            ride_document,
            "Trip status updated",
            f"{customer_name} trip is now {ride_document.get('status')}.",
            priority="high" if ride_document.get("status") in {"Completed", "Cancelled"} else "medium",
        )
    return _enrich_ride(ride_document, include_earnings=current_role == "driver")


def _status_count(documents: list[dict], status: str):
    return len([document for document in documents if document.get("status") == status])


def _in_scope_query(current_user_id: str, current_role: str):
    if current_role == "driver":
        current_object_id = _to_object_id(current_user_id, "current_user_id")
        return {"$or": [{"driver_id": current_object_id}, {"created_by": current_object_id}]}
    return {}


def _current_time_windows():
    now = now_utc()
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    return now, today, week_start, month_start


def _in_date_window(trip_date_value: str | None, start_date, end_date):
    if not trip_date_value:
        return False
    trip_date = datetime.strptime(trip_date_value, "%Y-%m-%d").date()
    return start_date <= trip_date <= end_date


def _earnings_summary(documents: list[dict]) -> dict:
    earning_trips = [
        document for document in documents
        if document.get("status") == "Completed" and document.get("actual_fare") is not None
    ]
    gross = round(sum(float(document.get("actual_fare") or 0) for document in earning_trips), 2)
    fees = round(sum(float(document.get("platform_fee") or 0) for document in earning_trips), 2)

    def breakdown(field_name: str):
        grouped: dict[str, dict] = {}
        for document in earning_trips:
            label = document.get(field_name) or "Not specified"
            item = grouped.setdefault(label, {"label": label, "trip_count": 0, "gross_charged": 0.0, "platform_fees": 0.0, "net_earnings": 0.0})
            item["trip_count"] += 1
            item["gross_charged"] += float(document.get("actual_fare") or 0)
            item["platform_fees"] += float(document.get("platform_fee") or 0)
            item["net_earnings"] += float(document.get("net_earnings") if document.get("net_earnings") is not None else (document.get("actual_fare") or 0) - (document.get("platform_fee") or 0))
        for item in grouped.values():
            for amount_field in ("gross_charged", "platform_fees", "net_earnings"):
                item[amount_field] = round(item[amount_field], 2)
        return sorted(grouped.values(), key=lambda item: (-item["net_earnings"], item["label"]))

    return {
        "trip_count": len(earning_trips),
        "gross_charged": gross,
        "platform_fees": fees,
        "net_earnings": round(gross - fees, 2),
        "payment_method_breakdown": breakdown("payment_method"),
        "source_breakdown": breakdown("trip_source"),
    }


def _earnings_date_range(period: str | None, start_date: str | None, end_date: str | None):
    today = now_utc().date()
    normalized_period = str(period or "month").strip().lower()
    if normalized_period == "today":
        return normalized_period, today, today
    if normalized_period == "week":
        return normalized_period, today - timedelta(days=today.weekday()), today
    if normalized_period == "month":
        return normalized_period, today.replace(day=1), today
    if normalized_period != "custom":
        raise ApiError("period must be one of: today, week, month, custom.", status_code=400)
    try:
        first = datetime.strptime(str(start_date or ""), "%Y-%m-%d").date()
        last = datetime.strptime(str(end_date or ""), "%Y-%m-%d").date()
    except ValueError as error:
        raise ApiError("start_date and end_date are required as YYYY-MM-DD for a custom range.", status_code=400) from error
    if first > last:
        raise ApiError("start_date cannot be after end_date.", status_code=400)
    return normalized_period, first, last


def get_driver_earnings(
    current_user_id: str,
    *,
    period: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    source: str | None = None,
    payment_method: str | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict:
    """Return private earnings derived directly from the authenticated driver's completed trips."""
    driver_id = _to_object_id(current_user_id, "current_user_id")
    normalized_period, first, last = _earnings_date_range(period, start_date, end_date)
    normalized_page, normalized_limit = _normalize_page_limit(page, limit)
    normalized_source = _normalize_text(source)
    normalized_method = _normalize_text(payment_method)
    if normalized_method and normalized_method not in PAYMENT_METHODS:
        raise ApiError("payment_method must be one of: Cash, MoMo.", status_code=400)

    query: dict[str, Any] = {
        "driver_id": driver_id,
        "status": "Completed",
        "actual_fare": {"$ne": None},
        "trip_date": {"$gte": first.isoformat(), "$lte": last.isoformat()},
    }
    if normalized_source:
        query["trip_source"] = normalized_source
    if normalized_method:
        query["payment_method"] = normalized_method

    documents = list(rides_collection().find(query, RIDE_LIST_PROJECTION).sort([
        ("trip_date", DESCENDING), ("end_time", DESCENDING), ("created_at", DESCENDING),
    ]))
    summary = _earnings_summary(documents)
    trend_by_date: dict[str, dict] = {}
    for document in documents:
        trip_date = document.get("trip_date")
        if not trip_date:
            continue
        row = trend_by_date.setdefault(trip_date, {
            "date": trip_date, "trip_count": 0, "gross_earnings": 0.0,
            "platform_fees": 0.0, "net_earnings": 0.0,
        })
        gross = float(document.get("actual_fare") or 0)
        fee = float(document.get("platform_fee") or 0)
        row["trip_count"] += 1
        row["gross_earnings"] += gross
        row["platform_fees"] += fee
        row["net_earnings"] += gross - fee
    for row in trend_by_date.values():
        for field in ("gross_earnings", "platform_fees", "net_earnings"):
            row[field] = round(row[field], 2)

    offset = (normalized_page - 1) * normalized_limit
    page_documents = documents[offset:offset + normalized_limit]
    transactions = []
    for document in page_documents:
        gross = round(float(document.get("actual_fare") or 0), 2)
        fee = round(float(document.get("platform_fee") or 0), 2)
        transactions.append({
            "id": str(document.get("_id")),
            "trip_id": document.get("trip_id") or document.get("ride_id"),
            "trip_date": document.get("trip_date"),
            "start_time": document.get("start_time"),
            "end_time": document.get("end_time"),
            "source": document.get("trip_source"),
            "payment_method": document.get("payment_method"),
            "gross_earnings": gross,
            "platform_fee": fee,
            "net_earnings": round(gross - fee, 2),
            "pickup_area": document.get("pickup_area"),
            "destination_area": document.get("destination_area"),
        })

    total = len(documents)
    cash = next((row["gross_charged"] for row in summary["payment_method_breakdown"] if row["label"] == "Cash"), 0.0)
    momo = next((row["gross_charged"] for row in summary["payment_method_breakdown"] if row["label"] == "MoMo"), 0.0)
    available_sources = sorted(value for value in rides_collection().distinct("trip_source", {
        "driver_id": driver_id, "status": "Completed", "actual_fare": {"$ne": None},
    }) if value)
    return {
        "summary": {
            "trip_count": summary["trip_count"],
            "gross_earnings": summary["gross_charged"],
            "platform_fees": summary["platform_fees"],
            "net_earnings": summary["net_earnings"],
            "cash": round(float(cash), 2),
            "momo": round(float(momo), 2),
        },
        "trend": [trend_by_date[key] for key in sorted(trend_by_date)],
        "transactions": transactions,
        "filters": {"sources": available_sources, "payment_methods": sorted(PAYMENT_METHODS)},
        "range": {"period": normalized_period, "start_date": first.isoformat(), "end_date": last.isoformat()},
        "pagination": {
            "page": normalized_page, "limit": normalized_limit, "total": total,
            "total_pages": max((total + normalized_limit - 1) // normalized_limit, 1),
            "has_next": offset + normalized_limit < total, "has_prev": normalized_page > 1,
        },
    }


def get_ride_summary(current_user_id: str, current_role: str) -> dict:
    cache_key = build_cache_key("ride_summary", current_user_id=current_user_id, current_role=current_role)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    request_started_at = perf_counter()
    query = _in_scope_query(current_user_id, current_role)
    query_metrics: list[dict] = []

    rides_started_at = perf_counter()
    ride_documents = list(rides_collection().find(query, RIDE_SUMMARY_PROJECTION))
    query_metrics.append({
        "label": "rides.summary.find",
        "collection": "rides",
        "duration_ms": log_db_duration("rides.summary.find", rides_started_at),
    })
    now, today, week_start, month_start = _current_time_windows()

    trips_today = [document for document in ride_documents if _in_date_window(document.get("trip_date"), today, today)]
    trips_this_week = [document for document in ride_documents if _in_date_window(document.get("trip_date"), week_start, today)]
    trips_this_month = [document for document in ride_documents if _in_date_window(document.get("trip_date"), month_start, today)]

    trend_map: dict[str, dict[str, int | str]] = {}
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        trend_map[day] = {"date": day, "trips": 0, "completed": 0, "vehicles_active": 0}

    active_vehicle_sets: dict[str, set[str]] = defaultdict(set)
    for document in ride_documents:
        trip_date = document.get("trip_date")
        if trip_date in trend_map:
            trend_map[trip_date]["trips"] += 1
            if document.get("status") == "Completed":
                trend_map[trip_date]["completed"] += 1
            if document.get("vehicle_id"):
                active_vehicle_sets[trip_date].add(str(document.get("vehicle_id")))
    for trip_date, vehicle_ids in active_vehicle_sets.items():
        trend_map[trip_date]["vehicles_active"] = len(vehicle_ids)

    source_counter = Counter(document.get("trip_source") for document in ride_documents if document.get("trip_source"))
    purpose_counter = Counter(document.get("trip_purpose") for document in ride_documents if document.get("trip_purpose"))

    vehicles_started_at = perf_counter()
    vehicle_documents = list(
        vehicles_collection().find(
            {},
            {"registration_number": 1, "vehicle_type": 1, "make": 1, "model": 1, "status": 1},
        ).sort("registration_number", ASCENDING)
    )
    query_metrics.append({
        "label": "rides.summary.vehicles",
        "collection": "vehicles",
        "duration_ms": log_db_duration("rides.summary.vehicles", vehicles_started_at),
    })
    days_elapsed_this_month = today.day
    vehicle_activity: dict[str, set[str]] = defaultdict(set)
    for document in trips_this_month:
        if document.get("vehicle_id") and document.get("trip_date"):
            vehicle_activity[str(document["vehicle_id"])].add(document["trip_date"])

    vehicle_utilization = []
    total_vehicle_active_days = 0
    total_vehicle_idle_days = 0
    for vehicle in vehicle_documents:
        active_days = len(vehicle_activity.get(str(vehicle["_id"]), set()))
        idle_days = max(days_elapsed_this_month - active_days, 0)
        total_vehicle_active_days += active_days
        total_vehicle_idle_days += idle_days
        vehicle_utilization.append(
            {
                "vehicle": _serialize_ride_list_vehicle(vehicle),
                "active_days": active_days,
                "idle_days": idle_days,
                "trip_count": len(
                    [document for document in trips_this_month if document.get("vehicle_id") == vehicle["_id"]]
                ),
            }
        )

    vehicle_utilization.sort(
        key=lambda item: (-item["active_days"], -item["trip_count"], item["vehicle"]["registration_number"])
    )

    driver_counter = defaultdict(lambda: {"trips": 0, "completed": 0})
    for document in ride_documents:
        driver_id = document.get("driver_id")
        if not driver_id:
            continue
        key = str(driver_id)
        driver_counter[key]["trips"] += 1
        if document.get("status") == "Completed":
            driver_counter[key]["completed"] += 1

    driver_ids = [ObjectId(driver_id) for driver_id in driver_counter]
    drivers_started_at = perf_counter()
    driver_lookup = {
        str(driver_document["_id"]): driver_document
        for driver_document in users_collection().find(
            {"_id": {"$in": driver_ids}},
            {"full_name": 1, "role": 1, "status": 1},
        )
    } if driver_ids else {}
    query_metrics.append({
        "label": "rides.summary.drivers",
        "collection": "users",
        "duration_ms": log_db_duration("rides.summary.drivers", drivers_started_at),
    })

    trip_performance = []
    for driver_id, stats in driver_counter.items():
        driver = driver_lookup.get(driver_id)
        trip_performance.append(
            {
                "driver": _serialize_ride_list_driver(driver),
                "trips": stats["trips"],
                "completed_trips": stats["completed"],
            }
        )
    trip_performance.sort(key=lambda item: (-item["trips"], -(item["completed_trips"])))

    result = {
        "total_trips": len(ride_documents),
        "completed_trips": _status_count(ride_documents, "Completed"),
        "cancelled_trips": _status_count(ride_documents, "Cancelled"),
        "scheduled_trips": _status_count(ride_documents, "Scheduled"),
        "logged_trips": _status_count(ride_documents, "Logged"),
        "trips_today": len(trips_today),
        "trips_this_week": len(trips_this_week),
        "trips_this_month": len(trips_this_month),
        "vehicle_active_days": total_vehicle_active_days,
        "vehicle_idle_days": total_vehicle_idle_days,
        "activity_trends": list(trend_map.values()),
        "trip_performance": trip_performance[:10],
        "trips_by_platform": [
            {"label": label, "count": count}
            for label, count in source_counter.most_common()
        ],
        "trips_by_purpose": [
            {"label": label, "count": count}
            for label, count in purpose_counter.most_common()
        ],
        "vehicle_utilization": vehicle_utilization,
        "personal_trip_count": len([document for document in ride_documents if document.get("trip_purpose") == "Personal Ride"]),
        "company_trip_count": len([document for document in ride_documents if document.get("trip_purpose") == "Company Ride"]),
        "customer_linked_trip_count": len([document for document in ride_documents if document.get("customer_id")]),
        "generated_at": now.isoformat(),
    }
    if current_role == "driver":
        result["earnings"] = {
            "today": _earnings_summary(trips_today),
            "week": _earnings_summary(trips_this_week),
            "month": _earnings_summary(trips_this_month),
        }
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    current_app.logger.info(
        "[Flux Rides] summary role=%s duration_ms=%.2f",
        current_role,
        total_duration_ms,
    )
    _log_slow_endpoint("/api/rides/summary", role=current_role, duration_ms=total_duration_ms, query_metrics=query_metrics)
    return set_ttl_cached(cache_key, result, ttl_seconds=30)
