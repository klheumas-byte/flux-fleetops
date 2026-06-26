from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId

from extensions import get_collection
from models.user import serialize_user
from services.driver_analytics_service import list_driver_analytics
from services.system_settings_service import get_admin_role_permissions
from services.vehicle_service import get_vehicle_economics_dashboard
from utils.api_error import ApiError
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


def now_utc():
    return datetime.now(timezone.utc)


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


def _build_booking_customer_scope(booking_documents: list[dict], ride_documents: list[dict], *, filters: dict):
    customer_ids = set()
    for document in booking_documents:
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"]) and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"]) and _date_in_range(document.get("pickup_at") or document.get("pickup_date"), filters["date_from"], filters["date_to"]):
            if document.get("customer_id"):
                customer_ids.add(_id_string(document.get("customer_id")))
    for document in ride_documents:
        if _matches_selected_id(document.get("driver_id"), filters["driver_id"]) and _matches_selected_id(document.get("vehicle_id"), filters["vehicle_id"]) and _date_in_range(document.get("trip_date"), filters["date_from"], filters["date_to"]):
            if document.get("customer_id"):
                customer_ids.add(_id_string(document.get("customer_id")))
    return customer_ids


def _build_customer_report(customer_documents: list[dict], booking_documents: list[dict], ride_documents: list[dict], *, filters: dict, active_filters: list[str]):
    scoped_customer_ids = _build_booking_customer_scope(booking_documents, ride_documents, filters=filters)
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

    driver_documents = list(users_collection().find({"role": "driver"}).sort("full_name", 1))
    vehicle_documents = list(vehicles_collection().find({}).sort("registration_number", 1))
    finance_accounts = list(finance_accounts_collection().find({}).sort("account_name", 1))
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
    branches = sorted(
        {
            branch_name
            for account in finance_accounts
            if (branch_name := _normalize_string(account.get("branch")))
        }
    )
    customer_documents = list(customers_collection().find({}))
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
        collections_query = _apply_common_filters(
            {"status": "approved", **_build_string_date_query("collection_date", filters)},
            filters=filters,
            driver_field="driver_id",
            vehicle_field="vehicle_id",
        )
        expenses_query = _apply_common_filters(
            _build_string_date_query("expense_date", filters),
            filters=filters,
            driver_field="driver_id",
            vehicle_field="vehicle_id",
        )
        collection_documents = list(collections_collection().find(collections_query))
        deposit_documents = list(deposits_collection().find(_build_string_date_query("deposit_date", filters)))
        expense_documents = list(expenses_collection().find(expenses_query))
        reports["collections"] = _build_collections_report(
            collection_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
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

    if "fuel" in selected_categories:
        fuel_query = _apply_common_filters(
            _build_string_date_query("fuel_date", filters),
            filters=filters,
            driver_field="driver_id",
            vehicle_field="vehicle_id",
        )
        fuel_documents = list(fuel_logs_collection().find(fuel_query))
        reports["fuel"] = _build_fuel_report(
            fuel_documents,
            filters=filters,
            drivers_by_id=drivers_by_id,
            vehicles_by_id=vehicles_by_id,
            active_filters=active_filters,
        )

    if "maintenance" in selected_categories:
        maintenance_query = _apply_common_filters({}, filters=filters, driver_field="driver_id", vehicle_field="vehicle_id")
        fault_query = _apply_common_filters({}, filters=filters, driver_field="driver_id", vehicle_field="vehicle_id")
        maintenance_documents = list(maintenance_jobs_collection().find(maintenance_query))
        fault_documents = list(faults_collection().find(fault_query))
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
        booking_documents = list(bookings_collection().find(_apply_common_filters({}, filters=filters, driver_field="driver_id", vehicle_field="vehicle_id")))
        ride_documents = list(rides_collection().find(_apply_common_filters(_build_string_date_query("trip_date", filters), filters=filters, driver_field="driver_id", vehicle_field="vehicle_id")))
        reports["customers"] = _build_customer_report(
            customer_documents,
            booking_documents,
            ride_documents,
            filters=filters,
            active_filters=active_filters,
        )

    if "trips" in selected_categories:
        booking_query = _apply_common_filters(
            {"is_recurring_template": False},
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
        booking_documents = list(bookings_collection().find(booking_query))
        ride_documents = list(rides_collection().find(ride_query))
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
        ride_documents = list(
            rides_collection().find(
                _apply_common_filters(
                    _build_string_date_query("trip_date", filters),
                    filters=filters,
                    driver_field="driver_id",
                    vehicle_field="vehicle_id",
                )
            )
        )
        reports["vehicle_performance"] = _build_vehicle_performance_report(
            ride_documents,
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
            "creator_roles": sorted(
                {
                    role
                    for document in customer_documents
                    if (role := _normalize_string(document.get("created_by_role")))
                }
            ),
            "customer_categories": sorted(
                {
                    document.get("customer_category")
                    for document in customer_documents
                    if document.get("customer_category")
                }
            ),
            "customer_category_items": sorted(
                [
                    {"id": item_id, "name": item_name}
                    for item_id, item_name in {
                        (
                            _id_string(document.get("customer_category_id")),
                            document.get("customer_category"),
                        )
                        for document in customer_documents
                        if document.get("customer_category") and document.get("customer_category_id")
                    }
                ],
                key=lambda item: item["name"],
            ),
            "sources": sorted(
                {
                    document.get("source")
                    for document in customer_documents
                    if document.get("source")
                }
            ),
        },
        "reports": reports,
    }
    return set_ttl_cached(cache_key, result, ttl_seconds=15)
