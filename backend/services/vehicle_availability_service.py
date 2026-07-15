"""Single compatibility-aware vehicle availability decision layer."""

from datetime import date, datetime, timezone

from bson import ObjectId

from extensions import get_collection


ACTIVE_DISPATCH = {"reserved", "assigned", "accepted", "clarification_requested", "in_progress"}
ACTIVE_MOVEMENTS = {"draft", "pending_approval", "approved", "checked_out", "in_progress"}
ACTIVE_MAINTENANCE = {"pending", "approved", "in_progress", "waiting_parts"}
TERMINAL_INCIDENTS = {"resolved", "rejected", "closed"}


def _reason(kind, code, message, entity_id=None):
    return {"type": kind, "code": code, "message": message, "entity_id": str(entity_id) if entity_id else None}


def resolve_vehicle_availability(vehicle_id: str | ObjectId, context: dict | None = None) -> dict:
    del context
    vehicle_object_id = vehicle_id if isinstance(vehicle_id, ObjectId) else ObjectId(str(vehicle_id))
    vehicle = get_collection("vehicles").find_one(
        {"_id": vehicle_object_id},
        {"status": 1, "assigned_driver_id": 1, "current_custodian_id": 1},
    )
    if not vehicle:
        return {"vehicle_id": str(vehicle_object_id), "is_available": False, "operational_state": "unavailable", "primary_reason": "Vehicle not found", "blocking_reasons": []}

    lifecycle = str(vehicle.get("status") or "available").strip().lower()
    reasons = []
    if lifecycle == "retired":
        reasons.append(_reason("lifecycle", "retired", "Vehicle is retired"))
    elif lifecycle in {"out_of_service", "suspended"}:
        reasons.append(_reason("lifecycle", lifecycle, f"Vehicle is {lifecycle.replace('_', ' ')}"))

    dispatch = get_collection("dispatch_jobs").find_one({"vehicle_id": vehicle_object_id, "status": {"$in": list(ACTIVE_DISPATCH)}}, {"_id": 1})
    if dispatch:
        reasons.append(_reason("dispatch", "active_dispatch", "Vehicle has an active dispatch", dispatch["_id"]))
    reservation = get_collection("resource_reservations").find_one({"resource_id": vehicle_object_id, "reservation_type": "vehicle", "status": {"$in": ["reserved", "consumed"]}}, {"_id": 1})
    if reservation:
        reasons.append(_reason("reservation", "active_reservation", "Vehicle has an active reservation", reservation["_id"]))
    movement = get_collection("vehicle_movements").find_one({"vehicle_id": vehicle_object_id, "status": {"$in": list(ACTIVE_MOVEMENTS)}}, {"_id": 1})
    if movement:
        reasons.append(_reason("movement", "active_movement", "Vehicle has an active vehicle movement", movement["_id"]))
    maintenance = get_collection("maintenance_jobs").find_one({"vehicle_id": vehicle_object_id, "status": {"$in": list(ACTIVE_MAINTENANCE)}}, {"_id": 1})
    if maintenance:
        reasons.append(_reason("maintenance", "active_maintenance_job", "Vehicle has an active maintenance job", maintenance["_id"]))
    fault = get_collection("faults").find_one({"vehicle_id": vehicle_object_id, "status": {"$nin": ["resolved", "rejected", "closed"]}, "$or": [{"severity": "critical"}, {"vehicle_unsafe": True}]}, {"_id": 1})
    if fault:
        reasons.append(_reason("fault", "critical_or_unsafe_fault", "Vehicle has a critical or unsafe fault", fault["_id"]))
    incident = get_collection("incidents").find_one({"vehicle_id": vehicle_object_id, "status": {"$nin": list(TERMINAL_INCIDENTS)}, "can_vehicle_move": False}, {"_id": 1})
    if incident:
        reasons.append(_reason("incident", "vehicle_blocking_incident", "Vehicle has a blocking incident", incident["_id"]))
    compliance = get_collection("vehicle_compliance_records").find_one({"vehicle_id": vehicle_object_id, "status": "expired"}, {"_id": 1})
    if compliance:
        reasons.append(_reason("compliance", "expired_mandatory_compliance", "Vehicle has expired mandatory compliance", compliance["_id"]))

    priority = {"lifecycle": 0, "fault": 1, "incident": 1, "compliance": 2, "maintenance": 3, "dispatch": 4, "movement": 5, "reservation": 6}
    reasons.sort(key=lambda item: priority.get(item["type"], 99))
    assigned = vehicle.get("assigned_driver_id")
    if reasons:
        primary = reasons[0]["message"]
        state = {"lifecycle": "unavailable", "fault": "blocked", "incident": "blocked", "compliance": "blocked", "maintenance": "under_maintenance", "dispatch": "on_dispatch", "movement": "in_movement", "reservation": "reserved"}.get(reasons[0]["type"], "unavailable")
    elif assigned:
        primary, state = "Assigned permanent driver", "assigned"
    else:
        primary, state = None, "available"
    return {"vehicle_id": str(vehicle_object_id), "is_available": not reasons, "lifecycle_status": lifecycle if lifecycle not in {"available", "assigned", "maintenance", "accident"} else "active", "operational_state": state, "primary_reason": primary, "blocking_reasons": reasons, "permanent_driver_id": str(assigned) if assigned else None, "current_custodian_id": str(vehicle.get("current_custodian_id")) if vehicle.get("current_custodian_id") else None, "evaluated_at": datetime.now(timezone.utc).isoformat()}


