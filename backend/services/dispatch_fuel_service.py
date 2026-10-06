from __future__ import annotations

from datetime import datetime, timezone
from bson import ObjectId

from extensions import get_collection
from models.vehicle_movement import serialize_vehicle_movement
from utils.api_error import ApiError
from utils.file_validation import validate_file_reference
from utils.fuel_levels import (
    build_fuel_level_details,
    is_valid_dispatch_fuel_level,
    normalize_fuel_level_eighths,
)


FUEL_READING_FIELDS = {
    "opening_fuel_level",
    "opening_odometer",
    "closing_fuel_level",
    "closing_odometer",
}
AUTHORIZED_FUEL_ROLES = {"owner", "admin", "dispatcher"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def dispatch_jobs_collection():
    return get_collection("dispatch_jobs")


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def vehicles_collection():
    return get_collection("vehicles")


def fuel_logs_collection():
    return get_collection("fuel_logs")


def _to_object_id(value, field_name: str) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _get_job(job_id: str | ObjectId) -> dict:
    query = {"_id": job_id} if isinstance(job_id, ObjectId) else (
        {"_id": ObjectId(job_id)} if ObjectId.is_valid(str(job_id)) else {"dispatch_job_id": str(job_id)}
    )
    document = dispatch_jobs_collection().find_one(query)
    if not document:
        raise ApiError("Dispatch job not found.", status_code=404)
    return document


def _assert_access(job: dict, *, current_user_id: str, current_role: str):
    role = str(current_role or "").strip().lower()
    if role in AUTHORIZED_FUEL_ROLES:
        return
    if role == "driver" and str(job.get("driver_id")) == str(current_user_id):
        return
    raise ApiError("You do not have permission to manage fuel for this dispatch.", status_code=403)


def _validate_non_negative_number(value, field_name: str, *, required: bool = True) -> float | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _validate_required_fuel_level(value, field_name: str) -> int:
    if value in (None, ""):
        raise ApiError(f"{field_name} is required.", status_code=400)
    if not is_valid_dispatch_fuel_level(value):
        raise ApiError(f"{field_name} must be E, 1/8 through 7/8, or F.", status_code=400)
    normalized, warning = normalize_fuel_level_eighths(value)
    if normalized is None:
        raise ApiError(warning or f"{field_name} must be E, 1/8 through 7/8, or F.", status_code=400)
    return normalized


def _find_movement(job: dict) -> dict | None:
    linked_id = job.get("linked_vehicle_movement_id")
    if isinstance(linked_id, ObjectId):
        movement = vehicle_movements_collection().find_one({"_id": linked_id})
        if movement:
            return movement
    return vehicle_movements_collection().find_one({"dispatch_job_id": job["_id"]})


def _ensure_predeparture_movement(job: dict, *, current_user_id: str) -> dict:
    from services.movement_source_service import ensure_dispatch_movement

    result = ensure_dispatch_movement(
        job,
        current_user_id=current_user_id,
        initial_status="approved",
    )
    return result["movement"]


def list_dispatch_fuel_logs(dispatch_job_id: ObjectId) -> list[dict]:
    return list(
        fuel_logs_collection()
        .find({"dispatch_job_id": dispatch_job_id, "status": {"$ne": "rejected"}})
        .sort([("fuel_date", 1), ("created_at", 1)])
    )


def build_dispatch_fuel_summary(
    movement: dict | None,
    *,
    vehicle: dict | None = None,
    fuel_logs: list[dict] | None = None,
) -> dict:
    movement = movement or {}
    vehicle = vehicle or {}
    fuel_logs = fuel_logs or []
    approved_logs = [item for item in fuel_logs if item.get("status") in {"approved", "recorded"}]
    pending_logs = [
        item
        for item in fuel_logs
        if item.get("status") not in {"approved", "recorded", "rejected"}
    ]
    opening_level = movement.get("opening_fuel_level")
    closing_level = movement.get("closing_fuel_level")
    opening_odometer = movement.get("opening_odometer")
    closing_odometer = movement.get("closing_odometer")
    tank_capacity = vehicle.get("tank_capacity_litres")
    opening_details = build_fuel_level_details(opening_level, tank_capacity_litres=tank_capacity)
    closing_details = build_fuel_level_details(closing_level, tank_capacity_litres=tank_capacity)
    total_litres = round(sum(float(item.get("litres") or 0) for item in approved_logs), 2)
    total_cost = round(sum(float(item.get("amount") or 0) for item in approved_logs), 2)
    pending_litres = round(sum(float(item.get("litres") or 0) for item in pending_logs), 2)
    pending_cost = round(sum(float(item.get("amount") or 0) for item in pending_logs), 2)
    distance = None
    if opening_odometer is not None and closing_odometer is not None:
        distance = round(float(closing_odometer) - float(opening_odometer), 2)
    estimated_consumed = None
    if (
        opening_details
        and closing_details
        and opening_details.get("estimated_litres") is not None
        and closing_details.get("estimated_litres") is not None
    ):
        estimated_consumed = round(
            opening_details["estimated_litres"] + total_litres - closing_details["estimated_litres"],
            2,
        )
    estimated_efficiency = (
        round(distance / estimated_consumed, 2)
        if distance is not None and estimated_consumed is not None and estimated_consumed > 0
        else None
    )
    if movement.get("fuel_summary_status") in {"complete", "legacy_exception"}:
        status = movement.get("fuel_summary_status")
    elif movement.get("closing_fuel_recorded_at"):
        status = "closing_confirmed"
    elif movement.get("opening_fuel_recorded_at"):
        status = "opening_confirmed"
    elif movement:
        status = "opening_missing"
    else:
        status = "not_started"
    def serialize_reference(value):
        return str(value) if isinstance(value, ObjectId) else value

    def serialize_datetime(value):
        return value.isoformat() if isinstance(value, datetime) else value

    correction_audit = []
    for item in movement.get("fuel_correction_audit") or []:
        correction_audit.append(
            {
                **item,
                "changed_by": serialize_reference(item.get("changed_by")),
                "changed_at": serialize_datetime(item.get("changed_at")),
            }
        )
    return {
        "opening_fuel_level": opening_level,
        "opening_fuel_details": opening_details,
        "opening_fuel_recorded_at": serialize_datetime(movement.get("opening_fuel_recorded_at")),
        "opening_fuel_recorded_by": serialize_reference(movement.get("opening_fuel_recorded_by")),
        "opening_fuel_photo": movement.get("opening_fuel_photo"),
        "opening_inspection_note": movement.get("opening_inspection_note"),
        "opening_odometer": opening_odometer,
        "closing_fuel_level": closing_level,
        "closing_fuel_details": closing_details,
        "closing_fuel_recorded_at": serialize_datetime(movement.get("closing_fuel_recorded_at")),
        "closing_fuel_recorded_by": serialize_reference(movement.get("closing_fuel_recorded_by")),
        "closing_odometer": closing_odometer,
        "return_note": movement.get("return_note"),
        "total_fuel_litres_added": total_litres,
        "total_fuel_cost": total_cost,
        "pending_fuel_litres": pending_litres,
        "pending_fuel_cost": pending_cost,
        "distance_travelled": distance,
        "estimated_fuel_consumed": estimated_consumed,
        "estimated_fuel_efficiency": estimated_efficiency,
        "litre_values_are_estimates": estimated_consumed is not None,
        "tank_capacity_litres": tank_capacity if isinstance(tank_capacity, (int, float)) and tank_capacity > 0 else None,
        "fuel_summary_status": status,
        "legacy_opening_missing": bool(movement and not movement.get("opening_fuel_recorded_at")),
        "fuel_purchases": [
            {
                "id": str(item.get("_id")),
                "amount": item.get("amount"),
                "litres": item.get("litres"),
                "fuel_station_id": str(item.get("fuel_station_id")) if item.get("fuel_station_id") else None,
                "payment_method": item.get("payment_method"),
                "receipt_image": item.get("receipt_image"),
                "fuel_date": item.get("fuel_date"),
                "recorded_by": str(item.get("submitted_by")) if item.get("submitted_by") else None,
                "approval_status": item.get("status"),
                "note": item.get("notes"),
            }
            for item in fuel_logs
        ],
        "correction_audit": correction_audit,
    }


def get_dispatch_fuel_accountability(job_id: str, *, current_user_id: str, current_role: str) -> dict:
    job = _get_job(job_id)
    _assert_access(job, current_user_id=current_user_id, current_role=current_role)
    movement = _find_movement(job)
    vehicle = vehicles_collection().find_one({"_id": job.get("vehicle_id")}) if job.get("vehicle_id") else None
    logs = list_dispatch_fuel_logs(job["_id"])
    return {
        "movement": serialize_vehicle_movement(movement) if movement else None,
        "summary": build_dispatch_fuel_summary(movement, vehicle=vehicle, fuel_logs=logs),
    }


def refresh_dispatch_fuel_summary(dispatch_job_id: str | ObjectId) -> dict | None:
    job = _get_job(dispatch_job_id)
    movement = _find_movement(job)
    if not movement:
        return None
    vehicle = vehicles_collection().find_one({"_id": job.get("vehicle_id")}) if job.get("vehicle_id") else None
    summary = build_dispatch_fuel_summary(
        movement,
        vehicle=vehicle,
        fuel_logs=list_dispatch_fuel_logs(job["_id"]),
    )
    stored_fields = {
        "total_fuel_litres_added": summary["total_fuel_litres_added"],
        "total_fuel_cost": summary["total_fuel_cost"],
        "estimated_fuel_consumed": summary["estimated_fuel_consumed"],
        "estimated_fuel_efficiency": summary["estimated_fuel_efficiency"],
        "distance_travelled": summary["distance_travelled"],
        "fuel_summary_updated_at": now_utc(),
        "updated_at": now_utc(),
    }
    vehicle_movements_collection().update_one({"_id": movement["_id"]}, {"$set": stored_fields})
    return summary


def record_dispatch_opening_fuel(
    job_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    job = _get_job(job_id)
    _assert_access(job, current_user_id=current_user_id, current_role=current_role)
    if str(job.get("status") or "").lower() != "accepted":
        raise ApiError(
            "Opening fuel can only be confirmed for an accepted dispatch before it starts.",
            status_code=400,
        )
    movement = _ensure_predeparture_movement(job, current_user_id=current_user_id)
    if movement.get("opening_fuel_recorded_at"):
        raise ApiError("Opening fuel has already been confirmed for this dispatch.", status_code=409)
    opening_fuel = _validate_required_fuel_level(payload.get("opening_fuel_level"), "opening_fuel_level")
    opening_odometer = _validate_non_negative_number(
        payload.get("opening_odometer"),
        "opening_odometer",
        required=False,
    )
    timestamp = now_utc()
    actor_id = _to_object_id(current_user_id, "current_user_id")
    update_fields = {
        "opening_fuel_level": opening_fuel,
        "opening_odometer": opening_odometer,
        "opening_fuel_recorded_at": timestamp,
        "opening_fuel_recorded_by": actor_id,
        "opening_fuel_photo": validate_file_reference(
            payload.get("opening_fuel_photo"),
            field_name="opening_fuel_photo",
            file_name="opening-fuel.jpg",
        ),
        "opening_inspection_note": str(payload.get("inspection_note") or "").strip() or None,
        "fuel_summary_status": "opening_confirmed",
        "updated_at": timestamp,
    }
    result = vehicle_movements_collection().update_one(
        {"_id": movement["_id"], "opening_fuel_recorded_at": None},
        {"$set": update_fields},
    )
    if result.matched_count != 1:
        raise ApiError("Opening fuel has already been confirmed for this dispatch.", status_code=409)
    movement.update(update_fields)
    return get_dispatch_fuel_accountability(
        str(job["_id"]),
        current_user_id=current_user_id,
        current_role=current_role,
    )


def assert_dispatch_opening_confirmed(job: dict, *, current_user_id: str | None = None):
    movement = (
        _ensure_predeparture_movement(job, current_user_id=current_user_id)
        if current_user_id
        else _find_movement(job)
    )
    if (
        not movement
        or movement.get("opening_fuel_recorded_at") is None
        or movement.get("opening_fuel_level") is None
    ):
        raise ApiError(
            "Record opening fuel level before starting this dispatch.",
            status_code=400,
        )
    return movement


def correct_dispatch_fuel_reading(
    job_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    if str(current_role or "").lower() not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can correct dispatch fuel readings.", status_code=403)
    job = _get_job(job_id)
    movement = _find_movement(job)
    if not movement:
        raise ApiError("Dispatch fuel record not found.", status_code=404)
    field = str(payload.get("field") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if field not in FUEL_READING_FIELDS:
        raise ApiError("field must be an opening or closing fuel/odometer reading.", status_code=400)
    if not reason:
        raise ApiError("reason is required for an audited correction.", status_code=400)
    if "fuel_level" in field:
        new_value = _validate_required_fuel_level(payload.get("new_value"), field)
    else:
        new_value = _validate_non_negative_number(payload.get("new_value"), field)
    timestamp = now_utc()
    audit_entry = {
        "field": field,
        "changed_by": _to_object_id(current_user_id, "current_user_id"),
        "changed_at": timestamp,
        "previous_value": movement.get(field),
        "new_value": new_value,
        "reason": reason,
    }
    vehicle_movements_collection().update_one(
        {"_id": movement["_id"]},
        {"$set": {field: new_value, "updated_at": timestamp}, "$push": {"fuel_correction_audit": audit_entry}},
    )
    return get_dispatch_fuel_accountability(
        str(job["_id"]),
        current_user_id=current_user_id,
        current_role=current_role,
    )
