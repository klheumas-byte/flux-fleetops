from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.waybill import serialize_waybill
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


WAYBILL_SOURCE_DEFINITIONS = {
    "dispatch_job": {"collection": "dispatch_jobs", "module": "dispatch"},
    "stock_transfer": {"collection": "stock_transfers", "module": "stock_transfers"},
    "delivery_return_request": {"collection": "delivery_return_requests", "module": "stock_transfers"},
    "supplier_pickup": {"collection": "supplier_pickups", "module": "supplier_pickups"},
    "vehicle_operation_request": {
        "collection": "vehicle_operation_requests",
        "module": "operational_requests",
    },
}
WAYBILL_STATUSES = (
    "draft",
    "approved",
    "driver_confirmed",
    "loaded",
    "in_transit",
    "delivered",
    "verified",
    "completed",
)
NEXT_STATUS = dict(zip(WAYBILL_STATUSES, WAYBILL_STATUSES[1:]))
ADMIN_ROLES = {"owner", "admin"}
DELIVERY_ITEM_CONDITIONS = {"correct", "missing", "damaged", "wrong_item", "excess"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def waybills_collection():
    return get_collection("waybills")


def ensure_waybill_indexes():
    ensure_indexes_for_collection(
        waybills_collection(),
        [
            {"keys": [("waybill_number", ASCENDING)], "options": {"unique": True}},
            {
                "keys": [("source_key", ASCENDING)],
                "options": {
                    "name": "waybill_source_key_unique",
                    "unique": True,
                    "partialFilterExpression": {"source_key": {"$type": "string"}},
                },
            },
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING)]},
            {"keys": [("movement_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("items.item_id", ASCENDING)]},
        ],
        collection_name="waybills",
    )


def _text(value, *, field: str = "value", required: bool = False, limit: int = 2000):
    result = str(value or "").strip() or None
    if required and not result:
        raise ApiError(f"{field} is required.", status_code=400)
    if result and len(result) > limit:
        raise ApiError(f"{field} is too long.", status_code=400)
    return result


def _oid(value, field: str, *, required: bool = True):
    if value in (None, "") and not required:
        return None
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {field}.", status_code=400)
    return ObjectId(str(value))


def _quantity(value, field: str, *, required: bool = False):
    if value in (None, "") and not required:
        return None
    try:
        quantity = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{field} must be numeric.", status_code=400) from exc
    if quantity < 0:
        raise ApiError(f"{field} cannot be negative.", status_code=400)
    return round(quantity, 3)


def _coordinate(value, field: str, *, minimum: float, maximum: float):
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{field} must be numeric.", status_code=400) from exc
    if coordinate < minimum or coordinate > maximum:
        raise ApiError(f"Invalid {field}.", status_code=400)
    return round(coordinate, 7)


def normalize_waybill_items(value, *, allow_empty: bool = False) -> list[dict]:
    if not isinstance(value, list) or (not value and not allow_empty) or len(value) > 500:
        minimum = "0" if allow_empty else "1"
        raise ApiError(f"items must contain between {minimum} and 500 items.", status_code=400)
    normalized = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ApiError("Each waybill item must be an object.", status_code=400)
        item_id = _text(
            raw.get("item_id") or raw.get("sku") or raw.get("product_id"),
            field="item_id",
            required=True,
            limit=120,
        )
        duplicate_key = item_id.casefold()
        if duplicate_key in seen:
            raise ApiError("Waybill items must not contain duplicate item IDs.", status_code=400)
        seen.add(duplicate_key)
        expected = _quantity(
            raw.get("expected_quantity", raw.get("quantity")),
            "expected_quantity",
            required=True,
        )
        if expected <= 0:
            raise ApiError("expected_quantity must be greater than zero.", status_code=400)
        loaded = _quantity(raw.get("loaded_quantity"), "loaded_quantity")
        received = _quantity(raw.get("received_quantity"), "received_quantity")
        serial_numbers = raw.get("serial_numbers") or []
        photos = raw.get("photos") or []
        if not isinstance(serial_numbers, list) or len(serial_numbers) > 500:
            raise ApiError("serial_numbers must be a list with at most 500 entries.", status_code=400)
        if not isinstance(photos, list) or len(photos) > 20:
            raise ApiError("photos must be a list with at most 20 entries.", status_code=400)
        serial_numbers = [
            _text(item, field="serial number", required=True, limit=200)
            for item in serial_numbers
        ]
        if len({item.casefold() for item in serial_numbers}) != len(serial_numbers):
            raise ApiError("Serial numbers must not contain duplicates.", status_code=400)
        normalized.append(
            {
                "item_id": item_id,
                "sku": _text(raw.get("sku"), limit=120) or item_id,
                "name": _text(raw.get("name"), required=True, field="item name", limit=300),
                "unit": _text(raw.get("unit"), limit=50) or "unit",
                "expected_quantity": expected,
                "loaded_quantity": loaded,
                "received_quantity": received,
                "variance": round(received - expected, 3) if received is not None else None,
                "notes": _text(raw.get("notes"), field="item notes"),
                "serial_numbers": serial_numbers,
                "photos": [_text(item, field="photo", required=True, limit=500000) for item in photos],
            }
        )
    return normalized


def _source_key(source_type: str, source_id) -> str:
    normalized_type = str(source_type or "").strip().lower()
    if normalized_type not in WAYBILL_SOURCE_DEFINITIONS:
        raise ApiError("Unsupported Waybill source type.", status_code=400)
    return f"{normalized_type}:{source_id}"


def _audit(event: str, actor_id, *, details: dict | None = None, timestamp=None) -> dict:
    return {
        "audit_id": uuid4().hex,
        "event": event,
        "actor_id": _oid(actor_id, "current_user_id"),
        "timestamp": timestamp or now_utc(),
        "details": details or {},
        "immutable": True,
    }


def _get(waybill_id, projection=None, *, collection=None) -> dict:
    target_collection = collection if collection is not None else waybills_collection()
    document = target_collection.find_one(
        {"_id": _oid(waybill_id, "waybill_id")}, projection
    )
    if not document:
        raise ApiError("Digital Waybill not found.", status_code=404)
    return document


def _assert_access(document: dict, *, current_user_id: str, current_role: str, mutate=False):
    if current_role in ADMIN_ROLES:
        return
    if current_role == "driver" and document.get("driver_id") == _oid(current_user_id, "current_user_id"):
        return
    verb = "modify" if mutate else "access"
    raise ApiError(f"You do not have permission to {verb} this Digital Waybill.", status_code=403)


def _assert_not_operational_task_owned(document: dict):
    if document.get("source_type") == "supplier_pickup":
        raise ApiError("Supplier Pickup Waybills are read-only. Continue the workflow in Operational Tasks.", status_code=409)


def _source_defaults(source_type: str, source_document: dict) -> tuple[list[dict], dict]:
    if source_type == "stock_transfer":
        items = [
            {
                "item_id": item.get("item_id") or item.get("sku"),
                "sku": item.get("sku") or item.get("item_id"),
                "name": item.get("name") or item.get("item_id"),
                "unit": item.get("unit") or "unit",
                "expected_quantity": item.get("quantity"),
            }
            for item in (source_document.get("transfer_items") or [])
        ]
        return items, {
            "reference": source_document.get("transfer_id"),
            "origin": source_document.get("sending_location"),
            "destination": source_document.get("receiving_location"),
        }
    if source_type == "supplier_pickup":
        confirmed_items = ((source_document.get("pickup_confirmation") or {}).get("items") or [])
        source_items = confirmed_items or (source_document.get("transfer_items") or [])
        items = [
            {
                "item_id": item.get("item_id") or item.get("sku"),
                "sku": item.get("sku") or item.get("item_id"),
                "name": item.get("name") or item.get("item_id"),
                "unit": item.get("unit") or "unit",
                "expected_quantity": item.get("collected_quantity", item.get("quantity")),
            }
            for item in source_items
        ]
        return items, {
            "reference": source_document.get("transfer_id"),
            "origin": source_document.get("sending_location"),
            "destination": source_document.get("receiving_location"),
        }
    if source_type == "delivery_return_request":
        return source_document.get("items") or [], {
            "reference": source_document.get("return_number"),
            "origin": source_document.get("origin"),
            "destination": source_document.get("destination"),
        }
    if source_type == "dispatch_job":
        return source_document.get("waybill_items") or [], {
            "reference": source_document.get("dispatch_job_id"),
            "origin": source_document.get("pickup"),
            "destination": source_document.get("destination"),
        }
    if source_type == "vehicle_operation_request":
        return source_document.get("operation_items") or [], {
            "reference": source_document.get("request_id"),
            "origin": source_document.get("origin"),
            "destination": source_document.get("destination"),
        }
    return source_document.get("items") or [], {
        "reference": source_document.get("pickup_id") or source_document.get("reference"),
        "origin": source_document.get("origin") or source_document.get("supplier_location"),
        "destination": source_document.get("destination"),
    }


def ensure_waybill_for_source(
    *,
    source_type: str,
    source_document: dict,
    movement_document: dict,
    current_user_id: str | ObjectId,
    collection=None,
) -> dict:
    target = collection if collection is not None else waybills_collection()
    normalized_type = str(source_type or "").strip().lower()
    source_id = source_document.get("_id")
    if normalized_type not in WAYBILL_SOURCE_DEFINITIONS or not isinstance(source_id, ObjectId):
        raise ApiError("Invalid Digital Waybill source.", status_code=400)
    if not isinstance(movement_document.get("_id"), ObjectId):
        raise ApiError("A linked Vehicle Movement is required for a Digital Waybill.", status_code=400)
    expected_source_key = _source_key(normalized_type, source_id)
    movement_source_key = movement_document.get("source_key")
    if movement_source_key and movement_source_key != expected_source_key:
        raise ApiError("Vehicle Movement belongs to a different source.", status_code=409)
    existing = target.find_one({"source_key": expected_source_key})
    if existing:
        if existing.get("movement_id") != movement_document["_id"]:
            raise ApiError("Digital Waybill is linked to a different Vehicle Movement.", status_code=409)
        return {"waybill": existing, "created": False}

    raw_items, source_details = _source_defaults(normalized_type, source_document)
    items = normalize_waybill_items(raw_items, allow_empty=True)
    timestamp = now_utc()
    document = {
        "waybill_number": f"DWB-{timestamp.strftime('%Y%m%d')}-{uuid4().hex[:7].upper()}",
        "source_type": normalized_type,
        "source_id": source_id,
        "source_key": expected_source_key,
        "source_module": WAYBILL_SOURCE_DEFINITIONS[normalized_type]["module"],
        "source_reference": source_details["reference"],
        "movement_id": movement_document["_id"],
        "vehicle_id": movement_document.get("vehicle_id") or source_document.get("vehicle_id"),
        "driver_id": movement_document.get("driver_id") or source_document.get("driver_id"),
        "scheduled_at": source_document.get("scheduled_at") or movement_document.get("requested_departure_time"),
        "origin": movement_document.get("origin") or source_details["origin"],
        "destination": movement_document.get("destination") or source_details["destination"],
        "recipient": source_document.get("recipient") if normalized_type in {"stock_transfer", "supplier_pickup"} else None,
        "status": "draft",
        "items": items,
        "has_variance": False,
        "variance_review": None,
        "confirmations": [],
        "custody_events": [],
        "signatures": {},
        "notes": source_document.get("notes"),
        "audit_log": [_audit("waybill_created", current_user_id, timestamp=timestamp)],
        "created_by": _oid(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "version": 1,
    }
    try:
        document["_id"] = target.insert_one(document).inserted_id
        return {"waybill": document, "created": True}
    except DuplicateKeyError:
        winner = target.find_one({"source_key": expected_source_key})
        if winner:
            return {"waybill": winner, "created": False}
        raise ApiError("A Digital Waybill already exists for this source.", status_code=409) from None


def ensure_waybill_from_registered_source(
    source_type: str,
    source_id: str,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    if current_role not in ADMIN_ROLES:
        raise ApiError("Only an owner or admin can create Digital Waybills.", status_code=403)
    normalized_type = str(source_type or "").strip().lower()
    definition = WAYBILL_SOURCE_DEFINITIONS.get(normalized_type)
    if not definition:
        raise ApiError("Unsupported Digital Waybill source type.", status_code=400)
    source_oid = _oid(source_id, "source_id")
    source = get_collection(definition["collection"]).find_one({"_id": source_oid})
    if not source:
        raise ApiError("Digital Waybill source not found.", status_code=404)
    movement_id = source.get("linked_vehicle_movement_id")
    movement = get_collection("vehicle_movements").find_one({"_id": movement_id}) if movement_id else None
    if not movement:
        movement = get_collection("vehicle_movements").find_one(
            {"source_key": _source_key(normalized_type, source_oid)}
        )
    if not movement:
        raise ApiError("Create the source Vehicle Movement before its Digital Waybill.", status_code=409)
    return ensure_waybill_for_source(
        source_type=normalized_type,
        source_document=source,
        movement_document=movement,
        current_user_id=current_user_id,
    )["waybill"]


def list_waybills(*, current_user_id: str, current_role: str, page=1, page_size=25, status=None, source_type=None):
    query = {}
    if current_role == "driver":
        query["driver_id"] = _oid(current_user_id, "current_user_id")
    elif current_role not in ADMIN_ROLES:
        raise ApiError("You do not have permission to list Digital Waybills.", status_code=403)
    if status:
        if status not in WAYBILL_STATUSES:
            raise ApiError("Invalid Digital Waybill status.", status_code=400)
        query["status"] = status
    if source_type:
        if source_type not in WAYBILL_SOURCE_DEFINITIONS:
            raise ApiError("Invalid Digital Waybill source type.", status_code=400)
        query["source_type"] = source_type
    page, page_size = max(int(page or 1), 1), min(max(int(page_size or 25), 1), 100)
    total = waybills_collection().count_documents(query)
    documents = list(
        waybills_collection().find(query).sort([("updated_at", DESCENDING), ("_id", DESCENDING)])
        .skip((page - 1) * page_size).limit(page_size)
    )
    return {
        "waybills": [serialize_waybill(item) for item in documents],
        "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": max(1, ceil(total / page_size))},
    }


def get_waybill(waybill_id, *, current_user_id: str, current_role: str):
    document = _get(waybill_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role)
    return serialize_waybill(document, include_audit=True)


def replace_waybill_items(waybill_id, payload, *, current_user_id: str, current_role: str):
    if current_role not in ADMIN_ROLES:
        raise ApiError("Only an owner or admin can edit Waybill items.", status_code=403)
    document = _get(waybill_id)
    _assert_not_operational_task_owned(document)
    if document.get("status") != "draft":
        raise ApiError("Waybill items can only be edited while the Waybill is a draft.", status_code=400)
    items = normalize_waybill_items((payload or {}).get("items"))
    timestamp = now_utc()
    update = {
        "$set": {"items": items, "notes": _text((payload or {}).get("notes")), "updated_at": timestamp},
        "$inc": {"version": 1},
        "$push": {"audit_log": _audit("items_updated", current_user_id, details={"item_count": len(items)}, timestamp=timestamp)},
    }
    waybills_collection().update_one({"_id": document["_id"], "status": "draft"}, update)
    document.update(update["$set"]); document["version"] = int(document.get("version") or 1) + 1
    document.setdefault("audit_log", []).append(update["$push"]["audit_log"])
    return serialize_waybill(document, include_audit=True)


def update_waybill_recipient_from_source(
    waybill_id, recipient, *, reason=None, current_user_id: str, current_role: str, collection=None
):
    if current_role not in ADMIN_ROLES:
        raise ApiError("Only an owner or admin can update planned Waybill recipient details.", status_code=403)
    target_collection = collection if collection is not None else waybills_collection()
    document = _get(waybill_id, collection=target_collection)
    if document.get("source_type") != "stock_transfer":
        raise ApiError("Only Stock Transfer recipient details can be synchronized this way.", status_code=400)
    if document.get("recipient") == recipient:
        return serialize_waybill(document, include_audit=True)
    timestamp = now_utc()
    audit = _audit("recipient_updated_from_source", current_user_id, details={"reason": reason}, timestamp=timestamp)
    update = {
        "$set": {"recipient": recipient, "updated_at": timestamp},
        "$inc": {"version": 1},
        "$push": {"audit_log": audit},
    }
    result = target_collection.update_one(
        {"_id": document["_id"], "version": int(document.get("version") or 1)}, update
    )
    if result.modified_count != 1:
        raise ApiError("Digital Waybill changed while recipient details were synchronized.", status_code=409)
    document.update({"recipient": recipient, "updated_at": timestamp, "version": int(document.get("version") or 1) + 1})
    document.setdefault("audit_log", []).append(audit)
    return serialize_waybill(document, include_audit=True)


def _apply_item_quantities(document: dict, values, *, field: str) -> list[dict]:
    if not isinstance(values, list):
        raise ApiError(f"{field} quantities must be a list.", status_code=400)
    supplied = {}
    for raw in values:
        if not isinstance(raw, dict):
            raise ApiError("Quantity entries must be objects.", status_code=400)
        item_id = _text(raw.get("item_id"), field="item_id", required=True, limit=120)
        if item_id.casefold() in supplied:
            raise ApiError("Quantity entries must not contain duplicate item IDs.", status_code=400)
        supplied[item_id.casefold()] = _quantity(raw.get("quantity"), field, required=True)
    expected_ids = {item["item_id"].casefold() for item in document.get("items") or []}
    if set(supplied) != expected_ids:
        raise ApiError("Quantities are required for every Waybill item and cannot include unknown items.", status_code=400)
    result = []
    for item in document.get("items") or []:
        updated = dict(item)
        updated[field] = supplied[item["item_id"].casefold()]
        if field == "received_quantity":
            updated["variance"] = round(updated[field] - updated["expected_quantity"], 3)
        result.append(updated)
    return result


def validate_stock_transfer_receiver_review(document: dict, payload, *, action: str) -> dict:
    if document.get("source_type") not in {"stock_transfer", "supplier_pickup"} or document.get("status") != "delivered":
        raise ApiError("Receiver review is only available for a delivered Stock Transfer or Supplier Pickup Waybill.", status_code=400)
    if document.get("linked_delivery_exception_id") and action != "exception":
        raise ApiError("A Delivery Exception is already linked to this Waybill.", status_code=409)
    payload = payload or {}
    receiver_payload = payload.get("actual_receiver") or {}
    if not isinstance(receiver_payload, dict):
        raise ApiError("actual_receiver must be an object.", status_code=400)
    initials = _text(receiver_payload.get("initials") or payload.get("initials"), field="receiver initials", limit=30)
    signature = _text(receiver_payload.get("signature") or payload.get("signature"), field="receiver signature", limit=500000)
    if not initials and not signature:
        raise ApiError("Receiver initials or signature are required.", status_code=400)
    actual_receiver = {
        "full_name": _text(receiver_payload.get("full_name"), required=True, field="actual receiver name", limit=300),
        "primary_contact": _text(receiver_payload.get("primary_contact"), required=True, field="actual receiver primary contact", limit=300),
        "role": _text(receiver_payload.get("role"), field="actual receiver role", limit=300),
        "initials": initials,
        "signature": signature,
        "notes": _text(receiver_payload.get("notes", payload.get("notes")), field="receiver notes", limit=2000),
        "acknowledged": receiver_payload.get("acknowledged") is True,
    }
    if action == "exception" and not actual_receiver["acknowledged"]:
        raise ApiError("The actual receiver must acknowledge the Delivery Exception report.", status_code=400)

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ApiError("Every Waybill item must be reviewed.", status_code=400)
    supplied = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ApiError("Each reviewed item must be an object.", status_code=400)
        item_id = _text(raw.get("item_id"), required=True, field="item_id", limit=120)
        key = item_id.casefold()
        if key in supplied:
            raise ApiError("Reviewed items must not contain duplicates.", status_code=400)
        condition = str(raw.get("exception_type") or raw.get("condition") or "").strip().lower().replace(" ", "_")
        if condition not in DELIVERY_ITEM_CONDITIONS:
            raise ApiError("Item condition must be Correct, Missing, Damaged, Wrong Item, or Excess.", status_code=400)
        photos = raw.get("photos") or []
        if not isinstance(photos, list):
            raise ApiError("Item photos must be a list.", status_code=400)
        if len(photos) > 10:
            raise ApiError("No more than 10 photos may be attached to one exception item.", status_code=400)
        normalized_photos = [_text(photo, required=True, field="item photo", limit=500000) for photo in photos]
        supplied[key] = {
            "received_quantity": _quantity(raw.get("received_quantity"), "received_quantity", required=True),
            "condition": condition,
            "supplied_exception_quantity": _quantity(raw.get("exception_quantity"), "exception_quantity"),
            "notes": _text(raw.get("notes"), field="exception item notes", limit=2000),
            "photos": normalized_photos,
            "expected_quantity": raw.get("expected_quantity"),
        }
    expected = {item["item_id"].casefold(): item for item in (document.get("items") or [])}
    if set(supplied) != set(expected):
        raise ApiError("Every Waybill item must be reviewed exactly once.", status_code=400)
    reviewed_items = []
    has_exception = False
    for item in document.get("items") or []:
        review = supplied[item["item_id"].casefold()]
        if review["expected_quantity"] is not None:
            supplied_expected = _quantity(review["expected_quantity"], "expected_quantity", required=True)
            if supplied_expected != item["expected_quantity"]:
                raise ApiError("Expected quantity must match the Waybill.", status_code=400)
        updated = dict(item)
        updated["received_quantity"] = review["received_quantity"]
        updated["variance"] = round(review["received_quantity"] - item["expected_quantity"], 3)
        if updated["variance"] < 0:
            if review["condition"] not in {"correct", "missing"}:
                raise ApiError("Received quantity below Expected is automatically Missing and cannot use another condition.", status_code=400)
            computed_condition = "missing"
            exception_quantity = round(-updated["variance"], 3)
        elif updated["variance"] > 0:
            if review["condition"] not in {"correct", "excess"}:
                raise ApiError("Received quantity above Expected is automatically Excess and cannot use another condition.", status_code=400)
            computed_condition = "excess"
            exception_quantity = updated["variance"]
        else:
            if review["condition"] in {"missing", "excess"}:
                raise ApiError("Missing and Excess are calculated from Received quantity and cannot be selected manually.", status_code=400)
            computed_condition = review["condition"]
            exception_quantity = updated["received_quantity"] if computed_condition in {"damaged", "wrong_item"} else 0
        if review["supplied_exception_quantity"] is not None and review["supplied_exception_quantity"] != exception_quantity:
            raise ApiError("Exception quantity is calculated automatically and the supplied value conflicts with it.", status_code=400)
        if computed_condition in {"damaged", "wrong_item"} and not review["notes"]:
            raise ApiError("Notes are required for Damaged or Wrong Item conditions.", status_code=400)
        updated["item_condition"] = computed_condition
        updated["exception_quantity"] = exception_quantity
        updated["missing_quantity"] = exception_quantity if computed_condition == "missing" else 0
        updated["excess_quantity"] = exception_quantity if computed_condition == "excess" else 0
        updated["exception_status"] = "exception" if computed_condition != "correct" else "clear"
        updated["exception_notes"] = review["notes"]
        updated["exception_photos"] = review["photos"] if computed_condition != "correct" else []
        if computed_condition != "correct":
            has_exception = True
        reviewed_items.append(updated)
    if action == "verify" and has_exception:
        raise ApiError("Verify & Sign requires matching quantities and Correct condition for every item.", status_code=400)
    if action == "exception" and not has_exception:
        raise ApiError("No quantity or condition exception was reported. Use Verify & Sign instead.", status_code=400)
    return {"actual_receiver": actual_receiver, "items": reviewed_items, "has_exception": has_exception}


def _confirmation(payload: dict, *, current_user_id: str, role: str, timestamp) -> dict:
    gps = payload.get("gps")
    if gps is not None:
        if not isinstance(gps, dict):
            raise ApiError("gps must be an object.", status_code=400)
        latitude = _coordinate(gps.get("latitude"), "gps.latitude", minimum=-90, maximum=90)
        longitude = _coordinate(gps.get("longitude"), "gps.longitude", minimum=-180, maximum=180)
        gps = {"latitude": latitude, "longitude": longitude, "accuracy": _quantity(gps.get("accuracy"), "gps.accuracy")}
    device = payload.get("device") or {}
    if not isinstance(device, dict):
        raise ApiError("device must be an object.", status_code=400)
    actor_id = _oid(current_user_id, "current_user_id")
    actor = get_collection("users").find_one({"_id": actor_id}, {"full_name": 1}) or {}
    return {
        "confirmation_id": uuid4().hex,
        "confirmed_by": actor_id,
        "confirmed_by_name": _text(actor.get("full_name"), limit=300),
        "confirmed_role": role,
        "confirmed_at": timestamp,
        "gps": gps,
        "device": {str(key)[:80]: _text(value, limit=500) for key, value in list(device.items())[:20]},
        "statement": _text(payload.get("statement"), limit=1000) or "Assigned driver confirmed this Digital Waybill.",
        "immutable": True,
    }


def transition_waybill(waybill_id, target_status: str, payload, *, current_user_id: str, current_role: str, collection=None, enforce_source_owner=False, source_workflow=False):
    target_collection = collection if collection is not None else waybills_collection()
    document = _get(waybill_id, collection=target_collection)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role, mutate=True)
    if enforce_source_owner and document.get("source_type") in {"stock_transfer", "supplier_pickup"}:
        owner = "Operational Tasks" if document.get("source_type") == "supplier_pickup" else "Stock Transfer"
        raise ApiError(f"{owner} owns this Waybill workflow. Use the source operation action instead.", status_code=409)
    target = str(target_status or "").strip().lower()
    if target not in WAYBILL_STATUSES[1:]:
        raise ApiError("Invalid Digital Waybill transition.", status_code=400)
    if document.get("status") == target:
        return serialize_waybill(document, include_audit=True)
    if NEXT_STATUS.get(document.get("status")) != target:
        raise ApiError(f"Digital Waybill must move from {document.get('status')} to {NEXT_STATUS.get(document.get('status'))}.", status_code=400)
    if source_workflow:
        pass
    elif target == "driver_confirmed":
        if current_role != "driver" or document.get("driver_id") != _oid(current_user_id, "current_user_id"):
            raise ApiError("Only the assigned driver can confirm this Digital Waybill.", status_code=403)
    elif current_role not in ADMIN_ROLES and target not in {"in_transit", "delivered"} and not (document.get("source_type") == "supplier_pickup" and target == "loaded"):
        raise ApiError("Only an owner or admin can perform this Waybill transition.", status_code=403)
    if target == "approved" and not document.get("items"):
        raise ApiError("Add at least one item before approving the Digital Waybill.", status_code=400)

    payload = payload or {}
    timestamp = now_utc()
    set_fields = {"status": target, "updated_at": timestamp, f"{target}_at": timestamp}
    push_fields = {"audit_log": _audit(f"status_{target}", current_user_id, timestamp=timestamp)}
    if target == "approved":
        set_fields["approved_by"] = _oid(current_user_id, "current_user_id")
    elif target == "driver_confirmed":
        confirmation = _confirmation(payload, current_user_id=current_user_id, role=current_role, timestamp=timestamp)
        push_fields["confirmations"] = confirmation
        if document.get("source_type") != "supplier_pickup":
            push_fields["custody_events"] = {
                "handover_id": uuid4().hex, "from": "origin_sender", "to": str(document.get("driver_id")),
                "to_name": confirmation.get("confirmed_by_name"),
                "time": timestamp, "location": payload.get("location") or document.get("origin"),
                "confirmation": confirmation["confirmation_id"], "variance": [],
                "notes": _text(payload.get("notes")), "recorded_by": _oid(current_user_id, "current_user_id"), "immutable": True,
            }
    elif target == "loaded":
        set_fields["items"] = _apply_item_quantities(document, payload.get("quantities"), field="loaded_quantity")
    elif target == "delivered" and document.get("source_type") in {"stock_transfer", "supplier_pickup"} and payload.get("physical_delivery_only"):
        set_fields["delivered_by"] = _oid(current_user_id, "current_user_id")
        set_fields["receipt_pending"] = True
    elif target == "delivered":
        items = _apply_item_quantities(document, payload.get("quantities"), field="received_quantity")
        set_fields["items"] = items
        set_fields["has_variance"] = any(item.get("variance") != 0 for item in items)
        receipt_confirmation = {
            "confirmation_id": uuid4().hex,
            "confirmation_type": "destination_receipt",
            "confirmed_by": _oid(current_user_id, "current_user_id"),
            "confirmed_role": current_role,
            "confirmed_at": timestamp,
            "receiver": _text(payload.get("receiver"), required=True, field="receiver", limit=300),
            "statement": _text(payload.get("statement"), limit=1000) or "Destination receipt and quantities confirmed.",
            "immutable": True,
        }
        push_fields["confirmations"] = receipt_confirmation
        push_fields["custody_events"] = {
            "handover_id": uuid4().hex, "from": str(document.get("driver_id")), "to": _text(payload.get("receiver"), required=True, field="receiver", limit=300),
            "time": timestamp, "location": payload.get("location") or document.get("destination"),
            "confirmation": receipt_confirmation["confirmation_id"], "variance": [item for item in items if item.get("variance") != 0],
            "notes": _text(payload.get("notes")), "recorded_by": _oid(current_user_id, "current_user_id"), "immutable": True,
        }
    elif target == "completed" and document.get("has_variance") and not document.get("variance_review"):
        raise ApiError("Variance review is required before completing this Digital Waybill.", status_code=409)

    update = {"$set": set_fields, "$inc": {"version": 1}, "$push": push_fields}
    waybill_update = target_collection.update_one({"_id": document["_id"], "status": document["status"]}, update)
    if waybill_update.modified_count != 1:
        raise ApiError("Digital Waybill changed while this transition was being recorded.", status_code=409)
    document.update(set_fields); document["version"] = int(document.get("version") or 1) + 1
    for key, value in push_fields.items():
        document.setdefault(key, []).append(value)
    return serialize_waybill(document, include_audit=True)


def finalize_stock_transfer_receiver_verification(
    waybill_id, review, *, current_user_id: str, current_role: str, collection=None
):
    if current_role != "driver":
        raise ApiError("Receiver verification must be recorded through the assigned driver's Waybill session.", status_code=403)
    target_collection = collection if collection is not None else waybills_collection()
    document = _get(waybill_id, collection=target_collection)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role, mutate=True)
    if document.get("status") == "completed" and document.get("actual_receiver"):
        return serialize_waybill(document, include_audit=True)
    if document.get("status") != "delivered":
        raise ApiError("The Waybill must be Delivered before receiver verification.", status_code=400)
    if document.get("linked_delivery_exception_id"):
        raise ApiError("A Delivery Exception is already linked to this Waybill.", status_code=409)
    timestamp = now_utc()
    receiver = review["actual_receiver"]
    confirmation_id = uuid4().hex
    confirmation = {
        "confirmation_id": confirmation_id,
        "confirmation_type": "receiver_verification",
        "confirmed_by": _oid(current_user_id, "current_user_id"),
        "confirmed_role": current_role,
        "confirmed_at": timestamp,
        "actual_receiver_name": receiver["full_name"],
        "actual_receiver_contact": receiver["primary_contact"],
        "statement": "Actual receiver verified all delivered items as correct.",
        "immutable": True,
    }
    signature = {
        "party": "receiver",
        "signature": receiver.get("signature"),
        "initials": receiver.get("initials"),
        "signed_by_name": receiver["full_name"],
        "primary_contact": receiver["primary_contact"],
        "recorded_by": _oid(current_user_id, "current_user_id"),
        "signed_at": timestamp,
        "immutable": True,
    }
    custody = {
        "handover_id": uuid4().hex,
        "from": str(document.get("driver_id")),
        "to": receiver["full_name"],
        "to_contact": receiver["primary_contact"],
        "time": timestamp,
        "location": document.get("destination"),
        "confirmation": confirmation_id,
        "variance": [],
        "notes": receiver.get("notes"),
        "recorded_by": _oid(current_user_id, "current_user_id"),
        "immutable": True,
    }
    audits = [
        _audit("receiver_verified", current_user_id, details={"receiver": receiver["full_name"]}, timestamp=timestamp),
        _audit("status_verified", current_user_id, timestamp=timestamp),
        _audit("status_completed", current_user_id, timestamp=timestamp),
    ]
    update = {
        "$set": {
            "status": "completed",
            "items": review["items"],
            "actual_receiver": receiver,
            "has_variance": False,
            "receipt_pending": False,
            "verified_by": _oid(current_user_id, "current_user_id"),
            "verified_at": timestamp,
            "completed_at": timestamp,
            "locked_at": timestamp,
            "signatures.receiver": signature,
            "updated_at": timestamp,
        },
        "$inc": {"version": 1},
        "$push": {
            "confirmations": confirmation,
            "custody_events": custody,
            "audit_log": {"$each": audits},
        },
    }
    result = target_collection.update_one(
        {"_id": document["_id"], "status": "delivered", "linked_delivery_exception_id": {"$exists": False}}, update
    )
    if result.modified_count != 1:
        winner = _get(waybill_id, collection=target_collection)
        if winner.get("status") == "completed" and winner.get("actual_receiver"):
            return serialize_waybill(winner, include_audit=True)
        raise ApiError("Digital Waybill changed while receiver verification was recorded.", status_code=409)
    document.update(update["$set"]); document["version"] = int(document.get("version") or 1) + 1
    document.setdefault("signatures", {})["receiver"] = signature
    document.setdefault("confirmations", []).append(confirmation)
    document.setdefault("custody_events", []).append(custody)
    document.setdefault("audit_log", []).extend(audits)
    return serialize_waybill(document, include_audit=True)


