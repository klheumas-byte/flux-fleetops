"""Driver-owned private earnings ledger.

This module intentionally has no admin/fleet-owner query surface and is not
referenced by company collection or vehicle profitability services.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


PLATFORMS = {"bolt", "uber", "yango", "indrive", "other", "multiple"}
SALES_FIELDS = ("cash_sales", "digital_sales", "other_sales")
DEDUCTION_FIELDS = ("platform_fees",)
EXPENSE_FIELDS = (
    "fuel_paid_personally", "parking", "tolls", "washing",
    "repairs_paid_personally", "other_expenses",
)
MONEY_FIELDS = (*SALES_FIELDS, *DEDUCTION_FIELDS, *EXPENSE_FIELDS)
MAX_PAGE_SIZE = 100
MAX_EXPORT_ROWS = 5000


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def private_finance_collection():
    return get_collection("driver_private_finance")


def private_finance_history_collection():
    return get_collection("driver_private_finance_history")


def ensure_driver_private_finance_indexes():
    ensure_indexes_for_collection(
        private_finance_collection(),
        [
            {
                "keys": [("driver_id", ASCENDING), ("entry_date", ASCENDING), ("platform", ASCENDING)],
                "options": {
                    "unique": True,
                    "partialFilterExpression": {"status": "active"},
                    "name": "uniq_active_driver_date_platform",
                },
            },
            {"keys": [("driver_id", ASCENDING), ("entry_date", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("platform", ASCENDING), ("entry_date", DESCENDING)]},
        ],
        collection_name="driver_private_finance",
    )
    ensure_indexes_for_collection(
        private_finance_history_collection(),
        [
            {"keys": [("driver_id", ASCENDING), ("entry_id", ASCENDING), ("changed_at", DESCENDING)]},
        ],
        collection_name="driver_private_finance_history",
    )


def _driver_id(value) -> ObjectId:
    if not ObjectId.is_valid(str(value)):
        raise ApiError("Private earnings are unavailable.", status_code=403)
    return ObjectId(str(value))


def _eligible_driver(driver_id) -> dict:
    object_id = _driver_id(driver_id)
    driver = get_collection("users").find_one(
        {"_id": object_id, "role": "driver", "status": "active"},
        {"driver_profile.operating_mode": 1, "driver_profile.target_enabled": 1,
         "driver_profile.private_finance_enabled": 1},
    )
    profile = (driver or {}).get("driver_profile") or {}
    if (
        not driver
        or profile.get("operating_mode", "hybrid") not in {"target_only", "hybrid"}
        or not profile.get("target_enabled", True)
        or not profile.get("private_finance_enabled", False)
    ):
        raise ApiError("Private earnings are not enabled for this driver account.", status_code=403)
    return driver


def _parse_date(value, field_name: str) -> str:
    try:
        return date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError as error:
        raise ApiError(f"{field_name} must be an ISO date.", status_code=400) from error


def _money(value, field_name: str) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        raise ApiError(f"{field_name} must be a non-negative amount.", status_code=400)
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ApiError(f"{field_name} must be a non-negative amount.", status_code=400) from error
    if not amount.is_finite() or amount < 0:
        raise ApiError(f"{field_name} must be a non-negative amount.", status_code=400)
    return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _totals(values: dict) -> dict:
    gross = round(sum(values[field] for field in SALES_FIELDS), 2)
    deductions = round(sum(values[field] for field in DEDUCTION_FIELDS), 2)
    expenses = round(sum(values[field] for field in EXPENSE_FIELDS), 2)
    return {
        "gross_sales": gross,
        "total_platform_deductions": deductions,
        "total_personal_expenses": expenses,
        "driver_net_earnings": round(gross - deductions - expenses, 2),
    }


def _normalized_payload(payload: dict, existing: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ApiError("Private earnings entry must be an object.", status_code=400)
    output = {}
    if not existing or "date" in payload or "entry_date" in payload:
        output["entry_date"] = _parse_date(payload.get("date", payload.get("entry_date")), "date")
    if not existing or "platform" in payload:
        platform = str(payload.get("platform") or "").strip().lower()
        if platform not in PLATFORMS:
            raise ApiError("platform must be Bolt, Uber, Yango, inDrive, Other, or Multiple.", status_code=400)
        output["platform"] = platform
    for field in MONEY_FIELDS:
        if not existing or field in payload:
            output[field] = _money(payload.get(field, 0), field)
    if not existing or "notes" in payload:
        notes = str(payload.get("notes") or "").strip()
        if len(notes) > 1000:
            raise ApiError("notes cannot exceed 1000 characters.", status_code=400)
        output["notes"] = notes or None
    combined = {**(existing or {}), **output}
    output.update(_totals(combined))
    return output


def _serialize(document: dict) -> dict:
    return {
        "id": str(document["_id"]),
        "date": document.get("entry_date"),
        "platform": document.get("platform"),
        **{field: float(document.get(field) or 0) for field in MONEY_FIELDS},
        "gross_sales": float(document.get("gross_sales") or 0),
        "total_platform_deductions": float(document.get("total_platform_deductions") or 0),
        "total_personal_expenses": float(document.get("total_personal_expenses") or 0),
        "driver_net_earnings": float(document.get("driver_net_earnings") or 0),
        "notes": document.get("notes"),
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


def _entry_for_driver(driver_id, entry_id) -> dict:
    object_driver_id = _driver_id(driver_id)
    if not ObjectId.is_valid(str(entry_id)):
        raise ApiError("Private earnings entry not found.", status_code=404)
    entry = private_finance_collection().find_one(
        {"_id": ObjectId(str(entry_id)), "driver_id": object_driver_id, "status": "active"}
    )
    if not entry:
        raise ApiError("Private earnings entry not found.", status_code=404)
    return entry


def create_private_entry(driver_id, payload: dict) -> dict:
    _eligible_driver(driver_id)
    timestamp = now_utc()
    document = {
        "driver_id": _driver_id(driver_id),
        **_normalized_payload(payload),
        "status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "version": 1,
    }
    try:
        document["_id"] = private_finance_collection().insert_one(document).inserted_id
    except DuplicateKeyError:
        raise ApiError("An entry already exists for this date and platform.", status_code=409) from None
    private_finance_history_collection().insert_one({
        "driver_id": document["driver_id"], "entry_id": document["_id"], "action": "created",
        "version": 1, "snapshot": document.copy(), "changed_at": timestamp,
    })
    return _serialize(document)


def update_private_entry(driver_id, entry_id, payload: dict) -> dict:
    _eligible_driver(driver_id)
    entry = _entry_for_driver(driver_id, entry_id)
    updates = _normalized_payload(payload, entry)
    timestamp = now_utc()
    next_version = int(entry.get("version", 1)) + 1
    updates.update({"updated_at": timestamp, "version": next_version})
    try:
        result = private_finance_collection().update_one(
            {"_id": entry["_id"], "driver_id": entry["driver_id"], "status": "active", "version": entry.get("version", 1)},
            {"$set": updates},
        )
    except DuplicateKeyError:
        raise ApiError("An entry already exists for this date and platform.", status_code=409) from None
    if result.modified_count != 1:
        raise ApiError("This entry changed while you were editing it. Refresh and try again.", status_code=409)
    updated = {**entry, **updates}
    private_finance_history_collection().insert_one({
        "driver_id": entry["driver_id"], "entry_id": entry["_id"], "action": "updated",
        "version": next_version, "snapshot": updated.copy(), "changed_at": timestamp,
    })
    return _serialize(updated)


def delete_private_entry(driver_id, entry_id) -> dict:
    _eligible_driver(driver_id)
    entry = _entry_for_driver(driver_id, entry_id)
    timestamp = now_utc()
    result = private_finance_collection().update_one(
        {"_id": entry["_id"], "driver_id": entry["driver_id"], "status": "active"},
        {"$set": {"status": "deleted", "deleted_at": timestamp, "updated_at": timestamp}},
    )
    if result.modified_count != 1:
        raise ApiError("Private earnings entry not found.", status_code=404)
    private_finance_history_collection().insert_one({
        "driver_id": entry["driver_id"], "entry_id": entry["_id"], "action": "deleted",
        "version": entry.get("version", 1), "snapshot": entry.copy(), "changed_at": timestamp,
    })
    return {"id": str(entry["_id"]), "deleted": True}


def _date_window(start_date=None, end_date=None) -> tuple[str, str]:
    today = date.today()
    default_start = today.replace(day=1)
    start = _parse_date(start_date, "start_date") if start_date else default_start.isoformat()
    end = _parse_date(end_date, "end_date") if end_date else today.isoformat()
    if start > end:
        raise ApiError("start_date cannot be after end_date.", status_code=400)
    return start, end


def _query(driver_id, start_date=None, end_date=None, platform=None) -> tuple[dict, str, str]:
    _eligible_driver(driver_id)
    start, end = _date_window(start_date, end_date)
    query = {"driver_id": _driver_id(driver_id), "status": "active", "entry_date": {"$gte": start, "$lte": end}}
    if platform:
        normalized = str(platform).strip().lower()
        if normalized not in PLATFORMS:
            raise ApiError("Invalid platform filter.", status_code=400)
        query["platform"] = normalized
    return query, start, end


def list_private_entries(driver_id, start_date=None, end_date=None, platform=None, page=1, page_size=25) -> dict:
    query, start, end = _query(driver_id, start_date, end_date, platform)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 25), 1), MAX_PAGE_SIZE)
    total = private_finance_collection().count_documents(query)
    records = list(private_finance_collection().find(query).sort("entry_date", DESCENDING).skip((page - 1) * page_size).limit(page_size))
    return {
        "records": [_serialize(item) for item in records],
        "filters": {"start_date": start, "end_date": end, "platform": platform or None},
        "pagination": {"page": page, "page_size": page_size, "total": total, "total_pages": max(1, (total + page_size - 1) // page_size)},
    }


def private_finance_summary(driver_id, start_date=None, end_date=None, platform=None, period="daily") -> dict:
    query, start, end = _query(driver_id, start_date, end_date, platform)
    period = str(period or "daily").strip().lower()
    if period not in {"daily", "weekly", "monthly"}:
        raise ApiError("period must be daily, weekly, or monthly.", status_code=400)
    records = list(private_finance_collection().find(query).sort("entry_date", ASCENDING).limit(MAX_EXPORT_ROWS))
    totals = _totals({field: round(sum(float(item.get(field) or 0) for item in records), 2) for field in MONEY_FIELDS})
    platform_breakdown = {}
    trends = {}
    for item in records:
        platform_key = item["platform"]
        platform_row = platform_breakdown.setdefault(platform_key, {"platform": platform_key, "entries": 0, "gross_sales": 0.0, "net_earnings": 0.0})
        platform_row["entries"] += 1
        platform_row["gross_sales"] = round(platform_row["gross_sales"] + float(item.get("gross_sales") or 0), 2)
        platform_row["net_earnings"] = round(platform_row["net_earnings"] + float(item.get("driver_net_earnings") or 0), 2)
        entry_day = date.fromisoformat(item["entry_date"])
        if period == "daily":
            bucket = entry_day.isoformat()
        elif period == "weekly":
            monday = entry_day - timedelta(days=entry_day.weekday())
            bucket = monday.isoformat()
        else:
            bucket = entry_day.strftime("%Y-%m")
        trend = trends.setdefault(bucket, {"period": bucket, "gross_sales": 0.0, "net_earnings": 0.0})
        trend["gross_sales"] = round(trend["gross_sales"] + float(item.get("gross_sales") or 0), 2)
        trend["net_earnings"] = round(trend["net_earnings"] + float(item.get("driver_net_earnings") or 0), 2)
    return {
        "period": period, "start_date": start, "end_date": end, "entry_count": len(records),
        **totals, "platform_breakdown": list(platform_breakdown.values()), "trend": list(trends.values()),
        "truncated": len(records) >= MAX_EXPORT_ROWS,
    }


def private_entry_history(driver_id, entry_id) -> list[dict]:
    _eligible_driver(driver_id)
    object_driver_id = _driver_id(driver_id)
    if not ObjectId.is_valid(str(entry_id)):
        raise ApiError("Private earnings entry not found.", status_code=404)
    rows = private_finance_history_collection().find(
        {"driver_id": object_driver_id, "entry_id": ObjectId(str(entry_id))}
    ).sort("changed_at", DESCENDING).limit(100)
    return [{"action": row["action"], "version": row.get("version"), "changed_at": row["changed_at"].isoformat()} for row in rows]


def export_private_entries_csv(driver_id, start_date=None, end_date=None, platform=None) -> str:
    query, _start, _end = _query(driver_id, start_date, end_date, platform)
    records = list(private_finance_collection().find(query).sort("entry_date", ASCENDING).limit(MAX_EXPORT_ROWS))
    output = io.StringIO()
    fields = ["date", "platform", *MONEY_FIELDS, "gross_sales", "total_platform_deductions", "total_personal_expenses", "driver_net_earnings", "notes"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in records:
        row = _serialize(item)
        writer.writerow({field: row.get(field) for field in fields})
    return output.getvalue()
