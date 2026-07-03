from datetime import datetime, timedelta, timezone
from math import ceil
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter

from bson import ObjectId
from flask import current_app
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.assignment import serialize_assignment
from models.collection import serialize_collection
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.payment_cycle_service import (
    APPROVED_PAYMENT_STATUSES,
    PENDING_PAYMENT_STATUSES,
    collection_cycle_window,
    get_current_cycle_for_assignment,
    get_weekly_cycle_window,
)
from services.wallet_service import create_wallet_entry
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached


ALLOWED_COLLECTION_STATUSES = {"pending", "submitted", "received", "approved", "rejected", "reversed"}
ALLOWED_PAYMENT_METHODS = {"cash", "momo", "bank", "other"}
COLLECTION_LIST_PROJECTION = {
    "driver_id": 1,
    "vehicle_id": 1,
    "assignment_id": 1,
    "amount": 1,
    "submitted_amount": 1,
    "admin_received_amount": 1,
    "collection_date": 1,
    "payment_method": 1,
    "reference_number": 1,
    "notes": 1,
    "driver_note": 1,
    "admin_approval_note": 1,
    "status": 1,
    "cycle_key": 1,
    "week_start": 1,
    "week_end": 1,
    "payment_deadline": 1,
    "rejection_reason": 1,
    "is_late": 1,
    "received_by_admin_id": 1,
    "approved_by_admin_id": 1,
    "created_at": 1,
    "updated_at": 1,
}
USER_SUMMARY_PROJECTION = {"full_name": 1, "email": 1, "phone": 1, "role": 1, "status": 1}
VEHICLE_SUMMARY_PROJECTION = {"registration_number": 1, "make": 1, "model": 1, "status": 1}
ASSIGNMENT_SUMMARY_PROJECTION = {
    "driver_id": 1,
    "vehicle_id": 1,
    "status": 1,
    "weekly_target": 1,
    "daily_target": 1,
    "start_date": 1,
    "end_date": 1,
    "created_at": 1,
    "updated_at": 1,
}


def now_utc():
    return datetime.now(timezone.utc)


def collections_collection():
    return get_collection("collections")


def users_collection():
    return get_collection("users")


def assignments_collection():
    return get_collection("assignments")


def vehicles_collection():
    return get_collection("vehicles")


