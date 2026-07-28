from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.assignment import serialize_assignment
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.wallet_service import create_wallet_entry
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, set_ttl_cached


ALLOWED_ASSIGNMENT_STATUSES = {
    "pending_handover",
    "active",
    "pending_return",
    "ended",
    "suspended",
}
LIVE_ALLOCATION_STATUSES = {
    "pending_handover",
    "active",
    "pending_return",
    "suspended",
}
ALLOWED_OPERATING_MODES = {"operations_only", "target_only", "hybrid"}
ALLOWED_TARGET_FREQUENCIES = {"daily", "weekly"}


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
            {"keys": [("handover_status", ASCENDING), ("updated_at", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("linked_handover_movement_id", ASCENDING)], "options": {"sparse": True}},
            {
                "keys": [("vehicle_id", ASCENDING), ("allocation_active", ASCENDING)],
                "options": {
                    "name": "uniq_active_allocation_vehicle",
                    "unique": True,
                    "partialFilterExpression": {"allocation_active": True},
                },
            },
            {
                "keys": [("driver_id", ASCENDING), ("allocation_active", ASCENDING)],
                "options": {
                    "name": "uniq_active_allocation_driver",
                    "unique": True,
                    "partialFilterExpression": {"allocation_active": True},
                },
            },
            {"keys": [("expected_end_at", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("ended_by", ASCENDING), ("end_date", ASCENDING)], "options": {"sparse": True}},
        ],
        collection_name="assignments",
    )


