from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from time import perf_counter

from bson import ObjectId
from flask import current_app
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.user import serialize_user
from services.driver_analytics_service import list_driver_analytics
from services.system_settings_service import get_admin_role_permissions
from services.vehicle_service import get_vehicle_economics_dashboard
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, set_ttl_cached


def collections_collection():
    return get_collection("collections")


def wallet_entries_collection():
    return get_collection("wallet_entries")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def deposits_collection():
    return get_collection("deposits")


def expenses_collection():
    return get_collection("expenses")


def fuel_logs_collection():
    return get_collection("fuel_logs")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def faults_collection():
    return get_collection("faults")


def customers_collection():
    return get_collection("customers")


def bookings_collection():
    return get_collection("bookings")


def rides_collection():
    return get_collection("rides")


def finance_accounts_collection():
    return get_collection("finance_accounts")


REPORT_DRIVER_PROJECTION = {
    "full_name": 1,
    "email": 1,
    "phone": 1,
    "role": 1,
    "status": 1,
    "last_login": 1,
    "created_at": 1,
    "updated_at": 1,
    "driver_profile": 1,
}

REPORT_VEHICLE_PROJECTION = {
    "registration_number": 1,
    "status": 1,
    "asset_owner_name": 1,
    "asset_owner_type": 1,
    "operating_fleet_name": 1,
}

REPORT_COLLECTION_PROJECTION = {
    "collection_date": 1,
    "amount": 1,
    "status": 1,
    "payment_method": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "created_at": 1,
    "updated_at": 1,
    "approved_at": 1,
}

REPORT_DEPOSIT_PROJECTION = {
    "deposit_date": 1,
    "amount": 1,
    "status": 1,
    "deposit_method": 1,
    "destination_name": 1,
    "finance_account_snapshot.branch": 1,
    "created_at": 1,
    "updated_at": 1,
    "verified_at": 1,
}

REPORT_EXPENSE_PROJECTION = {
    "expense_date": 1,
    "amount": 1,
    "status": 1,
    "expense_category": 1,
    "expense_title": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "finance_account_snapshot.branch": 1,
    "created_at": 1,
    "updated_at": 1,
    "approved_at": 1,
    "paid_at": 1,
}

REPORT_FUEL_PROJECTION = {
    "fuel_date": 1,
    "amount": 1,
    "litres": 1,
    "fuel_type": 1,
    "status": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "created_at": 1,
    "updated_at": 1,
}

REPORT_MAINTENANCE_PROJECTION = {
    "maintenance_type": 1,
    "title": 1,
    "status": 1,
    "actual_cost": 1,
    "estimated_cost": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "completion_date": 1,
    "start_date": 1,
    "target_completion_date": 1,
    "created_at": 1,
    "updated_at": 1,
}

REPORT_FAULT_PROJECTION = {
    "severity": 1,
    "status": 1,
    "description": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "reported_at": 1,
    "created_at": 1,
    "updated_at": 1,
}

REPORT_CUSTOMER_PROJECTION = {
    "full_name": 1,
    "phone_number": 1,
    "customer_category": 1,
    "customer_category_id": 1,
    "relationship_category": 1,
    "lead_status": 1,
    "lead_value_estimate": 1,
    "status": 1,
    "created_by_name": 1,
    "created_by_role": 1,
    "created_by_driver_id": 1,
    "preferred_driver_id": 1,
    "source": 1,
    "created_at": 1,
    "updated_at": 1,
}

REPORT_BOOKING_PROJECTION = {
    "booking_id": 1,
    "pickup_at": 1,
    "pickup_date": 1,
    "booking_type": 1,
    "status": 1,
    "expected_fare": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "customer_id": 1,
    "pickup_location": 1,
    "destination": 1,
    "is_recurring_template": 1,
    "created_at": 1,
    "updated_at": 1,
}

REPORT_RIDE_PROJECTION = {
    "trip_id": 1,
    "ride_id": 1,
    "trip_date": 1,
    "trip_source": 1,
    "trip_purpose": 1,
    "status": 1,
    "driver_id": 1,
    "vehicle_id": 1,
    "customer_id": 1,
    "pickup_area": 1,
    "destination_area": 1,
    "created_at": 1,
    "updated_at": 1,
}


def now_utc():
    return datetime.now(timezone.utc)