def resolve_many(vehicle_ids, context: dict | None = None) -> dict[str, dict]:
    """Resolve a vehicle list with one bounded query per blocker source."""
    del context
    object_ids = [item if isinstance(item, ObjectId) else ObjectId(str(item)) for item in vehicle_ids]
    if not object_ids:
        return {}
    vehicle_map = {item["_id"]: item for item in get_collection("vehicles").find(
        {"_id": {"$in": object_ids}}, {"status": 1, "assigned_driver_id": 1, "current_custodian_id": 1}
    )}
    def grouped(collection, query, projection):
        result = {}
        for item in get_collection(collection).find(query, projection):
            result.setdefault(item.get("vehicle_id") or item.get("resource_id"), []).append(item)
        return result
    dispatches = grouped("dispatch_jobs", {"vehicle_id": {"$in": object_ids}, "status": {"$in": list(ACTIVE_DISPATCH)}}, {"_id": 1, "vehicle_id": 1, "driver_id": 1})
    reservations = grouped("resource_reservations", {"resource_id": {"$in": object_ids}, "reservation_type": "vehicle", "status": {"$in": ["reserved", "consumed"]}}, {"_id": 1, "resource_id": 1})
    movements = grouped("vehicle_movements", {"vehicle_id": {"$in": object_ids}, "status": {"$in": list(ACTIVE_MOVEMENTS)}}, {"_id": 1, "vehicle_id": 1, "movement_custodian_id": 1, "driver_id": 1})
    maintenance = grouped("maintenance_jobs", {"vehicle_id": {"$in": object_ids}, "status": {"$in": list(ACTIVE_MAINTENANCE)}}, {"_id": 1, "vehicle_id": 1, "maintenance_coordinator_id": 1})
    faults = grouped("faults", {"vehicle_id": {"$in": object_ids}, "status": {"$nin": ["resolved", "rejected", "closed"]}, "$or": [{"severity": "critical"}, {"vehicle_unsafe": True}]}, {"_id": 1, "vehicle_id": 1})
    incidents = grouped("incidents", {"vehicle_id": {"$in": object_ids}, "status": {"$nin": list(TERMINAL_INCIDENTS)}, "can_vehicle_move": False}, {"_id": 1, "vehicle_id": 1})
    compliance = grouped("vehicle_compliance_records", {"vehicle_id": {"$in": object_ids}, "status": "expired"}, {"_id": 1, "vehicle_id": 1})
    priority = {"lifecycle": 0, "fault": 1, "incident": 1, "compliance": 2, "maintenance": 3, "dispatch": 4, "movement": 5, "reservation": 6}
    output = {}
    for object_id in object_ids:
        vehicle = vehicle_map.get(object_id, {})
        lifecycle = str(vehicle.get("status") or "available").strip().lower()
        reasons = []
        if lifecycle == "retired": reasons.append(_reason("lifecycle", "retired", "Vehicle is retired"))
        elif lifecycle in {"out_of_service", "suspended"}: reasons.append(_reason("lifecycle", lifecycle, f"Vehicle is {lifecycle.replace('_', ' ')}"))
        for item, kind, code, message in ((dispatches.get(object_id, []), "dispatch", "active_dispatch", "Vehicle has an active dispatch"), (reservations.get(object_id, []), "reservation", "active_reservation", "Vehicle has an active reservation"), (movements.get(object_id, []), "movement", "active_movement", "Vehicle has an active vehicle movement"), (maintenance.get(object_id, []), "maintenance", "active_maintenance_job", "Vehicle has an active maintenance job"), (faults.get(object_id, []), "fault", "critical_or_unsafe_fault", "Vehicle has a critical or unsafe fault"), (incidents.get(object_id, []), "incident", "vehicle_blocking_incident", "Vehicle has a blocking incident"), (compliance.get(object_id, []), "compliance", "expired_mandatory_compliance", "Vehicle has expired mandatory compliance")):
            if item:
                reasons.append(_reason(kind, code, message, item[0].get("_id")))
        reasons.sort(key=lambda item: priority.get(item["type"], 99))
        assigned = vehicle.get("assigned_driver_id")
        if reasons:
            state = {"lifecycle": "unavailable", "fault": "blocked", "incident": "blocked", "compliance": "blocked", "maintenance": "under_maintenance", "dispatch": "on_dispatch", "movement": "in_movement", "reservation": "reserved"}[reasons[0]["type"]]
            primary = reasons[0]["message"]
        else:
            state, primary = ("assigned", "Assigned permanent driver") if assigned else ("available", None)
        custodian = None
        for source in (dispatches, movements, maintenance):
            item = source.get(object_id, [])
            if item:
                custodian = item[0].get("driver_id") or item[0].get("movement_custodian_id") or item[0].get("maintenance_coordinator_id")
                break
        output[str(object_id)] = {"vehicle_id": str(object_id), "is_available": not reasons, "lifecycle_status": lifecycle if lifecycle not in {"available", "assigned", "maintenance", "accident"} else "active", "operational_state": state, "primary_reason": primary, "blocking_reasons": reasons, "permanent_driver_id": str(assigned) if assigned else None, "current_custodian_id": str(custodian) if custodian else None, "evaluated_at": datetime.now(timezone.utc).isoformat()}
    return output
