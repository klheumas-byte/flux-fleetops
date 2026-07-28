from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from bson import ObjectId

from extensions import get_collection
from utils.api_error import ApiError
from utils.fuel_levels import normalize_fuel_level_eighths


SUPPORTED_CUSTODY_EVENT_TYPES = {
    "released_to_driver",
    "accepted_by_driver",
    "transferred_to_mechanic",
    "accepted_by_mechanic",
    "returned_by_mechanic",
    "received_by_company",
    "transferred_between_drivers",
    "assignment_handover",
    "custody_return",
    "other",
}
ADMIN_ROLES = {"owner", "admin"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def _to_object_id(value, field_name: str, *, required: bool = False) -> ObjectId | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if ObjectId.is_valid(str(value)):
        return ObjectId(str(value))
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _normalize_role(value: str | None) -> str:
    role = str(value or "").strip().lower()
    return "admin" if role == "dispatcher" else role


def _normalize_text(value, *, max_length: int = 2000) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ApiError(f"Text values cannot exceed {max_length} characters.", status_code=400)
    return text


def _normalize_odometer(value) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("odometer must be numeric when provided.", status_code=400)
    if float(value) < 0:
        raise ApiError("odometer cannot be negative.", status_code=400)
    return round(float(value), 2)


def _normalize_fuel(value) -> int | None:
    normalized, warning = normalize_fuel_level_eighths(value)
    if warning:
        raise ApiError(warning, status_code=400)
    return normalized


def _normalize_evidence(value) -> list[dict]:
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else [value]
    if len(items) > 10:
        raise ApiError("Custody evidence cannot contain more than 10 items.", status_code=400)
    normalized = []
    for item in items:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            raise ApiError("Each custody evidence item must be an object or URL.", status_code=400)
        url = _normalize_text(item.get("url"), max_length=2000)
        if url and url.lower().startswith("data:"):
            raise ApiError("Embedded custody evidence is not supported.", status_code=400)
        normalized.append(
            {
                "url": url,
                "type": _normalize_text(item.get("type"), max_length=100),
                "label": _normalize_text(item.get("label"), max_length=200),
            }
        )
    return normalized


def _get_movement(movement_id: str | ObjectId) -> dict:
    movement_object_id = _to_object_id(movement_id, "movement_id", required=True)
    document = vehicle_movements_collection().find_one({"_id": movement_object_id})
    if not document:
        raise ApiError("Vehicle movement not found.", status_code=404)
    return document


def _event_id(source_event_key: str | None) -> str:
    if source_event_key:
        return f"CE-{uuid5(NAMESPACE_URL, source_event_key).hex[:20].upper()}"
    return f"CE-{uuid4().hex[:20].upper()}"


def _assert_actor_can_transfer(
    movement: dict,
    *,
    actor_id: ObjectId,
    current_role: str,
    audit_reason: str | None,
):
    if current_role in ADMIN_ROLES:
        if movement.get("movement_custodian_id") not in (None, actor_id) and not audit_reason:
            raise ApiError("audit_reason is required for an administrative custody override.", status_code=400)
        return
    if current_role != "driver":
        raise ApiError("You do not have permission to transfer vehicle custody.", status_code=403)
    if actor_id not in {movement.get("driver_id"), movement.get("movement_custodian_id")}:
        raise ApiError("Only the active movement custodian may transfer custody.", status_code=403)


def append_custody_event(
    movement_id: str | ObjectId,
    *,
    event_type: str,
    initiated_by: str | ObjectId,
    current_role: str,
    payload: dict | None = None,
    source_event_key: str | None = None,
    accepted_by: str | ObjectId | None = None,
    accepted_at: datetime | None = None,
) -> dict:
    """Append one chronological custody event, idempotently when keyed."""

    movement = _get_movement(movement_id)
    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_event_type not in SUPPORTED_CUSTODY_EVENT_TYPES:
        raise ApiError("Unsupported custody event type.", status_code=400)
    actor_id = _to_object_id(initiated_by, "initiated_by", required=True)
    normalized_role = _normalize_role(current_role)
    data = payload or {}
    audit_reason = _normalize_text(data.get("audit_reason"))
    if data.get("is_correction") and normalized_role not in ADMIN_ROLES:
        raise ApiError("Only an owner or admin may correct custody records.", status_code=403)
    if data.get("is_correction") and not audit_reason:
        raise ApiError("audit_reason is required for custody corrections.", status_code=400)

    to_user_id = _to_object_id(data.get("to_user_id"), "to_user_id", required=False)
    from_user_id = _to_object_id(
        data.get("from_user_id", movement.get("movement_custodian_id")),
        "from_user_id",
        required=False,
    )
    if to_user_id:
        target = users_collection().find_one({"_id": to_user_id}, {"status": 1})
        if not target or target.get("status") != "active":
            raise ApiError("Custody recipient must be an active user.", status_code=400)

    odometer = _normalize_odometer(data.get("odometer"))
    unavailable_reason = _normalize_text(data.get("odometer_unavailable_reason"), max_length=500)
    if odometer is None and data.get("odometer_available") is True:
        raise ApiError("odometer is required when odometer_available is true.", status_code=400)
    if odometer is None and data.get("odometer_available") is False and not unavailable_reason:
        raise ApiError("odometer_unavailable_reason is required when explicitly unavailable.", status_code=400)

    fuel_level = _normalize_fuel(data.get("fuel_level"))
    occurred_at = data.get("occurred_at")
    if occurred_at is not None and not isinstance(occurred_at, datetime):
        try:
            occurred_at = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
        except ValueError as error:
            raise ApiError("occurred_at must be a valid ISO datetime.", status_code=400) from error
    occurred_at = occurred_at or now_utc()
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    normalized_key = _normalize_text(source_event_key, max_length=500)
    event = {
        "event_id": _event_id(normalized_key),
        "event_key": normalized_key,
        "event_type": normalized_event_type,
        "from_user_id": from_user_id,
        "from_location": _normalize_text(data.get("from_location"), max_length=500),
        "to_user_id": to_user_id,
        "to_location": _normalize_text(data.get("to_location"), max_length=500),
        "initiated_by": actor_id,
        "accepted_by": _to_object_id(accepted_by, "accepted_by", required=False),
        "occurred_at": occurred_at,
        "accepted_at": accepted_at,
        "condition_summary": _normalize_text(data.get("condition_summary")),
        "fuel_level": fuel_level,
        "odometer": odometer,
        "odometer_available": odometer is not None,
        "odometer_unavailable_reason": unavailable_reason if odometer is None else None,
        "notes": _normalize_text(data.get("notes")),
        "evidence": _normalize_evidence(data.get("evidence")),
        "source_type": _normalize_text(data.get("source_type"), max_length=100)
        or movement.get("source_type"),
        "source_id": data.get("source_id", movement.get("source_id")),
        "is_correction": bool(data.get("is_correction")),
        "correction_reason": audit_reason if data.get("is_correction") else None,
    }
    timestamp = now_utc()
    query = {"_id": movement["_id"]}
    if normalized_key:
        query["custody_events.event_key"] = {"$ne": normalized_key}
    result = vehicle_movements_collection().update_one(
        query,
        {
            "$push": {"custody_events": event},
            "$set": {"updated_at": timestamp},
            "$inc": {"custody_version": 1},
        },
    )
    if result.modified_count == 0 and normalized_key:
        current = _get_movement(movement["_id"])
        existing = next(
            (item for item in current.get("custody_events") or [] if item.get("event_key") == normalized_key),
            None,
        )
        if existing:
            return {"movement": current, "event": existing, "created": False}
        raise ApiError("Custody event could not be recorded.", status_code=409)
    movement.setdefault("custody_events", []).append(event)
    movement["custody_version"] = int(movement.get("custody_version") or 0) + 1
    movement["updated_at"] = timestamp
    return {"movement": movement, "event": event, "created": True}


def transfer_movement_custody(
    movement_id: str | ObjectId,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
    source_event_key: str | None = None,
) -> dict:
    movement = _get_movement(movement_id)
    actor_id = _to_object_id(current_user_id, "current_user_id", required=True)
    normalized_role = _normalize_role(current_role)
    audit_reason = _normalize_text((payload or {}).get("audit_reason"))
    _assert_actor_can_transfer(
        movement,
        actor_id=actor_id,
        current_role=normalized_role,
        audit_reason=audit_reason,
    )
    to_user_id = _to_object_id((payload or {}).get("to_user_id"), "to_user_id", required=False)
    to_location = _normalize_text((payload or {}).get("to_location"), max_length=500)
    if to_user_id is None and not to_location:
        raise ApiError("Provide to_user_id or to_location for the custody transfer.", status_code=400)
    event_type = str((payload or {}).get("event_type") or "").strip().lower()
    if not event_type:
        event_type = "transferred_between_drivers" if to_user_id else "transferred_to_mechanic"
    result = append_custody_event(
        movement["_id"],
        event_type=event_type,
        initiated_by=actor_id,
        current_role=normalized_role,
        payload={
            **(payload or {}),
            "from_user_id": movement.get("movement_custodian_id"),
            "source_type": movement.get("source_type"),
            "source_id": movement.get("source_id"),
        },
        source_event_key=source_event_key or (payload or {}).get("event_key"),
    )
    pending = {
        "event_id": result["event"]["event_id"],
        "to_user_id": to_user_id,
        "to_location": to_location,
        "initiated_by": actor_id,
        "initiated_at": result["event"]["occurred_at"],
    }
    update_fields = {
        "pending_custody_transfer": pending,
        "custody_state": "pending_acceptance",
        "updated_at": now_utc(),
    }
    vehicle_movements_collection().update_one({"_id": movement["_id"]}, {"$set": update_fields})
    result["movement"].update(update_fields)
    return result


def accept_movement_custody(
    movement_id: str | ObjectId,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
    source_event_key: str | None = None,
) -> dict:
    movement = _get_movement(movement_id)
    actor_id = _to_object_id(current_user_id, "current_user_id", required=True)
    normalized_role = _normalize_role(current_role)
    pending = movement.get("pending_custody_transfer") or {}
    intended_user_id = pending.get("to_user_id")
    audit_reason = _normalize_text((payload or {}).get("audit_reason"))
    if not pending:
        requested_key = source_event_key or (payload or {}).get("event_key")
        if requested_key:
            existing = next(
                (item for item in movement.get("custody_events") or [] if item.get("event_key") == requested_key),
                None,
            )
            if existing:
                return {"movement": movement, "event": existing, "created": False}
        raise ApiError("There is no pending custody transfer to accept.", status_code=400)
    if intended_user_id:
        if actor_id != intended_user_id:
            if normalized_role not in ADMIN_ROLES:
                raise ApiError("Only the intended recipient may accept this custody transfer.", status_code=403)
            if not audit_reason:
                raise ApiError("audit_reason is required for an administrative custody override.", status_code=400)
    elif normalized_role not in ADMIN_ROLES:
        raise ApiError("Only an owner or admin may accept location-based custody.", status_code=403)
    destination_user_id = intended_user_id or _to_object_id(
        (payload or {}).get("to_user_id"),
        "to_user_id",
        required=False,
    )
    destination_location = pending.get("to_location") or _normalize_text(
        (payload or {}).get("to_location"),
        max_length=500,
    )
    event_type = str((payload or {}).get("event_type") or "").strip().lower()
    if not event_type:
        event_type = "accepted_by_driver" if destination_user_id else "accepted_by_mechanic"
    timestamp = now_utc()
    result = append_custody_event(
        movement["_id"],
        event_type=event_type,
        initiated_by=actor_id,
        current_role=normalized_role,
        payload={
            **(payload or {}),
            "from_user_id": movement.get("movement_custodian_id"),
            "to_user_id": destination_user_id,
            "to_location": destination_location,
            "source_type": movement.get("source_type"),
            "source_id": movement.get("source_id"),
        },
        source_event_key=source_event_key or (payload or {}).get("event_key"),
        accepted_by=actor_id,
        accepted_at=timestamp,
    )
    update_fields = {
        "movement_custodian_id": destination_user_id,
        "current_custody_location": destination_location,
        "custody_state": "accepted",
        "custody_accepted_at": timestamp,
        "custody_accepted_by": actor_id,
        "updated_at": timestamp,
    }
    vehicle_movements_collection().update_one(
        {"_id": movement["_id"]},
        {"$set": update_fields, "$unset": {"pending_custody_transfer": ""}},
    )
    vehicles_collection().update_one(
        {"_id": movement["vehicle_id"]},
        {
            "$set": {
                "current_custodian_id": destination_user_id,
                "current_custody_location": destination_location,
                "updated_at": timestamp,
            }
        },
    )
    result["movement"].update(update_fields)
    result["movement"].pop("pending_custody_transfer", None)
    return result


def return_movement_custody(
    movement_id: str | ObjectId,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
    source_event_key: str | None = None,
) -> dict:
    movement = _get_movement(movement_id)
    actor_id = _to_object_id(current_user_id, "current_user_id", required=True)
    normalized_role = _normalize_role(current_role)
    audit_reason = _normalize_text((payload or {}).get("audit_reason"))
    _assert_actor_can_transfer(
        movement,
        actor_id=actor_id,
        current_role=normalized_role,
        audit_reason=audit_reason,
    )
    timestamp = now_utc()
    result = append_custody_event(
        movement["_id"],
        event_type=str((payload or {}).get("event_type") or "custody_return").strip().lower(),
        initiated_by=actor_id,
        current_role=normalized_role,
        payload={
            **(payload or {}),
            "from_user_id": movement.get("movement_custodian_id"),
            "to_user_id": None,
            "to_location": (payload or {}).get("to_location") or "Company custody",
            "source_type": movement.get("source_type"),
            "source_id": movement.get("source_id"),
        },
        source_event_key=source_event_key or (payload or {}).get("event_key"),
        accepted_by=actor_id if normalized_role in ADMIN_ROLES else None,
        accepted_at=timestamp if normalized_role in ADMIN_ROLES else None,
    )
    update_fields = {
        "movement_custodian_id": None,
        "current_custody_location": (payload or {}).get("to_location") or "Company custody",
        "custody_state": "company_custody",
        "updated_at": timestamp,
    }
    if result["event"].get("odometer") is not None:
        update_fields["closing_odometer"] = result["event"]["odometer"]
    if result["event"].get("fuel_level") is not None:
        update_fields["closing_fuel_level"] = result["event"]["fuel_level"]
    if result["event"].get("condition_summary") is not None:
        update_fields["closing_condition_summary"] = result["event"]["condition_summary"]
    vehicle_movements_collection().update_one(
        {"_id": movement["_id"]},
        {"$set": update_fields, "$unset": {"pending_custody_transfer": ""}},
    )
    vehicles_collection().update_one(
        {"_id": movement["vehicle_id"]},
        {
            "$set": {
                "current_custodian_id": None,
                "current_custody_location": update_fields["current_custody_location"],
                "updated_at": timestamp,
            }
        },
    )
    result["movement"].update(update_fields)
    result["movement"].pop("pending_custody_transfer", None)
    return result
