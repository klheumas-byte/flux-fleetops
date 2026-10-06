"""Fast, authoritative blocker visibility and controlled recovery actions."""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from bson import ObjectId
from flask import current_app

from extensions import get_collection
from services.vehicle_availability_service import resolve_many, resolve_many_drivers
from utils.api_error import ApiError


VIEW_ROLES = {"owner", "admin", "operations_administrator", "operations_manager"}
RECOVERY_ROLES = {"owner", "admin"}
TERMINAL_MOVEMENTS = {"closed", "cancelled", "force_closed", "superseded", "voided"}
ACTIVE_ASSIGNMENTS = {"pending_handover", "active", "pending_return", "suspended"}
ACTIVE_SOURCE_STATUSES = {
    "dispatch_jobs": {"reserved", "assigned", "accepted", "clarification_requested", "in_progress"},
    "stock_transfers": {"approved", "scheduled", "released", "in_transit"},
    "vehicle_operation_requests": {"approved", "scheduled", "movement_in_progress"},
    "delivery_batches": {"scheduled", "assigned", "in_progress", "SCHEDULED", "ASSIGNED", "IN_PROGRESS", "PUBLISHED", "ISSUED"},
}
SOURCE_CONFIG = {
    "dispatch_job": ("dispatch_jobs", "dispatch_job_id", "dispatch-planner"),
    "stock_transfer": ("stock_transfers", "transfer_id", "stock-transfers"),
    "supplier_pickup": ("stock_transfers", "transfer_id", "supplier-pickup"),
    "vehicle_operation_request": ("vehicle_operation_requests", "request_id", "operational-requests"),
    "personal_vehicle_use": ("vehicle_operation_requests", "request_id", "operational-requests"),
    "delivery_run": ("delivery_batches", "batch_number", "smart-living-deliveries"),
}
OPEN_PAGES = {
    "dispatch": "dispatch-planner", "reservation": "dispatch-planner",
    "movement": "vehicle-movements", "maintenance": "maintenance",
    "fault": "fault-approvals", "incident": "incidents",
    "compliance": "preventive-maintenance", "manual": "vehicles",
    "lifecycle": "vehicles", "assignment": "assignments",
}
DETAIL_COLLECTIONS = {
    "dispatch": "dispatch_jobs", "dispatch_job": "dispatch_jobs", "dispatch_jobs": "dispatch_jobs",
    "movement": "vehicle_movements", "vehicle_movement": "vehicle_movements", "vehicle_movements": "vehicle_movements",
    "reservation": "resource_reservations", "resource_reservation": "resource_reservations", "resource_reservations": "resource_reservations",
    "assignment": "assignments", "assignments": "assignments",
    "maintenance": "maintenance_jobs", "maintenance_jobs": "maintenance_jobs",
    "fault": "faults", "faults": "faults", "incident": "incidents", "incidents": "incidents",
    "compliance": "vehicle_compliance_records", "vehicle_compliance_records": "vehicle_compliance_records",
    "stock_transfer": "stock_transfers", "stock_transfers": "stock_transfers",
    "vehicle_operation_request": "vehicle_operation_requests", "vehicle_operation_requests": "vehicle_operation_requests",
    "delivery_run": "delivery_batches", "delivery_batches": "delivery_batches",
}
SAFETY_BLOCKERS = {"fault", "maintenance", "incident", "compliance", "lifecycle", "manual"}
RECOVERY_BLOCKER_CODES = {"active_source_terminal_movement", "overdue_assignment"}


def _require_view(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized not in VIEW_ROLES:
        raise ApiError("You do not have permission to use Operations Control Center.", status_code=403)
    return normalized


def _require_recovery(role: str) -> str:
    normalized = _require_view(role)
    if normalized not in RECOVERY_ROLES:
        raise ApiError("Only an Owner or Admin can perform recovery actions.", status_code=403)
    return normalized


def _id(value):
    return str(value) if value else None


def _object_id(value, field: str) -> ObjectId:
    if not value or not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field}.", status_code=400)
    return ObjectId(str(value))


def _confirmation(payload: dict) -> str:
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ApiError("A recovery reason is required.", status_code=400)
    if payload.get("physical_state_confirmed") is not True:
        raise ApiError("Confirm the physical vehicle/driver state before recovery.", status_code=400)
    if str(payload.get("confirmation") or "").strip().upper() != "FORCE RELEASE":
        raise ApiError('Type "FORCE RELEASE" to confirm this recovery.', status_code=400)
    return reason


def _is_overdue(value, now: datetime) -> bool:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed < now


