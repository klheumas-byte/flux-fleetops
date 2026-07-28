from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.user import serialize_user
from services.notification_service import create_notification
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


VEHICLE_TYPES = {"motorcycle", "tricycle", "saloon_car", "suv", "pickup", "van", "other"}
VEHICLE_STATUSES = {"active", "inactive", "sold", "archived"}
FUEL_TYPES = {"petrol", "diesel", "lpg", "electric", "hybrid", "other"}
RECORD_COLLECTIONS = {
    "services": "maintenance_jobs",
    "faults": "faults",
    "accidents": "incidents",
    "fuel": "fuel_logs",
    "expenses": "expenses",
    "documents": "vehicle_compliance_records",
    "reminders": "personal_vehicle_reminders",
}
EXPENSE_CATEGORIES = {
    "fuel", "service", "repairs", "insurance", "roadworthy", "registration", "parking", "tolls",
    "washing", "tyres", "battery", "accessories", "fines", "accident", "other",
}
REMINDER_TYPES = {"service", "insurance", "roadworthy", "registration", "tyres", "battery", "custom"}
REMINDER_STATUSES = {"upcoming", "due", "overdue", "completed", "dismissed"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _oid(value: Any, field: str) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(str(value or "")):
        raise ApiError(f"Invalid {field}.", status_code=404)
    return ObjectId(str(value))


def _text(value: Any, field: str, *, required: bool = False, maximum: int = 2000) -> str | None:
    result = str(value or "").strip()
    if required and not result:
        raise ApiError(f"{field.replace('_', ' ').capitalize()} is required.", status_code=400)
    if len(result) > maximum:
        raise ApiError(f"{field.replace('_', ' ').capitalize()} is too long.", status_code=400)
    return result or None


def _number(value: Any, field: str, *, required: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field.replace('_', ' ').capitalize()} is required.", status_code=400)
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ApiError(f"{field.replace('_', ' ').capitalize()} must be numeric.", status_code=400) from None
    if result < 0:
        raise ApiError(f"{field.replace('_', ' ').capitalize()} cannot be negative.", status_code=400)
    return round(result, 4)


def _date(value: Any, field: str, *, required: bool = False) -> str | None:
    text = _text(value, field, required=required, maximum=40)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise ApiError(f"{field.replace('_', ' ').capitalize()} must be a valid date.", status_code=400) from None


def _datetime(value: Any, field: str, *, required: bool = False) -> datetime | None:
    text = _text(value, field, required=required, maximum=50)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(f"{field.replace('_', ' ').capitalize()} must be a valid date and time.", status_code=400) from None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _serialize(value: Any):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        hidden = {"personal_owner_user_id", "owner_user_id", "password_hash"}
        return {("id" if key == "_id" else key): _serialize(item) for key, item in value.items() if key not in hidden}
    return value


def _page(value: Any, default: int, maximum: int | None = None) -> int:
    try:
        result = int(value or default)
    except (TypeError, ValueError):
        result = default
    result = max(1, result)
    return min(result, maximum) if maximum else result


def _owner(user_id: str) -> ObjectId:
    user = get_collection("users").find_one({"_id": _oid(user_id, "user"), "role": "personal_vehicle_owner", "status": "active"})
    if not user:
        raise ApiError("Personal vehicle account is not active.", status_code=403)
    return user["_id"]


def require_owned_vehicle(user_id: str, vehicle_id: Any, projection: dict | None = None) -> dict:
    owner_id = _owner(user_id)
    vehicle = get_collection("vehicles").find_one(
        {"_id": _oid(vehicle_id, "vehicle"), "usage_type": "personal", "personal_owner_user_id": owner_id},
        projection,
    )
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _audit(action: str, actor_id: ObjectId, entity_type: str, entity_id: ObjectId, changes: dict | None = None, reason: str | None = None):
    get_collection("personal_vehicle_audit").insert_one({
        "actor_id": actor_id, "actor_role": "personal_vehicle_owner", "action": action,
        "entity_type": entity_type, "entity_id": entity_id, "changes": changes or {},
        "reason": reason, "created_at": now_utc(),
    })


def ensure_personal_vehicle_indexes():
    ensure_indexes_for_collection(get_collection("vehicles"), [
        {"keys": [("usage_type", ASCENDING), ("personal_owner_user_id", ASCENDING), ("status", ASCENDING)]},
        {"keys": [("personal_owner_user_id", ASCENDING), ("registration_number", ASCENDING)], "options": {"sparse": True}},
    ], collection_name="vehicles")
    for name in ("maintenance_jobs", "faults", "incidents", "fuel_logs", "expenses", "vehicle_compliance_records"):
        ensure_indexes_for_collection(get_collection(name), [
            {"keys": [("record_scope", ASCENDING), ("personal_owner_user_id", ASCENDING), ("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
        ], collection_name=name)
    ensure_indexes_for_collection(get_collection("personal_vehicle_reminders"), [
        {"keys": [("personal_owner_user_id", ASCENDING), ("vehicle_id", ASCENDING), ("status", ASCENDING), ("due_date", ASCENDING)]},
        {"keys": [("personal_owner_user_id", ASCENDING), ("dedupe_key", ASCENDING)], "options": {"unique": True, "sparse": True}},
    ], collection_name="personal_vehicle_reminders")
    ensure_indexes_for_collection(get_collection("personal_vehicle_audit"), [
        {"keys": [("entity_type", ASCENDING), ("entity_id", ASCENDING), ("created_at", DESCENDING)]},
        {"keys": [("actor_id", ASCENDING), ("created_at", DESCENDING)]},
    ], collection_name="personal_vehicle_audit")


def list_vehicles(user_id: str) -> list[dict]:
    owner_id = _owner(user_id)
    rows = get_collection("vehicles").find({"usage_type": "personal", "personal_owner_user_id": owner_id}).sort("created_at", DESCENDING)
    return [_serialize(item) for item in rows]


def create_vehicle(user_id: str, payload: dict) -> dict:
    owner_id = _owner(user_id)
    vehicle_type = str(payload.get("vehicle_type") or "").strip().lower()
    if vehicle_type not in VEHICLE_TYPES:
        raise ApiError("Unsupported vehicle type.", status_code=400)
    registration = _text(payload.get("registration_number"), "registration_number", required=True, maximum=50).upper()
    if get_collection("vehicles").find_one({"registration_number": registration}, {"_id": 1}):
        raise ApiError("Registration number already exists.", status_code=409)
    status = str(payload.get("status") or "active").lower()
    if status not in VEHICLE_STATUSES:
        raise ApiError("Invalid vehicle status.", status_code=400)
    fuel_type = str(payload.get("fuel_type") or payload.get("energy_type") or "other").lower()
    if fuel_type not in FUEL_TYPES:
        raise ApiError("Invalid fuel or energy type.", status_code=400)
    timestamp = now_utc()
    document = {
        "usage_type": "personal", "personal_owner_user_id": owner_id, "registration_number": registration,
        "vehicle_type": vehicle_type, "make": _text(payload.get("make"), "make", required=True, maximum=80),
        "model": _text(payload.get("model"), "model", required=True, maximum=80),
        "year": int(_number(payload.get("year"), "year", required=True)), "color": _text(payload.get("color") or payload.get("colour"), "colour", maximum=50),
        "chassis_number": _text(payload.get("chassis_number"), "chassis_number", maximum=100),
        "engine_number": _text(payload.get("engine_number"), "engine_number", maximum=100),
        "fuel_type": fuel_type, "transmission": _text(payload.get("transmission"), "transmission", maximum=30),
        "current_mileage": _number(payload.get("current_mileage"), "current_mileage") or 0,
        "purchase_date": _date(payload.get("purchase_date"), "purchase_date"),
        "purchase_mileage": _number(payload.get("purchase_mileage"), "purchase_mileage"),
        "tyre_size": _text(payload.get("tyre_size"), "tyre_size", maximum=50),
        "engine_capacity": _text(payload.get("engine_capacity"), "engine_capacity", maximum=50),
        "vehicle_photo": payload.get("vehicle_photo"), "notes": _text(payload.get("notes"), "notes"), "status": status,
        "created_by": owner_id, "created_at": timestamp, "updated_at": timestamp,
    }
    result = get_collection("vehicles").insert_one(document); document["_id"] = result.inserted_id
    _audit("vehicle_created", owner_id, "vehicle", document["_id"], {"registration_number": registration})
    return _serialize(document)


def update_vehicle(user_id: str, vehicle_id: str, payload: dict) -> dict:
    owner_id = _owner(user_id); vehicle = require_owned_vehicle(user_id, vehicle_id)
    allowed = {"registration_number", "vehicle_type", "make", "model", "year", "color", "colour", "chassis_number", "engine_number", "fuel_type", "transmission", "current_mileage", "purchase_date", "purchase_mileage", "tyre_size", "engine_capacity", "vehicle_photo", "notes", "status"}
    updates = {}
    for key in allowed.intersection(payload):
        value = payload[key]
        target = "color" if key == "colour" else key
        if key in {"current_mileage", "purchase_mileage", "year"}:
            value = _number(value, key)
            if key == "year" and value is not None: value = int(value)
        elif key == "purchase_date": value = _date(value, key)
        elif key not in {"vehicle_photo"}: value = _text(value, key, maximum=2000 if key == "notes" else 100)
        updates[target] = value
    if "vehicle_type" in updates and updates["vehicle_type"] not in VEHICLE_TYPES: raise ApiError("Unsupported vehicle type.", status_code=400)
    if "status" in updates and updates["status"] not in VEHICLE_STATUSES: raise ApiError("Invalid vehicle status.", status_code=400)
    if "fuel_type" in updates and updates["fuel_type"] not in FUEL_TYPES: raise ApiError("Invalid fuel or energy type.", status_code=400)
    old_mileage = float(vehicle.get("current_mileage") or 0)
    if updates.get("current_mileage") is not None and updates["current_mileage"] < old_mileage:
        reason = _text(payload.get("correction_reason"), "correction_reason", required=True, maximum=500)
    else: reason = _text(payload.get("change_reason"), "change_reason", maximum=500)
    updates["updated_at"] = now_utc()
    get_collection("vehicles").update_one({"_id": vehicle["_id"]}, {"$set": updates})
    if "current_mileage" in updates and updates["current_mileage"] != old_mileage:
        _audit("mileage_updated", owner_id, "vehicle", vehicle["_id"], {"from": old_mileage, "to": updates["current_mileage"]}, reason)
    if "status" in updates and updates["status"] != vehicle.get("status"):
        _audit("vehicle_status_changed", owner_id, "vehicle", vehicle["_id"], {"from": vehicle.get("status"), "to": updates["status"]}, reason)
    vehicle.update(updates); return _serialize(vehicle)


def get_vehicle(user_id: str, vehicle_id: str) -> dict:
    vehicle = require_owned_vehicle(user_id, vehicle_id)
    result = _serialize(vehicle); result["health"] = vehicle_health(user_id, vehicle_id)
    return result


def _record_collection(kind: str):
    if kind not in RECORD_COLLECTIONS: raise ApiError("Unsupported record type.", status_code=404)
    return get_collection(RECORD_COLLECTIONS[kind])


def _scope(user_id: str, vehicle_id: str | None = None) -> tuple[ObjectId, dict]:
    owner_id = _owner(user_id); query = {"record_scope": "personal", "personal_owner_user_id": owner_id}
    if vehicle_id: query["vehicle_id"] = require_owned_vehicle(user_id, vehicle_id)["_id"]
    return owner_id, query


def list_records(user_id: str, kind: str, *, vehicle_id: str | None = None, page=1, page_size=25, start_date=None, end_date=None) -> dict:
    _, query = _scope(user_id, vehicle_id)
    if kind == "reminders":
        _refresh_reminder_statuses(query)
    if start_date or end_date:
        bounds = {}; 
        if start_date: bounds["$gte"] = str(start_date)[:10]
        if end_date: bounds["$lte"] = str(end_date)[:10]
        query["record_date"] = bounds
    page = _page(page, 1); page_size = _page(page_size, 25, 100)
    collection = _record_collection(kind); total = collection.count_documents(query)
    rows = collection.find(query).sort([("record_date", DESCENDING), ("created_at", DESCENDING)]).skip((page - 1) * page_size).limit(page_size)
    return {"records": [_serialize(item) for item in rows], "pagination": {"page": page, "page_size": page_size, "total": total, "pages": max(1, (total + page_size - 1) // page_size)}}


def _status_history(status: str, owner_id: ObjectId, note: str | None = None) -> list[dict]:
    return [{"status": status, "changed_by": owner_id, "changed_at": now_utc(), "note": note}]


def _validate_mileage(user_id: str, vehicle: dict, mileage: float | None, payload: dict):
    if mileage is None: return
    current = float(vehicle.get("current_mileage") or 0)
    if mileage < current and not _text(payload.get("correction_reason"), "correction_reason", maximum=500):
        raise ApiError("Mileage cannot go backwards without an audited correction reason.", status_code=400)


def create_record(user_id: str, kind: str, payload: dict) -> dict:
    owner_id = _owner(user_id); vehicle = require_owned_vehicle(user_id, payload.get("vehicle_id")); timestamp = now_utc()
    mileage = _number(payload.get("mileage"), "mileage"); _validate_mileage(user_id, vehicle, mileage, payload)
    status_defaults = {"services": "completed", "faults": "open", "accidents": "reported", "fuel": "recorded", "expenses": "recorded", "documents": "active", "reminders": "upcoming"}
    status = str(payload.get("status") or status_defaults[kind]).strip().lower()
    document: dict[str, Any] = {"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": vehicle["_id"], "record_date": _date(payload.get("record_date") or payload.get("date") or date.today().isoformat(), "record_date", required=True), "mileage": mileage, "status": status, "notes": _text(payload.get("notes"), "notes"), "attachments": payload.get("attachments") or [], "created_by": owner_id, "created_at": timestamp, "updated_at": timestamp, "status_history": _status_history(status, owner_id)}
    if kind == "services":
        labour = _number(payload.get("labour_cost"), "labour_cost") or 0; parts = _number(payload.get("parts_cost"), "parts_cost") or 0; other = _number(payload.get("other_cost"), "other_cost") or 0
        document.update({"maintenance_type": _text(payload.get("service_type"), "service_type", required=True, maximum=100), "title": _text(payload.get("title") or payload.get("service_type"), "title", required=True), "description": _text(payload.get("work_performed"), "work_performed", required=True), "mechanic_or_garage": _text(payload.get("mechanic_or_garage"), "mechanic_or_garage"), "parts_and_fluids": payload.get("parts_and_fluids") or [], "labour_cost": labour, "parts_cost": parts, "other_cost": other, "total_cost": round(labour + parts + other, 2), "actual_cost": round(labour + parts + other, 2), "next_service_date": _date(payload.get("next_service_date"), "next_service_date"), "next_service_mileage": _number(payload.get("next_service_mileage"), "next_service_mileage"), "receipts": payload.get("receipts") or []})
    elif kind == "faults":
        document.update({"date_noticed": document["record_date"], "category": _text(payload.get("category"), "category", required=True), "description": _text(payload.get("description"), "description", required=True), "severity": str(payload.get("severity") or "medium").lower(), "vehicle_usable": str(payload.get("vehicle_usable") or "unsure").lower(), "diagnosis": _text(payload.get("diagnosis"), "diagnosis"), "estimated_repair_cost": _number(payload.get("estimated_repair_cost"), "estimated_repair_cost"), "actual_repair_cost": _number(payload.get("actual_repair_cost"), "actual_repair_cost"), "repair_date": _date(payload.get("repair_date"), "repair_date"), "resolution_notes": _text(payload.get("resolution_notes"), "resolution_notes"), "related_service_id": _oid(payload["related_service_id"], "related service") if payload.get("related_service_id") else None})
    elif kind == "accidents":
        document.update({"incident_at": _datetime(payload.get("incident_at") or payload.get("date_time"), "incident_at", required=True), "location": _text(payload.get("location"), "location", required=True), "description": _text(payload.get("description"), "description", required=True), "damage_areas": payload.get("damage_areas") or [], "severity": str(payload.get("severity") or "medium").lower(), "vehicle_drivable": payload.get("vehicle_drivable"), "police_report_reference": _text(payload.get("police_report_reference"), "police_report_reference"), "insurance_claim_reference": _text(payload.get("insurance_claim_reference"), "insurance_claim_reference"), "third_party_details": payload.get("third_party_details") or {}, "repair_estimate": _number(payload.get("repair_estimate"), "repair_estimate"), "repair_cost": _number(payload.get("repair_cost"), "repair_cost"), "repair_status": str(payload.get("repair_status") or "not_started").lower(), "completion_date": _date(payload.get("completion_date"), "completion_date")})
    elif kind == "fuel":
        energy = str(vehicle.get("fuel_type") or "").lower() == "electric" or payload.get("energy_used") not in (None, "")
        quantity = _number(payload.get("energy_used") if energy else payload.get("quantity"), "energy_used" if energy else "quantity", required=True); total = _number(payload.get("charging_cost") if energy else payload.get("total_cost"), "charging_cost" if energy else "total_cost", required=True)
        previous = get_collection("fuel_logs").find_one(
            {"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": vehicle["_id"], "mileage": {"$lt": mileage}},
            sort=[("mileage", DESCENDING)],
        ) if mileage is not None else None
        previous_mileage = float(previous.get("mileage")) if previous and previous.get("mileage") is not None else None
        distance = round(mileage - previous_mileage, 4) if mileage is not None and previous_mileage is not None else None
        document.update({"entry_type": "charging" if energy else "fuel", "fuel_type": str(payload.get("fuel_type") or vehicle.get("fuel_type") or "other").lower(), "quantity": quantity, "total_cost": total, "amount": total, "price_per_unit": round(total / quantity, 4) if quantity else None, "distance_since_previous": distance, "consumption_per_100_km": round(quantity * 100 / distance, 4) if distance else None, "cost_per_km": round(total / distance, 4) if distance else None, "station_or_location": _text(payload.get("station") or payload.get("charging_location"), "station_or_location"), "tank_level": str(payload.get("tank_level") or "partial").lower() if not energy else None, "battery_before": _number(payload.get("battery_before"), "battery_before"), "battery_after": _number(payload.get("battery_after"), "battery_after")})
    elif kind == "expenses":
        category = str(payload.get("category") or "").lower()
        if category not in EXPENSE_CATEGORIES: raise ApiError("Invalid expense category.", status_code=400)
        document.update({"expense_category": category, "expense_title": _text(payload.get("title"), "title", required=True), "amount": _number(payload.get("amount"), "amount", required=True), "expense_date": document["record_date"], "linked_source_type": _text(payload.get("linked_source_type"), "linked_source_type", maximum=40), "linked_source_id": _oid(payload["linked_source_id"], "linked source") if payload.get("linked_source_id") else None})
    elif kind == "documents":
        document.update({"document_type": str(payload.get("document_type") or "other").lower(), "compliance_item_name": _text(payload.get("document_type") or "other", "document_type", required=True), "document_number": _text(payload.get("document_number"), "document_number"), "issue_date": _date(payload.get("issue_date"), "issue_date"), "expiry_date": _date(payload.get("expiry_date"), "expiry_date"), "provider": _text(payload.get("provider"), "provider"), "attachment": payload.get("attachment"), "renewal_of_id": _oid(payload["renewal_of_id"], "previous document") if payload.get("renewal_of_id") else None})
    elif kind == "reminders":
        reminder_type = str(payload.get("reminder_type") or "custom").lower()
        if reminder_type not in REMINDER_TYPES: raise ApiError("Invalid reminder type.", status_code=400)
        if status not in REMINDER_STATUSES: raise ApiError("Invalid reminder status.", status_code=400)
        due_date = _date(payload.get("due_date"), "due_date"); due_mileage = _number(payload.get("due_mileage"), "due_mileage")
        if not due_date and due_mileage is None: raise ApiError("A due date or due mileage is required.", status_code=400)
        document.update({"reminder_type": reminder_type, "title": _text(payload.get("title"), "title", required=True), "due_date": due_date, "due_mileage": due_mileage, "dedupe_key": str(payload.get("dedupe_key") or f"{vehicle['_id']}:{reminder_type}:{due_date or due_mileage}:{document['title']}")})
    try:
        result = _record_collection(kind).insert_one(document)
    except DuplicateKeyError:
        raise ApiError("This reminder already exists.", status_code=409) from None
    document["_id"] = result.inserted_id
    if mileage is not None and mileage > float(vehicle.get("current_mileage") or 0):
        get_collection("vehicles").update_one({"_id": vehicle["_id"]}, {"$set": {"current_mileage": mileage, "updated_at": timestamp}})
    _audit(f"{kind}_created", owner_id, kind[:-1], document["_id"], {"vehicle": vehicle.get("registration_number")}, _text(payload.get("correction_reason"), "correction_reason", maximum=500))
    if kind == "services" and (document.get("next_service_date") or document.get("next_service_mileage") is not None):
        _upsert_service_reminder(owner_id, vehicle, document)
    if kind in {"documents", "reminders"}: _notify_due_record(owner_id, kind, document)
    return _serialize(document)


def update_record(user_id: str, kind: str, record_id: str, payload: dict) -> dict:
    owner_id = _owner(user_id); collection = _record_collection(kind)
    document = collection.find_one({"_id": _oid(record_id, "record"), "record_scope": "personal", "personal_owner_user_id": owner_id})
    if not document: raise ApiError("Record not found.", status_code=404)
    require_owned_vehicle(user_id, document["vehicle_id"])
    updates = {}; status = str(payload.get("status") or "").strip().lower()
    if status and status != document.get("status"):
        updates["status"] = status
        updates["status_history"] = [*(document.get("status_history") or []), {"status": status, "changed_by": owner_id, "changed_at": now_utc(), "note": _text(payload.get("status_note"), "status_note")}]
    for key in ("notes", "diagnosis", "resolution_notes", "repair_status", "completion_date", "repair_date", "actual_repair_cost", "repair_cost", "estimated_repair_cost", "repair_estimate"):
        if key in payload:
            updates[key] = _number(payload[key], key) if "cost" in key or "estimate" in key else (_date(payload[key], key) if "date" in key else _text(payload[key], key))
    if kind == "reminders" and status and status not in REMINDER_STATUSES: raise ApiError("Invalid reminder status.", status_code=400)
    updates["updated_at"] = now_utc(); collection.update_one({"_id": document["_id"]}, {"$set": updates}); document.update(updates)
    _audit(f"{kind}_updated", owner_id, kind[:-1], document["_id"], updates, _text(payload.get("change_reason"), "change_reason", maximum=500))
    return _serialize(document)


def renew_document(user_id: str, document_id: str, payload: dict) -> dict:
    owner_id = _owner(user_id); collection = _record_collection("documents")
    previous = collection.find_one({"_id": _oid(document_id, "document"), "record_scope": "personal", "personal_owner_user_id": owner_id})
    if not previous: raise ApiError("Document not found.", status_code=404)
    payload = {**payload, "vehicle_id": str(previous["vehicle_id"]), "document_type": payload.get("document_type") or previous.get("document_type"), "renewal_of_id": str(previous["_id"]), "record_date": payload.get("issue_date") or date.today().isoformat()}
    renewed = create_record(user_id, "documents", payload)
    collection.update_one({"_id": previous["_id"]}, {"$set": {"status": "renewed", "renewed_by_id": ObjectId(renewed["id"]), "updated_at": now_utc()}})
    return renewed


def _upsert_service_reminder(owner_id: ObjectId, vehicle: dict, service: dict):
    dedupe = f"service:{service['_id']}"
    doc = {"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": vehicle["_id"], "record_date": service["record_date"], "reminder_type": "service", "title": f"Next service for {vehicle.get('registration_number')}", "due_date": service.get("next_service_date"), "due_mileage": service.get("next_service_mileage"), "status": "upcoming", "dedupe_key": dedupe, "source_type": "service", "source_id": service["_id"], "created_at": now_utc(), "updated_at": now_utc(), "status_history": _status_history("upcoming", owner_id)}
    get_collection("personal_vehicle_reminders").update_one({"personal_owner_user_id": owner_id, "dedupe_key": dedupe}, {"$setOnInsert": doc}, upsert=True)


def _refresh_reminder_statuses(scope: dict):
    today = date.today().isoformat()
    vehicles = {
        item["_id"]: float(item.get("current_mileage") or 0)
        for item in get_collection("vehicles").find(
            {"_id": {"$in": list(get_collection("personal_vehicle_reminders").distinct("vehicle_id", scope))}},
            {"current_mileage": 1},
        )
    }
    for reminder in get_collection("personal_vehicle_reminders").find({**scope, "status": {"$in": ["upcoming", "due", "overdue"]}}):
        due_date = reminder.get("due_date")
        due_mileage = reminder.get("due_mileage")
        mileage_reached = due_mileage is not None and vehicles.get(reminder.get("vehicle_id"), 0) >= float(due_mileage)
        desired = "overdue" if (due_date and due_date < today) else "due" if (due_date == today or mileage_reached) else "upcoming"
        if desired != reminder.get("status"):
            get_collection("personal_vehicle_reminders").update_one(
                {"_id": reminder["_id"]},
                {"$set": {"status": desired, "updated_at": now_utc()}, "$push": {"status_history": {"status": desired, "changed_at": now_utc(), "note": "Automatically recalculated from due date or mileage."}}},
            )


def _notify_due_record(owner_id: ObjectId, kind: str, document: dict):
    due = document.get("due_date") or document.get("expiry_date")
    if not due: return
    create_notification(owner_id, f"Personal vehicle {kind[:-1]} reminder", document.get("title") or document.get("document_type") or "Vehicle record is approaching its due date.", category="maintenance", priority="normal", reference_type=f"personal_vehicle_{kind[:-1]}", reference_id=document["_id"], scheduled_for=datetime.fromisoformat(due).replace(tzinfo=timezone.utc), dedupe_key=f"personal:{kind}:{document['_id']}:{due}")


def _month_bounds(start_date=None, end_date=None):
    today = date.today(); start = str(start_date or today.replace(day=1).isoformat())[:10]; end = str(end_date or today.isoformat())[:10]
    return start, end


def _owned_vehicle_ids(owner_id: ObjectId, vehicle_id=None):
    query = {"usage_type": "personal", "personal_owner_user_id": owner_id}
    if vehicle_id: query["_id"] = _oid(vehicle_id, "vehicle")
    return [item["_id"] for item in get_collection("vehicles").find(query, {"_id": 1})]


def dashboard(user_id: str, *, vehicle_id=None, start_date=None, end_date=None) -> dict:
    owner_id = _owner(user_id); vehicle_ids = _owned_vehicle_ids(owner_id, vehicle_id)
    if vehicle_id and not vehicle_ids: raise ApiError("Vehicle not found.", status_code=404)
    start, end = _month_bounds(start_date, end_date); scope = {"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": {"$in": vehicle_ids}}
    vehicles = list(get_collection("vehicles").find({"_id": {"$in": vehicle_ids}}))
    _refresh_reminder_statuses({"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": {"$in": vehicle_ids}})
    services = list(get_collection("maintenance_jobs").find({**scope, "record_date": {"$gte": start, "$lte": end}}))
    faults = list(get_collection("faults").find(scope)); accidents = list(get_collection("incidents").find(scope))
    fuel = list(get_collection("fuel_logs").find({**scope, "record_date": {"$gte": start, "$lte": end}})); expenses = list(get_collection("expenses").find({**scope, "record_date": {"$gte": start, "$lte": end}, "linked_source_id": None}))
    documents = list(get_collection("vehicle_compliance_records").find(scope)); reminders = list(get_collection("personal_vehicle_reminders").find({**scope, "status": {"$in": ["upcoming", "due", "overdue"]}}))
    fuel_cost = round(sum(float(item.get("total_cost") or item.get("amount") or 0) for item in fuel), 2)
    service_cost = round(sum(float(item.get("total_cost") or item.get("actual_cost") or 0) for item in services), 2)
    manual_cost = round(sum(float(item.get("amount") or 0) for item in expenses), 2)
    unresolved_faults = [item for item in faults if item.get("status") not in {"resolved", "closed", "cancelled"}]
    unresolved_accidents = [item for item in accidents if item.get("repair_status") not in {"completed", "repaired"}]
    timeline = vehicle_timeline(user_id, vehicle_id=vehicle_id, page=1, page_size=8)["events"]
    vehicle_summaries = []
    for item in vehicles:
        service_scope = {"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": item["_id"]}
        last_service = get_collection("maintenance_jobs").find_one(service_scope, sort=[("record_date", DESCENDING), ("created_at", DESCENDING)])
        next_service = get_collection("personal_vehicle_reminders").find_one({**service_scope, "reminder_type": "service", "status": {"$in": ["upcoming", "due", "overdue"]}}, sort=[("due_date", ASCENDING), ("due_mileage", ASCENDING)])
        vehicle_summaries.append({**_serialize(item), "last_service": _serialize(last_service) if last_service else None, "next_service": _serialize(next_service) if next_service else None, "health": vehicle_health(user_id, str(item["_id"]))})
    return {"filters": {"start_date": start, "end_date": end, "vehicle_id": vehicle_id}, "summary": {"total_vehicles": len(vehicles), "active_vehicles": sum(item.get("status") == "active" for item in vehicles), "current_mileage": sum(float(item.get("current_mileage") or 0) for item in vehicles), "open_faults": len(unresolved_faults), "unresolved_accident_repairs": len(unresolved_accidents), "document_expiries": sum(bool(item.get("expiry_date") and item["expiry_date"] <= end and item.get("status") != "renewed") for item in documents), "reminders": len(reminders), "monthly_fuel_cost": fuel_cost, "monthly_ownership_cost": round(fuel_cost + service_cost + manual_cost, 2)}, "vehicles": vehicle_summaries, "recent_activity": timeline}


def expense_summary(user_id: str, *, vehicle_id=None, start_date=None, end_date=None) -> dict:
    owner_id = _owner(user_id); ids = _owned_vehicle_ids(owner_id, vehicle_id); start, end = _month_bounds(start_date, end_date)
    scope = {"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": {"$in": ids}, "record_date": {"$gte": start, "$lte": end}}
    categories: dict[str, float] = {}
    for item in get_collection("expenses").find({**scope, "linked_source_id": None}): categories[item.get("expense_category") or "other"] = categories.get(item.get("expense_category") or "other", 0) + float(item.get("amount") or 0)
    for collection, category, field in (("fuel_logs", "fuel", "total_cost"), ("maintenance_jobs", "service", "total_cost")):
        for item in get_collection(collection).find(scope): categories[category] = categories.get(category, 0) + float(item.get(field) or item.get("amount") or 0)
    return {"start_date": start, "end_date": end, "total": round(sum(categories.values()), 2), "by_category": {key: round(value, 2) for key, value in sorted(categories.items())}}


def vehicle_health(user_id: str, vehicle_id: str) -> dict:
    vehicle = require_owned_vehicle(user_id, vehicle_id); owner_id = _owner(user_id); scope = {"record_scope": "personal", "personal_owner_user_id": owner_id, "vehicle_id": vehicle["_id"]}; today = date.today().isoformat(); warnings=[]; score=100
    _refresh_reminder_statuses(scope)
    overdue = get_collection("personal_vehicle_reminders").count_documents({**scope, "status": {"$in": ["due", "overdue"]}})
    if overdue: warnings.append({"code": "overdue_reminders", "message": f"{overdue} reminder(s) are due or overdue.", "action": "Review and complete overdue care items."}); score -= min(25, overdue * 8)
    serious = get_collection("faults").count_documents({**scope, "status": {"$nin": ["resolved", "closed", "cancelled"]}, "severity": {"$in": ["high", "critical", "serious"]}})
    if serious: warnings.append({"code": "serious_faults", "message": f"{serious} serious unresolved fault(s).", "action": "Arrange a qualified inspection and repair."}); score -= min(40, serious * 20)
    accidents = get_collection("incidents").count_documents({**scope, "repair_status": {"$nin": ["completed", "repaired"]}})
    if accidents: warnings.append({"code": "accident_repairs", "message": f"{accidents} accident repair(s) remain unresolved.", "action": "Complete and document accident repairs."}); score -= min(25, accidents * 12)
    expired = get_collection("vehicle_compliance_records").count_documents({**scope, "expiry_date": {"$lt": today}, "status": {"$ne": "renewed"}, "document_type": {"$in": ["insurance", "roadworthy", "registration"]}})
    if expired: warnings.append({"code": "expired_documents", "message": f"{expired} critical document(s) expired.", "action": "Renew before using the vehicle."}); score -= min(30, expired * 15)
    score=max(0,score); band="good" if score>=80 else "attention" if score>=55 else "poor"
    return {"score": score, "band": band, "warnings": warnings, "disclaimer": "This ownership-care indicator is not a mechanical diagnosis."}


def vehicle_timeline(user_id: str, *, vehicle_id=None, page=1, page_size=25, event_type=None) -> dict:
    owner_id = _owner(user_id); ids = _owned_vehicle_ids(owner_id, vehicle_id); events=[]
    for vehicle in get_collection("vehicles").find({"_id": {"$in": ids}}): events.append({"key": f"vehicle:{vehicle['_id']}:created", "event_type": "vehicle", "title": "Vehicle added", "occurred_at": vehicle.get("created_at"), "vehicle": vehicle.get("registration_number"), "source": {"type": "vehicle", "id": str(vehicle["_id"])}})
    for kind, collection_name in RECORD_COLLECTIONS.items():
        if kind == "reminders": collection_name = "personal_vehicle_reminders"
        query={"record_scope":"personal","personal_owner_user_id":owner_id,"vehicle_id":{"$in":ids}}
        for item in get_collection(collection_name).find(query):
            events.append({"key":f"{kind}:{item['_id']}:created","event_type":kind,"title":item.get("title") or item.get("description") or item.get("document_type") or kind.replace('_',' ').title(),"occurred_at":item.get("incident_at") or item.get("record_date") or item.get("created_at"),"source":{"type":kind,"id":str(item["_id"])}})
    for audit in get_collection("personal_vehicle_audit").find({"actor_id":owner_id}):
        if audit.get("entity_type") == "vehicle" and audit.get("entity_id") not in ids: continue
        if audit.get("action") not in {"mileage_updated", "vehicle_status_changed"}: continue
        events.append({"key":f"audit:{audit['_id']}","event_type":"mileage" if audit["action"]=="mileage_updated" else "status","title":audit["action"].replace('_',' ').title(),"occurred_at":audit.get("created_at"),"details":audit.get("changes"),"source":{"type":"vehicle","id":str(audit.get("entity_id"))}})
    if event_type: events=[item for item in events if item["event_type"]==event_type]
    def sort_key(item):
        value=item.get("occurred_at");
        if isinstance(value,datetime): return value.isoformat()
        return str(value or "")
    events.sort(key=sort_key,reverse=True); unique={item["key"]:item for item in events}; events=list(unique.values()); page=_page(page,1); page_size=_page(page_size,25,100); total=len(events)
    return {"events":_serialize(events[(page-1)*page_size:page*page_size]),"pagination":{"page":page,"page_size":page_size,"total":total,"pages":max(1,(total+page_size-1)//page_size)}}


def get_profile(user_id: str) -> dict:
    return serialize_user(get_collection("users").find_one({"_id": _owner(user_id)}))


def update_profile(user_id: str, payload: dict) -> dict:
    owner_id=_owner(user_id); updates={}
    for key in ("full_name","phone"):
        if key in payload: updates[key]=_text(payload[key],key,required=True,maximum=120)
    updates["updated_at"]=now_utc(); get_collection("users").update_one({"_id":owner_id},{"$set":updates}); _audit("profile_updated",owner_id,"user",owner_id,updates)
    return get_profile(user_id)
