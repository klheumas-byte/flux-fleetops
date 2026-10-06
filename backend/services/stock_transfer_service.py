from __future__ import annotations

from datetime import date, datetime, timezone
from math import ceil
import hashlib
import json
import re
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.delivery_exception import serialize_delivery_exception
from models.delivery_exception_action import serialize_replacement_request, serialize_return_request
from models.delivery_exception_investigation import serialize_delivery_exception_investigation
from models.stock_transfer import serialize_stock_transfer
from services.movement_source_service import ensure_movement_for_source
from services.notification_service import create_notification, notify_roles, resolve_action_notifications
from services.branch_access_service import branch_ids_for_user
from services.rbac_service import role_definition, user_has_permission, user_role_codes
from services.vehicle_availability_service import resolve_vehicle_availability
from utils.api_error import ApiError
from utils.file_validation import validate_attachment_list
from utils.mongo_indexes import ensure_indexes_for_collection


TRANSFER_STATUSES = {"draft", "pending_approval", "approved", "scheduled", "released", "in_transit", "awaiting_receipt", "completed", "cancelled"}
OPERATION_TYPES = {"stock_transfer", "supplier_pickup"}
SUPPLIER_PICKUP_ACTIVE_STATUSES = {"scheduled", "released", "in_transit", "awaiting_receipt"}
LIST_PROJECTION = {
    "transfer_id": 1, "operation_type": 1, "supplier": 1, "supplier_reference": 1, "transfer_items": 1,
    "sending_location_id": 1, "receiving_location_id": 1, "destination_branch_id": 1,
    "sending_location": 1, "receiving_location": 1, "approved_by": 1,
    "released_by": 1, "received_by": 1, "received_by_user_id": 1,
    "receiver_name": 1, "receiver_role": 1, "receiving_branch_id": 1, "received_at": 1,
    "branch_receiving_status": 1, "receipt_confirmation": 1,
    "dispatch_status": 1,
    "receiving_status": 1, "reservation_status": 1, "vehicle_required": 1,
    "vehicle_id": 1, "driver_id": 1, "scheduled_at": 1, "acknowledged_at": 1,
    "requested_date": 1, "purpose": 1,
    "recipient": 1,
    "actual_receiver": 1, "linked_delivery_exception_id": 1, "delivery_exception_status": 1,
    "delivery_exception_summary": 1,
    "original_stock_transfer_id": 1, "source_delivery_exception_id": 1, "replacement_request_id": 1,
    "linked_replacement_transfer_id": 1, "linked_replacement_status": 1,
    "linked_vehicle_movement_id": 1, "linked_waybill_id": 1, "status": 1, "quantity_variance": 1,
    "linked_assignment_id": 1, "custody_history": 1,
    "notes": 1, "created_at": 1, "updated_at": 1, "version": 1,
    "item_count": 1, "acknowledged_by": 1, "released_at": 1,
    "supplier_arrived_at": 1, "supplier_arrived_by": 1,
    "started_at": 1, "started_by": 1, "arrived_at": 1, "arrived_by": 1,
    "verified_at": 1, "verified_by": 1,
    "pickup_confirmation": 1, "collected_quantities": 1, "supplier_shortfall_ids": 1,
    "audit_log": 1,
}

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()-]{5,29}$")


def now_utc():
    return datetime.now(timezone.utc)


def transfers_collection():
    return get_collection("stock_transfers")


def operation_assignments_collection():
    return get_collection("operation_assignments")


def movements_collection():
    return get_collection("vehicle_movements")


def _linked_waybill(document):
    waybill_id = document.get("linked_waybill_id")
    if not isinstance(waybill_id, ObjectId):
        return None, get_collection("waybills")
    collection = get_collection("waybills")
    return collection.find_one({"_id": waybill_id}), collection


def _waybill_quantities(document, field):
    return [
        {"item_id": item["item_id"], "quantity": item.get(field, item.get("quantity"))}
        for item in (document.get("transfer_items") or [])
    ]


def _text(value, *, required=False, field="value"):
    result = str(value or "").strip() or None
    if required and not result:
        raise ApiError(f"{field} is required.", status_code=400)
    return result


def _limited_text(value, *, required=False, field="value", limit=300):
    result = _text(value, required=required, field=field)
    if result and len(result) > limit:
        raise ApiError(f"{field} is too long.", status_code=400)
    return result


ELIGIBLE_RECIPIENT_ROLES = {"branch_manager", "branch_warehouse_coordinator"}


def _external_recipient(value, *, required=True):
    if not isinstance(value, dict):
        if required:
            raise ApiError("recipient must be an object.", status_code=400)
        return None
    full_name = _limited_text(value.get("full_name"), required=True, field="recipient full name")
    primary_phone = _limited_text(value.get("primary_phone"), required=True, field="recipient primary phone", limit=30)
    secondary_phone = _limited_text(value.get("secondary_phone"), field="recipient secondary phone", limit=30)
    email = _limited_text(value.get("email"), field="recipient email", limit=320)
    if not PHONE_PATTERN.fullmatch(primary_phone):
        raise ApiError("recipient primary phone is invalid.", status_code=400)
    if secondary_phone and not PHONE_PATTERN.fullmatch(secondary_phone):
        raise ApiError("recipient secondary phone is invalid.", status_code=400)
    if email and not EMAIL_PATTERN.fullmatch(email):
        raise ApiError("recipient email is invalid.", status_code=400)
    recipient = {
        "full_name": full_name,
        "role": _limited_text(value.get("role"), field="recipient role"),
        "primary_phone": primary_phone,
        "secondary_phone": secondary_phone,
        "email": email,
        "delivery_instructions": _limited_text(value.get("delivery_instructions"), field="delivery instructions", limit=2000),
    }
    if "recipient_type" in value or "recipient_user_id" in value:
        recipient.update({"recipient_user_id": None, "recipient_type": "external"})
    return recipient


def _internal_recipient(value, receiving_branch_id):
    if not isinstance(value, dict):
        raise ApiError("recipient must be an object.", status_code=400)
    if not receiving_branch_id:
        raise ApiError("Select a receiving branch before selecting a FleetOps receiver.", status_code=400)
    recipient_user_id = _oid(value.get("recipient_user_id"), "recipient_user_id")
    user = get_collection("users").find_one({"_id": recipient_user_id})
    status = str((user or {}).get("status") or ("active" if (user or {}).get("active", True) else "inactive")).lower()
    if not user or status != "active":
        raise ApiError("Selected recipient is unavailable.", status_code=409)
    roles = set(user_role_codes(user)) & ELIGIBLE_RECIPIENT_ROLES
    if not roles:
        raise ApiError("Selected recipient must be a Branch Manager or Branch Warehouse Coordinator.", status_code=400)
    assigned = str(user.get("primary_branch_id") or "") == str(receiving_branch_id) or any(
        str(item) == str(receiving_branch_id) for item in (user.get("allowed_branch_ids") or [])
    )
    if not assigned:
        raise ApiError("Selected recipient is not assigned to the receiving branch.", status_code=403)
    role = "branch_manager" if "branch_manager" in roles else "branch_warehouse_coordinator"
    branch = get_collection("branches").find_one({"_id": receiving_branch_id}, {"name": 1}) or {}
    return {
        "recipient_user_id": recipient_user_id, "recipient_type": "fleetops_user",
        "full_name": _limited_text(user.get("full_name"), required=True, field="recipient full name"),
        "role": role_definition(role).get("name") or role.replace("_", " ").title(),
        "branch_id": receiving_branch_id, "branch_name": branch.get("name"),
        "primary_phone": _limited_text(user.get("phone") or user.get("primary_phone"), required=True, field="recipient primary phone", limit=30),
        "secondary_phone": _limited_text(user.get("secondary_phone"), field="recipient secondary phone", limit=30),
        "email": _limited_text(user.get("email"), field="recipient email", limit=320),
        "delivery_instructions": _limited_text(value.get("delivery_instructions"), field="delivery instructions", limit=2000),
    }


def _recipient(value, *, required=True, receiving_branch_id=None):
    if isinstance(value, dict) and value.get("recipient_user_id"):
        return _internal_recipient(value, receiving_branch_id)
    if isinstance(value, dict) and value.get("recipient_type") == "fleetops_user":
        raise ApiError("Select a FleetOps receiver by user ID.", status_code=400)
    return _external_recipient(value, required=required)


def list_stock_transfer_recipient_options(*, branch_id=None, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can select transfer recipients.", status_code=403)
    branches = list(get_collection("branches").find(
        {"$or": [{"status": "active"}, {"status": {"$exists": False}, "active": {"$ne": False}}]}, {"name": 1, "code": 1},
    ).sort("name", ASCENDING))
    selected = _oid(branch_id, "branch_id", required=False)
    if selected and not any(item["_id"] == selected for item in branches):
        raise ApiError("Receiving branch was not found or is inactive.", status_code=404)
    receivers = []
    if selected:
        query = {"status": "active", "$and": [
            {"$or": [{"role": {"$in": list(ELIGIBLE_RECIPIENT_ROLES)}}, {"role_ids": {"$in": list(ELIGIBLE_RECIPIENT_ROLES)}}]},
            {"$or": [{"primary_branch_id": selected}, {"allowed_branch_ids": selected}]},
        ]}
        branch_name = next((item.get("name") for item in branches if item["_id"] == selected), None)
        for user in get_collection("users").find(query).sort("full_name", ASCENDING):
            roles = set(user_role_codes(user)) & ELIGIBLE_RECIPIENT_ROLES
            role = "branch_manager" if "branch_manager" in roles else "branch_warehouse_coordinator"
            receivers.append({
                "id": str(user["_id"]), "full_name": user.get("full_name"), "role": role,
                "role_name": role_definition(role).get("name"), "branch_id": str(selected), "branch_name": branch_name,
                "primary_phone": user.get("phone") or user.get("primary_phone"),
                "secondary_phone": user.get("secondary_phone"), "email": user.get("email"),
            })
    return {
        "branches": [{"id": str(item["_id"]), "name": item.get("name"), "code": item.get("code")} for item in branches],
        "receivers": receivers,
    }


def _operation_type(payload):
    value = _text((payload or {}).get("operation_type")) or "stock_transfer"
    if value not in OPERATION_TYPES:
        raise ApiError("Invalid operation_type.", status_code=400)
    return value


def _supplier(value):
    if not isinstance(value, dict):
        raise ApiError("supplier must be an object.", status_code=400)
    supplier_name = _limited_text(value.get("supplier_name") or value.get("name"), required=True, field="supplier name", limit=300)
    contact_person = _limited_text(value.get("contact_person"), required=True, field="contact person", limit=300)
    primary_phone = _limited_text(value.get("primary_phone"), required=True, field="supplier primary phone", limit=30)
    secondary_phone = _limited_text(value.get("secondary_phone"), field="supplier secondary phone", limit=30)
    email = _limited_text(value.get("email"), field="supplier email", limit=320)
    if not PHONE_PATTERN.fullmatch(primary_phone):
        raise ApiError("supplier primary phone is invalid.", status_code=400)
    if secondary_phone and not PHONE_PATTERN.fullmatch(secondary_phone):
        raise ApiError("supplier secondary phone is invalid.", status_code=400)
    if email and not EMAIL_PATTERN.fullmatch(email):
        raise ApiError("supplier email is invalid.", status_code=400)
    return {
        "supplier_name": supplier_name,
        "contact_person": contact_person,
        "primary_phone": primary_phone,
        "secondary_phone": secondary_phone,
        "email": email,
        "pickup_address": _limited_text(value.get("pickup_address") or value.get("address"), required=True, field="pickup address", limit=1000),
        "pickup_instructions": _limited_text(value.get("pickup_instructions"), field="pickup instructions", limit=2000),
    }


def _reference_label(document):
    return "supplier pickup" if (document.get("operation_type") or "stock_transfer") == "supplier_pickup" else "stock transfer"


def _source_event_prefix(document):
    return "supplier-pickup" if (document.get("operation_type") or "stock_transfer") == "supplier_pickup" else "stock-transfer"


def _audit(event, current_user_id, current_role, *, timestamp=None, details=None):
    actor_id = _oid(current_user_id, "current_user_id")
    actor = get_collection("users").find_one({"_id": actor_id}, {"full_name": 1}) or {}
    return {
        "audit_id": uuid4().hex,
        "event": event,
        "actor_id": actor_id,
        "actor_name": _text(actor.get("full_name")),
        "actor_role": current_role,
        "timestamp": timestamp or now_utc(),
        "details": details or {},
        "immutable": True,
    }


def _oid(value, field, *, required=True):
    if value in (None, "") and not required:
        return None
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field}.", status_code=400)
    return ObjectId(str(value))


