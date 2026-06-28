from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.assignment import serialize_assignment
from models.fuel import serialize_fuel_log, serialize_fuel_station
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.assignment_service import get_active_assignment_for_driver
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError
from utils.file_validation import validate_file_reference
from utils.mongo_indexes import ensure_indexes_for_collection


ALLOWED_FUEL_STATION_STATUS = {"active", "inactive"}
ALLOWED_FUEL_LOG_STATUS = {"submitted", "approved", "rejected"}
ALLOWED_FUEL_TYPES = {"petrol", "diesel", "hybrid", "electric"}

DEFAULT_FUEL_STATIONS = [
    {"station_name": "Shell", "brand_name": "Shell"},
    {"station_name": "TotalEnergies", "brand_name": "TotalEnergies"},
    {"station_name": "Star Oil", "brand_name": "Star Oil"},
    {"station_name": "Zen Petroleum", "brand_name": "Zen Petroleum"},
    {"station_name": "Goil", "brand_name": "Goil"},
    {"station_name": "Puma", "brand_name": "Puma"},
    {"station_name": "Engen", "brand_name": "Engen"},
    {"station_name": "Allied Oil", "brand_name": "Allied Oil"},
    {"station_name": "So Energy", "brand_name": "So Energy"},
    {"station_name": "Frimps Oil", "brand_name": "Frimps Oil"},
    {"station_name": "Other", "brand_name": "Other"},
]


def now_utc():
    return datetime.now(timezone.utc)


def fuel_stations_collection():
    return get_collection("fuel_stations")


def fuel_logs_collection():
    return get_collection("fuel_logs")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def assignments_collection():
    return get_collection("assignments")