def record_stock_transfer_delivery_exception(
    waybill_id, exception_id, review, *, current_user_id: str, current_role: str, collection=None,
    exception_summary=None,
):
    if current_role != "driver":
        raise ApiError("Delivery exceptions must be recorded through the assigned driver's Waybill session.", status_code=403)
    target_collection = collection if collection is not None else waybills_collection()
    document = _get(waybill_id, collection=target_collection)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role, mutate=True)
    if document.get("linked_delivery_exception_id") == exception_id:
        return serialize_waybill(document, include_audit=True)
    if document.get("status") != "delivered":
        raise ApiError("The Waybill must be Delivered before reporting an exception.", status_code=400)
    timestamp = now_utc()
    receiver = review["actual_receiver"]
    confirmation = {
        "confirmation_id": uuid4().hex,
        "confirmation_type": "receiver_exception_report",
        "confirmed_by": _oid(current_user_id, "current_user_id"),
        "confirmed_role": current_role,
        "confirmed_at": timestamp,
        "actual_receiver_name": receiver["full_name"],
        "actual_receiver_contact": receiver["primary_contact"],
        "statement": "Actual receiver reported a delivery exception.",
        "immutable": True,
    }
    signature = {
        "party": "receiver",
        "signature": receiver.get("signature"),
        "initials": receiver.get("initials"),
        "signed_by_name": receiver["full_name"],
        "primary_contact": receiver["primary_contact"],
        "recorded_by": _oid(current_user_id, "current_user_id"),
        "signed_at": timestamp,
        "immutable": True,
    }
    audit = _audit("delivery_exception_reported", current_user_id, details={"exception_id": str(exception_id)}, timestamp=timestamp)
    update = {
        "$set": {
            "items": review["items"],
            "actual_receiver": receiver,
            "has_variance": any(item.get("variance") != 0 for item in review["items"]),
            "receipt_pending": False,
            "linked_delivery_exception_id": exception_id,
            "delivery_exception_status": "open",
            "delivery_exception_summary": exception_summary or {},
            "signatures.receiver": signature,
            "updated_at": timestamp,
        },
        "$inc": {"version": 1},
        "$push": {"confirmations": confirmation, "audit_log": audit},
    }
    result = target_collection.update_one(
        {"_id": document["_id"], "status": "delivered", "linked_delivery_exception_id": {"$exists": False}}, update
    )
    if result.modified_count != 1:
        winner = _get(waybill_id, collection=target_collection)
        if winner.get("linked_delivery_exception_id") == exception_id:
            return serialize_waybill(winner, include_audit=True)
        raise ApiError("A Delivery Exception is already linked to this Waybill.", status_code=409)
    document.update(update["$set"]); document["version"] = int(document.get("version") or 1) + 1
    document.setdefault("signatures", {})["receiver"] = signature
    document.setdefault("confirmations", []).append(confirmation)
    document.setdefault("audit_log", []).append(audit)
    return serialize_waybill(document, include_audit=True)


