from time import sleep
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING
from flask import current_app
from pymongo.errors import (
    AutoReconnect,
    ConnectionFailure,
    DuplicateKeyError,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from extensions import get_collection
from utils.api_error import ApiError


MASTER_DATA_DEFAULTS: dict[str, list[str]] = {
    "customer_categories": [
        "Regular",
        "Recurring",
        "Corporate",
        "Airport",
        "Church",
        "School",
        "VIP",
        "Event",
        "Other",
    ],
    "relationship_categories": [
        "General Customer",
        "Business Owner",
        "Executive",
        "CEO",
        "Investor",
        "Diplomat",
        "Government Official",
        "Industry Leader",
        "Gatekeeper",
        "Decision Maker",
        "Influencer",
        "Partner",
        "Vendor",
        "Supplier",
        "Pastor",
        "Religious Leader",
        "Media Personality",
        "Community Leader",
        "Professional",
        "Friend",
        "Personal Contact",
        "Other",
    ],
    "opportunity_levels": [
        "Low",
        "Medium",
        "High",
        "Strategic",
    ],
    "network_values": [
        "Potential Client",
        "Potential Partner",
        "Potential Investor",
        "Referral Source",
        "Industry Gatekeeper",
        "Mentor",
        "Supplier",
        "No Current Opportunity",
    ],
    "ride_types": [
        "Immediate Ride",
        "Scheduled Ride",
        "Recurring Ride",
        "Airport Ride",
        "Corporate Ride",
        "Church Ride",
        "School Ride",
        "Event Ride",
        "Special Booking",
    ],
    "ride_sources": [
        "Bolt",
        "Uber",
        "Yango",
        "Direct Customer",
        "Corporate Customer",
        "Airport Pickup",
        "Church Booking",
        "Referral",
        "Other",
    ],
    "ride_purposes": [
        "Company Ride",
        "Personal Ride",
        "Staff Ride",
        "Maintenance Run",
        "Test Drive",
        "Corporate Assignment",
        "Other",
    ],
    "booking_types": [
        "Customer Booking",
        "Airport Pickup",
        "Corporate Booking",
        "Church Pickup",
        "School Pickup",
        "VIP Booking",
        "Staff Assignment",
        "Follow-Up Reminder",
        "Personal Reminder",
        "Maintenance Reminder",
        "Insurance Renewal Reminder",
        "Vehicle Inspection Reminder",
        "Other",
    ],
    "customer_sources": [
        "Manual Entry",
        "Ride Customer",
        "Scheduled Booking",
        "Referral",
        "Business Lead",
        "Imported Record",
        "Other",
    ],
    "organization_types": [
        "Corporate",
        "Government",
        "Church",
        "School",
        "NGO",
        "SME",
        "Other",
    ],
    "industries": [
        "Banking",
        "Telecommunications",
        "Government",
        "Education",
        "Healthcare",
        "Logistics",
        "Retail",
        "Other",
    ],
    "lead_statuses": [
        "New",
        "Warm",
        "Hot",
        "Converted",
        "Not Interested",
        "Follow Up Later",
    ],
    "potential_services": [
        "Business Operating System",
        "Website Development",
        "CRM System",
        "Fleet Management System",
        "Inventory System",
        "Business Consulting",
        "Business Training",
        "Digital Transformation",
        "Other",
    ],
    "payment_methods": [
        "Cash",
        "Mobile Money",
        "Bank Transfer",
        "Corporate Account",
        "Credit",
        "Other",
    ],
}

MASTER_DATA_TYPES = set(MASTER_DATA_DEFAULTS.keys())


def now_utc():
    return datetime.now(timezone.utc)


def master_data_collection():
    return get_collection("master_data")


def ensure_master_data_indexes():
    master_data_collection().create_index([("data_type", ASCENDING)])
    master_data_collection().create_index(
        [("data_type", ASCENDING), ("normalized_name", ASCENDING)],
        unique=True,
    )
    master_data_collection().create_index([("active", ASCENDING)])
    master_data_collection().create_index([("archived", ASCENDING)])
    master_data_collection().create_index([("sort_order", ASCENDING)])
    safe_seed_master_data()


def _master_data_defaults_missing() -> bool:
    for data_type, values in MASTER_DATA_DEFAULTS.items():
        existing_count = master_data_collection().count_documents(
            {
                "data_type": data_type,
                "normalized_name": {
                    "$in": [value.lower() for value in values],
                },
            },
            limit=1,
        )
        if existing_count == 0:
            return True
    return False


def _to_object_id(value, field_name: str, *, required: bool = True):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _normalize_text(value: Any):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_master_data_type(data_type: str | None):
    normalized = _normalize_text(data_type)
    if normalized not in MASTER_DATA_TYPES:
        raise ApiError("Invalid master data type.", status_code=400)
    return normalized


def _normalize_name(name: str | None):
    normalized = _normalize_text(name)
    if not normalized:
        raise ApiError("name is required.", status_code=400)
    return normalized


def _serialize_item(document: dict):
    return {
        "id": str(document.get("_id")),
        "data_type": document.get("data_type"),
        "name": document.get("name"),
        "active": bool(document.get("active")),
        "archived": bool(document.get("archived", False)),
        "admin_editable": bool(document.get("admin_editable", True)),
        "description": document.get("description"),
        "sort_order": document.get("sort_order"),
        "created_by": str(document.get("created_by")) if document.get("created_by") else None,
        "updated_by": str(document.get("updated_by")) if document.get("updated_by") else None,
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


def seed_default_master_data():
    timestamp = now_utc()
    for data_type, values in MASTER_DATA_DEFAULTS.items():
        for index, value in enumerate(values, start=1):
            normalized_name = value.lower()
            master_data_collection().update_one(
                {"data_type": data_type, "normalized_name": normalized_name},
                {
                    "$setOnInsert": {
                        "data_type": data_type,
                        "name": value,
                        "normalized_name": normalized_name,
                        "active": True,
                        "archived": False,
                        "admin_editable": True,
                        "description": None,
                        "sort_order": index,
                        "created_by": None,
                        "updated_by": None,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    }
                },
                upsert=True,
            )


def safe_seed_master_data():
    retries = max(1, int(current_app.config.get("MASTER_DATA_SEED_RETRIES", 3)))
    retry_delay = float(current_app.config.get("MASTER_DATA_SEED_RETRY_DELAY_SECONDS", 1.5))

    for attempt in range(1, retries + 1):
        try:
            if not _master_data_defaults_missing():
                return
            seed_default_master_data()
            normalize_trip_master_data_defaults()
            current_app.logger.info(
                "[Flux Startup] Master data seed completed successfully on attempt %s.",
                attempt,
            )
            return
        except (
            AutoReconnect,
            ServerSelectionTimeoutError,
            ConnectionFailure,
            OperationFailure,
        ) as error:
            current_app.logger.exception(
                "[Flux Startup] Master data seed attempt %s/%s failed due to MongoDB connectivity issue: %s",
                attempt,
                retries,
                error,
            )
            if attempt < retries:
                sleep(retry_delay)
        except Exception:
            current_app.logger.exception(
                "[Flux Startup] Master data seed failed with an unexpected error."
            )
            return

    current_app.logger.error(
        "[Flux Startup] Master data seed skipped after %s failed attempts. Flask will continue running.",
        retries,
    )


def normalize_trip_master_data_defaults():
    timestamp = now_utc()
    active_source_names = {value.lower() for value in MASTER_DATA_DEFAULTS["ride_sources"]}
    legacy_seeded_sources = {
        "direct driver customer",
        "scheduled booking",
        "corporate account",
        "walk-in",
        "airport stand",
    }
    master_data_collection().update_many(
        {
            "data_type": "ride_sources",
            "normalized_name": {"$in": list(legacy_seeded_sources - active_source_names)},
            "created_by": None,
        },
        {
            "$set": {
                "active": False,
                "updated_at": timestamp,
            }
        },
    )


def _can_manage(current_role: str, document: dict | None = None):
    if current_role == "owner":
        return
    if current_role == "admin":
        if document is None:
            return
        if document.get("admin_editable", True):
            return
    raise ApiError("You do not have permission to manage this master data.", status_code=403)


def list_master_data(*, current_role: str, active_only: bool = False) -> dict:
    query: dict[str, Any] = {}
    if active_only or current_role == "driver":
        query["active"] = True
        query["archived"] = {"$ne": True}

    items = list(
        master_data_collection().find(query).sort(
            [("data_type", ASCENDING), ("sort_order", ASCENDING), ("name", ASCENDING)]
        )
    )
    grouped: dict[str, list[dict]] = {data_type: [] for data_type in MASTER_DATA_TYPES}
    for item in items:
        grouped.setdefault(item["data_type"], []).append(_serialize_item(item))
    return {
        "master_data": grouped,
        "types": sorted(MASTER_DATA_TYPES),
    }


def get_active_master_data_items(data_type: str) -> list[dict]:
    normalized_type = _normalize_master_data_type(data_type)
    documents = master_data_collection().find(
        {
            "data_type": normalized_type,
            "active": True,
            "archived": {"$ne": True},
        }
    ).sort([("sort_order", ASCENDING), ("name", ASCENDING)])
    return [_serialize_item(document) for document in documents]


def get_active_master_data_values(data_type: str) -> list[str]:
    return [item["name"] for item in get_active_master_data_items(data_type)]


def resolve_master_data_item(
    data_type: str,
    identifier: str | ObjectId | None,
    *,
    active_only: bool = True,
):
    if identifier in (None, ""):
        return None

    normalized_type = _normalize_master_data_type(data_type)
    query: dict[str, Any] = {"data_type": normalized_type}
    if isinstance(identifier, ObjectId) or (
        isinstance(identifier, str) and ObjectId.is_valid(identifier)
    ):
        query["_id"] = _to_object_id(identifier, f"{normalized_type}_id")
    else:
        query["normalized_name"] = _normalize_name(str(identifier)).lower()

    document = master_data_collection().find_one(query)
    if not document:
        raise ApiError(f"{identifier} is not configured for {normalized_type}.", status_code=400)
    if active_only and (not document.get("active") or document.get("archived")):
        raise ApiError(
            f"{document.get('name')} is inactive or archived and cannot be used for new records.",
            status_code=400,
        )
    return document


def assert_master_data_value(data_type: str, value: str | None):
    document = resolve_master_data_item(data_type, value, active_only=True)
    return document.get("name") if document else None


def create_master_data_item(payload: dict, *, current_user_id: str, current_role: str):
    _can_manage(current_role)
    data_type = _normalize_master_data_type(payload.get("data_type"))
    name = _normalize_name(payload.get("name"))
    description = _normalize_text(payload.get("description"))
    active = bool(payload.get("active", True))
    archived = bool(payload.get("archived", False))
    admin_editable = bool(payload.get("admin_editable", True))
    if current_role == "admin":
        admin_editable = True
    if archived:
        active = False

    max_document = master_data_collection().find_one({"data_type": data_type}, sort=[("sort_order", -1)])
    sort_order = int(payload.get("sort_order") or (max_document.get("sort_order", 0) + 1 if max_document else 1))
    timestamp = now_utc()
    document = {
        "data_type": data_type,
        "name": name,
        "normalized_name": name.lower(),
        "active": active,
        "archived": archived,
        "admin_editable": admin_editable,
        "description": description,
        "sort_order": sort_order,
        "created_by": _to_object_id(current_user_id, "current_user_id"),
        "updated_by": _to_object_id(current_user_id, "current_user_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        result = master_data_collection().insert_one(document)
    except DuplicateKeyError:
        raise ApiError("A master data item with this name already exists for that type.", status_code=409) from None
    document["_id"] = result.inserted_id
    return _serialize_item(document)


def update_master_data_item(item_id: str, payload: dict, *, current_user_id: str, current_role: str):
    document = master_data_collection().find_one({"_id": _to_object_id(item_id, "item_id")})
    if not document:
        raise ApiError("Master data item not found.", status_code=404)
    _can_manage(current_role, document)

    update_fields: dict[str, Any] = {}
    if "name" in payload:
        name = _normalize_name(payload.get("name"))
        update_fields["name"] = name
        update_fields["normalized_name"] = name.lower()
    if "description" in payload:
        update_fields["description"] = _normalize_text(payload.get("description"))
    if "active" in payload:
        update_fields["active"] = bool(payload.get("active"))
    if "archived" in payload:
        update_fields["archived"] = bool(payload.get("archived"))
        if update_fields["archived"]:
            update_fields["active"] = False
    if "sort_order" in payload:
        sort_order = payload.get("sort_order")
        if isinstance(sort_order, bool) or not isinstance(sort_order, int):
            raise ApiError("sort_order must be numeric.", status_code=400)
        update_fields["sort_order"] = sort_order
    if "admin_editable" in payload:
        if current_role != "owner":
            raise ApiError("Only the owner can change admin edit permission.", status_code=403)
        update_fields["admin_editable"] = bool(payload.get("admin_editable"))

    if not update_fields:
        raise ApiError("No master data fields provided for update.", status_code=400)

    if update_fields.get("active") and update_fields.get("archived"):
        raise ApiError("Archived master data cannot remain active.", status_code=400)

    update_fields["updated_by"] = _to_object_id(current_user_id, "current_user_id")
    update_fields["updated_at"] = now_utc()
    try:
        master_data_collection().update_one(
            {"_id": document["_id"]},
            {"$set": update_fields},
        )
    except DuplicateKeyError:
        raise ApiError("A master data item with this name already exists for that type.", status_code=409) from None
    document.update(update_fields)
    return _serialize_item(document)