def validate_positive_number(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value <= 0:
        raise ApiError(f"{field_name} must be a positive number.", status_code=400)
    return value


def _parse_optional_datetime(value, field_name: str):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise ApiError(f"{field_name} must be a valid ISO-8601 datetime.", status_code=400) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _normalize_allocation_configuration(payload: dict, driver_profile: dict) -> dict:
    operating_mode = str(
        payload.get("operating_mode") or driver_profile.get("operating_mode") or "hybrid"
    ).strip().lower()
    if operating_mode not in ALLOWED_OPERATING_MODES:
        raise ApiError(
            "operating_mode must be one of: operations_only, target_only, hybrid.",
            status_code=400,
        )

    target_enabled = payload.get(
        "target_enabled",
        driver_profile.get("target_enabled", True),
    )
    if not isinstance(target_enabled, bool):
        raise ApiError("target_enabled must be a boolean value.", status_code=400)
    if operating_mode == "operations_only" and target_enabled:
        raise ApiError(
            "operations_only drivers cannot have targets enabled.",
            status_code=400,
        )

    target_frequency = str(
        payload.get("target_frequency")
        or driver_profile.get("target_frequency")
        or "weekly"
    ).strip().lower()
    if target_frequency not in ALLOWED_TARGET_FREQUENCIES:
        raise ApiError("target_frequency must be daily or weekly.", status_code=400)

    target_amount = payload.get("target_amount", driver_profile.get("target_amount"))
    if target_enabled:
        if target_amount is None:
            target_amount = (
                payload.get("daily_target")
                if target_frequency == "daily"
                else payload.get("weekly_target")
            )
        target_amount = validate_positive_number(target_amount, "target_amount")
    elif target_amount is not None:
        if isinstance(target_amount, bool) or not isinstance(target_amount, (int, float)) or target_amount < 0:
            raise ApiError("target_amount must be a non-negative number.", status_code=400)

    weekly_target = payload.get("weekly_target")
    daily_target = payload.get("daily_target")
    if target_enabled:
        if target_frequency == "weekly":
            weekly_target = target_amount
            daily_target = (
                validate_positive_number(daily_target, "daily_target")
                if daily_target is not None
                else round(float(target_amount) / 7, 2)
            )
        else:
            daily_target = target_amount
            weekly_target = (
                validate_positive_number(weekly_target, "weekly_target")
                if weekly_target is not None
                else round(float(target_amount) * 7, 2)
            )
    else:
        weekly_target = 0
        daily_target = 0

    return {
        "operating_mode": operating_mode,
        "target_enabled": target_enabled,
        "target_amount": target_amount,
        "target_frequency": target_frequency,
        "weekly_target": weekly_target,
        "daily_target": daily_target,
    }


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
    assigned_by = users_collection().find_one({"_id": assignment_document.get("assigned_by") or assignment_document.get("created_by")})
    ended_by = users_collection().find_one({"_id": assignment_document.get("ended_by")}) if assignment_document.get("ended_by") else None

    assignment["driver"] = serialize_user(driver) if driver else None
    assignment["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
    assignment["assigned_by_user"] = {"full_name": assigned_by.get("full_name"), "role": assigned_by.get("role")} if assigned_by else None
    assignment["ended_by_user"] = {"full_name": ended_by.get("full_name"), "role": ended_by.get("role")} if ended_by else None
    return assignment


def _enrich_assignments(assignment_documents: list[dict]) -> list[dict]:
    if not assignment_documents:
        return []
    user_ids = {
        value
        for document in assignment_documents
        for value in (document.get("driver_id"), document.get("assigned_by") or document.get("created_by"), document.get("ended_by"))
        if isinstance(value, ObjectId)
    }
    vehicle_ids = {
        document.get("vehicle_id")
        for document in assignment_documents
        if isinstance(document.get("vehicle_id"), ObjectId)
    }
    user_map = {
        document["_id"]: document
        for document in users_collection().find({"_id": {"$in": list(user_ids)}})
    } if user_ids else {}
    vehicle_map = {
        document["_id"]: document
        for document in vehicles_collection().find({"_id": {"$in": list(vehicle_ids)}})
    } if vehicle_ids else {}
    enriched = []
    for document in assignment_documents:
        assignment = serialize_assignment(document)
        driver = user_map.get(document.get("driver_id"))
        vehicle = vehicle_map.get(document.get("vehicle_id"))
        assignment["driver"] = serialize_user(driver) if driver else None
        assignment["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
        assigned_by = user_map.get(document.get("assigned_by") or document.get("created_by"))
        ended_by = user_map.get(document.get("ended_by"))
        assignment["assigned_by_user"] = {"full_name": assigned_by.get("full_name"), "role": assigned_by.get("role")} if assigned_by else None
        assignment["ended_by_user"] = {"full_name": ended_by.get("full_name"), "role": ended_by.get("role")} if ended_by else None
        enriched.append(assignment)
    return enriched


def list_assignments() -> list[dict]:
    assignments = list(assignments_collection().find({}).sort("created_at", ASCENDING))
    return _enrich_assignments(assignments)


def get_assignment(assignment_id: str) -> dict:
    return enrich_assignment(get_assignment_document_by_id(assignment_id))


def get_active_assignment_for_driver(driver_user_id: str) -> dict | None:
    cache_key = build_cache_key("driver_active_assignment", driver_user_id=driver_user_id)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
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
        return set_ttl_cached(cache_key, None, ttl_seconds=15)

    serialized_assignment = serialize_assignment(assignment_document)
    vehicle_document = vehicles_collection().find_one({"_id": assignment_document["vehicle_id"]})
    serialized_vehicle = serialize_vehicle(vehicle_document) if vehicle_document else None

    return set_ttl_cached(
        cache_key,
        {
        "assignment_id": serialized_assignment["id"],
        "driver_id": serialized_assignment["driver_id"],
        "vehicle_id": serialized_assignment["vehicle_id"],
        "weekly_target": serialized_assignment["weekly_target"] or 0,
        "daily_target": serialized_assignment["daily_target"] or 0,
        "target_enabled": serialized_assignment["target_enabled"],
        "target_amount": serialized_assignment["target_amount"],
        "target_frequency": serialized_assignment["target_frequency"],
        "operating_mode": serialized_assignment["operating_mode"],
        "start_date": serialized_assignment["start_date"],
        "start_time": serialized_assignment["start_time"],
        "expected_end_at": serialized_assignment["expected_end_at"],
        "status": serialized_assignment["status"],
        "vehicle": serialized_vehicle,
    },
        ttl_seconds=15,
    )


def _validate_driver_for_assignment(driver: dict):
    driver_profile = dict(driver.get("driver_profile") or {})

    if driver.get("status") != "active":
        raise ApiError("Only active drivers can be assigned.", status_code=400)

    if driver_profile.get("approval_status") != "approved":
        raise ApiError("Driver must be approved before assignment.", status_code=400)

    existing_driver_assignment = assignments_collection().find_one(
        {
            "driver_id": driver["_id"],
            "$or": [
                {"allocation_active": True},
                {"allocation_active": {"$exists": False}, "status": {"$in": list(LIVE_ALLOCATION_STATUSES)}},
            ],
        }
    )
    if existing_driver_assignment:
        raise ApiError("Driver already has an active assignment.", status_code=409)

    return driver_profile


def _validate_vehicle_for_assignment(vehicle: dict):
    existing_vehicle_assignment = assignments_collection().find_one(
        {
            "vehicle_id": vehicle["_id"],
            "$or": [
                {"allocation_active": True},
                {"allocation_active": {"$exists": False}, "status": {"$in": list(LIVE_ALLOCATION_STATUSES)}},
            ],
        }
    )
    if existing_vehicle_assignment:
        raise ApiError("Vehicle already has an active assignment.", status_code=409)
    if vehicle.get("status") != "available":
        raise ApiError("Only available vehicles can be assigned.", status_code=400)


def _assignment_handover_source_id(assignment: dict, handover_kind: str) -> str:
    sequence = int(assignment.get("handover_sequence") or 1)
    return f"{assignment['_id']}:{sequence}:{handover_kind}"


def _ensure_assignment_handover_movement(
    assignment: dict,
    *,
    current_user_id: str | ObjectId,
    handover_kind: str,
) -> dict:
    from services.movement_custody_service import transfer_movement_custody
    from services.movement_source_service import ensure_movement_for_source

    if handover_kind not in {"initial", "return"}:
        raise ApiError("Unsupported assignment handover kind.", status_code=400)
    actor_id = (
        current_user_id
        if isinstance(current_user_id, ObjectId)
        else ObjectId(str(current_user_id))
        if ObjectId.is_valid(str(current_user_id))
        else None
    )
    if actor_id is None:
        raise ApiError("Invalid user identity.", status_code=400)
    vehicle = vehicles_collection().find_one(
        {"_id": assignment["vehicle_id"]},
        {"assigned_driver_id": 1, "current_custodian_id": 1, "registration_number": 1},
    )
    if not vehicle:
        raise ApiError("Assignment vehicle not found.", status_code=404)
    previous_custodian_id = (
        assignment.get("previous_custodian_id")
        if handover_kind == "initial"
        else vehicle.get("current_custodian_id") or assignment.get("driver_id")
    )
    target_driver_id = assignment.get("driver_id") if handover_kind == "initial" else None
    timestamp = now_utc()
    source_record_id = _assignment_handover_source_id(assignment, handover_kind)
    result = ensure_movement_for_source(
        source_type="assignment_handover",
        source_record_id=source_record_id,
        source_reference=f"{assignment['_id']}:{handover_kind}",
        movement_defaults={
            "vehicle_id": assignment["vehicle_id"],
            "driver_id": target_driver_id or assignment.get("driver_id"),
            "movement_custodian_id": previous_custodian_id,
            "permanent_driver_id": vehicle.get("assigned_driver_id"),
            "assignment_id": assignment["_id"],
            "primary_assignment_id": assignment["_id"],
            "movement_type": "assignment_handover",
            "handover_kind": handover_kind,
            "handover_sequence": int(assignment.get("handover_sequence") or 1),
            "previous_custodian_id": previous_custodian_id,
            "next_custodian_id": target_driver_id,
            "status": "approved",
            "origin": "Company custody" if handover_kind == "initial" else None,
            "destination": "Assigned driver" if handover_kind == "initial" else "Company custody",
            "purpose": f"Assignment {handover_kind} custody handover",
            "opening_odometer": None,
            "closing_odometer": None,
            "opening_fuel_level": None,
            "closing_fuel_level": None,
            "custody_state": "pending_acceptance",
            "custody_events": [],
            "custody_version": 0,
            "approved_by": actor_id,
            "approved_at": timestamp,
            "created_by": actor_id,
            "created_at": timestamp,
        },
        legacy_query={
            "assignment_id": assignment["_id"],
            "movement_type": "assignment_handover",
            "handover_kind": handover_kind,
            "handover_sequence": int(assignment.get("handover_sequence") or 1),
        },
    )
    movement = result["movement"]
    if assignment.get("linked_handover_movement_id") != movement["_id"]:
        assignments_collection().update_one(
            {"_id": assignment["_id"]},
            {
                "$set": {
                    "linked_handover_movement_id": movement["_id"],
                    "updated_at": now_utc(),
                }
            },
        )
        assignment["linked_handover_movement_id"] = movement["_id"]
    transfer_payload = {
        "to_user_id": target_driver_id,
        "to_location": "Company custody" if handover_kind == "return" else None,
        "event_type": "assignment_handover" if handover_kind == "initial" else "custody_return",
        "from_user_id": previous_custodian_id,
        "source_type": "assignment_handover",
        "source_id": source_record_id,
        "audit_reason": "Assignment handover initiated by an authorized administrator.",
    }
    transfer_movement_custody(
        movement["_id"],
        transfer_payload,
        current_user_id=str(actor_id),
        current_role="admin",
        source_event_key=f"assignment:{source_record_id}:release",
    )
    return movement


def _activate_assignment_after_handover(
    assignment: dict,
    *,
    accepted_by: ObjectId,
) -> dict:
    timestamp = now_utc()
    driver = users_collection().find_one({"_id": assignment["driver_id"]})
    vehicle = vehicles_collection().find_one({"_id": assignment["vehicle_id"]})
    if not driver or not vehicle:
        raise ApiError("Assignment driver or vehicle no longer exists.", status_code=409)
    assignments_collection().update_one(
        {"_id": assignment["_id"], "status": "pending_handover"},
        {
            "$set": {
                "status": "active",
                "handover_status": "accepted",
                "handover_accepted_at": timestamp,
                "handover_accepted_by": accepted_by,
                "updated_at": timestamp,
            }
        },
    )
    assignment.update(
        {
            "status": "active",
            "handover_status": "accepted",
            "handover_accepted_at": timestamp,
            "handover_accepted_by": accepted_by,
            "updated_at": timestamp,
        }
    )
    vehicles_collection().update_one(
        {"_id": vehicle["_id"]},
        {
            "$set": {
                "assigned_driver_id": driver["_id"],
                "current_custodian_id": driver["_id"],
                "status": "assigned",
                "updated_at": timestamp,
            },
            "$unset": {"pending_assignment_id": ""},
        },
    )
    driver_profile = dict(driver.get("driver_profile") or {})
    driver_profile["assigned_vehicle_id"] = vehicle["_id"]
    users_collection().update_one(
        {"_id": driver["_id"]},
        {"$set": {"driver_profile": driver_profile, "updated_at": timestamp}},
    )
    existing_target = get_collection("wallet_entries").find_one(
        {
            "assignment_id": assignment["_id"],
            "type": "weekly_target",
            "reference_id": assignment["_id"],
        },
        {"_id": 1},
    )
    if assignment.get("target_enabled", True) and not existing_target:
        create_wallet_entry(
            driver_id=driver["_id"],
            vehicle_id=vehicle["_id"],
            assignment_id=assignment["_id"],
            entry_type="weekly_target",
            description="Weekly target obligation created",
            debit=assignment["weekly_target"],
            credit=0,
            reference_id=assignment["_id"],
            created_by=accepted_by,
        )
    return assignment


def accept_assignment_handover(
    assignment_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    from services.movement_custody_service import accept_movement_custody

    assignment = get_assignment_document_by_id(assignment_id)
    actor_id = ObjectId(current_user_id) if ObjectId.is_valid(current_user_id) else None
    if actor_id is None:
        raise ApiError("Invalid user identity.", status_code=400)
    if current_role == "driver" and actor_id != assignment.get("driver_id"):
        raise ApiError("You cannot accept another driver's assignment handover.", status_code=403)
    if assignment.get("status") == "active" and assignment.get("handover_status") == "accepted":
        return enrich_assignment(
            _activate_assignment_after_handover(assignment, accepted_by=actor_id)
        )
    if assignment.get("status") != "pending_handover":
        raise ApiError("This assignment is not awaiting handover acceptance.", status_code=400)
    movement_id = assignment.get("linked_handover_movement_id")
    if not isinstance(movement_id, ObjectId):
        movement = _ensure_assignment_handover_movement(
            assignment,
            current_user_id=assignment.get("assigned_by") or actor_id,
            handover_kind="initial",
        )
        movement_id = movement["_id"]
    source_id = _assignment_handover_source_id(assignment, "initial")
    custody_result = accept_movement_custody(
        movement_id,
        {
            **(payload or {}),
            "event_type": "accepted_by_driver",
            "to_user_id": assignment["driver_id"],
            "source_type": "assignment_handover",
            "source_id": source_id,
        },
        current_user_id=current_user_id,
        current_role=current_role,
        source_event_key=f"assignment:{source_id}:accepted",
    )
    timestamp = now_utc()
    get_collection("vehicle_movements").update_one(
        {"_id": movement_id},
        {
            "$set": {
                "status": "closed",
                "checked_out_by": actor_id,
                "checked_out_at": timestamp,
                "returned_by": actor_id,
                "returned_at": timestamp,
                "closed_by": actor_id,
                "closed_at": timestamp,
                "physical_completion_status": "verified",
                "opening_odometer": custody_result["event"].get("odometer"),
                "opening_fuel_level": custody_result["event"].get("fuel_level"),
                "opening_condition_summary": custody_result["event"].get("condition_summary"),
                "updated_at": timestamp,
            }
        },
    )
    return enrich_assignment(_activate_assignment_after_handover(assignment, accepted_by=actor_id))


def list_driver_assignment_handovers(current_user_id: str) -> list[dict]:
    if not ObjectId.is_valid(current_user_id):
        raise ApiError("Invalid user identity.", status_code=400)
    documents = list(
        assignments_collection().find(
            {
                "driver_id": ObjectId(current_user_id),
                "status": {"$in": ["pending_handover", "pending_return"]},
            }
        ).sort("updated_at", ASCENDING)
    )
    return _enrich_assignments(documents)


def create_assignment(payload: dict, current_user_id: str) -> dict:
    if not ObjectId.is_valid(current_user_id):
        raise ApiError("Invalid user identity.", status_code=400)

    driver_id = payload.get("driver_id")
    vehicle_id = payload.get("vehicle_id")
    start_date = str(payload.get("start_date") or "").strip()

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
    configuration = _normalize_allocation_configuration(payload, driver_profile)

    timestamp = now_utc()
    start_time = _parse_optional_datetime(payload.get("start_time"), "start_time") or timestamp
    expected_end_at = _parse_optional_datetime(payload.get("expected_end_at"), "expected_end_at")
    if expected_end_at and expected_end_at <= start_time:
        raise ApiError("expected_end_at must be after start_time.", status_code=400)
    assignment_reason = str(payload.get("reason") or payload.get("assignment_reason") or "").strip()
    if not assignment_reason:
        raise ApiError("reason is required.", status_code=400)
    assignment_document = {
        "driver_id": driver["_id"],
        "vehicle_id": vehicle["_id"],
        **configuration,
        "start_date": start_date,
        "start_time": start_time,
        "expected_end_at": expected_end_at,
        "end_date": None,
        "status": "pending_handover",
        "allocation_active": True,
        "handover_status": "awaiting_driver_acceptance",
        "handover_sequence": 1,
        "linked_handover_movement_id": None,
        "previous_custodian_id": vehicle.get("current_custodian_id") or vehicle.get("assigned_driver_id"),
        "handover_accepted_at": None,
        "assigned_by": ObjectId(current_user_id),
        "assignment_reason": assignment_reason,
        "transferred_from_allocation_id": (
            ObjectId(payload["transferred_from_allocation_id"])
            if ObjectId.is_valid(str(payload.get("transferred_from_allocation_id")))
            else None
        ),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        insert_result = assignments_collection().insert_one(assignment_document)
    except DuplicateKeyError:
        raise ApiError(
            "The driver or vehicle already has an active allocation. Refresh and try again.",
            status_code=409,
        ) from None
    assignment_document["_id"] = insert_result.inserted_id

    try:
        movement = _ensure_assignment_handover_movement(
            assignment_document,
            current_user_id=current_user_id,
            handover_kind="initial",
        )
    except Exception:
        # Compensate only the just-created pending record. No driver, vehicle,
        # wallet, or target state has been activated at this point.
        assignments_collection().delete_one({"_id": assignment_document["_id"]})
        raise
    assignment_document["linked_handover_movement_id"] = movement["_id"]

    vehicle_lock = vehicles_collection().update_one(
        {
            "_id": vehicle["_id"],
            "status": "available",
            "$or": [
                {"pending_assignment_id": {"$exists": False}},
                {"pending_assignment_id": None},
            ],
        },
        {
            "$set": {
                "status": "assigned",
                "pending_assignment_id": assignment_document["_id"],
                "updated_at": timestamp,
            }
        },
    )
    if vehicle_lock.modified_count != 1:
        assignments_collection().delete_one({"_id": assignment_document["_id"]})
        raise ApiError(
            "Vehicle allocation conflict. The vehicle was allocated by another request.",
            status_code=409,
        )

    profile_updates = {
        "driver_profile.operating_mode": configuration["operating_mode"],
        "driver_profile.target_enabled": configuration["target_enabled"],
        "driver_profile.target_amount": configuration["target_amount"],
        "driver_profile.target_frequency": configuration["target_frequency"],
        "updated_at": timestamp,
    }
    users_collection().update_one({"_id": driver["_id"]}, {"$set": profile_updates})

    return enrich_assignment(assignment_document)


def update_assignment(
    assignment_id: str,
    payload: dict,
    *,
    current_user_id: str | None = None,
    current_role: str = "admin",
) -> dict:
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
            return end_assignment(
                assignment_id,
                payload.get("end_date"),
                current_user_id=current_user_id,
                current_role=current_role,
            )
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


def _finalize_assignment_end(
    assignment: dict,
    end_date: str | None = None,
    *,
    ended_by: ObjectId | None = None,
    end_reason: str | None = None,
) -> dict:
    timestamp = now_utc()
    normalized_end_date = str(end_date).strip() if end_date is not None else None
    assignments_collection().update_one(
        {"_id": assignment["_id"]},
        {
            "$set": {
                "status": "ended",
                "handover_status": (
                    "returned_to_company"
                    if assignment.get("handover_status") != "handover_not_recorded"
                    else "handover_not_recorded"
                ),
                "updated_at": timestamp,
                "end_date": normalized_end_date or timestamp.date().isoformat(),
                "ended_at": timestamp,
                "ended_by": ended_by,
                "end_reason": end_reason,
                "allocation_active": False,
            }
        },
    )
    assignment["status"] = "ended"
    assignment["handover_status"] = (
        "returned_to_company"
        if assignment.get("handover_status") != "handover_not_recorded"
        else "handover_not_recorded"
    )
    assignment["updated_at"] = timestamp
    assignment["end_date"] = normalized_end_date or timestamp.date().isoformat()
    assignment["ended_at"] = timestamp
    assignment["ended_by"] = ended_by
    assignment["end_reason"] = end_reason
    assignment["allocation_active"] = False

    vehicle = vehicles_collection().find_one({"_id": assignment["vehicle_id"]})
    if vehicle:
        vehicles_collection().update_one(
            {
                "_id": vehicle["_id"],
                "$or": [
                    {"assigned_driver_id": assignment["driver_id"]},
                    {"pending_assignment_id": assignment["_id"]},
                ],
            },
            {
                "$set": {
                    "assigned_driver_id": None,
                    "current_custodian_id": None,
                    "current_custody_location": "Company custody",
                    "status": "available",
                    "updated_at": timestamp,
                },
                "$unset": {"pending_assignment_id": ""},
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
    return assignment


def end_assignment(
    assignment_id: str,
    end_date: str | None = None,
    *,
    current_user_id: str | None = None,
    current_role: str = "admin",
    end_reason: str | None = None,
) -> dict:
    assignment = get_assignment_document_by_id(assignment_id)
    if assignment.get("status") == "ended":
        return enrich_assignment(assignment)
    actor_id = (
        ObjectId(str(current_user_id))
        if current_user_id and ObjectId.is_valid(str(current_user_id))
        else None
    )
    # Legacy active assignments have no handover metadata. Preserve their
    # historical immediate-end behavior rather than retroactively blocking
    # them on a custody workflow that never existed.
    if not assignment.get("handover_status"):
        assignment["handover_status"] = "handover_not_recorded"
        return enrich_assignment(
            _finalize_assignment_end(
                assignment,
                end_date,
                ended_by=actor_id,
                end_reason=str(end_reason or "Allocation unassigned").strip(),
            )
        )
    if assignment.get("status") == "pending_handover":
        return enrich_assignment(
            _finalize_assignment_end(
                assignment,
                end_date,
                ended_by=actor_id,
                end_reason=str(end_reason or "Pending allocation cancelled").strip(),
            )
        )
    if assignment.get("status") == "pending_return":
        return enrich_assignment(assignment)
    if assignment.get("status") not in {"active", "suspended"}:
        raise ApiError("Only active or suspended assignments can begin return handover.", status_code=400)
    actor = current_user_id or assignment.get("assigned_by")
    if not actor or not ObjectId.is_valid(str(actor)):
        raise ApiError("An authorized actor is required to begin assignment return.", status_code=400)
    timestamp = now_utc()
    next_sequence = int(assignment.get("handover_sequence") or 1) + 1
    updates = {
        "status": "pending_return",
        "handover_status": "awaiting_vehicle_return",
        "handover_sequence": next_sequence,
        "requested_end_date": str(end_date).strip() if end_date else None,
        "requested_end_reason": str(end_reason or "Allocation unassigned").strip(),
        "end_requested_by": actor_id,
        "updated_at": timestamp,
    }
    assignments_collection().update_one({"_id": assignment["_id"]}, {"$set": updates})
    assignment.update(updates)
    movement = _ensure_assignment_handover_movement(
        assignment,
        current_user_id=actor,
        handover_kind="return",
    )
    assignment["linked_handover_movement_id"] = movement["_id"]
    return enrich_assignment(assignment)


def transfer_assignment(
    assignment_id: str,
    payload: dict,
    *,
    current_user_id: str,
) -> dict:
    if not ObjectId.is_valid(str(current_user_id)):
        raise ApiError("Invalid user identity.", status_code=400)
    assignment = get_assignment_document_by_id(assignment_id)
    if assignment.get("status") not in {"active", "suspended"}:
        raise ApiError("Only active or suspended allocations can be transferred.", status_code=400)
    next_driver_id = payload.get("driver_id")
    if not next_driver_id:
        raise ApiError("driver_id is required.", status_code=400)
    next_driver = get_driver_document(next_driver_id)
    if next_driver["_id"] == assignment.get("driver_id"):
        raise ApiError("Select a different driver for transfer.", status_code=400)
    next_profile = _validate_driver_for_assignment(next_driver)
    configuration = _normalize_allocation_configuration(payload, next_profile)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ApiError("reason is required.", status_code=400)

    timestamp = now_utc()
    actor_id = ObjectId(str(current_user_id))
    expected_end_at = _parse_optional_datetime(payload.get("expected_end_at"), "expected_end_at")
    new_document = {
        "driver_id": next_driver["_id"],
        "vehicle_id": assignment["vehicle_id"],
        **configuration,
        "start_date": str(payload.get("start_date") or timestamp.date().isoformat()),
        "start_time": timestamp,
        "expected_end_at": expected_end_at,
        "end_date": None,
        "status": "active",
        "allocation_active": True,
        "handover_status": "transferred",
        "handover_sequence": int(assignment.get("handover_sequence") or 1) + 1,
        "assigned_by": actor_id,
        "assignment_reason": reason,
        "transferred_from_allocation_id": assignment["_id"],
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    released = assignments_collection().update_one(
        {
            "_id": assignment["_id"],
            "status": {"$in": ["active", "suspended"]},
            "$or": [
                {"allocation_active": True},
                {"allocation_active": {"$exists": False}},
            ],
        },
        {
            "$set": {
                "status": "ended",
                "allocation_active": False,
                "end_date": timestamp.date().isoformat(),
                "ended_at": timestamp,
                "ended_by": actor_id,
                "end_reason": reason,
                "handover_status": "transferred",
                "updated_at": timestamp,
            }
        },
    )
    if released.modified_count != 1:
        raise ApiError("Allocation changed before the transfer could complete.", status_code=409)

    try:
        result = assignments_collection().insert_one(new_document)
        new_document["_id"] = result.inserted_id
    except Exception as error:
        assignments_collection().update_one(
            {"_id": assignment["_id"], "allocation_active": False, "status": "ended"},
            {
                "$set": {
                    "status": assignment.get("status"),
                    "allocation_active": True,
                    "end_date": assignment.get("end_date"),
                    "handover_status": assignment.get("handover_status"),
                    "updated_at": now_utc(),
                },
                "$unset": {"ended_at": "", "ended_by": "", "end_reason": ""},
            },
        )
        if isinstance(error, DuplicateKeyError):
            raise ApiError(
                "The selected driver already has an active allocation.",
                status_code=409,
            ) from None
        raise

    assignments_collection().update_one(
        {"_id": assignment["_id"]},
        {"$set": {"transferred_to_allocation_id": new_document["_id"]}},
    )
    vehicle_transfer = vehicles_collection().update_one(
        {
            "_id": assignment["vehicle_id"],
            "assigned_driver_id": assignment["driver_id"],
        },
        {
            "$set": {
                "assigned_driver_id": next_driver["_id"],
                "current_custodian_id": next_driver["_id"],
                "status": "assigned",
                "updated_at": timestamp,
            },
            "$unset": {"pending_assignment_id": ""},
        },
    )
    if vehicle_transfer.modified_count != 1:
        assignments_collection().delete_one({"_id": new_document["_id"]})
        assignments_collection().update_one(
            {"_id": assignment["_id"], "transferred_to_allocation_id": new_document["_id"]},
            {
                "$set": {
                    "status": assignment.get("status"),
                    "allocation_active": True,
                    "end_date": assignment.get("end_date"),
                    "handover_status": assignment.get("handover_status"),
                    "updated_at": now_utc(),
                },
                "$unset": {
                    "ended_at": "",
                    "ended_by": "",
                    "end_reason": "",
                    "transferred_to_allocation_id": "",
                },
            },
        )
        raise ApiError(
            "Vehicle custody changed before the transfer could complete.",
            status_code=409,
        )
    users_collection().update_one(
        {"_id": assignment["driver_id"], "driver_profile.assigned_vehicle_id": assignment["vehicle_id"]},
        {"$set": {"driver_profile.assigned_vehicle_id": None, "updated_at": timestamp}},
    )
    users_collection().update_one(
        {"_id": next_driver["_id"]},
        {
            "$set": {
                "driver_profile.assigned_vehicle_id": assignment["vehicle_id"],
                "driver_profile.operating_mode": configuration["operating_mode"],
                "driver_profile.target_enabled": configuration["target_enabled"],
                "driver_profile.target_amount": configuration["target_amount"],
                "driver_profile.target_frequency": configuration["target_frequency"],
                "updated_at": timestamp,
            }
        },
    )
    if configuration["target_enabled"]:
        create_wallet_entry(
            driver_id=next_driver["_id"],
            vehicle_id=assignment["vehicle_id"],
            assignment_id=new_document["_id"],
            entry_type="weekly_target",
            description="Target obligation created after allocation transfer",
            debit=new_document["weekly_target"],
            credit=0,
            reference_id=new_document["_id"],
            created_by=actor_id,
        )
    return enrich_assignment(new_document)


def complete_assignment_return(
    assignment_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    from services.movement_custody_service import return_movement_custody

    assignment = get_assignment_document_by_id(assignment_id)
    if assignment.get("status") == "ended":
        return enrich_assignment(assignment)
    if assignment.get("status") != "pending_return":
        raise ApiError("This assignment is not awaiting vehicle return.", status_code=400)
    actor_id = ObjectId(current_user_id) if ObjectId.is_valid(current_user_id) else None
    if actor_id is None:
        raise ApiError("Invalid user identity.", status_code=400)
    if current_role == "driver" and actor_id != assignment.get("driver_id"):
        raise ApiError("You cannot return another driver's assigned vehicle.", status_code=403)
    movement_id = assignment.get("linked_handover_movement_id")
    if not isinstance(movement_id, ObjectId):
        raise ApiError("Assignment return movement is missing.", status_code=409)
    source_id = _assignment_handover_source_id(assignment, "return")
    result = return_movement_custody(
        movement_id,
        {
            **(payload or {}),
            "event_type": "custody_return",
            "to_location": "Company custody",
            "source_type": "assignment_handover",
            "source_id": source_id,
        },
        current_user_id=current_user_id,
        current_role=current_role,
        source_event_key=f"assignment:{source_id}:returned",
    )
    timestamp = now_utc()
    get_collection("vehicle_movements").update_one(
        {"_id": movement_id},
        {
            "$set": {
                "status": "closed",
                "returned_by": actor_id,
                "returned_at": timestamp,
                "actual_return_time": timestamp,
                "closed_by": actor_id,
                "closed_at": timestamp,
                "physical_completion_status": "verified",
                "closing_odometer": result["event"].get("odometer"),
                "closing_fuel_level": result["event"].get("fuel_level"),
                "updated_at": timestamp,
            }
        },
    )
    return enrich_assignment(
        _finalize_assignment_end(
            assignment,
            assignment.get("requested_end_date"),
            ended_by=actor_id,
            end_reason=assignment.get("requested_end_reason") or "Vehicle returned",
        )
    )


def list_assignable_drivers() -> list[dict]:
    blocked_driver_ids = [
        document["driver_id"]
        for document in assignments_collection().find(
            {
                "status": {
                    "$in": [
                        "pending_handover",
                        "active",
                        "pending_return",
                        "suspended",
                    ]
                }
            },
            {"driver_id": 1},
        )
        if isinstance(document.get("driver_id"), ObjectId)
    ]
    drivers = users_collection().find(
        {
            "_id": {"$nin": blocked_driver_ids},
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
