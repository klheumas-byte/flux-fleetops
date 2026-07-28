"""Fleet Owner account management and strictly vehicle-scoped read models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.assignment import serialize_assignment
from models.collection import serialize_collection
from models.fault import serialize_fault
from models.fuel import serialize_fuel_log
from models.maintenance import serialize_maintenance_job
from models.ride import serialize_ride
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.auth_service import create_user
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


RECOGNIZED_COLLECTION_STATUSES = {"approved"}
OPERATING_EXPENSE_STATUSES = {"approved", "paid"}
FUEL_COST_STATUSES = {"approved"}
MAINTENANCE_COST_STATUSES = {"approved", "in_progress", "completed"}
OPEN_FAULT_STATUSES = {
    "reported", "pending", "under_review", "approved", "converted_to_maintenance",
    "info_requested",
}
ACTIVE_MAINTENANCE_STATUSES = {"pending", "approved", "scheduled", "in_progress"}
FLEET_OWNER_REQUEST_TYPES = {"maintenance", "vehicle_withdrawal", "driver_reassignment"}


def now_utc():
    return datetime.now(timezone.utc)


def ensure_fleet_owner_indexes():
    ensure_indexes_for_collection(
        get_collection("fleet_owner_audit"),
        [
            {"keys": [("actor_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("entity_type", ASCENDING), ("entity_id", ASCENDING), ("created_at", DESCENDING)]},
        ],
        collection_name="fleet_owner_audit",
    )
    ensure_indexes_for_collection(
        get_collection("fleet_owner_participation_requests"),
        [
            {"keys": [("fleet_owner_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("request_type", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="fleet_owner_participation_requests",
    )


def _oid(value, field_name="id"):
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field_name}.", status_code=404)
    return ObjectId(str(value))


def _iso(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _date_bounds(start_date=None, end_date=None):
    today = now_utc().date()
    try:
        start = datetime.fromisoformat(str(start_date)).date() if start_date else today - timedelta(days=6)
        end = datetime.fromisoformat(str(end_date)).date() if end_date else today
    except ValueError as error:
        raise ApiError("Dates must use YYYY-MM-DD format.", status_code=400) from error
    if start > end:
        raise ApiError("start_date cannot be after end_date.", status_code=400)
    return start.isoformat(), end.isoformat()


def _audit(actor_id, action, entity_type, entity_id, before=None, after=None):
    get_collection("fleet_owner_audit").insert_one(
        {
            "actor_id": _oid(actor_id, "actor_id"),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "before": before,
            "after": after,
            "created_at": now_utc(),
            "immutable": True,
        }
    )


def _owner_profile_for_account(account_id, *, require_active=True):
    account_object_id = _oid(account_id, "account_id")
    user = get_collection("users").find_one({"_id": account_object_id, "role": "fleet_owner"})
    if not user:
        raise ApiError("Fleet Owner account not found.", status_code=404)
    if require_active and user.get("status") != "active":
        raise ApiError("This Fleet Owner account is inactive.", status_code=403)
    profile = get_collection("fleet_owners").find_one({"account_id": account_object_id})
    if not profile:
        raise ApiError("Fleet Owner profile is not linked to this account.", status_code=403)
    if require_active and profile.get("status", "active") != "active":
        raise ApiError("This Fleet Owner profile is inactive.", status_code=403)
    return user, profile


def _owner_vehicle_ids(account_id):
    _, profile = _owner_profile_for_account(account_id)
    return [
        item["_id"]
        for item in get_collection("vehicles").find(
            {"fleet_owner_id": profile["_id"], "ownership_type": "third_party_owned"},
            {"_id": 1},
        )
    ]


def require_owned_vehicle(account_id, vehicle_id):
    vehicle_object_id = _oid(vehicle_id, "vehicle_id")
    if vehicle_object_id not in set(_owner_vehicle_ids(account_id)):
        # Deliberately return 404 so an owner cannot enumerate another tenant's IDs.
        raise ApiError("Vehicle not found.", status_code=404)
    vehicle = get_collection("vehicles").find_one({"_id": vehicle_object_id})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _serialize_participation_request(document):
    return {
        "id": str(document["_id"]), "request_type": document["request_type"],
        "vehicle_id": str(document["vehicle_id"]), "fleet_owner_id": str(document["fleet_owner_id"]),
        "vehicle_registration": document.get("vehicle_registration"),
        "requested_by": str(document["requested_by"]), "reporter_role": "fleet_owner",
        "reason": document.get("reason"), "details": document.get("details") or {},
        "attachments": document.get("attachments") or [],
        "status_history": [
            {"status": item.get("status"), "changed_by": str(item.get("changed_by")) if item.get("changed_by") else None,
             "changed_at": _iso(item.get("changed_at"))}
            for item in document.get("history") or []
        ],
        "status": document.get("status"), "reviewed_by": str(document.get("reviewed_by")) if document.get("reviewed_by") else None,
        "review_note": document.get("review_note"), "created_at": _iso(document.get("created_at")),
        "reviewed_at": _iso(document.get("reviewed_at")), "updated_at": _iso(document.get("updated_at")),
    }


def create_participation_request(account_id, payload):
    request_type = str(payload.get("request_type") or "").strip().lower()
    if request_type not in FLEET_OWNER_REQUEST_TYPES:
        raise ApiError("request_type must be maintenance, vehicle_withdrawal, or driver_reassignment.", status_code=400)
    vehicle = require_owned_vehicle(account_id, payload.get("vehicle_id"))
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ApiError("reason is required.", status_code=400)
    if len(reason) > 1000:
        raise ApiError("reason cannot exceed 1000 characters.", status_code=400)
    timestamp = now_utc()
    _, profile = _owner_profile_for_account(account_id)
    document = {
        "request_type": request_type, "vehicle_id": vehicle["_id"], "fleet_owner_id": profile["_id"],
        "vehicle_registration": vehicle.get("registration_number"),
        "requested_by": _oid(account_id, "account_id"), "reporter_role": "fleet_owner",
        "reason": reason, "details": payload.get("details") if isinstance(payload.get("details"), dict) else {},
        "attachments": payload.get("attachments") if isinstance(payload.get("attachments"), list) else [],
        "status": "pending_review", "history": [{"status": "pending_review", "changed_by": _oid(account_id, "account_id"), "changed_at": timestamp}],
        "created_at": timestamp, "updated_at": timestamp,
    }
    document["_id"] = get_collection("fleet_owner_participation_requests").insert_one(document).inserted_id
    notify_roles(["owner", "admin"], title="Fleet Owner request requires review",
                 message=f"A {request_type.replace('_', ' ')} request was submitted for {vehicle.get('registration_number') or 'a linked vehicle'}.",
                 category="fleet", priority="high", reference_type="fleet_owner_request", reference_id=document["_id"],
                 dedupe_key=f"fleet-owner-request:{document['_id']}", action_url="fleet-owners")
    return _serialize_participation_request(document)


def list_participation_requests(current_user_id, current_role, status=None):
    query = {}
    if current_role == "fleet_owner":
        _, profile = _owner_profile_for_account(current_user_id)
        query["fleet_owner_id"] = profile["_id"]
    elif current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to view these requests.", status_code=403)
    if status:
        query["status"] = status
    return [_serialize_participation_request(item) for item in get_collection("fleet_owner_participation_requests").find(query).sort("created_at", DESCENDING).limit(250)]


def review_participation_request(request_id, payload, actor_id, actor_role):
    if actor_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can review this request.", status_code=403)
    action = str(payload.get("status") or "").strip().lower()
    if action not in {"approved", "rejected"}:
        raise ApiError("status must be approved or rejected.", status_code=400)
    collection = get_collection("fleet_owner_participation_requests")
    document = collection.find_one({"_id": _oid(request_id, "request_id")})
    if not document:
        raise ApiError("Fleet Owner request not found.", status_code=404)
    if document.get("status") == action:
        return _serialize_participation_request(document)
    if document.get("status") != "pending_review":
        raise ApiError("This request has already been reviewed.", status_code=409)
    timestamp = now_utc(); actor = _oid(actor_id, "actor_id")
    result = collection.update_one({"_id": document["_id"], "status": "pending_review"}, {
        "$set": {"status": action, "reviewed_by": actor, "reviewed_at": timestamp,
                 "review_note": str(payload.get("review_note") or "").strip() or None, "updated_at": timestamp},
        "$push": {"history": {"status": action, "changed_by": actor, "changed_at": timestamp}},
    })
    if result.modified_count != 1:
        raise ApiError("The request was reviewed in another session.", status_code=409)
    document.update({"status": action, "reviewed_by": actor, "reviewed_at": timestamp,
                     "review_note": str(payload.get("review_note") or "").strip() or None, "updated_at": timestamp})
    create_notification(document["requested_by"], f"Fleet request {action}",
                        f"Your {document['request_type'].replace('_', ' ')} request was {action}.",
                        category="fleet", priority="medium", reference_type="fleet_owner_request", reference_id=document["_id"])
    return _serialize_participation_request(document)


def add_owned_case_comment(account_id, case_type, case_id, comment):
    collection_name = {"fault": "faults", "maintenance": "maintenance_jobs"}.get(case_type)
    if not collection_name:
        raise ApiError("case_type must be fault or maintenance.", status_code=400)
    collection = get_collection(collection_name)
    document = collection.find_one({"_id": _oid(case_id, "case_id")})
    if not document:
        raise ApiError("Case not found.", status_code=404)
    require_owned_vehicle(account_id, document.get("vehicle_id"))
    text = str(comment or "").strip()
    if not text or len(text) > 2000:
        raise ApiError("comment is required and cannot exceed 2000 characters.", status_code=400)
    entry = {"id": ObjectId(), "comment": text, "created_by": _oid(account_id, "account_id"),
             "created_by_role": "fleet_owner", "created_at": now_utc()}
    collection.update_one({"_id": document["_id"]}, {"$push": {"participant_comments": entry}, "$set": {"updated_at": now_utc()}})
    return {"id": str(entry["id"]), "comment": text, "created_by_role": "fleet_owner", "created_at": _iso(entry["created_at"])}


def notify_linked_owner(vehicle_id, event, *, title, message, priority="medium", reference_id=None):
    """Send one deduplicated notification to the active account linked to a vehicle."""
    vehicle_object_id = _oid(vehicle_id, "vehicle_id")
    vehicle = get_collection("vehicles").find_one(
        {"_id": vehicle_object_id, "ownership_type": "third_party_owned"},
        {"fleet_owner_id": 1},
    )
    if not vehicle or not vehicle.get("fleet_owner_id"):
        return
    profile = get_collection("fleet_owners").find_one(
        {"_id": vehicle["fleet_owner_id"], "status": "active"},
        {"account_id": 1},
    )
    if not profile or not profile.get("account_id"):
        return
    account = get_collection("users").find_one(
        {"_id": profile["account_id"], "role": "fleet_owner", "status": "active"},
        {"_id": 1},
    )
    if not account:
        return
    resolved_reference = reference_id or vehicle_object_id
    create_notification(
        account["_id"],
        title,
        message,
        category="fleet",
        priority=priority,
        reference_type=event,
        reference_id=resolved_reference,
        dedupe_key=f"fleet-owner:{account['_id']}:{event}:{resolved_reference}",
        action_url="dashboard",
        metadata={"vehicle_id": str(vehicle_object_id)},
    )


def _serialize_owner(profile, user=None):
    return {
        "id": str(profile["_id"]),
        "account_id": str(profile.get("account_id")) if profile.get("account_id") else None,
        "name": profile.get("name"),
        "contact_name": profile.get("contact_name"),
        "email": profile.get("email"),
        "phone": profile.get("phone"),
        "status": profile.get("status", "active"),
        "vehicle_count": get_collection("vehicles").count_documents(
            {"fleet_owner_id": profile["_id"], "ownership_type": "third_party_owned"}
        ),
        "account": serialize_user(user) if user else None,
        "created_at": _iso(profile.get("created_at")),
        "updated_at": _iso(profile.get("updated_at")),
    }


def list_owner_accounts():
    profiles = list(get_collection("fleet_owners").find({}).sort("name", ASCENDING))
    user_ids = [item["account_id"] for item in profiles if item.get("account_id")]
    users = {item["_id"]: item for item in get_collection("users").find({"_id": {"$in": user_ids}})}
    return [_serialize_owner(item, users.get(item.get("account_id"))) for item in profiles]


def create_owner_account(payload, actor_id):
    user_payload = {
        "full_name": payload.get("contact_name") or payload.get("full_name") or payload.get("name"),
        "email": payload.get("email"),
        "phone": payload.get("phone"),
        "password": payload.get("password"),
        "status": payload.get("status", "active"),
    }
    user = create_user(user_payload, "fleet_owner")
    account_id = _oid(user["id"], "account_id")
    timestamp = now_utc()
    profile = {
        "name": str(payload.get("name") or user["full_name"]).strip(),
        "account_id": account_id,
        "contact_name": user["full_name"],
        "email": user["email"],
        "phone": user["phone"],
        "status": user["status"],
        "created_by": _oid(actor_id, "actor_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        profile["_id"] = get_collection("fleet_owners").insert_one(profile).inserted_id
    except Exception:
        # Do not leave a login without its mandatory owner profile.
        get_collection("users").delete_one({"_id": account_id})
        raise
    _audit(actor_id, "fleet_owner_account_created", "fleet_owner", profile["_id"], after=_serialize_owner(profile))
    return _serialize_owner(profile, get_collection("users").find_one({"_id": account_id}))


def update_owner_account(owner_id, payload, actor_id):
    owner_object_id = _oid(owner_id, "owner_id")
    profile = get_collection("fleet_owners").find_one({"_id": owner_object_id})
    if not profile:
        raise ApiError("Fleet Owner not found.", status_code=404)
    allowed = {"name", "contact_name", "email", "phone", "status"}
    updates = {key: payload[key] for key in allowed if key in payload}
    if "status" in updates and updates["status"] not in {"active", "inactive", "suspended"}:
        raise ApiError("Invalid account status.", status_code=400)
    if not updates:
        raise ApiError("No Fleet Owner fields provided.", status_code=400)
    before = _serialize_owner(profile)
    updates["updated_at"] = now_utc()
    get_collection("fleet_owners").update_one({"_id": owner_object_id}, {"$set": updates})
    if profile.get("account_id"):
        user_updates = {key: updates[key] for key in ("email", "phone", "status") if key in updates}
        if "contact_name" in updates:
            user_updates["full_name"] = updates["contact_name"]
        if user_updates:
            user_updates["updated_at"] = updates["updated_at"]
            get_collection("users").update_one({"_id": profile["account_id"]}, {"$set": user_updates})
    profile.update(updates)
    _audit(actor_id, "fleet_owner_account_updated", "fleet_owner", owner_object_id, before, _serialize_owner(profile))
    user = get_collection("users").find_one({"_id": profile.get("account_id")})
    return _serialize_owner(profile, user)


def link_owner_vehicles(owner_id, vehicle_ids, actor_id):
    owner_object_id = _oid(owner_id, "owner_id")
    owner = get_collection("fleet_owners").find_one({"_id": owner_object_id})
    if not owner:
        raise ApiError("Fleet Owner not found.", status_code=404)
    requested_ids = list(dict.fromkeys(_oid(item, "vehicle_id") for item in (vehicle_ids or [])))
    if not requested_ids:
        raise ApiError("At least one vehicle_id is required.", status_code=400)
    vehicles = list(get_collection("vehicles").find({"_id": {"$in": requested_ids}}))
    if len(vehicles) != len(requested_ids):
        raise ApiError("One or more vehicles were not found.", status_code=404)
    conflicts = [
        item for item in vehicles
        if item.get("fleet_owner_id") and item.get("fleet_owner_id") != owner_object_id
    ]
    if conflicts:
        raise ApiError("A vehicle is already linked to another Fleet Owner.", status_code=409)
    timestamp = now_utc()
    for vehicle in vehicles:
        before_owner = vehicle.get("fleet_owner_id")
        get_collection("vehicles").update_one(
            {"_id": vehicle["_id"], "$or": [{"fleet_owner_id": None}, {"fleet_owner_id": owner_object_id}, {"fleet_owner_id": {"$exists": False}}]},
            {"$set": {
                "ownership_type": "third_party_owned",
                "fleet_owner_id": owner_object_id,
                "ownership_start_date": timestamp.date().isoformat(),
                "updated_at": timestamp,
            }},
        )
        get_collection("vehicle_ownership_history").insert_one(
            {
                "vehicle_id": vehicle["_id"],
                "ownership_type": "third_party_owned",
                "fleet_owner_id": owner_object_id,
                "previous_fleet_owner_id": before_owner,
                "effective_at": timestamp,
                "approved_by": _oid(actor_id, "actor_id"),
                "created_at": timestamp,
                "immutable": True,
            }
        )
        _audit(actor_id, "vehicle_owner_linked", "vehicle", vehicle["_id"], {"fleet_owner_id": str(before_owner) if before_owner else None}, {"fleet_owner_id": str(owner_object_id)})
    return {"linked_count": len(vehicles), "vehicle_ids": [str(item["_id"]) for item in vehicles]}


def _profitability(vehicle_ids, start, end):
    collections = list(get_collection("collections").find({
        "vehicle_id": {"$in": vehicle_ids},
        "status": {"$in": list(RECOGNIZED_COLLECTION_STATUSES)},
        "collection_date": {"$gte": start, "$lte": end},
    }))
    fuel = list(get_collection("fuel_logs").find({
        "vehicle_id": {"$in": vehicle_ids},
        "status": {"$in": list(FUEL_COST_STATUSES)},
        "fuel_date": {"$gte": start, "$lte": end},
    }))
    maintenance = list(get_collection("maintenance_jobs").find({
        "vehicle_id": {"$in": vehicle_ids},
        "status": {"$in": list(MAINTENANCE_COST_STATUSES)},
        "$or": [
            {"completion_date": {"$gte": start, "$lte": end}},
            {"start_date": {"$gte": start, "$lte": end}},
        ],
    }))
    expenses = list(get_collection("expenses").find({
        "vehicle_id": {"$in": vehicle_ids},
        "status": {"$in": list(OPERATING_EXPENSE_STATUSES)},
        "expense_date": {"$gte": start, "$lte": end},
    }))
    by_vehicle = {}
    for vehicle_id in vehicle_ids:
        revenue = sum(float(item.get("amount") or 0) for item in collections if item.get("vehicle_id") == vehicle_id)
        fuel_cost = sum(float(item.get("amount") or 0) for item in fuel if item.get("vehicle_id") == vehicle_id)
        maintenance_cost = sum(
            float(item.get("actual_cost") if item.get("actual_cost") is not None else item.get("estimated_cost") or 0)
            for item in maintenance if item.get("vehicle_id") == vehicle_id
        )
        other_cost = sum(float(item.get("amount") or 0) for item in expenses if item.get("vehicle_id") == vehicle_id)
        total_cost = fuel_cost + maintenance_cost + other_cost
        incomplete = any(
            item.get("actual_cost") is None for item in maintenance if item.get("vehicle_id") == vehicle_id
        )
        by_vehicle[str(vehicle_id)] = {
            "gross_revenue": round(revenue, 2),
            "fuel_cost": round(fuel_cost, 2),
            "maintenance_cost": round(maintenance_cost, 2),
            "other_operating_cost": round(other_cost, 2),
            "total_recorded_operating_cost": round(total_cost, 2),
            "net_profitability": round(revenue - total_cost, 2),
            "data_complete": not incomplete,
            "data_note": (
                "Some maintenance jobs lack actual cost; estimates were used."
                if incomplete else
                "Based only on approved collections and recorded vehicle operating costs."
            ),
        }
    totals = {
        key: round(sum(item[key] for item in by_vehicle.values()), 2)
        for key in ("gross_revenue", "fuel_cost", "maintenance_cost", "other_operating_cost", "total_recorded_operating_cost", "net_profitability")
    }
    return {"by_vehicle": by_vehicle, "totals": totals, "period": {"start_date": start, "end_date": end}}


def _profitability_with_comparison(vehicle_ids, start, end):
    current = _profitability(vehicle_ids, start, end)
    start_date = datetime.fromisoformat(start).date()
    end_date = datetime.fromisoformat(end).date()
    day_count = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=day_count - 1)
    previous = _profitability(
        vehicle_ids, previous_start.isoformat(), previous_end.isoformat()
    )
    current["comparison"] = {
        "previous_period": previous["period"],
        "previous_totals": previous["totals"],
        "change": {
            key: round(current["totals"][key] - previous["totals"][key], 2)
            for key in current["totals"]
        },
    }
    return current


def owner_dashboard(account_id, start_date=None, end_date=None, vehicle_id=None):
    start, end = _date_bounds(start_date, end_date)
    vehicle_ids = _owner_vehicle_ids(account_id)
    if vehicle_id:
        selected = require_owned_vehicle(account_id, vehicle_id)
        vehicle_ids = [selected["_id"]]
    vehicles = list(get_collection("vehicles").find({"_id": {"$in": vehicle_ids}}))
    assignments = list(get_collection("assignments").find(
        {"vehicle_id": {"$in": vehicle_ids}, "allocation_active": True}
    ))
    assigned_driver_ids = [item["driver_id"] for item in assignments if item.get("driver_id")]
    drivers = {
        item["_id"]: item for item in get_collection("users").find(
            {"_id": {"$in": assigned_driver_ids}}, {"full_name": 1, "phone": 1}
        )
    }
    collections = list(get_collection("collections").find({
        "vehicle_id": {"$in": vehicle_ids},
        "status": {"$in": ["submitted", "received", "approved"]},
        "collection_date": {"$gte": start, "$lte": end},
    }))
    today = now_utc().date().isoformat()
    approved = [item for item in collections if item.get("status") == "approved"]
    target_total = sum(
        float(item.get("target_amount") or item.get("weekly_target") or 0)
        for item in assignments if item.get("target_enabled")
    )
    approved_total = sum(float(item.get("amount") or 0) for item in approved)
    rides = list(get_collection("rides").find({
        "vehicle_id": {"$in": vehicle_ids}, "trip_date": {"$gte": start, "$lte": end}
    }))
    open_faults = get_collection("faults").count_documents({
        "vehicle_id": {"$in": vehicle_ids}, "status": {"$in": list(OPEN_FAULT_STATUSES)}
    })
    active_maintenance = get_collection("maintenance_jobs").count_documents({
        "vehicle_id": {"$in": vehicle_ids}, "status": {"$in": list(ACTIVE_MAINTENANCE_STATUSES)}
    })
    maintenance_vehicle_ids = set(
        item["vehicle_id"] for item in get_collection("maintenance_jobs").find(
            {"vehicle_id": {"$in": vehicle_ids}, "status": {"$in": list(ACTIVE_MAINTENANCE_STATUSES)}},
            {"vehicle_id": 1},
        )
    )
    fault_vehicle_ids = set(
        item["vehicle_id"] for item in get_collection("faults").find(
            {"vehicle_id": {"$in": vehicle_ids}, "status": {"$in": list(OPEN_FAULT_STATUSES)}},
            {"vehicle_id": 1},
        )
    )
    return {
        "filters": {"start_date": start, "end_date": end, "vehicle_id": vehicle_id},
        "summary": {
            "total_linked_vehicles": len(vehicles),
            "available_vehicles": sum(1 for item in vehicles if item.get("status") == "available"),
            "active_vehicles": sum(1 for item in vehicles if item.get("status") in {"assigned", "active", "in_operation"}),
            "maintenance_or_fault_vehicles": len(maintenance_vehicle_ids | fault_vehicle_ids),
            "today_company_collections": round(sum(float(item.get("amount") or 0) for item in approved if item.get("collection_date") == today), 2),
            "period_company_collections": round(approved_total, 2),
            "weekly_target_achievement_percent": round((approved_total / target_total * 100), 1) if target_total else 0,
            "trips_completed": sum(1 for item in rides if item.get("status") in {"completed", "complete"}),
            "upcoming_maintenance": active_maintenance,
            "open_faults": open_faults,
        },
        "current_drivers": [
            {
                "vehicle_id": str(item["vehicle_id"]),
                "driver_id": str(item["driver_id"]),
                "driver_name": (drivers.get(item["driver_id"]) or {}).get("full_name"),
            }
            for item in assignments
        ],
        "vehicles": [
            {
                "id": str(item["_id"]),
                "registration_number": item.get("registration_number"),
                "make": item.get("make"),
                "model": item.get("model"),
                "status": item.get("status"),
            }
            for item in vehicles
        ],
        "profitability": _profitability_with_comparison(vehicle_ids, start, end),
    }


def owner_vehicle_detail(account_id, vehicle_id, start_date=None, end_date=None):
    vehicle = require_owned_vehicle(account_id, vehicle_id)
    vehicle_object_id = vehicle["_id"]
    start, end = _date_bounds(start_date, end_date)
    allocation_docs = list(get_collection("assignments").find(
        {"vehicle_id": vehicle_object_id}
    ).sort("created_at", DESCENDING))
    driver_ids = [item["driver_id"] for item in allocation_docs if item.get("driver_id")]
    drivers = {
        item["_id"]: {"id": str(item["_id"]), "full_name": item.get("full_name"), "phone": item.get("phone")}
        for item in get_collection("users").find({"_id": {"$in": driver_ids}})
    }
    collections = list(get_collection("collections").find({
        "vehicle_id": vehicle_object_id, "collection_date": {"$gte": start, "$lte": end}
    }).sort("collection_date", DESCENDING))
    rides = list(get_collection("rides").find({
        "vehicle_id": vehicle_object_id, "trip_date": {"$gte": start, "$lte": end}
    }).sort("trip_date", DESCENDING))
    fuel = list(get_collection("fuel_logs").find({
        "vehicle_id": vehicle_object_id, "fuel_date": {"$gte": start, "$lte": end}
    }).sort("fuel_date", DESCENDING))
    maintenance = list(get_collection("maintenance_jobs").find(
        {"vehicle_id": vehicle_object_id}
    ).sort("created_at", DESCENDING))
    faults = list(get_collection("faults").find(
        {"vehicle_id": vehicle_object_id}
    ).sort("created_at", DESCENDING))
    ownership = list(get_collection("vehicle_ownership_history").find(
        {"vehicle_id": vehicle_object_id}
    ).sort("created_at", DESCENDING))
    current = next((item for item in allocation_docs if item.get("allocation_active")), None)
    return {
        "vehicle": serialize_vehicle(vehicle, include_sensitive=False),
        "current_driver": drivers.get(current.get("driver_id")) if current else None,
        "current_allocation": serialize_assignment(current) if current else None,
        "allocation_history": [
            {**serialize_assignment(item), "driver": drivers.get(item.get("driver_id"))}
            for item in allocation_docs
        ],
        "ownership_history": [
            {
                "id": str(item["_id"]),
                "ownership_type": item.get("ownership_type"),
                "fleet_owner_id": str(item.get("fleet_owner_id")) if item.get("fleet_owner_id") else None,
                "effective_at": _iso(item.get("effective_at") or item.get("created_at")),
            }
            for item in ownership
        ],
        "target_progress": {
            "target_enabled": bool(current and current.get("target_enabled")),
            "target_amount": (current or {}).get("target_amount") or (current or {}).get("weekly_target"),
            "recognized_collections": round(sum(float(item.get("amount") or 0) for item in collections if item.get("status") == "approved"), 2),
        },
        "collections": [serialize_collection(item) for item in collections],
        "trips": [serialize_ride(item) for item in rides],
        "fuel_logs": [serialize_fuel_log(item) for item in fuel],
        "maintenance": [serialize_maintenance_job(item) for item in maintenance],
        "faults": [serialize_fault(item) for item in faults],
        "documents": [
            {"type": "insurance", "expiry_date": vehicle.get("insurance_expiry") or (vehicle.get("insurance_profile") or {}).get("expiry_date")},
            {"type": "roadworthy", "expiry_date": vehicle.get("roadworthy_expiry")},
        ],
        "profitability": _profitability_with_comparison([vehicle_object_id], start, end),
        "read_only": True,
    }
