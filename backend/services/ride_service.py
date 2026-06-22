from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.booking import serialize_booking
from models.customer import serialize_customer
from models.ride import serialize_ride
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.master_data_service import get_active_master_data_items, resolve_master_data_item
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError


TRIP_STATUSES = {
    "Logged",
    "Scheduled",
    "Completed",
    "Cancelled",
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


def _validate_number(value, field_name: str, *, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    return round(float(value), 2)


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


def _enrich_ride(ride_document: dict):
    ride = serialize_ride(ride_document)
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

    if "customer_id" in payload or not partial:
        customer = _get_customer_document(payload.get("customer_id"))
        normalized["customer_id"] = customer["_id"] if customer else None

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
    customer_query = {}
    driver_query = {"role": "driver", "status": "active"}
    if current_role == "driver":
        customer_query["created_by"] = _to_object_id(current_user_id, "current_user_id")
        driver_query["_id"] = _to_object_id(current_user_id, "current_user_id")
    bookings_query = {
        "status": {"$in": ["Scheduled", "Acknowledged", "En Route", "Picked Up", "Confirmed"]},
        "is_recurring_template": False,
    }
    if current_role == "driver":
        current_object_id = _to_object_id(current_user_id, "current_user_id")
        bookings_query["$or"] = [{"driver_id": current_object_id}, {"created_by": current_object_id}]

    return {
        "customers": [serialize_customer(customer) for customer in customers_collection().find(customer_query).sort("full_name", ASCENDING)],
        "drivers": [serialize_user(driver) for driver in users_collection().find(driver_query).sort("full_name", ASCENDING)],
        "vehicles": [serialize_vehicle(vehicle) for vehicle in vehicles_collection().find({}).sort("registration_number", ASCENDING)],
        "bookings": [serialize_booking(booking) for booking in bookings_collection().find(bookings_query).sort([("pickup_at", ASCENDING)])],
        "trip_sources": get_active_master_data_items("ride_sources"),
        "trip_purposes": get_active_master_data_items("ride_purposes"),
        "statuses": sorted(TRIP_STATUSES),
    }


def list_rides(current_user_id: str, current_role: str) -> list[dict]:
    query = {}
    if current_role == "driver":
        current_object_id = _to_object_id(current_user_id, "current_user_id")
        query["$or"] = [{"driver_id": current_object_id}, {"created_by": current_object_id}]
    rides = rides_collection().find(query).sort([("trip_date", DESCENDING), ("created_at", DESCENDING)])
    return [_enrich_ride(ride_document) for ride_document in rides]


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

    if current_role == "driver":
        current_driver_id = _to_object_id(current_user_id, "current_user_id")
        normalized["driver_id"] = normalized.get("driver_id") or current_driver_id
        if normalized["driver_id"] != current_driver_id:
            raise ApiError("Drivers can only assign trip logs to themselves.", status_code=403)

    if normalized.get("end_time"):
        normalized["status"] = "Completed"

    timestamp = now_utc()
    trip_identifier = _build_trip_id()
    ride_document = {
        "trip_id": trip_identifier,
        "ride_id": trip_identifier,
        "customer_id": normalized.get("customer_id"),
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
    result = rides_collection().insert_one(ride_document)
    ride_document["_id"] = result.inserted_id
    _sync_booking_status_from_ride(ride_document)

    customer_name = customer_document.get("full_name") if customer_document else "Trip log"
    _create_ride_notifications(
        ride_document,
        "Trip logged",
        f"{customer_name} trip has been logged for {ride_document['trip_date']}.",
    )
    return _enrich_ride(ride_document)


def convert_booking_to_ride(booking_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    booking_document = _get_booking_document(booking_id)
    pickup_at = _as_utc_datetime(booking_document.get("pickup_at"))
    pickup_date = pickup_at.date().isoformat() if pickup_at else booking_document.get("pickup_date")
    pickup_time = pickup_at.strftime("%H:%M") if pickup_at else booking_document.get("pickup_time")

    source_payload = {
        "customer_id": str(booking_document.get("customer_id")) if booking_document.get("customer_id") else None,
        "driver_id": str(booking_document.get("driver_id")) if booking_document.get("driver_id") else None,
        "vehicle_id": str(booking_document.get("vehicle_id")) if booking_document.get("vehicle_id") else None,
        "trip_source_id": payload.get("trip_source_id") or payload.get("ride_source"),
        "trip_purpose_id": payload.get("trip_purpose_id") or payload.get("ride_purpose") or "Company Ride",
        "trip_date": payload.get("trip_date") or pickup_date,
        "start_time": payload.get("start_time") or pickup_time,
        "end_time": payload.get("end_time"),
        "pickup_area": payload.get("pickup_area") or payload.get("pickup_location") or booking_document.get("pickup_location"),
        "destination_area": payload.get("destination_area") or payload.get("destination") or booking_document.get("destination"),
        "notes": payload.get("notes") or booking_document.get("notes"),
        "status": payload.get("status") or "Scheduled",
        "source_booking_id": booking_id,
        "odometer_start": payload.get("odometer_start"),
        "odometer_end": payload.get("odometer_end"),
    }
    if not source_payload["trip_source_id"]:
        source_payload["trip_source_id"] = "Direct Customer"
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
    return _enrich_ride(ride_document)


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

    if current_role == "driver" and "driver_id" in normalized:
        current_driver_id = _to_object_id(current_user_id, "current_user_id")
        if normalized.get("driver_id") and normalized["driver_id"] != current_driver_id:
            raise ApiError("Drivers can only assign trip logs to themselves.", status_code=403)

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

    if "status" in normalized:
        customer_document = customers_collection().find_one({"_id": ride_document.get("customer_id")})
        customer_name = customer_document.get("full_name") if customer_document else "Trip"
        _create_ride_notifications(
            ride_document,
            "Trip status updated",
            f"{customer_name} trip is now {ride_document.get('status')}.",
            priority="high" if ride_document.get("status") in {"Completed", "Cancelled"} else "medium",
        )
    return _enrich_ride(ride_document)


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


def get_ride_summary(current_user_id: str, current_role: str) -> dict:
    query = _in_scope_query(current_user_id, current_role)
    ride_documents = list(rides_collection().find(query))
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

    vehicle_documents = list(vehicles_collection().find({}).sort("registration_number", ASCENDING))
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
                "vehicle": serialize_vehicle(vehicle),
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

    trip_performance = []
    for driver_id, stats in driver_counter.items():
        driver = users_collection().find_one({"_id": ObjectId(driver_id)})
        trip_performance.append(
            {
                "driver": serialize_user(driver) if driver else None,
                "trips": stats["trips"],
                "completed_trips": stats["completed"],
            }
        )
    trip_performance.sort(key=lambda item: (-item["trips"], -(item["completed_trips"])))

    return {
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
