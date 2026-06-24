from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from time import perf_counter

from flask import current_app

from extensions import get_collection
from services.payment_cycle_service import APPROVED_PAYMENT_STATUSES, get_weekly_cycle_window
from services.system_settings_service import get_admin_role_permissions, should_include_fuel_in_profitability
from services.vehicle_service import _matches_company_expense, get_vehicle_economics_dashboard
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached


ACTIVE_VEHICLE_STATUSES = {"active", "available", "assigned"}
ACTIVE_TRIP_BOOKING_STATUSES = {"Acknowledged", "En Route", "Picked Up"}
ACTIVE_RIDE_STATUSES = {"Scheduled"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def assignments_collection():
    return get_collection("assignments")


def collections_collection():
    return get_collection("collections")


def fuel_logs_collection():
    return get_collection("fuel_logs")


def expenses_collection():
    return get_collection("expenses")


def rides_collection():
    return get_collection("rides")


def bookings_collection():
    return get_collection("bookings")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def preventive_maintenance_collection():
    return get_collection("preventive_maintenance")


def compliance_records_collection():
    return get_collection("vehicle_compliance_records")


def incidents_collection():
    return get_collection("incidents")


def _safe_float(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return round(float(value), 2)


def _parse_iso_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _parse_iso_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = _parse_iso_datetime(value)
    return parsed.date() if parsed else None


def _format_currency(value: float) -> str:
    return f"GHS {value:,.2f}"


def _format_relative_time(value) -> str:
    parsed = _parse_iso_datetime(value)
    if not parsed:
        return "Unknown time"
    delta = now_utc() - parsed
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hr ago"
    days = seconds // 86400
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def _load_vehicle_lookup() -> dict[str, str]:
    cache_key = "dashboard:vehicle_lookup"
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    started_at = perf_counter()
    vehicles = list(
        vehicles_collection().find(
            {},
            {"registration_number": 1, "make": 1, "model": 1},
        )
    )
    log_db_duration("dashboard.vehicle_lookup", started_at)
    lookup = {
        str(vehicle["_id"]): vehicle.get("registration_number")
        or " ".join(filter(None, [vehicle.get("make"), vehicle.get("model")])).strip()
        or "Vehicle"
        for vehicle in vehicles
    }
    return set_ttl_cached(cache_key, lookup, ttl_seconds=60)


def _load_driver_lookup() -> dict[str, str]:
    cache_key = "dashboard:driver_lookup"
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    started_at = perf_counter()
    drivers = list(
        users_collection().find(
            {"role": "driver"},
            {"full_name": 1},
        )
    )
    log_db_duration("dashboard.driver_lookup", started_at)
    lookup = {
        str(driver["_id"]): driver.get("full_name") or "Driver"
        for driver in drivers
    }
    return set_ttl_cached(cache_key, lookup, ttl_seconds=60)


def _empty_owner_fleet_economics_summary() -> dict:
    return {
        "total_fleet_investment": 0.0,
        "total_capital_recovered": 0.0,
        "outstanding_capital": 0.0,
        "fleet_roi_percent": 0.0,
        "total_revenue_collected": 0.0,
        "net_revenue": 0.0,
        "top_vehicle_profitability": {
            "vehicle_id": None,
            "vehicle": "No vehicle data yet",
            "registration_number": None,
            "net_profit": 0.0,
            "gross_revenue": 0.0,
            "roi_percent": 0.0,
        },
    }


def _empty_owner_fleet_risk_summary(*, vehicles_due_service: int = 0) -> dict:
    return {
        "vehicles_due_service": vehicles_due_service,
        "open_incidents": 0,
        "open_claims": 0,
        "expired_compliance_count": 0,
    }


def _build_owner_fleet_summaries(*, vehicles_due_service: int, net_revenue: float, today: date) -> tuple[dict, dict]:
    fleet_economics_summary = _empty_owner_fleet_economics_summary()
    fleet_risk_summary = _empty_owner_fleet_risk_summary(vehicles_due_service=vehicles_due_service)

    economics_started_at = perf_counter()
    economics_dashboard = get_vehicle_economics_dashboard(current_role="owner")
    log_db_duration("dashboard.owner_fleet_economics", economics_started_at)

    total_fleet_investment = round(_safe_float(economics_dashboard.get("total_fleet_investment")), 2)
    total_capital_recovered = round(_safe_float(economics_dashboard.get("total_recovered")), 2)
    outstanding_capital = round(_safe_float(economics_dashboard.get("remaining_recovery_balance")), 2)
    top_vehicle = economics_dashboard.get("most_profitable_vehicle") or {}
    top_vehicle_profitability = (top_vehicle.get("economics") or {}).get("profitability") or {}
    total_revenue_collected = round(
        sum(
            _safe_float((vehicle.get("economics") or {}).get("profitability", {}).get("gross_revenue"))
            for vehicle in (economics_dashboard.get("vehicles") or [])
        ),
        2,
    )
    fleet_roi_percent = round((net_revenue / total_fleet_investment) * 100, 2) if total_fleet_investment > 0 else 0.0

    fleet_economics_summary = {
        "total_fleet_investment": total_fleet_investment,
        "total_capital_recovered": total_capital_recovered,
        "outstanding_capital": outstanding_capital,
        "fleet_roi_percent": fleet_roi_percent,
        "total_revenue_collected": total_revenue_collected,
        "net_revenue": round(net_revenue, 2),
        "top_vehicle_profitability": {
            "vehicle_id": top_vehicle.get("id"),
            "vehicle": top_vehicle.get("registration_number") or "No vehicle data yet",
            "registration_number": top_vehicle.get("registration_number"),
            "net_profit": round(_safe_float(top_vehicle_profitability.get("net_profit")), 2),
            "gross_revenue": round(_safe_float(top_vehicle_profitability.get("gross_revenue")), 2),
            "roi_percent": round(_safe_float(top_vehicle_profitability.get("roi")), 2),
        },
    }

    incidents_started_at = perf_counter()
    open_incidents = incidents_collection().count_documents(
        {"status": {"$nin": ["resolved", "rejected", "closed"]}}
    )
    open_claims = incidents_collection().count_documents(
        {"claim_status": {"$in": ["under_review", "submitted", "assessment_scheduled", "approved", "partially_paid"]}}
    )
    log_db_duration("dashboard.owner_fleet_incidents", incidents_started_at)

    compliance_started_at = perf_counter()
    expired_compliance_count = compliance_records_collection().count_documents(
        {
            "status": {"$ne": "inactive"},
            "$or": [
                {"status": "expired"},
                {"expiry_date": {"$lt": today.isoformat()}},
            ],
        }
    )
    log_db_duration("dashboard.owner_fleet_compliance", compliance_started_at)

    fleet_risk_summary = {
        "vehicles_due_service": int(vehicles_due_service or 0),
        "open_incidents": int(open_incidents or 0),
        "open_claims": int(open_claims or 0),
        "expired_compliance_count": int(expired_compliance_count or 0),
    }
    return fleet_economics_summary, fleet_risk_summary


def get_dashboard_summary(*, current_role: str) -> dict:
    cache_key = build_cache_key("dashboard_summary", current_role=current_role)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    request_started_at = perf_counter()
    current_app.logger.info("[Flux Dashboard] summary requested role=%s", current_role)

    week_window = get_weekly_cycle_window()
    week_start = week_window["week_start_dt"]
    week_end = week_window["week_end_dt"] + timedelta(seconds=1)
    today = now_utc().date()
    today_iso = today.isoformat()
    include_fuel_in_profitability = should_include_fuel_in_profitability()
    admin_permissions = get_admin_role_permissions() if current_role == "admin" else {}

    vehicle_lookup = _load_vehicle_lookup()
    driver_lookup = _load_driver_lookup()

    vehicles_started_at = perf_counter()
    total_vehicles = vehicles_collection().count_documents({})
    active_vehicles = vehicles_collection().count_documents({"status": {"$in": list(ACTIVE_VEHICLE_STATUSES)}})
    log_db_duration("dashboard.vehicle_counts", vehicles_started_at)

    drivers_started_at = perf_counter()
    active_drivers = users_collection().count_documents({"role": "driver", "status": "active"})
    log_db_duration("dashboard.driver_counts", drivers_started_at)

    assignments_started_at = perf_counter()
    active_assignments = list(
        assignments_collection().find(
            {"status": "active"},
            {"driver_id": 1, "vehicle_id": 1, "weekly_target": 1, "daily_target": 1, "start_date": 1},
        )
    )
    log_db_duration("dashboard.active_assignments", assignments_started_at)
    weekly_revenue_target = round(sum(_safe_float(item.get("weekly_target")) for item in active_assignments), 2)
    daily_revenue_target = round(
        sum(
            _safe_float(item.get("daily_target")) or (_safe_float(item.get("weekly_target")) / 7 if _safe_float(item.get("weekly_target")) else 0)
            for item in active_assignments
        ),
        2,
    )

    collections_started_at = perf_counter()
    approved_collections = list(
        collections_collection().find(
            {
                "status": {"$in": list(APPROVED_PAYMENT_STATUSES)},
                "collection_date": {
                    "$gte": week_window["week_start"],
                    "$lte": week_window["week_end"],
                },
            },
            {
                "amount": 1,
                "vehicle_id": 1,
                "driver_id": 1,
                "assignment_id": 1,
                "collection_date": 1,
                "status": 1,
                "created_at": 1,
            },
        ).sort([("collection_date", -1), ("created_at", -1)])
    )
    recent_collection_documents = list(
        collections_collection().find(
            {},
            {
                "amount": 1,
                "vehicle_id": 1,
                "driver_id": 1,
                "collection_date": 1,
                "status": 1,
                "created_at": 1,
            },
        ).sort([("created_at", -1)]).limit(5)
    )
    log_db_duration("dashboard.collections", collections_started_at)

    approved_total_this_week = round(sum(_safe_float(item.get("amount")) for item in approved_collections), 2)
    outstanding_balance = round(max(weekly_revenue_target - approved_total_this_week, 0), 2)

    collections_by_assignment: dict[str, float] = defaultdict(float)
    collections_by_vehicle: dict[str, float] = defaultdict(float)
    collections_by_day: dict[str, float] = defaultdict(float)
    for item in approved_collections:
        assignment_id = str(item.get("assignment_id")) if item.get("assignment_id") else None
        vehicle_id = str(item.get("vehicle_id")) if item.get("vehicle_id") else None
        amount = _safe_float(item.get("amount"))
        if assignment_id:
            collections_by_assignment[assignment_id] += amount
        if vehicle_id:
            collections_by_vehicle[vehicle_id] += amount
        collection_date = _parse_iso_date(item.get("collection_date"))
        if collection_date:
            collections_by_day[collection_date.isoformat()] += amount

    fuel_started_at = perf_counter()
    approved_fuel_logs = list(
        fuel_logs_collection().find(
            {
                "status": "approved",
                "fuel_date": {
                    "$gte": week_window["week_start"],
                    "$lte": week_window["week_end"],
                },
            },
            {
                "vehicle_id": 1,
                "driver_id": 1,
                "amount": 1,
                "fuel_date": 1,
                "created_at": 1,
            },
        ).sort([("fuel_date", -1), ("created_at", -1)])
    )
    recent_fuel_logs = list(
        fuel_logs_collection().find(
            {},
            {
                "vehicle_id": 1,
                "driver_id": 1,
                "amount": 1,
                "fuel_date": 1,
                "created_at": 1,
            },
        ).sort([("created_at", -1)]).limit(4)
    )
    log_db_duration("dashboard.fuel_logs", fuel_started_at)
    fuel_spend = round(sum(_safe_float(item.get("amount")) for item in approved_fuel_logs), 2)

    expenses_started_at = perf_counter()
    approved_expenses = list(
        expenses_collection().find(
            {
                "status": {"$in": ["approved", "paid"]},
                "expense_date": {
                    "$gte": week_window["week_start"],
                    "$lte": week_window["week_end"],
                },
            },
            {
                "vehicle_id": 1,
                "driver_id": 1,
                "expense_title": 1,
                "expense_category": 1,
                "amount": 1,
                "expense_date": 1,
                "created_at": 1,
                "notes": 1,
            },
        )
    )
    log_db_duration("dashboard.expenses", expenses_started_at)
    company_expenses = [item for item in approved_expenses if _matches_company_expense(item)]
    company_expense_total = round(sum(_safe_float(item.get("amount")) for item in company_expenses), 2)

    maintenance_started_at = perf_counter()
    maintenance_jobs = list(
        maintenance_jobs_collection().find(
            {},
            {
                "vehicle_id": 1,
                "title": 1,
                "maintenance_type": 1,
                "priority": 1,
                "status": 1,
                "target_completion_date": 1,
                "current_stage": 1,
                "actual_cost": 1,
                "estimated_cost": 1,
                "start_date": 1,
                "created_at": 1,
                "updated_at": 1,
            },
        ).sort([("created_at", -1)])
    )
    log_db_duration("dashboard.maintenance_jobs", maintenance_started_at)
    weekly_maintenance_cost = round(
        sum(
            _safe_float(job.get("actual_cost") or job.get("estimated_cost"))
            for job in maintenance_jobs
            if (_parse_iso_date(job.get("start_date")) or today) >= week_start.date()
        ),
        2,
    )

    preventive_started_at = perf_counter()
    due_service_count = preventive_maintenance_collection().count_documents(
        {"status": {"$in": ["due", "overdue"]}}
    )
    log_db_duration("dashboard.preventive_due_count", preventive_started_at)

    compliance_started_at = perf_counter()
    compliance_records = list(
        compliance_records_collection().find(
            {"expiry_date": {"$ne": None}},
            {
                "vehicle_id": 1,
                "compliance_item_name": 1,
                "expiry_date": 1,
                "status": 1,
            },
        )
    )
    log_db_duration("dashboard.compliance_records", compliance_started_at)

    rides_started_at = perf_counter()
    active_ride_count = rides_collection().count_documents({"status": {"$in": list(ACTIVE_RIDE_STATUSES)}})
    bookings_in_progress = bookings_collection().count_documents({"status": {"$in": list(ACTIVE_TRIP_BOOKING_STATUSES)}})
    log_db_duration("dashboard.active_trip_counts", rides_started_at)
    active_trips = active_ride_count + bookings_in_progress

    profitability_allowed = current_role == "owner" or bool(admin_permissions.get("view_profitability"))
    if current_role == "admin" and not profitability_allowed:
        current_app.logger.warning("[Flux Dashboard] Net revenue hidden for admin due to role permissions.")
    net_revenue = (
        round(
            approved_total_this_week
            - (
                weekly_maintenance_cost
                + company_expense_total
                + (fuel_spend if include_fuel_in_profitability else 0)
            ),
            2,
        )
        if profitability_allowed
        else 0.0
    )

    fleet_economics_summary = _empty_owner_fleet_economics_summary()
    fleet_risk_summary = _empty_owner_fleet_risk_summary(vehicles_due_service=due_service_count)
    if current_role == "owner":
        fleet_economics_summary, fleet_risk_summary = _build_owner_fleet_summaries(
            vehicles_due_service=due_service_count,
            net_revenue=net_revenue,
            today=today,
        )

    weekly_revenue = []
    for offset in range(7):
        day = (week_start + timedelta(days=offset)).date()
        weekly_revenue.append(
            {
                "day": day.strftime("%a"),
                "target": round(daily_revenue_target, 2),
                "collected": round(collections_by_day.get(day.isoformat(), 0.0), 2),
            }
        )

    maintenance_cost_by_vehicle: dict[str, float] = defaultdict(float)
    for job in maintenance_jobs:
        vehicle_id = str(job.get("vehicle_id")) if job.get("vehicle_id") else None
        if vehicle_id:
            maintenance_cost_by_vehicle[vehicle_id] += _safe_float(job.get("actual_cost") or job.get("estimated_cost"))

    expense_cost_by_vehicle: dict[str, float] = defaultdict(float)
    for item in company_expenses:
        vehicle_id = str(item.get("vehicle_id")) if item.get("vehicle_id") else None
        if vehicle_id:
            expense_cost_by_vehicle[vehicle_id] += _safe_float(item.get("amount"))

    fuel_cost_by_vehicle: dict[str, float] = defaultdict(float)
    for item in approved_fuel_logs:
        vehicle_id = str(item.get("vehicle_id")) if item.get("vehicle_id") else None
        if vehicle_id:
            fuel_cost_by_vehicle[vehicle_id] += _safe_float(item.get("amount"))

    vehicle_profitability = []
    for vehicle_id, revenue in collections_by_vehicle.items():
        cost = round(
            maintenance_cost_by_vehicle.get(vehicle_id, 0.0)
            + expense_cost_by_vehicle.get(vehicle_id, 0.0)
            + (fuel_cost_by_vehicle.get(vehicle_id, 0.0) if include_fuel_in_profitability else 0.0),
            2,
        )
        vehicle_profitability.append(
            {
                "vehicle": vehicle_lookup.get(vehicle_id, "Vehicle"),
                "revenue": round(revenue, 2),
                "cost": cost,
                "profit": round(revenue - cost, 2),
            }
        )
    vehicle_profitability.sort(key=lambda item: item["profit"], reverse=True)
    vehicle_profitability = vehicle_profitability[:5]

    recent_collections = [
        {
            "id": str(item.get("_id")),
            "driver": driver_lookup.get(str(item.get("driver_id")), "Driver"),
            "vehicle": vehicle_lookup.get(str(item.get("vehicle_id")), "Vehicle"),
            "amount": _safe_float(item.get("amount")),
            "time": _format_relative_time(item.get("created_at")),
            "status": item.get("status") or "unknown",
        }
        for item in recent_collection_documents
    ]

    drivers_owing = []
    payment_deadline_dt = week_window["payment_deadline_dt"]
    for assignment in active_assignments:
        assignment_id = str(assignment.get("_id"))
        weekly_target = _safe_float(assignment.get("weekly_target"))
        approved_total = round(collections_by_assignment.get(assignment_id, 0.0), 2)
        outstanding = round(max(weekly_target - approved_total, 0), 2)
        if outstanding <= 0:
            continue
        drivers_owing.append(
            {
                "driver": driver_lookup.get(str(assignment.get("driver_id")), "Driver"),
                "vehicle": vehicle_lookup.get(str(assignment.get("vehicle_id")), "Vehicle"),
                "balance": outstanding,
                "daysOverdue": max((today - payment_deadline_dt.date()).days, 0),
                "status": "overdue" if today > payment_deadline_dt.date() else "due",
            }
        )
    drivers_owing.sort(key=lambda item: item["balance"], reverse=True)
    drivers_owing = drivers_owing[:5]

    maintenance_alerts = []
    for job in maintenance_jobs:
        if (job.get("status") or "").lower() in {"completed", "cancelled"}:
            continue
        maintenance_alerts.append(
            {
                "vehicle": vehicle_lookup.get(str(job.get("vehicle_id")), "Vehicle"),
                "type": job.get("title") or job.get("maintenance_type") or "Maintenance",
                "due": job.get("target_completion_date") or job.get("current_stage") or "Pending",
                "priority": (job.get("priority") or "medium").lower(),
            }
        )
    maintenance_alerts = maintenance_alerts[:4]

    upcoming_expiries = []
    for record in compliance_records:
        expiry_date = _parse_iso_date(record.get("expiry_date"))
        if not expiry_date:
            continue
        upcoming_expiries.append(
            {
                "vehicle": vehicle_lookup.get(str(record.get("vehicle_id")), "Vehicle"),
                "type": record.get("compliance_item_name") or "Compliance",
                "expiryDate": expiry_date.isoformat(),
                "daysLeft": (expiry_date - today).days,
            }
        )
    upcoming_expiries.sort(key=lambda item: item["daysLeft"])
    upcoming_expiries = upcoming_expiries[:4]

    activity_feed = []
    for item in recent_collection_documents[:2]:
        activity_feed.append(
            {
                "id": f"collection-{item.get('_id')}",
                "title": f"{vehicle_lookup.get(str(item.get('vehicle_id')), 'Vehicle')} collection recorded",
                "subtitle": f"{_format_currency(_safe_float(item.get('amount')))} • {_format_relative_time(item.get('created_at'))}",
                "tone": "green",
            }
        )
    for item in recent_fuel_logs[:1]:
        activity_feed.append(
            {
                "id": f"fuel-{item.get('_id')}",
                "title": "Fuel recorded",
                "subtitle": f"{vehicle_lookup.get(str(item.get('vehicle_id')), 'Vehicle')} • {_format_currency(_safe_float(item.get('amount')))} • {_format_relative_time(item.get('created_at'))}",
                "tone": "amber",
            }
        )
    for item in maintenance_jobs[:1]:
        activity_feed.append(
            {
                "id": f"maintenance-{item.get('_id')}",
                "title": item.get("title") or "Maintenance update",
                "subtitle": f"{vehicle_lookup.get(str(item.get('vehicle_id')), 'Vehicle')} • {_format_relative_time(item.get('updated_at') or item.get('created_at'))}",
                "tone": "red" if (item.get("priority") or "").lower() == "critical" else "blue",
            }
        )
    activity_feed = activity_feed[:4]

    result = {
        "summary": {
            "total_vehicles": total_vehicles,
            "active_vehicles": active_vehicles,
            "active_drivers": active_drivers,
            "weekly_revenue_target": weekly_revenue_target,
            "revenue_collected": approved_total_this_week,
            "outstanding_balance": outstanding_balance,
            "fuel_spend": fuel_spend,
            "fuel_metric_label": "Fuel Cost" if include_fuel_in_profitability else "Driver Fuel Spend",
            "net_revenue": net_revenue,
            "active_trips": active_trips,
            "vehicles_due_service": due_service_count,
        },
        "fleet_economics_summary": fleet_economics_summary,
        "fleet_risk_summary": fleet_risk_summary,
        "charts": {
            "weekly_revenue": weekly_revenue,
            "vehicle_profitability": vehicle_profitability,
        },
        "tables": {
            "recent_collections": recent_collections,
            "drivers_owing": drivers_owing,
        },
        "alerts": {
            "maintenance": maintenance_alerts,
            "expiries": upcoming_expiries,
            "activity_feed": activity_feed,
        },
    }

    current_app.logger.info(
        "[Flux Dashboard] summary generated role=%s duration_ms=%.2f",
        current_role,
        (perf_counter() - request_started_at) * 1000,
    )
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    if total_duration_ms > 2000:
        current_app.logger.warning(
            "SLOW API WARNING endpoint=/api/dashboard/summary role=%s duration_ms=%.2f",
            current_role,
            total_duration_ms,
        )
    return set_ttl_cached(cache_key, result, ttl_seconds=15)
