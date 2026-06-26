from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from time import perf_counter

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from uuid import uuid4

from extensions import get_collection
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.preventive_maintenance_service import generate_default_preventive_schedules_for_vehicle
from services.system_settings_service import (
    get_admin_role_permissions,
    should_include_fuel_in_profitability,
)
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


ALLOWED_VEHICLE_TYPES = {"saloon", "suv", "pickup", "van", "truck", "motorcycle"}
ALLOWED_TRANSMISSIONS = {"manual", "automatic"}
ALLOWED_FUEL_TYPES = {"petrol", "diesel", "hybrid", "electric"}
ALLOWED_INSURANCE_TYPES = {"Third Party", "Comprehensive"}
ALLOWED_ASSET_OWNER_TYPES = {
    "Axelera Owned",
    "Existing Company Asset",
    "Managed Third-Party Vehicle",
    "Investor-Funded Vehicle",
    "Leased Vehicle",
    "Partner Vehicle",
}
ALLOWED_RECOVERY_BASIS_TYPES = {
    "Original Purchase Cost",
    "Current Estimated Value",
    "Custom Recovery Value",
    "Transfer Value",
}
ALLOWED_VEHICLE_STATUSES = {
    "available",
    "assigned",
    "maintenance",
    "accident",
    "out_of_service",
    "suspended",
    "retired",
}
SENSITIVE_ADMIN_PERMISSION_FIELDS = {
    "purchase_cost": "view_vehicle_investment",
    "shipping_cost": "view_vehicle_investment",
    "clearing_cost": "view_vehicle_investment",
    "insurance_cost": "view_vehicle_investment",
    "roadworthy_cost": "view_vehicle_investment",
    "ama_permit_cost": "view_vehicle_investment",
    "vehicle_license_cost": "view_vehicle_investment",
    "tracker_cost": "view_vehicle_investment",
    "branding_cost": "view_vehicle_investment",
    "initial_repairs_cost": "view_vehicle_investment",
    "registration_cost": "view_vehicle_investment",
    "other_setup_cost": "view_vehicle_investment",
    "total_vehicle_investment": "view_vehicle_investment",
    "amount_recovered": "view_vehicle_recovery",
    "remaining_balance": "view_vehicle_recovery",
    "recovery_percentage": "view_vehicle_recovery",
    "estimated_recovery_weeks": "view_vehicle_recovery",
    "estimated_recovery_months": "view_vehicle_recovery",
    "estimated_recovery_date": "view_vehicle_recovery",
    "estimated_break_even_date": "view_vehicle_recovery",
    "recovery_status": "view_vehicle_recovery",
    "gross_revenue": "view_profitability",
    "net_profit": "view_profitability",
    "profit_margin": "view_profitability",
    "roi": "view_profitability",
}
INVESTMENT_COST_FIELDS = [
    "purchase_cost",
    "shipping_cost",
    "clearing_cost",
    "insurance_cost",
    "roadworthy_cost",
    "ama_permit_cost",
    "vehicle_license_cost",
    "tracker_cost",
    "branding_cost",
    "initial_repairs_cost",
    "registration_cost",
    "other_setup_cost",
]
DEFAULT_OPERATING_FLEET_NAME = "Flux Fleet Ops"
DEFAULT_ASSET_OWNER_TYPE = "Axelera Owned"
DEFAULT_ASSET_OWNER_NAME = "Axelera"


def now_utc():
    return datetime.now(timezone.utc)


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def vehicle_cost_items_collection():
    return get_collection("vehicle_cost_items")


def ownership_history_collection():
    return get_collection("vehicle_ownership_history")


def collections_collection():
    return get_collection("collections")


def fuel_logs_collection():
    return get_collection("fuel_logs")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def expenses_collection():
    return get_collection("expenses")


def rides_collection():
    return get_collection("rides")


def faults_collection():
    return get_collection("faults")


def compliance_records_collection():
    return get_collection("vehicle_compliance_records")