def record_waybill_destination_receipt(
    waybill_id, payload, *, current_user_id: str, current_role: str, collection=None
):
    if current_role not in ADMIN_ROLES:
        raise ApiError("Only an owner or admin can record the destination receipt.", status_code=403)
    target_collection = collection if collection is not None else waybills_collection()
    document = _get(waybill_id, collection=target_collection)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role, mutate=True)
    if document.get("status") != "delivered":
        raise ApiError("The Waybill must be delivered before receipt quantities are recorded.", status_code=400)
    existing = next(
        (item for item in (document.get("confirmations") or []) if item.get("confirmation_type") == "destination_receipt"),
        None,
    )
    if existing:
        return serialize_waybill(document, include_audit=True)
    payload = payload or {}
    timestamp = now_utc()
    items = _apply_item_quantities(document, payload.get("quantities"), field="received_quantity")
    confirmation = {
        "confirmation_id": uuid4().hex,
        "confirmation_type": "destination_receipt",
        "confirmed_by": _oid(current_user_id, "current_user_id"),
        "confirmed_role": current_role,
        "confirmed_at": timestamp,
        "receiver": _text(payload.get("receiver"), required=True, field="receiver", limit=300),
        "statement": _text(payload.get("statement"), limit=1000) or "Destination receipt and quantities confirmed.",
        "immutable": True,
    }
    custody = {
        "handover_id": uuid4().hex,
        "from": str(document.get("driver_id")),
        "to": confirmation["receiver"],
        "time": timestamp,
        "location": payload.get("location") or document.get("destination"),
        "confirmation": confirmation["confirmation_id"],
        "variance": [item for item in items if item.get("variance") != 0],
        "notes": _text(payload.get("notes")),
        "recorded_by": _oid(current_user_id, "current_user_id"),
        "immutable": True,
    }
    audit = _audit("destination_receipt_recorded", current_user_id, timestamp=timestamp)
    update = {
        "$set": {
            "items": items,
            "has_variance": any(item.get("variance") != 0 for item in items),
            "receipt_pending": False,
            "updated_at": timestamp,
        },
        "$inc": {"version": 1},
        "$push": {"confirmations": confirmation, "custody_events": custody, "audit_log": audit},
    }
    result = target_collection.update_one(
        {"_id": document["_id"], "status": "delivered", "confirmations.confirmation_type": {"$ne": "destination_receipt"}},
        update,
    )
    if result.modified_count != 1:
        winner = _get(waybill_id, collection=target_collection)
        if any(item.get("confirmation_type") == "destination_receipt" for item in (winner.get("confirmations") or [])):
            return serialize_waybill(winner, include_audit=True)
        raise ApiError("Digital Waybill changed while receipt was being recorded.", status_code=409)
    document.update(update["$set"]); document["version"] = int(document.get("version") or 1) + 1
    document.setdefault("confirmations", []).append(confirmation)
    document.setdefault("custody_events", []).append(custody)
    document.setdefault("audit_log", []).append(audit)
    return serialize_waybill(document, include_audit=True)