def _as_utc(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _iso(value):
    parsed = _as_utc(value)
    return parsed.isoformat() if parsed else None


def _seconds_since(value, now: datetime) -> int | None:
    parsed = _as_utc(value)
    return max(0, int((now - parsed).total_seconds())) if parsed else None


def _issue_context(reason: dict, now: datetime) -> dict:
    scheduled_at = reason.get("scheduled_at") or reason.get("start_time") or reason.get("requested_departure_time")
    movement_started_at = reason.get("movement_started_at") or reason.get("started_at") or reason.get("departure_time")
    movement_ended_at = reason.get("movement_ended_at") or reason.get("returned_at") or reason.get("actual_return_time") or reason.get("completed_at")
    last_activity_at = reason.get("last_activity_at") or reason.get("updated_at") or movement_started_at or scheduled_at or reason.get("created_at")
    end_at = reason.get("end_time") or reason.get("expected_return_time") or reason.get("expected_end_at")
    overdue_seconds = _seconds_since(end_at, now) if _is_overdue(end_at, now) else None
    unresolved_from = last_activity_at or reason.get("assigned_at") or reason.get("created_at")
    blocker_type = str(reason.get("code") or "")
    recovery_required = blocker_type in RECOVERY_BLOCKER_CODES or overdue_seconds is not None
    kind = str(reason.get("type") or "blocker")
    return {
        "task": reason.get("task") or reason.get("title") or reason.get("purpose"),
        "origin": reason.get("origin") or reason.get("pickup_location") or reason.get("source_location"),
        "destination": reason.get("destination") or reason.get("dropoff_location") or reason.get("destination_location"),
        "assigned_at": _iso(reason.get("assigned_at") or reason.get("created_at")),
        "scheduled_at": _iso(scheduled_at),
        "movement_started_at": _iso(movement_started_at),
        "movement_ended_at": _iso(movement_ended_at),
        "last_activity_at": _iso(last_activity_at),
        "overdue_seconds": overdue_seconds,
        "unresolved_seconds": _seconds_since(unresolved_from, now),
        "asset_blocked": kind in SAFETY_BLOCKERS,
        "recovery_required": recovery_required,
    }


def _actions_for_reason(reason: dict, *, now: datetime) -> list[str]:
    kind = reason.get("type")
    actions = ["open_record", "recheck"]
    if kind == "movement":
        actions[1:1] = ["resolve", "force_close_movement"]
    elif kind == "reservation" and _is_overdue(reason.get("end_time"), now):
        actions[1:1] = ["resolve", "release_reservation"]
    elif kind == "dispatch":
        actions.insert(1, "reassign")
    elif kind == "maintenance":
        actions.insert(1, "resolve_maintenance")
    return actions


def _recommendation(reason: dict) -> str:
    return {
        "dispatch": "Open the active dispatch to continue, reassign, or restart its movement.",
        "movement": "Complete the normal return flow, or force close only after physical verification.",
        "reservation": "Open the owning operation; release only if the reservation is confirmed stale.",
        "maintenance": "Complete or cancel the maintenance job through its normal workflow.",
        "fault": "Resolve the safety fault before returning the vehicle to work.",
        "incident": "Resolve the incident and confirm the vehicle can move.",
        "compliance": "Renew or resolve the expired compliance record.",
        "manual": "Review and clear the manual unavailability state when appropriate.",
        "lifecycle": "Review the asset lifecycle status.",
        "assignment": "Complete the return workflow, or force release after physical verification.",
    }.get(reason.get("type"), "Open the blocking record and use its normal workflow.")


def _issue_from_reason(*, asset_type: str, asset: dict, reason: dict, now: datetime) -> dict:
    kind = str(reason.get("type") or "blocker")
    entity_id = reason.get("entity_id")
    page = OPEN_PAGES.get(kind, "vehicles" if asset_type == "vehicle" else "drivers")
    context = _issue_context(reason, now)
    actions = _actions_for_reason(reason, now=now)
    return {
        "id": f"{asset_type}:{asset['_id']}:{kind}:{entity_id or reason.get('code')}",
        "kind": kind, "blocker_type": reason.get("code") or kind,
        "title": asset.get("registration_number") or asset.get("full_name") or f"{asset_type.title()} blocker",
        "asset_type": asset_type,
        "vehicle_id": _id(asset["_id"]) if asset_type == "vehicle" else _id(reason.get("vehicle_id")),
        "driver_id": _id(asset["_id"]) if asset_type == "driver" else _id(reason.get("driver_id") or asset.get("assigned_driver_id")),
        "source_type": reason.get("source_type") or kind,
        "source_id": reason.get("source_id") or entity_id,
        "source_reference": reason.get("reference") or entity_id,
        "current_status": reason.get("status"),
        "movement_id": reason.get("movement_id") or (entity_id if kind == "movement" else None),
        "reservation_id": entity_id if kind == "reservation" else None,
        "assignment_id": entity_id if kind == "assignment" else None,
        "blocker": reason.get("message") or "Operational blocker",
        "preventing": "New assignments and movement starts",
        "recommended_action": _recommendation(reason),
        "allowed_actions": actions,
        "primary_action": next((action for action in actions if action not in {"open_record", "recheck"}), "open_record"),
        **context,
        "timeline_available": bool(entity_id or reason.get("source_id") or reason.get("movement_id")),
        "open_target": {"page": page, "record_id": reason.get("source_id") or entity_id},
        "detail": reason,
    }


def _terminal_link_issues(now: datetime) -> list[dict]:
    movements = list(get_collection("vehicle_movements").find(
        {"status": {"$in": sorted(TERMINAL_MOVEMENTS)}, "$or": [{"superseded_by_movement_id": {"$exists": False}}, {"superseded_by_movement_id": None}], "source_type": {"$in": sorted(SOURCE_CONFIG)}},
        {"status": 1, "movement_id": 1, "source_type": 1, "source_id": 1, "source_reference": 1,
         "vehicle_id": 1, "driver_id": 1, "stock_transfer_id": 1, "operation_request_id": 1,
         "personal_vehicle_request_id": 1, "delivery_run_id": 1, "dispatch_job_id": 1,
         "created_at": 1, "updated_at": 1, "requested_departure_time": 1, "expected_return_time": 1,
         "started_at": 1, "departure_time": 1, "returned_at": 1, "actual_return_time": 1,
         "completed_at": 1, "origin": 1, "destination": 1, "pickup_location": 1, "dropoff_location": 1},
    ))
    by_collection: dict[str, set[ObjectId]] = defaultdict(set)
    source_id_by_movement = {}
    for movement in movements:
        source_type = str(movement.get("source_type") or "").lower()
        config = SOURCE_CONFIG.get(source_type)
        source_id = movement.get("source_id")
        if source_type == "dispatch_job":
            source_id = movement.get("dispatch_job_id") or source_id
        elif source_type in {"stock_transfer", "supplier_pickup"}:
            source_id = movement.get("stock_transfer_id") or source_id
        elif source_type in {"vehicle_operation_request", "personal_vehicle_use"}:
            source_id = movement.get("operation_request_id") or movement.get("personal_vehicle_request_id") or source_id
        elif source_type == "delivery_run":
            source_id = movement.get("delivery_run_id") or source_id
        if config and isinstance(source_id, ObjectId):
            by_collection[config[0]].add(source_id)
            source_id_by_movement[movement["_id"]] = source_id
    sources = {}
    source_projection = {
        "status": 1, "linked_vehicle_movement_id": 1, "movement_id": 1, "dispatch_job_id": 1,
        "transfer_id": 1, "request_id": 1, "run_id": 1, "batch_number": 1, "vehicle_id": 1, "driver_id": 1,
        "title": 1, "purpose": 1, "origin": 1, "destination": 1, "pickup_location": 1, "dropoff_location": 1,
        "assigned_at": 1, "scheduled_at": 1, "scheduled_start_time": 1, "planned_departure_at": 1,
        "expected_return_at": 1, "expected_return_time": 1, "created_at": 1, "updated_at": 1,
    }
    source_collections = {name: get_collection(name) for name in by_collection}
    with ThreadPoolExecutor(max_workers=max(1, len(by_collection))) as executor:
        futures = {
            name: executor.submit(lambda collection=source_collections[name], source_ids=ids: list(collection.find({"_id": {"$in": list(source_ids)}}, source_projection)))
            for name, ids in by_collection.items()
        }
        for collection_name, future in futures.items():
            for source in future.result():
                sources[(collection_name, source["_id"])] = source
    issues = []
    for movement in movements:
        config = SOURCE_CONFIG.get(str(movement.get("source_type") or "").lower())
        source_id = source_id_by_movement.get(movement["_id"])
        source = sources.get((config[0], source_id)) if config and source_id else None
        if not source or source.get("status") not in ACTIVE_SOURCE_STATUSES.get(config[0], set()):
            continue
        linked_id = source.get("linked_vehicle_movement_id") or source.get("movement_id")
        if isinstance(linked_id, ObjectId) and linked_id != movement["_id"]:
            continue
        reference = source.get(config[1]) or movement.get("source_reference") or str(source["_id"])
        detail = {
            "movement_status": movement.get("status"), "evaluated_at": now.isoformat(),
            "task": source.get("title") or source.get("purpose"),
            "origin": source.get("origin") or source.get("pickup_location") or movement.get("origin") or movement.get("pickup_location"),
            "destination": source.get("destination") or source.get("dropoff_location") or movement.get("destination") or movement.get("dropoff_location"),
            "assigned_at": source.get("assigned_at") or source.get("created_at"),
            "scheduled_at": source.get("scheduled_at") or source.get("scheduled_start_time") or source.get("planned_departure_at"),
            "expected_return_time": source.get("expected_return_at") or source.get("expected_return_time") or movement.get("expected_return_time"),
            "started_at": movement.get("started_at"), "departure_time": movement.get("departure_time"),
            "returned_at": movement.get("returned_at"), "actual_return_time": movement.get("actual_return_time"),
            "completed_at": movement.get("completed_at"), "created_at": movement.get("created_at"),
            "updated_at": source.get("updated_at") or movement.get("updated_at"),
        }
        context = _issue_context({"type": "terminal_link", "code": "active_source_terminal_movement", **detail}, now)
        issues.append({
            "id": f"terminal_link:{movement['_id']}", "kind": "terminal_link",
            "blocker_type": "active_source_terminal_movement", "title": "Active task linked to a terminal movement",
            "asset_type": "vehicle", "vehicle_id": _id(movement.get("vehicle_id")), "driver_id": _id(movement.get("driver_id")),
            "source_type": config[0], "source_id": _id(source["_id"]), "source_reference": reference,
            "current_status": source.get("status"), "movement_id": _id(movement["_id"]),
            "blocker": f"Movement {movement.get('movement_id') or movement['_id']} is {movement.get('status')}",
            "preventing": "The active source task cannot start or advance.",
            "recommended_action": "Restart the movement to preserve history and create one linked replacement.",
            "allowed_actions": ["restart_movement", "resolve", "reassign", "open_record", "recheck"],
            "primary_action": "restart_movement", **context, "timeline_available": True,
            "open_target": {"page": config[2], "record_id": _id(source["_id"])},
            "detail": detail,
        })
    return issues


def _overdue_assignment_issues(now: datetime) -> list[dict]:
    issues = []
    for assignment in get_collection("assignments").find(
        {"allocation_active": True, "status": {"$in": sorted(ACTIVE_ASSIGNMENTS)}, "expected_end_at": {"$lt": now}},
        {"status": 1, "vehicle_id": 1, "driver_id": 1, "expected_end_at": 1, "assigned_at": 1, "created_at": 1, "updated_at": 1},
    ):
        detail = {"end_time": assignment.get("expected_end_at"), "assigned_at": assignment.get("assigned_at") or assignment.get("created_at"), "updated_at": assignment.get("updated_at")}
        context = _issue_context({"type": "assignment", "code": "overdue_assignment", **detail}, now)
        issues.append({
            "id": f"assignment:{assignment['_id']}", "kind": "assignment", "blocker_type": "overdue_assignment",
            "title": "Overdue active assignment", "asset_type": "vehicle", "vehicle_id": _id(assignment.get("vehicle_id")),
            "driver_id": _id(assignment.get("driver_id")), "source_type": "assignment", "source_id": _id(assignment["_id"]),
            "source_reference": _id(assignment["_id"]), "current_status": assignment.get("status"), "assignment_id": _id(assignment["_id"]),
            "blocker": "Assignment remains active after its expected end time.", "preventing": "A new permanent allocation may be rejected.",
            "recommended_action": "Complete the return handover, or force release after confirming physical custody.",
            "allowed_actions": ["resolve", "open_record", "release_assignment", "recheck"],
            "primary_action": "release_assignment", **context, "timeline_available": True,
            "open_target": {"page": "assignments", "record_id": _id(assignment["_id"])},
            "detail": {**detail, "end_time": _iso(detail["end_time"])},
        })
    return issues


def get_control_center(*, current_role: str) -> dict:
    _require_view(current_role)
    now = datetime.now(timezone.utc)
    app = current_app._get_current_object()
    vehicle_collection = get_collection("vehicles")
    user_collection = get_collection("users")
    vehicle_projection = {
        "registration_number": 1, "status": 1, "assigned_driver_id": 1, "current_custodian_id": 1,
        "manual_availability_status": 1, "manual_availability_reason": 1,
    }
    driver_projection = {
        "full_name": 1, "status": 1, "driver_profile.approval_status": 1,
        "driver_profile.manual_availability_status": 1, "driver_profile.manual_availability_reason": 1,
        "driver_profile.manual_availability_note": 1, "driver_profile.manual_availability_updated_by": 1,
        "driver_profile.manual_availability_updated_at": 1,
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        vehicle_future = executor.submit(lambda: list(vehicle_collection.find({}, vehicle_projection)))
        driver_future = executor.submit(lambda: list(user_collection.find({"role": "driver"}, driver_projection)))
        vehicles = vehicle_future.result()
        drivers = driver_future.result()

    def in_app_context(callback):
        with app.app_context():
            return callback()

    with ThreadPoolExecutor(max_workers=4) as executor:
        vehicle_future = executor.submit(in_app_context, lambda: resolve_many([row["_id"] for row in vehicles], vehicle_documents=vehicles))
        driver_future = executor.submit(in_app_context, lambda: resolve_many_drivers([row["_id"] for row in drivers], driver_documents=drivers))
        terminal_future = executor.submit(in_app_context, lambda: _terminal_link_issues(now))
        assignment_future = executor.submit(in_app_context, lambda: _overdue_assignment_issues(now))
        vehicle_availability = vehicle_future.result()
        driver_availability = driver_future.result()
        terminal_issues = terminal_future.result()
        assignment_issues = assignment_future.result()
    issues = []
    vehicle_rows = []
    driver_rows = []
    for vehicle in vehicles:
        state = vehicle_availability.get(str(vehicle["_id"]), {})
        vehicle_rows.append({"id": _id(vehicle["_id"]), "label": vehicle.get("registration_number") or "Vehicle", **state})
        issues.extend(_issue_from_reason(asset_type="vehicle", asset=vehicle, reason=reason, now=now) for reason in state.get("blocking_reasons") or [])
    for driver in drivers:
        state = driver_availability.get(str(driver["_id"]), {})
        driver_rows.append({"id": _id(driver["_id"]), "label": driver.get("full_name") or "Driver", **state})
        issues.extend(_issue_from_reason(asset_type="driver", asset=driver, reason=reason, now=now) for reason in state.get("blocking_reasons") or [])
    issues.extend(terminal_issues)
    issues.extend(assignment_issues)

    vehicle_labels = {_id(item["_id"]): item.get("registration_number") or "Vehicle" for item in vehicles}
    driver_labels = {_id(item["_id"]): item.get("full_name") or "Driver" for item in drivers}
    for issue in issues:
        issue["vehicle_label"] = vehicle_labels.get(issue.get("vehicle_id"))
        issue["driver_label"] = driver_labels.get(issue.get("driver_id"))

    counts = {"vehicles": {"available": 0, "active": 0, "maintenance": 0, "blocked": 0}, "drivers": {"available": 0, "active": 0, "blocked": 0}}
    for row in vehicle_rows:
        key = "available" if row.get("is_available") else "maintenance" if row.get("operational_state") == "under_maintenance" else "active" if row.get("operational_state") in {"on_dispatch", "in_movement"} else "blocked"
        counts["vehicles"][key] += 1
    for row in driver_rows:
        key = "available" if row.get("is_available") else "active" if row.get("operational_state") in {"on_dispatch", "in_movement"} else "blocked"
        counts["drivers"][key] += 1

    groups = []
    for asset_type, rows, id_field in (("vehicle", vehicle_rows, "vehicle_id"), ("driver", driver_rows, "driver_id")):
        for row in rows:
            blockers = [issue for issue in issues if issue.get(id_field) == row["id"]]
            if any(issue.get("recovery_required") for issue in blockers):
                recovery_state = "recovery_required"
            elif not row.get("is_available", False):
                recovery_state = "blocked"
            elif blockers or row.get("active_restrictions"):
                recovery_state = "available_with_attention"
            else:
                recovery_state = "available"
            groups.append({
                "asset_type": asset_type, "asset_id": row["id"], "label": row["label"],
                "is_available": row.get("is_available", False), "operational_state": row.get("operational_state"),
                "recovery_state": recovery_state, "blockers": blockers,
            })
    return {"overview": counts, "issues": issues, "groups": groups, "vehicles": vehicle_rows, "drivers": driver_rows, "generated_at": now.isoformat()}


def get_control_timeline(
    *, current_role: str, source_type=None, source_id=None, movement_id=None,
    reservation_id=None, assignment_id=None,
) -> dict:
    """Lazy, bounded history lookup for one selected blocker."""
    _require_view(current_role)
    requested = []

    def add(collection_name, value, label):
        if value and ObjectId.is_valid(str(value)):
            key = (collection_name, str(value))
            if key not in {(item[0], item[1]) for item in requested}:
                requested.append((collection_name, str(value), label))

    normalized_source = str(source_type or "").strip().lower()
    source_collection = DETAIL_COLLECTIONS.get(normalized_source)
    if source_collection:
        add(source_collection, source_id, normalized_source or "source")
    add("vehicle_movements", movement_id, "movement")
    add("resource_reservations", reservation_id, "reservation")
    add("assignments", assignment_id, "assignment")
    if not requested:
        raise ApiError("A valid blocker record is required for the timeline.", status_code=400)

    projection = {
        "status": 1, "created_at": 1, "updated_at": 1, "reported_at": 1, "detected_at": 1,
        "assigned_at": 1, "scheduled_at": 1, "scheduled_start_time": 1, "start_time": 1,
        "started_at": 1, "departure_time": 1, "returned_at": 1, "actual_return_time": 1,
        "completed_at": 1, "closed_at": 1, "cancelled_at": 1, "released_at": 1,
        "status_history": 1, "audit_log": 1, "history": 1, "participant_comments": 1,
        "movement_id": 1, "dispatch_job_id": 1, "transfer_id": 1, "request_id": 1,
        "maintenance_id": 1, "fault_id": 1, "incident_id": 1, "batch_number": 1,
    }
    collections = {name: get_collection(name) for name, _value, _label in requested}

    def load(spec):
        name, value, label = spec
        return spec, collections[name].find_one({"_id": ObjectId(value)}, projection)

    with ThreadPoolExecutor(max_workers=min(4, len(requested))) as executor:
        loaded = list(executor.map(load, requested))

    events = []
    records = []
    for (collection_name, value, label), document in loaded:
        if not document:
            continue
        reference = next((document.get(field) for field in ("movement_id", "dispatch_job_id", "transfer_id", "request_id", "maintenance_id", "fault_id", "incident_id", "batch_number") if document.get(field)), value)
        records.append({"type": label, "id": value, "reference": str(reference), "status": document.get("status")})
        for field in ("status_history", "audit_log", "history", "participant_comments"):
            for item in document.get(field) or []:
                if not isinstance(item, dict):
                    continue
                timestamp = item.get("timestamp") or item.get("at") or item.get("created_at") or item.get("updated_at")
                events.append({
                    "record_type": label, "record_id": value,
                    "event": str(item.get("event") or item.get("status") or item.get("action") or ("comment" if field == "participant_comments" else field)),
                    "status": item.get("status"), "timestamp": _iso(timestamp),
                    "actor_id": _id(item.get("actor_id") or item.get("created_by") or item.get("user_id")),
                    "note": item.get("note") or item.get("reason") or item.get("message") or item.get("comment"),
                })
        if not any(event["record_id"] == value for event in events):
            events.append({
                "record_type": label, "record_id": value, "event": "record_created",
                "status": document.get("status"), "timestamp": _iso(document.get("created_at") or document.get("reported_at") or document.get("detected_at")),
                "actor_id": None, "note": None,
            })
    events.sort(key=lambda item: item.get("timestamp") or "")
    return {"records": records, "events": events}


def _release_reservation(payload: dict, *, actor_id: ObjectId, reason: str) -> dict:
    issue = payload.get("issue") or {}
    reservation_id = _object_id(payload.get("reservation_id") or issue.get("reservation_id"), "reservation_id")
    timestamp = datetime.now(timezone.utc)
    event = {"event": "force_released", "actor_id": actor_id, "timestamp": timestamp, "reason": reason, "physical_state_confirmed": True}
    collection = get_collection("resource_reservations")
    reservation = collection.find_one({"_id": reservation_id})
    if not reservation:
        raise ApiError("Reservation not found.", status_code=404)
    if reservation.get("status") == "released":
        return {"type": "resource_reservation", "id": str(reservation_id), "status": "released"}
    linked_movement_id = reservation.get("movement_id") or reservation.get("vehicle_movement_id")
    linked_movement = get_collection("vehicle_movements").find_one(
        {"_id": linked_movement_id}, {"status": 1},
    ) if isinstance(linked_movement_id, ObjectId) else None
    stale = _is_overdue(reservation.get("end_time"), timestamp) or (
        linked_movement is not None and linked_movement.get("status") in TERMINAL_MOVEMENTS
    )
    if not stale:
        raise ApiError("This reservation is not stale. Resolve it through the active source workflow.", status_code=409)
    result = collection.update_one(
        {"_id": reservation_id, "status": {"$in": ["reserved", "consumed"]}},
        {"$set": {"status": "released", "released_at": timestamp, "released_by": actor_id, "release_reason": reason, "updated_at": timestamp}, "$push": {"audit_log": event}},
    )
    if result.matched_count != 1:
        existing = collection.find_one({"_id": reservation_id}, {"status": 1})
        if not existing:
            raise ApiError("Reservation not found.", status_code=404)
        if existing.get("status") != "released":
            raise ApiError("Reservation changed while recovery was being applied.", status_code=409)
    return {"type": "resource_reservation", "id": str(reservation_id), "status": "released"}


def _restart_source_movement(payload: dict, *, current_user_id: str, reason: str) -> dict:
    issue = payload.get("issue") or {}
    source_type = str(payload.get("source_type") or issue.get("source_type") or "").strip().lower()
    source_id = _object_id(payload.get("source_id") or issue.get("source_id"), "source_id")
    if source_type not in ACTIVE_SOURCE_STATUSES:
        config = SOURCE_CONFIG.get(source_type)
        source_type = config[0] if config else source_type
    source = get_collection(source_type).find_one({"_id": source_id}) if source_type in ACTIVE_SOURCE_STATUSES else None
    if not source:
        raise ApiError("Active source record not found.", status_code=404)
    if source.get("status") not in ACTIVE_SOURCE_STATUSES[source_type]:
        raise ApiError("The source workflow is no longer active.", status_code=409)
    if source_type == "dispatch_jobs":
        from services.movement_source_service import ensure_dispatch_movement
        movement = ensure_dispatch_movement(source, current_user_id=current_user_id, initial_status="approved")["movement"]
    elif source_type == "stock_transfers":
        from services.stock_transfer_service import _ensure_movement
        movement = _ensure_movement(source, current_user_id=current_user_id)
    elif source_type == "vehicle_operation_requests":
        from services.vehicle_operation_request_service import _ensure_request_movement
        movement = _ensure_request_movement(source, current_user_id=current_user_id)
    elif source_type == "delivery_batches":
        from services.smart_living_delivery_service import _ensure_run_vehicle_movement
        movement = _ensure_run_vehicle_movement(source, current_user_id)
    else:
        raise ApiError("This source workflow does not support movement restart.", status_code=400)
    timestamp = datetime.now(timezone.utc)
    get_collection("vehicle_movements").update_one(
        {"_id": movement["_id"]},
        {"$push": {"audit_log": {"event": "operations_control_restart", "actor_id": ObjectId(current_user_id), "timestamp": timestamp, "reason": reason}}},
    )
    return {"type": "vehicle_movement", "id": str(movement["_id"]), "status": movement.get("status"), "replaces_movement_id": _id(movement.get("replaces_movement_id"))}


def _source_record(issue: dict) -> tuple[str | None, ObjectId | None, dict | None]:
    source_type = str(issue.get("source_type") or "").strip().lower()
    if source_type not in ACTIVE_SOURCE_STATUSES:
        config = SOURCE_CONFIG.get(source_type)
        source_type = config[0] if config else source_type
    source_id = issue.get("source_id")
    if source_type not in ACTIVE_SOURCE_STATUSES or not ObjectId.is_valid(str(source_id or "")):
        return None, None, None
    object_id = ObjectId(str(source_id))
    return source_type, object_id, get_collection(source_type).find_one({"_id": object_id})


def _resolve_terminal_source(
    issue: dict, *, resolution: str, actor_id: ObjectId, reason: str,
) -> dict | None:
    """Close an active source whose linked movement is already terminal.

    Normal source completion APIs require physical workflow evidence that a recovery
    screen cannot invent. This owner/admin recovery records the override explicitly,
    preserves the source and movement, and releases only reservations linked to that
    exact source or movement.
    """
    source_type, source_id, source = _source_record(issue)
    if not source_type or not source_id or not source:
        return None
    if source.get("status") not in ACTIVE_SOURCE_STATUSES[source_type]:
        return {"type": source_type, "id": str(source_id), "status": source.get("status"), "resolution": resolution}

    timestamp = datetime.now(timezone.utc)
    if resolution == "physically_completed":
        if source_type == "stock_transfers":
            target_status = "awaiting_receipt"
        elif source_type == "vehicle_operation_requests" and source.get("operation_type") != "personal_use":
            target_status = "awaiting_verification"
        elif source_type == "delivery_batches":
            target_status = "EXECUTION_COMPLETED" if str(source.get("status") or "").isupper() else "awaiting_reconciliation"
        else:
            target_status = "completed"
        disposition = "force_completed"
    else:
        target_status = "CANCELLED" if source_type == "delivery_batches" and str(source.get("status") or "").isupper() else "cancelled"
        disposition = "voided" if resolution == "stale_incorrect_record" else "cancelled"
    event = {
        "event": "operations_control_resolved", "status": target_status,
        "resolution": resolution, "disposition": disposition,
        "actor_id": actor_id, "timestamp": timestamp, "reason": reason,
    }
    outcome_fields = (
        {"physical_operation_completed_at": timestamp, "physical_operation_completed_by": actor_id}
        if resolution == "physically_completed" else
        {"cancelled_at": timestamp, "cancelled_by": actor_id, "cancellation_reason": reason}
    )
    if str(target_status).lower() == "completed":
        outcome_fields.update({"completed_at": timestamp, "completed_by": actor_id})
    result = get_collection(source_type).update_one(
        {"_id": source_id, "status": {"$in": sorted(ACTIVE_SOURCE_STATUSES[source_type])}},
        {"$set": {
            "status": target_status, "recovery_disposition": disposition,
            "recovery_resolved_at": timestamp, "recovery_resolved_by": actor_id,
            "recovery_reason": reason, "updated_at": timestamp,
            **outcome_fields,
        }, "$push": {"audit_log": event, "status_history": event}},
    )
    if result.matched_count != 1:
        latest = get_collection(source_type).find_one({"_id": source_id}, {"status": 1})
        if not latest or latest.get("status") in ACTIVE_SOURCE_STATUSES[source_type]:
            raise ApiError("The source changed while recovery was being applied. Recheck and try again.", status_code=409)
        target_status = latest.get("status")

    movement_id = issue.get("movement_id")
    linked_values = [{"source_id": source_id}]
    if ObjectId.is_valid(str(movement_id or "")):
        movement_object_id = ObjectId(str(movement_id))
        linked_values.extend([{"movement_id": movement_object_id}, {"vehicle_movement_id": movement_object_id}])
    reservation_event = {
        "event": "released_by_source_recovery", "actor_id": actor_id,
        "timestamp": timestamp, "reason": reason, "source_id": source_id,
    }
    get_collection("resource_reservations").update_many(
        {"status": {"$in": ["reserved", "consumed"]}, "$or": linked_values},
        {"$set": {
            "status": "released", "released_at": timestamp, "released_by": actor_id,
            "release_reason": reason, "updated_at": timestamp,
        }, "$push": {"audit_log": reservation_event}},
    )
    return {"type": source_type, "id": str(source_id), "status": target_status, "resolution": resolution}


def _movement_status(movement_id) -> str | None:
    if not ObjectId.is_valid(str(movement_id or "")):
        return None
    movement = get_collection("vehicle_movements").find_one({"_id": ObjectId(str(movement_id))}, {"status": 1})
    if not movement:
        raise ApiError("Vehicle movement not found.", status_code=404)
    return movement.get("status")


def execute_control_action(payload: dict, *, current_user_id: str, current_role: str) -> dict:
    _require_view(current_role)
    action = str(payload.get("action") or "").strip().lower()
    if action == "recheck":
        return {"action": action, "control_center": get_control_center(current_role=current_role)}
    _require_recovery(current_role)
    if not ObjectId.is_valid(str(current_user_id)):
        raise ApiError("Invalid recovery actor.", status_code=400)
    actor_id = ObjectId(str(current_user_id))
    reason = str(payload.get("reason") or "").strip()
    affected = []
    if action == "resolve":
        resolution = str(payload.get("resolution") or "").strip().lower()
        if resolution not in {"continue_operation", "physically_completed", "cancelled", "reassignment_required", "stale_incorrect_record"}:
            raise ApiError("Select a valid resolution outcome.", status_code=400)
        if not reason:
            raise ApiError("A recovery reason is required.", status_code=400)
        issue = payload.get("issue") or {}
        movement_id = payload.get("movement_id") or issue.get("movement_id")
        if resolution == "continue_operation":
            affected.append(_restart_source_movement(payload, current_user_id=current_user_id, reason=reason))
        elif resolution == "stale_incorrect_record" and issue.get("reservation_id"):
            _confirmation(payload)
            affected.append(_release_reservation(payload, actor_id=actor_id, reason=reason))
        elif resolution == "stale_incorrect_record" and issue.get("assignment_id"):
            _confirmation(payload)
            from services.assignment_service import force_release_assignment
            assignment = force_release_assignment(str(issue["assignment_id"]), current_user_id=current_user_id, current_role=current_role, reason=reason, physical_state_confirmed=True)
            affected.append({"type": "assignment", "id": str(issue["assignment_id"]), "status": assignment.get("status"), "resolution": resolution})
        elif resolution in {"physically_completed", "stale_incorrect_record"} and movement_id:
            _confirmation(payload)
            status = _movement_status(movement_id)
            if status not in TERMINAL_MOVEMENTS:
                from services.vehicle_movement_service import force_close_vehicle_movement
                movement = force_close_vehicle_movement(
                    str(movement_id), {"reason": reason, "physical_vehicle_confirmed": True},
                    current_user_id=current_user_id, current_role=current_role,
                )
                status = movement.get("status")
            affected.append({"type": "vehicle_movement", "id": str(movement_id), "status": status, "resolution": resolution})
            source_result = _resolve_terminal_source(issue, resolution=resolution, actor_id=actor_id, reason=reason)
            if source_result:
                affected.append(source_result)
        elif resolution == "cancelled" and movement_id:
            _confirmation(payload)
            status = _movement_status(movement_id)
            if status not in TERMINAL_MOVEMENTS:
                from services.vehicle_movement_service import cancel_vehicle_movement
                movement = cancel_vehicle_movement(
                    str(movement_id), {"cancellation_reason": reason},
                    current_user_id=current_user_id, current_role=current_role,
                )
                status = movement.get("status")
            affected.append({"type": "vehicle_movement", "id": str(movement_id), "status": status, "resolution": resolution})
            source_result = _resolve_terminal_source(issue, resolution=resolution, actor_id=actor_id, reason=reason)
            if source_result:
                affected.append(source_result)
        elif resolution == "reassignment_required":
            source_collection = DETAIL_COLLECTIONS.get(str(issue.get("source_type") or "").lower())
            source_id = issue.get("source_id")
            if source_collection and source_id and ObjectId.is_valid(str(source_id)):
                get_collection(source_collection).update_one(
                    {"_id": ObjectId(str(source_id))},
                    {"$push": {"audit_log": {"event": "reassignment_required", "actor_id": actor_id, "timestamp": datetime.now(timezone.utc), "reason": reason}}},
                )
            affected.append({"type": "reassignment", "id": str(source_id or ""), "status": "required", "resolution": resolution})
        else:
            raise ApiError("That resolution is not valid for this blocker. Open the owning workflow instead.", status_code=409)
    elif action == "restart_movement":
        if not reason:
            raise ApiError("A recovery reason is required.", status_code=400)
        affected.append(_restart_source_movement(payload, current_user_id=current_user_id, reason=reason))
    elif action == "force_close_movement":
        reason = _confirmation(payload)
        movement_id = payload.get("movement_id") or (payload.get("issue") or {}).get("movement_id")
        if not movement_id:
            raise ApiError("movement_id is required.", status_code=400)
        from services.vehicle_movement_service import force_close_vehicle_movement
        movement = force_close_vehicle_movement(
            str(movement_id), {"reason": reason, "physical_vehicle_confirmed": True},
            current_user_id=current_user_id, current_role=current_role,
        )
        affected.append({"type": "vehicle_movement", "id": str(movement_id), "status": movement.get("status")})
    elif action == "release_reservation":
        reason = _confirmation(payload)
        affected.append(_release_reservation(payload, actor_id=actor_id, reason=reason))
    elif action == "release_assignment":
        reason = _confirmation(payload)
        assignment_id = payload.get("assignment_id") or (payload.get("issue") or {}).get("assignment_id")
        from services.assignment_service import force_release_assignment
        assignment = force_release_assignment(str(assignment_id), current_user_id=current_user_id, current_role=current_role, reason=reason, physical_state_confirmed=True)
        affected.append({"type": "assignment", "id": str(assignment_id), "status": assignment.get("status")})
    else:
        raise ApiError("This recovery action is not valid for the selected blocker.", status_code=400)
    # Keep the completed mutation independent from the comparatively expensive
    # dashboard query. The client performs a separate, deduplicated GET so a
    # refresh timeout cannot make a successful recovery look like a failure.
    return {"action": action, "affected_records": affected}
