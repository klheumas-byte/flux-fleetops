from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING

from extensions import get_collection
from utils.api_error import ApiError


SUPPORTED_CURRENCIES: dict[str, str] = {
    "GHS": "GHS",
    "USD": "$",
    "NGN": "NGN",
    "KES": "KSh",
    "ZAR": "R",
    "GBP": "GBP",
    "EUR": "EUR",
}

SUPPORTED_DISTANCE_UNITS = {"KM", "MI"}

DEFAULT_SETTINGS = {
    "key": "core",
    "default_currency": "GHS",
    "currency_symbol": SUPPORTED_CURRENCIES["GHS"],
    "distance_unit": "KM",
    "include_fuel_in_profitability": False,
    "role_permissions": {
        "admin": {
            "view_vehicle_investment": False,
            "view_vehicle_recovery": False,
            "view_profitability": False,
            "view_investor_information": False,
            "view_reports": False,
            "export_financial_reports": False,
            "manage_vehicle_cost_items": False,
        }
    },
    "role_permission_audit_log": [],
    "created_by": None,
    "updated_by": None,
}


def now_utc():
    return datetime.now(timezone.utc)


def system_settings_collection():
    return get_collection("system_settings")


def ensure_system_settings_indexes():
    system_settings_collection().create_index([("key", ASCENDING)], unique=True)
    seed_system_settings()


def _normalize_text(value: Any):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _serialize_settings(document: dict):
    return {
        "id": str(document.get("_id")),
        "default_currency": document.get("default_currency"),
        "currency_symbol": document.get("currency_symbol"),
        "distance_unit": document.get("distance_unit"),
        "include_fuel_in_profitability": bool(
            document.get("include_fuel_in_profitability", DEFAULT_SETTINGS["include_fuel_in_profitability"])
        ),
        "role_permissions": document.get("role_permissions") or DEFAULT_SETTINGS["role_permissions"],
        "role_permission_audit_log": [
            {
                **entry,
                "changed_by": str(entry.get("changed_by")) if entry.get("changed_by") else None,
                "changed_at": entry.get("changed_at").isoformat() if entry.get("changed_at") else None,
            }
            for entry in (document.get("role_permission_audit_log") or [])
        ],
        "supported_currencies": list(SUPPORTED_CURRENCIES.keys()),
        "supported_distance_units": sorted(SUPPORTED_DISTANCE_UNITS),
        "created_by": str(document.get("created_by")) if document.get("created_by") else None,
        "updated_by": str(document.get("updated_by")) if document.get("updated_by") else None,
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


def seed_system_settings():
    timestamp = now_utc()
    system_settings_collection().update_one(
        {"key": DEFAULT_SETTINGS["key"]},
        {
            "$setOnInsert": {
                **DEFAULT_SETTINGS,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        },
        upsert=True,
    )


def get_system_settings() -> dict:
    document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})
    if not document:
        seed_system_settings()
        document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})
    return _serialize_settings(document)


def _validate_currency(value: str | None):
    normalized = _normalize_text(value)
    if normalized not in SUPPORTED_CURRENCIES:
        raise ApiError("Invalid default currency.", status_code=400)
    return normalized


def _validate_currency_symbol(value: str | None, *, default_currency: str):
    normalized = _normalize_text(value)
    return normalized or SUPPORTED_CURRENCIES[default_currency]


def _validate_distance_unit(value: str | None):
    normalized = _normalize_text(value)
    if normalized not in SUPPORTED_DISTANCE_UNITS:
        raise ApiError("Invalid distance unit.", status_code=400)
    return normalized


def update_system_settings(payload: dict, *, current_user_id: str):
    document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})
    if not document:
        seed_system_settings()
        document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})

    update_fields: dict[str, Any] = {}
    next_currency = document.get("default_currency", DEFAULT_SETTINGS["default_currency"])

    if "default_currency" in payload:
        next_currency = _validate_currency(payload.get("default_currency"))
        update_fields["default_currency"] = next_currency

    if "currency_symbol" in payload or "default_currency" in payload:
        update_fields["currency_symbol"] = _validate_currency_symbol(
            payload.get("currency_symbol"),
            default_currency=next_currency,
        )

    if "distance_unit" in payload:
        update_fields["distance_unit"] = _validate_distance_unit(payload.get("distance_unit"))

    if "include_fuel_in_profitability" in payload:
        include_fuel_in_profitability = payload.get("include_fuel_in_profitability")
        if not isinstance(include_fuel_in_profitability, bool):
            raise ApiError("include_fuel_in_profitability must be boolean.", status_code=400)
        update_fields["include_fuel_in_profitability"] = include_fuel_in_profitability

    if "role_permissions" in payload:
        role_permissions = payload.get("role_permissions")
        if not isinstance(role_permissions, dict):
            raise ApiError("role_permissions must be an object.", status_code=400)
        admin_permissions = role_permissions.get("admin")
        if not isinstance(admin_permissions, dict):
            raise ApiError("role_permissions.admin must be an object.", status_code=400)
        next_admin_permissions = {
            **(document.get("role_permissions") or DEFAULT_SETTINGS["role_permissions"]).get("admin", {}),
        }
        changed_keys: list[str] = []
        for key, value in admin_permissions.items():
            if not isinstance(value, bool):
                raise ApiError(f"role_permissions.admin.{key} must be boolean.", status_code=400)
            if next_admin_permissions.get(key) != value:
                changed_keys.append(key)
            next_admin_permissions[key] = value
        update_fields["role_permissions"] = {
            **(document.get("role_permissions") or DEFAULT_SETTINGS["role_permissions"]),
            "admin": next_admin_permissions,
        }
        if changed_keys:
            audit_entry = {
                "changed_by": current_user_id,
                "changed_at": now_utc(),
                "changed_keys": changed_keys,
                "scope": "admin_vehicle_economics_permissions",
            }
            existing_audit = list(document.get("role_permission_audit_log") or [])
            existing_audit.append(audit_entry)
            update_fields["role_permission_audit_log"] = existing_audit

    if not update_fields:
        raise ApiError("No system settings fields provided for update.", status_code=400)

    timestamp = now_utc()
    update_fields["updated_by"] = current_user_id
    update_fields["updated_at"] = timestamp

    system_settings_collection().update_one(
        {"_id": document["_id"]},
        {"$set": update_fields},
    )
    document.update(update_fields)
    return _serialize_settings(document)


def get_admin_role_permissions() -> dict[str, bool]:
    document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})
    if not document:
        seed_system_settings()
        document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})
    return {
        **DEFAULT_SETTINGS["role_permissions"]["admin"],
        **((document.get("role_permissions") or {}).get("admin") or {}),
    }


def should_include_fuel_in_profitability() -> bool:
    document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})
    if not document:
        seed_system_settings()
        document = system_settings_collection().find_one({"key": DEFAULT_SETTINGS["key"]})
    return bool(
        document.get(
            "include_fuel_in_profitability",
            DEFAULT_SETTINGS["include_fuel_in_profitability"],
        )
    )