def review_waybill_variance(waybill_id, payload, *, current_user_id: str, current_role: str, collection=None, enforce_source_owner=False):
    if current_role not in ADMIN_ROLES:
        raise ApiError("Only an owner or admin can review Waybill variance.", status_code=403)
    target_collection = collection if collection is not None else waybills_collection()
    document = _get(waybill_id, collection=target_collection)
    _assert_not_operational_task_owned(document)
    if enforce_source_owner and document.get("source_type") == "stock_transfer":
        raise ApiError("Stock Transfer owns this variance workflow. Review it from Stock Transfers.", status_code=409)
    if document.get("status") not in {"delivered", "verified"}:
        raise ApiError("Variance can only be reviewed after delivery.", status_code=400)
    if not document.get("has_variance"):
        raise ApiError("This Digital Waybill has no variance to review.", status_code=400)
    resolution = _text((payload or {}).get("resolution"), required=True, field="variance resolution")
    timestamp = now_utc()
    review = {"resolution": resolution, "notes": _text((payload or {}).get("notes")), "reviewed_by": _oid(current_user_id, "current_user_id"), "reviewed_at": timestamp}
    audit = _audit("variance_reviewed", current_user_id, details={"resolution": resolution}, timestamp=timestamp)
    target_collection.update_one({"_id": document["_id"]}, {"$set": {"variance_review": review, "updated_at": timestamp}, "$inc": {"version": 1}, "$push": {"audit_log": audit}})
    document.update({"variance_review": review, "updated_at": timestamp}); document.setdefault("audit_log", []).append(audit)
    return serialize_waybill(document, include_audit=True)