def ensure_fuel_indexes():
    ensure_indexes_for_collection(
        fuel_stations_collection(),
        [
            {"keys": [("normalized_name", ASCENDING)], "options": {"unique": True}},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
        ],
        collection_name="fuel_stations",
    )
    ensure_indexes_for_collection(
        fuel_logs_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("assignment_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("fuel_station_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("fuel_date", DESCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("fuel_date", DESCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="fuel_logs",
    )


def seed_default_fuel_stations():
    owner_or_admin = users_collection().find_one(
        {"role": {"$in": ["owner", "admin"]}, "status": "active"}
    )
    created_by = owner_or_admin["_id"] if owner_or_admin else ObjectId()

    for item in DEFAULT_FUEL_STATIONS:
        normalized_name = _normalize_station_name(item["station_name"])
        existing = fuel_stations_collection().find_one({"normalized_name": normalized_name})
        if existing:
            continue

        timestamp = now_utc()
        fuel_stations_collection().insert_one(
            {
                "station_name": item["station_name"],
                "brand_name": item.get("brand_name"),
                "location": None,
                "city": None,
                "contact_number": None,
                "status": "active",
                "normalized_name": normalized_name,
                "created_by": created_by,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
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


def _normalize_station_name(value: str | None):
    normalized = (value or "").strip().lower()
    if not normalized:
        raise ApiError("station_name is required.", status_code=400)
    return normalized


def _validate_fuel_type(value: str | None):
    fuel_type = (value or "").strip().lower()
    if fuel_type not in ALLOWED_FUEL_TYPES:
        raise ApiError(
            "fuel_type must be one of: petrol, diesel, hybrid, electric.",
            status_code=400,
        )
    return fuel_type


def _validate_positive_number(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value <= 0:
        raise ApiError(f"{field_name} must be greater than zero.", status_code=400)
    return round(float(value), 2)


def _validate_non_negative_number(value, field_name: str):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _normalize_date(value, field_name: str):
    normalized = str(value or "").strip()
    if not normalized:
        raise ApiError(f"{field_name} is required.", status_code=400)
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        try:
            datetime.strptime(normalized, "%Y-%m-%d")
        except ValueError as exc:
            raise ApiError(f"{field_name} must be a valid date.", status_code=400) from exc
    return normalized


def _get_station_document(station_id: str | ObjectId):
    station = fuel_stations_collection().find_one({"_id": _to_object_id(station_id, "fuel_station_id")})
    if not station:
        raise ApiError("Fuel station not found.", status_code=404)
    return station


def _get_vehicle_document(vehicle_id: str | ObjectId):
    vehicle = vehicles_collection().find_one({"_id": _to_object_id(vehicle_id, "vehicle_id")})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _get_driver_document(driver_id: str | ObjectId):
    driver = users_collection().find_one({"_id": _to_object_id(driver_id, "driver_id")})
    if not driver or driver.get("role") != "driver":
        raise ApiError("Driver not found.", status_code=404)
    return driver


def _get_assignment_document(assignment_id: str | ObjectId):
    assignment = assignments_collection().find_one(
        {"_id": _to_object_id(assignment_id, "assignment_id")}
    )
    if not assignment:
        raise ApiError("Assignment not found.", status_code=404)
    return assignment


def _get_fuel_log_document(log_id: str | ObjectId):
    document = fuel_logs_collection().find_one({"_id": _to_object_id(log_id, "fuel_log_id")})
    if not document:
        raise ApiError("Fuel log not found.", status_code=404)
    return document


def _resolve_driver_submission_context(current_user_id: str):
    assignment = get_active_assignment_for_driver(current_user_id)
    if not assignment:
        raise ApiError(
            "Driver must have an active assignment before submitting fuel logs.",
            status_code=400,
        )
    return assignment


def _find_previous_approved_log(vehicle_id: ObjectId, fuel_date: str, current_log_id: ObjectId | None = None):
    query = {
        "vehicle_id": vehicle_id,
        "status": "approved",
        "$or": [
            {"fuel_date": {"$lt": fuel_date}},
            {"fuel_date": fuel_date},
        ],
    }
    if current_log_id is not None:
        query["_id"] = {"$ne": current_log_id}

    logs = list(
        fuel_logs_collection()
        .find(query)
        .sort([("fuel_date", DESCENDING), ("created_at", DESCENDING)])
    )
    for log in logs:
        if log.get("fuel_date") < fuel_date:
            return log
        if current_log_id is not None and log.get("_id") == current_log_id:
            continue
        return log
    return None


def _calculate_log_metrics(vehicle_id: ObjectId, fuel_date: str, odometer_reading: float, amount: float, log_id: ObjectId | None = None):
    previous_log = _find_previous_approved_log(vehicle_id, fuel_date, current_log_id=log_id)
    previous_odometer = previous_log.get("odometer_reading") if previous_log else None
    distance_since_last_fill = None
    cost_per_km = None
    if previous_odometer is not None:
        distance_since_last_fill = round(odometer_reading - previous_odometer, 2)
        if distance_since_last_fill > 0:
            cost_per_km = round(amount / distance_since_last_fill, 4)
        else:
            distance_since_last_fill = None
    return previous_odometer, distance_since_last_fill, cost_per_km


def _calculate_abnormal_spending(vehicle_id: ObjectId, station_id: ObjectId, price_per_litre: float, amount: float, litres: float, cost_per_km: float | None):
    approved_logs = list(fuel_logs_collection().find({"status": "approved"}))
    avg_price_per_litre = (
        round(
            sum(log.get("amount", 0) for log in approved_logs)
            / max(sum(log.get("litres", 0) for log in approved_logs), 1),
            4,
        )
        if approved_logs
        else 0
    )
    vehicle_cost_per_km_values = [
        log.get("cost_per_km")
        for log in approved_logs
        if log.get("vehicle_id") == vehicle_id and log.get("cost_per_km") is not None
    ]
    avg_vehicle_cost_per_km = (
        sum(vehicle_cost_per_km_values) / len(vehicle_cost_per_km_values)
        if vehicle_cost_per_km_values
        else None
    )

    if litres > 120 or amount > 2500:
        return True
    if avg_price_per_litre and price_per_litre > avg_price_per_litre * 1.2:
        return True
    if avg_vehicle_cost_per_km and cost_per_km is not None and cost_per_km > avg_vehicle_cost_per_km * 1.5:
        return True

    station_logs = list(
        fuel_logs_collection().find({"status": "approved", "fuel_station_id": station_id})
    )
    station_average_amount = (
        sum(log.get("amount", 0) for log in station_logs) / len(station_logs)
        if station_logs
        else None
    )
    if station_average_amount and amount > station_average_amount * 1.5:
        return True
    return False


def _enrich_fuel_station(document: dict):
    return serialize_fuel_station(document)


def _enrich_fuel_log(document: dict):
    serialized = serialize_fuel_log(document)
    vehicle = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
    driver = users_collection().find_one({"_id": document.get("driver_id")})
    station = fuel_stations_collection().find_one({"_id": document.get("fuel_station_id")})
    assignment = (
        assignments_collection().find_one({"_id": document.get("assignment_id")})
        if document.get("assignment_id")
        else None
    )
    serialized["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
    serialized["driver"] = serialize_user(driver) if driver else None
    serialized["fuel_station"] = serialize_fuel_station(station) if station else None
    serialized["assignment"] = serialize_assignment(assignment) if assignment else None
    return serialized


def list_fuel_stations(current_role: str):
    query = {}
    if current_role == "driver":
        query["status"] = "active"
    stations = fuel_stations_collection().find(query).sort([("station_name", ASCENDING)])
    return [_enrich_fuel_station(station) for station in stations]


def create_fuel_station(payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to create fuel stations.", status_code=403)

    station_name = (payload.get("station_name") or "").strip()
    normalized_name = _normalize_station_name(station_name)
    existing = fuel_stations_collection().find_one({"normalized_name": normalized_name})
    if existing:
        raise ApiError("A fuel station with that name already exists.", status_code=409)

    timestamp = now_utc()
    document = {
        "station_name": station_name,
        "brand_name": (payload.get("brand_name") or "").strip() or None,
        "location": (payload.get("location") or "").strip() or None,
        "city": (payload.get("city") or "").strip() or None,
        "contact_number": (payload.get("contact_number") or "").strip() or None,
        "status": "active",
        "normalized_name": normalized_name,
        "created_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = fuel_stations_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _enrich_fuel_station(document)


def update_fuel_station(station_id: str, payload: dict, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update fuel stations.", status_code=403)

    document = _get_station_document(station_id)
    update_fields = {}

    if "station_name" in payload:
        station_name = (payload.get("station_name") or "").strip()
        normalized_name = _normalize_station_name(station_name)
        duplicate = fuel_stations_collection().find_one(
            {"normalized_name": normalized_name, "_id": {"$ne": document["_id"]}}
        )
        if duplicate:
            raise ApiError("A fuel station with that name already exists.", status_code=409)
        update_fields["station_name"] = station_name
        update_fields["normalized_name"] = normalized_name

    for field in ["brand_name", "location", "city", "contact_number"]:
        if field in payload:
            update_fields[field] = (payload.get(field) or "").strip() or None

    if not update_fields:
        raise ApiError("No valid fuel station fields provided for update.", status_code=400)

    update_fields["updated_at"] = now_utc()
    fuel_stations_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_fuel_station(document)


def update_fuel_station_status(station_id: str, status: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update fuel station status.", status_code=403)
    normalized_status = (status or "").strip().lower()
    if normalized_status not in ALLOWED_FUEL_STATION_STATUS:
        raise ApiError("status must be one of: active, inactive.", status_code=400)

    document = _get_station_document(station_id)
    update_fields = {"status": normalized_status, "updated_at": now_utc()}
    fuel_stations_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_fuel_station(document)


def _build_fuel_log_payload(payload: dict, current_user_id: str, current_role: str):
    if current_role == "driver":
        assignment = _resolve_driver_submission_context(current_user_id)
        vehicle_id = _to_object_id(assignment["vehicle_id"], "vehicle_id")
        driver_id = _to_object_id(assignment["driver_id"], "driver_id")
        assignment_id = _to_object_id(assignment["assignment_id"], "assignment_id")
    else:
        vehicle_id = _to_object_id(payload.get("vehicle_id"), "vehicle_id")
        driver_id = _to_object_id(payload.get("driver_id"), "driver_id", required=False)
        assignment_id = _to_object_id(payload.get("assignment_id"), "assignment_id", required=False)

    vehicle = _get_vehicle_document(vehicle_id)
    if driver_id is not None:
        _get_driver_document(driver_id)
    if assignment_id is not None:
        assignment_document = _get_assignment_document(assignment_id)
        if assignment_document.get("vehicle_id") != vehicle["_id"]:
            raise ApiError("assignment_id does not belong to the selected vehicle.", status_code=400)
        if driver_id is not None and assignment_document.get("driver_id") != driver_id:
            raise ApiError("assignment_id does not belong to the selected driver.", status_code=400)

    station = _get_station_document(payload.get("fuel_station_id"))
    if station.get("status") != "active":
        raise ApiError("Selected fuel station is inactive.", status_code=400)

    fuel_type = _validate_fuel_type(payload.get("fuel_type") or vehicle.get("fuel_type"))
    litres = _validate_positive_number(payload.get("litres"), "litres")
    amount = _validate_positive_number(payload.get("amount"), "amount")
    odometer_reading = _validate_positive_number(payload.get("odometer_reading"), "odometer_reading")
    fuel_date = _normalize_date(payload.get("fuel_date"), "fuel_date")
    price_per_litre = round(amount / litres, 4)
    previous_odometer, distance_since_last_fill, cost_per_km = _calculate_log_metrics(
        vehicle["_id"],
        fuel_date,
        odometer_reading,
        amount,
    )
    abnormal_spending = _calculate_abnormal_spending(
        vehicle["_id"],
        station["_id"],
        price_per_litre,
        amount,
        litres,
        cost_per_km,
    )

    return {
        "vehicle_id": vehicle["_id"],
        "driver_id": driver_id,
        "assignment_id": assignment_id,
        "fuel_station_id": station["_id"],
        "fuel_date": fuel_date,
        "fuel_type": fuel_type,
        "litres": litres,
        "amount": amount,
        "price_per_litre": price_per_litre,
        "odometer_reading": odometer_reading,
        "receipt_image": validate_file_reference(
            payload.get("receipt_image"),
            field_name="receipt_image",
            file_name="fuel-receipt",
        ),
        "notes": (payload.get("notes") or "").strip() or None,
        "status": "submitted",
        "submitted_by": _to_object_id(current_user_id, "current_user_id"),
        "approved_by": None,
        "rejected_by": None,
        "rejection_reason": None,
        "previous_odometer": previous_odometer,
        "distance_since_last_fill": distance_since_last_fill,
        "cost_per_km": cost_per_km,
        "abnormal_spending": abnormal_spending,
    }


def create_fuel_log(payload: dict, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to create fuel logs.", status_code=403)

    document = _build_fuel_log_payload(payload, current_user_id, current_role)
    timestamp = now_utc()
    document["created_at"] = timestamp
    document["updated_at"] = timestamp

    result = fuel_logs_collection().insert_one(document)
    document["_id"] = result.inserted_id

    notify_roles(
        ["owner", "admin"],
        title="New Fuel Log Submitted",
        message="A new fuel log has been submitted and is awaiting review.",
        category="fuel",
        priority="high" if document.get("abnormal_spending") else "medium",
        reference_type="fuel_log",
        reference_id=document["_id"],
    )
    return _enrich_fuel_log(document)


def _can_view_fuel_log(document: dict, current_user_id: str, current_role: str):
    if current_role in {"owner", "admin"}:
        return True
    if current_role == "driver":
        return str(document.get("submitted_by")) == current_user_id or str(document.get("driver_id")) == current_user_id
    return False


def _build_fuel_log_analytics(documents: list[dict]):
    approved_logs = [log for log in documents if log.get("status") == "approved"]
    total_fuel_spend = round(sum(log.get("amount", 0) for log in approved_logs), 2)
    total_litres = round(sum(log.get("litres", 0) for log in approved_logs), 2)
    average_price_per_litre = round(total_fuel_spend / total_litres, 4) if total_litres else 0

    station_totals = {}
    vehicle_totals = {}
    driver_totals = {}
    abnormal_logs = []

    for log in documents:
        if log.get("abnormal_spending"):
            abnormal_logs.append(_enrich_fuel_log(log))
        if log.get("status") != "approved":
            continue
        station = fuel_stations_collection().find_one({"_id": log.get("fuel_station_id")})
        vehicle = vehicles_collection().find_one({"_id": log.get("vehicle_id")})
        driver = users_collection().find_one({"_id": log.get("driver_id")}) if log.get("driver_id") else None

        station_label = station.get("station_name") if station else "Unknown Station"
        vehicle_label = vehicle.get("registration_number") if vehicle else "Unknown Vehicle"
        driver_label = driver.get("full_name") if driver else "Unassigned Driver"

        station_totals[station_label] = round(station_totals.get(station_label, 0) + log.get("amount", 0), 2)
        vehicle_totals[vehicle_label] = round(vehicle_totals.get(vehicle_label, 0) + log.get("amount", 0), 2)
        driver_totals[driver_label] = round(driver_totals.get(driver_label, 0) + log.get("amount", 0), 2)

    return {
        "total_fuel_spend": total_fuel_spend,
        "total_litres": total_litres,
        "average_price_per_litre": average_price_per_litre,
        "fuel_spend_by_station": [
            {"station_name": key, "total_amount": value}
            for key, value in sorted(station_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        "fuel_spend_by_vehicle": [
            {"vehicle_registration": key, "total_amount": value}
            for key, value in sorted(vehicle_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        "fuel_spend_by_driver": [
            {"driver_name": key, "total_amount": value}
            for key, value in sorted(driver_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        "abnormal_fuel_spending": abnormal_logs,
    }


def list_fuel_logs(current_user_id: str, current_role: str):
    query = {}
    if current_role == "driver":
        query["driver_id"] = _to_object_id(current_user_id, "current_user_id")
    documents = list(
        fuel_logs_collection()
        .find(query)
        .sort([("fuel_date", DESCENDING), ("created_at", DESCENDING)])
    )
    visible_documents = [
        document for document in documents if _can_view_fuel_log(document, current_user_id, current_role)
    ]
    return {
        "logs": [_enrich_fuel_log(document) for document in visible_documents],
        "analytics": _build_fuel_log_analytics(visible_documents),
    }


def get_fuel_log_by_id(log_id: str, current_user_id: str, current_role: str):
    document = _get_fuel_log_document(log_id)
    if not _can_view_fuel_log(document, current_user_id, current_role):
        raise ApiError("You do not have permission to view this fuel log.", status_code=403)
    return _enrich_fuel_log(document)


def approve_fuel_log(log_id: str, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to approve fuel logs.", status_code=403)

    document = _get_fuel_log_document(log_id)
    if document.get("status") == "approved":
        raise ApiError("Fuel log has already been approved.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "approved",
        "approved_by": _to_object_id(current_user_id, "current_user_id"),
        "rejected_by": None,
        "rejection_reason": None,
        "updated_at": timestamp,
    }
    fuel_logs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)

    vehicles_collection().update_one(
        {"_id": document["vehicle_id"]},
        {
            "$push": {
                "fuel_history": {
                    "fuel_log_id": document["_id"],
                    "fuel_date": document.get("fuel_date"),
                    "fuel_type": document.get("fuel_type"),
                    "litres": document.get("litres"),
                    "amount": document.get("amount"),
                    "price_per_litre": document.get("price_per_litre"),
                    "odometer_reading": document.get("odometer_reading"),
                    "fuel_station_id": document.get("fuel_station_id"),
                    "cost_per_km": document.get("cost_per_km"),
                }
            },
            "$set": {"updated_at": timestamp},
        },
    )

    submitted_by = document.get("submitted_by")
    if submitted_by:
        create_notification(
            recipient_user_id=submitted_by,
            title="Fuel Log Approved",
            message="Your fuel log was approved successfully.",
            category="fuel",
            priority="medium",
            reference_type="fuel_log",
            reference_id=document["_id"],
        )

    return _enrich_fuel_log(document)


def reject_fuel_log(log_id: str, rejection_reason: str, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to reject fuel logs.", status_code=403)

    normalized_reason = (rejection_reason or "").strip()
    if not normalized_reason:
        raise ApiError("rejection_reason is required.", status_code=400)

    document = _get_fuel_log_document(log_id)
    if document.get("status") == "approved":
        raise ApiError("Approved fuel logs cannot be rejected.", status_code=400)

    update_fields = {
        "status": "rejected",
        "rejected_by": _to_object_id(current_user_id, "current_user_id"),
        "approved_by": None,
        "rejection_reason": normalized_reason,
        "updated_at": now_utc(),
    }
    fuel_logs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)

    submitted_by = document.get("submitted_by")
    if submitted_by:
        create_notification(
            recipient_user_id=submitted_by,
            title="Fuel Log Rejected",
            message=f"Your fuel log was rejected: {normalized_reason}",
            category="fuel",
            priority="high",
            reference_type="fuel_log",
            reference_id=document["_id"],
        )

    return _enrich_fuel_log(document)
