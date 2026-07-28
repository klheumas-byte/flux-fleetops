"""Role-scoped commercial analytics built from operational source records.

Private driver-finance collections are intentionally never queried here.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from extensions import get_collection
from services.fleet_owner_service import _owner_vehicle_ids, _profitability
from utils.api_error import ApiError


MAX_RANGE_DAYS = 366
MAX_EXPORT_ROWS = 5000
VALID_PERIODS = {"daily", "weekly", "monthly"}


def _oid(value, name):
    if not ObjectId.is_valid(str(value)):
        raise ApiError(f"Invalid {name}.", status_code=404)
    return ObjectId(str(value))


def _bounds(start_date=None, end_date=None):
    today = datetime.now(timezone.utc).date()
    try:
        start = datetime.fromisoformat(str(start_date)).date() if start_date else today - timedelta(days=29)
        end = datetime.fromisoformat(str(end_date)).date() if end_date else today
    except ValueError as error:
        raise ApiError("Dates must use YYYY-MM-DD format.", status_code=400) from error
    if start > end:
        raise ApiError("start_date cannot be after end_date.", status_code=400)
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ApiError(f"Date range cannot exceed {MAX_RANGE_DAYS} days.", status_code=400)
    return start, end


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _period_key(day, period):
    if period == "monthly":
        return day.strftime("%Y-%m")
    if period == "weekly":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    return day.isoformat()


def _assignment_interval(document):
    start = _date(document.get("start_date") or document.get("start_time") or document.get("created_at"))
    end = _date(document.get("end_date") or document.get("ended_at"))
    return start, end


def _overlaps(document, start, end):
    assigned, ended = _assignment_interval(document)
    return (assigned is None or assigned <= end) and (ended is None or ended >= start)


def _scope(*, role, user_id, start, end, vehicle_id=None, driver_id=None, fleet_owner_id=None):
    """Resolve all allowed entity IDs before any fact collection is read."""
    users = get_collection("users")
    vehicles = get_collection("vehicles")
    assignments = get_collection("assignments")
    requested_driver = _oid(driver_id, "driver_id") if driver_id else None

    if role in {"owner", "admin"}:
        query = {"usage_type": {"$ne": "personal"}}
        if fleet_owner_id:
            query["fleet_owner_id"] = _oid(fleet_owner_id, "fleet_owner_id")
        allowed = [item["_id"] for item in vehicles.find(query, {"_id": 1})]
        scoped_driver = requested_driver
    elif role == "fleet_owner":
        if fleet_owner_id:
            raise ApiError("Fleet owner scope cannot be overridden.", status_code=403)
        allowed = _owner_vehicle_ids(user_id)
        scoped_driver = requested_driver
    elif role == "driver":
        driver_object_id = _oid(user_id, "user_id")
        if requested_driver and requested_driver != driver_object_id:
            raise ApiError("Driver scope cannot be overridden.", status_code=403)
        scoped_driver = driver_object_id
        allowed = []
        for assignment in assignments.find({"driver_id": driver_object_id}, {"vehicle_id": 1, "start_date": 1, "start_time": 1, "created_at": 1, "end_date": 1, "ended_at": 1}):
            if assignment.get("vehicle_id") and _overlaps(assignment, start, end):
                allowed.append(assignment["vehicle_id"])
        allowed = list(dict.fromkeys(allowed))
    else:
        raise ApiError("This role cannot access commercial analytics.", status_code=403)

    if scoped_driver and not users.find_one({"_id": scoped_driver, "role": "driver"}, {"_id": 1}):
        raise ApiError("Driver not found.", status_code=404)
    if vehicle_id:
        selected = _oid(vehicle_id, "vehicle_id")
        if selected not in set(allowed):
            raise ApiError("Vehicle not found.", status_code=404)
        allowed = [selected]
    return allowed, scoped_driver


def _assignment_map(vehicle_ids, start, end):
    result = defaultdict(list)
    for item in get_collection("assignments").find({"vehicle_id": {"$in": vehicle_ids}}):
        if _overlaps(item, start, end):
            result[item["vehicle_id"]].append(item)
    return result


def _attributed_driver(record, event_day, assignments):
    if record.get("driver_id"):
        return record["driver_id"]
    matches = []
    for assignment in assignments.get(record.get("vehicle_id"), []):
        assigned, ended = _assignment_interval(assignment)
        if (assigned is None or assigned <= event_day) and (ended is None or ended >= event_day):
            matches.append(assignment)
    # Ambiguous history is excluded rather than attributed to the current driver.
    return matches[0].get("driver_id") if len(matches) == 1 else None


def get_commercial_analytics(*, role, user_id, start_date=None, end_date=None,
                             period="daily", vehicle_id=None, driver_id=None,
                             fleet_owner_id=None, operation_type=None, status=None,
                             page=1, page_size=25):
    start, end = _bounds(start_date, end_date)
    if period not in VALID_PERIODS:
        raise ApiError("period must be daily, weekly, or monthly.", status_code=400)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 25), 1), 100)
    vehicle_ids, scoped_driver = _scope(
        role=role, user_id=user_id, start=start, end=end, vehicle_id=vehicle_id,
        driver_id=driver_id, fleet_owner_id=fleet_owner_id,
    )
    start_s, end_s = start.isoformat(), end.isoformat()
    assignments = _assignment_map(vehicle_ids, start, end)

    ride_query = {"vehicle_id": {"$in": vehicle_ids}, "trip_date": {"$gte": start_s, "$lte": end_s}}
    if operation_type:
        ride_query["operation_type"] = operation_type
    if status:
        ride_query["status"] = status
    rides = list(get_collection("rides").find(ride_query))
    if scoped_driver:
        rides = [item for item in rides if _attributed_driver(item, _date(item.get("trip_date")), assignments) == scoped_driver]

    financials = _profitability(vehicle_ids, start_s, end_s)
    if scoped_driver:
        # Driver view recognizes only approved company collections attributed to that driver.
        company = list(get_collection("collections").find({
            "vehicle_id": {"$in": vehicle_ids}, "status": "approved",
            "collection_date": {"$gte": start_s, "$lte": end_s},
        }))
        company = [item for item in company if _attributed_driver(item, _date(item.get("collection_date")), assignments) == scoped_driver]
        recognized = round(sum(float(item.get("amount") or 0) for item in company), 2)
        revenue_by_vehicle = defaultdict(float)
        for item in company:
            revenue_by_vehicle[item.get("vehicle_id")] += float(item.get("amount") or 0)
    else:
        recognized = financials["totals"]["gross_revenue"]

    restrictions = list(get_collection("maintenance_availability_overrides").find({
        "vehicle_id": {"$in": vehicle_ids},
        "start_at": {"$lte": datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)},
        "repair_deadline": {"$gte": datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)},
    }))
    completed = [item for item in rides if item.get("status") in {"completed", "complete"}]
    distance = round(sum(float(item.get("distance") or item.get("distance_km") or 0) for item in completed), 2)
    day_count = (end - start).days + 1
    utilized_days = len({(item.get("vehicle_id"), str(item.get("trip_date"))[:10]) for item in completed})
    capacity_days = len(vehicle_ids) * day_count

    trend = defaultdict(lambda: {"trips_completed": 0, "distance_km": 0.0})
    for item in completed:
        day = _date(item.get("trip_date"))
        if not day:
            continue
        bucket = trend[_period_key(day, period)]
        bucket["trips_completed"] += 1
        bucket["distance_km"] += float(item.get("distance") or item.get("distance_km") or 0)

    vehicle_docs = {item["_id"]: item for item in get_collection("vehicles").find({"_id": {"$in": vehicle_ids}})}
    rows = []
    for vid in vehicle_ids:
        vehicle = vehicle_docs.get(vid, {})
        values = financials["by_vehicle"].get(str(vid), {})
        if role == "driver":
            driver_revenue = round(revenue_by_vehicle.get(vid, 0), 2)
            values = {
                "gross_revenue": driver_revenue,
                "fuel_cost": None, "maintenance_cost": None, "other_operating_cost": None,
                "total_recorded_operating_cost": None, "net_profitability": None,
                "data_complete": True,
                "data_note": "Driver scope shows own approved company collections; fleet operating costs are not exposed.",
            }
        rows.append({
            "vehicle_id": str(vid),
            "registration_number": vehicle.get("registration_number"),
            **values,
            "completed_trips": sum(1 for item in completed if item.get("vehicle_id") == vid),
            "restriction_count": sum(1 for item in restrictions if item.get("vehicle_id") == vid),
        })
    rows.sort(key=lambda item: (item.get("registration_number") or "", item["vehicle_id"]))
    offset = (page - 1) * page_size
    warnings = sorted({item.get("data_note") for item in rows if not item.get("data_complete", True) and item.get("data_note")})
    totals = financials["totals"] if role != "driver" else {
        "gross_revenue": recognized, "fuel_cost": None, "maintenance_cost": None,
        "other_operating_cost": None, "total_recorded_operating_cost": None,
        "net_profitability": None,
    }
    return {
        "scope": {"role": role, "vehicle_count": len(vehicle_ids), "driver_id": str(scoped_driver) if scoped_driver else None},
        "filters": {"start_date": start_s, "end_date": end_s, "period": period, "vehicle_id": vehicle_id,
                    "driver_id": driver_id, "fleet_owner_id": fleet_owner_id, "operation_type": operation_type, "status": status},
        "summary": {
            **totals, "recognized_company_revenue": recognized,
            "completed_trips": len(completed), "distance_km": distance,
            "utilization_percent": round((utilized_days / capacity_days * 100), 1) if capacity_days else 0,
            "restricted_operation_count": len(restrictions),
        },
        "trend": [{"period": key, **value, "distance_km": round(value["distance_km"], 2)} for key, value in sorted(trend.items())],
        "vehicles": rows[offset:offset + page_size],
        "pagination": {"page": page, "page_size": page_size, "total": len(rows), "total_pages": (len(rows) + page_size - 1) // page_size},
        "data_quality": {"complete": not warnings, "warnings": warnings,
                         "note": "Private driver earnings are excluded. Profitability uses approved company collections and recorded operating costs."},
    }


def export_commercial_analytics_csv(**kwargs):
    report = get_commercial_analytics(**kwargs, page=1, page_size=100)
    total = report["pagination"]["total"]
    if total > MAX_EXPORT_ROWS:
        raise ApiError(f"Export is limited to {MAX_EXPORT_ROWS} rows. Narrow the filters.", status_code=400)
    # Retrieve all bounded rows without relaxing the public page-size cap.
    rows = report["vehicles"]
    if total > len(rows):
        rows = []
        pages = (total + 99) // 100
        for page in range(1, pages + 1):
            rows.extend(get_commercial_analytics(**kwargs, page=page, page_size=100)["vehicles"])
    output = io.StringIO()
    fields = ["vehicle_id", "registration_number", "gross_revenue", "fuel_cost", "maintenance_cost",
              "other_operating_cost", "total_recorded_operating_cost", "net_profitability", "completed_trips",
              "restriction_count", "data_complete", "data_note"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