def ensure_vehicle_indexes():
    ensure_indexes_for_collection(
        vehicles_collection(),
        [
            {"keys": [("registration_number", ASCENDING)], "options": {"unique": True}},
            {"keys": [("chassis_number", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("engine_number", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("assigned_driver_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("asset_owner_name", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("asset_owner_type", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("assigned_driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("assigned_driver_id", ASCENDING), ("updated_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("updated_at", DESCENDING)]},
            {"keys": [("asset_owner_name", ASCENDING), ("status", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("asset_owner_type", ASCENDING), ("status", ASCENDING)], "options": {"sparse": True}},
        ],
        collection_name="vehicles",
    )
    ensure_indexes_for_collection(
        vehicle_cost_items_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
        ],
        collection_name="vehicle_cost_items",
    )
    ensure_indexes_for_collection(
        ownership_history_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("effective_date", DESCENDING)]},
            {"keys": [("current_record", ASCENDING)]},
            {"keys": [("asset_owner_name", ASCENDING)]},
            {"keys": [("asset_owner_type", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("effective_date", DESCENDING)]},
        ],
        collection_name="vehicle_ownership_history",
    )


def normalize_string(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_registration_number(value):
    normalized = normalize_string(value)
    return normalized.upper() if normalized else None


def validate_numeric(value, field_name: str, *, positive: bool = False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if positive and value <= 0:
        raise ApiError(f"{field_name} must be a positive number.", status_code=400)
    return round(float(value), 2) if isinstance(value, (int, float)) else value


def validate_integer(value, field_name: str, *, positive: bool = False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"{field_name} must be an integer.", status_code=400)
    if positive and value <= 0:
        raise ApiError(f"{field_name} must be a positive integer.", status_code=400)
    return value


def validate_boolean(value, field_name: str):
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ApiError(f"{field_name} must be true or false.", status_code=400)
    return value


def validate_reference_id(value, field_name: str) -> ObjectId | None:
    if value in (None, ""):
        return None
    if not ObjectId.is_valid(value):
        raise ApiError(f"Invalid {field_name}.", status_code=400)
    return ObjectId(value)


def _driver_object_id_from_reference(value) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    return None


def _serialize_assigned_driver_details(driver_document: dict | None) -> dict | None:
    if not driver_document or driver_document.get("role") != "driver":
        return None

    serialized_driver = serialize_user(driver_document)
    driver_profile = serialized_driver.get("driver_profile") or {}
    return {
        "id": serialized_driver.get("id"),
        "full_name": serialized_driver.get("full_name"),
        "phone": serialized_driver.get("phone"),
        "email": serialized_driver.get("email"),
        "status": serialized_driver.get("status"),
        "license_number": driver_profile.get("license_number"),
    }


def _build_assigned_driver_map(vehicle_documents: list[dict]) -> dict[str, dict]:
    driver_object_ids: list[ObjectId] = []
    seen_driver_ids: set[str] = set()

    for vehicle_document in vehicle_documents:
        driver_object_id = _driver_object_id_from_reference(vehicle_document.get("assigned_driver_id"))
        if not driver_object_id:
            continue
        driver_key = str(driver_object_id)
        if driver_key in seen_driver_ids:
            continue
        seen_driver_ids.add(driver_key)
        driver_object_ids.append(driver_object_id)

    if not driver_object_ids:
        return {}

    return {
        str(driver_document["_id"]): _serialize_assigned_driver_details(driver_document)
        for driver_document in users_collection().find({"_id": {"$in": driver_object_ids}})
    }


def get_vehicle_document_by_id(vehicle_id: str) -> dict:
    if not ObjectId.is_valid(vehicle_id):
        raise ApiError("Vehicle not found.", status_code=404)

    vehicle = vehicles_collection().find_one({"_id": ObjectId(vehicle_id)})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def get_vehicle_document_by_id_with_projection(vehicle_id: str, projection: dict | None = None) -> dict:
    if not ObjectId.is_valid(vehicle_id):
        raise ApiError("Vehicle not found.", status_code=404)

    vehicle = vehicles_collection().find_one({"_id": ObjectId(vehicle_id)}, projection)
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def validate_assigned_driver(driver_id: ObjectId | None, *, vehicle_id: ObjectId | None = None) -> ObjectId | None:
    if driver_id is None:
        return None

    driver = users_collection().find_one({"_id": driver_id})
    if not driver or driver.get("role") != "driver":
        raise ApiError("Assigned driver must be a valid driver user.", status_code=400)

    assigned_vehicle_id = (driver.get("driver_profile") or {}).get("assigned_vehicle_id")
    if assigned_vehicle_id and assigned_vehicle_id != vehicle_id:
        raise ApiError("Driver is already assigned to another vehicle.", status_code=409)

    return driver_id


def _safe_float(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return round(float(value), 2)


def _days_in_month(target_date: date) -> int:
    if target_date.month == 12:
        next_month = date(target_date.year + 1, 1, 1)
    else:
        next_month = date(target_date.year, target_date.month + 1, 1)
    return (next_month - date(target_date.year, target_date.month, 1)).days


def _serialize_cost_item(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "vehicle_id": str(document.get("vehicle_id")) if document.get("vehicle_id") else None,
        "item_name": document.get("item_name"),
        "amount": _safe_float(document.get("amount")),
        "date": document.get("date"),
        "notes": document.get("notes"),
        "created_by": str(document.get("created_by")) if document.get("created_by") else None,
        "updated_by": str(document.get("updated_by")) if document.get("updated_by") else None,
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


def _serialize_vehicle_list_item(vehicle_document: dict, assigned_driver_details: dict | None = None) -> dict:
    _apply_vehicle_ownership_defaults(vehicle_document)
    return {
        "id": str(vehicle_document.get("_id")),
        "registration_number": vehicle_document.get("registration_number"),
        "vehicle_type": vehicle_document.get("vehicle_type"),
        "make": vehicle_document.get("make"),
        "model": vehicle_document.get("model"),
        "year": vehicle_document.get("year"),
        "color": vehicle_document.get("color"),
        "transmission": vehicle_document.get("transmission"),
        "fuel_type": vehicle_document.get("fuel_type"),
        "chassis_number": None,
        "engine_number": None,
        "insurance_expiry": vehicle_document.get("insurance_expiry"),
        "insurance_profile": vehicle_document.get("insurance_profile") or {},
        "roadworthy_expiry": vehicle_document.get("roadworthy_expiry"),
        "default_weekly_target": vehicle_document.get("default_weekly_target"),
        "default_daily_target": vehicle_document.get("default_daily_target"),
        "operating_fleet_name": vehicle_document.get("operating_fleet_name"),
        "asset_owner_type": vehicle_document.get("asset_owner_type"),
        "asset_owner_name": vehicle_document.get("asset_owner_name"),
        "status": vehicle_document.get("status"),
        "assigned_driver_id": str(vehicle_document.get("assigned_driver_id")) if vehicle_document.get("assigned_driver_id") else None,
        "assigned_driver_details": assigned_driver_details,
        "created_by": str(vehicle_document.get("created_by")) if vehicle_document.get("created_by") else None,
        "created_at": vehicle_document.get("created_at").isoformat() if vehicle_document.get("created_at") else None,
        "updated_at": vehicle_document.get("updated_at").isoformat() if vehicle_document.get("updated_at") else None,
        "vehicle_cost_items": [],
        "economics": {},
    }


def _vehicle_detail_projection() -> dict:
    return {
        "registration_number": 1,
        "vehicle_type": 1,
        "make": 1,
        "model": 1,
        "year": 1,
        "color": 1,
        "transmission": 1,
        "fuel_type": 1,
        "chassis_number": 1,
        "engine_number": 1,
        "insurance_expiry": 1,
        "insurance_profile": 1,
        "roadworthy_expiry": 1,
        "default_weekly_target": 1,
        "default_daily_target": 1,
        "current_odometer": 1,
        "operating_fleet_name": 1,
        "asset_owner_type": 1,
        "asset_owner_name": 1,
        "asset_owner_contact": 1,
        "ownership_notes": 1,
        "ownership_start_date": 1,
        "recovery_basis_type": 1,
        "original_purchase_price": 1,
        "original_purchase_date": 1,
        "current_estimated_value": 1,
        "custom_recovery_value": 1,
        "capital_basis_for_recovery": 1,
        "capital_recovery_tracking_enabled": 1,
        "status": 1,
        "assigned_driver_id": 1,
        "created_by": 1,
        "updated_by": 1,
        "created_at": 1,
        "updated_at": 1,
        "purchase_cost": 1,
        "shipping_cost": 1,
        "clearing_cost": 1,
        "insurance_cost": 1,
        "roadworthy_cost": 1,
        "ama_permit_cost": 1,
        "vehicle_license_cost": 1,
        "tracker_cost": 1,
        "branding_cost": 1,
        "initial_repairs_cost": 1,
        "registration_cost": 1,
        "other_setup_cost": 1,
    }


def _extract_vehicle_current_odometer(vehicle_id: ObjectId) -> float | None:
    candidates: list[float] = []

    latest_fuel_log = fuel_logs_collection().find_one(
        {"vehicle_id": vehicle_id, "odometer_reading": {"$ne": None}},
        {"odometer_reading": 1},
        sort=[("fuel_date", -1), ("created_at", -1)],
    )
    if latest_fuel_log and isinstance(latest_fuel_log.get("odometer_reading"), (int, float)):
        candidates.append(float(latest_fuel_log["odometer_reading"]))

    latest_maintenance_job = maintenance_jobs_collection().find_one(
        {"vehicle_id": vehicle_id, "odometer_reading": {"$ne": None}},
        {"odometer_reading": 1},
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    if latest_maintenance_job and isinstance(latest_maintenance_job.get("odometer_reading"), (int, float)):
        candidates.append(float(latest_maintenance_job["odometer_reading"]))

    latest_ride = rides_collection().find_one(
        {
            "vehicle_id": vehicle_id,
            "$or": [
                {"odometer_end": {"$ne": None}},
                {"odometer_start": {"$ne": None}},
            ],
        },
        {"odometer_end": 1, "odometer_start": 1},
        sort=[("trip_date", -1), ("created_at", -1)],
    )
    if latest_ride:
        for field_name in ("odometer_end", "odometer_start"):
            value = latest_ride.get(field_name)
            if isinstance(value, (int, float)):
                candidates.append(float(value))
                break

    return round(max(candidates), 2) if candidates else None


def _can_admin_access(permission_key: str) -> bool:
    return bool(get_admin_role_permissions().get(permission_key))


def _normalize_text(value):
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _normalize_risk_list(values):
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        raise ApiError("Insurance risks must be provided as a list.", status_code=400)
    normalized = []
    for item in values:
        label = normalize_string(item)
        if label:
            normalized.append(label)
    return normalized


def _normalize_asset_owner_contact(payload: dict, existing_contact: dict | None = None) -> dict:
    existing = existing_contact or {}
    return {
        "phone": normalize_string(payload.get("asset_owner_phone"))
        if "asset_owner_phone" in payload
        else existing.get("phone"),
        "email": normalize_string(payload.get("asset_owner_email"))
        if "asset_owner_email" in payload
        else existing.get("email"),
        "address": normalize_string(payload.get("asset_owner_address"))
        if "asset_owner_address" in payload
        else existing.get("address"),
    }


def _ownership_summary_from_vehicle(vehicle_document: dict) -> dict:
    return {
        "operating_fleet_name": vehicle_document.get("operating_fleet_name") or DEFAULT_OPERATING_FLEET_NAME,
        "asset_owner_type": vehicle_document.get("asset_owner_type") or DEFAULT_ASSET_OWNER_TYPE,
        "asset_owner_name": vehicle_document.get("asset_owner_name") or DEFAULT_ASSET_OWNER_NAME,
        "ownership_start_date": vehicle_document.get("ownership_start_date"),
        "recovery_basis_type": vehicle_document.get("recovery_basis_type") or "Original Purchase Cost",
        "capital_basis_for_recovery": _safe_float(vehicle_document.get("capital_basis_for_recovery")),
    }


def _serialize_ownership_history_entry(document: dict) -> dict:
    return {
        "id": str(document.get("_id")) if document.get("_id") else str(document.get("id") or uuid4()),
        "vehicle_id": str(document.get("vehicle_id")) if document.get("vehicle_id") else None,
        "previous_owner": document.get("previous_owner"),
        "new_owner": document.get("new_owner"),
        "ownership_type": document.get("ownership_type"),
        "transfer_date": document.get("transfer_date"),
        "effective_date": document.get("effective_date"),
        "transfer_value": _safe_float(document.get("transfer_value")),
        "previous_recovery_balance": _safe_float(document.get("previous_recovery_balance")),
        "new_capital_basis": _safe_float(document.get("new_capital_basis")),
        "recovery_basis_type": document.get("recovery_basis_type"),
        "transfer_reason": document.get("transfer_reason"),
        "notes": document.get("notes"),
        "approved_by": str(document.get("approved_by")) if document.get("approved_by") else None,
        "current_record": bool(document.get("current_record")),
        "created_at": document.get("created_at").isoformat() if isinstance(document.get("created_at"), datetime) else document.get("created_at"),
    }


def _setup_cost_adjustment_total(vehicle_document: dict, custom_cost_total: float) -> float:
    purchase_cost = _safe_float(vehicle_document.get("purchase_cost"))
    setup_total = sum(_safe_float(vehicle_document.get(field)) for field in INVESTMENT_COST_FIELDS if field != "purchase_cost")
    return round(setup_total + custom_cost_total, 2), purchase_cost


def _default_recovery_basis_type(asset_owner_type: str | None, existing_value: str | None = None) -> str:
    if existing_value in ALLOWED_RECOVERY_BASIS_TYPES:
        return existing_value
    if asset_owner_type in {"Existing Company Asset", "Managed Third-Party Vehicle"}:
        return "Current Estimated Value"
    if asset_owner_type in {"Partner Vehicle", "Leased Vehicle"}:
        return "Custom Recovery Value"
    return "Original Purchase Cost"


def _calculate_capital_basis_for_vehicle(vehicle_document: dict, *, custom_cost_total: float) -> float:
    asset_owner_type = normalize_string(vehicle_document.get("asset_owner_type")) or DEFAULT_ASSET_OWNER_TYPE
    recovery_basis_type = normalize_string(vehicle_document.get("recovery_basis_type")) or _default_recovery_basis_type(asset_owner_type)
    capital_recovery_tracking_enabled = bool(vehicle_document.get("capital_recovery_tracking_enabled"))

    total_vehicle_investment = round(sum(_safe_float(vehicle_document.get(field)) for field in INVESTMENT_COST_FIELDS) + custom_cost_total, 2)
    setup_adjustments_total, purchase_cost = _setup_cost_adjustment_total(vehicle_document, custom_cost_total)
    original_purchase_price = _safe_float(vehicle_document.get("original_purchase_price"))
    current_estimated_value = _safe_float(vehicle_document.get("current_estimated_value"))
    custom_recovery_value = _safe_float(vehicle_document.get("custom_recovery_value"))
    manual_capital_basis = _safe_float(vehicle_document.get("capital_basis_for_recovery"))

    if asset_owner_type == "Leased Vehicle" and not capital_recovery_tracking_enabled:
        return 0.0

    if recovery_basis_type == "Current Estimated Value":
        return current_estimated_value
    if recovery_basis_type == "Custom Recovery Value":
        return custom_recovery_value
    if recovery_basis_type == "Transfer Value":
        return manual_capital_basis or custom_recovery_value

    if asset_owner_type == "Axelera Owned":
        return custom_recovery_value if custom_recovery_value > 0 else total_vehicle_investment
    if asset_owner_type == "Existing Company Asset":
        return round(current_estimated_value + setup_adjustments_total, 2)
    if asset_owner_type == "Managed Third-Party Vehicle":
        return custom_recovery_value if custom_recovery_value > 0 else current_estimated_value
    if asset_owner_type == "Investor-Funded Vehicle":
        return custom_recovery_value if custom_recovery_value > 0 else max(total_vehicle_investment, original_purchase_price)
    if asset_owner_type == "Partner Vehicle":
        return custom_recovery_value if custom_recovery_value > 0 else current_estimated_value
    return original_purchase_price if original_purchase_price > 0 else total_vehicle_investment


def _apply_vehicle_ownership_defaults(vehicle_document: dict) -> dict:
    vehicle_document["operating_fleet_name"] = vehicle_document.get("operating_fleet_name") or DEFAULT_OPERATING_FLEET_NAME
    vehicle_document["asset_owner_type"] = vehicle_document.get("asset_owner_type") or DEFAULT_ASSET_OWNER_TYPE
    vehicle_document["asset_owner_name"] = vehicle_document.get("asset_owner_name") or DEFAULT_ASSET_OWNER_NAME
    vehicle_document["asset_owner_contact"] = vehicle_document.get("asset_owner_contact") or {
        "phone": None,
        "email": None,
        "address": None,
    }
    vehicle_document["ownership_start_date"] = vehicle_document.get("ownership_start_date") or (
        vehicle_document.get("created_at").date().isoformat()
        if isinstance(vehicle_document.get("created_at"), datetime)
        else now_utc().date().isoformat()
    )
    vehicle_document["recovery_basis_type"] = _default_recovery_basis_type(
        vehicle_document.get("asset_owner_type"),
        vehicle_document.get("recovery_basis_type"),
    )
    vehicle_document["capital_recovery_tracking_enabled"] = bool(
        vehicle_document.get("capital_recovery_tracking_enabled", vehicle_document.get("asset_owner_type") != "Leased Vehicle")
    )
    return vehicle_document


def _build_current_ownership_history_record(vehicle_document: dict, *, approved_by: ObjectId | str | None = None, previous_owner: str | None = None, transfer_reason: str | None = None, notes: str | None = None, transfer_value: float | None = None, previous_recovery_balance: float | None = None) -> dict:
    return {
        "vehicle_id": vehicle_document["_id"],
        "previous_owner": previous_owner,
        "new_owner": vehicle_document.get("asset_owner_name") or DEFAULT_ASSET_OWNER_NAME,
        "ownership_type": vehicle_document.get("asset_owner_type") or DEFAULT_ASSET_OWNER_TYPE,
        "transfer_date": vehicle_document.get("ownership_start_date"),
        "effective_date": vehicle_document.get("ownership_start_date"),
        "transfer_value": transfer_value,
        "previous_recovery_balance": previous_recovery_balance,
        "new_capital_basis": _safe_float(vehicle_document.get("capital_basis_for_recovery")),
        "recovery_basis_type": vehicle_document.get("recovery_basis_type"),
        "transfer_reason": transfer_reason or "Initial ownership record",
        "notes": notes or vehicle_document.get("ownership_notes"),
        "approved_by": approved_by,
        "current_record": True,
        "created_at": now_utc(),
    }


def _ensure_vehicle_ownership_history(vehicle_document: dict, *, approved_by: ObjectId | str | None = None):
    existing = ownership_history_collection().find_one({"vehicle_id": vehicle_document["_id"], "current_record": True})
    if existing:
        return
    ownership_history_collection().insert_one(
        _build_current_ownership_history_record(vehicle_document, approved_by=approved_by)
    )


def list_vehicle_ownership_history(vehicle_id: str) -> list[dict]:
    vehicle = get_vehicle_document_by_id(vehicle_id)
    _apply_vehicle_ownership_defaults(vehicle)
    _ensure_vehicle_ownership_history(vehicle)
    documents = list(
        ownership_history_collection()
        .find({"vehicle_id": vehicle["_id"]})
        .sort([("effective_date", DESCENDING), ("created_at", DESCENDING)])
    )
    return [_serialize_ownership_history_entry(document) for document in documents]


def transfer_vehicle_ownership(vehicle_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to transfer vehicle ownership.", status_code=403)

    vehicle = get_vehicle_document_by_id(vehicle_id)
    _apply_vehicle_ownership_defaults(vehicle)
    existing_economics = _calculate_vehicle_economics(vehicle)
    previous_owner = vehicle.get("asset_owner_name") or DEFAULT_ASSET_OWNER_NAME
    previous_recovery_balance = _safe_float((existing_economics.get("recovery") or {}).get("remaining_balance"))

    new_owner_name = normalize_string(payload.get("asset_owner_name"))
    new_owner_type = normalize_string(payload.get("asset_owner_type"))
    if new_owner_type not in ALLOWED_ASSET_OWNER_TYPES:
        raise ApiError("Please choose a valid ownership type.", status_code=400)
    if not new_owner_name:
        raise ApiError("Please provide the new asset owner name.", status_code=400)

    transfer_date = normalize_string(payload.get("transfer_date"))
    effective_date = normalize_string(payload.get("effective_date"))
    if not transfer_date or not effective_date:
        raise ApiError("Please provide transfer date and effective date.", status_code=400)

    transfer_payload = {
        "asset_owner_type": new_owner_type,
        "asset_owner_name": new_owner_name,
        "asset_owner_phone": payload.get("asset_owner_phone"),
        "asset_owner_email": payload.get("asset_owner_email"),
        "asset_owner_address": payload.get("asset_owner_address"),
        "ownership_notes": normalize_string(payload.get("notes")),
        "ownership_start_date": effective_date,
        "recovery_basis_type": payload.get("recovery_basis_type"),
        "current_estimated_value": payload.get("current_estimated_value"),
        "custom_recovery_value": payload.get("custom_recovery_value"),
        "capital_recovery_tracking_enabled": payload.get("capital_recovery_tracking_enabled"),
    }
    normalized_transfer = normalize_vehicle_payload(
        transfer_payload,
        partial=True,
        vehicle_id=vehicle["_id"],
        existing_insurance_profile=vehicle.get("insurance_profile") or {},
        existing_asset_owner_contact=vehicle.get("asset_owner_contact") or {},
    )
    timestamp = now_utc()
    normalized_transfer["updated_at"] = timestamp
    normalized_transfer["updated_by"] = ObjectId(current_user_id) if ObjectId.is_valid(current_user_id) else current_user_id
    vehicles_collection().update_one({"_id": vehicle["_id"]}, {"$set": normalized_transfer})
    vehicle.update(normalized_transfer)
    vehicle["economics"] = _calculate_vehicle_economics(vehicle)
    vehicle["vehicle_cost_items"] = vehicle["economics"].get("vehicle_cost_items", [])

    ownership_history_collection().update_many(
        {"vehicle_id": vehicle["_id"], "current_record": True},
        {"$set": {"current_record": False}},
    )
    transfer_value = _safe_float(payload.get("transfer_value"))
    history_entry = _build_current_ownership_history_record(
        vehicle,
        approved_by=ObjectId(current_user_id) if ObjectId.is_valid(current_user_id) else current_user_id,
        previous_owner=previous_owner,
        transfer_reason=normalize_string(payload.get("reason")) or "Ownership transfer",
        notes=normalize_string(payload.get("notes")),
        transfer_value=transfer_value,
        previous_recovery_balance=previous_recovery_balance,
    )
    history_entry["transfer_date"] = transfer_date
    history_entry["effective_date"] = effective_date
    ownership_history_collection().insert_one(history_entry)
    return _filter_vehicle_for_role(vehicle, current_role=current_role)


def _build_insurance_profile(payload: dict, existing_profile: dict | None = None) -> dict | None:
    existing = existing_profile or {}
    insurance_fields = {
        "insurance_company",
        "policy_number",
        "insurance_type",
        "start_date",
        "expiry_date",
        "coverage_duration_months",
        "claims_officer_name",
        "claims_officer_phone",
        "claims_officer_email",
        "emergency_contact",
        "excess_amount",
        "covered_risks",
        "excluded_risks",
    }
    if not any(field in payload for field in insurance_fields):
        return None

    profile = {
        "insurance_company": normalize_string(payload.get("insurance_company"))
        if "insurance_company" in payload
        else existing.get("insurance_company"),
        "policy_number": normalize_string(payload.get("policy_number"))
        if "policy_number" in payload
        else existing.get("policy_number"),
        "insurance_type": normalize_string(payload.get("insurance_type"))
        if "insurance_type" in payload
        else existing.get("insurance_type"),
        "start_date": normalize_string(payload.get("start_date"))
        if "start_date" in payload
        else existing.get("start_date"),
        "expiry_date": normalize_string(payload.get("expiry_date"))
        if "expiry_date" in payload
        else existing.get("expiry_date"),
        "coverage_duration_months": validate_integer(
            payload.get("coverage_duration_months"),
            "coverage_duration_months",
            positive=True,
        )
        if "coverage_duration_months" in payload
        else existing.get("coverage_duration_months"),
        "claims_officer_name": normalize_string(payload.get("claims_officer_name"))
        if "claims_officer_name" in payload
        else existing.get("claims_officer_name"),
        "claims_officer_phone": normalize_string(payload.get("claims_officer_phone"))
        if "claims_officer_phone" in payload
        else existing.get("claims_officer_phone"),
        "claims_officer_email": normalize_string(payload.get("claims_officer_email"))
        if "claims_officer_email" in payload
        else existing.get("claims_officer_email"),
        "emergency_contact": normalize_string(payload.get("emergency_contact"))
        if "emergency_contact" in payload
        else existing.get("emergency_contact"),
        "excess_amount": validate_numeric(payload.get("excess_amount"), "excess_amount")
        if "excess_amount" in payload
        else existing.get("excess_amount"),
        "covered_risks": _normalize_risk_list(payload.get("covered_risks"))
        if "covered_risks" in payload
        else existing.get("covered_risks") or [],
        "excluded_risks": _normalize_risk_list(payload.get("excluded_risks"))
        if "excluded_risks" in payload
        else existing.get("excluded_risks") or [],
    }

    insurance_type = profile.get("insurance_type")
    if insurance_type is not None and insurance_type not in ALLOWED_INSURANCE_TYPES:
        raise ApiError("insurance_type must be Third Party or Comprehensive.", status_code=400)
    if insurance_type == "Third Party":
        profile["excess_amount"] = None
    if not any(profile.get(key) not in (None, [], "") for key in profile):
        return {}
    return profile


def _parse_iso_date(value):
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _count_distinct_collection_weeks(collections: list[dict]) -> int:
    weeks = set()
    for item in collections:
        week_start = item.get("week_start")
        if week_start:
            weeks.add(str(week_start))
            continue
        collection_date = _parse_iso_date(item.get("collection_date"))
        if collection_date:
            iso_year, iso_week, _ = collection_date.isocalendar()
            weeks.add(f"{iso_year}-W{iso_week:02d}")
    return len(weeks)


def _matches_company_expense(expense_document: dict) -> bool:
    category = _normalize_text(expense_document.get("expense_category"))
    if category in {"fuel", "driver_advance", "office", "car_wash"}:
        return False
    return category in {"repairs", "servicing", "insurance", "roadworthy", "tyres", "battery", "other"}


def _matches_compliance_renewal_expense(expense_document: dict) -> bool:
    category = _normalize_text(expense_document.get("expense_category"))
    if category in {"insurance", "roadworthy"}:
        return True
    title = " ".join(
        filter(
            None,
            [
                _normalize_text(expense_document.get("expense_title")),
                _normalize_text(expense_document.get("notes")),
            ],
        )
    )
    return any(keyword in title for keyword in {"permit", "license", "roadworthy", "insurance", "ama"})


def _matches_repair_maintenance_job(job_document: dict) -> bool:
    return _normalize_text(job_document.get("maintenance_type")) in {
        "repair",
        "body_repair",
        "electrical_repair",
        "engine_service",
        "accident_repair",
        "tyre_change",
        "battery_replacement",
        "gearbox_work",
    }


def _restrict_admin_sensitive_payload(payload: dict, *, current_role: str):
    if current_role != "admin":
        return
    touched_sensitive_fields = [
        field_name
        for field_name, permission_key in SENSITIVE_ADMIN_PERMISSION_FIELDS.items()
        if field_name in payload and permission_key == "view_vehicle_investment"
    ]
    if touched_sensitive_fields and not _can_admin_access("view_vehicle_investment"):
        raise ApiError(
            "Owner permissions are required to manage vehicle investment fields.",
            status_code=403,
        )


def _calculate_vehicle_economics(vehicle_document: dict) -> dict:
    _apply_vehicle_ownership_defaults(vehicle_document)
    vehicle_id = vehicle_document["_id"]
    today = now_utc().date()
    month_start = date(today.year, today.month, 1)
    quarter_month = ((today.month - 1) // 3) * 3 + 1
    quarter_start = date(today.year, quarter_month, 1)
    year_start = date(today.year, 1, 1)

    custom_cost_items = list(vehicle_cost_items_collection().find({"vehicle_id": vehicle_id}))
    setup_investment = sum(_safe_float(vehicle_document.get(field)) for field in INVESTMENT_COST_FIELDS)
    custom_cost_total = sum(_safe_float(item.get("amount")) for item in custom_cost_items)
    total_vehicle_investment = round(setup_investment + custom_cost_total, 2)
    capital_basis_for_recovery = round(
        _calculate_capital_basis_for_vehicle(vehicle_document, custom_cost_total=custom_cost_total),
        2,
    )
    vehicle_document["capital_basis_for_recovery"] = capital_basis_for_recovery

    approved_collections = list(collections_collection().find({"vehicle_id": vehicle_id, "status": "approved"}))
    gross_revenue = round(sum(_safe_float(item.get("amount")) for item in approved_collections), 2)
    amount_recovered = gross_revenue
    remaining_balance = round(max(capital_basis_for_recovery - amount_recovered, 0), 2)
    recovery_percentage = round((amount_recovered / capital_basis_for_recovery) * 100, 2) if capital_basis_for_recovery > 0 else 0.0

    collection_week_count = _count_distinct_collection_weeks(approved_collections)
    weekly_target = _safe_float(vehicle_document.get("default_weekly_target"))
    weekly_average = (
        round(gross_revenue / collection_week_count, 2)
        if collection_week_count > 0
        else 0.0
    )
    break_even_weekly_rate = weekly_target if weekly_target > 0 else weekly_average
    estimated_recovery_weeks = round(remaining_balance / weekly_average, 1) if weekly_average > 0 and remaining_balance > 0 else 0.0
    estimated_recovery_months = round(estimated_recovery_weeks / 4.345, 1) if estimated_recovery_weeks else 0.0
    estimated_break_even_weeks = (
        round(remaining_balance / break_even_weekly_rate, 1)
        if break_even_weekly_rate > 0 and remaining_balance > 0
        else 0.0
    )
    estimated_recovery_weeks = estimated_break_even_weeks
    estimated_recovery_months = round(estimated_break_even_weeks / 4.345, 1) if estimated_break_even_weeks else 0.0
    estimated_break_even_date = (
        today + timedelta(days=int(estimated_break_even_weeks * 7))
        if estimated_break_even_weeks
        else None
    )
    if amount_recovered <= 0:
        recovery_status = "Not Started"
    elif amount_recovered < capital_basis_for_recovery:
        recovery_status = "Recovering"
    else:
        recovery_status = "Profit Generating"

    approved_fuel_logs = list(fuel_logs_collection().find({"vehicle_id": vehicle_id, "status": "approved"}))
    approved_expenses = list(expenses_collection().find({"vehicle_id": vehicle_id, "status": {"$in": ["approved", "paid"]}}))
    maintenance_documents = list(maintenance_jobs_collection().find({"vehicle_id": vehicle_id}))
    compliance_records = list(compliance_records_collection().find({"vehicle_id": vehicle_id}))

    include_fuel_in_profitability = should_include_fuel_in_profitability()
    fuel_cost = round(sum(_safe_float(item.get("amount")) for item in approved_fuel_logs), 2)
    maintenance_cost = round(
        sum(
            _safe_float(item.get("actual_cost") or item.get("estimated_cost"))
            for item in maintenance_documents
        ),
        2,
    )
    company_expenses = [item for item in approved_expenses if _matches_company_expense(item)]
    expense_cost = round(sum(_safe_float(item.get("amount")) for item in company_expenses), 2)
    repair_cost = round(
        sum(
            _safe_float(item.get("actual_cost") or item.get("estimated_cost"))
            for item in maintenance_documents
            if _matches_repair_maintenance_job(item)
        ),
        2,
    )
    compliance_renewal_cost = round(
        sum(
            _safe_float(item.get("amount"))
            for item in company_expenses
            if _matches_compliance_renewal_expense(item)
        ),
        2,
    )
    company_vehicle_costs = round(maintenance_cost + expense_cost, 2)
    profitability_operating_costs = round(
        company_vehicle_costs + (fuel_cost if include_fuel_in_profitability else 0),
        2,
    )
    net_profit = round(gross_revenue - profitability_operating_costs, 2)
    profit_margin = round((net_profit / gross_revenue) * 100, 2) if gross_revenue > 0 else 0.0
    roi = round((net_profit / capital_basis_for_recovery) * 100, 2) if capital_basis_for_recovery > 0 else 0.0

    rides = list(rides_collection().find({"vehicle_id": vehicle_id}))
    trips_today = len([item for item in rides if item.get("trip_date") == today.isoformat()])
    trips_this_month = len([item for item in rides if isinstance(item.get("trip_date"), str) and item.get("trip_date", "").startswith(f"{today.year}-{today.month:02d}")])
    active_days_set = {item.get("trip_date") for item in rides if item.get("trip_date")}
    active_days = len(active_days_set)
    idle_days = max(_days_in_month(today) - len({day for day in active_days_set if isinstance(day, str) and day.startswith(f"{today.year}-{today.month:02d}")}), 0)
    utilization_percentage = round((len({day for day in active_days_set if isinstance(day, str) and day.startswith(f"{today.year}-{today.month:02d}")}) / _days_in_month(today)) * 100, 2) if _days_in_month(today) else 0.0

    downtime_dates = set()
    for job in maintenance_documents:
        start_raw = job.get("start_date")
        end_raw = job.get("completion_date") or today.isoformat()
        try:
            start_date = datetime.fromisoformat(start_raw).date() if start_raw else None
            end_date = datetime.fromisoformat(end_raw).date() if end_raw else None
        except ValueError:
            start_date = None
            end_date = None
        if start_date and end_date and start_date <= end_date:
            span = min((end_date - start_date).days, 60)
            for offset in range(span + 1):
                downtime_dates.add((start_date + timedelta(days=offset)).isoformat())
    downtime_days = len([day for day in downtime_dates if day.startswith(f"{today.year}-{today.month:02d}")])

    fault_documents = list(faults_collection().find({"vehicle_id": vehicle_id}))
    critical_faults = len([item for item in fault_documents if (item.get("severity") or "").lower() == "critical"])
    overdue_maintenance = len([item for item in (vehicle_document.get("preventive_summaries") or []) if item.get("status") == "overdue"])
    active_compliance_count = len([item for item in compliance_records if (item.get("status") or "").lower() in {"active", "renewed"}])
    expired_compliance_count = len([item for item in compliance_records if (item.get("status") or "").lower() == "expired"])
    health_score = max(0.0, min(100.0, round(100 - (critical_faults * 8) - (len(fault_documents) * 2) - (downtime_days * 1.5) - (overdue_maintenance * 6) - (expired_compliance_count * 5) + min(utilization_percentage, 30) * 0.3, 2)))
    if health_score >= 85:
        health_category = "Excellent"
    elif health_score >= 70:
        health_category = "Good"
    elif health_score >= 50:
        health_category = "Fair"
    else:
        health_category = "Poor"

    def _period_cost_total(start_date: date):
        start_key = start_date.isoformat()
        fuel_total = sum(
            _safe_float(item.get("amount"))
            for item in approved_fuel_logs
            if (item.get("fuel_date") or "") >= start_key
        )
        expense_total = sum(
            _safe_float(item.get("amount"))
            for item in company_expenses
            if (item.get("expense_date") or "") >= start_key
        )
        maintenance_total = sum(
            _safe_float(item.get("actual_cost") or item.get("estimated_cost"))
            for item in maintenance_documents
            if (item.get("start_date") or "") >= start_key
        )
        return round(
            maintenance_total
            + expense_total
            + (fuel_total if include_fuel_in_profitability else 0),
            2,
        )

    return {
        "investment": {
            "purchase_cost": _safe_float(vehicle_document.get("purchase_cost")),
            "shipping_cost": _safe_float(vehicle_document.get("shipping_cost")),
            "clearing_cost": _safe_float(vehicle_document.get("clearing_cost")),
            "insurance_cost": _safe_float(vehicle_document.get("insurance_cost")),
            "roadworthy_cost": _safe_float(vehicle_document.get("roadworthy_cost")),
            "ama_permit_cost": _safe_float(vehicle_document.get("ama_permit_cost")),
            "vehicle_license_cost": _safe_float(vehicle_document.get("vehicle_license_cost")),
            "tracker_cost": _safe_float(vehicle_document.get("tracker_cost")),
            "branding_cost": _safe_float(vehicle_document.get("branding_cost")),
            "initial_repairs_cost": _safe_float(vehicle_document.get("initial_repairs_cost")),
            "registration_cost": _safe_float(vehicle_document.get("registration_cost")),
            "other_setup_cost": _safe_float(vehicle_document.get("other_setup_cost")),
            "custom_cost_total": custom_cost_total,
            "total_vehicle_investment": total_vehicle_investment,
            "original_purchase_price": _safe_float(vehicle_document.get("original_purchase_price")),
            "original_purchase_date": vehicle_document.get("original_purchase_date"),
            "current_estimated_value": _safe_float(vehicle_document.get("current_estimated_value")),
            "custom_recovery_value": _safe_float(vehicle_document.get("custom_recovery_value")),
            "recovery_basis_type": vehicle_document.get("recovery_basis_type"),
            "capital_basis_for_recovery": capital_basis_for_recovery,
        },
        "recovery": {
            "recovery_basis_type": vehicle_document.get("recovery_basis_type"),
            "capital_basis_for_recovery": capital_basis_for_recovery,
            "amount_recovered": amount_recovered,
            "remaining_balance": remaining_balance,
            "recovery_percentage": recovery_percentage,
            "estimated_recovery_weeks": estimated_recovery_weeks,
            "estimated_recovery_months": estimated_recovery_months,
            "estimated_recovery_date": estimated_break_even_date.isoformat() if estimated_break_even_date else None,
            "estimated_break_even_date": estimated_break_even_date.isoformat() if estimated_break_even_date else None,
            "status": recovery_status,
            "recovery_status": recovery_status,
        },
        "operating_costs": {
            "fuel_cost": fuel_cost,
            "maintenance_cost": maintenance_cost,
            "repair_cost": repair_cost,
            "expense_cost": expense_cost,
            "compliance_renewal_cost": compliance_renewal_cost,
            "company_vehicle_costs": company_vehicle_costs,
            "include_fuel_in_profitability": include_fuel_in_profitability,
            "monthly": _period_cost_total(month_start),
            "quarterly": _period_cost_total(quarter_start),
            "annual": _period_cost_total(year_start),
            "lifetime": profitability_operating_costs,
        },
        "profitability": {
            "gross_revenue": gross_revenue,
            "operating_costs": profitability_operating_costs,
            "company_vehicle_costs": company_vehicle_costs,
            "net_profit": net_profit,
            "profit_margin": profit_margin,
            "roi": roi,
            "capital_basis_for_recovery": capital_basis_for_recovery,
        },
        "fuel_analytics": {
            "fuel_by_vehicle": fuel_cost,
            "fuel_by_driver": [
                {"driver_id": str(driver_id), "amount": round(total_amount, 2)}
                for driver_id, total_amount in sorted(
                    defaultdict(
                        float,
                        {
                            str(item.get("driver_id")): sum(
                                _safe_float(log.get("amount"))
                                for log in approved_fuel_logs
                                if str(log.get("driver_id")) == str(item.get("driver_id"))
                            )
                            for item in approved_fuel_logs
                            if item.get("driver_id")
                        },
                    ).items(),
                    key=lambda entry: entry[1],
                    reverse=True,
                )
            ],
            "fuel_by_station": [
                {"station_id": str(station_id), "amount": round(total_amount, 2)}
                for station_id, total_amount in sorted(
                    defaultdict(
                        float,
                        {
                            str(item.get("fuel_station_id")): sum(
                                _safe_float(log.get("amount"))
                                for log in approved_fuel_logs
                                if str(log.get("fuel_station_id")) == str(item.get("fuel_station_id"))
                            )
                            for item in approved_fuel_logs
                            if item.get("fuel_station_id")
                        },
                    ).items(),
                    key=lambda entry: entry[1],
                    reverse=True,
                )
            ],
            "monthly_trend": [
                {"month": month, "amount": round(amount, 2)}
                for month, amount in sorted(
                    defaultdict(
                        float,
                        {
                            str(item.get("fuel_date"))[:7]: sum(
                                _safe_float(log.get("amount"))
                                for log in approved_fuel_logs
                                if str(log.get("fuel_date"))[:7] == str(item.get("fuel_date"))[:7]
                            )
                            for item in approved_fuel_logs
                            if item.get("fuel_date")
                        },
                    ).items()
                )
            ],
        },
        "performance": {
            "trips_today": trips_today,
            "trips_this_month": trips_this_month,
            "utilization_percentage": utilization_percentage,
            "active_days": active_days,
            "idle_days": idle_days,
            "downtime_days": downtime_days,
        },
        "health": {
            "score": health_score,
            "category": health_category,
            "maintenance_compliance_count": max(active_compliance_count - expired_compliance_count, 0),
            "fault_frequency": len(fault_documents),
            "critical_faults": critical_faults,
        },
        "vehicle_cost_items": [_serialize_cost_item(item) for item in custom_cost_items],
    }


def _filter_vehicle_for_role(vehicle_document: dict, *, current_role: str) -> dict:
    economics = vehicle_document.get("economics") or {}
    _apply_vehicle_ownership_defaults(vehicle_document)
    include_sensitive = current_role == "owner"
    serialized = serialize_vehicle(vehicle_document, include_sensitive=include_sensitive)
    serialized["assigned_driver_details"] = vehicle_document.get("assigned_driver_details")
    if current_role == "owner":
        serialized["ownership_summary"] = _ownership_summary_from_vehicle(vehicle_document)
        return serialized
    if current_role == "admin":
        permissions = get_admin_role_permissions()
        filtered_economics = {
            "operating_costs": economics.get("operating_costs"),
            "fuel_analytics": economics.get("fuel_analytics"),
            "performance": economics.get("performance"),
            "health": economics.get("health"),
            "recovery": {},
            "investment": {},
            "profitability": {},
        }
        if permissions.get("view_vehicle_investment"):
            filtered_economics["investment"] = economics.get("investment", {})
            serialized["purchase_cost"] = vehicle_document.get("purchase_cost")
        if permissions.get("view_vehicle_recovery"):
            filtered_economics["recovery"] = economics.get("recovery", {})
        if permissions.get("view_profitability"):
            filtered_economics["profitability"] = economics.get("profitability", {})
        serialized["economics"] = filtered_economics
        serialized["ownership_summary"] = _ownership_summary_from_vehicle(vehicle_document)
        if not permissions.get("manage_vehicle_cost_items"):
            serialized["vehicle_cost_items"] = []
        return serialized
    serialized["economics"] = {}
    serialized["vehicle_cost_items"] = []
    return serialized


def normalize_vehicle_payload(
    payload: dict,
    *,
    partial: bool = False,
    vehicle_id: ObjectId | None = None,
    existing_insurance_profile: dict | None = None,
    existing_asset_owner_contact: dict | None = None,
) -> dict:
    normalized_data = {}
    insurance_profile = _build_insurance_profile(payload, existing_profile=existing_insurance_profile)
    asset_owner_contact = _normalize_asset_owner_contact(payload, existing_asset_owner_contact)

    string_fields = {
        "registration_number": normalize_registration_number,
        "vehicle_type": normalize_string,
        "make": normalize_string,
        "model": normalize_string,
        "color": normalize_string,
        "transmission": normalize_string,
        "fuel_type": normalize_string,
        "chassis_number": normalize_string,
        "engine_number": normalize_string,
        "insurance_expiry": normalize_string,
        "roadworthy_expiry": normalize_string,
        "status": normalize_string,
        "operating_fleet_name": normalize_string,
        "asset_owner_type": normalize_string,
        "asset_owner_name": normalize_string,
        "ownership_notes": normalize_string,
        "ownership_start_date": normalize_string,
        "recovery_basis_type": normalize_string,
        "original_purchase_date": normalize_string,
    }

    for field_name, normalizer in string_fields.items():
        if field_name in payload:
            normalized_data[field_name] = normalizer(payload.get(field_name))

    if "year" in payload:
        year = payload.get("year")
        if isinstance(year, bool) or not isinstance(year, int):
            raise ApiError("year must be an integer.", status_code=400)
        normalized_data["year"] = year

    if "default_weekly_target" in payload:
        normalized_data["default_weekly_target"] = validate_numeric(
            payload.get("default_weekly_target"),
            "default_weekly_target",
            positive=True,
        )
    if "default_daily_target" in payload:
        normalized_data["default_daily_target"] = validate_numeric(
            payload.get("default_daily_target"),
            "default_daily_target",
            positive=True,
        )
    if "purchase_cost" in payload:
        normalized_data["purchase_cost"] = validate_numeric(payload.get("purchase_cost"), "purchase_cost")
    if "shipping_cost" in payload:
        normalized_data["shipping_cost"] = validate_numeric(payload.get("shipping_cost"), "shipping_cost")
    if "clearing_cost" in payload:
        normalized_data["clearing_cost"] = validate_numeric(payload.get("clearing_cost"), "clearing_cost")
    if "insurance_cost" in payload:
        normalized_data["insurance_cost"] = validate_numeric(payload.get("insurance_cost"), "insurance_cost")
    if "roadworthy_cost" in payload:
        normalized_data["roadworthy_cost"] = validate_numeric(
            payload.get("roadworthy_cost"),
            "roadworthy_cost",
        )
    if "ama_permit_cost" in payload:
        normalized_data["ama_permit_cost"] = validate_numeric(payload.get("ama_permit_cost"), "ama_permit_cost")
    if "vehicle_license_cost" in payload:
        normalized_data["vehicle_license_cost"] = validate_numeric(payload.get("vehicle_license_cost"), "vehicle_license_cost")
    if "tracker_cost" in payload:
        normalized_data["tracker_cost"] = validate_numeric(payload.get("tracker_cost"), "tracker_cost")
    if "branding_cost" in payload:
        normalized_data["branding_cost"] = validate_numeric(payload.get("branding_cost"), "branding_cost")
    if "initial_repairs_cost" in payload:
        normalized_data["initial_repairs_cost"] = validate_numeric(payload.get("initial_repairs_cost"), "initial_repairs_cost")
    if "registration_cost" in payload:
        normalized_data["registration_cost"] = validate_numeric(payload.get("registration_cost"), "registration_cost")
    if "other_setup_cost" in payload:
        normalized_data["other_setup_cost"] = validate_numeric(payload.get("other_setup_cost"), "other_setup_cost")
    if "original_purchase_price" in payload:
        normalized_data["original_purchase_price"] = validate_numeric(payload.get("original_purchase_price"), "original_purchase_price")
    if "current_estimated_value" in payload:
        normalized_data["current_estimated_value"] = validate_numeric(payload.get("current_estimated_value"), "current_estimated_value")
    if "custom_recovery_value" in payload:
        normalized_data["custom_recovery_value"] = validate_numeric(payload.get("custom_recovery_value"), "custom_recovery_value")
    if "capital_basis_for_recovery" in payload:
        normalized_data["capital_basis_for_recovery"] = validate_numeric(payload.get("capital_basis_for_recovery"), "capital_basis_for_recovery")
    if "capital_recovery_tracking_enabled" in payload:
        normalized_data["capital_recovery_tracking_enabled"] = validate_boolean(
            payload.get("capital_recovery_tracking_enabled"),
            "capital_recovery_tracking_enabled",
        )

    if "assigned_driver_id" in payload:
        assigned_driver_id = validate_reference_id(payload.get("assigned_driver_id"), "assigned_driver_id")
        normalized_data["assigned_driver_id"] = validate_assigned_driver(
            assigned_driver_id,
            vehicle_id=vehicle_id,
        )

    required_fields = {
        "registration_number",
        "vehicle_type",
        "make",
        "model",
        "year",
        "transmission",
        "fuel_type",
        "default_weekly_target",
        "default_daily_target",
    }
    if not partial:
        missing_fields = [field for field in required_fields if normalized_data.get(field) is None]
        if missing_fields:
            raise ApiError(f"Missing required vehicle fields: {', '.join(sorted(missing_fields))}.", status_code=400)

    vehicle_type = normalized_data.get("vehicle_type")
    if vehicle_type is not None and vehicle_type not in ALLOWED_VEHICLE_TYPES:
        raise ApiError("Invalid vehicle type.", status_code=400)

    transmission = normalized_data.get("transmission")
    if transmission is not None and transmission not in ALLOWED_TRANSMISSIONS:
        raise ApiError("Invalid transmission.", status_code=400)

    fuel_type = normalized_data.get("fuel_type")
    if fuel_type is not None and fuel_type not in ALLOWED_FUEL_TYPES:
        raise ApiError("Invalid fuel type.", status_code=400)

    vehicle_status = normalized_data.get("status")
    if vehicle_status is not None and vehicle_status not in ALLOWED_VEHICLE_STATUSES:
        raise ApiError("Invalid vehicle status.", status_code=400)

    asset_owner_type = normalized_data.get("asset_owner_type")
    if asset_owner_type is not None and asset_owner_type not in ALLOWED_ASSET_OWNER_TYPES:
        raise ApiError("Please choose a valid asset owner type.", status_code=400)

    recovery_basis_type = normalized_data.get("recovery_basis_type")
    if recovery_basis_type is not None and recovery_basis_type not in ALLOWED_RECOVERY_BASIS_TYPES:
        raise ApiError("Please choose a valid recovery basis type.", status_code=400)

    if any(value is not None for value in asset_owner_contact.values()):
        normalized_data["asset_owner_contact"] = asset_owner_contact

    if insurance_profile is not None:
        normalized_data["insurance_profile"] = insurance_profile
        normalized_data["insurance_expiry"] = insurance_profile.get("expiry_date") or normalized_data.get("insurance_expiry")

    if not partial:
        normalized_data["operating_fleet_name"] = normalized_data.get("operating_fleet_name") or DEFAULT_OPERATING_FLEET_NAME
        normalized_data["asset_owner_type"] = normalized_data.get("asset_owner_type") or DEFAULT_ASSET_OWNER_TYPE
        normalized_data["asset_owner_name"] = normalized_data.get("asset_owner_name") or DEFAULT_ASSET_OWNER_NAME
        normalized_data["ownership_start_date"] = normalized_data.get("ownership_start_date") or now_utc().date().isoformat()
        normalized_data["recovery_basis_type"] = _default_recovery_basis_type(normalized_data.get("asset_owner_type"))
        normalized_data["capital_recovery_tracking_enabled"] = (
            normalized_data.get("capital_recovery_tracking_enabled")
            if normalized_data.get("capital_recovery_tracking_enabled") is not None
            else normalized_data.get("asset_owner_type") != "Leased Vehicle"
        )

    basis_type_to_validate = normalized_data.get("recovery_basis_type")
    if basis_type_to_validate == "Current Estimated Value" and "current_estimated_value" in payload:
        if normalized_data.get("current_estimated_value") in (None, 0.0):
            raise ApiError("Current estimated value is required when using Current Estimated Value.", status_code=400)
    if basis_type_to_validate == "Custom Recovery Value" and "custom_recovery_value" in payload:
        if normalized_data.get("custom_recovery_value") in (None, 0.0):
            raise ApiError("Custom recovery value is required when using Custom Recovery Value.", status_code=400)

    if not partial and "status" not in normalized_data:
        normalized_data["status"] = "available"

    return normalized_data


def ensure_unique_vehicle_fields(data: dict, *, exclude_vehicle_id: ObjectId | None = None):
    unique_fields = {
        "registration_number": data.get("registration_number"),
        "chassis_number": data.get("chassis_number"),
        "engine_number": data.get("engine_number"),
    }

    for field_name, field_value in unique_fields.items():
        if not field_value:
            continue

        query = {field_name: field_value}
        if exclude_vehicle_id is not None:
            query["_id"] = {"$ne": exclude_vehicle_id}

        existing_vehicle = vehicles_collection().find_one(query)
        if existing_vehicle:
            raise ApiError(f"A vehicle with this {field_name} already exists.", status_code=409)


def sync_vehicle_assignment(
    *,
    vehicle_id: ObjectId,
    previous_driver_id: ObjectId | None,
    new_driver_id: ObjectId | None,
):
    if previous_driver_id and previous_driver_id != new_driver_id:
        users_collection().update_one(
            {
                "_id": previous_driver_id,
                "driver_profile.assigned_vehicle_id": vehicle_id,
            },
            {"$set": {"driver_profile.assigned_vehicle_id": None}},
        )

    if new_driver_id:
        users_collection().update_one(
            {"_id": new_driver_id},
            {"$set": {"driver_profile.assigned_vehicle_id": vehicle_id}},
        )


def list_vehicles(*, current_role: str) -> list[dict]:
    del current_role
    query_started_at = perf_counter()
    vehicle_documents = list(
        vehicles_collection()
        .find(
            {},
            {
                "registration_number": 1,
                "vehicle_type": 1,
                "make": 1,
                "model": 1,
                "year": 1,
                "color": 1,
                "transmission": 1,
                "fuel_type": 1,
                "insurance_expiry": 1,
                "insurance_profile": 1,
                "roadworthy_expiry": 1,
                "default_weekly_target": 1,
                "default_daily_target": 1,
                "status": 1,
                "assigned_driver_id": 1,
                "created_by": 1,
                "created_at": 1,
                "updated_at": 1,
            },
        )
        .sort("created_at", ASCENDING)
    )
    assigned_driver_map = _build_assigned_driver_map(vehicle_documents)
    serialized = []
    for vehicle_document in vehicle_documents:
        _apply_vehicle_ownership_defaults(vehicle_document)
        assigned_driver_object_id = _driver_object_id_from_reference(vehicle_document.get("assigned_driver_id"))
        serialized.append(
            _serialize_vehicle_list_item(
                vehicle_document,
                assigned_driver_details=assigned_driver_map.get(str(assigned_driver_object_id)) if assigned_driver_object_id else None,
            )
        )
    print(
        f"[Flux Performance] list_vehicles returned {len(serialized)} lightweight records in "
        f"{round((perf_counter() - query_started_at) * 1000, 2)}ms"
    )
    return serialized


def get_vehicle_by_id(vehicle_id: str, *, current_role: str, include_economics: bool = True) -> dict:
    query_started_at = perf_counter()
    print(
        f"[Flux Performance] vehicle details query started vehicle_id={vehicle_id} "
        f"include_economics={include_economics}"
    )
    vehicle = get_vehicle_document_by_id_with_projection(vehicle_id, _vehicle_detail_projection())
    _apply_vehicle_ownership_defaults(vehicle)
    _ensure_vehicle_ownership_history(vehicle)
    if vehicle.get("current_odometer") is None:
        vehicle["current_odometer"] = _extract_vehicle_current_odometer(vehicle["_id"])
    assigned_driver_object_id = _driver_object_id_from_reference(vehicle.get("assigned_driver_id"))
    vehicle["assigned_driver_details"] = (
        _serialize_assigned_driver_details(users_collection().find_one({"_id": assigned_driver_object_id}))
        if assigned_driver_object_id
        else None
    )
    print(
        f"[Flux Performance] vehicle details query completed vehicle_id={vehicle_id} "
        f"durationMs={round((perf_counter() - query_started_at) * 1000, 2)}"
    )
    if include_economics:
        vehicle["economics"] = _calculate_vehicle_economics(vehicle)
        vehicle["vehicle_cost_items"] = vehicle["economics"].get("vehicle_cost_items", [])
    else:
        vehicle["economics"] = {}
        vehicle["vehicle_cost_items"] = []
    if current_role == "owner":
        vehicle["ownership_history"] = list_vehicle_ownership_history(vehicle_id)
    print(
        f"[Flux Performance] get_vehicle_by_id include_economics={include_economics} completed in "
        f"{round((perf_counter() - query_started_at) * 1000, 2)}ms for vehicle {vehicle_id}"
    )
    return _filter_vehicle_for_role(vehicle, current_role=current_role)


def get_vehicle_economics_by_id(vehicle_id: str, *, current_role: str) -> dict:
    query_started_at = perf_counter()
    print(f"[Flux Performance] vehicle economics database query start vehicle_id={vehicle_id}")
    vehicle = get_vehicle_document_by_id_with_projection(vehicle_id, _vehicle_detail_projection())
    _apply_vehicle_ownership_defaults(vehicle)
    _ensure_vehicle_ownership_history(vehicle)
    if vehicle.get("current_odometer") is None:
        vehicle["current_odometer"] = _extract_vehicle_current_odometer(vehicle["_id"])
    print(
        f"[Flux Performance] vehicle economics database query end vehicle_id={vehicle_id} "
        f"durationMs={round((perf_counter() - query_started_at) * 1000, 2)}"
    )
    vehicle["economics"] = _calculate_vehicle_economics(vehicle)
    vehicle["vehicle_cost_items"] = vehicle["economics"].get("vehicle_cost_items", [])
    filtered_vehicle = _filter_vehicle_for_role(vehicle, current_role=current_role)
    print(
        f"[Flux Performance] get_vehicle_economics_by_id completed in "
        f"{round((perf_counter() - query_started_at) * 1000, 2)}ms for vehicle {vehicle_id}"
    )
    return {
        "economics": filtered_vehicle.get("economics") or {},
        "vehicle_cost_items": filtered_vehicle.get("vehicle_cost_items") or [],
        "operating_fleet_name": filtered_vehicle.get("operating_fleet_name"),
        "asset_owner_type": filtered_vehicle.get("asset_owner_type"),
        "asset_owner_name": filtered_vehicle.get("asset_owner_name"),
        "ownership_summary": filtered_vehicle.get("ownership_summary"),
        "purchase_cost": filtered_vehicle.get("purchase_cost"),
        "shipping_cost": filtered_vehicle.get("shipping_cost"),
        "clearing_cost": filtered_vehicle.get("clearing_cost"),
        "insurance_cost": filtered_vehicle.get("insurance_cost"),
        "roadworthy_cost": filtered_vehicle.get("roadworthy_cost"),
        "ama_permit_cost": filtered_vehicle.get("ama_permit_cost"),
        "vehicle_license_cost": filtered_vehicle.get("vehicle_license_cost"),
        "tracker_cost": filtered_vehicle.get("tracker_cost"),
        "branding_cost": filtered_vehicle.get("branding_cost"),
        "initial_repairs_cost": filtered_vehicle.get("initial_repairs_cost"),
        "registration_cost": filtered_vehicle.get("registration_cost"),
        "other_setup_cost": filtered_vehicle.get("other_setup_cost"),
        "original_purchase_price": filtered_vehicle.get("original_purchase_price"),
        "original_purchase_date": filtered_vehicle.get("original_purchase_date"),
        "current_estimated_value": filtered_vehicle.get("current_estimated_value"),
        "custom_recovery_value": filtered_vehicle.get("custom_recovery_value"),
        "capital_basis_for_recovery": filtered_vehicle.get("capital_basis_for_recovery"),
        "recovery_basis_type": filtered_vehicle.get("recovery_basis_type"),
    }


def create_vehicle(payload: dict, current_user_id: str, *, current_role: str) -> dict:
    if not ObjectId.is_valid(current_user_id):
        raise ApiError("Invalid user identity.", status_code=400)

    _restrict_admin_sensitive_payload(payload, current_role=current_role)
    normalized_data = normalize_vehicle_payload(payload, partial=False)
    ensure_unique_vehicle_fields(normalized_data)

    timestamp = now_utc()
    vehicle_document = {
        **normalized_data,
        "created_by": ObjectId(current_user_id),
        "updated_by": ObjectId(current_user_id),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    _apply_vehicle_ownership_defaults(vehicle_document)

    try:
        insert_result = vehicles_collection().insert_one(vehicle_document)
    except DuplicateKeyError:
        raise ApiError("A vehicle with one of the unique fields already exists.", status_code=409) from None

    vehicle_document["_id"] = insert_result.inserted_id
    sync_vehicle_assignment(
        vehicle_id=insert_result.inserted_id,
        previous_driver_id=None,
        new_driver_id=vehicle_document.get("assigned_driver_id"),
    )
    _ensure_vehicle_ownership_history(vehicle_document, approved_by=ObjectId(current_user_id))
    generate_default_preventive_schedules_for_vehicle(insert_result.inserted_id, ObjectId(current_user_id))
    vehicle_document["economics"] = _calculate_vehicle_economics(vehicle_document)
    vehicle_document["vehicle_cost_items"] = vehicle_document["economics"].get("vehicle_cost_items", [])
    return _filter_vehicle_for_role(vehicle_document, current_role=current_role)


def update_vehicle(vehicle_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    vehicle = get_vehicle_document_by_id(vehicle_id)
    _restrict_admin_sensitive_payload(payload, current_role=current_role)
    normalized_data = normalize_vehicle_payload(
        payload,
        partial=True,
        vehicle_id=vehicle["_id"],
        existing_insurance_profile=vehicle.get("insurance_profile") or {},
        existing_asset_owner_contact=vehicle.get("asset_owner_contact") or {},
    )
    if not normalized_data:
        raise ApiError("No vehicle fields provided for update.", status_code=400)

    ensure_unique_vehicle_fields(normalized_data, exclude_vehicle_id=vehicle["_id"])

    previous_driver_id = vehicle.get("assigned_driver_id")
    timestamp = now_utc()
    normalized_data["updated_at"] = timestamp
    normalized_data["updated_by"] = ObjectId(current_user_id) if ObjectId.is_valid(current_user_id) else current_user_id

    try:
        vehicles_collection().update_one({"_id": vehicle["_id"]}, {"$set": normalized_data})
    except DuplicateKeyError:
        raise ApiError("A vehicle with one of the unique fields already exists.", status_code=409) from None

    vehicle.update(normalized_data)
    _apply_vehicle_ownership_defaults(vehicle)
    sync_vehicle_assignment(
        vehicle_id=vehicle["_id"],
        previous_driver_id=previous_driver_id,
        new_driver_id=vehicle.get("assigned_driver_id"),
    )
    vehicle["economics"] = _calculate_vehicle_economics(vehicle)
    vehicle["vehicle_cost_items"] = vehicle["economics"].get("vehicle_cost_items", [])
    return _filter_vehicle_for_role(vehicle, current_role=current_role)


def update_vehicle_status(vehicle_id: str, status: str, *, current_role: str) -> dict:
    if status not in ALLOWED_VEHICLE_STATUSES:
        raise ApiError("Invalid vehicle status.", status_code=400)

    vehicle = get_vehicle_document_by_id(vehicle_id)
    timestamp = now_utc()
    vehicles_collection().update_one(
        {"_id": vehicle["_id"]},
        {"$set": {"status": status, "updated_at": timestamp}},
    )
    vehicle["status"] = status
    vehicle["updated_at"] = timestamp
    vehicle["economics"] = _calculate_vehicle_economics(vehicle)
    vehicle["vehicle_cost_items"] = vehicle["economics"].get("vehicle_cost_items", [])
    return _filter_vehicle_for_role(vehicle, current_role=current_role)


def delete_vehicle(vehicle_id: str) -> None:
    vehicle = get_vehicle_document_by_id(vehicle_id)
    if vehicle.get("assigned_driver_id"):
        sync_vehicle_assignment(
            vehicle_id=vehicle["_id"],
            previous_driver_id=vehicle.get("assigned_driver_id"),
            new_driver_id=None,
        )

    vehicles_collection().delete_one({"_id": vehicle["_id"]})


def list_vehicle_cost_items(vehicle_id: str, *, current_role: str) -> list[dict]:
    if current_role == "admin" and not _can_admin_access("manage_vehicle_cost_items"):
        raise ApiError("You do not have permission to view vehicle cost items.", status_code=403)
    vehicle = get_vehicle_document_by_id(vehicle_id)
    items = vehicle_cost_items_collection().find({"vehicle_id": vehicle["_id"]}).sort("date", ASCENDING)
    return [_serialize_cost_item(item) for item in items]


def create_vehicle_cost_item(vehicle_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role == "admin" and not _can_admin_access("manage_vehicle_cost_items"):
        raise ApiError("You do not have permission to manage vehicle cost items.", status_code=403)
    vehicle = get_vehicle_document_by_id(vehicle_id)
    item_name = normalize_string(payload.get("item_name"))
    if not item_name:
        raise ApiError("item_name is required.", status_code=400)
    amount = validate_numeric(payload.get("amount"), "amount", positive=True)
    item_date = normalize_string(payload.get("date")) or now_utc().date().isoformat()
    timestamp = now_utc()
    document = {
        "vehicle_id": vehicle["_id"],
        "item_name": item_name,
        "amount": amount,
        "date": item_date,
        "notes": normalize_string(payload.get("notes")),
        "created_by": ObjectId(current_user_id) if ObjectId.is_valid(current_user_id) else current_user_id,
        "updated_by": ObjectId(current_user_id) if ObjectId.is_valid(current_user_id) else current_user_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = vehicle_cost_items_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize_cost_item(document)


def get_vehicle_economics_dashboard(*, current_role: str) -> dict:
    vehicles = list(vehicles_collection().find({}))
    serialized_vehicles = []
    for vehicle in vehicles:
        _apply_vehicle_ownership_defaults(vehicle)
        vehicle["economics"] = _calculate_vehicle_economics(vehicle)
        vehicle["vehicle_cost_items"] = vehicle["economics"].get("vehicle_cost_items", [])
        serialized_vehicles.append(_filter_vehicle_for_role(vehicle, current_role=current_role))

    total_fleet_investment = round(sum(_safe_float((vehicle.get("economics") or {}).get("investment", {}).get("total_vehicle_investment")) for vehicle in serialized_vehicles), 2)
    total_recovered = round(sum(_safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("amount_recovered")) for vehicle in serialized_vehicles), 2)
    remaining_recovery_balance = round(sum(_safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("remaining_balance")) for vehicle in serialized_vehicles), 2)
    net_fleet_profit = round(sum(_safe_float((vehicle.get("economics") or {}).get("profitability", {}).get("net_profit")) for vehicle in serialized_vehicles), 2)

    with_profit = [vehicle for vehicle in serialized_vehicles if ((vehicle.get("economics") or {}).get("recovery", {}).get("status") == "Profit Generating")]
    recovering = [vehicle for vehicle in serialized_vehicles if ((vehicle.get("economics") or {}).get("recovery", {}).get("status") == "Recovering")]
    recovered = [
        vehicle
        for vehicle in serialized_vehicles
        if ((vehicle.get("economics") or {}).get("recovery", {}).get("status") == "Profit Generating")
    ]
    profitability_ranked = sorted(
        [vehicle for vehicle in serialized_vehicles if (vehicle.get("economics") or {}).get("profitability")],
        key=lambda item: _safe_float((item.get("economics") or {}).get("profitability", {}).get("net_profit")),
        reverse=True,
    )
    total_managed_fleet_value = round(
        sum(_safe_float((vehicle.get("economics") or {}).get("investment", {}).get("current_estimated_value")) for vehicle in serialized_vehicles),
        2,
    )
    owner_breakdown: dict[str, dict] = {}
    for vehicle in serialized_vehicles:
        owner_name = vehicle.get("asset_owner_name") or DEFAULT_ASSET_OWNER_NAME
        ownership_type = vehicle.get("asset_owner_type") or DEFAULT_ASSET_OWNER_TYPE
        entry = owner_breakdown.setdefault(
            owner_name,
            {
                "asset_owner_name": owner_name,
                "asset_owner_type": ownership_type,
                "vehicle_count": 0,
                "fleet_value": 0.0,
                "fleet_investment": 0.0,
                "capital_basis_for_recovery": 0.0,
                "revenue_generated": 0.0,
                "net_profit": 0.0,
                "capital_recovered": 0.0,
                "outstanding_capital": 0.0,
            },
        )
        entry["vehicle_count"] += 1
        entry["fleet_value"] += _safe_float((vehicle.get("economics") or {}).get("investment", {}).get("current_estimated_value"))
        entry["fleet_investment"] += _safe_float((vehicle.get("economics") or {}).get("investment", {}).get("total_vehicle_investment"))
        entry["capital_basis_for_recovery"] += _safe_float((vehicle.get("economics") or {}).get("investment", {}).get("capital_basis_for_recovery"))
        entry["revenue_generated"] += _safe_float((vehicle.get("economics") or {}).get("profitability", {}).get("gross_revenue"))
        entry["net_profit"] += _safe_float((vehicle.get("economics") or {}).get("profitability", {}).get("net_profit"))
        entry["capital_recovered"] += _safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("amount_recovered"))
        entry["outstanding_capital"] += _safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("remaining_balance"))
    grouped_portfolio = []
    for entry in owner_breakdown.values():
        capital_basis = round(entry["capital_basis_for_recovery"], 2)
        net_profit = round(entry["net_profit"], 2)
        entry["fleet_value"] = round(entry["fleet_value"], 2)
        entry["fleet_investment"] = round(entry["fleet_investment"], 2)
        entry["capital_basis_for_recovery"] = capital_basis
        entry["revenue_generated"] = round(entry["revenue_generated"], 2)
        entry["net_profit"] = net_profit
        entry["capital_recovered"] = round(entry["capital_recovered"], 2)
        entry["outstanding_capital"] = round(entry["outstanding_capital"], 2)
        entry["roi_percent"] = round((net_profit / capital_basis) * 100, 2) if capital_basis > 0 else 0.0
        grouped_portfolio.append(entry)
    grouped_portfolio.sort(key=lambda item: item["asset_owner_name"])

    return {
        "operating_fleet_name": DEFAULT_OPERATING_FLEET_NAME,
        "total_managed_fleet": len(serialized_vehicles),
        "total_active_vehicles": len(
            [vehicle for vehicle in serialized_vehicles if vehicle.get("status") in {"available", "assigned", "active"}]
        ),
        "total_managed_fleet_value": total_managed_fleet_value,
        "total_fleet_investment": total_fleet_investment,
        "total_recovered": total_recovered,
        "remaining_recovery_balance": remaining_recovery_balance,
        "net_fleet_profit": net_fleet_profit,
        "fleet_roi_percent": round((net_fleet_profit / total_fleet_investment) * 100, 2) if total_fleet_investment > 0 else 0.0,
        "vehicles_recovering": len(recovering),
        "vehicles_fully_recovered": len(recovered),
        "vehicles_profit_generating": len(with_profit),
        "most_profitable_vehicle": profitability_ranked[0] if profitability_ranked else None,
        "least_profitable_vehicle": profitability_ranked[-1] if profitability_ranked else None,
        "portfolio_breakdown": grouped_portfolio,
        "vehicles": serialized_vehicles,
    }