def ensure_collection_indexes():
    ensure_indexes_for_collection(
        collections_collection(),
        [
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("assignment_id", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("submitted_at", DESCENDING)]},
            {"keys": [("collection_date", DESCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("collection_date", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING), ("collection_date", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING), ("collection_date", DESCENDING)]},
            {"keys": [("assignment_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("collection_date", DESCENDING), ("created_at", DESCENDING)]},
            {
                "keys": [
                    ("driver_id", ASCENDING),
                    ("assignment_id", ASCENDING),
                    ("cycle_key", ASCENDING),
                    ("status", ASCENDING),
                    ("collection_date", DESCENDING),
                ]
            },
            {"keys": [("cycle_key", ASCENDING)]},
            {"keys": [("week_start", ASCENDING)]},
            {"keys": [("payment_deadline", ASCENDING)]},
            {"keys": [("received_by_admin_id", ASCENDING)]},
            {"keys": [("approved_by_admin_id", ASCENDING)]},
        ],
        collection_name="collections",
    )


def _to_object_id(value, field_name: str, required: bool = True):
    if value is None:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _validate_positive_amount(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value <= 0:
        raise ApiError(f"{field_name} must be a positive number.", status_code=400)
    return float(value)


def _round_currency_amount(value: float) -> float:
    return round(float(value), 2)


def _get_admin_document(admin_id):
    admin_object_id = _to_object_id(admin_id, "admin_id")
    admin = users_collection().find_one({"_id": admin_object_id, "role": {"$in": ["owner", "admin"]}})
    if not admin:
        raise ApiError("Admin user not found.", status_code=404)
    return admin


def _get_driver_document(driver_id):
    driver_object_id = _to_object_id(driver_id, "driver_id")
    driver = users_collection().find_one({"_id": driver_object_id, "role": "driver"})
    if not driver:
        raise ApiError("Driver not found.", status_code=404)
    return driver


def _get_vehicle_document(vehicle_id):
    vehicle_object_id = _to_object_id(vehicle_id, "vehicle_id")
    vehicle = vehicles_collection().find_one({"_id": vehicle_object_id})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _get_assignment_document(assignment_id):
    assignment_object_id = _to_object_id(assignment_id, "assignment_id")
    assignment = assignments_collection().find_one({"_id": assignment_object_id})
    if not assignment:
        raise ApiError("Assignment not found.", status_code=404)
    return assignment


def _build_document_lookup(collection, ids: set[ObjectId], projection: dict) -> dict[ObjectId, dict]:
    if not ids:
        return {}
    return {
        document["_id"]: document
        for document in collection.find({"_id": {"$in": list(ids)}}, projection)
    }


def _load_collection_related_maps(collection_documents: list[dict]) -> dict[str, dict[ObjectId, dict]]:
    user_ids = {
        value
        for document in collection_documents
        for value in (
            document.get("driver_id"),
            document.get("received_by_admin_id"),
            document.get("approved_by_admin_id"),
        )
        if isinstance(value, ObjectId)
    }
    vehicle_ids = {
        document.get("vehicle_id")
        for document in collection_documents
        if isinstance(document.get("vehicle_id"), ObjectId)
    }
    assignment_ids = {
        document.get("assignment_id")
        for document in collection_documents
        if isinstance(document.get("assignment_id"), ObjectId)
    }
    cache_key = build_cache_key(
        "collections:related_maps",
        user_ids=",".join(sorted(str(item) for item in user_ids)),
        vehicle_ids=",".join(sorted(str(item) for item in vehicle_ids)),
        assignment_ids=",".join(sorted(str(item) for item in assignment_ids)),
    )
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    with ThreadPoolExecutor(max_workers=3) as executor:
        user_future = executor.submit(_build_document_lookup, users_collection(), user_ids, USER_SUMMARY_PROJECTION)
        vehicle_future = executor.submit(
            _build_document_lookup,
            vehicles_collection(),
            vehicle_ids,
            VEHICLE_SUMMARY_PROJECTION,
        )
        assignment_future = executor.submit(
            _build_document_lookup,
            assignments_collection(),
            assignment_ids,
            ASSIGNMENT_SUMMARY_PROJECTION,
        )
        related_maps = {
            "users": user_future.result(),
            "vehicles": vehicle_future.result(),
            "assignments": assignment_future.result(),
        }
    return set_ttl_cached(cache_key, related_maps, ttl_seconds=15)


def _enrich_collection(
    collection_document: dict,
    *,
    user_lookup: dict[ObjectId, dict] | None = None,
    vehicle_lookup: dict[ObjectId, dict] | None = None,
    assignment_lookup: dict[ObjectId, dict] | None = None,
) -> dict:
    collection = serialize_collection(collection_document)
    driver = (user_lookup or {}).get(collection_document.get("driver_id")) or users_collection().find_one(
        {"_id": collection_document.get("driver_id")},
        USER_SUMMARY_PROJECTION,
    )
    vehicle = (vehicle_lookup or {}).get(collection_document.get("vehicle_id")) or vehicles_collection().find_one(
        {"_id": collection_document.get("vehicle_id")},
        VEHICLE_SUMMARY_PROJECTION,
    )
    assignment = (assignment_lookup or {}).get(
        collection_document.get("assignment_id")
    ) or assignments_collection().find_one(
        {"_id": collection_document.get("assignment_id")},
        ASSIGNMENT_SUMMARY_PROJECTION,
    )
    received_by = (user_lookup or {}).get(
        collection_document.get("received_by_admin_id")
    ) or users_collection().find_one(
        {"_id": collection_document.get("received_by_admin_id")},
        USER_SUMMARY_PROJECTION,
    )
    approved_by = (user_lookup or {}).get(
        collection_document.get("approved_by_admin_id")
    ) or users_collection().find_one(
        {"_id": collection_document.get("approved_by_admin_id")},
        USER_SUMMARY_PROJECTION,
    )

    collection["driver"] = serialize_user(driver) if driver else None
    collection["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
    collection["assignment"] = serialize_assignment(assignment) if assignment else None
    collection["received_by_admin"] = serialize_user(received_by) if received_by else None
    collection["approved_by_admin"] = serialize_user(approved_by) if approved_by else None
    cycle_window = collection_cycle_window(collection_document)
    collection["cycle_key"] = collection_document.get("cycle_key") or cycle_window["cycle_key"]
    collection["week_start"] = collection_document.get("week_start") or cycle_window["week_start"]
    collection["week_end"] = collection_document.get("week_end") or cycle_window["week_end"]
    collection["payment_deadline"] = collection_document.get("payment_deadline") or cycle_window["payment_deadline"]
    collection["rejection_reason"] = collection_document.get("rejection_reason")
    collection["is_late"] = bool(collection_document.get("is_late"))
    collection["submitted_amount"] = _round_currency_amount(
        collection_document.get("submitted_amount")
        if collection_document.get("submitted_amount") is not None
        else collection_document.get("amount") or 0
    )
    collection["admin_received_amount"] = (
        _round_currency_amount(collection_document.get("admin_received_amount"))
        if collection_document.get("admin_received_amount") is not None
        else None
    )
    collection["driver_note"] = collection_document.get("driver_note") or collection_document.get("notes")
    collection["admin_approval_note"] = collection_document.get("admin_approval_note")
    return collection


def _batch_enrich_collections(collection_documents: list[dict]) -> list[dict]:
    if not collection_documents:
        return []
    related_maps = _load_collection_related_maps(collection_documents)
    return [
        _enrich_collection(
            collection_document,
            user_lookup=related_maps["users"],
            vehicle_lookup=related_maps["vehicles"],
            assignment_lookup=related_maps["assignments"],
        )
        for collection_document in collection_documents
    ]


def _log_slow_collection_section(label: str, started_at: float, *, threshold_ms: float = 1000) -> float:
    duration_ms = (perf_counter() - started_at) * 1000
    if duration_ms >= threshold_ms:
        current_app.logger.warning("[Flux Collections] slow_section=%s duration_ms=%.2f", label, duration_ms)
    return duration_ms


def _cached_collection_options_payload() -> dict:
    cache_key = "collections:options"
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    assignments = list(
        assignments_collection()
        .find({"status": {"$in": ["active", "suspended"]}}, ASSIGNMENT_SUMMARY_PROJECTION)
        .sort("created_at", DESCENDING)
    )
    admins = list(
        users_collection()
        .find({"role": {"$in": ["owner", "admin"]}}, USER_SUMMARY_PROJECTION)
        .sort("full_name", ASCENDING)
    )
    driver_lookup = _build_document_lookup(
        users_collection(),
        {assignment.get("driver_id") for assignment in assignments if isinstance(assignment.get("driver_id"), ObjectId)},
        USER_SUMMARY_PROJECTION,
    )
    vehicle_lookup = _build_document_lookup(
        vehicles_collection(),
        {assignment.get("vehicle_id") for assignment in assignments if isinstance(assignment.get("vehicle_id"), ObjectId)},
        VEHICLE_SUMMARY_PROJECTION,
    )

    assignment_options = []
    for assignment in assignments:
        option = serialize_assignment(assignment)
        driver = driver_lookup.get(assignment.get("driver_id"))
        vehicle = vehicle_lookup.get(assignment.get("vehicle_id"))
        option["driver"] = serialize_user(driver) if driver else None
        option["vehicle"] = serialize_vehicle(vehicle) if vehicle else None
        assignment_options.append(option)

    return set_ttl_cached(
        cache_key,
        {
            "assignments": assignment_options,
            "admins": [serialize_user(admin) for admin in admins],
        },
        ttl_seconds=15,
    )


def _create_wallet_credit_for_collection(collection_document: dict, *, current_user_id: str):
    create_wallet_entry(
        driver_id=collection_document["driver_id"],
        vehicle_id=collection_document.get("vehicle_id"),
        assignment_id=collection_document.get("assignment_id"),
        entry_type="collection",
        description=f"Approved payment via {collection_document.get('payment_method')}",
        debit=0,
        credit=float(collection_document.get("amount") or 0),
        reference_id=collection_document["_id"],
        created_by=current_user_id,
    )


def _build_collection_document(
    *,
    driver: dict,
    vehicle: dict,
    assignment: dict,
    amount: float,
    collection_date: str,
    payment_method: str,
    reference_number: str | None,
    notes: str | None,
    status: str,
    current_user_id: str,
    submitted_by_driver_id: ObjectId | None = None,
    received_by_admin_id: ObjectId | None = None,
    approved_by_admin_id: ObjectId | None = None,
    admin_received_amount: float | None = None,
    admin_approval_note: str | None = None,
) -> dict:
    timestamp = now_utc()
    cycle_window = get_weekly_cycle_window(collection_date)
    collection_dt = _parse_collection_date(collection_date) or timestamp
    is_late = collection_dt.astimezone(timezone.utc) > cycle_window["payment_deadline_dt"]

    return {
        "driver_id": driver["_id"],
        "vehicle_id": vehicle["_id"],
        "assignment_id": assignment["_id"],
        "amount": amount,
        "submitted_amount": amount,
        "admin_received_amount": admin_received_amount,
        "collection_date": collection_date,
        "payment_method": payment_method,
        "reference_number": reference_number,
        "notes": notes,
        "driver_note": notes,
        "admin_approval_note": admin_approval_note,
        "status": status,
        "cycle_key": cycle_window["cycle_key"],
        "week_start": cycle_window["week_start"],
        "week_end": cycle_window["week_end"],
        "payment_deadline": cycle_window["payment_deadline"],
        "is_late": is_late,
        "submitted_by_driver_id": submitted_by_driver_id,
        "received_by_admin_id": received_by_admin_id,
        "approved_by_admin_id": approved_by_admin_id,
        "rejected_by_admin_id": None,
        "rejection_reason": None,
        "submitted_at": timestamp if submitted_by_driver_id else None,
        "approved_at": timestamp if approved_by_admin_id else None,
        "rejected_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def list_collections(
    *,
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    driver_id: str | None = None,
    payment_method: str | None = None,
    collection_date: str | None = None,
    search: str | None = None,
) -> dict:
    request_started_at = perf_counter()
    cache_key = build_cache_key(
        "collections:list",
        page=page,
        page_size=page_size,
        status=status or "all",
        driver_id=driver_id or "all",
        payment_method=payment_method or "all",
        collection_date=collection_date or "",
        search=(search or "").strip().lower(),
    )
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    query = {}
    if status and status != "all":
        if status == "pending":
            query["status"] = {"$in": ["pending", "submitted", "received"]}
        else:
            query["status"] = status
    if driver_id and driver_id != "all":
        query["driver_id"] = _to_object_id(driver_id, "driver_id")
    if payment_method and payment_method != "all":
        query["payment_method"] = payment_method
    if collection_date:
        query["collection_date"] = collection_date
    if search:
        escaped = str(search).strip()
        if escaped:
            query["$or"] = [
                {"reference_number": {"$regex": escaped, "$options": "i"}},
                {"notes": {"$regex": escaped, "$options": "i"}},
                {"driver_note": {"$regex": escaped, "$options": "i"}},
            ]

    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 25), 1), 100)
    skip = (page - 1) * page_size

    aggregate_started_at = perf_counter()
    aggregate_result = list(
        collections_collection().aggregate(
            [
                {"$match": query},
                {
                    "$facet": {
                        "summary": [
                            {
                                "$group": {
                                    "_id": None,
                                    "approved_total": {
                                        "$sum": {
                                            "$cond": [{"$eq": ["$status", "approved"]}, {"$ifNull": ["$amount", 0]}, 0]
                                        }
                                    },
                                    "approved_count": {"$sum": {"$cond": [{"$eq": ["$status", "approved"]}, 1, 0]}},
                                    "pending_count": {
                                        "$sum": {
                                            "$cond": [{"$in": ["$status", ["pending", "submitted", "received"]]}, 1, 0]
                                        }
                                    },
                                    "rejected_count": {"$sum": {"$cond": [{"$eq": ["$status", "rejected"]}, 1, 0]}},
                                    "reversed_count": {"$sum": {"$cond": [{"$eq": ["$status", "reversed"]}, 1, 0]}},
                                }
                            }
                        ],
                        "total_count": [{"$count": "count"}],
                        "documents": [
                            {"$sort": {"collection_date": -1, "created_at": -1}},
                            {"$skip": skip},
                            {"$limit": page_size},
                            {"$project": COLLECTION_LIST_PROJECTION},
                        ],
                    }
                },
            ]
        )
    )
    log_db_duration("collections.page_aggregate", aggregate_started_at)
    aggregate_payload = aggregate_result[0] if aggregate_result else {}
    total_records = int(((aggregate_payload.get("total_count") or [{}])[0]).get("count") or 0)
    summary = ((aggregate_payload.get("summary") or [{}])[0]) if aggregate_payload.get("summary") else {}
    documents = aggregate_payload.get("documents") or []
    enrich_started_at = perf_counter()
    enriched_collections = _batch_enrich_collections(documents)
    _log_slow_collection_section("list_collections.enrich_page", enrich_started_at, threshold_ms=250)

    response = {
        "collections": enriched_collections,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": ceil(total_records / page_size) if total_records else 1,
        },
        "summary": {
            "total_records": total_records,
            "approved_total": _round_currency_amount(summary.get("approved_total") or 0),
            "approved_count": int(summary.get("approved_count") or 0),
            "pending_count": int(summary.get("pending_count") or 0),
            "rejected_count": int(summary.get("rejected_count") or 0),
            "reversed_count": int(summary.get("reversed_count") or 0),
        },
    }
    _log_slow_collection_section("list_collections.total", request_started_at)
    return set_ttl_cached(cache_key, response, ttl_seconds=10)


def get_collection_by_id(collection_id: str) -> dict:
    collection_object_id = _to_object_id(collection_id, "collection_id")
    collection_document = collections_collection().find_one({"_id": collection_object_id}, COLLECTION_LIST_PROJECTION)
    if not collection_document:
        raise ApiError("Collection not found.", status_code=404)
    return _enrich_collection(collection_document)


def create_collection(payload: dict, current_user_id: str) -> dict:
    if not ObjectId.is_valid(current_user_id):
        raise ApiError("Invalid user identity.", status_code=400)

    driver = _get_driver_document(payload.get("driver_id"))
    vehicle = _get_vehicle_document(payload.get("vehicle_id"))
    assignment = _get_assignment_document(payload.get("assignment_id"))

    if assignment.get("driver_id") != driver.get("_id"):
        raise ApiError("Assignment does not belong to the selected driver.", status_code=400)
    if assignment.get("vehicle_id") != vehicle.get("_id"):
        raise ApiError("Assignment does not belong to the selected vehicle.", status_code=400)
    if assignment.get("status") not in {"active", "suspended"}:
        raise ApiError("Collections can only be recorded for active or suspended assignments.", status_code=400)

    amount = _validate_positive_amount(payload.get("amount"), "amount")
    collection_date = (payload.get("collection_date") or "").strip()
    if not collection_date:
        raise ApiError("collection_date is required.", status_code=400)

    payment_method = (payload.get("payment_method") or "").strip().lower()
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        raise ApiError("payment_method must be one of: cash, momo, bank, other.", status_code=400)

    status = (payload.get("status") or "pending").strip().lower()
    if status not in {"pending", "submitted", "approved"}:
        raise ApiError("New collections can only start as pending or approved.", status_code=400)

    received_by_admin = None
    if payload.get("received_by_admin_id"):
        received_by_admin = _get_admin_document(payload.get("received_by_admin_id"))
    approved_by_admin = None
    admin_received_amount = None
    admin_approval_note = (payload.get("admin_approval_note") or "").strip() or None
    if status == "approved":
        approved_by_admin = _get_admin_document(payload.get("approved_by_admin_id") or current_user_id)
        received_by_admin = received_by_admin or approved_by_admin
        admin_received_amount = _round_currency_amount(amount)
        if payload.get("admin_received_amount") is not None:
            admin_received_amount = _round_currency_amount(
                _validate_positive_amount(payload.get("admin_received_amount"), "admin_received_amount")
            )
            if admin_received_amount != _round_currency_amount(amount):
                raise ApiError("Received amount must match submitted amount.", status_code=400)

    collection_document = _build_collection_document(
        driver=driver,
        vehicle=vehicle,
        assignment=assignment,
        amount=amount,
        collection_date=collection_date,
        payment_method=payment_method,
        reference_number=(payload.get("reference_number") or "").strip() or None,
        notes=(payload.get("notes") or "").strip() or None,
        status=status,
        current_user_id=current_user_id,
        submitted_by_driver_id=None,
        received_by_admin_id=received_by_admin["_id"] if received_by_admin else None,
        approved_by_admin_id=approved_by_admin["_id"] if approved_by_admin else None,
        admin_received_amount=admin_received_amount,
        admin_approval_note=admin_approval_note,
    )
    result = collections_collection().insert_one(collection_document)
    collection_document["_id"] = result.inserted_id

    if status == "approved":
        _create_wallet_credit_for_collection(collection_document, current_user_id=current_user_id)

    return _enrich_collection(collection_document)


def submit_driver_payment(payload: dict, current_user_id: str) -> dict:
    driver = _get_driver_document(current_user_id)
    assignment = assignments_collection().find_one(
        {"driver_id": driver["_id"], "status": {"$in": ["active", "suspended"]}}
    )
    if not assignment:
        raise ApiError("You do not have an active assignment to submit payments for.", status_code=400)

    vehicle = _get_vehicle_document(str(assignment.get("vehicle_id")))
    amount = _validate_positive_amount(payload.get("amount"), "amount")
    collection_date = (payload.get("collection_date") or now_utc().date().isoformat()).strip()
    payment_method = (payload.get("payment_method") or "").strip().lower()
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        raise ApiError("payment_method must be one of: cash, momo, bank, other.", status_code=400)

    collection_document = _build_collection_document(
        driver=driver,
        vehicle=vehicle,
        assignment=assignment,
        amount=amount,
        collection_date=collection_date,
        payment_method=payment_method,
        reference_number=(payload.get("reference_number") or "").strip() or None,
        notes=(payload.get("notes") or "").strip() or None,
        status="pending",
        current_user_id=current_user_id,
        submitted_by_driver_id=driver["_id"],
    )
    result = collections_collection().insert_one(collection_document)
    collection_document["_id"] = result.inserted_id
    return _enrich_collection(collection_document)


def update_collection_status(
    collection_id: str,
    status: str,
    current_user_id: str,
    rejection_reason: str | None = None,
    admin_received_amount: float | None = None,
    admin_approval_note: str | None = None,
) -> dict:
    if not ObjectId.is_valid(current_user_id):
        raise ApiError("Invalid user identity.", status_code=400)

    next_status = (status or "").strip().lower()
    if next_status not in ALLOWED_COLLECTION_STATUSES:
        raise ApiError(
            "status must be one of: submitted, received, approved, rejected, reversed.", status_code=400
        )

    collection_object_id = _to_object_id(collection_id, "collection_id")
    collection_document = collections_collection().find_one({"_id": collection_object_id})
    if not collection_document:
        raise ApiError("Collection not found.", status_code=404)

    current_status = collection_document.get("status")
    if current_status == "reversed":
        raise ApiError("Reversed collections cannot be updated.", status_code=400)
    if current_status == "approved" and next_status in {"pending", "submitted", "received", "rejected"}:
        raise ApiError("Approved collections cannot be moved back to a pending or rejected state.", status_code=400)
    if current_status == next_status:
        raise ApiError("Collection already has that status.", status_code=400)

    timestamp = now_utc()
    update_fields = {"status": next_status, "updated_at": timestamp}

    if next_status == "approved":
        approved_by_admin = _get_admin_document(current_user_id)
        submitted_amount = _round_currency_amount(
            collection_document.get("submitted_amount")
            if collection_document.get("submitted_amount") is not None
            else collection_document.get("amount") or 0
        )
        if admin_received_amount is None:
            raise ApiError("admin_received_amount is required when approving a payment.", status_code=400)
        normalized_received_amount = _round_currency_amount(
            _validate_positive_amount(admin_received_amount, "admin_received_amount")
        )
        if normalized_received_amount != submitted_amount:
            raise ApiError("Received amount must match submitted amount.", status_code=400)
        update_fields["approved_by_admin_id"] = approved_by_admin["_id"]
        update_fields["approved_at"] = timestamp
        update_fields["rejection_reason"] = None
        update_fields["rejected_by_admin_id"] = None
        update_fields["rejected_at"] = None
        update_fields["admin_received_amount"] = normalized_received_amount
        update_fields["admin_approval_note"] = (admin_approval_note or "").strip() or None
        if not collection_document.get("received_by_admin_id"):
            update_fields["received_by_admin_id"] = approved_by_admin["_id"]
        if current_status not in APPROVED_PAYMENT_STATUSES:
            _create_wallet_credit_for_collection(collection_document, current_user_id=current_user_id)

    if next_status == "rejected":
        reason = (rejection_reason or "").strip()
        if not reason:
            raise ApiError("rejection_reason is required when rejecting a payment.", status_code=400)
        rejected_by_admin = _get_admin_document(current_user_id)
        update_fields["rejected_by_admin_id"] = rejected_by_admin["_id"]
        update_fields["rejection_reason"] = reason
        update_fields["rejected_at"] = timestamp

    if next_status == "reversed":
        create_wallet_entry(
            driver_id=collection_document["driver_id"],
            vehicle_id=collection_document.get("vehicle_id"),
            assignment_id=collection_document.get("assignment_id"),
            entry_type="reversal",
            description="Collection reversal",
            debit=float(collection_document.get("amount") or 0),
            credit=0,
            reference_id=collection_document["_id"],
            created_by=current_user_id,
        )
        update_fields["rejection_reason"] = (rejection_reason or "").strip() or None

    collections_collection().update_one(
        {"_id": collection_object_id},
        {"$set": update_fields},
    )
    collection_document.update(update_fields)
    return _enrich_collection(collection_document)


def list_pending_payment_submissions() -> list[dict]:
    cache_key = "collections:pending_submissions"
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    submissions = list(
        collections_collection()
        .find({"status": {"$in": list(PENDING_PAYMENT_STATUSES)}}, COLLECTION_LIST_PROJECTION)
        .sort([("collection_date", DESCENDING), ("created_at", DESCENDING)])
    )
    return set_ttl_cached(cache_key, _batch_enrich_collections(submissions), ttl_seconds=10)


def list_driver_weekly_statuses() -> list[dict]:
    cache_key = "collections:weekly_statuses"
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    assignments = list(
        assignments_collection().find(
            {"status": {"$in": ["active", "suspended"]}},
            ASSIGNMENT_SUMMARY_PROJECTION,
        )
    )
    driver_lookup = _build_document_lookup(
        users_collection(),
        {assignment.get("driver_id") for assignment in assignments if isinstance(assignment.get("driver_id"), ObjectId)},
        USER_SUMMARY_PROJECTION,
    )
    vehicle_lookup = _build_document_lookup(
        vehicles_collection(),
        {assignment.get("vehicle_id") for assignment in assignments if isinstance(assignment.get("vehicle_id"), ObjectId)},
        VEHICLE_SUMMARY_PROJECTION,
    )
    weekly_statuses = []
    for assignment in assignments:
        driver = driver_lookup.get(assignment.get("driver_id"))
        vehicle = vehicle_lookup.get(assignment.get("vehicle_id"))
        current_cycle = get_current_cycle_for_assignment(assignment)
        weekly_statuses.append(
            {
                "assignment": serialize_assignment(assignment),
                "driver": serialize_user(driver) if driver else None,
                "vehicle": serialize_vehicle(vehicle) if vehicle else None,
                "cycle": current_cycle,
            }
        )

    weekly_statuses.sort(
        key=lambda item: (
            item["cycle"].get("status") != "overdue",
            item["cycle"].get("outstanding_balance", 0),
        ),
        reverse=True,
    )
    return set_ttl_cached(cache_key, weekly_statuses, ttl_seconds=15)


def list_collection_options() -> dict:
    return _cached_collection_options_payload()


def _parse_collection_date(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def get_driver_dashboard_summary(driver_user_id: str) -> dict:
    cache_key = build_cache_key("driver_dashboard_summary", driver_user_id=driver_user_id)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    request_started_at = perf_counter()
    driver = _get_driver_document(driver_user_id)

    active_assignment = assignments_collection().find_one(
        {"driver_id": driver["_id"], "status": "active"}
    )
    if not active_assignment:
        return {
            "driver_id": str(driver["_id"]),
            "active_assignment": None,
            "vehicle": None,
            "weekly_cycle": None,
            "weekly_target": 0,
            "daily_target": 0,
            "amount_paid_this_week": 0,
            "submitted_total_this_week": 0,
            "approved_total_this_week": 0,
            "outstanding_balance": 0,
            "achievement_percentage": 0,
            "total_collections_this_week": 0,
            "latest_collections": [],
            "today_collection_total": 0,
        }

    vehicle = vehicles_collection().find_one({"_id": active_assignment.get("vehicle_id")})
    serialized_assignment = serialize_assignment(active_assignment)
    serialized_vehicle = serialize_vehicle(vehicle) if vehicle else None

    current_cycle = get_current_cycle_for_assignment(active_assignment)
    week_window = get_weekly_cycle_window()
    week_start = week_window["week_start_dt"].date().isoformat()
    week_end = week_window["week_end_dt"].date().isoformat()
    today_iso = now_utc().date().isoformat()

    summary_started_at = perf_counter()
    collection_summary = list(
        collections_collection().aggregate(
            [
                {
                    "$match": {
                        "driver_id": driver["_id"],
                        "assignment_id": active_assignment["_id"],
                        "cycle_key": current_cycle["cycle_key"],
                        "status": {"$in": ["submitted", "received", "approved"]},
                        "collection_date": {"$gte": week_start, "$lte": week_end},
                    }
                },
                {
                    "$facet": {
                        "totals": [
                            {
                                "$group": {
                                    "_id": None,
                                    "submitted_total": {"$sum": {"$ifNull": ["$amount", 0]}},
                                    "approved_total": {
                                        "$sum": {
                                            "$cond": [{"$eq": ["$status", "approved"]}, {"$ifNull": ["$amount", 0]}, 0]
                                        }
                                    },
                                    "total_collections": {"$sum": 1},
                                    "today_total": {
                                        "$sum": {
                                            "$cond": [
                                                {"$eq": ["$collection_date", today_iso]},
                                                {"$ifNull": ["$amount", 0]},
                                                0,
                                            ]
                                        }
                                    },
                                }
                            }
                        ],
                        "latest": [
                            {"$sort": {"collection_date": -1, "created_at": -1}},
                            {"$limit": 5},
                            {"$project": COLLECTION_LIST_PROJECTION},
                        ],
                    }
                },
            ]
        )
    )
    log_db_duration("driver_dashboard_summary.collections_aggregate", summary_started_at)
    summary_payload = collection_summary[0] if collection_summary else {}
    totals = (summary_payload.get("totals") or [{}])[0]
    latest_collection_documents = summary_payload.get("latest") or []
    submitted_total = round(float(totals.get("submitted_total") or 0), 2)
    amount_paid_this_week = round(float(totals.get("approved_total") or 0), 2)
    weekly_target = float(active_assignment.get("weekly_target") or 0)
    daily_target = float(active_assignment.get("daily_target") or 0)
    outstanding_balance = round(max(weekly_target - amount_paid_this_week, 0), 2)
    achievement_percentage = round(
        (amount_paid_this_week / weekly_target * 100) if weekly_target > 0 else 0,
        2,
    )
    latest_collections = [serialize_collection(collection_document) for collection_document in latest_collection_documents]
    today_collection_total = round(float(totals.get("today_total") or 0), 2)

    summary = {
        "driver_id": str(driver["_id"]),
        "active_assignment": serialized_assignment,
        "vehicle": serialized_vehicle,
        "weekly_cycle": current_cycle,
        "weekly_target": weekly_target,
        "daily_target": daily_target,
        "amount_paid_this_week": amount_paid_this_week,
        "submitted_total_this_week": submitted_total,
        "approved_total_this_week": amount_paid_this_week,
        "outstanding_balance": outstanding_balance,
        "achievement_percentage": achievement_percentage,
        "total_collections_this_week": int(totals.get("total_collections") or 0),
        "latest_collections": latest_collections,
        "today_collection_total": today_collection_total,
    }
    _log_slow_collection_section("driver_dashboard_summary.total", request_started_at, threshold_ms=800)
    return set_ttl_cached(cache_key, summary, ttl_seconds=15)