def _datetime(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApiError(f"{field} must be a valid date and time.", status_code=400) from exc
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def _date(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ApiError(f"{field} must be a valid date.", status_code=400) from exc


def _items(value, *, field="transfer_items", allow_zero=False):
    if not isinstance(value, list) or not value or len(value) > 200:
        raise ApiError(f"{field} must contain between 1 and 200 items.", status_code=400)
    result = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ApiError(f"Each {field} entry must be an object.", status_code=400)
        name = _text(raw.get("name") or raw.get("item_id") or raw.get("sku"), required=True, field="item name")
        item_id = _text(raw.get("item_id") or raw.get("sku") or name, required=True, field="item identifier")
        try:
            quantity = float(raw.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise ApiError("Item quantity must be numeric.", status_code=400) from exc
        if quantity < 0 or (quantity == 0 and not allow_zero):
            raise ApiError("Item quantity must be non-negative and greater than zero for planned transfers.", status_code=400)
        duplicate_key = item_id.casefold()
        if duplicate_key in seen:
            raise ApiError("Transfer items must not contain duplicate item IDs.", status_code=400)
        seen.add(duplicate_key)
        result.append({"item_id": item_id, "name": name, "quantity": quantity, "unit": _text(raw.get("unit")) or "unit"})
    return result


def _receiving_items(value, planned_items):
    if not isinstance(value, list) or not value:
        raise ApiError("received_items must contain at least one item.", status_code=400)
    planned = {str(item["item_id"]).casefold(): item for item in planned_items or []}
    supplied = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise ApiError("Each received item must be an object.", status_code=400)
        item_id = _text(raw.get("item_id"), required=True, field="item identifier")
        key = item_id.casefold()
        if key not in planned or key in supplied:
            raise ApiError("Received items must match every transferred item exactly once.", status_code=400)
        try:
            received = float(raw.get("received_quantity", raw.get("quantity", 0)))
            good = float(raw.get("good_quantity", received))
            damaged = float(raw.get("damaged_quantity", 0))
            wrong = float(raw.get("wrong_item_quantity", raw.get("wrong_quantity", 0)))
        except (TypeError, ValueError) as exc:
            raise ApiError("Receipt quantities must be numeric.", status_code=400) from exc
        if any(number < 0 for number in (received, good, damaged, wrong)):
            raise ApiError("Receipt quantities cannot be negative.", status_code=400)
        if round(good + damaged + wrong, 3) != round(received, 3):
            raise ApiError("Received quantity must equal good + damaged + wrong-item quantity.", status_code=400)
        sent = float(planned[key].get("quantity") or 0)
        supplied[key] = {
            "item_id": planned[key]["item_id"], "name": planned[key].get("name") or item_id,
            "unit": planned[key].get("unit") or "unit", "sent_quantity": sent, "expected_quantity": sent,
            "quantity": received, "received_quantity": received, "good_quantity": good,
            "damaged_quantity": damaged, "wrong_item_quantity": wrong,
            "missing_quantity": max(round(sent - received, 3), 0),
            "notes": _limited_text(raw.get("notes"), field="receipt notes", limit=2000),
        }
    if set(supplied) != set(planned):
        raise ApiError("Every transferred item must be confirmed exactly once.", status_code=400)
    return list(supplied.values())


def ensure_stock_transfer_indexes():
    ensure_indexes_for_collection(
        transfers_collection(),
        [
            {"keys": [("transfer_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("created_by", ASCENDING), ("idempotency_key", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("operation_type", ASCENDING), ("created_at", DESCENDING), ("_id", DESCENDING)]},
            {"keys": [("sending_location_id", ASCENDING), ("status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("receiving_location_id", ASCENDING), ("status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("recipient.recipient_user_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING), ("scheduled_at", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("linked_vehicle_movement_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("linked_waybill_id", ASCENDING)], "options": {"sparse": True}},
        ],
        collection_name="stock_transfers",
    )
    ensure_indexes_for_collection(
        get_collection("delivery_exceptions"),
        [
            {"keys": [("stock_transfer_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("waybill_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
        ],
        collection_name="delivery_exceptions",
    )
    ensure_indexes_for_collection(
        operation_assignments_collection(),
        [
            {"keys": [("source_key", ASCENDING)], "options": {"unique": True}},
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="operation_assignments",
    )
    ensure_indexes_for_collection(
        get_collection("supplier_shortfalls"),
        [
            {"keys": [("source_key", ASCENDING)], "options": {"unique": True}},
            {"keys": [("supplier_pickup_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="supplier_shortfalls",
    )
    ensure_indexes_for_collection(get_collection("delivery_return_requests"), [
        {"keys": [("delivery_exception_id", ASCENDING)], "options": {"unique": True}},
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
    ], collection_name="delivery_return_requests")
    ensure_indexes_for_collection(get_collection("delivery_replacement_requests"), [
        {"keys": [("delivery_exception_id", ASCENDING)], "options": {"unique": True}},
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
    ], collection_name="delivery_replacement_requests")
    ensure_indexes_for_collection(get_collection("delivery_exception_investigations"), [
        {"keys": [("delivery_exception_id", ASCENDING)], "options": {"unique": True}},
        {"keys": [("status", ASCENDING), ("priority", ASCENDING), ("updated_at", DESCENDING)]},
        {"keys": [("investigator_id", ASCENDING), ("status", ASCENDING)], "options": {"sparse": True}},
    ], collection_name="delivery_exception_investigations")
    ensure_indexes_for_collection(get_collection("delivery_investigation_actions"), [
        {"keys": [("investigation_id", ASCENDING), ("action_type", ASCENDING)], "options": {"unique": True}},
        {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
    ], collection_name="delivery_investigation_actions")


def _get(transfer_id: str, projection=None):
    document = transfers_collection().find_one({"_id": _oid(transfer_id, "transfer_id")}, projection)
    if not document:
        raise ApiError("Stock transfer not found.", status_code=404)
    return document


def _assert_access(document, *, current_user_id, current_role):
    user = get_collection("users").find_one({"_id": _oid(current_user_id, "current_user_id")}) or {"role": current_role}
    roles = set(user_role_codes(user))
    if roles & {"owner", "admin", "system_administrator", "operations_administrator"}:
        return
    if current_role == "driver" and str(document.get("driver_id")) == str(current_user_id):
        return
    if user_has_permission(user, "stock_transfers.view_incoming"):
        _assert_destination_branch_access(document, user)
        return
    raise ApiError("You do not have permission to access this stock transfer.", status_code=403)


def _destination_branch_id(document):
    return document.get("destination_branch_id") or document.get("receiving_location_id")


def _assert_destination_branch_access(document, user):
    destination = _destination_branch_id(document)
    allowed = branch_ids_for_user(user)
    if not destination or (allowed is not None and destination not in allowed):
        raise ApiError("You do not have access to stock transfers for this destination branch.", status_code=403)


def _notify_destination_receivers(document, title, message, *, event, action=False):
    destination = _destination_branch_id(document)
    if not isinstance(destination, ObjectId):
        return
    query = {"status": "active", "$and": [
        {"$or": [{"role": {"$in": ["branch_manager", "branch_warehouse_coordinator"]}}, {"role_ids": {"$in": ["branch_manager", "branch_warehouse_coordinator"]}}]},
        {"$or": [{"primary_branch_id": destination}, {"allowed_branch_ids": destination}]},
    ]}
    for recipient in get_collection("users").find(query, {"_id": 1}):
        create_notification(
            recipient["_id"], title, message, category="inventory", module="stock-transfers",
            priority="high" if action else "medium", reference_type="stock_transfer", reference_id=document["_id"],
            action_type="receive_stock_transfer" if action else None, action_url="stock-transfers",
            action_label="Receive stock" if action else "View incoming stock",
            dedupe_key=f"stock-transfer:{document['_id']}:destination:{event}:{recipient['_id']}",
        )


def _add_query_clause(query, clause):
    if not clause:
        return
    if not query:
        query.update(clause)
        return
    existing = dict(query)
    query.clear()
    query["$and"] = [existing, clause]


def create_stock_transfer(payload: dict, *, current_user_id: str, current_role: str):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can create operations.", status_code=403)
    operation_type = _operation_type(payload)
    supplier = _supplier(payload.get("supplier") or payload) if operation_type == "supplier_pickup" else None
    sending_location = (
        supplier["pickup_address"]
        if operation_type == "supplier_pickup"
        else _text(payload.get("sending_location"), required=True, field="sending_location")
    )
    receiving_location = _text(payload.get("receiving_location"), required=True, field="receiving_location")
    sending_location_id = None if operation_type == "supplier_pickup" else _oid(payload.get("sending_location_id"), "sending_location_id", required=False)
    receiving_location_id = _oid(payload.get("receiving_location_id"), "receiving_location_id", required=False)
    if operation_type == "stock_transfer" and ((sending_location_id and sending_location_id == receiving_location_id) or sending_location.casefold() == receiving_location.casefold()):
        raise ApiError("Sending and receiving locations must be different.", status_code=400)
    timestamp = now_utc()
    transfer_items = _items(payload.get("transfer_items"))
    recipient = _recipient(payload.get("recipient"), required=operation_type != "supplier_pickup", receiving_branch_id=receiving_location_id)
    idempotency_key = _text(payload.get("idempotency_key"))
    if idempotency_key and len(idempotency_key) > 200:
        raise ApiError("idempotency_key is too long.", status_code=400)
    fingerprint = hashlib.sha256(json.dumps({
        "operation_type": operation_type,
        "sending_location": sending_location.casefold(),
        "receiving_location": receiving_location.casefold(),
        "items": transfer_items,
        "requested_date": str(_date(payload.get("requested_date"), "requested_date") or ""),
        "purpose": _text(payload.get("purpose")),
        "notes": _text(payload.get("notes")),
        "recipient": {key: str(value) if isinstance(value, ObjectId) else value for key, value in (recipient or {}).items()} if recipient else None,
        "supplier": supplier,
        "supplier_reference": _text(payload.get("supplier_reference") or payload.get("po_reference") or payload.get("reference")),
    }, sort_keys=True).encode("utf-8")).hexdigest()
    actor_id = _oid(current_user_id, "current_user_id")
    if idempotency_key:
        existing = transfers_collection().find_one({"created_by": actor_id, "idempotency_key": idempotency_key})
        if existing:
            if existing.get("create_fingerprint") != fingerprint:
                raise ApiError("This idempotency key was already used for a different operation.", status_code=409)
            return serialize_stock_transfer(existing, include_items=True)
    document = {
        "transfer_id": f"{'SP' if operation_type == 'supplier_pickup' else 'ST'}-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
        "operation_type": operation_type,
        "origin_type": "external_supplier" if operation_type == "supplier_pickup" else "internal_location",
        "supplier": supplier,
        "supplier_reference": _text(payload.get("supplier_reference") or payload.get("po_reference") or payload.get("reference")),
        "sending_location_id": sending_location_id,
        "receiving_location_id": receiving_location_id,
        "destination_branch_id": receiving_location_id,
        "sending_location": sending_location,
        "receiving_location": receiving_location,
        "transfer_items": transfer_items,
        "item_count": len(transfer_items),
        "received_items": [],
        "quantity_variance": [],
        "approved_by": None, "approved_at": None, "released_by": None,
        "received_by": None, "dispatch_status": "not_released",
        "receiving_status": "not_received", "reservation_status": "not_reserved",
        "inventory_posting_status": "not_configured",
        "vehicle_required": bool(payload.get("vehicle_required", True)),
        "vehicle_id": None, "driver_id": None, "scheduled_at": None,
        "requested_date": _date(payload.get("requested_date"), "requested_date"),
        "purpose": _text(payload.get("purpose")) or ("Supplier pickup" if operation_type == "supplier_pickup" else None),
        "recipient": recipient,
        "linked_assignment_id": None,
        "linked_vehicle_movement_id": None,
        "linked_waybill_id": None,
        "custody_history": [],
        "pickup_confirmation": None,
        "collected_quantities": [],
        "supplier_shortfall_ids": [],
        "create_fingerprint": fingerprint,
        "status": "pending_approval" if payload.get("submit_for_approval") else "draft",
        "notes": _text(payload.get("notes")),
        "created_by": actor_id,
        "audit_log": [_audit("transfer_created", current_user_id, current_role, timestamp=timestamp, details={"operation_type": operation_type})],
        "created_at": timestamp, "updated_at": timestamp, "version": 1,
    }
    if idempotency_key:
        document["idempotency_key"] = idempotency_key
    if document["status"] == "pending_approval":
        document["audit_log"].append(_audit("transfer_submitted", current_user_id, current_role, timestamp=timestamp))
    try:
        document["_id"] = transfers_collection().insert_one(document).inserted_id
    except DuplicateKeyError:
        existing = transfers_collection().find_one({"created_by": actor_id, "idempotency_key": idempotency_key}) if idempotency_key else None
        if existing and existing.get("create_fingerprint") == fingerprint:
            return serialize_stock_transfer(existing, include_items=True)
        raise ApiError("A duplicate operation was prevented.", status_code=409) from None
    if document["status"] == "pending_approval":
        _notify_approval(document)
    return serialize_stock_transfer(document, include_items=True)


def _notify_approval(document):
    is_pickup = (document.get("operation_type") or "stock_transfer") == "supplier_pickup"
    label = "Supplier pickup" if is_pickup else "Stock transfer"
    notify_roles(["owner", "admin"], title=f"{label} awaiting approval", message=f"{document.get('transfer_id')} - {document.get('sending_location')} to {document.get('receiving_location')}", category="inventory", module="supplier-pickup" if is_pickup else "stock-transfers", priority="high", reference_type="stock_transfer", reference_id=document["_id"], action_type="approve_stock_transfer", action_url="supplier-pickup" if is_pickup else "stock-transfers", action_label="Review operation", dedupe_key=f"{_source_event_prefix(document)}:{document['_id']}:approval")


def list_stock_transfers(*, current_user_id: str, current_role: str, page=1, page_size=25, status=None, operation_type=None, active_tasks=False):
    query = {}
    user = get_collection("users").find_one({"_id": _oid(current_user_id, "current_user_id")}) or {"role": current_role}
    roles = set(user_role_codes(user))
    if current_role == "driver":
        query["driver_id"] = _oid(current_user_id, "current_user_id")
    elif roles & {"owner", "admin", "system_administrator", "operations_administrator"}:
        pass
    elif user_has_permission(user, "stock_transfers.view_incoming"):
        allowed = branch_ids_for_user(user)
        if allowed is not None:
            _add_query_clause(query, {"$or": [
                {"destination_branch_id": {"$in": list(allowed)}},
                {"receiving_location_id": {"$in": list(allowed)}},
            ]})
    else:
        raise ApiError("You do not have permission to list stock transfers.", status_code=403)
    if status:
        if status not in TRANSFER_STATUSES:
            raise ApiError("Invalid stock transfer status.", status_code=400)
        query["status"] = status
    if operation_type:
        if operation_type not in OPERATION_TYPES:
            raise ApiError("Invalid operation_type.", status_code=400)
        if operation_type == "stock_transfer":
            _add_query_clause(query, {"$or": [{"operation_type": operation_type}, {"operation_type": {"$exists": False}}]})
        else:
            query["operation_type"] = operation_type
    if current_role == "driver" and active_tasks:
        if operation_type not in {None, "supplier_pickup"}:
            raise ApiError("active_tasks is only supported for Supplier Pickups.", status_code=400)
        # Operational Tasks is a dedicated Supplier Pickup view. Keep this
        # discriminator server-side even if an older client omits it.
        query = {"driver_id": _oid(current_user_id, "current_user_id"), "operation_type": "supplier_pickup"}
        query["status"] = {"$in": list(SUPPLIER_PICKUP_ACTIVE_STATUSES)}
    page, page_size = max(int(page or 1), 1), min(max(int(page_size or 25), 1), 100)
    total = transfers_collection().count_documents(query)
    documents = list(transfers_collection().find(query, LIST_PROJECTION).sort([("created_at", DESCENDING), ("_id", DESCENDING)]).skip((page - 1) * page_size).limit(page_size))
    vehicle_ids = {item.get("vehicle_id") for item in documents if isinstance(item.get("vehicle_id"), ObjectId)}
    driver_ids = {item.get("driver_id") for item in documents if isinstance(item.get("driver_id"), ObjectId)}
    vehicles = {
        item["_id"]: item for item in get_collection("vehicles").find(
            {"_id": {"$in": list(vehicle_ids)}}, {"registration_number": 1, "make": 1, "model": 1},
        )
    } if vehicle_ids else {}
    drivers = {
        item["_id"]: item for item in get_collection("users").find(
            {"_id": {"$in": list(driver_ids)}}, {"full_name": 1},
        )
    } if driver_ids else {}
    transfers = []
    for item in documents:
        payload = serialize_stock_transfer(item, include_items=(current_role == "driver" and active_tasks) or user_has_permission(user, "stock_transfers.view_incoming"))
        vehicle = vehicles.get(item.get("vehicle_id"))
        if vehicle:
            payload["vehicle"] = {
                "id": str(vehicle["_id"]),
                "registration_number": vehicle.get("registration_number"),
                "make": vehicle.get("make"),
                "model": vehicle.get("model"),
            }
        driver = drivers.get(item.get("driver_id"))
        if driver:
            payload["driver"] = {"id": str(driver["_id"]), "full_name": driver.get("full_name")}
        transfers.append(payload)
    return {"transfers": transfers, "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": max(1, ceil(total / page_size))}}


def get_stock_transfer(transfer_id, *, current_user_id, current_role):
    document = _get(transfer_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    payload = serialize_stock_transfer(document, include_items=True)
    waybill, _collection = _linked_waybill(document)
    if waybill:
        from models.waybill import serialize_waybill
        payload["waybill"] = serialize_waybill(waybill, include_audit=True)
    if isinstance(document.get("linked_delivery_exception_id"), ObjectId):
        exception = get_collection("delivery_exceptions").find_one({"_id": document["linked_delivery_exception_id"]})
        if exception:
            payload["delivery_exception"] = serialize_delivery_exception(exception)
            return_request = get_collection("delivery_return_requests").find_one({"delivery_exception_id": exception["_id"]})
            replacement_request = get_collection("delivery_replacement_requests").find_one({"delivery_exception_id": exception["_id"]})
            payload["delivery_exception"]["return_request"] = serialize_return_request(return_request)
            payload["delivery_exception"]["replacement_request"] = serialize_replacement_request(replacement_request)
            replacement_transfer = get_collection("stock_transfers").find_one({"_id": (replacement_request or {}).get("linked_stock_transfer_id")}) if replacement_request else None
            payload["delivery_exception"]["operations_timeline"] = _exception_operations_timeline(exception, replacement_request, replacement_transfer)
            investigation = get_collection("delivery_exception_investigations").find_one({"delivery_exception_id": exception["_id"]})
            actions = list(get_collection("delivery_investigation_actions").find({"investigation_id": investigation["_id"]}).sort("created_at", ASCENDING)) if investigation else []
            payload["delivery_exception"]["investigation"] = serialize_delivery_exception_investigation(investigation, actions=actions)
            if current_role in {"owner", "admin"}:
                users = get_collection("users").find({"role": {"$in": ["owner", "admin"]}, "status": {"$in": ["active", None]}}, {"full_name": 1, "role": 1})
                payload["investigation_users"] = [{"id": str(user["_id"]), "full_name": user.get("full_name") or "Operations user", "role": user.get("role")} for user in users]
    return payload


def _exception_operations_timeline(exception, replacement_request=None, replacement_transfer=None):
    current = exception.get("current_action") or {}
    action_selected_at = current.get("selected_at") or next((item.get("selected_at") for item in exception.get("action_history") or [] if item.get("action")), None)
    stages = [
        ("exception_reported", "Exception Reported", exception.get("reported_at")),
        ("action_selected", "Action Selected", action_selected_at),
        ("replacement_created", "Replacement Created", (replacement_request or {}).get("created_at")),
        ("driver_assigned", "Driver Assigned", (replacement_transfer or {}).get("scheduled_at")),
        ("loaded", "Loaded", (replacement_transfer or {}).get("released_at")),
        ("in_transit", "In Transit", (replacement_transfer or {}).get("started_at")),
        ("delivered", "Delivered", (replacement_transfer or {}).get("arrived_at")),
        ("receiver_verified", "Receiver Verified", (replacement_transfer or {}).get("verified_at")),
        ("exception_resolved", "Exception Resolved", exception.get("resolved_at")),
    ]
    return [{"key": key, "label": label, "completed": timestamp is not None, "timestamp": timestamp} for key, label, timestamp in stages]


def update_stock_transfer_recipient(transfer_id, payload, *, current_user_id, current_role):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can edit transfer recipient details.", status_code=403)
    document = _get(transfer_id)
    if document.get("status") in {"completed", "cancelled"}:
        raise ApiError("Recipient details cannot be edited after the transfer is closed.", status_code=400)
    if document.get("acknowledged_at") or document.get("status") in {"released", "in_transit", "awaiting_receipt"}:
        raise ApiError("Recipient details are read-only after Driver Confirmation. Use a change request for future recipient changes.", status_code=409)
    recipient = _recipient((payload or {}).get("recipient", payload), receiving_branch_id=_destination_branch_id(document))
    if document.get("recipient") == recipient:
        return serialize_stock_transfer(document, include_items=True)
    reason = _limited_text((payload or {}).get("reason"), field="edit reason", limit=1000)
    timestamp = now_utc()
    audit = _audit(
        "recipient_updated",
        current_user_id,
        current_role,
        timestamp=timestamp,
        details={"reason": reason, "after_departure": False},
    )
    update = {
        "$set": {"recipient": recipient, "updated_at": timestamp},
        "$inc": {"version": 1},
        "$push": {"audit_log": audit},
    }
    result = transfers_collection().update_one(
        {"_id": document["_id"], "version": int(document.get("version") or 1)},
        update,
    )
    if result.modified_count != 1:
        raise ApiError("Stock transfer changed while recipient details were being updated.", status_code=409)
    document.update({"recipient": recipient, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1})
    document.setdefault("audit_log", []).append(audit)
    waybill, waybill_collection = _linked_waybill(document)
    if waybill:
        from services.waybill_service import update_waybill_recipient_from_source
        update_waybill_recipient_from_source(
            waybill["_id"], recipient, reason=reason,
            current_user_id=current_user_id, current_role=current_role,
            collection=waybill_collection,
        )
    return serialize_stock_transfer(document, include_items=True)


def submit_stock_transfer(transfer_id, *, current_user_id, current_role):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can submit stock transfers.", status_code=403)
    document = _get(transfer_id)
    if document.get("status") == "pending_approval":
        return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "draft":
        raise ApiError("Only draft stock transfers can be submitted.", status_code=400)
    timestamp = now_utc()
    audit = _audit("transfer_submitted", current_user_id, current_role, timestamp=timestamp)
    updates = {"status": "pending_approval", "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    transfers_collection().update_one({"_id": document["_id"], "status": "draft"}, {"$set": updates, "$push": {"audit_log": audit}})
    document.update(updates); document.setdefault("audit_log", []).append(audit); _notify_approval(document)
    return serialize_stock_transfer(document, include_items=True)


def approve_stock_transfer(transfer_id, *, current_user_id, current_role):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can approve stock transfers.", status_code=403)
    document = _get(transfer_id)
    if document.get("status") in {"approved", "scheduled", "released", "in_transit", "awaiting_receipt", "completed"}:
        return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "pending_approval":
        raise ApiError("This stock transfer is not awaiting approval.", status_code=400)
    timestamp = now_utc(); audit = _audit("transfer_approved", current_user_id, current_role, timestamp=timestamp)
    updates = {"status": "approved", "approved_by": _oid(current_user_id, "current_user_id"), "approved_at": timestamp, "reservation_status": "reserved", "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    transfers_collection().update_one({"_id": document["_id"], "status": "pending_approval"}, {"$set": updates, "$push": {"audit_log": audit}}); document.update(updates); document.setdefault("audit_log", []).append(audit)
    resolve_action_notifications("stock_transfer", document["_id"], action_type="approve_stock_transfer", completed_by=current_user_id)
    return serialize_stock_transfer(document, include_items=True)


def _assert_assignment_resources_available(document, vehicle_id, driver_id):
    vehicle = get_collection("vehicles").find_one(
        {"_id": vehicle_id},
        {"current_operational_location_id": 1, "current_operational_location": 1},
    )
    driver = get_collection("users").find_one(
        {"_id": driver_id, "role": "driver", "status": "active"},
        {"_id": 1},
    )
    if not vehicle or not driver:
        raise ApiError("Selected vehicle or driver is unavailable.", status_code=404)
    availability = resolve_vehicle_availability(
        vehicle_id,
        context={
            "movement_type": document.get("operation_type") or "stock_transfer",
            "exclude_movement_id": document.get("linked_vehicle_movement_id"),
        },
    )
    if not availability.get("is_available"):
        reasons = availability.get("blocking_reasons") or []
        raise ApiError(
            "; ".join(item.get("message") for item in reasons)
            or "Vehicle is unavailable.",
            status_code=409,
        )
    active_transfer = transfers_collection().find_one(
        {
            "_id": {"$ne": document["_id"]},
            "driver_id": driver_id,
            "status": {"$in": ["scheduled", "released", "in_transit"]},
        },
        {"_id": 1, "transfer_id": 1},
    )
    active_operation = get_collection("vehicle_operation_requests").find_one(
        {
            "driver_id": driver_id,
            "status": {"$in": ["scheduled", "movement_in_progress"]},
        },
        {"_id": 1, "request_id": 1},
    )
    active_dispatch = get_collection("dispatch_jobs").find_one(
        {
            "driver_id": driver_id,
            "status": {"$in": ["reserved", "assigned", "accepted", "clarification_requested", "in_progress"]},
        },
        {"_id": 1, "dispatch_job_id": 1},
    )
    if active_transfer or active_operation or active_dispatch:
        raise ApiError("Driver already has an active operational assignment.", status_code=409)
    return vehicle


def _ensure_supplier_pickup_assignment(document, movement, waybill=None, *, current_user_id):
    if (document.get("operation_type") or "stock_transfer") != "supplier_pickup":
        return None
    source_key = f"supplier_pickup:{document['_id']}"
    assignment = None
    if isinstance(document.get("linked_assignment_id"), ObjectId):
        assignment = operation_assignments_collection().find_one(
            {"_id": document["linked_assignment_id"]}
        )
    if assignment is None:
        assignment = operation_assignments_collection().find_one({"source_key": source_key})
    if assignment:
        if assignment.get("driver_id") != document.get("driver_id") or assignment.get("vehicle_id") != document.get("vehicle_id"):
            raise ApiError("Supplier Pickup assignment belongs to another driver or vehicle.", status_code=409)
    else:
        timestamp = now_utc()
        actor_id = _oid(current_user_id, "current_user_id")
        actor = get_collection("users").find_one({"_id": actor_id}, {"role": 1}) or {}
        assignment = {
            "assignment_number": f"OPA-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
            "assignment_type": "supplier_pickup",
            "source_type": "supplier_pickup",
            "source_id": document["_id"],
            "source_key": source_key,
            "source_reference": document.get("transfer_id"),
            "driver_id": document.get("driver_id"),
            "vehicle_id": document.get("vehicle_id"),
            "movement_id": movement["_id"],
            "waybill_id": waybill.get("_id") if waybill else None,
            "supplier": document.get("supplier"),
            "pickup_location": document.get("sending_location"),
            "destination": document.get("receiving_location"),
            "requested_items": document.get("transfer_items") or [],
            "status": "assigned",
            "assigned_by": actor_id,
            "assigned_at": timestamp,
            "confirmed_by": None,
            "confirmed_at": None,
            "audit_log": [_audit(
                "pickup_assignment_created",
                current_user_id,
                actor.get("role") or "admin",
                timestamp=timestamp,
                details={
                    "driver_id": str(document.get("driver_id")),
                    "vehicle_id": str(document.get("vehicle_id")),
                },
            )],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        try:
            assignment["_id"] = operation_assignments_collection().insert_one(assignment).inserted_id
        except DuplicateKeyError:
            assignment = operation_assignments_collection().find_one({"source_key": source_key})
            if assignment is None:
                raise ApiError("A duplicate Supplier Pickup assignment was prevented.", status_code=409) from None
    if waybill and assignment.get("waybill_id") != waybill.get("_id"):
        operation_assignments_collection().update_one(
            {"_id": assignment["_id"]},
            {"$set": {"waybill_id": waybill["_id"], "updated_at": now_utc()}},
        )
        assignment["waybill_id"] = waybill["_id"]
    if document.get("linked_assignment_id") != assignment["_id"]:
        transfers_collection().update_one(
            {"_id": document["_id"]},
            {"$set": {"linked_assignment_id": assignment["_id"], "updated_at": now_utc()}},
        )
        document["linked_assignment_id"] = assignment["_id"]
    return assignment


def _ensure_movement(document, *, current_user_id):
    operation_type = document.get("operation_type") or "stock_transfer"
    event_prefix = _source_event_prefix(document)
    existing = None
    if isinstance(document.get("linked_vehicle_movement_id"), ObjectId):
        existing = movements_collection().find_one({"_id": document["linked_vehicle_movement_id"]})
    if existing is None:
        existing = movements_collection().find_one({"source_key": f"{operation_type}:{document['_id']}"})
    if existing is None:
        availability = resolve_vehicle_availability(document["vehicle_id"], context={"movement_type": operation_type})
        if not availability.get("is_available"):
            raise ApiError("; ".join(item.get("message") for item in availability.get("blocking_reasons") or []) or "Vehicle is unavailable.", status_code=409)
    actor = _oid(current_user_id, "current_user_id"); timestamp = now_utc()
    result = ensure_movement_for_source(source_type=operation_type, source_record_id=document["_id"], source_reference=document.get("transfer_id"), existing_movement=existing, replace_terminal=True, recovery_actor_id=current_user_id, recovery_reason=f"{_reference_label(document).title()} is active and requires a journey movement.", movement_defaults={
        "vehicle_id": document["vehicle_id"], "driver_id": document.get("driver_id"), "movement_custodian_id": None,
        "stock_transfer_id": document["_id"], "movement_type": operation_type, "financial_class": "non_revenue", "status": "approved",
        "requested_departure_time": document.get("scheduled_at"), "origin": document.get("sending_location"), "destination": document.get("receiving_location"),
        "origin_location_id": document.get("sending_location_id"), "destination_location_id": document.get("receiving_location_id"),
        "origin_snapshot": {"name": document.get("sending_location"), "type": document.get("origin_type")}, "destination_snapshot": {"name": document.get("receiving_location")},
        "purpose": document.get("purpose") or f"{_reference_label(document).title()} {document.get('transfer_id')}", "custody_state": "pending_acceptance", "custody_events": [], "custody_version": 0,
        "approved_by": actor, "approved_at": timestamp, "created_by": actor, "created_at": timestamp, "updated_at": timestamp,
    })
    movement = result["movement"]
    if movement.get("vehicle_id") != document.get("vehicle_id") or movement.get("driver_id") != document.get("driver_id"):
        raise ApiError("Stock transfer movement belongs to another driver or vehicle.", status_code=409)
    if document.get("linked_vehicle_movement_id") != movement["_id"]:
        transfers_collection().update_one({"_id": document["_id"]}, {"$set": {"linked_vehicle_movement_id": movement["_id"], "updated_at": now_utc()}}); document["linked_vehicle_movement_id"] = movement["_id"]
    waybill = None
    if operation_type != "supplier_pickup":
        from services.waybill_service import ensure_waybill_for_source
        waybill_result = ensure_waybill_for_source(
            source_type=operation_type,
            source_document=document,
            movement_document=movement,
            current_user_id=current_user_id,
            collection=get_collection("waybills"),
        )
        waybill = waybill_result["waybill"]
        if document.get("linked_waybill_id") != waybill["_id"]:
            transfers_collection().update_one({"_id": document["_id"]}, {"$set": {"linked_waybill_id": waybill["_id"], "updated_at": now_utc()}})
            document["linked_waybill_id"] = waybill["_id"]
    _ensure_supplier_pickup_assignment(
        document,
        movement,
        waybill,
        current_user_id=current_user_id,
    )
    return movement


def _ensure_confirmed_supplier_pickup_waybill(document, *, current_user_id, current_role):
    if (document.get("operation_type") or "stock_transfer") != "supplier_pickup" or not document.get("pickup_confirmation"):
        raise ApiError("Confirm the Supplier Pickup before creating its Digital Waybill.", status_code=400)
    movement = movements_collection().find_one({"_id": document.get("linked_vehicle_movement_id")})
    if movement is None:
        raise ApiError("The Supplier Pickup Operational Task has no linked Vehicle Movement.", status_code=409)
    from services.waybill_service import ensure_waybill_for_source, transition_waybill
    waybill_collection = get_collection("waybills")
    result = ensure_waybill_for_source(
        source_type="supplier_pickup",
        source_document=document,
        movement_document=movement,
        current_user_id=current_user_id,
        collection=waybill_collection,
    )
    waybill = result["waybill"]
    if document.get("linked_waybill_id") != waybill["_id"]:
        transfers_collection().update_one(
            {"_id": document["_id"]},
            {"$set": {"linked_waybill_id": waybill["_id"], "updated_at": now_utc()}},
        )
        document["linked_waybill_id"] = waybill["_id"]
    _ensure_supplier_pickup_assignment(document, movement, waybill, current_user_id=current_user_id)
    if waybill.get("status") == "draft":
        transition_waybill(
            waybill["_id"], "approved", {}, current_user_id=current_user_id,
            current_role=current_role, collection=waybill_collection, source_workflow=True,
        )
        waybill = waybill_collection.find_one({"_id": waybill["_id"]})
    if waybill and waybill.get("status") == "approved":
        transition_waybill(
            waybill["_id"], "driver_confirmed",
            {"statement": "Collected Supplier Pickup quantities were confirmed in Operational Tasks."},
            current_user_id=current_user_id, current_role=current_role,
            collection=waybill_collection, source_workflow=True,
        )
        waybill = waybill_collection.find_one({"_id": waybill["_id"]})
    return waybill, waybill_collection


def _update_supplier_pickup_task(document, status, audit):
    if ((document.get("operation_type") or "stock_transfer") != "supplier_pickup"
            or not isinstance(document.get("linked_assignment_id"), ObjectId)):
        return
    operation_assignments_collection().update_one(
        {"_id": document["linked_assignment_id"], "source_type": "supplier_pickup", "status": {"$ne": status}},
        {"$set": {"status": status, "updated_at": audit["timestamp"]}, "$push": {"audit_log": audit}},
    )


def _reassign_scheduled_transfer(document, payload, *, current_user_id, current_role):
    supplier_pickup = (document.get("operation_type") or "stock_transfer") == "supplier_pickup"
    if document.get("acknowledged_at"):
        raise ApiError("A transfer cannot be reassigned after the driver accepts the Operational Task.", status_code=409)
    vehicle_id = _oid(payload.get("vehicle_id"), "vehicle_id")
    driver_id = _oid(payload.get("driver_id"), "driver_id")
    if supplier_pickup:
        _assert_assignment_resources_available(document, vehicle_id, driver_id)
    else:
        vehicle = get_collection("vehicles").find_one({"_id": vehicle_id}, {"_id": 1})
        driver = get_collection("users").find_one(
            {"_id": driver_id, "role": "driver", "status": "active"},
            {"_id": 1},
        )
        if not vehicle or not driver:
            raise ApiError("Selected vehicle or driver is unavailable.", status_code=404)
        availability = resolve_vehicle_availability(
            vehicle_id,
            context={
                "movement_type": "stock_transfer",
                "exclude_movement_id": document.get("linked_vehicle_movement_id"),
            },
        )
        if not availability.get("is_available"):
            raise ApiError(
                "; ".join(item.get("message") for item in availability.get("blocking_reasons") or [])
                or "Vehicle is unavailable.",
                status_code=409,
            )
    scheduled_at = _datetime(payload.get("scheduled_at"), "scheduled_at") or document.get("scheduled_at")
    if not scheduled_at:
        raise ApiError("scheduled_at is required.", status_code=400)
    movement = None
    if isinstance(document.get("linked_vehicle_movement_id"), ObjectId):
        movement = movements_collection().find_one({"_id": document["linked_vehicle_movement_id"]})
    assignment = (
        operation_assignments_collection().find_one({"_id": document.get("linked_assignment_id")})
        if supplier_pickup
        else None
    )
    if not movement or (supplier_pickup and not assignment):
        raise ApiError("The existing transfer assignment links are incomplete.", status_code=409)
    timestamp = now_utc()
    actor_id = _oid(current_user_id, "current_user_id")
    old_driver_id, old_vehicle_id = document.get("driver_id"), document.get("vehicle_id")
    audit = _audit(
        "driver_reassigned",
        current_user_id,
        current_role,
        timestamp=timestamp,
        details={
            "previous_driver_id": str(old_driver_id),
            "previous_vehicle_id": str(old_vehicle_id),
            "driver_id": str(driver_id),
            "vehicle_id": str(vehicle_id),
        },
    )
    assignment_audit = {**audit, "audit_id": uuid4().hex, "event": "pickup_assignment_reassigned"}
    movement_result = movements_collection().update_one(
        {
            "_id": movement["_id"],
            "source_key": f"{document.get('operation_type') or 'stock_transfer'}:{document['_id']}",
            "status": "approved",
        },
        {"$set": {"driver_id": driver_id, "vehicle_id": vehicle_id, "requested_departure_time": scheduled_at, "updated_at": timestamp}},
    )
    if movement_result.modified_count != 1:
        raise ApiError("Supplier Pickup movement could not be reassigned.", status_code=409)
    if supplier_pickup:
        operation_assignments_collection().update_one(
            {"_id": assignment["_id"], "source_key": f"supplier_pickup:{document['_id']}", "status": "assigned"},
            {
                "$set": {
                    "driver_id": driver_id,
                    "vehicle_id": vehicle_id,
                    "assigned_by": actor_id,
                    "assigned_at": timestamp,
                    "updated_at": timestamp,
                },
                "$push": {"audit_log": assignment_audit},
            },
        )
    updates = {
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "scheduled_at": scheduled_at,
        "scheduled_by": actor_id,
        "updated_at": timestamp,
        "version": int(document.get("version") or 1) + 1,
    }




    transfers_collection().update_one(
        {"_id": document["_id"], "status": "scheduled", "acknowledged_at": None},
        {"$set": updates, "$push": {"audit_log": audit}},
    )
    document.update(updates)
    document.setdefault("audit_log", []).append(audit)
    if not supplier_pickup and isinstance(document.get("linked_waybill_id"), ObjectId):
        get_collection("waybills").update_one(
            {"_id": document["linked_waybill_id"], "status": {"$in": ["draft", "approved", "driver_confirmed"]}},
            {"$set": {"driver_id": driver_id, "vehicle_id": vehicle_id, "updated_at": timestamp}},
        )
    from services.movement_custody_service import transfer_movement_custody
    transfer_movement_custody(
        movement["_id"],
        {
            "to_user_id": str(driver_id),
            "event_type": "transferred_between_drivers",
            "audit_reason": _text(payload.get("reason")) or "Authorized Supplier Pickup reassignment before Driver Confirmation.",
        },
        current_user_id=current_user_id,
        current_role=current_role,
        source_event_key=f"{_source_event_prefix(document)}:{document['_id']}:reassigned:{driver_id}",
    )
    resolve_action_notifications(
        "supplier_pickup" if supplier_pickup else "stock_transfer",
        document["_id"],
        action_type="accept_supplier_pickup" if supplier_pickup else "acknowledge_stock_transfer",
        completed_by=current_user_id,
    )
    create_notification(
        driver_id,
        "Supplier pickup assigned" if supplier_pickup else "Stock transfer assigned",
        f"{document.get('transfer_id')} - Review the transfer details and accept the assignment.",
        category="inventory",
        module="my-operational-tasks",
        priority="high",
        reference_type="supplier_pickup" if supplier_pickup else "stock_transfer",
        reference_id=document["_id"],
        action_type="accept_supplier_pickup" if supplier_pickup else "acknowledge_stock_transfer",
        action_url="my-operational-tasks",
        action_label="Accept Assignment" if supplier_pickup else "Accept Transfer",
        dedupe_key=f"{_source_event_prefix(document)}:{document['_id']}:driver:{driver_id}",
    )
    return serialize_stock_transfer(document, include_items=True)


def schedule_stock_transfer(transfer_id, payload, *, current_user_id, current_role):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can schedule stock transfers.", status_code=403)
    document = _get(transfer_id)
    event_prefix = _source_event_prefix(document)
    operation_label = "Supplier pickup" if (document.get("operation_type") or "stock_transfer") == "supplier_pickup" else "Stock transfer"
    if document.get("status") == "scheduled" and document.get("linked_vehicle_movement_id"):
        requested_vehicle = _oid(payload.get("vehicle_id"), "vehicle_id", required=False)
        requested_driver = _oid(payload.get("driver_id"), "driver_id", required=False)
        if ((requested_vehicle and requested_vehicle != document.get("vehicle_id")) or
                (requested_driver and requested_driver != document.get("driver_id"))):
            return _reassign_scheduled_transfer(
                document,
                payload,
                current_user_id=current_user_id,
                current_role=current_role,
            )
        movement = _ensure_movement(document, current_user_id=current_user_id)
        if not document.get("acknowledged_at"):
            from services.movement_custody_service import transfer_movement_custody
            transfer_movement_custody(movement["_id"], {"to_user_id": str(document["driver_id"]), "event_type": "released_to_driver"}, current_user_id=current_user_id, current_role=current_role, source_event_key=f"{event_prefix}:{document['_id']}:release-to-driver")
        return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "approved":
        raise ApiError(f"Approve the {_reference_label(document)} before scheduling.", status_code=400)
    vehicle_id, driver_id = _oid(payload.get("vehicle_id"), "vehicle_id"), _oid(payload.get("driver_id"), "driver_id")
    if (document.get("operation_type") or "stock_transfer") == "supplier_pickup":
        vehicle = _assert_assignment_resources_available(document, vehicle_id, driver_id)
    else:
        vehicle = get_collection("vehicles").find_one({"_id": vehicle_id}, {"current_operational_location_id": 1, "current_operational_location": 1})
        driver = get_collection("users").find_one({"_id": driver_id, "role": "driver", "status": "active"}, {"_id": 1})
        if not vehicle or not driver:
            raise ApiError("Selected vehicle or driver is unavailable.", status_code=404)
    location_conflict = document.get("sending_location_id") and vehicle.get("current_operational_location_id") and document.get("sending_location_id") != vehicle.get("current_operational_location_id")
    if location_conflict and not _text(payload.get("override_reason")):
        raise ApiError("Vehicle is not currently at the sending location.", status_code=409)
    scheduled_at = _datetime(payload.get("scheduled_at"), "scheduled_at")
    if not scheduled_at:
        raise ApiError("scheduled_at is required.", status_code=400)
    timestamp = now_utc()
    updates = {"vehicle_id": vehicle_id, "driver_id": driver_id, "scheduled_at": scheduled_at, "schedule_override_reason": _text(payload.get("override_reason")), "scheduled_by": _oid(current_user_id, "current_user_id"), "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    document.update(updates); movement = _ensure_movement(document, current_user_id=current_user_id); updates.update({"status": "scheduled", "linked_assignment_id": document.get("linked_assignment_id"), "linked_vehicle_movement_id": movement["_id"]})
    waybill, waybill_collection = _linked_waybill(document)
    if operation_label != "Supplier pickup" and waybill and waybill.get("status") == "draft":
        from services.waybill_service import transition_waybill
        transition_waybill(waybill["_id"], "approved", {}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection)
    from services.movement_custody_service import transfer_movement_custody
    transfer_movement_custody(movement["_id"], {"to_user_id": str(driver_id), "event_type": "released_to_driver"}, current_user_id=current_user_id, current_role=current_role, source_event_key=f"{event_prefix}:{document['_id']}:release-to-driver")
    audit = _audit("driver_assigned", current_user_id, current_role, timestamp=timestamp, details={"driver_id": str(driver_id), "vehicle_id": str(vehicle_id)})
    transfers_collection().update_one({"_id": document["_id"], "status": "approved"}, {"$set": updates, "$push": {"audit_log": audit}}); document.update(updates); document.setdefault("audit_log", []).append(audit)
    notification_reference_type = "supplier_pickup" if operation_label == "Supplier pickup" else "stock_transfer"
    notification_action = "accept_supplier_pickup" if operation_label == "Supplier pickup" else "acknowledge_stock_transfer"
    create_notification(driver_id, f"{operation_label} assigned", f"{document.get('transfer_id')} - Review the items and accept the assignment." if operation_label == "Supplier pickup" else f"{document.get('transfer_id')} - Review the items and accept custody.", category="inventory", module="my-operational-tasks", priority="high", reference_type=notification_reference_type, reference_id=document["_id"], action_type=notification_action, action_url="my-operational-tasks", action_label="Accept Pickup" if operation_label == "Supplier pickup" else "Accept Transfer", dedupe_key=f"{event_prefix}:{document['_id']}:driver:{driver_id}")
    if operation_label == "Stock transfer":
        _notify_destination_receivers(document, "Stock transfer assigned", f"{document.get('transfer_id')} has been assigned for delivery to your branch.", event="assigned")
    return serialize_stock_transfer(document, include_items=True)


def acknowledge_stock_transfer(transfer_id, *, current_user_id, current_role):
    if current_role != "driver":
        raise ApiError("Only the assigned driver can acknowledge this transfer.", status_code=403)
    document = _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if document.get("acknowledged_at"):
        waybill, _waybill_collection = _linked_waybill(document)
        if waybill:
            resolve_action_notifications("waybill", waybill["_id"], action_type="accept_stock_transfer_waybill", completed_by=current_user_id)
        if (document.get("operation_type") or "stock_transfer") == "supplier_pickup":
            resolve_action_notifications("supplier_pickup", document["_id"], action_type="accept_supplier_pickup", completed_by=current_user_id)
        else:
            resolve_action_notifications("stock_transfer", document["_id"], action_type="acknowledge_stock_transfer", completed_by=current_user_id)
        return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "scheduled":
        raise ApiError("This stock transfer is not awaiting driver acknowledgement.", status_code=400)
    from services.movement_custody_service import accept_movement_custody
    accept_movement_custody(document["linked_vehicle_movement_id"], {}, current_user_id=current_user_id, current_role=current_role, source_event_key=f"{_source_event_prefix(document)}:{document['_id']}:driver-acceptance")
    is_pickup = (document.get("operation_type") or "stock_transfer") == "supplier_pickup"
    waybill, waybill_collection = _linked_waybill(document)
    if waybill and waybill.get("status") == "approved":
        from services.waybill_service import transition_waybill
        statement = "Assigned driver accepted the Supplier Pickup assignment." if is_pickup else f"Assigned driver confirmed {_reference_label(document)} custody."
        transition_waybill(waybill["_id"], "driver_confirmed", {"statement": statement}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection)
    timestamp = now_utc()
    audit = _audit("driver_accepted" if is_pickup else "driver_confirmed", current_user_id, current_role, timestamp=timestamp)
    updates = {"acknowledged_at": timestamp, "acknowledged_by": _oid(current_user_id, "current_user_id"), "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    transfers_collection().update_one(
        {"_id": document["_id"], "acknowledged_at": None},
        {"$set": updates, "$push": {"audit_log": audit}},
    )
    document.update(updates); document.setdefault("audit_log", []).append(audit)
    if is_pickup:
        if isinstance(document.get("linked_assignment_id"), ObjectId):
            operation_assignments_collection().update_one(
                {"_id": document["linked_assignment_id"], "status": "assigned"},
                {
                    "$set": {
                        "status": "driver_accepted",
                        "confirmed_by": _oid(current_user_id, "current_user_id"),
                        "confirmed_at": timestamp,
                        "updated_at": timestamp,
                    },
                    "$push": {"audit_log": audit},
                },
            )
    if waybill:
        resolve_action_notifications("waybill", waybill["_id"], action_type="accept_stock_transfer_waybill", completed_by=current_user_id)
    if not is_pickup:
        resolve_action_notifications("stock_transfer", document["_id"], action_type="acknowledge_stock_transfer", completed_by=current_user_id)
    if is_pickup:
        resolve_action_notifications("supplier_pickup", document["_id"], action_type="accept_supplier_pickup", completed_by=current_user_id)
    resolve_action_notifications("stock_transfer", document["_id"], action_type="start_stock_transfer", completed_by=current_user_id)
    return serialize_stock_transfer(document, include_items=True)


def release_stock_transfer(transfer_id, payload, *, current_user_id, current_role):
    document = _get(transfer_id)
    is_pickup = (document.get("operation_type") or "stock_transfer") == "supplier_pickup"
    if is_pickup:
        if current_role != "driver" or document.get("driver_id") != _oid(current_user_id, "current_user_id"):
            raise ApiError("Only the assigned driver can mark a Supplier Pickup as Loaded.", status_code=403)
    elif current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can release stock.", status_code=403)
    if document.get("status") == "released": return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "scheduled": raise ApiError("Schedule the transfer before releasing stock.", status_code=400)
    if not document.get("acknowledged_at"): raise ApiError("The assigned driver must acknowledge custody before stock release.", status_code=400)
    if is_pickup and not document.get("pickup_confirmation"):
        raise ApiError("Confirm collected pickup quantities before marking this pickup as Loaded.", status_code=400)
    # Loading/releasing stock is a business-workflow event.  It must not imply
    # that the vehicle has physically departed; the shared start endpoint owns
    # that transition once the driver records departure fuel.
    _ensure_movement(document, current_user_id=current_user_id)
    waybill, waybill_collection = _linked_waybill(document)
    if is_pickup:
        if (payload or {}).get("loaded_quantities") is not None or (payload or {}).get("loaded_items") is not None:
            raise ApiError("Loaded quantities come from Pickup Confirmation and cannot be entered again.", status_code=400)
        loaded_quantities = document.get("collected_quantities") or []
    else:
        loaded_quantities = (payload or {}).get("loaded_quantities") or (payload or {}).get("loaded_items")
        if loaded_quantities is None:
            loaded_quantities = _waybill_quantities(document, "quantity")
    if waybill and waybill.get("status") == "driver_confirmed":
        from services.waybill_service import transition_waybill
        transition_waybill(waybill["_id"], "loaded", {"quantities": loaded_quantities}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection, source_workflow=is_pickup)
    timestamp = now_utc(); audit = _audit("loaded", current_user_id, current_role, timestamp=timestamp)
    updates = {"status": "released", "dispatch_status": "released", "released_by": _oid(current_user_id, "current_user_id"), "released_at": timestamp, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    if is_pickup:
        updates["loaded_quantities"] = loaded_quantities
    transfers_collection().update_one({"_id": document["_id"], "status": "scheduled"}, {"$set": updates, "$push": {"audit_log": audit}}); document.update(updates); document.setdefault("audit_log", []).append(audit)
    if is_pickup:
        _update_supplier_pickup_task(document, "loaded", audit)
    else:
        _notify_destination_receivers(document, "Stock transfer loaded and dispatched", f"{document.get('transfer_id')} has been loaded and released for delivery to your branch.", event="loaded-dispatched")
    return serialize_stock_transfer(document, include_items=True)


def start_stock_transfer(transfer_id, payload, *, current_user_id, current_role):
    document = _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if (document.get("operation_type") or "stock_transfer") == "supplier_pickup" and current_role != "driver":
        raise ApiError("Only the assigned driver can start a Supplier Pickup journey.", status_code=403)
    if document.get("status") == "in_transit": return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "released": raise ApiError("Stock must be released before movement starts.", status_code=400)
    movement = _ensure_movement(document, current_user_id=current_user_id)
    from services.vehicle_movement_service import start_vehicle_movement
    start_vehicle_movement(str(movement["_id"]), payload or {}, current_user_id=current_user_id, current_role=current_role)
    waybill, waybill_collection = _linked_waybill(document)
    if waybill and waybill.get("status") == "loaded":
        from services.waybill_service import transition_waybill
        transition_waybill(waybill["_id"], "in_transit", {}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection, source_workflow=(document.get("operation_type") or "stock_transfer") == "supplier_pickup")
    timestamp = now_utc(); audit = _audit("journey_started", current_user_id, current_role, timestamp=timestamp)
    updates = {"status": "in_transit", "dispatch_status": "in_transit", "started_by": _oid(current_user_id, "current_user_id"), "started_at": timestamp, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    transfers_collection().update_one({"_id": document["_id"], "status": "released"}, {"$set": updates, "$push": {"audit_log": audit}}); document.update(updates); document.setdefault("audit_log", []).append(audit)
    _update_supplier_pickup_task(document, "in_transit", audit)
    if (document.get("operation_type") or "stock_transfer") == "stock_transfer":
        _notify_destination_receivers(document, "Stock transfer in transit", f"{document.get('transfer_id')} is now in transit to your branch.", event="in-transit")
    return serialize_stock_transfer(document, include_items=True)


def arrive_stock_transfer(transfer_id, payload, *, current_user_id, current_role):
    document = _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    is_pickup = (document.get("operation_type") or "stock_transfer") == "supplier_pickup"
    if is_pickup and document.get("status") == "scheduled":
        return mark_supplier_pickup_arrived(transfer_id, payload, current_user_id=current_user_id, current_role=current_role, document=document)
    if document.get("status") == "awaiting_receipt": return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "in_transit": raise ApiError("Transfer movement is not in progress.", status_code=400)
    movement = _ensure_movement(document, current_user_id=current_user_id)
    from services.vehicle_movement_service import return_vehicle_movement
    return_vehicle_movement(str(movement["_id"]), payload or {}, current_user_id=current_user_id, current_role=current_role)
    from services.movement_custody_service import return_movement_custody
    return_movement_custody(movement["_id"], {**(payload or {}), "to_location": document.get("receiving_location")}, current_user_id=current_user_id, current_role=current_role, source_event_key=f"stock-transfer:{document['_id']}:destination-custody")
    waybill, waybill_collection = _linked_waybill(document)
    if waybill and waybill.get("status") == "in_transit":
        from services.waybill_service import transition_waybill
        transition_waybill(
            waybill["_id"], "delivered", {"physical_delivery_only": True},
            current_user_id=current_user_id, current_role=current_role, collection=waybill_collection,
            source_workflow=is_pickup,
        )
    timestamp = now_utc(); audit = _audit("delivered", current_user_id, current_role, timestamp=timestamp)
    updates = {"status": "awaiting_receipt", "dispatch_status": "delivered", "receiving_status": "awaiting_confirmation", "arrived_by": _oid(current_user_id, "current_user_id"), "arrived_at": timestamp, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    transfers_collection().update_one({"_id": document["_id"], "status": "in_transit"}, {"$set": updates, "$push": {"audit_log": audit}}); document.update(updates); document.setdefault("audit_log", []).append(audit)
    if is_pickup:
        _update_supplier_pickup_task(document, "delivered", audit)
    label = "Supplier pickup" if is_pickup else "Stock transfer"
    notify_roles(["owner", "admin"], title=f"{label} awaiting receipt", message=f"{document.get('transfer_id')} has physically arrived. Confirm quantities before completion.", category="inventory", module="supplier-pickup" if is_pickup else "stock-transfers", priority="high", reference_type="supplier_pickup" if is_pickup else "stock_transfer", reference_id=document["_id"], action_type="verify_supplier_pickup_delivery" if is_pickup else "receive_stock_transfer", action_url="supplier-pickup" if is_pickup else "stock-transfers", action_label="Review delivery" if is_pickup else "Confirm receipt", dedupe_key=f"{_source_event_prefix(document)}:{document['_id']}:receipt")
    if not is_pickup:
        _notify_destination_receivers(document, "Stock transfer ready for receiving", f"{document.get('transfer_id')} has arrived. Confirm item quantities and condition.", event="ready", action=True)
    return serialize_stock_transfer(document, include_items=True)


def mark_supplier_pickup_arrived(transfer_id, payload, *, current_user_id, current_role, document=None):
    if current_role != "driver":
        raise ApiError("Only the assigned driver can mark arrival at the supplier.", status_code=403)
    document = document or _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if document.get("supplier_arrived_at"):
        # Supplier-yard arrival remains complete throughout every later phase.
        # Treat repeated arrival requests as idempotent instead of reviving the
        # former delivery-disabled guard.
        return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "scheduled" or not document.get("acknowledged_at"):
        raise ApiError("The assigned driver must confirm the pickup before supplier arrival.", status_code=400)
    timestamp = now_utc()
    audit = _audit("arrived_at_supplier", current_user_id, current_role, timestamp=timestamp)
    updates = {
        "supplier_arrived_at": timestamp,
        "supplier_arrived_by": _oid(current_user_id, "current_user_id"),
        "updated_at": timestamp,
        "version": int(document.get("version") or 1) + 1,
    }
    result = transfers_collection().update_one(
        {"_id": document["_id"], "status": "scheduled", "supplier_arrived_at": {"$exists": False}},
        {"$set": updates, "$push": {"audit_log": audit}},
    )
    if result.modified_count != 1:
        return serialize_stock_transfer(_get(transfer_id), include_items=True)
    document.update(updates); document.setdefault("audit_log", []).append(audit)
    _update_supplier_pickup_task(document, "arrived_at_supplier", audit)
    return serialize_stock_transfer(document, include_items=True)


def confirm_supplier_pickup(transfer_id, payload, *, current_user_id, current_role):
    if current_role != "driver":
        raise ApiError("Only the assigned driver can confirm collected quantities.", status_code=403)
    document = _get(transfer_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if (document.get("operation_type") or "stock_transfer") != "supplier_pickup":
        raise ApiError("Pickup confirmation is only available for Supplier Pickups.", status_code=400)
    if document.get("pickup_confirmation"):
        _ensure_confirmed_supplier_pickup_waybill(document, current_user_id=current_user_id, current_role=current_role)
        return serialize_stock_transfer(_get(transfer_id), include_items=True)
    if document.get("status") != "scheduled" or not document.get("supplier_arrived_at"):
        raise ApiError("Arrive at the supplier before confirming collected quantities.", status_code=400)
    raw_items = (payload or {}).get("items")
    if not isinstance(raw_items, list):
        raise ApiError("Pickup confirmation items must be a list.", status_code=400)
    expected = {
        str(item.get("item_id") or "").casefold(): item
        for item in (document.get("transfer_items") or [])
    }
    supplied = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ApiError("Each pickup confirmation item must be an object.", status_code=400)
        item_id = _limited_text(raw.get("item_id"), required=True, field="item_id", limit=120)
        key = item_id.casefold()
        if key in supplied:
            raise ApiError("Pickup confirmation items must not contain duplicate item IDs.", status_code=400)
        try:
            collected = float(raw.get("collected_quantity"))
            available = float(raw.get("available_quantity", collected))
        except (TypeError, ValueError) as exc:
            raise ApiError("Available and collected quantities must be numeric.", status_code=400) from exc
        if not all(map(lambda value: value >= 0, (available, collected))):
            raise ApiError("Available and collected quantities cannot be negative.", status_code=400)
        supplied[key] = {
            "item_id": item_id,
            "available_quantity": round(available, 3),
            "collected_quantity": round(collected, 3),
            "shortfall_reason": _limited_text(raw.get("shortfall_reason"), field="shortfall reason", limit=1000),
        }
    if set(supplied) != set(expected):
        raise ApiError("Every requested pickup item must be confirmed exactly once.", status_code=400)
    confirmed_items = []
    for key, requested_item in expected.items():
        supplied_item = supplied[key]
        requested = round(float(requested_item.get("quantity") or 0), 3)
        available = supplied_item["available_quantity"]
        collected = supplied_item["collected_quantity"]
        if available > requested or collected > available:
            raise ApiError("Collected quantity must be less than or equal to available quantity, and available quantity must not exceed requested quantity.", status_code=400)
        shortfall = round(requested - collected, 3)
        if shortfall > 0 and not supplied_item["shortfall_reason"]:
            raise ApiError("A shortfall reason is required when collected quantity is below requested quantity.", status_code=400)
        confirmed_items.append({
            "item_id": requested_item["item_id"],
            "name": requested_item.get("name") or requested_item["item_id"],
            "unit": requested_item.get("unit") or "unit",
            "requested_quantity": requested,
            "available_quantity": available,
            "collected_quantity": collected,
            "shortfall_quantity": shortfall,
            "shortfall_reason": supplied_item["shortfall_reason"] if shortfall > 0 else None,
        })
    timestamp = now_utc()
    actor_id = _oid(current_user_id, "current_user_id")
    shortfall_ids = []
    shortfall_collection = get_collection("supplier_shortfalls")
    for item in confirmed_items:
        if item["shortfall_quantity"] <= 0:
            continue
        source_key = f"supplier_pickup:{document['_id']}:{item['item_id'].casefold()}"
        shortfall = shortfall_collection.find_one({"source_key": source_key})
        if shortfall is None:
            shortfall = {
                "shortfall_number": f"SSF-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
                "source_key": source_key,
                "supplier_pickup_id": document["_id"],
                "supplier_pickup_reference": document.get("transfer_id"),
                "supplier": document.get("supplier"),
                "item_id": item["item_id"],
                "item_name": item["name"],
                "unit": item["unit"],
                "requested_quantity": item["requested_quantity"],
                "available_quantity": item["available_quantity"],
                "collected_quantity": item["collected_quantity"],
                "shortfall_quantity": item["shortfall_quantity"],
                "reason": item["shortfall_reason"],
                "status": "open",
                "reported_by": actor_id,
                "reported_at": timestamp,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            try:
                shortfall["_id"] = shortfall_collection.insert_one(shortfall).inserted_id
            except DuplicateKeyError:
                shortfall = shortfall_collection.find_one({"source_key": source_key})
                if shortfall is None:
                    raise ApiError("A duplicate Supplier Shortfall was prevented.", status_code=409) from None
        shortfall_ids.append(shortfall["_id"])
    confirmation = {
        "items": confirmed_items,
        "confirmed_by": actor_id,
        "confirmed_at": timestamp,
        "immutable": True,
    }
    collected_quantities = [
        {"item_id": item["item_id"], "quantity": item["collected_quantity"]}
        for item in confirmed_items
    ]
    custody = {
        "event": "supplier_to_driver",
        "from": "supplier",
        "from_name": (document.get("supplier") or {}).get("supplier_name") or "Supplier",
        "to": str(document.get("driver_id")),
        "location": document.get("sending_location"),
        "recorded_by": actor_id,
        "recorded_at": timestamp,
        "items": collected_quantities,
        "immutable": True,
    }
    audit = _audit("pickup_confirmed", current_user_id, current_role, timestamp=timestamp, details={"shortfall_count": len(shortfall_ids)})
    updates = {
        "pickup_confirmation": confirmation,
        "collected_quantities": collected_quantities,
        "supplier_shortfall_ids": shortfall_ids,
        "updated_at": timestamp,
        "version": int(document.get("version") or 1) + 1,
    }
    result = transfers_collection().update_one(
        {"_id": document["_id"], "status": "scheduled", "pickup_confirmation": None},
        {"$set": updates, "$push": {"custody_history": custody, "audit_log": audit}},
    )
    if result.modified_count != 1:
        return serialize_stock_transfer(_get(transfer_id), include_items=True)
    document.update(updates)
    document.setdefault("custody_history", []).append(custody)
    document.setdefault("audit_log", []).append(audit)
    waybill, waybill_collection = _ensure_confirmed_supplier_pickup_waybill(
        document, current_user_id=current_user_id, current_role=current_role,
    )
    if waybill:
        waybill_items = []
        confirmed_by_id = {item["item_id"].casefold(): item for item in confirmed_items}
        for item in waybill.get("items") or []:
            pickup_item = confirmed_by_id[item["item_id"].casefold()]
            waybill_items.append({
                **item,
                "available_quantity": pickup_item["available_quantity"],
                "collected_quantity": pickup_item["collected_quantity"],
                "shortfall_quantity": pickup_item["shortfall_quantity"],
                "shortfall_reason": pickup_item["shortfall_reason"],
                "variance": round(pickup_item["collected_quantity"] - pickup_item["requested_quantity"], 3),
            })
        waybill_collection.update_one(
            {"_id": waybill["_id"], "source_type": "supplier_pickup", "status": "driver_confirmed"},
            {"$set": {"items": waybill_items, "updated_at": timestamp}, "$push": {"custody_events": custody, "audit_log": {"event": "pickup_confirmed", "actor_id": actor_id, "timestamp": timestamp, "details": {"shortfall_count": len(shortfall_ids)}, "immutable": True}}},
        )
    _update_supplier_pickup_task(document, "pickup_confirmed", audit)
    return serialize_stock_transfer(document, include_items=True)


def record_supplier_pickup_handover(transfer_id, payload, *, current_user_id, current_role):
    if current_role != "driver":
        raise ApiError("Only the assigned driver can record supplier handover.", status_code=403)
    document = _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if (document.get("operation_type") or "stock_transfer") != "supplier_pickup":
        raise ApiError("Supplier handover is only available for Supplier Pickups.", status_code=400)
    if document.get("supplier_handover"):
        return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "scheduled" or not document.get("supplier_arrived_at"):
        raise ApiError("Mark arrival at the supplier before recording handover.", status_code=400)
    timestamp = now_utc()
    handover = {
        "supplier_representative": _limited_text(payload.get("supplier_representative"), required=True, field="supplier_representative", limit=200),
        "phone": _limited_text(payload.get("phone"), field="phone", limit=30),
        "notes": _limited_text(payload.get("notes"), limit=1000),
        "recorded_by": _oid(current_user_id, "current_user_id"),
        "recorded_at": timestamp,
        "immutable": True,
    }
    if handover.get("phone") and not PHONE_PATTERN.fullmatch(handover["phone"]):
        raise ApiError("phone is invalid.", status_code=400)
    custody = {
        "event": "supplier_to_driver",
        "from": "supplier",
        "from_name": handover["supplier_representative"],
        "to": str(document.get("driver_id")),
        "location": document.get("sending_location"),
        "recorded_by": _oid(current_user_id, "current_user_id"),
        "recorded_at": timestamp,
        "notes": handover.get("notes"),
        "immutable": True,
    }
    audit = _audit("supplier_handover_recorded", current_user_id, current_role, timestamp=timestamp, details={"supplier_representative": handover["supplier_representative"]})
    updates = {"supplier_handover": handover, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    result = transfers_collection().update_one(
        {"_id": document["_id"], "status": "scheduled", "supplier_handover": {"$exists": False}},
        {"$set": updates, "$push": {"custody_history": custody, "audit_log": audit}},
    )
    if result.modified_count != 1:
        return serialize_stock_transfer(_get(transfer_id), include_items=True)
    waybill, waybill_collection = _linked_waybill(document)
    if waybill:
        waybill_collection.update_one({"_id": waybill["_id"]}, {"$push": {"custody_events": custody, "audit_log": {"event": "supplier_handover_recorded", "actor_id": _oid(current_user_id, "current_user_id"), "timestamp": timestamp, "details": {"supplier_representative": handover["supplier_representative"]}, "immutable": True}}, "$set": {"updated_at": timestamp}})
    document.update(updates); document.setdefault("custody_history", []).append(custody); document.setdefault("audit_log", []).append(audit)
    return serialize_stock_transfer(document, include_items=True)


def _resolve_replacement_delivery_exception(document, *, current_user_id, current_role):
    exception_id = document.get("source_delivery_exception_id")
    if not isinstance(exception_id, ObjectId) or document.get("status") != "completed":
        return
    exceptions = get_collection("delivery_exceptions")
    exception = exceptions.find_one({"_id": exception_id})
    if not exception:
        raise ApiError("The replacement's original Delivery Exception was not found.", status_code=409)
    if exception.get("linked_replacement_transfer_id") != document["_id"]:
        raise ApiError("The replacement transfer does not match the original Delivery Exception.", status_code=409)
    replacement_request = get_collection("delivery_replacement_requests").find_one({"delivery_exception_id": exception_id})
    if not replacement_request or replacement_request.get("linked_stock_transfer_id") != document["_id"]:
        raise ApiError("The linked Replacement Request is inconsistent.", status_code=409)
    timestamp = document.get("verified_at") or document.get("completed_at") or now_utc()
    actor_id = _oid(current_user_id, "current_user_id")
    resolution_audit = _audit("exception_resolved", current_user_id, current_role, timestamp=timestamp, details={"replacement_transfer_id": str(document["_id"]), "replacement_request_id": str(replacement_request["_id"])})
    completed_action = {**(exception.get("current_action") or {}), "status": "completed", "completed_at": timestamp}
    result = exceptions.update_one({"_id": exception_id, "status": {"$ne": "resolved"}}, {"$set": {"status": "resolved", "operational_status": "resolved", "resolved_at": timestamp, "resolved_by": actor_id, "resolution": {"type": "replacement_completed", "replacement_transfer_id": document["_id"], "replacement_request_id": replacement_request["_id"], "resolved_at": timestamp}, "linked_replacement_status": "completed", "current_action": completed_action, "updated_at": timestamp}, "$push": {"audit_log": resolution_audit, "action_history": {"action": "dispatch_replacement", "status": "completed", "completed_at": timestamp, "stock_transfer_id": document["_id"]}}})
    original_transfer_id = exception.get("stock_transfer_id")
    original = transfers_collection().find_one({"_id": original_transfer_id}, {"linked_waybill_id": 1}) or {}
    transfer_updates = {"delivery_exception_status": "resolved", "delivery_exception_summary.operational_status": "resolved", "linked_replacement_transfer_id": document["_id"], "linked_replacement_status": "completed", "updated_at": timestamp}
    transfer_update = {"$set": transfer_updates}
    if result.modified_count: transfer_update["$push"] = {"audit_log": resolution_audit}
    transfers_collection().update_one({"_id": original_transfer_id}, transfer_update)
    if original.get("linked_waybill_id"):
        waybill_update = {"$set": {"delivery_exception_status": "resolved", "delivery_exception_summary.operational_status": "resolved", "linked_replacement_transfer_id": document["_id"], "linked_replacement_status": "completed", "updated_at": timestamp}}
        if result.modified_count: waybill_update["$push"] = {"audit_log": {"event": "exception_resolved", "actor_id": actor_id, "timestamp": timestamp, "details": {"replacement_transfer_id": str(document["_id"])}, "immutable": True}}
        get_collection("waybills").update_one({"_id": original["linked_waybill_id"]}, waybill_update)
    replacement_update = {"$set": {"status": "completed", "completed_at": timestamp, "updated_at": timestamp}}
    if result.modified_count: replacement_update["$push"] = {"audit_log": resolution_audit}
    get_collection("delivery_replacement_requests").update_one({"_id": replacement_request["_id"]}, replacement_update)


def verify_stock_transfer_delivery(transfer_id, payload, *, current_user_id, current_role):
    if current_role != "driver":
        raise ApiError("Receiver verification must be recorded through the assigned driver's Waybill session.", status_code=403)
    document = _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    is_pickup = (document.get("operation_type") or "stock_transfer") == "supplier_pickup"
    if document.get("status") == "completed" and document.get("actual_receiver"):
        _resolve_replacement_delivery_exception(document, current_user_id=current_user_id, current_role=current_role)
        return serialize_stock_transfer(document, include_items=True)
    if document.get("linked_delivery_exception_id"):
        raise ApiError("This transfer already has a linked Delivery Exception.", status_code=409)
    if document.get("status") != "awaiting_receipt" or document.get("dispatch_status") != "delivered":
        raise ApiError("The transfer must be Delivered before receiver verification.", status_code=400)
    waybill, waybill_collection = _linked_waybill(document)
    if not waybill:
        raise ApiError("The linked Digital Waybill is required for receiver verification.", status_code=409)
    from services.waybill_service import (
        finalize_stock_transfer_receiver_verification,
        validate_stock_transfer_receiver_review,
    )
    review = validate_stock_transfer_receiver_review(waybill, payload, action="verify")
    finalize_stock_transfer_receiver_verification(
        waybill["_id"], review, current_user_id=current_user_id,
        current_role=current_role, collection=waybill_collection,
    )
    movement = movements_collection().find_one({"_id": document.get("linked_vehicle_movement_id")}, {"status": 1})
    if not movement:
        raise ApiError("The linked Vehicle Movement is required for completion.", status_code=409)
    if movement.get("status") != "closed":
        if movement.get("status") != "returned":
            raise ApiError("The linked Vehicle Movement must be at the destination before completion.", status_code=409)
        from services.vehicle_movement_service import close_vehicle_movement
        close_vehicle_movement(str(movement["_id"]), current_user_id=current_user_id, current_role=current_role)
    timestamp = now_utc()
    receiver = review["actual_receiver"]
    received_items = [
        {"item_id": item["item_id"], "name": item["name"], "quantity": item["received_quantity"], "unit": item.get("unit") or "unit", "condition": item["item_condition"]}
        for item in review["items"]
    ]
    audits = [
        _audit("receiver_verified", current_user_id, current_role, timestamp=timestamp, details={"receiver": receiver["full_name"]}),
        _audit("status_verified", current_user_id, current_role, timestamp=timestamp),
        _audit("status_completed", current_user_id, current_role, timestamp=timestamp),
    ]
    updates = {
        "status": "completed",
        "verification_status": "verified",
        "actual_receiver": receiver,
        "received_items": received_items,
        "quantity_variance": [],
        "receiving_status": "verified",
        "verified_by": _oid(current_user_id, "current_user_id"),
        "verified_at": timestamp,
        "completed_by": _oid(current_user_id, "current_user_id"),
        "completed_at": timestamp,
        "reservation_status": "consumed",
        "updated_at": timestamp,
        "version": int(document.get("version") or 1) + 1,
    }
    result = transfers_collection().update_one(
        {"_id": document["_id"], "status": "awaiting_receipt", "linked_delivery_exception_id": {"$exists": False}},
        {"$set": updates, "$push": {"audit_log": {"$each": audits}}},
    )
    if result.modified_count != 1:
        winner = _get(transfer_id)
        if winner.get("status") == "completed" and winner.get("actual_receiver"):
            _resolve_replacement_delivery_exception(winner, current_user_id=current_user_id, current_role=current_role)
            return serialize_stock_transfer(winner, include_items=True)
        raise ApiError("Stock transfer changed while receiver verification was recorded.", status_code=409)
    document.update(updates); document.setdefault("audit_log", []).extend(audits)
    if is_pickup:
        _update_supplier_pickup_task(document, "completed", audits[-1])
    _resolve_replacement_delivery_exception(document, current_user_id=current_user_id, current_role=current_role)
    resolve_action_notifications("stock_transfer", document["_id"], resolution="receiver_verified", completed_by=current_user_id)
    if is_pickup:
        resolve_action_notifications("supplier_pickup", document["_id"], resolution="receiver_verified", completed_by=current_user_id)
    return serialize_stock_transfer(document, include_items=True)


def report_stock_transfer_delivery_exception(transfer_id, payload, *, current_user_id, current_role):
    if current_role != "driver":
        raise ApiError("Delivery exceptions must be recorded through the assigned driver's Waybill session.", status_code=403)
    document = _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    if (document.get("operation_type") or "stock_transfer") == "supplier_pickup":
        raise ApiError("Supplier Pickup exceptions are not enabled yet.", status_code=409)
    if document.get("status") == "completed":
        raise ApiError("Completed transfers cannot report a Delivery Exception.", status_code=409)
    if document.get("status") != "awaiting_receipt" or document.get("dispatch_status") != "delivered":
        raise ApiError("The transfer must be Delivered before reporting an exception.", status_code=400)
    waybill, waybill_collection = _linked_waybill(document)
    if not waybill:
        raise ApiError("The linked Digital Waybill is required for exception reporting.", status_code=409)
    from services.waybill_service import (
        record_stock_transfer_delivery_exception,
        validate_stock_transfer_receiver_review,
    )
    review = validate_stock_transfer_receiver_review(waybill, payload, action="exception")
    fingerprint = hashlib.sha256(json.dumps(review, sort_keys=True).encode("utf-8")).hexdigest()
    exceptions = get_collection("delivery_exceptions")
    existing = exceptions.find_one({"stock_transfer_id": document["_id"]})
    if existing and existing.get("submission_fingerprint") != fingerprint:
        raise ApiError("A different Delivery Exception is already linked to this transfer.", status_code=409)
    timestamp = now_utc()
    if not existing:
        exception_items = [
            {
                "item_id": item["item_id"],
                "name": item.get("name"),
                "unit": item.get("unit") or "unit",
                "expected_quantity": item["expected_quantity"],
                "received_quantity": item["received_quantity"],
                "exception_quantity": item["exception_quantity"],
                "exception_type": item["item_condition"],
                "variance": item["variance"],
                "notes": item.get("exception_notes"),
                "photos": item.get("exception_photos") or [],
            }
            for item in review["items"] if item.get("item_condition") != "correct"
        ]
        exception = {
            "exception_number": f"DEX-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
            "stock_transfer_id": document["_id"],
            "waybill_id": waybill["_id"],
            "movement_id": document.get("linked_vehicle_movement_id"),
            "driver_id": document.get("driver_id"),
            "status": "open",
            "items": exception_items,
            "actual_receiver": review["actual_receiver"],
            "receiver_acknowledgement": {
                "acknowledged": True,
                "acknowledged_by_name": review["actual_receiver"]["full_name"],
                "acknowledged_at": timestamp,
            },
            "notes": review["actual_receiver"].get("notes"),
            "submission_fingerprint": fingerprint,
            "reported_by": _oid(current_user_id, "current_user_id"),
            "reported_at": timestamp,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        try:
            exception["_id"] = exceptions.insert_one(exception).inserted_id
            existing = exception
        except DuplicateKeyError:
            existing = exceptions.find_one({"stock_transfer_id": document["_id"]})
            if not existing or existing.get("submission_fingerprint") != fingerprint:
                raise ApiError("A Delivery Exception is already linked to this transfer.", status_code=409) from None
    exception_summary = {
        "exception_number": existing["exception_number"],
        "status": existing["status"],
        "affected_item_count": len(existing.get("items") or []),
        "exception_types": sorted({item["exception_type"] for item in existing.get("items") or []}),
        "reported_at": existing["reported_at"],
    }
    record_stock_transfer_delivery_exception(
        waybill["_id"], existing["_id"], review, current_user_id=current_user_id,
        current_role=current_role, collection=waybill_collection, exception_summary=exception_summary,
    )
    received_items = [
        {"item_id": item["item_id"], "name": item["name"], "quantity": item["received_quantity"], "unit": item.get("unit") or "unit", "condition": item["item_condition"]}
        for item in review["items"]
    ]
    variance = [
        {"item_id": item["item_id"], "expected_quantity": item["expected_quantity"], "received_quantity": item["received_quantity"], "difference": item["variance"], "condition": item["item_condition"]}
        for item in review["items"] if item.get("variance") != 0 or item.get("item_condition") != "correct"
    ]
    audit = _audit("delivery_exception_reported", current_user_id, current_role, timestamp=timestamp, details={
        "exception_id": str(existing["_id"]), "exception_number": existing["exception_number"],
        "affected_item_count": len(existing.get("items") or []),
    })
    updates = {
        "actual_receiver": review["actual_receiver"],
        "received_items": received_items,
        "quantity_variance": variance,
        "receiving_status": "exception_reported",
        "linked_delivery_exception_id": existing["_id"],
        "delivery_exception_status": "open",
        "delivery_exception_summary": exception_summary,
        "updated_at": timestamp,
        "version": int(document.get("version") or 1) + 1,
    }
    result = transfers_collection().update_one(
        {"_id": document["_id"], "status": "awaiting_receipt", "linked_delivery_exception_id": {"$exists": False}},
        {"$set": updates, "$push": {"audit_log": audit}},
    )
    if result.modified_count != 1:
        winner = _get(transfer_id)
        if winner.get("linked_delivery_exception_id") == existing["_id"]:
            return serialize_stock_transfer(winner, include_items=True)
        raise ApiError("Stock transfer changed while the Delivery Exception was linked.", status_code=409)
    document.update(updates); document.setdefault("audit_log", []).append(audit)
    notify_roles(
        ["owner", "admin"], title="Stock transfer delivery exception",
        message=f"{document.get('transfer_id')} has a receiver-reported delivery exception.",
        category="inventory", module="stock-transfers", priority="high",
        reference_type="delivery_exception", reference_id=existing["_id"],
        action_url="stock-transfers", action_label="View exception",
        dedupe_key=f"delivery-exception:{existing['_id']}:open",
    )
    return serialize_stock_transfer(document, include_items=True)


EXCEPTION_ACTIONS = {
    "missing": {"dispatch_replacement", "hold_for_investigation", "correct_documentation"},
    "damaged": {"return_item", "hold_for_investigation"},
    "wrong_item": {"return_item", "dispatch_replacement"},
    "excess": {"return_item", "accept_excess"},
}


def _exception_for_transfer(document):
    exception_id = document.get("linked_delivery_exception_id")
    exception = get_collection("delivery_exceptions").find_one({"_id": exception_id}) if exception_id else None
    if not exception:
        raise ApiError("This transfer does not have a Delivery Exception.", status_code=404)
    return exception


def _action_items(exception, action):
    eligible = [item for item in exception.get("items") or [] if action in EXCEPTION_ACTIONS.get(item.get("exception_type"), set())]
    if not eligible:
        raise ApiError("That action is not valid for this Delivery Exception type.", status_code=400)
    return eligible


def _action_audit(event, current_user_id, current_role, timestamp, details=None):
    return _audit(event, current_user_id, current_role, timestamp=timestamp, details=details)


def _sync_exception_status(document, exception, *, status, current_user_id, current_role, event, details=None):
    timestamp = now_utc(); audit = _action_audit(event, current_user_id, current_role, timestamp, details)
    get_collection("delivery_exceptions").update_one({"_id": exception["_id"]}, {"$set": {"operational_status": status, "updated_at": timestamp}, "$push": {"audit_log": audit}})
    transfers_collection().update_one({"_id": document["_id"]}, {"$set": {"delivery_exception_status": status, "delivery_exception_summary.operational_status": status, "updated_at": timestamp}, "$push": {"audit_log": audit}})
    if document.get("linked_waybill_id"):
        get_collection("waybills").update_one({"_id": document["linked_waybill_id"]}, {"$set": {"delivery_exception_status": status, "delivery_exception_summary.operational_status": status, "updated_at": timestamp}, "$push": {"audit_log": {"event": event, "actor_id": _oid(current_user_id, "current_user_id"), "timestamp": timestamp, "details": details or {}, "immutable": True}}})


def _ensure_delivery_return_movement(request: dict, *, current_user_id: str) -> dict:
    existing = None
    linked_id = request.get("linked_vehicle_movement_id")
    if isinstance(linked_id, ObjectId):
        existing = movements_collection().find_one({"_id": linked_id})
    result = ensure_movement_for_source(
        source_type="delivery_return_request",
        source_record_id=request["_id"],
        source_reference=request.get("return_number"),
        existing_movement=existing,
        replace_terminal=True,
        recovery_actor_id=current_user_id,
        recovery_reason="Delivery return remains active and requires a movement.",
        movement_defaults={
            "movement_type": "stock_return",
            "financial_class": "non_revenue",
            "status": "approved",
            "vehicle_id": request.get("vehicle_id"),
            "driver_id": request.get("driver_id"),
            "movement_custodian_id": request.get("driver_id"),
            "origin": request.get("origin"),
            "destination": request.get("destination"),
            "purpose": request.get("return_number"),
            "delivery_exception_id": request.get("delivery_exception_id"),
            "created_by": _oid(current_user_id, "current_user_id"),
        },
    )
    movement = result["movement"]
    if request.get("linked_vehicle_movement_id") != movement["_id"]:
        timestamp = now_utc()
        get_collection("delivery_return_requests").update_one(
            {"_id": request["_id"]},
            {"$set": {"linked_vehicle_movement_id": movement["_id"], "updated_at": timestamp}},
        )
        if isinstance(request.get("linked_waybill_id"), ObjectId):
            get_collection("waybills").update_one(
                {"_id": request["linked_waybill_id"], "movement_id": request.get("linked_vehicle_movement_id")},
                {"$set": {"movement_id": movement["_id"], "vehicle_id": movement.get("vehicle_id"), "driver_id": movement.get("driver_id"), "updated_at": timestamp},
                 "$push": {"audit_log": _action_audit("movement_relinked_after_terminal_recovery", current_user_id, "system", timestamp, {"replacement_movement_id": str(movement["_id"])})}},
            )
        request["linked_vehicle_movement_id"] = movement["_id"]
    return movement


def take_delivery_exception_action(transfer_id, payload, *, current_user_id, current_role):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can select a Delivery Exception action.", status_code=403)
    document = _get(transfer_id); exception = _exception_for_transfer(document)
    action = str((payload or {}).get("action") or "").strip().lower()
    items = _action_items(exception, action)
    current = exception.get("current_action") or {}
    if current.get("status") == "active":
        if current.get("action") == action:
            return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
        raise ApiError("This Delivery Exception already has an active action.", status_code=409)
    if action == "dispatch_replacement" and any(item.get("exception_type") == "wrong_item" for item in items):
        returned = any(entry.get("action") == "return_item" and entry.get("status") == "completed" for entry in exception.get("action_history") or [])
        if not returned:
            raise ApiError("Wrong Item exceptions must complete Return Item before Dispatch Replacement.", status_code=409)
    timestamp = now_utc(); action_id = uuid4().hex
    action_record = {"action_id": action_id, "action": action, "status": "completed" if action == "accept_excess" else "active", "item_ids": [item["item_id"] for item in items], "selected_by": _oid(current_user_id, "current_user_id"), "selected_at": timestamp}

    if action == "return_item":
        driver_id = _oid(payload.get("driver_id"), "driver_id", required=False) or document.get("driver_id")
        vehicle_id = _oid(payload.get("vehicle_id"), "vehicle_id", required=False) or document.get("vehicle_id")
        if not driver_id or not vehicle_id:
            raise ApiError("A returning driver and vehicle are required.", status_code=400)
        request = {"return_number": f"RTR-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}", "delivery_exception_id": exception["_id"], "stock_transfer_id": document["_id"], "original_waybill_id": document.get("linked_waybill_id"), "items": [{"item_id": item["item_id"], "name": item.get("name") or item["item_id"], "unit": item.get("unit") or "unit", "expected_quantity": item["exception_quantity"], "quantity": item["exception_quantity"]} for item in items], "origin": document.get("receiving_location"), "destination": document.get("sending_location"), "vehicle_id": vehicle_id, "driver_id": driver_id, "status": "assigned", "status_history": [{"status": "pending", "timestamp": timestamp}, {"status": "assigned", "timestamp": timestamp}], "audit_log": [_action_audit("return_request_created", current_user_id, current_role, timestamp), _action_audit("return_assigned", current_user_id, current_role, timestamp, {"driver_id": str(driver_id), "vehicle_id": str(vehicle_id)})], "created_by": _oid(current_user_id, "current_user_id"), "created_at": timestamp, "updated_at": timestamp}
        try: request["_id"] = get_collection("delivery_return_requests").insert_one(request).inserted_id
        except DuplicateKeyError: request = get_collection("delivery_return_requests").find_one({"delivery_exception_id": exception["_id"]})
        movement = _ensure_delivery_return_movement(request, current_user_id=current_user_id)
        from services.waybill_service import ensure_waybill_for_source
        waybill = ensure_waybill_for_source(source_type="delivery_return_request", source_document=request, movement_document=movement, current_user_id=current_user_id)["waybill"]
        get_collection("waybills").update_one({"_id": waybill["_id"], "status": "draft"}, {"$set": {"status": "approved", "approved_at": timestamp, "updated_at": timestamp}})
        get_collection("delivery_return_requests").update_one({"_id": request["_id"]}, {"$set": {"linked_vehicle_movement_id": movement["_id"], "linked_waybill_id": waybill["_id"], "updated_at": timestamp}})
        action_record.update({"return_request_id": request["_id"], "movement_id": movement["_id"], "waybill_id": waybill["_id"]})
    elif action == "dispatch_replacement":
        replacement = {"replacement_number": f"RPL-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}", "delivery_exception_id": exception["_id"], "original_stock_transfer_id": document["_id"], "status": "pending", "items": items, "created_by": _oid(current_user_id, "current_user_id"), "created_at": timestamp, "updated_at": timestamp, "audit_log": [_action_audit("replacement_request_created", current_user_id, current_role, timestamp)]}
        try: replacement["_id"] = get_collection("delivery_replacement_requests").insert_one(replacement).inserted_id
        except DuplicateKeyError: replacement = get_collection("delivery_replacement_requests").find_one({"delivery_exception_id": exception["_id"]})
        replacement_transfer = create_stock_transfer({"sending_location": document["sending_location"], "receiving_location": document["receiving_location"], "recipient": document.get("recipient"), "transfer_items": [{"item_id": item["item_id"], "name": item.get("name") or item["item_id"], "quantity": item["exception_quantity"], "unit": item.get("unit") or "unit"} for item in items], "purpose": f"Replacement for {exception['exception_number']}", "notes": "Replacement generated from a Delivery Exception.", "idempotency_key": f"delivery-exception-replacement:{exception['_id']}", "submit_for_approval": True}, current_user_id=current_user_id, current_role=current_role)
        replacement_id = replacement_transfer["id"]
        transfers_collection().update_one({"_id": ObjectId(replacement_id)}, {"$set": {"original_stock_transfer_id": document["_id"], "source_delivery_exception_id": exception["_id"], "replacement_request_id": replacement["_id"]}})
        approve_stock_transfer(replacement_id, current_user_id=current_user_id, current_role=current_role)
        assigned = schedule_stock_transfer(replacement_id, {"vehicle_id": str(document.get("vehicle_id")), "driver_id": str(document.get("driver_id")), "scheduled_at": payload.get("scheduled_at") or timestamp}, current_user_id=current_user_id, current_role=current_role)
        get_collection("delivery_replacement_requests").update_one({"_id": replacement["_id"]}, {"$set": {"status": "assigned", "linked_stock_transfer_id": ObjectId(replacement_id), "linked_waybill_id": ObjectId(assigned["linked_waybill_id"]), "linked_vehicle_movement_id": ObjectId(assigned["linked_vehicle_movement_id"]), "updated_at": timestamp}})
        action_record.update({"replacement_request_id": replacement["_id"], "stock_transfer_id": ObjectId(replacement_id), "waybill_id": ObjectId(assigned["linked_waybill_id"]), "movement_id": ObjectId(assigned["linked_vehicle_movement_id"])})

    audit = _action_audit("exception_action_selected", current_user_id, current_role, timestamp, {"action": action, "action_id": action_id})
    updates = {"current_action": action_record, "operational_status": "action_completed" if action_record["status"] == "completed" else "action_in_progress", "updated_at": timestamp}
    if action == "return_item": updates["linked_return_request_id"] = action_record["return_request_id"]
    if action == "dispatch_replacement": updates.update({"linked_replacement_request_id": action_record["replacement_request_id"], "linked_replacement_transfer_id": action_record["stock_transfer_id"]})
    get_collection("delivery_exceptions").update_one({"_id": exception["_id"], "$or": [{"current_action.status": {"$ne": "active"}}, {"current_action": {"$exists": False}}]}, {"$set": updates, "$push": {"action_history": action_record, "audit_log": audit}})
    exception.update(updates)
    _sync_exception_status(document, exception, status=updates["operational_status"], current_user_id=current_user_id, current_role=current_role, event="exception_action_selected", details={"action": action})
    return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)


def transition_delivery_exception_return(transfer_id, target, payload, *, current_user_id, current_role):
    document = _get(transfer_id); _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    exception = _exception_for_transfer(document)
    request = get_collection("delivery_return_requests").find_one({"delivery_exception_id": exception["_id"]})
    if not request: raise ApiError("No Return Request is linked to this exception.", status_code=404)
    if target == request.get("status") and target != "assigned": return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
    if target == "assigned" and request.get("status") == "assigned" and str(request.get("driver_id")) == str(payload.get("driver_id")) and str(request.get("vehicle_id")) == str(payload.get("vehicle_id")):
        return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
    transitions = {"assigned": {"pending"}, "in_transit": {"assigned"}, "returned": {"in_transit"}, "received_at_origin": {"returned"}}
    if request.get("status") != target and request.get("status") not in transitions.get(target, set()): raise ApiError("Invalid Return Request transition.", status_code=400)
    movement_id = request.get("linked_vehicle_movement_id"); waybill_id = request.get("linked_waybill_id")
    if target == "assigned":
        if current_role not in {"owner", "admin"}: raise ApiError("Only an owner or admin can assign a return.", status_code=403)
        driver_id = _oid(payload.get("driver_id"), "driver_id"); vehicle_id = _oid(payload.get("vehicle_id"), "vehicle_id")
        get_collection("vehicle_movements").update_one({"_id": movement_id, "status": "approved"}, {"$set": {"driver_id": driver_id, "vehicle_id": vehicle_id}})
        get_collection("waybills").update_one({"_id": waybill_id, "status": "approved"}, {"$set": {"driver_id": driver_id, "vehicle_id": vehicle_id}})
        extra = {"driver_id": driver_id, "vehicle_id": vehicle_id}
    elif target == "in_transit":
        movement = _ensure_delivery_return_movement(request, current_user_id=current_user_id)
        movement_id = movement["_id"]
        from services.vehicle_movement_service import start_vehicle_movement
        start_vehicle_movement(str(movement_id), payload or {}, current_user_id=current_user_id, current_role=current_role); get_collection("waybills").update_one({"_id": waybill_id}, {"$set": {"status": "in_transit"}}); extra = {}
    elif target == "returned":
        from services.vehicle_movement_service import return_vehicle_movement
        return_vehicle_movement(str(movement_id), payload or {}, current_user_id=current_user_id, current_role=current_role); get_collection("waybills").update_one({"_id": waybill_id}, {"$set": {"status": "delivered"}}); extra = {}
    else:
        if current_role not in {"owner", "admin"}: raise ApiError("Only an owner or admin can confirm receipt at origin.", status_code=403)
        from services.vehicle_movement_service import close_vehicle_movement
        close_vehicle_movement(str(movement_id), current_user_id=current_user_id, current_role=current_role); get_collection("waybills").update_one({"_id": waybill_id}, {"$set": {"status": "completed", "completed_at": now_utc()}}); extra = {"received_by": _oid(current_user_id, "current_user_id")}
    timestamp = now_utc(); audit = _action_audit(f"return_{target}", current_user_id, current_role, timestamp)
    get_collection("delivery_return_requests").update_one({"_id": request["_id"], "status": request["status"]}, {"$set": {"status": target, **extra, "updated_at": timestamp, f"{target}_at": timestamp}, "$push": {"audit_log": audit, "status_history": {"status": target, "timestamp": timestamp, "actor_id": _oid(current_user_id, "current_user_id")}}})
    if target == "received_at_origin":
        completed_action = {**(exception.get("current_action") or {}), "status": "completed", "completed_at": timestamp}
        get_collection("delivery_exceptions").update_one({"_id": exception["_id"]}, {"$set": {"current_action": completed_action}, "$push": {"action_history": {"action": "return_item", "status": "completed", "completed_at": timestamp}}})
        exception["current_action"] = completed_action
        _sync_exception_status(document, exception, status="action_completed", current_user_id=current_user_id, current_role=current_role, event="return_received_at_origin")
    else: _sync_exception_status(document, exception, status="action_in_progress", current_user_id=current_user_id, current_role=current_role, event=f"return_{target}")
    return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)


INVESTIGATION_STATUSES = {"open", "under_investigation", "awaiting_approval", "approved", "actions_in_progress", "closed"}
INVESTIGATION_PRIORITIES = {"low", "medium", "high", "critical"}
INVESTIGATION_ROOT_CAUSES = {
    "warehouse_picking_error", "warehouse_loading_error", "driver_negligence",
    "transport_accident", "supplier_error", "documentation_error",
    "customer_receiver_error", "suspected_theft", "other",
}
INVESTIGATION_RESPONSIBILITIES = {"warehouse", "driver", "supplier", "customer", "third_party", "shared"}
INVESTIGATION_DECISIONS = {
    "no_action", "retraining", "warning", "supplier_claim", "recovery",
    "hr_case", "finance_case", "write_off", "escalate",
}
INVESTIGATION_TRANSITIONS = {
    "under_investigation": {"open"},
    "awaiting_approval": {"under_investigation"},
    "approved": {"awaiting_approval"},
    "actions_in_progress": {"approved"},
    "closed": {"actions_in_progress"},
}


def _assert_investigation_manager(current_role):
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only an owner or admin can manage Delivery Exception investigations.", status_code=403)


def _investigator(value):
    investigator_id = _oid(value, "investigator_id")
    user = get_collection("users").find_one(
        {"_id": investigator_id, "role": {"$in": ["owner", "admin"]}, "status": {"$in": ["active", None]}},
        {"full_name": 1, "role": 1},
    )
    if not user:
        raise ApiError("Investigator must be an active owner or admin.", status_code=400)
    return investigator_id, user.get("full_name") or "Operations user", user.get("role")


def _choice(value, choices, field):
    result = str(value or "").strip().lower()
    if result not in choices:
        raise ApiError(f"Invalid {field}.", status_code=400)
    return result


RECOVERY_STATUSES = {"not_started", "in_progress", "recovered", "written_off", "not_recoverable"}


def _money(value, field):
    if value in (None, ""):
        return 0.0
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{field} must be numeric.", status_code=400) from exc
    if amount < 0:
        raise ApiError(f"{field} cannot be negative.", status_code=400)
    return amount


def _cost_impact(value, exception=None):
    payload = value if isinstance(value, dict) else {}
    affected_items = payload.get("affected_items")
    if affected_items is None:
        affected_items = [
            {
                "item_id": item.get("item_id"),
                "name": item.get("name"),
                "quantity": item.get("exception_quantity"),
                "exception_type": item.get("exception_type"),
            }
            for item in ((exception or {}).get("items") or [])
        ]
    if not isinstance(affected_items, list):
        raise ApiError("affected_items must be a list.", status_code=400)
    estimated_loss = _money(payload.get("estimated_loss"), "estimated_loss")
    replacement_cost = _money(payload.get("replacement_cost"), "replacement_cost")
    recovered_amount = _money(payload.get("recovered_amount"), "recovered_amount")
    outstanding_amount = round(max(estimated_loss + replacement_cost - recovered_amount, 0), 2)
    recovery_status = str(payload.get("recovery_status") or ("recovered" if outstanding_amount == 0 and recovered_amount > 0 else "not_started")).strip().lower()
    if recovery_status not in RECOVERY_STATUSES:
        raise ApiError("Invalid recovery_status.", status_code=400)
    return {
        "affected_items": affected_items,
        "estimated_loss": estimated_loss,
        "replacement_cost": replacement_cost,
        "recovered_amount": recovered_amount,
        "outstanding_amount": outstanding_amount,
        "recovery_status": recovery_status,
    }


def _case_closure_summary(document, exception, investigation, actions, *, actor_id, timestamp):
    approval = investigation.get("approval") or {}
    return {
        "status": document.get("status"),
        "exception_status": exception.get("status"),
        "replacement_status": exception.get("linked_replacement_status") or document.get("linked_replacement_status"),
        "investigation_status": "closed",
        "root_cause": investigation.get("root_cause"),
        "responsibility": investigation.get("responsibility"),
        "decision": investigation.get("decision"),
        "linked_actions": [
            {
                "id": action.get("_id"),
                "action_type": action.get("action_type"),
                "status": action.get("status"),
                "completed_at": action.get("completed_at"),
            }
            for action in actions
        ],
        "cost_impact": investigation.get("cost_impact") or _cost_impact({}, exception),
        "approved_by": approval.get("approved_by"),
        "approved_on": approval.get("approved_on") or approval.get("approved_at"),
        "approval_comments": approval.get("approval_comments"),
        "closed_by": actor_id,
        "closed_on": timestamp,
    }


def _investigation_for_exception(exception, *, required=True):
    investigation = get_collection("delivery_exception_investigations").find_one({"delivery_exception_id": exception["_id"]})
    if required and not investigation:
        raise ApiError("This Delivery Exception does not have an Investigation.", status_code=404)
    return investigation


def start_delivery_exception_investigation(transfer_id, payload, *, current_user_id, current_role):
    _assert_investigation_manager(current_role)
    document = _get(transfer_id); exception = _exception_for_transfer(document)
    if exception.get("status") != "resolved":
        raise ApiError("Investigation can start only after the Delivery Exception is operationally resolved.", status_code=409)
    existing = _investigation_for_exception(exception, required=False)
    if existing:
        return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
    investigator_id, investigator_name, investigator_role = _investigator((payload or {}).get("investigator_id"))
    priority = _choice((payload or {}).get("priority") or "medium", INVESTIGATION_PRIORITIES, "priority")
    note = _limited_text((payload or {}).get("note") or (payload or {}).get("notes"), field="investigation note", limit=4000)
    evidence = validate_attachment_list((payload or {}).get("evidence") or [], field_name="evidence", max_files=10)
    timestamp = now_utc(); actor_id = _oid(current_user_id, "current_user_id")
    audit = _audit("investigation_opened", current_user_id, current_role, timestamp=timestamp, details={"investigator_id": str(investigator_id), "priority": priority})
    investigation = {
        "investigation_number": f"INV-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}",
        "delivery_exception_id": exception["_id"], "stock_transfer_id": document["_id"],
        "waybill_id": exception.get("waybill_id"), "movement_id": exception.get("movement_id"),
        "replacement_transfer_id": exception.get("linked_replacement_transfer_id"),
        "status": "open", "priority": priority,
        "investigator_id": investigator_id, "investigator_name": investigator_name, "investigator_role": investigator_role,
        "notes": [{"note_id": uuid4().hex, "text": note, "actor_id": actor_id, "actor_role": current_role, "created_at": timestamp}] if note else [],
        "evidence": evidence, "root_cause": None, "responsibility": None, "decision": None,
        "cost_impact": _cost_impact((payload or {}).get("cost_impact"), exception),
        "suspected_theft_confirmed": False, "approval": None,
        "closure_summary": None,
        "status_history": [{"status": "open", "timestamp": timestamp, "actor_id": actor_id}],
        "audit_log": [audit], "created_by": actor_id, "created_at": timestamp, "updated_at": timestamp, "version": 1,
    }
    try:
        investigation["_id"] = get_collection("delivery_exception_investigations").insert_one(investigation).inserted_id
    except DuplicateKeyError:
        return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
    get_collection("delivery_exceptions").update_one({"_id": exception["_id"]}, {"$set": {"investigation_id": investigation["_id"], "investigation_status": "open", "updated_at": timestamp}, "$push": {"audit_log": audit}})
    transfers_collection().update_one({"_id": document["_id"]}, {"$set": {"delivery_exception_summary.investigation_status": "open", "updated_at": timestamp}, "$push": {"audit_log": audit}})
    return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)


def update_delivery_exception_investigation(transfer_id, payload, *, current_user_id, current_role):
    _assert_investigation_manager(current_role)
    document = _get(transfer_id); exception = _exception_for_transfer(document); investigation = _investigation_for_exception(exception)
    if investigation.get("status") not in {"open", "under_investigation"}:
        raise ApiError("Investigation findings are locked after they are submitted for approval.", status_code=409)
    updates = {}; details = {}; timestamp = now_utc(); actor_id = _oid(current_user_id, "current_user_id")
    if "investigator_id" in payload:
        investigator_id, investigator_name, investigator_role = _investigator(payload.get("investigator_id"))
        updates.update({"investigator_id": investigator_id, "investigator_name": investigator_name, "investigator_role": investigator_role})
        details["investigator_id"] = str(investigator_id)
    if "priority" in payload:
        updates["priority"] = _choice(payload.get("priority"), INVESTIGATION_PRIORITIES, "priority"); details["priority"] = updates["priority"]
    for field, choices in (("root_cause", INVESTIGATION_ROOT_CAUSES), ("responsibility", INVESTIGATION_RESPONSIBILITIES), ("decision", INVESTIGATION_DECISIONS)):
        if field in payload:
            updates[field] = _choice(payload.get(field), choices, field); details[field] = updates[field]
    if "cost_impact" in payload:
        updates["cost_impact"] = _cost_impact(payload.get("cost_impact"), exception)
        details["cost_impact"] = updates["cost_impact"]
    note = _limited_text(payload.get("note") or payload.get("notes"), field="investigation note", limit=4000)
    evidence = validate_attachment_list(payload.get("evidence"), field_name="evidence", max_files=10) if "evidence" in payload else []
    if not updates and not note and not evidence:
        return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
    audit = _audit("investigation_updated", current_user_id, current_role, timestamp=timestamp, details=details)
    operation = {"$set": {**updates, "updated_at": timestamp}, "$inc": {"version": 1}, "$push": {"audit_log": audit}}
    if note:
        operation["$push"]["notes"] = {"note_id": uuid4().hex, "text": note, "actor_id": actor_id, "actor_role": current_role, "created_at": timestamp}
    if evidence:
        operation["$push"]["evidence"] = {"$each": [{**item, "evidence_id": item.get("id") or uuid4().hex, "uploaded_by": actor_id, "uploaded_at": timestamp} for item in evidence]}
    result = get_collection("delivery_exception_investigations").update_one({"_id": investigation["_id"], "version": investigation.get("version", 1), "status": {"$in": ["open", "under_investigation"]}}, operation)
    if result.modified_count != 1:
        raise ApiError("Investigation changed while it was being updated.", status_code=409)
    return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)


def _decision_action_type(investigation):
    decision = investigation.get("decision")
    if decision == "no_action": return None
    if decision == "retraining": return "warehouse_action" if investigation.get("responsibility") == "warehouse" else "operations_action"
    if decision in {"warning", "hr_case"}: return "hr_action"
    if decision == "supplier_claim": return "supplier_claim"
    if decision in {"recovery", "finance_case", "write_off"}: return "finance_recovery"
    if decision == "escalate": return "operations_action"
    return None


def _ensure_investigation_actions(investigation, *, current_user_id, current_role, timestamp):
    action_type = _decision_action_type(investigation)
    if not action_type:
        return
    record = {
        "investigation_id": investigation["_id"], "delivery_exception_id": investigation["delivery_exception_id"],
        "action_type": action_type, "status": "pending", "decision": investigation.get("decision"),
        "responsibility": investigation.get("responsibility"), "created_by": _oid(current_user_id, "current_user_id"),
        "created_at": timestamp, "updated_at": timestamp,
        "audit_log": [_audit("investigation_action_generated", current_user_id, current_role, timestamp=timestamp, details={"action_type": action_type})],
    }
    try:
        get_collection("delivery_investigation_actions").insert_one(record)
    except DuplicateKeyError:
        pass


def transition_delivery_exception_investigation(transfer_id, target, payload, *, current_user_id, current_role):
    _assert_investigation_manager(current_role)
    target = str(target or "").strip().lower()
    if target not in INVESTIGATION_STATUSES or target == "open":
        raise ApiError("Invalid Investigation transition.", status_code=400)
    document = _get(transfer_id); exception = _exception_for_transfer(document); investigation = _investigation_for_exception(exception)
    if investigation.get("status") == target:
        return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
    if investigation.get("status") not in INVESTIGATION_TRANSITIONS.get(target, set()):
        raise ApiError("Invalid Investigation transition.", status_code=400)
    if target == "under_investigation" and not investigation.get("investigator_id"):
        raise ApiError("Assign an investigator before starting the Investigation.", status_code=400)
    if target == "awaiting_approval":
        missing = [field for field in ("root_cause", "responsibility", "decision") if not investigation.get(field)]
        if missing:
            raise ApiError("Root cause, responsibility, and decision are required before approval.", status_code=400)
        if investigation.get("root_cause") == "other" and not (investigation.get("notes") or []):
            raise ApiError("Other root cause requires an Investigation note.", status_code=400)
    if target == "approved":
        if current_role != "owner":
            raise ApiError("Management approval must be recorded by an owner.", status_code=403)
        if investigation.get("root_cause") == "suspected_theft" and (payload or {}).get("confirm_suspected_theft") is not True:
            raise ApiError("Suspected Theft requires explicit management confirmation.", status_code=400)
    if target == "closed":
        pending = get_collection("delivery_investigation_actions").count_documents({"investigation_id": investigation["_id"], "status": {"$ne": "completed"}})
        if pending:
            raise ApiError("All linked Investigation actions must be completed before the case can close.", status_code=409)
    timestamp = now_utc(); actor_id = _oid(current_user_id, "current_user_id")
    audit = _audit(f"investigation_{target}", current_user_id, current_role, timestamp=timestamp)
    updates = {"status": target, "updated_at": timestamp, f"{target}_at": timestamp}
    if target == "approved":
        comments = _limited_text((payload or {}).get("approval_comments") or (payload or {}).get("comments"), field="approval comments", limit=2000)
        updates["approval"] = {"approved_by": actor_id, "approved_on": timestamp, "approved_at": timestamp, "actor_role": current_role, "approval_comments": comments}
        updates["suspected_theft_confirmed"] = investigation.get("root_cause") == "suspected_theft"
    if target == "closed":
        actions = list(get_collection("delivery_investigation_actions").find({"investigation_id": investigation["_id"]}).sort("created_at", ASCENDING))
        updates.update({"closed_by": actor_id, "closed_on": timestamp, "closed_at": timestamp, "closure_summary": _case_closure_summary(document, exception, investigation, actions, actor_id=actor_id, timestamp=timestamp)})
    result = get_collection("delivery_exception_investigations").update_one(
        {"_id": investigation["_id"], "status": investigation["status"]},
        {"$set": updates, "$inc": {"version": 1}, "$push": {"status_history": {"status": target, "timestamp": timestamp, "actor_id": actor_id}, "audit_log": audit}},
    )
    if result.modified_count != 1:
        winner = _investigation_for_exception(exception)
        if winner.get("status") == target:
            return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
        raise ApiError("Investigation changed while its status was updated.", status_code=409)
    investigation.update(updates)
    if target == "approved": _ensure_investigation_actions(investigation, current_user_id=current_user_id, current_role=current_role, timestamp=timestamp)
    get_collection("delivery_exceptions").update_one({"_id": exception["_id"]}, {"$set": {"investigation_status": target, "updated_at": timestamp}, "$push": {"audit_log": audit}})
    transfer_updates = {"delivery_exception_summary.investigation_status": target, "updated_at": timestamp}
    if target == "closed":
        transfer_updates["delivery_exception_summary.closure_summary"] = updates["closure_summary"]
    transfers_collection().update_one({"_id": document["_id"]}, {"$set": transfer_updates, "$push": {"audit_log": audit}})
    return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)


def complete_delivery_investigation_action(transfer_id, action_id, payload, *, current_user_id, current_role):
    _assert_investigation_manager(current_role)
    document = _get(transfer_id); exception = _exception_for_transfer(document); investigation = _investigation_for_exception(exception)
    if investigation.get("status") != "actions_in_progress":
        raise ApiError("Linked actions can be completed only while actions are in progress.", status_code=409)
    action = get_collection("delivery_investigation_actions").find_one({"_id": _oid(action_id, "action_id"), "investigation_id": investigation["_id"]})
    if not action: raise ApiError("Investigation action not found.", status_code=404)
    if action.get("status") == "completed": return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)
    notes = _limited_text((payload or {}).get("notes"), field="completion notes", limit=4000)
    timestamp = now_utc(); audit = _audit("investigation_action_completed", current_user_id, current_role, timestamp=timestamp, details={"action_type": action.get("action_type")})
    result = get_collection("delivery_investigation_actions").update_one({"_id": action["_id"], "status": "pending"}, {"$set": {"status": "completed", "completion_notes": notes, "completed_by": _oid(current_user_id, "current_user_id"), "completed_at": timestamp, "updated_at": timestamp}, "$push": {"audit_log": audit}})
    if result.modified_count:
        get_collection("delivery_exception_investigations").update_one({"_id": investigation["_id"]}, {"$set": {"updated_at": timestamp}, "$push": {"audit_log": audit}})
        get_collection("delivery_exceptions").update_one({"_id": exception["_id"]}, {"$push": {"audit_log": audit}, "$set": {"updated_at": timestamp}})
    return get_stock_transfer(transfer_id, current_user_id=current_user_id, current_role=current_role)


def receive_stock_transfer(transfer_id, payload, *, current_user_id, current_role):
    document = _get(transfer_id)
    actor = get_collection("users").find_one({"_id": _oid(current_user_id, "current_user_id")}) or {"role": current_role}
    roles = set(user_role_codes(actor))
    is_branch_receiver = bool(roles & {"branch_manager", "branch_warehouse_coordinator"})
    is_privileged_receiver = bool(roles & {"owner", "admin", "system_administrator", "operations_administrator"})
    if not is_privileged_receiver:
        if not is_branch_receiver or not user_has_permission(actor, "stock_transfers.receive"):
            raise ApiError("You do not have permission to receive stock transfers.", status_code=403)
        _assert_destination_branch_access(document, actor)
    if (document.get("operation_type") or "stock_transfer") == "supplier_pickup":
        raise ApiError("Supplier Pickup receipt is not enabled yet.", status_code=409)
    if document.get("branch_receiving_status") or document.get("receiving_status") == "received": return serialize_stock_transfer(document, include_items=True)
    if document.get("status") != "awaiting_receipt": raise ApiError("This transfer is not awaiting receipt.", status_code=400)
    if is_branch_receiver and payload.get("confirmed") is not True:
        raise ApiError("Final receiver confirmation is required.", status_code=400)
    received_items = _receiving_items(payload.get("received_items"), document.get("transfer_items") or [])
    planned = {item["item_id"]: float(item["quantity"]) for item in document.get("transfer_items") or []}
    received = {item["item_id"]: float(item["received_quantity"]) for item in received_items}
    variance = [{
        "item_id": item["item_id"], "expected_quantity": item["expected_quantity"], "received_quantity": item["received_quantity"],
        "difference": item["received_quantity"] - item["expected_quantity"], "good_quantity": item["good_quantity"],
        "damaged_quantity": item["damaged_quantity"], "wrong_item_quantity": item["wrong_item_quantity"],
        "missing_quantity": item["missing_quantity"], "notes": item.get("notes"),
    } for item in received_items if item["received_quantity"] != item["expected_quantity"] or item["damaged_quantity"] or item["wrong_item_quantity"]]
    waybill, waybill_collection = _linked_waybill(document)
    if waybill and waybill.get("status") == "in_transit":
        from services.waybill_service import transition_waybill
        transition_waybill(
            waybill["_id"], "delivered",
            {"receiver": _text(actor.get("full_name")) or f"Operations user {current_user_id}", "quantities": [{"item_id": item_id, "quantity": received.get(item_id, 0)} for item_id in planned]},
            current_user_id=current_user_id, current_role=current_role, collection=waybill_collection,
        )
    elif waybill and waybill.get("status") == "delivered":
        from services.waybill_service import record_waybill_destination_receipt
        record_waybill_destination_receipt(
            waybill["_id"],
            {"receiver": _text(actor.get("full_name")) or f"Operations user {current_user_id}", "quantities": [{"item_id": item_id, "quantity": received.get(item_id, 0)} for item_id in planned]},
            current_user_id=current_user_id, current_role=current_role, collection=waybill_collection,
        )
    timestamp = now_utc()
    receiver_role_code = "branch_manager" if "branch_manager" in roles else "branch_warehouse_coordinator" if "branch_warehouse_coordinator" in roles else current_role if current_role in roles else next(iter(roles), current_role)
    receiver_role = role_definition(receiver_role_code).get("name") or str(receiver_role_code).replace("_", " ").title()
    receiving_branch_id = _destination_branch_id(document)
    signature = _text(payload.get("receiver_signature") or payload.get("signature"))
    initials = _limited_text(payload.get("receiver_initials"), field="receiver initials", limit=20)
    if signature and len(signature) > 1_500_000:
        raise ApiError("Receiver signature is too large.", status_code=400)
    branch = get_collection("branches").find_one({"_id": receiving_branch_id}, {"name": 1}) if isinstance(receiving_branch_id, ObjectId) else None
    manual_receiver = payload.get("actual_receiver") if is_privileged_receiver else None
    if manual_receiver is not None and not isinstance(manual_receiver, dict):
        raise ApiError("actual_receiver must be an object.", status_code=400)
    if isinstance(manual_receiver, dict) and manual_receiver.get("receiver_type") == "external":
        receiver_name = _limited_text(manual_receiver.get("full_name"), required=True, field="actual receiver name")
        receiver_contact = _limited_text(manual_receiver.get("primary_contact"), required=True, field="actual receiver contact")
        receiver_role = _limited_text(manual_receiver.get("role"), field="actual receiver role") or "External recipient"
        actual_receiver = {
            "receiver_type": "external", "user_id": None, "full_name": receiver_name,
            "primary_contact": receiver_contact, "role": receiver_role,
            "branch_id": receiving_branch_id, "branch_name": (branch or {}).get("name") or document.get("receiving_location"),
            "initials": initials, "signature": signature,
            "notes": _limited_text(manual_receiver.get("notes", payload.get("notes")), field="receiver notes", limit=2000),
            "acknowledged": True,
        }
    else:
        receiver_name = _text(actor.get("full_name")) or f"Operations user {current_user_id}"
        receiver_contact = _text(actor.get("phone") or actor.get("email"))
        actual_receiver = {
            "receiver_type": "fleetops_user", "user_id": _oid(current_user_id, "current_user_id"),
            "full_name": receiver_name, "primary_contact": receiver_contact,
            "role": receiver_role, "branch_id": receiving_branch_id,
            "branch_name": (branch or {}).get("name") or document.get("receiving_location"),
            "initials": initials, "signature": signature,
            "notes": _limited_text(payload.get("notes"), field="receiver notes", limit=2000),
            "acknowledged": True,
        }
    outcome = "RECEIVED_WITH_VARIANCE" if variance else "VERIFIED"
    confirmation = {"confirmed_by": _oid(current_user_id, "current_user_id"), "confirmed_at": timestamp, "receiver_name": receiver_name, "receiver_role": receiver_role, "receiver_contact": receiver_contact, "receiving_branch_id": receiving_branch_id, "initials": initials, "signature": signature, "immutable": True}
    audit = _audit("branch_receipt_confirmed" if is_branch_receiver else "receipt_recorded", current_user_id, receiver_role_code, timestamp=timestamp, details={"outcome": outcome, "variance_count": len(variance)})
    updates = {
        "received_items": received_items, "quantity_variance": variance, "receiving_status": "received",
        "received_by": _oid(current_user_id, "current_user_id"), "received_by_user_id": _oid(current_user_id, "current_user_id"),
        "receiver_name": receiver_name, "receiver_role": receiver_role, "receiving_branch_id": receiving_branch_id,
        "actual_receiver": actual_receiver,
        "received_at": timestamp,
        "updated_at": timestamp, "version": int(document.get("version") or 1) + 1,
    }
    if is_branch_receiver:
        updates.update({"branch_receiving_status": outcome, "receipt_confirmation": confirmation})
    if variance and is_branch_receiver:
        exception_items = []
        for item in received_items:
            exception_quantities = (("missing", item["missing_quantity"]), ("damaged", item["damaged_quantity"]), ("wrong_item", item["wrong_item_quantity"]), ("excess", max(item["received_quantity"] - item["expected_quantity"], 0)))
            for exception_type, quantity in exception_quantities:
                if quantity:
                    exception_items.append({"item_id": item["item_id"], "name": item["name"], "unit": item["unit"], "expected_quantity": item["expected_quantity"], "received_quantity": item["received_quantity"], "exception_quantity": quantity, "exception_type": exception_type, "variance": item["received_quantity"] - item["expected_quantity"], "notes": item.get("notes"), "photos": []})
        exceptions = get_collection("delivery_exceptions")
        existing = exceptions.find_one({"stock_transfer_id": document["_id"]})
        if not existing:
            existing = {"exception_number": f"DEX-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}", "stock_transfer_id": document["_id"], "waybill_id": document.get("linked_waybill_id"), "movement_id": document.get("linked_vehicle_movement_id"), "driver_id": document.get("driver_id"), "status": "open", "items": exception_items, "notes": _limited_text(payload.get("notes"), field="receipt notes", limit=2000), "reported_by": _oid(current_user_id, "current_user_id"), "reported_at": timestamp, "created_at": timestamp, "updated_at": timestamp, "audit_log": [audit]}
            existing["_id"] = exceptions.insert_one(existing).inserted_id
        summary = {"exception_number": existing["exception_number"], "status": existing.get("status", "open"), "affected_item_count": len(existing.get("items") or []), "exception_types": sorted({item["exception_type"] for item in existing.get("items") or []}), "reported_at": existing.get("reported_at")}
        updates.update({"receiving_status": "exception_reported", "linked_delivery_exception_id": existing["_id"], "delivery_exception_status": "open", "delivery_exception_summary": summary})
    transfers_collection().update_one({"_id": document["_id"], "receiving_status": {"$ne": "received"}}, {"$set": updates, "$push": {"audit_log": audit}}); document.update(updates); document.setdefault("audit_log", []).append(audit)
    resolve_action_notifications("stock_transfer", document["_id"], action_type="receive_stock_transfer", completed_by=current_user_id)
    if variance and is_branch_receiver:
        notify_roles(["owner", "admin"], title="Stock transfer receiving variance", message=f"{document.get('transfer_id')} was received with a quantity or condition variance.", category="inventory", module="stock-transfers", priority="high", reference_type="delivery_exception", reference_id=updates["linked_delivery_exception_id"], action_url="stock-transfers", action_label="Review exception", dedupe_key=f"delivery-exception:{updates['linked_delivery_exception_id']}:open")
    return serialize_stock_transfer(document, include_items=True)


def complete_stock_transfer(transfer_id, payload, *, current_user_id, current_role):
    if current_role not in {"owner", "admin"}: raise ApiError("Only an owner or admin can complete stock transfers.", status_code=403)
    document = _get(transfer_id)
    if document.get("status") == "completed": return serialize_stock_transfer(document, include_items=True)
    exception_id = document.get("linked_delivery_exception_id")
    if exception_id:
        exception = get_collection("delivery_exceptions").find_one(
            {"_id": exception_id}, {"status": 1, "operational_status": 1}
        )
        exception_resolved = (
            (exception or {}).get("status") == "resolved"
            or (exception or {}).get("operational_status") == "resolved"
            or (not exception and document.get("delivery_exception_status") == "resolved")
        )
        if not exception_resolved:
            raise ApiError("An open Delivery Exception blocks transfer completion.", status_code=409)
    if document.get("recipient") and not document.get("actual_receiver"):
        raise ApiError("Actual receiver verification is required before completion.", status_code=409)
    if document.get("status") != "awaiting_receipt" or document.get("receiving_status") != "received": raise ApiError("Receiving confirmation is required before completion.", status_code=400)
    if document.get("quantity_variance") and not (document.get("variance_review") or _text(payload.get("variance_resolution"))):
        raise ApiError("An audited variance resolution is required before completion.", status_code=400)
    waybill, waybill_collection = _linked_waybill(document)
    if waybill and waybill.get("status") == "delivered":
        from services.waybill_service import review_waybill_variance, transition_waybill
        if waybill.get("has_variance") and not waybill.get("variance_review"):
            review_waybill_variance(waybill["_id"], {"resolution": payload.get("variance_resolution")}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection)
        transition_waybill(waybill["_id"], "verified", {}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection)
        transition_waybill(waybill["_id"], "completed", {}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection)
    elif waybill and waybill.get("status") == "verified":
        from services.waybill_service import transition_waybill
        transition_waybill(waybill["_id"], "completed", {}, current_user_id=current_user_id, current_role=current_role, collection=waybill_collection)
    from services.vehicle_movement_service import close_vehicle_movement
    close_vehicle_movement(str(document["linked_vehicle_movement_id"]), current_user_id=current_user_id, current_role=current_role)
    variance_review = document.get("variance_review")
    if document.get("quantity_variance") and not variance_review:
        variance_review = {"resolution": _text(payload.get("variance_resolution")), "reviewed_by": _oid(current_user_id, "current_user_id"), "reviewed_at": now_utc()}
    updates = {"status": "completed", "reservation_status": "consumed", "inventory_posting_status": "awaiting_external_inventory_posting", "variance_resolution": _text(payload.get("variance_resolution")), "variance_review": variance_review, "completed_by": _oid(current_user_id, "current_user_id"), "completed_at": now_utc(), "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    transfers_collection().update_one({"_id": document["_id"]}, {"$set": updates}); document.update(updates)
    resolve_action_notifications("stock_transfer", document["_id"], resolution="completed", completed_by=current_user_id)
    return serialize_stock_transfer(document, include_items=True)


def review_stock_transfer_variance(transfer_id, payload, *, current_user_id, current_role):
    document = _get(transfer_id)
    actor = get_collection("users").find_one({"_id": _oid(current_user_id, "current_user_id")}) or {"role": current_role}
    roles = set(user_role_codes(actor))
    if not (roles & {"owner", "admin", "system_administrator", "operations_administrator"}):
        if not user_has_permission(actor, "stock_transfers.report_variance"):
            raise ApiError("You do not have permission to report stock transfer variance.", status_code=403)
        _assert_destination_branch_access(document, actor)
    if document.get("status") != "awaiting_receipt" or document.get("receiving_status") != "received":
        raise ApiError("Receive the stock transfer before reviewing variance.", status_code=400)
    if not document.get("quantity_variance"):
        raise ApiError("This stock transfer has no quantity variance.", status_code=400)
    resolution = _text(payload.get("resolution") or payload.get("variance_resolution"), required=True, field="variance resolution")
    existing_review = document.get("variance_review")
    if existing_review:
        if existing_review.get("resolution") != resolution:
            raise ApiError("Stock transfer variance has already been reviewed.", status_code=409)
        return serialize_stock_transfer(document, include_items=True)
    waybill, waybill_collection = _linked_waybill(document)
    if waybill and waybill.get("has_variance") and not waybill.get("variance_review"):
        from services.waybill_service import review_waybill_variance
        review_waybill_variance(
            waybill["_id"], {"resolution": resolution, "notes": payload.get("notes")},
            current_user_id=current_user_id, current_role=current_role, collection=waybill_collection,
        )
    timestamp = now_utc()
    review = {
        "resolution": resolution,
        "notes": _text(payload.get("notes")),
        "reviewed_by": _oid(current_user_id, "current_user_id"),
        "reviewed_at": timestamp,
    }
    updates = {"variance_review": review, "variance_resolution": resolution, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1}
    result = transfers_collection().update_one({"_id": document["_id"], "variance_review": {"$in": [None]}}, {"$set": updates})
    if result.modified_count != 1:
        winner = _get(transfer_id)
        if (winner.get("variance_review") or {}).get("resolution") == resolution:
            return serialize_stock_transfer(winner, include_items=True)
        raise ApiError("Stock transfer variance changed while it was being reviewed.", status_code=409)
    document.update(updates)
    return serialize_stock_transfer(document, include_items=True)


def cancel_stock_transfer(transfer_id, payload, *, current_user_id, current_role):
    if current_role not in {"owner", "admin"}: raise ApiError("Only an owner or admin can cancel stock transfers.", status_code=403)
    document = _get(transfer_id)
    if document.get("status") == "cancelled": return serialize_stock_transfer(document, include_items=True)
    if document.get("status") in {"in_transit", "awaiting_receipt", "completed"}: raise ApiError("This transfer cannot be cancelled at its current stage.", status_code=400)
    reason = _text(payload.get("reason"), required=True, field="cancellation reason")
    movement_id = document.get("linked_vehicle_movement_id")
    if movement_id:
        movement = movements_collection().find_one({"_id": movement_id}, {"status": 1})
        if movement and movement.get("status") in {"draft", "pending_approval", "approved"}:
            from services.vehicle_movement_service import cancel_vehicle_movement
            cancel_vehicle_movement(str(movement_id), {"cancellation_reason": reason}, current_user_id=current_user_id, current_role=current_role)
    updates = {"status": "cancelled", "reservation_status": "released", "cancellation_reason": reason, "cancelled_by": _oid(current_user_id, "current_user_id"), "cancelled_at": now_utc(), "updated_at": now_utc(), "version": int(document.get("version") or 1) + 1}
    transfers_collection().update_one({"_id": document["_id"]}, {"$set": updates}); document.update(updates)
    resolve_action_notifications(
        "supplier_pickup" if (document.get("operation_type") or "stock_transfer") == "supplier_pickup" else "stock_transfer",
        document["_id"],
        resolution="cancelled",
        completed_by=current_user_id,
    )
    return serialize_stock_transfer(document, include_items=True)