def ensure_report_indexes():
    ensure_indexes_for_collection(
        deposits_collection(),
        [
            {"keys": [("finance_account_snapshot.branch", ASCENDING), ("deposit_date", DESCENDING)]},
        ],
        collection_name="deposits_reports",
    )
    ensure_indexes_for_collection(
        expenses_collection(),
        [
            {"keys": [("finance_account_snapshot.branch", ASCENDING), ("expense_date", DESCENDING)]},
        ],
        collection_name="expenses_reports",
    )
    ensure_indexes_for_collection(
        fuel_logs_collection(),
        [
            {"keys": [("driver_id", ASCENDING), ("fuel_date", DESCENDING)]},
        ],
        collection_name="fuel_logs_reports",
    )
    ensure_indexes_for_collection(
        faults_collection(),
        [
            {"keys": [("driver_id", ASCENDING), ("reported_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("reported_at", DESCENDING)]},
        ],
        collection_name="faults_reports",
    )
    ensure_indexes_for_collection(
        rides_collection(),
        [
            {"keys": [("driver_id", ASCENDING), ("trip_date", DESCENDING), ("created_at", DESCENDING)]},
        ],
        collection_name="rides_reports",
    )
    ensure_indexes_for_collection(
        customers_collection(),
        [
            {"keys": [("created_by_role", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("customer_category_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("source", ASCENDING), ("created_at", DESCENDING)]},
        ],
        collection_name="customers_reports",
    )


def _normalize_string(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value.isoformat()
    elif isinstance(value, date):
        normalized = value.isoformat()
    else:
        normalized = str(value).strip()
    return normalized or None


def _normalize_date(value):
    raw = _normalize_string(value)
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as error:
        raise ApiError("date filters must use YYYY-MM-DD format.", status_code=400) from error


def _to_utc_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        for candidate in (raw, raw.replace("Z", "+00:00")):
            try:
                parsed = datetime.fromisoformat(candidate)
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            except ValueError:
                continue
        try:
            return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _id_string(value):
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return str(value)
    return str(value)


def _safe_float(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _matches_selected_id(value, selected_id: str | None):
    if not selected_id:
        return True
    return _id_string(value) == selected_id


def _date_in_range(value, start_date: date | None, end_date: date | None):
    if start_date is None and end_date is None:
        return True
    instant = _to_utc_datetime(value)
    if instant is None:
        return False
    current = instant.date()
    if start_date and current < start_date:
        return False
    if end_date and current > end_date:
        return False
    return True


def _last_updated_iso(records: list[dict], *candidate_fields: str):
    timestamps = []
    for record in records:
        for field in candidate_fields:
            instant = _to_utc_datetime(record.get(field))
            if instant:
                timestamps.append(instant)
    if not timestamps:
        return None
    return max(timestamps).isoformat()


def _active_filters_payload(filters: dict):
    return {
        "date_from": filters["date_from"].isoformat() if filters["date_from"] else None,
        "date_to": filters["date_to"].isoformat() if filters["date_to"] else None,
        "driver_id": filters["driver_id"],
        "vehicle_id": filters["vehicle_id"],
        "branch": filters["branch"],
        "asset_owner_name": filters["asset_owner_name"],
        "creator_role": filters["creator_role"],
        "customer_category_id": filters["customer_category_id"],
        "source": filters["source"],
    }


def _active_filters_labels(filters: dict, *, drivers_by_id: dict, vehicles_by_id: dict):
    labels = []
    if filters["date_from"] or filters["date_to"]:
        start = filters["date_from"].isoformat() if filters["date_from"] else "Any"
        end = filters["date_to"].isoformat() if filters["date_to"] else "Any"
        labels.append(f"Date: {start} to {end}")
    if filters["driver_id"]:
        driver = drivers_by_id.get(filters["driver_id"])
        labels.append(f"Driver: {driver.get('full_name') if driver else filters['driver_id']}")
    if filters["vehicle_id"]:
        vehicle = vehicles_by_id.get(filters["vehicle_id"])
        labels.append(
            f"Vehicle: {vehicle.get('registration_number') if vehicle else filters['vehicle_id']}"
        )
    if filters["branch"]:
        labels.append(f"Branch: {filters['branch']}")
    if filters["asset_owner_name"]:
        labels.append(f"Asset Owner: {filters['asset_owner_name']}")
    if filters["creator_role"]:
        labels.append(f"Creator Role: {filters['creator_role']}")
    if filters["customer_category_id"]:
        labels.append(f"Customer Category: {filters['customer_category_id']}")
    if filters["source"]:
        labels.append(f"Source: {filters['source']}")
    return labels or ["All records"]


def _normalize_filters(
    *,
    date_from: str | None,
    date_to: str | None,
    driver_id: str | None,
    vehicle_id: str | None,
    branch: str | None,
    asset_owner_name: str | None = None,
    creator_role: str | None = None,
    customer_category_id: str | None = None,
    source: str | None = None,
):
    return {
        "date_from": _normalize_date(date_from),
        "date_to": _normalize_date(date_to),
        "driver_id": _normalize_string(driver_id),
        "vehicle_id": _normalize_string(vehicle_id),
        "branch": _normalize_string(branch),
        "asset_owner_name": _normalize_string(asset_owner_name),
        "creator_role": _normalize_string(creator_role),
        "customer_category_id": _normalize_string(customer_category_id),
        "source": _normalize_string(source),
    }


def _branch_from_snapshot(record: dict):
    snapshot = record.get("finance_account_snapshot") or {}
    return _normalize_string(snapshot.get("branch"))


def _base_section(*, records: list[dict], total_amount: float, last_updated: str | None, active_filters: list[str]):
    return {
        "records": records,
        "validation": {
            "total_records": len(records),
            "total_amount": round(total_amount, 2),
            "last_updated": last_updated,
            "active_filters": active_filters,
        },
    }


def _empty_validation(active_filters: list[str] | None = None):
    return {
        "total_records": 0,
        "total_amount": 0,
        "last_updated": None,
        "active_filters": active_filters or ["All records"],
    }


def _empty_section(active_filters: list[str] | None = None):
    return {
        "records": [],
        "validation": _empty_validation(active_filters),
        "message": "No records found for this filter.",
    }


def _empty_vehicle_economics(active_filters: list[str] | None = None):
    return {
        "validation": _empty_validation(active_filters),
        "message": "No records found for this filter.",
        "total_fleet_investment": 0,
        "total_recovered": 0,
        "remaining_recovery_balance": 0,
        "net_fleet_profit": 0,
        "vehicles": [],
    }


def _build_collections_report(collection_documents: list[dict], *, filters: dict, drivers_by_id: dict, vehicles_by_id: dict, active_filters: list[str]):
    filtered = [
        document
        for document in collection_documents
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(document.get("collection_date"), filters["date_from"], filters["date_to"])
        and (not filters["branch"])
    ]
    filtered.sort(key=lambda item: (_normalize_string(item.get("collection_date")) or "", _normalize_string(item.get("created_at")) or ""), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "collection_date": document.get("collection_date"),
            "amount": _safe_float(document.get("amount")),
            "status": document.get("status"),
            "payment_method": document.get("payment_method"),
            "driver_name": (drivers_by_id.get(_id_string(document.get("driver_id"))) or {}).get("full_name"),
            "vehicle_registration": (vehicles_by_id.get(_id_string(document.get("vehicle_id"))) or {}).get("registration_number"),
        }
        for document in filtered
    ]
    return _base_section(
        records=records,
        total_amount=sum(item["amount"] for item in records),
        last_updated=_last_updated_iso(filtered, "updated_at", "approved_at", "created_at"),
        active_filters=active_filters,
    )


def _build_deposits_report(deposit_documents: list[dict], *, filters: dict, active_filters: list[str]):
    filtered = [
        document
        for document in deposit_documents
        if _date_in_range(document.get("deposit_date"), filters["date_from"], filters["date_to"])
        and (not filters["branch"] or _branch_from_snapshot(document) == filters["branch"])
    ]
    filtered.sort(key=lambda item: (_normalize_string(item.get("deposit_date")) or "", _normalize_string(item.get("created_at")) or ""), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "deposit_date": document.get("deposit_date"),
            "amount": _safe_float(document.get("amount")),
            "status": document.get("status"),
            "deposit_method": document.get("deposit_method"),
            "destination_name": document.get("destination_name"),
            "branch": _branch_from_snapshot(document),
        }
        for document in filtered
    ]
    return _base_section(
        records=records,
        total_amount=sum(item["amount"] for item in records),
        last_updated=_last_updated_iso(filtered, "updated_at", "verified_at", "created_at"),
        active_filters=active_filters,
    )


def _build_expenses_report(expense_documents: list[dict], *, filters: dict, drivers_by_id: dict, vehicles_by_id: dict, active_filters: list[str]):
    filtered = [
        document
        for document in expense_documents
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(document.get("expense_date"), filters["date_from"], filters["date_to"])
        and (not filters["branch"] or _branch_from_snapshot(document) == filters["branch"])
    ]
    filtered.sort(key=lambda item: (_normalize_string(item.get("expense_date")) or "", _normalize_string(item.get("created_at")) or ""), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "expense_date": document.get("expense_date"),
            "amount": _safe_float(document.get("amount")),
            "status": document.get("status"),
            "expense_category": document.get("expense_category"),
            "expense_title": document.get("expense_title"),
            "driver_name": (drivers_by_id.get(_id_string(document.get("driver_id"))) or {}).get("full_name"),
            "vehicle_registration": (vehicles_by_id.get(_id_string(document.get("vehicle_id"))) or {}).get("registration_number"),
            "branch": _branch_from_snapshot(document),
        }
        for document in filtered
    ]
    return _base_section(
        records=records,
        total_amount=sum(item["amount"] for item in records),
        last_updated=_last_updated_iso(filtered, "updated_at", "paid_at", "approved_at", "created_at"),
        active_filters=active_filters,
    )


def _build_fuel_report(fuel_documents: list[dict], *, filters: dict, drivers_by_id: dict, vehicles_by_id: dict, active_filters: list[str]):
    filtered = [
        document
        for document in fuel_documents
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(document.get("fuel_date"), filters["date_from"], filters["date_to"])
        and (not filters["branch"])
    ]
    filtered.sort(key=lambda item: (_normalize_string(item.get("fuel_date")) or "", _normalize_string(item.get("created_at")) or ""), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "fuel_date": document.get("fuel_date"),
            "amount": _safe_float(document.get("amount")),
            "litres": round(float(document.get("litres") or 0), 2),
            "fuel_type": document.get("fuel_type"),
            "status": document.get("status"),
            "driver_name": (drivers_by_id.get(_id_string(document.get("driver_id"))) or {}).get("full_name"),
            "vehicle_registration": (vehicles_by_id.get(_id_string(document.get("vehicle_id"))) or {}).get("registration_number"),
        }
        for document in filtered
    ]
    section = _base_section(
        records=records,
        total_amount=sum(item["amount"] for item in records),
        last_updated=_last_updated_iso(filtered, "updated_at", "created_at"),
        active_filters=active_filters,
    )
    section["total_litres"] = round(sum(item["litres"] for item in records), 2)
    return section


def _maintenance_reference_date(document: dict):
    return document.get("completion_date") or document.get("start_date") or document.get("target_completion_date") or document.get("created_at")


def _build_maintenance_report(maintenance_documents: list[dict], *, filters: dict, drivers_by_id: dict, vehicles_by_id: dict, active_filters: list[str]):
    filtered = [
        document
        for document in maintenance_documents
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(_maintenance_reference_date(document), filters["date_from"], filters["date_to"])
        and (not filters["branch"])
    ]
    filtered.sort(key=lambda item: (_normalize_string(_maintenance_reference_date(item)) or "", _normalize_string(item.get("created_at")) or ""), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "maintenance_type": document.get("maintenance_type"),
            "title": document.get("title"),
            "status": document.get("status"),
            "reference_date": _maintenance_reference_date(document),
            "actual_cost": _safe_float(document.get("actual_cost") if document.get("actual_cost") is not None else document.get("estimated_cost")),
            "driver_name": (drivers_by_id.get(_id_string(document.get("driver_id"))) or {}).get("full_name"),
            "vehicle_registration": (vehicles_by_id.get(_id_string(document.get("vehicle_id"))) or {}).get("registration_number"),
        }
        for document in filtered
    ]
    return _base_section(
        records=records,
        total_amount=sum(item["actual_cost"] for item in records),
        last_updated=_last_updated_iso(filtered, "updated_at", "completion_date", "created_at"),
        active_filters=active_filters,
    )


def _build_fault_report(fault_documents: list[dict], *, filters: dict, drivers_by_id: dict, vehicles_by_id: dict, active_filters: list[str]):
    filtered = [
        document
        for document in fault_documents
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(document.get("reported_at") or document.get("created_at"), filters["date_from"], filters["date_to"])
        and (not filters["branch"])
    ]
    filtered.sort(key=lambda item: _to_utc_datetime(item.get("reported_at") or item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "reported_at": (_to_utc_datetime(document.get("reported_at")) or _to_utc_datetime(document.get("created_at"))).isoformat()
            if (_to_utc_datetime(document.get("reported_at")) or _to_utc_datetime(document.get("created_at")))
            else None,
            "severity": document.get("severity"),
            "status": document.get("status"),
            "description": document.get("description"),
            "driver_name": (drivers_by_id.get(_id_string(document.get("driver_id"))) or {}).get("full_name"),
            "vehicle_registration": (vehicles_by_id.get(_id_string(document.get("vehicle_id"))) or {}).get("registration_number"),
        }
        for document in filtered
    ]
    return _base_section(
        records=records,
        total_amount=0,
        last_updated=_last_updated_iso(filtered, "updated_at", "reported_at", "created_at"),
        active_filters=active_filters,
    )


def _build_customer_report(
    customer_documents: list[dict],
    *,
    filters: dict,
    active_filters: list[str],
    scoped_customer_ids: set[str] | None = None,
):
    scoped_customer_ids = scoped_customer_ids or set()
    filtered = []
    for document in customer_documents:
        if filters["driver_id"]:
            matches_selected_driver = (
                _id_string(document.get("preferred_driver_id")) == filters["driver_id"]
                or _id_string(document.get("created_by_driver_id")) == filters["driver_id"]
                or _id_string(document.get("_id")) in scoped_customer_ids
            )
            if not matches_selected_driver:
                continue
        elif filters["vehicle_id"] and _id_string(document.get("_id")) not in scoped_customer_ids:
            continue
        elif not _date_in_range(document.get("created_at"), filters["date_from"], filters["date_to"]):
            continue
        if filters["creator_role"] and _normalize_string(document.get("created_by_role")) != filters["creator_role"]:
            continue
        if filters["customer_category_id"] and _id_string(document.get("customer_category_id")) != filters["customer_category_id"]:
            continue
        if filters["source"] and _normalize_string(document.get("source")) != filters["source"]:
            continue
        filtered.append(document)
    filtered.sort(key=lambda item: _to_utc_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "full_name": document.get("full_name"),
            "phone_number": document.get("phone_number"),
            "customer_category": document.get("customer_category"),
            "relationship_category": document.get("relationship_category"),
            "lead_status": document.get("lead_status"),
            "lead_value_estimate": _safe_float(document.get("lead_value_estimate")),
            "status": document.get("status"),
            "creator_name": document.get("created_by_name") or "Unknown / Legacy Record",
            "creator_role": document.get("created_by_role") or "legacy",
            "source": document.get("source") or "other",
            "created_at": (_to_utc_datetime(document.get("created_at")).isoformat() if _to_utc_datetime(document.get("created_at")) else None),
        }
        for document in filtered
    ]
    return _base_section(
        records=records,
        total_amount=sum(item["lead_value_estimate"] for item in records),
        last_updated=_last_updated_iso(filtered, "updated_at", "created_at"),
        active_filters=active_filters,
    )


def _booking_status(value):
    return (value or "Scheduled").strip()


def _build_booking_report(booking_documents: list[dict], *, filters: dict, drivers_by_id: dict, vehicles_by_id: dict, active_filters: list[str]):
    filtered = [
        document
        for document in booking_documents
        if not document.get("is_recurring_template")
        and _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(document.get("pickup_at") or document.get("pickup_date"), filters["date_from"], filters["date_to"])
        and (not filters["branch"])
    ]
    filtered.sort(key=lambda item: _to_utc_datetime(item.get("pickup_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "booking_id": document.get("booking_id"),
            "pickup_at": (_to_utc_datetime(document.get("pickup_at")).isoformat() if _to_utc_datetime(document.get("pickup_at")) else None),
            "booking_type": document.get("booking_type"),
            "status": _booking_status(document.get("status")),
            "expected_fare": _safe_float(document.get("expected_fare")),
            "driver_name": (drivers_by_id.get(_id_string(document.get("driver_id"))) or {}).get("full_name"),
            "vehicle_registration": (vehicles_by_id.get(_id_string(document.get("vehicle_id"))) or {}).get("registration_number"),
            "pickup_location": document.get("pickup_location"),
            "destination": document.get("destination"),
        }
        for document in filtered
    ]
    section = _base_section(
        records=records,
        total_amount=sum(item["expected_fare"] for item in records),
        last_updated=_last_updated_iso(filtered, "updated_at", "pickup_at", "created_at"),
        active_filters=active_filters,
    )
    section["status_breakdown"] = dict(Counter(item["status"] for item in records if item["status"]))
    return section


def _build_trip_report(ride_documents: list[dict], *, filters: dict, drivers_by_id: dict, vehicles_by_id: dict, active_filters: list[str]):
    filtered = [
        document
        for document in ride_documents
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(document.get("trip_date"), filters["date_from"], filters["date_to"])
        and (not filters["branch"])
    ]
    filtered.sort(key=lambda item: (_normalize_string(item.get("trip_date")) or "", _normalize_string(item.get("created_at")) or ""), reverse=True)
    records = [
        {
            "id": str(document["_id"]),
            "trip_id": document.get("trip_id") or document.get("ride_id"),
            "trip_date": document.get("trip_date"),
            "trip_source": document.get("trip_source"),
            "trip_purpose": document.get("trip_purpose"),
            "status": document.get("status"),
            "driver_name": (drivers_by_id.get(_id_string(document.get("driver_id"))) or {}).get("full_name"),
            "vehicle_registration": (vehicles_by_id.get(_id_string(document.get("vehicle_id"))) or {}).get("registration_number"),
            "pickup_area": document.get("pickup_area"),
            "destination_area": document.get("destination_area"),
        }
        for document in filtered
    ]
    section = _base_section(
        records=records,
        total_amount=0,
        last_updated=_last_updated_iso(filtered, "updated_at", "created_at"),
        active_filters=active_filters,
    )
    section["trips_by_platform"] = [
        {"label": label, "count": count}
        for label, count in Counter(item["trip_source"] for item in records if item["trip_source"]).most_common()
    ]
    section["trips_by_purpose"] = [
        {"label": label, "count": count}
        for label, count in Counter(item["trip_purpose"] for item in records if item["trip_purpose"]).most_common()
    ]
    return section


def _build_driver_performance_report(*, current_user_id: str, current_role: str, filters: dict, active_filters: list[str]):
    analytics = list_driver_analytics(
        current_user_id=current_user_id,
        current_role=current_role,
        start_date=filters["date_from"].isoformat() if filters["date_from"] else None,
        end_date=filters["date_to"].isoformat() if filters["date_to"] else None,
        vehicle_id=filters["vehicle_id"],
        branch=filters["branch"],
    )
    records = analytics.get("drivers") or []
    if filters["driver_id"]:
        records = [record for record in records if (record.get("driver") or {}).get("id") == filters["driver_id"]]
    validation = {
        "total_records": len(records),
        "total_amount": round(sum(_safe_float(record.get("amount_collected")) for record in records), 2),
        "last_updated": now_utc().isoformat(),
        "active_filters": active_filters,
    }
    return {
        "records": records,
        "validation": validation,
    }


def _build_vehicle_performance_report(ride_documents: list[dict], vehicle_documents: list[dict], *, filters: dict, active_filters: list[str]):
    filtered_rides = [
        document
        for document in ride_documents
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"])
        and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"])
        and _date_in_range(document.get("trip_date"), filters["date_from"], filters["date_to"])
        and (not filters["branch"])
    ]
    rides_by_vehicle: dict[str, list[dict]] = defaultdict(list)
    active_days_by_vehicle: dict[str, set[str]] = defaultdict(set)
    for document in filtered_rides:
        vehicle_key = _id_string(document.get("vehicle_id"))
        if not vehicle_key:
            continue
        rides_by_vehicle[vehicle_key].append(document)
        if document.get("trip_date"):
            active_days_by_vehicle[vehicle_key].add(document.get("trip_date"))

    start_date = filters["date_from"] or ((now_utc().date() - timedelta(days=29)) if not filters["date_to"] else filters["date_to"])
    end_date = filters["date_to"] or now_utc().date()
    total_days = max((end_date - start_date).days + 1, 1)

    selected_vehicles = [
        vehicle
        for vehicle in vehicle_documents
        if _matches_selected_id(vehicle.get("_id"), filters["vehicle_id"])
        and (not filters["asset_owner_name"] or _normalize_string(vehicle.get("asset_owner_name")) == filters["asset_owner_name"])
    ]
    records = []
    for vehicle in selected_vehicles:
        vehicle_id = str(vehicle["_id"])
        trip_count = len(rides_by_vehicle.get(vehicle_id, []))
        active_days = len(active_days_by_vehicle.get(vehicle_id, set()))
        idle_days = max(total_days - active_days, 0)
        utilization_percentage = round((active_days / total_days) * 100, 1) if total_days else 0.0
        records.append(
            {
                "id": vehicle_id,
                "registration_number": vehicle.get("registration_number"),
                "status": vehicle.get("status"),
                "operating_fleet_name": vehicle.get("operating_fleet_name"),
                "asset_owner_name": vehicle.get("asset_owner_name"),
                "asset_owner_type": vehicle.get("asset_owner_type"),
                "trip_count": trip_count,
                "active_days": active_days,
                "idle_days": idle_days,
                "utilization_percentage": utilization_percentage,
            }
        )
    records.sort(key=lambda item: (-item["trip_count"], -item["utilization_percentage"], item["registration_number"] or ""))
    return {
        "records": records,
        "validation": {
            "total_records": len(records),
            "total_amount": round(sum(item["trip_count"] for item in records), 2),
            "last_updated": _last_updated_iso(filtered_rides, "updated_at", "created_at"),
            "active_filters": active_filters,
        },
    }


def _filter_economics_dashboard(dashboard: dict, *, vehicle_id: str | None, asset_owner_name: str | None):
    vehicles = dashboard.get("vehicles") or []
    if vehicle_id:
        vehicles = [vehicle for vehicle in vehicles if vehicle.get("id") == vehicle_id]
    if asset_owner_name:
        vehicles = [vehicle for vehicle in vehicles if _normalize_string(vehicle.get("asset_owner_name")) == asset_owner_name]

    filtered_dashboard = {**dashboard, "vehicles": vehicles}
    filtered_dashboard["total_fleet_investment"] = round(
        sum(_safe_float((vehicle.get("economics") or {}).get("investment", {}).get("total_vehicle_investment")) for vehicle in vehicles),
        2,
    )
    filtered_dashboard["total_recovered"] = round(
        sum(_safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("amount_recovered")) for vehicle in vehicles),
        2,
    )
    filtered_dashboard["remaining_recovery_balance"] = round(
        sum(_safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("remaining_balance")) for vehicle in vehicles),
        2,
    )
    filtered_dashboard["net_fleet_profit"] = round(
        sum(_safe_float((vehicle.get("economics") or {}).get("profitability", {}).get("net_profit")) for vehicle in vehicles),
        2,
    )
    filtered_dashboard["vehicles_recovering"] = len(
        [vehicle for vehicle in vehicles if ((vehicle.get("economics") or {}).get("recovery", {}).get("status") == "Recovering")]
    )
    filtered_dashboard["vehicles_fully_recovered"] = len(
        [vehicle for vehicle in vehicles if ((vehicle.get("economics") or {}).get("recovery", {}).get("status") == "Recovered")]
    )
    filtered_dashboard["vehicles_profit_generating"] = len(
        [vehicle for vehicle in vehicles if ((vehicle.get("economics") or {}).get("recovery", {}).get("status") == "Profit Generating")]
    )
    ranked = sorted(
        vehicles,
        key=lambda item: _safe_float((item.get("economics") or {}).get("profitability", {}).get("net_profit")),
        reverse=True,
    )
    filtered_dashboard["most_profitable_vehicle"] = ranked[0] if ranked else None
    filtered_dashboard["least_profitable_vehicle"] = ranked[-1] if ranked else None
    filtered_dashboard["total_managed_fleet"] = len(vehicles)
    filtered_dashboard["total_active_vehicles"] = len(
        [vehicle for vehicle in vehicles if (vehicle.get("status") or "").lower() in {"available", "assigned", "active"}]
    )
    filtered_dashboard["total_managed_fleet_value"] = round(
        sum(_safe_float((vehicle.get("economics") or {}).get("investment", {}).get("current_estimated_value")) for vehicle in vehicles),
        2,
    )
    portfolio_breakdown: dict[str, dict] = {}
    for vehicle in vehicles:
        owner_name = _normalize_string(vehicle.get("asset_owner_name")) or "Unspecified Owner"
        owner_entry = portfolio_breakdown.setdefault(
            owner_name,
            {
                "asset_owner_name": owner_name,
                "asset_owner_type": vehicle.get("asset_owner_type"),
                "vehicle_count": 0,
                "fleet_value": 0.0,
                "capital_basis_for_recovery": 0.0,
                "capital_recovered": 0.0,
                "outstanding_capital": 0.0,
                "revenue_generated": 0.0,
                "net_profit": 0.0,
            },
        )
        owner_entry["vehicle_count"] += 1
        owner_entry["fleet_value"] += _safe_float((vehicle.get("economics") or {}).get("investment", {}).get("current_estimated_value"))
        owner_entry["capital_basis_for_recovery"] += _safe_float((vehicle.get("economics") or {}).get("investment", {}).get("capital_basis_for_recovery"))
        owner_entry["capital_recovered"] += _safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("amount_recovered"))
        owner_entry["outstanding_capital"] += _safe_float((vehicle.get("economics") or {}).get("recovery", {}).get("remaining_balance"))
        owner_entry["revenue_generated"] += _safe_float((vehicle.get("economics") or {}).get("profitability", {}).get("gross_revenue"))
        owner_entry["net_profit"] += _safe_float((vehicle.get("economics") or {}).get("profitability", {}).get("net_profit"))
    filtered_dashboard["portfolio_breakdown"] = [
        {
            **entry,
            "fleet_value": round(entry["fleet_value"], 2),
            "capital_basis_for_recovery": round(entry["capital_basis_for_recovery"], 2),
            "capital_recovered": round(entry["capital_recovered"], 2),
            "outstanding_capital": round(entry["outstanding_capital"], 2),
            "revenue_generated": round(entry["revenue_generated"], 2),
            "net_profit": round(entry["net_profit"], 2),
            "roi_percent": round((entry["net_profit"] / entry["capital_basis_for_recovery"]) * 100, 2)
            if entry["capital_basis_for_recovery"] > 0
            else 0.0,
        }
        for entry in sorted(portfolio_breakdown.values(), key=lambda item: item["asset_owner_name"])
    ]
    return filtered_dashboard


def _optional_object_id(value: str | None):
    return ObjectId(value) if value and ObjectId.is_valid(value) else None


def _build_date_query(field_name: str, filters: dict):
    conditions = {}
    if filters["date_from"]:
        conditions["$gte"] = datetime.combine(filters["date_from"], time.min, tzinfo=timezone.utc)
    if filters["date_to"]:
        conditions["$lte"] = datetime.combine(filters["date_to"], time.max, tzinfo=timezone.utc)
    return {field_name: conditions} if conditions else {}


def _build_string_date_query(field_name: str, filters: dict):
    conditions = {}
    if filters["date_from"]:
        conditions["$gte"] = filters["date_from"].isoformat()
    if filters["date_to"]:
        conditions["$lte"] = filters["date_to"].isoformat()
    return {field_name: conditions} if conditions else {}


def _apply_common_filters(query: dict, *, filters: dict, driver_field: str | None = None, vehicle_field: str | None = None):
    driver_object_id = _optional_object_id(filters["driver_id"])
    vehicle_object_id = _optional_object_id(filters["vehicle_id"])
    if driver_field and driver_object_id:
        query[driver_field] = driver_object_id
    if vehicle_field and vehicle_object_id:
        query[vehicle_field] = vehicle_object_id
    return query


def _fetch_documents(collection, query: dict, projection: dict | None = None, *, sort_fields: list[tuple[str, int]] | None = None) -> list[dict]:
    cursor = collection.find(query, projection)
    if sort_fields:
        cursor = cursor.sort(sort_fields)
    return list(cursor)


def _sorted_distinct_strings(collection, field_name: str) -> list[str]:
    values = {
        normalized
        for raw in collection.distinct(field_name)
        if (normalized := _normalize_string(raw))
    }
    return sorted(values)


def _build_booking_datetime_or_string_query(filters: dict) -> dict:
    clauses = []
    datetime_query = _build_date_query("pickup_at", filters)
    string_query = _build_string_date_query("pickup_date", filters)
    if datetime_query:
        clauses.append(datetime_query)
    if string_query:
        clauses.append(string_query)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def _load_scoped_customer_ids(filters: dict) -> set[str]:
    booking_query = _apply_common_filters(
        _build_booking_datetime_or_string_query(filters),
        filters=filters,
        driver_field="driver_id",
        vehicle_field="vehicle_id",
    )
    ride_query = _apply_common_filters(
        _build_string_date_query("trip_date", filters),
        filters=filters,
        driver_field="driver_id",
        vehicle_field="vehicle_id",
    )
    customer_ids = {
        _id_string(customer_id)
        for customer_id in bookings_collection().distinct("customer_id", booking_query)
        if customer_id
    }
    customer_ids.update(
        _id_string(customer_id)
        for customer_id in rides_collection().distinct("customer_id", ride_query)
        if customer_id
    )
    return customer_ids


def _build_customer_query(filters: dict, scoped_customer_ids: set[str] | None = None) -> dict:
    query: dict = {}
    created_at_query = _build_date_query("created_at", filters)
    if created_at_query:
        query.update(created_at_query)

    if filters["creator_role"]:
        query["created_by_role"] = filters["creator_role"]
    if filters["customer_category_id"]:
        category_object_id = _optional_object_id(filters["customer_category_id"])
        query["customer_category_id"] = category_object_id or filters["customer_category_id"]
    if filters["source"]:
        query["source"] = filters["source"]

    if filters["driver_id"]:
        driver_object_id = _optional_object_id(filters["driver_id"])
        or_conditions = []
        if driver_object_id:
            or_conditions.extend(
                [
                    {"preferred_driver_id": driver_object_id},
                    {"created_by_driver_id": driver_object_id},
                ]
            )
        if scoped_customer_ids:
            scoped_object_ids = [ObjectId(customer_id) for customer_id in scoped_customer_ids if ObjectId.is_valid(customer_id)]
            if scoped_object_ids:
                or_conditions.append({"_id": {"$in": scoped_object_ids}})
        if not or_conditions:
            return {"_id": {"$in": []}}
        query["$or"] = or_conditions
    elif filters["vehicle_id"]:
        if not scoped_customer_ids:
            return {"_id": {"$in": []}}
        scoped_object_ids = [ObjectId(customer_id) for customer_id in scoped_customer_ids if ObjectId.is_valid(customer_id)]
        if not scoped_object_ids:
            return {"_id": {"$in": []}}
        query["_id"] = {"$in": scoped_object_ids}

    return query


def _log_finance_report_duration(*, started_at: float, category: str | None, filters: dict, selected_categories: set[str]) -> None:
    duration_ms = (perf_counter() - started_at) * 1000
    if duration_ms < 1500:
        return
    current_app.logger.warning(
        "[Flux Reports] SLOW finance report category=%s duration_ms=%.2f selected=%s driver_id=%s vehicle_id=%s branch=%s",
        category or "all",
        duration_ms,
        ",".join(sorted(selected_categories)),
        filters["driver_id"],
        filters["vehicle_id"],
        filters["branch"],
    )


def get_finance_reports(
    *,
    current_role: str,
    current_user_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    driver_id: str | None = None,
    vehicle_id: str | None = None,
    branch: str | None = None,
    category: str | None = None,
    asset_owner_name: str | None = None,
    creator_role: str | None = None,
    customer_category_id: str | None = None,
    source: str | None = None,
) -> dict:
    request_started_at = perf_counter()
    filters = _normalize_filters(
        date_from=date_from,
        date_to=date_to,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        branch=branch,
        asset_owner_name=asset_owner_name,
        creator_role=creator_role,
        customer_category_id=customer_category_id,
        source=source,
    )
    cache_key = build_cache_key(
        "finance_reports",
        role=current_role,
        user_id=current_user_id,
        date_from=date_from,
        date_to=date_to,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        branch=branch,
        category=category or "all",
        asset_owner_name=asset_owner_name or "",
        creator_role=creator_role or "",
        customer_category_id=customer_category_id or "",
        source=source or "",
    )
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    driver_documents = _fetch_documents(
        users_collection(),
        {"role": "driver"},
        REPORT_DRIVER_PROJECTION,
        sort_fields=[("full_name", ASCENDING)],
    )
    vehicle_documents = _fetch_documents(
        vehicles_collection(),
        {},
        REPORT_VEHICLE_PROJECTION,
        sort_fields=[("registration_number", ASCENDING)],
    )
    current_user = (
        users_collection().find_one({"_id": ObjectId(current_user_id)})
        if current_user_id and ObjectId.is_valid(current_user_id)
        else None
    )

    drivers_by_id = {str(document["_id"]): serialize_user(document) for document in driver_documents}
    vehicles_by_id = {
        str(document["_id"]): {
            "id": str(document["_id"]),
            "registration_number": document.get("registration_number"),
            "status": document.get("status"),
            "asset_owner_name": document.get("asset_owner_name"),
            "asset_owner_type": document.get("asset_owner_type"),
            "operating_fleet_name": document.get("operating_fleet_name"),
        }
        for document in vehicle_documents
    }
    branches = _sorted_distinct_strings(finance_accounts_collection(), "branch")
    active_filters = _active_filters_labels(filters, drivers_by_id=drivers_by_id, vehicles_by_id=vehicles_by_id)

    selected_categories = (
        {category}
        if category in {"revenue", "drivers", "vehicles", "trips", "fuel", "maintenance", "customers"}
        else {"revenue", "drivers", "vehicles", "trips", "fuel", "maintenance", "customers"}
    )
    reports = {
        "collections": _empty_section(active_filters),
        "deposits": _empty_section(active_filters),
        "expenses": _empty_section(active_filters),
        "fuel": {**_empty_section(active_filters), "total_litres": 0},
        "maintenance": _empty_section(active_filters),
        "faults": _empty_section(active_filters),
        "customers": _empty_section(active_filters),
        "bookings": {**_empty_section(active_filters), "status_breakdown": {}},
        "trip_logs": {
            **_empty_section(active_filters),
            "trips_by_platform": [],
            "trips_by_purpose": [],
        },
        "driver_performance": _empty_section(active_filters),
        "vehicle_performance": _empty_section(active_filters),
        "vehicle_economics": _empty_vehicle_economics(active_filters),
    }

    if "revenue" in selected_categories:
        if not filters["branch"]:
            collections_query = _apply_common_filters(
                {"status": "approved", **_build_string_date_query("collection_date", filters)},
                filters=filters,
                driver_field="driver_id",
                vehicle_field="vehicle_id",
            )
            collection_documents = _fetch_documents(
                collections_collection(),
                collections_query,
                REPORT_COLLECTION_PROJECTION,
                sort_fields=[("collection_date", DESCENDING), ("created_at", DESCENDING)],
            )
            reports["collections"] = _build_collections_report(
                collection_documents,
                filters=filters,
                drivers_by_id=drivers_by_id,
                vehicles_by_id=vehicles_by_id,
                active_filters=active_filters,
            )

        deposit_documents = _fetch_documents(
            deposits_collection(),
            {
                **_build_string_date_query("deposit_date", filters),
                **({"finance_account_snapshot.branch": filters["branch"]} if filters["branch"] else {}),
            },
            REPORT_DEPOSIT_PROJECTION,
            sort_fields=[("deposit_date", DESCENDING), ("created_at", DESCENDING)],
        )
        expenses_query = _apply_common_filters(
            {
                **_build_string_date_query("expense_date", filters),
                **({"finance_account_snapshot.branch": filters["branch"]} if filters["branch"] else {}),
            },
            filters=filters,
            driver_field="driver_id",
            vehicle_field="vehicle_id",
        )
        expense_documents = _fetch_documents(
            expenses_collection(),
            expenses_query,
            REPORT_EXPENSE_PROJECTION,
            sort_fields=[("expense_date", DESCENDING), ("created_at", DESCENDING)],
        )
        reports["deposits"] = _build_deposits_report(
            deposit_documents,
            filters=filters,
            active_filters=active_filters,
        )
        reports["expenses"] = _build_expenses_report(
            expense_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
        )

    if "fuel" in selected_categories and not filters["branch"]:
        fuel_query = _apply_common_filters(
            _build_string_date_query("fuel_date", filters),
            filters=filters,
            driver_field="driver_id",
            vehicle_field="vehicle_id",
        )
        fuel_documents = _fetch_documents(
            fuel_logs_collection(),
            fuel_query,
            REPORT_FUEL_PROJECTION,
            sort_fields=[("fuel_date", DESCENDING), ("created_at", DESCENDING)],
        )
        reports["fuel"] = _build_fuel_report(
            fuel_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
        )

    if "maintenance" in selected_categories and not filters["branch"]:
        maintenance_query = _apply_common_filters({}, filters=filters, driver_field="driver_id", vehicle_field="vehicle_id")
        fault_query = _apply_common_filters({}, filters=filters, driver_field="driver_id", vehicle_field="vehicle_id")
        maintenance_documents = _fetch_documents(
            maintenance_jobs_collection(),
            maintenance_query,
            REPORT_MAINTENANCE_PROJECTION,
            sort_fields=[("created_at", DESCENDING)],
        )
        fault_documents = _fetch_documents(
            faults_collection(),
            fault_query,
            REPORT_FAULT_PROJECTION,
            sort_fields=[("reported_at", DESCENDING), ("created_at", DESCENDING)],
        )
        reports["maintenance"] = _build_maintenance_report(
            maintenance_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
        )
        reports["faults"] = _build_fault_report(
            fault_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
        )

    if "customers" in selected_categories:
        scoped_customer_ids = _load_scoped_customer_ids(filters) if filters["driver_id"] or filters["vehicle_id"] else set()
        customer_documents = _fetch_documents(
            customers_collection(),
            _build_customer_query(filters, scoped_customer_ids),
            REPORT_CUSTOMER_PROJECTION,
            sort_fields=[("created_at", DESCENDING)],
        )
        reports["customers"] = _build_customer_report(
            customer_documents,
            filters=filters,
            active_filters=active_filters,
            scoped_customer_ids=scoped_customer_ids,
        )

    if "trips" in selected_categories and not filters["branch"]:
        booking_query = _apply_common_filters(
            {
                "is_recurring_template": False,
                **_build_booking_datetime_or_string_query(filters),
            },
            filters=filters,
            driver_field="driver_id",
            vehicle_field="vehicle_id",
        )
        ride_query = _apply_common_filters(
            _build_string_date_query("trip_date", filters),
            filters=filters,
            driver_field="driver_id",
            vehicle_field="vehicle_id",
        )
        booking_documents = _fetch_documents(
            bookings_collection(),
            booking_query,
            REPORT_BOOKING_PROJECTION,
            sort_fields=[("pickup_at", DESCENDING), ("created_at", DESCENDING)],
        )
        ride_documents = _fetch_documents(
            rides_collection(),
            ride_query,
            REPORT_RIDE_PROJECTION,
            sort_fields=[("trip_date", DESCENDING), ("created_at", DESCENDING)],
        )
        reports["bookings"] = _build_booking_report(
            booking_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
        )
        reports["trip_logs"] = _build_trip_report(
            ride_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
        )

    if "drivers" in selected_categories:
        reports["driver_performance"] = _build_driver_performance_report(
            current_user_id=current_user_id,
            current_role=current_role,
            filters=filters,
            active_filters=active_filters,
        )

    if "vehicles" in selected_categories:
        if not filters["branch"]:
            vehicle_ride_documents = _fetch_documents(
                rides_collection(),
                _apply_common_filters(
                    _build_string_date_query("trip_date", filters),
                    filters=filters,
                    driver_field="driver_id",
                    vehicle_field="vehicle_id",
                ),
                REPORT_RIDE_PROJECTION,
                sort_fields=[("trip_date", DESCENDING), ("created_at", DESCENDING)],
            )
            reports["vehicle_performance"] = _build_vehicle_performance_report(
                vehicle_ride_documents,
                vehicle_documents,
                filters=filters,
                active_filters=active_filters,
            )
        vehicle_economics_dashboard = _filter_economics_dashboard(
            get_vehicle_economics_dashboard(current_role=current_role),
            vehicle_id=filters["vehicle_id"],
            asset_owner_name=filters["asset_owner_name"],
        )
        if current_role == "admin" and not get_admin_role_permissions().get("view_reports"):
            vehicle_economics_dashboard["message"] = (
                "Financial report visibility is limited by owner settings. Operational vehicle cost data remains available."
            )
        vehicle_economics_dashboard["validation"] = {
            "total_records": len(vehicle_economics_dashboard.get("vehicles") or []),
            "total_amount": round(vehicle_economics_dashboard.get("net_fleet_profit") or 0, 2),
            "last_updated": now_utc().isoformat(),
            "active_filters": active_filters,
        }
        reports["vehicle_economics"] = vehicle_economics_dashboard

    customer_creator_roles = _sorted_distinct_strings(customers_collection(), "created_by_role")
    customer_categories = _sorted_distinct_strings(customers_collection(), "customer_category")
    customer_sources = _sorted_distinct_strings(customers_collection(), "source")
    customer_category_items = sorted(
        [
            {"id": _id_string(item["_id"]["id"]), "name": item["_id"]["name"]}
            for item in customers_collection().aggregate(
                [
                    {"$match": {"customer_category_id": {"$ne": None}, "customer_category": {"$ne": None}}},
                    {"$group": {"_id": {"id": "$customer_category_id", "name": "$customer_category"}}},
                    {"$sort": {"_id.name": 1}},
                ]
            )
            if item["_id"].get("id") and item["_id"].get("name")
        ],
        key=lambda item: item["name"],
    )

    result = {
        "generated_by": serialize_user(current_user) if current_user else None,
        "generated_at": now_utc().isoformat(),
        "filters": _active_filters_payload(filters),
        "available_filters": {
            "drivers": list(drivers_by_id.values()),
            "vehicles": list(vehicles_by_id.values()),
            "asset_owners": sorted(
                {
                    owner_name
                    for document in vehicle_documents
                    if (owner_name := _normalize_string(document.get("asset_owner_name")))
                }
            ),
            "branches": branches,
            "creator_roles": customer_creator_roles,
            "customer_categories": customer_categories,
            "customer_category_items": customer_category_items,
            "sources": customer_sources,
        },
        "reports": reports,
    }
    _log_finance_report_duration(
        started_at=request_started_at,
        category=category,
        filters=filters,
        selected_categories=selected_categories,
    )
    return set_ttl_cached(cache_key, result, ttl_seconds=15)