def record_waybill_custody(waybill_id, payload, *, current_user_id: str, current_role: str):
    document = _get(waybill_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role, mutate=True)
    _assert_not_operational_task_owned(document)
    if document.get("locked_at") or document.get("status") == "completed":
        raise ApiError("Completed Waybills are locked from further edits.", status_code=409)
    timestamp = now_utc()
    event = {
        "handover_id": uuid4().hex,
        "from": _text((payload or {}).get("from"), required=True, field="from", limit=300),
        "to": _text((payload or {}).get("to"), required=True, field="to", limit=300),
        "time": timestamp,
        "location": _text((payload or {}).get("location"), required=True, field="location", limit=500),
        "confirmation": _text((payload or {}).get("confirmation"), required=True, field="confirmation", limit=500),
        "variance": (payload or {}).get("variance") or [],
        "notes": _text((payload or {}).get("notes")),
        "recorded_by": _oid(current_user_id, "current_user_id"),
        "immutable": True,
    }
    audit = _audit("custody_handover_recorded", current_user_id, details={"handover_id": event["handover_id"]}, timestamp=timestamp)
    waybills_collection().update_one({"_id": document["_id"]}, {"$set": {"updated_at": timestamp}, "$inc": {"version": 1}, "$push": {"custody_events": event, "audit_log": audit}})
    document.setdefault("custody_events", []).append(event); document.setdefault("audit_log", []).append(audit)
    return serialize_waybill(document, include_audit=True)


