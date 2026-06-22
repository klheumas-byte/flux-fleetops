from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING

from extensions import get_collection
from models.assignment import serialize_assignment
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.wallet_service import create_wallet_entry
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


ALLOWED_ASSIGNMENT_STATUSES = {"active", "ended", "suspended"}


def now_utc():
    return datetime.now(timezone.utc)


def assignments_collection():
    return get_collection("assignments")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def ensure_assignment_indexes():
    ensure_indexes_for_collection(
        assignments_collection(),
        [
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("start_date", ASCENDING)]},
            {"keys": [("created_at", ASCENDING)]},
            {"keys": [("updated_at", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", ASCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="assignments",
    )


def validate_positive_number(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value <= 0:
        raise ApiError(f"{field_name} must be a positive number.", status_code=400)
    return value


def get_assignment_document_by_id(assignment_id: str) -> dict:
    if not ObjectId.is_valid(assignment_id):
        raise ApiError("Assignment not found.", status_code=404)

    assignment = assignments_collection().find_one({"_id": ObjectId(assignment_id)})
    if not assignment:
        raise ApiError("Assignment not found.", status_code=404)
    return assignment


def get_driver_document(driver_id: str) -> dict:
    if not ObjectId.is_valid(driver_id):
        raise ApiError("Driver not found.", status_code=404)

    driver = users_collection().find_one({"_id": ObjectId(driver_id)})
    if not driver or driver.get("role") != "driver":
        raise ApiError("Driver not found.", status_code=404)
    return driver


def get_vehicle_document(vehicle_id: str) -> dict:
    if not ObjectId.is_valid(vehicle_id):
        raise ApiError("Vehicle not found.", status_code=404)

    vehicle = vehicles_collection().find_one({"_id": ObjectId(vehicle_id)})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def enrich_assignment(assignment_document: dict) -> dict:
    assignment = serialize_assignment(assignment_document)
    driver = users_collection().find_one({"_id": assignment_document["driver_id"]})
    vehicle = vehicles_collection().find_one({"_id": assignment_document["vehicle_id"]})

    assignment["driver"] = serialize_user(driver) if driver else None
    assignment["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
    return assignment


def list_assignments() -> list[dict]:
    assignments = assignments_collection().find({}).sort("created_at", ASCENDING)
    return [enrich_assignment(assignment) for assignment in assignments]


def get_assignment(assignment_id: str) -> dict:
    return enrich_assignment(get_assignment_document_by_id(assignment_id))


def get_active_assignment_for_driver(driver_user_id: str) -> dict | None:
    if not ObjectId.is_valid(driver_user_id):
        raise ApiError("Invalid user identity.", status_code=400)

    driver = users_collection().find_one({"_id": ObjectId(driver_user_id)})
    if not driver or driver.get("role") != "driver":
        raise ApiError("Driver not found.", status_code=404)

    assignment_document = assignments_collection().find_one(
        {
            "driver_id": driver["_id"],
            "status": "active",
        }
    )
    if not assignment_document:
        return None

    serialized_assignment = serialize_assignment(assignment_document)
    vehicle_document = vehicles_collection().find_one({"_id": assignment_document["vehicle_id"]})
    serialized_vehicle = serialize_vehicle(vehicle_document) if vehicle_document else None

    return {
        "assignment_id": serialized_assignment["id"],
        "driver_id": serialized_assignment["driver_id"],
        "vehicle_id": serialized_assignment["vehicle_id"],
        "weekly_target": serialized_assignment["weekly_target"] or 0,
        "daily_target": serialized_assignment["daily_target"] or 0,
        "start_date": serialized_assignment["start_date"],
        "status": serialized_assignment["status"],
        "vehicle": serialized_vehicle,
    }


def _validate_driver_for_assignment(driver: dict):
    driver_profile = dict(driver.get("driver_profile") or {})

    if driver.get("status") != "active":
        raise ApiError("Only active drivers can be assigned.", status_code=400)

    if driver_profile.get("approval_status") != "approved":
        raise ApiError("Driver must be approved before assignment.", status_code=400)

    if driver_profile.get("assigned_vehicle_id"):
        raise ApiError("Driver already has an active vehicle assignment.", status_code=409)

    existing_driver_assignment = assignments_collection().find_one(
        {"driver_id": driver["_id"], "status": {"$in": ["active", "suspended"]}}
    )
    if existing_driver_assignment:
        raise ApiError("Driver already has an active assignment.", status_code=409)

    return driver_profile


def _validate_vehicle_for_assignment(vehicle: dict):
    if vehicle.get("status") != "available":
        raise ApiError("Only available vehicles can be assigned.", status_code=400)

    if vehicle.get("assigned_driver_id"):
        raise ApiError("Vehicle is already assigned to a driver.", status_code=409)

    existing_vehicle_assignment = assignments_collection().find_one(
        {"vehicle_id": vehicle["_id"], "status": {"$in": ["active", "suspended"]}}
    )
    if existing_vehicle_assignment:
        raise ApiError("Vehicle already has an active assignment.", status_code=409)


def create_assignment(payload: dict, current_user_id: str) -> dict:
    if not ObjectId.is_valid(current_user_id):
        raise ApiError("Invalid user identity.", status_code=400)

    driver_id = payload.get("driver_id")
    vehicle_id = payload.get("vehicle_id")
    start_date = (payload.get("start_date") or "").strip()
    weekly_target = validate_positive_number(payload.get("weekly_target"), "weekly_target")
    daily_target = validate_positive_number(payload.get("daily_target"), "daily_target")

    if not driver_id:
        raise ApiError("driver_id is required.", status_code=400)
    if not vehicle_id:
        raise ApiError("vehicle_id is required.", status_code=400)
    if not start_date:
        raise ApiError("start_date is required.", status_code=400)

    driver = get_driver_document(driver_id)
    vehicle = get_vehicle_document(vehicle_id)

    driver_profile = _validate_driver_for_assignment(driver)
    _validate_vehicle_for_assignment(vehicle)

    timestamp = now_utc()
    assignment_document = {
        "driver_id": driver["_id"],
        "vehicle_id": vehicle["_id"],
        "weekly_target": weekly_target,
        "daily_target": daily_target,
        "start_date": start_date,
        "end_date": None,
        "status": "active",
        "assigned_by": ObjectId(current_user_id),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    insert_result = assignments_collection().insert_one(assignment_document)
    assignment_document["_id"] = insert_result.inserted_id

    vehicles_collection().update_one(
        {"_id": vehicle["_id"]},
        {
            "$set": {
                "assigned_driver_id": driver["_id"],
                "status": "assigned",
                "updated_at": timestamp,
            }
        },
    )

    driver_profile["assigned_vehicle_id"] = vehicle["_id"]
    users_collection().update_one(
        {"_id": driver["_id"]},
        {
            "$set": {
                "driver_profile": driver_profile,
                "updated_at": timestamp,
            }
        },
    )

    create_wallet_entry(
        driver_id=driver["_id"],
        vehicle_id=vehicle["_id"],
        assignment_id=assignment_document["_id"],
        entry_type="weekly_target",
        description="Weekly target obligation created",
        debit=weekly_target,
        credit=0,
        reference_id=assignment_document["_id"],
        created_by=current_user_id,
    )

    return enrich_assignment(assignment_document)


def update_assignment(assignment_id: str, payload: dict) -> dict:
    assignment = get_assignment_document_by_id(assignment_id)
    current_status = assignment.get("status")
    if current_status == "ended":
        raise ApiError("Ended assignments cannot be updated.", status_code=400)

    update_fields = {}

    if "weekly_target" in payload:
        update_fields["weekly_target"] = validate_positive_number(
            payload.get("weekly_target"), "weekly_target"
        )

    if "daily_target" in payload:
        update_fields["daily_target"] = validate_positive_number(
            payload.get("daily_target"), "daily_target"
        )

    if "start_date" in payload:
        start_date = (payload.get("start_date") or "").strip()
        if not start_date:
            raise ApiError("start_date cannot be empty.", status_code=400)
        update_fields["start_date"] = start_date

    if "end_date" in payload:
        end_date = payload.get("end_date")
        if end_date is not None and not str(end_date).strip():
            raise ApiError("end_date cannot be empty.", status_code=400)
        update_fields["end_date"] = str(end_date).strip() if end_date is not None else None

    if "status" in payload:
        next_status = (payload.get("status") or "").strip().lower()
        if next_status not in ALLOWED_ASSIGNMENT_STATUSES:
            raise ApiError(
                "status must be one of: active, ended, suspended.", status_code=400
            )
        if next_status == "ended":
            return end_assignment(assignment_id, payload.get("end_date"))
        update_fields["status"] = next_status

    if not update_fields:
        raise ApiError("No valid assignment fields provided for update.", status_code=400)

    timestamp = now_utc()
    update_fields["updated_at"] = timestamp

    assignments_collection().update_one(
        {"_id": assignment["_id"]},
        {"$set": update_fields},
    )
    assignment.update(update_fields)
    return enrich_assignment(assignment)


def end_assignment(assignment_id: str, end_date: str | None = None) -> dict:
    assignment = get_assignment_document_by_id(assignment_id)
    if assignment.get("status") == "ended":
        raise ApiError("Only active or suspended assignments can be ended.", status_code=400)

    timestamp = now_utc()
    normalized_end_date = str(end_date).strip() if end_date is not None else None
    assignments_collection().update_one(
        {"_id": assignment["_id"]},
        {
            "$set": {
                "status": "ended",
                "updated_at": timestamp,
                "end_date": normalized_end_date or timestamp.date().isoformat(),
            }
        },
    )
    assignment["status"] = "ended"
    assignment["updated_at"] = timestamp
    assignment["end_date"] = normalized_end_date or timestamp.date().isoformat()

    vehicle = vehicles_collection().find_one({"_id": assignment["vehicle_id"]})
    if vehicle:
        vehicles_collection().update_one(
            {"_id": vehicle["_id"]},
            {
                "$set": {
                    "assigned_driver_id": None,
                    "status": "available",
                    "updated_at": timestamp,
                }
            },
        )

    driver = users_collection().find_one({"_id": assignment["driver_id"]})
    if driver:
        driver_profile = dict(driver.get("driver_profile") or {})
        if driver_profile.get("assigned_vehicle_id") == assignment["vehicle_id"]:
            driver_profile["assigned_vehicle_id"] = None
        users_collection().update_one(
            {"_id": driver["_id"]},
            {
                "$set": {
                    "driver_profile": driver_profile,
                    "updated_at": timestamp,
                }
            },
        )

    return enrich_assignment(assignment)


def list_assignable_drivers() -> list[dict]:
    drivers = users_collection().find(
        {
            "role": "driver",
            "status": "active",
            "driver_profile.approval_status": "approved",
            "$or": [
                {"driver_profile.assigned_vehicle_id": None},
                {"driver_profile.assigned_vehicle_id": {"$exists": False}},
            ],
        }
    ).sort("full_name", ASCENDING)
    return [serialize_user(driver) for driver in drivers]


def list_assignable_vehicles() -> list[dict]:
    vehicles = vehicles_collection().find(
        {
            "status": "available",
            "$or": [
                {"assigned_driver_id": None},
                {"assigned_driver_id": {"$exists": False}},
            ],
        }
    ).sort("registration_number", ASCENDING)
    return [serialize_vehicle(vehicle) for vehicle in vehicles]
