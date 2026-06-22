from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId

from extensions import get_collection
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.payment_cycle_service import get_weekly_cycle_window
from utils.api_error import ApiError


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def users_collection():
    return get_collection("users")


def assignments_collection():
    return get_collection("assignments")


def collections_collection():
    return get_collection("collections")


def fuel_logs_collection():
    return get_collection("fuel_logs")


def faults_collection():
    return get_collection("faults")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def vehicles_collection():
    return get_collection("vehicles")


def customers_collection():
    return get_collection("customers")


def bookings_collection():
    return get_collection("bookings")


def _to_object_id(value, field_name: str, *, required: bool = False) -> ObjectId | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _parse_date(value, field_name: str) -> date:
    if not value:
        raise ApiError(f"{field_name} is required.", status_code=400)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ApiError(f"{field_name} must be a valid YYYY-MM-DD date.", status_code=400) from exc


def _parse_date_optional(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _parse_datetime_optional(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _end_of_day(value: date) -> datetime:
    return datetime.combine(value, time.max, tzinfo=timezone.utc)


def _default_range() -> tuple[date, date]:
    week = get_weekly_cycle_window()
    return week["week_start_dt"].date(), week["week_end_dt"].date()


def _normalize_filters(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    vehicle_id: str | None = None,
    admin_id: str | None = None,
    branch: str | None = None,
) -> dict:
    default_start, default_end = _default_range()
    resolved_start = _parse_date(start_date, "start_date") if start_date else default_start
    resolved_end = _parse_date(end_date, "end_date") if end_date else default_end
    if resolved_start > resolved_end:
        raise ApiError("start_date cannot be later than end_date.", status_code=400)

    return {
        "start_date": resolved_start,
        "end_date": resolved_end,
        "vehicle_id": _to_object_id(vehicle_id, "vehicle_id") if vehicle_id else None,
        "admin_id": _to_object_id(admin_id, "admin_id") if admin_id else None,
        "branch": (branch or "").strip() or None,
    }


def _date_overlaps_range(
    candidate_start: date | None,
    candidate_end: date | None,
    range_start: date,
    range_end: date,
) -> bool:
    if candidate_start is None:
        return False
    effective_end = candidate_end or range_end
    return candidate_start <= range_end and effective_end >= range_start


def _week_starts_between(start_value: date, end_value: date) -> list[date]:
    cursor = start_value - timedelta(days=start_value.weekday())
    result: list[date] = []
    while cursor <= end_value:
        result.append(cursor)
        cursor += timedelta(days=7)
    return result


def _count_assignment_weeks_in_range(assignment_document: dict, range_start: date, range_end: date) -> int:
    assignment_start = _parse_date_optional(assignment_document.get("start_date"))
    assignment_end = _parse_date_optional(assignment_document.get("end_date"))
    if not _date_overlaps_range(assignment_start, assignment_end, range_start, range_end):
        return 0

    effective_start = max(assignment_start, range_start)
    effective_end = min(assignment_end or range_end, range_end)
    week_starts = _week_starts_between(effective_start, effective_end)
    count = 0
    for week_start in week_starts:
        week_end = week_start + timedelta(days=5)
        if week_start <= effective_end and week_end >= effective_start:
            count += 1
    return count


def _maintenance_days_in_range(job_document: dict, range_start: date, range_end: date) -> int:
    start_value = (
        _parse_date_optional(job_document.get("start_date"))
        or _parse_date_optional(job_document.get("created_at"))
    )
    if start_value is None:
        return 0

    end_value = _parse_date_optional(job_document.get("completion_date"))
    if end_value is None and job_document.get("status") not in {"completed", "cancelled"}:
        end_value = range_end
    if end_value is None:
        end_value = start_value

    if end_value < range_start or start_value > range_end:
        return 0

    effective_start = max(start_value, range_start)
    effective_end = min(end_value, range_end)
    return max((effective_end - effective_start).days + 1, 0)


def _collection_in_range(collection_document: dict, start_dt: datetime, end_dt: datetime) -> bool:
    collection_dt = _parse_datetime_optional(collection_document.get("collection_date"))
    if collection_dt is None:
        collection_dt = collection_document.get("created_at")
    if collection_dt is None:
        return False
    collection_dt = collection_dt if collection_dt.tzinfo else collection_dt.replace(tzinfo=timezone.utc)
    return start_dt <= collection_dt <= end_dt


def _datetime_in_range(value, start_dt: datetime, end_dt: datetime) -> bool:
    candidate = _parse_datetime_optional(value)
    if candidate is None:
        return False
    return start_dt <= candidate <= end_dt


def _resolve_driver_scope(current_user_id: str, current_role: str) -> list[dict]:
    if current_role == "driver":
        driver = users_collection().find_one(
            {"_id": _to_object_id(current_user_id, "current_user_id", required=True), "role": "driver"}
        )
        if not driver:
            raise ApiError("Driver not found.", status_code=404)
        return [driver]

    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to view driver analytics.", status_code=403)

    return list(users_collection().find({"role": "driver"}).sort("full_name", 1))


def _get_admin_vehicle_ids(admin_object_id: ObjectId) -> set[ObjectId]:
    vehicle_ids: set[ObjectId] = set()
    for assignment in assignments_collection().find({"assigned_by": admin_object_id}):
        vehicle_id = assignment.get("vehicle_id")
        if isinstance(vehicle_id, ObjectId):
            vehicle_ids.add(vehicle_id)
    for job in maintenance_jobs_collection().find({"maintenance_coordinator_id": admin_object_id}):
        vehicle_id = job.get("vehicle_id")
        if isinstance(vehicle_id, ObjectId):
            vehicle_ids.add(vehicle_id)
    for collection in collections_collection().find(
        {"$or": [{"approved_by_admin_id": admin_object_id}, {"received_by_admin_id": admin_object_id}]}
    ):
        vehicle_id = collection.get("vehicle_id")
        if isinstance(vehicle_id, ObjectId):
            vehicle_ids.add(vehicle_id)
    return vehicle_ids


def _serialize_driver_analytics(
    *,
    driver_document: dict,
    filters: dict,
    global_avg_cost_per_km: float | None,
) -> dict:
    start_date = filters["start_date"]
    end_date = filters["end_date"]
    start_dt = _start_of_day(start_date)
    end_dt = _end_of_day(end_date)
    vehicle_filter = filters["vehicle_id"]

    assignments = list(
        assignments_collection()
        .find({"driver_id": driver_document["_id"]})
        .sort("start_date", -1)
    )
    if vehicle_filter:
        assignments = [item for item in assignments if item.get("vehicle_id") == vehicle_filter]

    vehicle_documents: dict[ObjectId, dict] = {}
    for assignment in assignments:
        vehicle_id = assignment.get("vehicle_id")
        if isinstance(vehicle_id, ObjectId) and vehicle_id not in vehicle_documents:
            vehicle = vehicles_collection().find_one({"_id": vehicle_id})
            if vehicle:
                vehicle_documents[vehicle_id] = vehicle

    active_assignment = next((item for item in assignments if item.get("status") == "active"), None)
    if active_assignment is None and assignments:
        active_assignment = assignments[0]

    weekly_target = 0.0
    for assignment in assignments:
        weekly_target += _count_assignment_weeks_in_range(assignment, start_date, end_date) * float(
            assignment.get("weekly_target") or 0
        )
    weekly_target = round(weekly_target, 2)

    collections = list(collections_collection().find({"driver_id": driver_document["_id"]}))
    if vehicle_filter:
        collections = [item for item in collections if item.get("vehicle_id") == vehicle_filter]
    collections = [item for item in collections if _collection_in_range(item, start_dt, end_dt)]

    amount_collected = round(
        sum(float(item.get("amount") or 0) for item in collections if item.get("status") == "approved"),
        2,
    )
    outstanding_balance = round(max(weekly_target - amount_collected, 0), 2)
    target_achievement_percentage = round(
        (amount_collected / weekly_target * 100) if weekly_target > 0 else 0,
        2,
    )
    late_payment_documents = [
        item
        for item in collections
        if item.get("status") in {"pending", "submitted", "received", "approved"} and item.get("is_late")
    ]

    fuel_logs = list(fuel_logs_collection().find({"driver_id": driver_document["_id"]}))
    if vehicle_filter:
        fuel_logs = [item for item in fuel_logs if item.get("vehicle_id") == vehicle_filter]
    fuel_logs = [item for item in fuel_logs if _datetime_in_range(item.get("fuel_date"), start_dt, end_dt)]
    approved_fuel_logs = [item for item in fuel_logs if item.get("status") == "approved"]
    fuel_spend = round(sum(float(item.get("amount") or 0) for item in approved_fuel_logs), 2)
    fuel_costs_per_km = [
        float(item.get("cost_per_km"))
        for item in approved_fuel_logs
        if item.get("cost_per_km") not in (None, 0)
    ]
    average_fuel_cost_per_km = round(
        (sum(fuel_costs_per_km) / len(fuel_costs_per_km)) if fuel_costs_per_km else 0,
        4,
    )

    faults = list(faults_collection().find({"driver_id": driver_document["_id"]}))
    if vehicle_filter:
        faults = [item for item in faults if item.get("vehicle_id") == vehicle_filter]
    faults = [item for item in faults if _datetime_in_range(item.get("reported_at"), start_dt, end_dt)]
    critical_faults = [item for item in faults if item.get("severity") == "critical"]

    maintenance_jobs = list(maintenance_jobs_collection().find({"driver_id": driver_document["_id"]}))
    if vehicle_filter:
        maintenance_jobs = [item for item in maintenance_jobs if item.get("vehicle_id") == vehicle_filter]
    maintenance_jobs = [
        item
        for item in maintenance_jobs
        if _date_overlaps_range(
            _parse_date_optional(item.get("start_date")) or _parse_date_optional(item.get("created_at")),
            _parse_date_optional(item.get("completion_date")),
            start_date,
            end_date,
        )
    ]
    maintenance_days_lost = sum(_maintenance_days_in_range(item, start_date, end_date) for item in maintenance_jobs)

    active_assignment_status = active_assignment.get("status") if active_assignment else "no_assignment"
    payment_consistency_percentage = round(
        (
            ((len(collections) - len(late_payment_documents)) / len(collections)) * 100
            if collections
            else 100
        ),
        2,
    )
    fuel_efficiency_score = 60.0
    if average_fuel_cost_per_km > 0 and global_avg_cost_per_km and global_avg_cost_per_km > 0:
        fuel_efficiency_score = round(
            max(min((global_avg_cost_per_km / average_fuel_cost_per_km) * 100, 100), 0),
            2,
        )
    elif approved_fuel_logs:
        fuel_efficiency_score = 75.0

    reliability_score = max(
        0.0,
        100.0 - (len(faults) * 6.0) - (len(critical_faults) * 18.0) - (maintenance_days_lost * 1.5),
    )
    assignment_score_map = {
        "active": 100.0,
        "suspended": 70.0,
        "ended": 45.0,
        "no_assignment": 20.0,
    }
    assignment_score = assignment_score_map.get(active_assignment_status, 50.0)

    overall_driver_score = round(
        (
            target_achievement_percentage * 0.45
            + payment_consistency_percentage * 0.2
            + fuel_efficiency_score * 0.15
            + reliability_score * 0.1
            + assignment_score * 0.1
        ),
        2,
    )

    generated_customers = [
        customer
        for customer in customers_collection().find(
            {
                "$or": [
                    {"created_by_driver_id": driver_document["_id"]},
                    {"created_by_user_id": driver_document["_id"]},
                    {"created_by": driver_document["_id"]},
                ]
            }
        )
        if (created_at := _parse_datetime_optional(customer.get("created_at"))) and start_dt <= created_at <= end_dt
    ]
    generated_customer_ids = {customer["_id"] for customer in generated_customers}
    generated_bookings = []
    if generated_customer_ids:
        generated_bookings = list(bookings_collection().find({"customer_id": {"$in": list(generated_customer_ids)}}))
        if vehicle_filter:
            generated_bookings = [
                booking for booking in generated_bookings if booking.get("vehicle_id") == vehicle_filter
            ]
        generated_bookings = [
            booking
            for booking in generated_bookings
            if _datetime_in_range(booking.get("pickup_at") or booking.get("created_at"), start_dt, end_dt)
        ]
    recurring_customer_ids = {
        booking.get("customer_id")
        for booking in generated_bookings
        if booking.get("customer_id")
        and (
            booking.get("is_recurring_template")
            or str(booking.get("booking_type") or "").lower() == "scheduled booking"
        )
    }
    scheduled_customer_ids = {
        booking.get("customer_id")
        for booking in generated_bookings
        if booking.get("customer_id") and not booking.get("is_recurring_template")
    }
    business_leads_captured = len(
        [
            customer
            for customer in generated_customers
            if customer.get("is_business_lead") or (customer.get("source") or "").lower() == "business_lead"
        ]
    )

    vehicle_document = None
    if active_assignment and active_assignment.get("vehicle_id") in vehicle_documents:
        vehicle_document = vehicle_documents[active_assignment.get("vehicle_id")]
    elif vehicle_filter and vehicle_filter in vehicle_documents:
        vehicle_document = vehicle_documents[vehicle_filter]

    return {
        "driver": serialize_user(driver_document),
        "vehicle": serialize_vehicle(vehicle_document) if vehicle_document else None,
        "weekly_target": weekly_target,
        "amount_collected": amount_collected,
        "outstanding_balance": outstanding_balance,
        "target_achievement_percentage": target_achievement_percentage,
        "number_of_late_payments": len(late_payment_documents),
        "payment_consistency_percentage": payment_consistency_percentage,
        "fuel_spend": fuel_spend,
        "fuel_logs_count": len(approved_fuel_logs),
        "average_fuel_cost_per_km": average_fuel_cost_per_km,
        "fuel_efficiency_score": round(fuel_efficiency_score, 2),
        "number_of_fault_reports": len(faults),
        "number_of_critical_faults": len(critical_faults),
        "maintenance_days_lost": maintenance_days_lost,
        "customers_generated": len(generated_customers),
        "recurring_customers": len(recurring_customer_ids),
        "scheduled_customers": len(scheduled_customer_ids),
        "business_leads_captured": business_leads_captured,
        "active_assignment_status": active_assignment_status,
        "overall_driver_score": overall_driver_score,
        "score_breakdown": {
            "target_score": target_achievement_percentage,
            "payment_score": payment_consistency_percentage,
            "fuel_score": round(fuel_efficiency_score, 2),
            "reliability_score": round(reliability_score, 2),
            "assignment_score": assignment_score,
        },
        "detail": {
            "active_assignment": {
                "id": str(active_assignment["_id"]),
                "weekly_target": float(active_assignment.get("weekly_target") or 0),
                "daily_target": float(active_assignment.get("daily_target") or 0),
                "start_date": active_assignment.get("start_date"),
                "end_date": active_assignment.get("end_date"),
                "status": active_assignment.get("status"),
            }
            if active_assignment
            else None,
            "recent_collections": [
                {
                    "id": str(item["_id"]),
                    "collection_date": item.get("collection_date"),
                    "amount": float(item.get("amount") or 0),
                    "status": item.get("status"),
                    "is_late": bool(item.get("is_late")),
                    "payment_method": item.get("payment_method"),
                }
                for item in sorted(
                    collections,
                    key=lambda entry: (
                        str(entry.get("collection_date") or ""),
                        str(entry.get("created_at") or ""),
                    ),
                    reverse=True,
                )[:5]
            ],
            "recent_fuel_logs": [
                {
                    "id": str(item["_id"]),
                    "fuel_date": item.get("fuel_date"),
                    "amount": float(item.get("amount") or 0),
                    "cost_per_km": item.get("cost_per_km"),
                    "status": item.get("status"),
                }
                for item in sorted(
                    approved_fuel_logs,
                    key=lambda entry: (
                        str(entry.get("fuel_date") or ""),
                        str(entry.get("created_at") or ""),
                    ),
                    reverse=True,
                )[:5]
            ],
            "fault_history": [
                {
                    "id": str(item["_id"]),
                    "reported_at": item.get("reported_at").isoformat() if item.get("reported_at") else None,
                    "severity": item.get("severity"),
                    "status": item.get("status"),
                    "description": item.get("description"),
                }
                for item in sorted(
                    faults,
                    key=lambda entry: entry.get("reported_at") or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )[:5]
            ],
            "maintenance_summary": {
                "jobs_count": len(maintenance_jobs),
                "days_lost": maintenance_days_lost,
            },
            "recent_generated_customers": [
                {
                    "id": str(customer["_id"]),
                    "full_name": customer.get("full_name"),
                    "source": customer.get("source"),
                    "created_at": customer.get("created_at").isoformat() if customer.get("created_at") else None,
                }
                for customer in sorted(
                    generated_customers,
                    key=lambda entry: entry.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True,
                )[:5]
            ],
        },
    }


def _global_average_cost_per_km(drivers: list[dict], filters: dict) -> float | None:
    start_dt = _start_of_day(filters["start_date"])
    end_dt = _end_of_day(filters["end_date"])
    vehicle_filter = filters["vehicle_id"]
    driver_ids = [item["_id"] for item in drivers]
    query: dict = {
        "driver_id": {"$in": driver_ids},
        "status": "approved",
    }
    if vehicle_filter:
        query["vehicle_id"] = vehicle_filter
    values = [
        float(item.get("cost_per_km"))
        for item in fuel_logs_collection().find(query)
        if item.get("cost_per_km") not in (None, 0)
        and _datetime_in_range(item.get("fuel_date"), start_dt, end_dt)
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _available_filter_options() -> dict:
    vehicles = [
        serialize_vehicle(vehicle)
        for vehicle in vehicles_collection().find({}).sort("registration_number", 1)
    ]
    admins = [
        serialize_user(admin)
        for admin in users_collection().find({"role": {"$in": ["owner", "admin"]}}).sort("full_name", 1)
    ]
    return {
        "vehicles": vehicles,
        "admins": admins,
        "branches": [],
    }


def list_driver_analytics(
    *,
    current_user_id: str,
    current_role: str,
    start_date: str | None = None,
    end_date: str | None = None,
    vehicle_id: str | None = None,
    admin_id: str | None = None,
    branch: str | None = None,
) -> dict:
    filters = _normalize_filters(
        start_date=start_date,
        end_date=end_date,
        vehicle_id=vehicle_id,
        admin_id=admin_id,
        branch=branch,
    )
    drivers = _resolve_driver_scope(current_user_id, current_role)
    global_avg_cost = _global_average_cost_per_km(drivers, filters)
    records = [
        _serialize_driver_analytics(
            driver_document=driver,
            filters=filters,
            global_avg_cost_per_km=global_avg_cost,
        )
        for driver in drivers
    ]

    if filters["admin_id"]:
        allowed_vehicle_ids = _get_admin_vehicle_ids(filters["admin_id"])
        records = [
            item
            for item in records
            if (
                item.get("vehicle")
                and ObjectId(item["vehicle"]["id"]) in allowed_vehicle_ids
            )
            or any(
                assignment.get("assigned_by") == filters["admin_id"]
                for assignment in assignments_collection().find({"driver_id": _to_object_id(item["driver"]["id"], "driver_id", required=True)})
            )
        ]

    records.sort(
        key=lambda item: (
            -item["overall_driver_score"],
            -item["target_achievement_percentage"],
            item["driver"]["full_name"] or "",
        )
    )

    return {
        "drivers": records,
        "filters": {
            "start_date": filters["start_date"].isoformat(),
            "end_date": filters["end_date"].isoformat(),
            "vehicle_id": str(filters["vehicle_id"]) if filters["vehicle_id"] else None,
            "admin_id": str(filters["admin_id"]) if filters["admin_id"] else None,
            "branch": filters["branch"],
        },
        "available_filters": _available_filter_options(),
        "score_formula": {
            "target_score_weight": 0.45,
            "payment_score_weight": 0.2,
            "fuel_score_weight": 0.15,
            "reliability_score_weight": 0.1,
            "assignment_score_weight": 0.1,
        },
    }


def get_driver_analytics_detail(
    *,
    current_user_id: str,
    current_role: str,
    driver_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    vehicle_id: str | None = None,
    admin_id: str | None = None,
    branch: str | None = None,
) -> dict:
    analytics = list_driver_analytics(
        current_user_id=current_user_id,
        current_role=current_role,
        start_date=start_date,
        end_date=end_date,
        vehicle_id=vehicle_id,
        admin_id=admin_id,
        branch=branch,
    )
    if current_role == "driver" and current_user_id != driver_id:
        raise ApiError("You do not have permission to view this driver performance record.", status_code=403)

    target = next((item for item in analytics["drivers"] if item["driver"]["id"] == driver_id), None)
    if target is None:
        raise ApiError("Driver analytics not found.", status_code=404)
    return {
        "driver_performance": target,
        "filters": analytics["filters"],
        "score_formula": analytics["score_formula"],
    }


def get_driver_analytics_leaderboard(
    *,
    current_user_id: str,
    current_role: str,
    start_date: str | None = None,
    end_date: str | None = None,
    vehicle_id: str | None = None,
    admin_id: str | None = None,
    branch: str | None = None,
) -> dict:
    analytics = list_driver_analytics(
        current_user_id=current_user_id,
        current_role=current_role,
        start_date=start_date,
        end_date=end_date,
        vehicle_id=vehicle_id,
        admin_id=admin_id,
        branch=branch,
    )
    leaderboard = []
    for index, record in enumerate(analytics["drivers"], start=1):
        leaderboard.append(
            {
                "rank": index,
                "driver": record["driver"],
                "vehicle": record.get("vehicle"),
                "overall_driver_score": record["overall_driver_score"],
                "target_achievement_percentage": record["target_achievement_percentage"],
                "payment_consistency_percentage": record["payment_consistency_percentage"],
                "fuel_efficiency_score": record["fuel_efficiency_score"],
                "number_of_critical_faults": record["number_of_critical_faults"],
                "maintenance_days_lost": record["maintenance_days_lost"],
                "customers_generated": record["customers_generated"],
                "recurring_customers": record["recurring_customers"],
                "scheduled_customers": record["scheduled_customers"],
                "business_leads_captured": record["business_leads_captured"],
            }
        )
    return {
        "leaderboard": leaderboard,
        "filters": analytics["filters"],
    }