def save_waybill_signature(waybill_id, party: str, payload, *, current_user_id: str, current_role: str):
    document = _get(waybill_id)
    _assert_access(document, current_user_id=current_user_id, current_role=current_role, mutate=True)
    _assert_not_operational_task_owned(document)
    if document.get("locked_at") or document.get("status") == "completed":
        raise ApiError("Completed Waybills are locked from further edits.", status_code=409)
    normalized_party = str(party or "").strip().lower()
    if normalized_party not in {"sender", "receiver"}:
        raise ApiError("Signature party must be sender or receiver.", status_code=400)
    if (document.get("signatures") or {}).get(normalized_party):
        raise ApiError(f"The {normalized_party} signature is immutable once recorded.", status_code=409)
    signature_data = _text((payload or {}).get("signature"), required=True, field="signature", limit=500000)
    timestamp = now_utc()
    signature = {"party": normalized_party, "signature": signature_data, "signed_by_name": _text((payload or {}).get("signed_by_name"), required=True, field="signed_by_name", limit=300), "recorded_by": _oid(current_user_id, "current_user_id"), "signed_at": timestamp, "immutable": True}
    audit = _audit(f"{normalized_party}_signature_recorded", current_user_id, timestamp=timestamp)
    waybills_collection().update_one({"_id": document["_id"], f"signatures.{normalized_party}": {"$exists": False}}, {"$set": {f"signatures.{normalized_party}": signature, "updated_at": timestamp}, "$inc": {"version": 1}, "$push": {"audit_log": audit}})
    document.setdefault("signatures", {})[normalized_party] = signature; document.setdefault("audit_log", []).append(audit)
    return serialize_waybill(document, include_audit=True)


def search_waybill_products(query: str, *, current_role: str):
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to search Waybill products.", status_code=403)
    needle = str(query or "").strip().casefold()
    if len(needle) < 2:
        return {"products": []}
    products = {}
    for collection_name, item_field in (("waybills", "items"), ("stock_transfers", "transfer_items")):
        for document in get_collection(collection_name).find({}, {item_field: 1}).limit(500):
            for item in document.get(item_field) or []:
                item_id = str(item.get("item_id") or item.get("sku") or "").strip()
                name = str(item.get("name") or item_id).strip()
                if item_id and needle in f"{item_id} {name}".casefold():
                    products[item_id.casefold()] = {"item_id": item_id, "sku": item.get("sku") or item_id, "name": name, "unit": item.get("unit") or "unit"}
                if len(products) >= 30:
                    break
    return {"products": list(products.values())[:30]}
