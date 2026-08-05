"""Single compatibility-aware vehicle availability decision layer."""

from datetime import date, datetime, timezone

from bson import ObjectId

from extensions import get_collection
from utils.api_error import ApiError


ACTIVE_DISPATCH = {"reserved", "assigned", "accepted", "clarification_requested", "in_progress"}
ACTIVE_MOVEMENTS = {"draft", "pending_approval", "approved", "checked_out", "in_progress"}
ACTIVE_MAINTENANCE = {"pending", "approved", "in_progress", "waiting_parts"}
TERMINAL_INCIDENTS = {"resolved", "rejected", "closed"}
MANUAL_AVAILABILITY_STATES = {"available", "temporarily_unavailable"}
VEHICLE_MANUAL_UNAVAILABLE_REASONS = {"fueling", "cleaning", "parked_secured", "minor_issue", "other"}
DRIVER_MANUAL_UNAVAILABLE_REASONS = {"driver_unavailable", "break", "off_duty", "personal_reason", "other"}
MANUAL_AVAILABILITY_NOTE_LIMIT = 200


def _reason(kind, code, message, entity_id=None):
    return {"type": kind, "code": code, "message": message, "entity_id": str(entity_id) if entity_id else None}


def _restriction_view(document):
    return {
        "override_id": str(document["_id"]),
        "linked_record_type": document.get("linked_record_type"),
        "linked_record_id": str(document.get("linked_record_id")),
        "operational_restriction": document.get("operational_restriction"),
        "repair_deadline": document.get("repair_deadline").isoformat() if document.get("repair_deadline") else None,
        "maximum_mileage": document.get("maximum_mileage"),
        "maximum_hours": document.get("maximum_hours"),
    }


def _apply_window(query: dict, *, start_field: str, end_field: str, context: dict) -> dict:
    start_time = context.get("start_time")
    end_time = context.get("end_time")
    if not isinstance(start_time, datetime) or not isinstance(end_time, datetime):
        return query
    return {
        **query,
        "$or": [
            {"$and": [{start_field: {"$lt": end_time}}, {end_field: {"$gt": start_time}}]},
            {start_field: None},
            {end_field: None},
        ],
    }


def _manual_reason(document: dict) -> dict | None:
    if document.get("manual_availability_status") != "temporarily_unavailable":
        return None
    reason = str(document.get("manual_availability_reason") or "Temporarily unavailable").replace("_", " ").strip()
    note = str(document.get("manual_availability_note") or "").strip()
    detail = f" ({note})" if note else ""
    return _reason("manual", "temporarily_unavailable", f"Vehicle temporarily unavailable — {reason.title()}{detail}")


def _manual_availability_values(payload: dict, valid_reasons: set[str]) -> tuple[str, str | None, str | None]:
    status = str(payload.get("status") or "").strip().lower()
    if status not in MANUAL_AVAILABILITY_STATES:
        raise ApiError("Availability must be available or temporarily_unavailable.", status_code=400)
    if status == "available":
        return status, None, None
    reason = str(payload.get("reason") or "").strip().lower().replace("/", "_").replace(" ", "_") or None
    if reason not in valid_reasons:
        raise ApiError("Please select a valid temporary unavailability reason.", status_code=400)
    note = str(payload.get("note") or "").strip() or None
    if note and len(note) > MANUAL_AVAILABILITY_NOTE_LIMIT:
        raise ApiError(f"Availability note must be {MANUAL_AVAILABILITY_NOTE_LIMIT} characters or fewer.", status_code=400)
    return status, reason, note if reason == "other" else None


