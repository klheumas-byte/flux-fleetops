from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.expense import serialize_expense
from models.finance_account import serialize_finance_account_snapshot
from models.funding_contribution import serialize_funding_contribution
from models.maintenance import serialize_maintenance_job
from models.user import serialize_user
from services.finance_account_service import get_finance_account_document, increment_finance_account_balance
from services.master_data_service import resolve_master_data_item
from utils.api_error import ApiError
from utils.file_validation import validate_file_reference
from utils.mongo_indexes import ensure_indexes_for_collection


DRIVER_COLLECTION_SOURCE = "fleet sales / driver collection"


def now_utc():
    return datetime.now(timezone.utc)


def _oid(value, field, required=True):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if ObjectId.is_valid(str(value)):
        return ObjectId(str(value))
    raise ApiError(f"Invalid {field}.", status_code=400)


def _positive(value, field="amount"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ApiError(f"{field} must be a positive number.", status_code=400)
    return round(float(value), 2)


def _date_text(value, field):
    raw = str(value or "").strip()
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise ApiError(f"{field} must be a valid YYYY-MM-DD date.", status_code=400) from None
    return raw


def _source(identifier, description=None):
    document = resolve_master_data_item("funding_sources", identifier, active_only=True)
    if not document:
        raise ApiError("funding_source_id is required.", status_code=400)
    detail = str(description or "").strip() or None
    if str(document.get("name") or "").strip().lower() == "other" and not detail:
        raise ApiError("funding_source_description is required when Funding Source is Other.", status_code=400)
    return document, detail


def funding_contributions_collection():
    return get_collection("funding_contributions")


def ensure_finance_foundation_indexes():
    ensure_indexes_for_collection(
        funding_contributions_collection(),
        [
            {"keys": [("funding_source_id", ASCENDING), ("contribution_date", DESCENDING)]},
            {"keys": [("finance_account_id", ASCENDING), ("contribution_date", DESCENDING)]},
            {"keys": [("recorded_by", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("idempotency_key", ASCENDING)], "options": {"unique": True, "sparse": True}},
        ],
        collection_name="funding_contributions",
    )


def create_funding_contribution(payload, *, current_user_id, current_role, idempotency_key=None):
    if current_role not in {"owner", "admin", "finance", "finance_officer"}:
        raise ApiError("You do not have permission to record funding.", status_code=403)
    source, source_description = _source(payload.get("funding_source_id"), payload.get("funding_source_description"))
    account = get_finance_account_document(payload.get("finance_account_id"))
    if account.get("status") != "active":
        raise ApiError("Selected finance account is inactive.", status_code=400)
    key = str(idempotency_key or payload.get("idempotency_key") or "").strip() or None
    if key:
        existing = funding_contributions_collection().find_one({"idempotency_key": key})
        if existing:
            return serialize_funding_contribution(existing)
    description = str(payload.get("description") or "").strip()
    if not description:
        raise ApiError("description is required.", status_code=400)
    timestamp = now_utc()
    actor_id = _oid(current_user_id, "current_user_id")
    document = {
        "funding_source_id": source["_id"],
        "funding_source_snapshot": {"id": str(source["_id"]), "name": source.get("name")},
        "funding_source_description": source_description,
        "finance_account_id": account["_id"],
        "finance_account_snapshot": serialize_finance_account_snapshot(account),
        "amount": _positive(payload.get("amount")),
        "contribution_date": _date_text(payload.get("contribution_date"), "contribution_date"),
        "description": description,
        "reference_number": str(payload.get("reference_number") or "").strip() or None,
        "receipt_image": validate_file_reference(payload.get("receipt_image"), field_name="receipt_image", file_name="funding-receipt"),
        "notes": str(payload.get("notes") or "").strip() or None,
        "recorded_by": actor_id,
        "idempotency_key": key,
        "created_at": timestamp,
        "updated_at": timestamp,
        "audit_log": [{"action": "funding_contribution_recorded", "actor_id": actor_id, "actor_role": current_role, "at": timestamp}],
    }
    try:
        result = funding_contributions_collection().insert_one(document)
    except DuplicateKeyError:
        return serialize_funding_contribution(funding_contributions_collection().find_one({"idempotency_key": key}))
    document["_id"] = result.inserted_id
    increment_finance_account_balance(account["_id"], document["amount"], actor_id=actor_id, reference_type="funding_contribution", reference_id=document["_id"])
    return serialize_funding_contribution(document)


def list_funding_contributions():
    return [serialize_funding_contribution(item) for item in funding_contributions_collection().find({}).sort([("contribution_date", DESCENDING), ("created_at", DESCENDING)])]


def _period(start_date=None, end_date=None, preset=None):
    today = now_utc().date()
    preset = str(preset or "").lower()
    if preset == "this_week":
        start = today - timedelta(days=today.weekday()); end = today
    elif preset == "last_week":
        end = today - timedelta(days=today.weekday() + 1); start = end - timedelta(days=6)
    else:
        start = date.fromisoformat(start_date) if start_date else date.min
        end = date.fromisoformat(end_date) if end_date else today
    if start > end:
        raise ApiError("start_date cannot be after end_date.", status_code=400)
    return start, end


def _in_period(value, start, end):
    if isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, str):
        try: value = date.fromisoformat(value[:10])
        except ValueError: return False
    return isinstance(value, date) and start <= value <= end


def funding_position(*, start_date=None, end_date=None):
    start, end = _period(start_date, end_date)
    contributions = [item for item in funding_contributions_collection().find({}) if _in_period(item.get("contribution_date") or item.get("created_at"), start, end)]
    expenses = [item for item in get_collection("expenses").find({"status": {"$in": ["approved", "paid"]}, "record_scope": {"$ne": "personal"}}) if _in_period(item.get("expense_date") or item.get("created_at"), start, end)]
    rows = {}
    for item in contributions:
        key = str(item.get("funding_source_id")); row = rows.setdefault(key, {"funding_source_id": key, "funding_source": item.get("funding_source_snapshot"), "money_in": 0.0, "expenses_out": 0.0})
        row["money_in"] += float(item.get("amount") or 0)
    for item in expenses:
        key = str(item.get("funding_source_id")); row = rows.setdefault(key, {"funding_source_id": key, "funding_source": item.get("funding_source_snapshot"), "money_in": 0.0, "expenses_out": 0.0})
        row["expenses_out"] += float(item.get("amount") or 0)
    for row in rows.values():
        row["money_in"] = round(row["money_in"], 2); row["expenses_out"] = round(row["expenses_out"], 2); row["net_position"] = round(row["money_in"] - row["expenses_out"], 2)
    money_in = round(sum(row["money_in"] for row in rows.values()), 2); expenses_out = round(sum(row["expenses_out"] for row in rows.values()), 2)
    return {"start_date": None if start == date.min else start.isoformat(), "end_date": end.isoformat(), "money_in": money_in, "expenses_out": expenses_out, "net_funding_position": round(money_in-expenses_out, 2), "sources": list(rows.values())}


def target_for_date(driver_document, on_date):
    profile = driver_document.get("driver_profile") or {}
    candidates = []
    for item in profile.get("target_history") or []:
        try: effective_from = date.fromisoformat(str(item.get("effective_from"))[:10])
        except (TypeError, ValueError): continue
        effective_to = date.fromisoformat(str(item.get("effective_to"))[:10]) if item.get("effective_to") else None
        if effective_from <= on_date and (effective_to is None or on_date <= effective_to): candidates.append((effective_from, item))
    if candidates:
        return max(candidates, key=lambda pair: pair[0])[1]
    if profile.get("target_history"):
        return {"target_amount": 0, "target_frequency": "weekly", "effective_from": None, "effective_to": None}
    return {"target_amount": profile.get("target_amount") or 0, "target_frequency": profile.get("target_frequency") or "weekly", "effective_from": profile.get("settings_effective_date")}


def reconciliation_report(*, current_user_id, current_role, driver_id=None, preset=None, start_date=None, end_date=None):
    if current_role == "driver":
        if driver_id and str(driver_id) != str(current_user_id): raise ApiError("Drivers can only view their own reconciliation.", status_code=403)
        driver_id = current_user_id
    elif current_role not in {"owner", "admin", "finance", "finance_officer"}:
        raise ApiError("You do not have permission to view finance reconciliation.", status_code=403)
    start, end = _period(start_date, end_date, preset)
    query = {"role": "driver"}
    if driver_id: query["_id"] = _oid(driver_id, "driver_id")
    result = []
    for driver in get_collection("users").find(query):
        collections = [item for item in get_collection("collections").find({"driver_id": driver["_id"], "status": {"$ne": "reversed"}}) if _in_period(item.get("collection_date") or item.get("created_at"), start, end)]
        expenses = [item for item in get_collection("expenses").find({"driver_id": driver["_id"], "status": {"$in": ["approved", "paid"]}, "record_scope": {"$ne": "personal"}}) if _in_period(item.get("expense_date") or item.get("created_at"), start, end)]
        gross = round(sum(float(item.get("amount") or 0) for item in collections), 2)
        submitted = round(sum(float(item.get("submitted_amount") if item.get("submitted_amount") is not None else item.get("amount") or 0) for item in collections if item.get("status") in {"pending", "submitted", "received", "approved"}), 2)
        collection_funded = round(sum(float(item.get("amount") or 0) for item in expenses if str((item.get("funding_source_snapshot") or {}).get("name") or "").lower() == DRIVER_COLLECTION_SOURCE), 2)
        target_entry = target_for_date(driver, end); target = float(target_entry.get("target_amount") or 0)
        result.append({"driver": serialize_user(driver), "start_date": start.isoformat(), "end_date": end.isoformat(), "gross_collections": gross, "amount_submitted": submitted, "submission_history": [{"type": "collection_submission", **item} for item in [__import__('models.collection', fromlist=['serialize_collection']).serialize_collection(value) for value in collections]], "target": target, "target_record": target_entry, "target_achievement_percentage": round((gross/target*100) if target else 0, 2), "expenses": [serialize_expense(item) for item in expenses], "fleet_sales_funded_expenses": collection_funded, "expected_cash_submission": round(gross-collection_funded, 2), "outstanding_unsubmitted_amount": round(max(gross-collection_funded-submitted, 0), 2), "net_operating_position": round(gross-sum(float(item.get("amount") or 0) for item in expenses), 2)})
    return {"start_date": start.isoformat(), "end_date": end.isoformat(), "drivers": result}


def vehicle_finance_history(vehicle_id):
    vehicle_oid = _oid(vehicle_id, "vehicle_id")
    if not get_collection("vehicles").find_one({"_id": vehicle_oid}): raise ApiError("Vehicle not found.", status_code=404)
    collections = list(get_collection("collections").find({"vehicle_id": vehicle_oid, "status": "approved"}))
    expenses = list(get_collection("expenses").find({"vehicle_id": vehicle_oid, "status": {"$in": ["approved", "paid"]}, "record_scope": {"$ne": "personal"}}))
    maintenance = list(get_collection("maintenance_jobs").find({"vehicle_id": vehicle_oid}))
    revenue = round(sum(float(item.get("amount") or 0) for item in collections), 2); expense_total = round(sum(float(item.get("amount") or 0) for item in expenses), 2)
    linked_expense_ids = {item.get("expense_id") for item in maintenance if item.get("expense_id")}
    unlinked_maintenance = round(sum(float(item.get("actual_cost") or item.get("estimated_cost") or 0) for item in maintenance if not item.get("expense_id")), 2)
    sources = sorted({str((item.get("funding_source_snapshot") or {}).get("name")) for item in expenses if (item.get("funding_source_snapshot") or {}).get("name")})
    return {"vehicle_id": str(vehicle_oid), "revenue_sales": revenue, "expenses": expense_total, "repair_maintenance_costs": round(sum(float(item.get("actual_cost") or item.get("estimated_cost") or 0) for item in maintenance), 2), "funding_sources_used": sources, "lifetime_cost": round(expense_total+unlinked_maintenance, 2), "net_contribution": round(revenue-expense_total-unlinked_maintenance, 2), "transactions": {"collections": [__import__('models.collection', fromlist=['serialize_collection']).serialize_collection(item) for item in collections], "expenses": [serialize_expense(item) for item in expenses], "maintenance": [serialize_maintenance_job(item) for item in maintenance]}, "deduplication": {"linked_maintenance_expense_count": len(linked_expense_ids)}}