def update_vehicle_manual_availability(
    vehicle_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    if not ObjectId.is_valid(str(vehicle_id)) or not ObjectId.is_valid(str(current_user_id)):
        raise ApiError("Invalid vehicle or user identity.", status_code=400)
    vehicle_object_id = ObjectId(str(vehicle_id))
    actor_id = ObjectId(str(current_user_id))
    vehicle = get_collection("vehicles").find_one({"_id": vehicle_object_id})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    if current_role == "driver":
        assigned = vehicle.get("assigned_driver_id") == actor_id or vehicle.get("current_custodian_id") == actor_id
        if not assigned:
            assigned = bool(get_collection("assignments").find_one({
                "vehicle_id": vehicle_object_id,
                "driver_id": actor_id,
                "status": "active",
            }, {"_id": 1}))
        if not assigned:
            raise ApiError("You can only update availability for your assigned vehicle.", status_code=403)
    elif current_role not in {"owner", "admin", "operations_administrator", "operations_manager"}:
        raise ApiError("You do not have permission to update vehicle availability.", status_code=403)
    status, reason, note = _manual_availability_values(payload, VEHICLE_MANUAL_UNAVAILABLE_REASONS)
    timestamp = datetime.now(timezone.utc)
    updates = {
        "manual_availability_status": status,
        "manual_availability_reason": reason if status == "temporarily_unavailable" else None,
        "manual_availability_note": note,
        "manual_availability_updated_by": actor_id,
        "manual_availability_updated_at": timestamp,
        "updated_at": timestamp,
    }
    get_collection("vehicles").update_one({"_id": vehicle_object_id}, {"$set": updates})
    return resolve_vehicle_availability(vehicle_object_id)


def update_driver_manual_availability(
    driver_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    if not ObjectId.is_valid(str(driver_id)) or not ObjectId.is_valid(str(current_user_id)):
        raise ApiError("Invalid driver or user identity.", status_code=400)
    driver_object_id = ObjectId(str(driver_id))
    actor_id = ObjectId(str(current_user_id))
    if current_role == "driver" and driver_object_id != actor_id:
        raise ApiError("You can only update your own availability.", status_code=403)
    if current_role not in {"driver", "owner", "admin", "operations_administrator", "operations_manager"}:
        raise ApiError("You do not have permission to update driver availability.", status_code=403)
    if not get_collection("users").find_one({"_id": driver_object_id, "role": "driver"}, {"_id": 1}):
        raise ApiError("Driver not found.", status_code=404)
    status, reason, note = _manual_availability_values(payload, DRIVER_MANUAL_UNAVAILABLE_REASONS)
    timestamp = datetime.now(timezone.utc)
    updates = {
        "driver_profile.manual_availability_status": status,
        "driver_profile.manual_availability_reason": reason if status == "temporarily_unavailable" else None,
        "driver_profile.manual_availability_note": note,
        "driver_profile.manual_availability_updated_by": actor_id,
        "driver_profile.manual_availability_updated_at": timestamp,
        "updated_at": timestamp,
    }
    get_collection("users").update_one({"_id": driver_object_id}, {"$set": updates})
    return resolve_driver_availability(driver_object_id)


def resolve_driver_availability(driver_id: str | ObjectId, context: dict | None = None) -> dict:
    context = context or {}
    driver_object_id = driver_id if isinstance(driver_id, ObjectId) else ObjectId(str(driver_id))
    driver = get_collection("users").find_one(
        {"_id": driver_object_id, "role": "driver"},
        {"status": 1, "driver_profile.approval_status": 1, "driver_profile.manual_availability_status": 1, "driver_profile.manual_availability_reason": 1, "driver_profile.manual_availability_note": 1, "driver_profile.manual_availability_updated_by": 1, "driver_profile.manual_availability_updated_at": 1},
    )
    if not driver:
        return {"driver_id": str(driver_object_id), "is_available": False, "operational_state": "unavailable", "primary_reason": "Driver not found", "blocking_reasons": []}
    reasons = []
    account_status = str(driver.get("status") or "").strip().lower()
    approval_status = str((driver.get("driver_profile") or {}).get("approval_status") or "approved").strip().lower()
    if account_status != "active":
        reasons.append(_reason("lifecycle", "driver_inactive", "Driver is suspended" if account_status == "suspended" else "Driver is inactive"))
    elif approval_status != "approved":
        reasons.append(_reason("lifecycle", "driver_not_approved", "Driver is not approved"))
    reservation_query = _apply_window(
        {"resource_id": driver_object_id, "reservation_type": "driver", "status": {"$in": ["reserved", "consumed"]}},
        start_field="start_time", end_field="end_time", context=context,
    )
    if context.get("exclude_reservation_id"):
        excluded_reservation = context["exclude_reservation_id"]
        if not isinstance(excluded_reservation, ObjectId) and ObjectId.is_valid(str(excluded_reservation)):
            excluded_reservation = ObjectId(str(excluded_reservation))
        reservation_query["_id"] = {"$ne": excluded_reservation}
    reservation = get_collection("resource_reservations").find_one(reservation_query, {"_id": 1})
    if reservation:
        reasons.append(_reason("reservation", "active_driver_reservation", "Driver has an active reservation", reservation["_id"]))
    movement_query = _apply_window(
        {"driver_id": driver_object_id, "status": {"$in": list(ACTIVE_MOVEMENTS)}, "movement_type": {"$ne": "assignment_handover"}},
        start_field="requested_departure_time", end_field="expected_return_time", context=context,
    )
    if context.get("exclude_movement_id"):
        excluded_movement = context["exclude_movement_id"]
        if not isinstance(excluded_movement, ObjectId) and ObjectId.is_valid(str(excluded_movement)):
            excluded_movement = ObjectId(str(excluded_movement))
        movement_query["_id"] = {"$ne": excluded_movement}
    movement = get_collection("vehicle_movements").find_one(movement_query, {"_id": 1})
    if movement:
        reasons.append(_reason("movement", "active_driver_movement", "Driver has an active vehicle movement", movement["_id"]))
    dispatch_query = _apply_window(
        {"driver_id": driver_object_id, "status": {"$in": list(ACTIVE_DISPATCH)}},
        start_field="scheduled_start_time", end_field="expected_return_time", context=context,
    )
    if context.get("exclude_dispatch_job_id"):
        excluded_dispatch = context["exclude_dispatch_job_id"]
        if not isinstance(excluded_dispatch, ObjectId) and ObjectId.is_valid(str(excluded_dispatch)):
            excluded_dispatch = ObjectId(str(excluded_dispatch))
        dispatch_query["_id"] = {"$ne": excluded_dispatch}
    dispatch = get_collection("dispatch_jobs").find_one(dispatch_query, {"_id": 1})
    if dispatch:
        reasons.append(_reason("dispatch", "active_driver_dispatch", "Driver has an active dispatch", dispatch["_id"]))
    profile = driver.get("driver_profile") or {}
    manual_status = profile.get("manual_availability_status") or "available"
    if manual_status == "temporarily_unavailable":
        reason = str(profile.get("manual_availability_reason") or "temporarily unavailable").replace("_", " ")
        note = str(profile.get("manual_availability_note") or "").strip()
        detail = f" ({note})" if note else ""
        reasons.append(_reason("manual", "temporarily_unavailable", f"Driver temporarily unavailable — {reason.title()}{detail}"))
    priority = {"lifecycle": 0, "dispatch": 1, "movement": 1, "reservation": 1, "manual": 2}
    reasons.sort(key=lambda item: priority.get(item["type"], 99))
    primary = reasons[0]["message"] if reasons else None
    state = {"dispatch": "on_dispatch", "movement": "in_movement", "reservation": "reserved", "manual": "temporarily_unavailable"}.get(reasons[0]["type"], "unavailable") if reasons else "available"
    return {
        "driver_id": str(driver_object_id), "is_available": not reasons, "operational_state": state,
        "primary_reason": primary, "blocking_reasons": reasons,
        "manual_availability_status": manual_status,
        "manual_availability_reason": profile.get("manual_availability_reason"),
        "manual_availability_note": profile.get("manual_availability_note"),
        "manual_availability_updated_at": profile.get("manual_availability_updated_at").isoformat() if hasattr(profile.get("manual_availability_updated_at"), "isoformat") else profile.get("manual_availability_updated_at"),
        "manual_availability_updated_by": str(profile.get("manual_availability_updated_by")) if profile.get("manual_availability_updated_by") else None,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_vehicle_availability(vehicle_id: str | ObjectId, context: dict | None = None) -> dict:
    context = context or {}
    vehicle_object_id = vehicle_id if isinstance(vehicle_id, ObjectId) else ObjectId(str(vehicle_id))
    vehicle = get_collection("vehicles").find_one(
        {"_id": vehicle_object_id},
        {"status": 1, "assigned_driver_id": 1, "current_custodian_id": 1, "manual_availability_status": 1, "manual_availability_reason": 1, "manual_availability_note": 1, "manual_availability_updated_by": 1, "manual_availability_updated_at": 1},
    )
    if not vehicle:
        return {"vehicle_id": str(vehicle_object_id), "is_available": False, "operational_state": "unavailable", "primary_reason": "Vehicle not found", "blocking_reasons": []}

    from services.maintenance_override_service import active_overrides_for_vehicle
    active_overrides = active_overrides_for_vehicle(
        vehicle_object_id,
        collection=get_collection("maintenance_availability_overrides"),
    )
    overridden_maintenance_ids = {
        item["linked_record_id"] for item in active_overrides if item.get("linked_record_type") == "maintenance"
    }

    lifecycle = str(vehicle.get("status") or "available").strip().lower()
    reasons = []
    if lifecycle == "retired":
        reasons.append(_reason("lifecycle", "retired", "Vehicle is retired"))
    elif lifecycle in {"out_of_service", "suspended"} or (lifecycle in {"maintenance", "accident"} and not active_overrides):
        reasons.append(_reason("lifecycle", lifecycle, f"Vehicle is {lifecycle.replace('_', ' ')}"))

    dispatch_query = _apply_window(
        {"vehicle_id": vehicle_object_id, "status": {"$in": list(ACTIVE_DISPATCH)}},
        start_field="scheduled_start_time", end_field="expected_return_time", context=context,
    )
    dispatch = get_collection("dispatch_jobs").find_one(dispatch_query, {"_id": 1})
    if dispatch:
        reasons.append(_reason("dispatch", "active_dispatch", "Vehicle has an active dispatch", dispatch["_id"]))
    reservation_query = {"resource_id": vehicle_object_id, "reservation_type": "vehicle", "status": {"$in": ["reserved", "consumed"]}}
    reservation_query = _apply_window(reservation_query, start_field="start_time", end_field="end_time", context=context)
    if context.get("exclude_reservation_id"):
        excluded_reservation = context["exclude_reservation_id"]
        if not isinstance(excluded_reservation, ObjectId) and ObjectId.is_valid(str(excluded_reservation)):
            excluded_reservation = ObjectId(str(excluded_reservation))
        reservation_query["_id"] = {"$ne": excluded_reservation}
    reservation = get_collection("resource_reservations").find_one(reservation_query, {"_id": 1, "source_type": 1, "end_time": 1})
    if reservation:
        source_label = str(reservation.get("source_type") or "another operation").replace("_", " ").title()
        until = reservation.get("end_time")
        suffix = f" until {until.strftime('%Y-%m-%d %H:%M')}" if isinstance(until, datetime) else ""
        reasons.append(_reason("reservation", "active_reservation", f"Vehicle unavailable — {source_label}{suffix}", reservation["_id"]))
    movement_query = {"vehicle_id": vehicle_object_id, "status": {"$in": list(ACTIVE_MOVEMENTS)}}
    movement_query = _apply_window(movement_query, start_field="requested_departure_time", end_field="expected_return_time", context=context)
    if context.get("exclude_movement_id"):
        excluded_id = context["exclude_movement_id"]
        if not isinstance(excluded_id, ObjectId) and ObjectId.is_valid(str(excluded_id)):
            excluded_id = ObjectId(str(excluded_id))
        movement_query["_id"] = {"$ne": excluded_id}
    movement = get_collection("vehicle_movements").find_one(
        movement_query,
        {
            "_id": 1,
            "movement_type": 1,
            "custody_state": 1,
            "current_custody_location": 1,
            "movement_type": 1,
            "expected_return_time": 1,
            "source_reference": 1,
        },
    )
    if movement and movement.get("movement_type") == "assignment_handover" and movement.get("custody_state") != "pending_acceptance":
        movement = None
    if movement:
        custody_state = movement.get("custody_state")
        if movement.get("movement_type") == "assignment_handover" and custody_state == "pending_acceptance":
            reasons.append(_reason("movement", "pending_handover", "Vehicle is awaiting custody handover acceptance", movement["_id"]))
        elif custody_state in {"workshop_custody", "accepted"} and movement.get("current_custody_location"):
            reasons.append(_reason("movement", "external_custody", f"Vehicle is in custody at {movement['current_custody_location']}", movement["_id"]))
        else:
            movement_label = str(movement.get("movement_type") or "vehicle movement").replace("_", " ").title()
            until = movement.get("expected_return_time")
            suffix = f" until {until.strftime('%Y-%m-%d %H:%M')}" if isinstance(until, datetime) else ""
            reasons.append(_reason("movement", "active_movement", f"Vehicle unavailable — {movement_label}{suffix}", movement["_id"]))
    maintenance = list(get_collection("maintenance_jobs").find({"vehicle_id": vehicle_object_id, "status": {"$in": list(ACTIVE_MAINTENANCE)}}, {"_id": 1}))
    for maintenance_job in maintenance:
        if maintenance_job["_id"] not in overridden_maintenance_ids:
            reasons.append(_reason("maintenance", "active_maintenance_job", "Vehicle has an active maintenance job", maintenance_job["_id"]))
    fault = get_collection("faults").find_one({"vehicle_id": vehicle_object_id, "status": {"$nin": ["resolved", "rejected", "closed"]}, "$or": [{"severity": "critical"}, {"vehicle_unsafe": True}]}, {"_id": 1})
    if fault:
        reasons.append(_reason("fault", "critical_or_unsafe_fault", "Vehicle has a critical or unsafe fault", fault["_id"]))
    incident = get_collection("incidents").find_one({"vehicle_id": vehicle_object_id, "status": {"$nin": list(TERMINAL_INCIDENTS)}, "can_vehicle_move": False}, {"_id": 1})
    if incident:
        reasons.append(_reason("incident", "vehicle_blocking_incident", "Vehicle has a blocking incident", incident["_id"]))
    compliance = get_collection("vehicle_compliance_records").find_one({"vehicle_id": vehicle_object_id, "status": "expired"}, {"_id": 1})
    if compliance:
        reasons.append(_reason("compliance", "expired_mandatory_compliance", "Vehicle has expired mandatory compliance", compliance["_id"]))
    manual_reason = _manual_reason(vehicle)
    if manual_reason:
        reasons.append(manual_reason)

    # Only the exact compliance blocker being addressed may be bypassed.
    if (
        context.get("movement_type") == "compliance_inspection_visit"
        and context.get("related_source_type") == "compliance_record"
        and context.get("related_source_id")
    ):
        related_id = str(context["related_source_id"])
        reasons = [item for item in reasons if not (
            item.get("type") == "compliance" and item.get("entity_id") == related_id
        )]

    priority = {"lifecycle": 0, "fault": 1, "incident": 1, "compliance": 2, "maintenance": 3, "dispatch": 4, "movement": 4, "reservation": 4, "manual": 5}
    reasons.sort(key=lambda item: priority.get(item["type"], 99))
    assigned = vehicle.get("assigned_driver_id")
    if reasons:
        primary = reasons[0]["message"]
        state = {"lifecycle": "unavailable", "fault": "blocked", "incident": "blocked", "compliance": "blocked", "maintenance": "under_maintenance", "dispatch": "on_dispatch", "movement": "in_movement", "reservation": "reserved", "manual": "temporarily_unavailable"}.get(reasons[0]["type"], "unavailable")
        if reasons[0]["code"] == "pending_handover":
            state = "pending_handover"
        elif reasons[0]["code"] == "external_custody":
            state = "external_custody"
    elif active_overrides:
        primary, state = "Available with operational restrictions", "available_with_restriction"
    elif assigned or lifecycle == "assigned":
        primary, state = "Assigned permanent driver", "assigned"
    else:
        primary, state = None, "available"
    return {"vehicle_id": str(vehicle_object_id), "is_available": not reasons, "lifecycle_status": "active" if lifecycle in {"available", "assigned", "active"} else lifecycle, "operational_state": state, "primary_reason": primary, "blocking_reasons": reasons, "active_restrictions": [_restriction_view(item) for item in active_overrides], "restriction_acknowledgement_required": bool(active_overrides), "manual_availability_status": vehicle.get("manual_availability_status") or "available", "manual_availability_reason": vehicle.get("manual_availability_reason"), "manual_availability_note": vehicle.get("manual_availability_note"), "manual_availability_updated_at": vehicle.get("manual_availability_updated_at").isoformat() if hasattr(vehicle.get("manual_availability_updated_at"), "isoformat") else vehicle.get("manual_availability_updated_at"), "manual_availability_updated_by": str(vehicle.get("manual_availability_updated_by")) if vehicle.get("manual_availability_updated_by") else None, "permanent_driver_id": str(assigned) if assigned else None, "current_custodian_id": str(vehicle.get("current_custodian_id")) if vehicle.get("current_custodian_id") else None, "evaluated_at": datetime.now(timezone.utc).isoformat()}


def resolve_many(vehicle_ids, context: dict | None = None) -> dict[str, dict]:
    """Resolve a vehicle list with one bounded query per blocker source."""
    context = context or {}
    object_ids = [item if isinstance(item, ObjectId) else ObjectId(str(item)) for item in vehicle_ids]
    if not object_ids:
        return {}
    from services.maintenance_override_service import active_overrides_for_vehicles
    overrides = active_overrides_for_vehicles(
        object_ids,
        collection=get_collection("maintenance_availability_overrides"),
    )
    vehicle_map = {item["_id"]: item for item in get_collection("vehicles").find(
        {"_id": {"$in": object_ids}}, {"status": 1, "assigned_driver_id": 1, "current_custodian_id": 1, "manual_availability_status": 1, "manual_availability_reason": 1}
    )}
    def grouped(collection, query, projection):
        result = {}
        for item in get_collection(collection).find(query, projection):
            result.setdefault(item.get("vehicle_id") or item.get("resource_id"), []).append(item)
        return result
    dispatches = grouped("dispatch_jobs", _apply_window(
        {"vehicle_id": {"$in": object_ids}, "status": {"$in": list(ACTIVE_DISPATCH)}},
        start_field="scheduled_start_time", end_field="expected_return_time", context=context,
    ), {"_id": 1, "vehicle_id": 1, "driver_id": 1})
    reservations = grouped("resource_reservations", _apply_window(
        {"resource_id": {"$in": object_ids}, "reservation_type": "vehicle", "status": {"$in": ["reserved", "consumed"]}},
        start_field="start_time", end_field="end_time", context=context,
    ), {"_id": 1, "resource_id": 1, "source_type": 1, "start_time": 1, "end_time": 1})
    movements = grouped(
        "vehicle_movements",
        _apply_window(
            {"vehicle_id": {"$in": object_ids}, "status": {"$in": list(ACTIVE_MOVEMENTS)}},
            start_field="requested_departure_time", end_field="expected_return_time", context=context,
        ),
        {
            "_id": 1,
            "vehicle_id": 1,
            "movement_custodian_id": 1,
            "driver_id": 1,
            "movement_type": 1,
            "custody_state": 1,
            "current_custody_location": 1,
        },
    )
    maintenance = grouped("maintenance_jobs", {"vehicle_id": {"$in": object_ids}, "status": {"$in": list(ACTIVE_MAINTENANCE)}}, {"_id": 1, "vehicle_id": 1, "maintenance_coordinator_id": 1})
    faults = grouped("faults", {"vehicle_id": {"$in": object_ids}, "status": {"$nin": ["resolved", "rejected", "closed"]}, "$or": [{"severity": "critical"}, {"vehicle_unsafe": True}]}, {"_id": 1, "vehicle_id": 1})
    incidents = grouped("incidents", {"vehicle_id": {"$in": object_ids}, "status": {"$nin": list(TERMINAL_INCIDENTS)}, "can_vehicle_move": False}, {"_id": 1, "vehicle_id": 1})
    compliance = grouped("vehicle_compliance_records", {"vehicle_id": {"$in": object_ids}, "status": "expired"}, {"_id": 1, "vehicle_id": 1})
    priority = {"lifecycle": 0, "fault": 1, "incident": 1, "compliance": 2, "maintenance": 3, "dispatch": 4, "movement": 4, "reservation": 4, "manual": 5}
    output = {}
    for object_id in object_ids:
        vehicle = vehicle_map.get(object_id, {})
        lifecycle = str(vehicle.get("status") or "available").strip().lower()
        reasons = []
        active_overrides = overrides.get(object_id, [])
        overridden_maintenance_ids = {
            item["linked_record_id"] for item in active_overrides if item.get("linked_record_type") == "maintenance"
        }
        if lifecycle == "retired": reasons.append(_reason("lifecycle", "retired", "Vehicle is retired"))
        elif lifecycle in {"out_of_service", "suspended"} or (lifecycle in {"maintenance", "accident"} and not active_overrides): reasons.append(_reason("lifecycle", lifecycle, f"Vehicle is {lifecycle.replace('_', ' ')}"))
        movement_items = [item for item in movements.get(object_id, []) if item.get("movement_type") != "assignment_handover" or item.get("custody_state") == "pending_acceptance"]
        movement_code = "active_movement"
        movement_message = "Vehicle has an active vehicle movement"
        if movement_items:
            active_movement = movement_items[0]
            if active_movement.get("movement_type") == "assignment_handover" and active_movement.get("custody_state") == "pending_acceptance":
                movement_code = "pending_handover"
                movement_message = "Vehicle is awaiting custody handover acceptance"
            elif active_movement.get("current_custody_location") and active_movement.get("custody_state") in {"workshop_custody", "accepted"}:
                movement_code = "external_custody"
                movement_message = f"Vehicle is in custody at {active_movement['current_custody_location']}"
        uncovered_maintenance = [item for item in maintenance.get(object_id, []) if item.get("_id") not in overridden_maintenance_ids]
        for item, kind, code, message in ((dispatches.get(object_id, []), "dispatch", "active_dispatch", "Vehicle has an active dispatch"), (reservations.get(object_id, []), "reservation", "active_reservation", "Vehicle has an active reservation"), (movement_items, "movement", movement_code, movement_message), (uncovered_maintenance, "maintenance", "active_maintenance_job", "Vehicle has an active maintenance job"), (faults.get(object_id, []), "fault", "critical_or_unsafe_fault", "Vehicle has a critical or unsafe fault"), (incidents.get(object_id, []), "incident", "vehicle_blocking_incident", "Vehicle has a blocking incident"), (compliance.get(object_id, []), "compliance", "expired_mandatory_compliance", "Vehicle has expired mandatory compliance")):
            if item:
                reasons.append(_reason(kind, code, message, item[0].get("_id")))
        manual_reason = _manual_reason(vehicle)
        if manual_reason:
            reasons.append(manual_reason)
        reasons.sort(key=lambda item: priority.get(item["type"], 99))
        assigned = vehicle.get("assigned_driver_id")
        if reasons:
            state = {"lifecycle": "unavailable", "fault": "blocked", "incident": "blocked", "compliance": "blocked", "maintenance": "under_maintenance", "dispatch": "on_dispatch", "movement": "in_movement", "reservation": "reserved", "manual": "temporarily_unavailable"}[reasons[0]["type"]]
            if reasons[0]["code"] == "pending_handover":
                state = "pending_handover"
            elif reasons[0]["code"] == "external_custody":
                state = "external_custody"
            primary = reasons[0]["message"]
        elif active_overrides:
            state, primary = "available_with_restriction", "Available with operational restrictions"
        else:
            state, primary = ("assigned", "Assigned permanent driver") if assigned or lifecycle == "assigned" else ("available", None)
        custodian = None
        for source in (dispatches, movements, maintenance):
            item = source.get(object_id, [])
            if item:
                custodian = item[0].get("movement_custodian_id") or item[0].get("driver_id") or item[0].get("maintenance_coordinator_id")
                break
        output[str(object_id)] = {"vehicle_id": str(object_id), "is_available": not reasons, "lifecycle_status": "active" if lifecycle in {"available", "assigned", "active"} else lifecycle, "operational_state": state, "primary_reason": primary, "blocking_reasons": reasons, "active_restrictions": [_restriction_view(item) for item in active_overrides], "restriction_acknowledgement_required": bool(active_overrides), "manual_availability_status": vehicle.get("manual_availability_status") or "available", "manual_availability_reason": vehicle.get("manual_availability_reason"), "permanent_driver_id": str(assigned) if assigned else None, "current_custodian_id": str(custodian) if custodian else None, "evaluated_at": datetime.now(timezone.utc).isoformat()}
    return output
