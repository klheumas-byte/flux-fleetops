"""Dispatch finance snapshots and analytics built on the canonical dispatch record.

This module deliberately extends ``dispatch_financial_records`` instead of
creating a second dispatch ledger.  The only entry collection introduced is
the vehicle maintenance reserve sub-ledger, whose unique source keys make
posting idempotent.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from services.master_data_service import resolve_master_data_item
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


PRICING_TYPES = {"standard", "subsidized", "complimentary"}
COMPENSATION_MODES = {"amount", "percentage"}
ADJUSTMENT_CATEGORIES = {
    "loading", "offloading", "waiting", "extra_stops", "difficult_load",
    "special_duty", "other",
}
SETTING_TYPES = {"maintenance_reserve_rate", "fuel_price_per_litre", "vehicle_capital_profit_rule"}
PRIVILEGED_ROLES = {"owner", "admin", "finance", "finance_officer", "operations_administrator"}


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


def _number(value, field, *, required=True, positive=False):
    if value in (None, "") and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field} must be numeric.", status_code=400)
    result = round(float(value), 2)
    if result < 0 or (positive and result <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise ApiError(f"{field} must be {qualifier}.", status_code=400)
    return result


def _date(value, field="effective_from"):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        raise ApiError(f"{field} must be a valid YYYY-MM-DD date.", status_code=400) from None


def _date_of(document):
    raw = document.get("dispatch_date") or document.get("scheduled_start_time") or document.get("created_at")
    if isinstance(raw, datetime):
        return raw.date()
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return now_utc().date()


def finance_settings_collection():
    return get_collection("dispatch_finance_settings")


def reserve_entries_collection():
    return get_collection("vehicle_maintenance_reserve_entries")


def financials_collection():
    return get_collection("dispatch_financial_records")


def jobs_collection():
    return get_collection("dispatch_jobs")


def ensure_dispatch_finance_engine_indexes():
    ensure_indexes_for_collection(finance_settings_collection(), [
        {"keys": [("setting_type", ASCENDING), ("effective_from", ASCENDING)], "options": {"unique": True}},
        {"keys": [("setting_type", ASCENDING), ("effective_from", DESCENDING)]},
    ], collection_name="dispatch_finance_settings")
    ensure_indexes_for_collection(reserve_entries_collection(), [
        {"keys": [("source_key", ASCENDING)], "options": {"unique": True}},
        {"keys": [("vehicle_id", ASCENDING), ("posted_at", DESCENDING)]},
        {"keys": [("dispatch_job_id", ASCENDING)], "options": {"sparse": True}},
        {"keys": [("maintenance_job_id", ASCENDING)], "options": {"sparse": True}},
    ], collection_name="vehicle_maintenance_reserve_entries")


def _serialize_setting(item):
    return {
        "id": str(item.get("_id")), "setting_type": item.get("setting_type"),
        "value": item.get("value"), "configuration": item.get("configuration"),
        "effective_from": item.get("effective_from"), "effective_to": item.get("effective_to"),
        "reason": item.get("reason"), "changed_by": str(item.get("changed_by")) if item.get("changed_by") else None,
        "changed_by_name": item.get("changed_by_name"),
        "changed_at": item.get("changed_at").isoformat() if isinstance(item.get("changed_at"), datetime) else item.get("changed_at"),
    }


def list_finance_settings(current_role):
    if current_role not in PRIVILEGED_ROLES:
        raise ApiError("You do not have permission to view dispatch finance settings.", status_code=403)
    rows = [_serialize_setting(item) for item in finance_settings_collection().find({}).sort([("setting_type", 1), ("effective_from", -1)])]
    return {"settings": rows, "defaults": {"maintenance_reserve_rate": 25.0}, "setting_types": sorted(SETTING_TYPES)}


def schedule_finance_setting(setting_type, payload, *, current_user_id, current_role):
    if current_role != "owner":
        raise ApiError("Only the owner can change dispatch finance rates.", status_code=403)
    kind = str(setting_type or "").strip().lower()
    if kind not in SETTING_TYPES:
        raise ApiError("Invalid dispatch finance setting type.", status_code=400)
    start = _date(payload.get("effective_from"))
    end = _date(payload.get("effective_to"), "effective_to") if payload.get("effective_to") else None
    if end and end < start:
        raise ApiError("effective_to cannot be before effective_from.", status_code=400)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ApiError("reason is required.", status_code=400)
    configuration = payload.get("configuration") if isinstance(payload.get("configuration"), dict) else None
    value = payload.get("value")
    if kind != "vehicle_capital_profit_rule":
        value = _number(value, "value")
        if kind == "maintenance_reserve_rate" and value > 100:
            raise ApiError("maintenance reserve rate cannot exceed 100 percent.", status_code=400)
    elif configuration is None:
        # Capital/profit intentionally has no implicit percentage.
        raise ApiError("configuration is required for the vehicle capital/profit rule.", status_code=400)
    elif configuration.get("mode") not in {"amount", "percentage"}:
        raise ApiError("vehicle capital/profit rule mode must be amount or percentage.", status_code=400)
    elif _number(configuration.get("value"), "configuration.value") > (100 if configuration.get("mode") == "percentage" else float("inf")):
        raise ApiError("vehicle capital/profit percentage cannot exceed 100.", status_code=400)
    existing = list(finance_settings_collection().find({"setting_type": kind}))
    if any(str(item.get("effective_from")) == start.isoformat() for item in existing):
        raise ApiError("A setting already starts on effective_from.", status_code=409)
    for item in existing:
        item_start = _date(item.get("effective_from"))
        item_end = _date(item.get("effective_to"), "effective_to") if item.get("effective_to") else None
        if start <= (item_end or date.max) and item_start <= (end or date.max):
            if item_start < start and (item_end is None or item_end >= start):
                finance_settings_collection().update_one({"_id": item["_id"]}, {"$set": {"effective_to": (start - timedelta(days=1)).isoformat()}})
            else:
                raise ApiError("Setting period overlaps an existing period.", status_code=409)
    actor_id = _oid(current_user_id, "current_user_id")
    actor = get_collection("users").find_one({"_id": actor_id}, {"full_name": 1}) or {}
    timestamp = now_utc()
    document = {
        "setting_type": kind, "value": value, "configuration": configuration,
        "effective_from": start.isoformat(), "effective_to": end.isoformat() if end else None,
        "reason": reason, "changed_by": actor_id, "changed_by_name": actor.get("full_name") or "Unknown user",
        "changed_at": timestamp, "immutable_history": True,
    }
    document["_id"] = finance_settings_collection().insert_one(document).inserted_id
    get_collection("fleet_owner_audit").insert_one({
        "actor_id": actor_id, "actor_role": current_role, "action": "dispatch_finance_setting_scheduled",
        "entity_type": "dispatch_finance_setting", "entity_id": document["_id"], "after": document,
        "reason": reason, "created_at": timestamp, "immutable": True,
    })
    return _serialize_setting(document)


def schedule_vehicle_efficiency(vehicle_id, payload, *, current_user_id, current_role):
    if current_role != "owner":
        raise ApiError("Only the owner can change vehicle fuel efficiency.", status_code=403)
    oid = _oid(vehicle_id, "vehicle_id")
    vehicle = get_collection("vehicles").find_one({"_id": oid})
    if not vehicle: raise ApiError("Vehicle not found.", status_code=404)
    efficiency = _number(payload.get("km_per_litre"), "km_per_litre", positive=True)
    start = _date(payload.get("effective_from")); end = _date(payload.get("effective_to"), "effective_to") if payload.get("effective_to") else None
    if end and end < start: raise ApiError("effective_to cannot be before effective_from.", status_code=400)
    reason = str(payload.get("reason") or "").strip()
    if not reason: raise ApiError("reason is required.", status_code=400)
    history = [dict(item) for item in vehicle.get("fuel_efficiency_history") or []]
    if any(str(item.get("effective_from"))[:10] == start.isoformat() for item in history): raise ApiError("Vehicle efficiency already starts on effective_from.", status_code=409)
    for item in history:
        item_start=_date(item.get("effective_from")); item_end=_date(item.get("effective_to"), "effective_to") if item.get("effective_to") else None
        if start <= (item_end or date.max) and item_start <= (end or date.max):
            if item_start < start: item["effective_to"]=(start-timedelta(days=1)).isoformat()
            else: raise ApiError("Vehicle efficiency period overlaps an existing period.", status_code=409)
    timestamp=now_utc(); actor=_oid(current_user_id,"current_user_id")
    entry={"km_per_litre":efficiency,"effective_from":start.isoformat(),"effective_to":end.isoformat() if end else None,"reason":reason,"changed_by":actor,"changed_at":timestamp}
    history.append(entry); history.sort(key=lambda item:str(item.get("effective_from") or ""))
    get_collection("vehicles").update_one({"_id":oid},{"$set":{"fuel_efficiency_history":history,"updated_at":timestamp}})
    get_collection("fleet_owner_audit").insert_one({"actor_id":actor,"actor_role":current_role,"action":"vehicle_fuel_efficiency_scheduled","entity_type":"vehicle","entity_id":oid,"after":entry,"reason":reason,"created_at":timestamp,"immutable":True})
    return {**entry,"changed_by":str(actor),"changed_at":timestamp.isoformat(),"vehicle_id":str(oid)}


def _effective_setting(kind, on_date):
    candidates = []
    for item in finance_settings_collection().find({"setting_type": kind}):
        start = _date(item.get("effective_from"))
        end = _date(item.get("effective_to"), "effective_to") if item.get("effective_to") else None
        if start <= on_date and (end is None or on_date <= end):
            candidates.append((start, item))
    if candidates:
        return max(candidates, key=lambda pair: pair[0])[1]
    if kind == "maintenance_reserve_rate":
        return {"setting_type": kind, "value": 25.0, "effective_from": None, "effective_to": None, "reason": "Initial system default"}
    return None


def _setting_snapshot(item):
    if not item:
        return None
    return {key: item.get(key) for key in ("setting_type", "value", "configuration", "effective_from", "effective_to", "reason")}


def _funding_snapshot(payload, concession):
    if concession <= 0:
        return None
    item = resolve_master_data_item("funding_sources", payload.get("funding_source_id"), active_only=True)
    if not item:
        raise ApiError("funding_source_id is required for Subsidized and Complimentary dispatches.", status_code=400)
    description = str(payload.get("funding_source_description") or "").strip() or None
    if str(item.get("name") or "").strip().lower() == "other" and not description:
        raise ApiError("funding_source_description is required when Funding Source is Other.", status_code=400)
    return {"id": str(item["_id"]), "name": item.get("name"), "description": description}


def _adjustments(payload, commercial_value):
    result, total = [], 0.0
    for raw in payload.get("driver_adjustments") or []:
        category = str(raw.get("category") or "").strip().lower()
        reason = str(raw.get("reason") or "").strip()
        mode = str(raw.get("mode") or "amount").strip().lower()
        if category not in ADJUSTMENT_CATEGORIES or not reason:
            raise ApiError("Every driver adjustment requires a valid category and reason.", status_code=400)
        if mode not in COMPENSATION_MODES:
            raise ApiError("Driver adjustment mode must be AMOUNT or PERCENTAGE.", status_code=400)
        value = _number(raw.get("value"), "driver adjustment value")
        if mode == "percentage" and value > 100:
            raise ApiError("Driver adjustment percentage cannot exceed 100.", status_code=400)
        amount = round(commercial_value * value / 100, 2) if mode == "percentage" else value
        result.append({"category": category, "reason": reason, "mode": mode, "value": value, "amount": amount})
        total += amount
    return result, round(total, 2)


def _vehicle_efficiency(vehicle, on_date):
    history = vehicle.get("fuel_efficiency_history") or []
    applicable = []
    for item in history:
        try:
            start = _date(item.get("effective_from")); end = _date(item.get("effective_to"), "effective_to") if item.get("effective_to") else None
        except ApiError:
            continue
        if start <= on_date and (end is None or on_date <= end):
            applicable.append((start, item))
    if applicable:
        item = max(applicable, key=lambda pair: pair[0])[1]
        return float(item.get("km_per_litre") or 0), {key: item.get(key) for key in ("km_per_litre", "effective_from", "effective_to", "reason")}
    economics = vehicle.get("economics") or {}
    value = vehicle.get("km_per_litre") or economics.get("km_per_litre") or economics.get("fuel_efficiency_km_per_litre") or 0
    return float(value or 0), {"km_per_litre": float(value or 0), "effective_from": None, "legacy_vehicle_value": True}


def _job(job_id):
    oid = _oid(job_id, "dispatch_job_id")
    job = jobs_collection().find_one({"_id": oid})
    if not job:
        raise ApiError("Dispatch job not found.", status_code=404)
    return job


def build_finance_preview(job_id, payload, *, current_user_id, current_role):
    if current_role not in PRIVILEGED_ROLES:
        raise ApiError("You do not have permission to preview dispatch finance.", status_code=403)
    job = _job(job_id)
    request_doc = get_collection("dispatch_requests").find_one({"_id": job.get("dispatch_request_id")}) or {}
    vehicle = get_collection("vehicles").find_one({"_id": job.get("vehicle_id")}) or {}
    movement = get_collection("vehicle_movements").find_one({"dispatch_job_id": job["_id"]}) or {}
    dispatch_date = _date_of(job)
    commercial = _number(payload.get("commercial_value", request_doc.get("commercial_value", request_doc.get("approved_charge", request_doc.get("proposed_charge")))), "commercial_value")
    pricing_type = str(payload.get("pricing_type") or request_doc.get("pricing_type") or "standard").strip().lower()
    if pricing_type not in PRICING_TYPES:
        raise ApiError("pricing_type must be STANDARD, SUBSIDIZED, or COMPLIMENTARY.", status_code=400)
    default_charge = 0 if pricing_type == "complimentary" else request_doc.get("customer_charge", request_doc.get("approved_charge", commercial))
    charge = _number(payload.get("customer_charge", default_charge), "customer_charge")
    if charge > commercial:
        raise ApiError("customer_charge cannot exceed commercial_value.", status_code=400)
    if pricing_type == "standard" and charge != commercial:
        raise ApiError("STANDARD dispatch customer_charge must equal commercial_value.", status_code=400)
    if pricing_type == "subsidized" and not (0 < charge < commercial):
        raise ApiError("SUBSIDIZED dispatch requires customer_charge between zero and commercial_value.", status_code=400)
    if pricing_type == "complimentary" and charge != 0:
        raise ApiError("COMPLIMENTARY dispatch customer_charge must be zero.", status_code=400)
    concession = round(commercial - charge, 2)
    funding = _funding_snapshot(payload, concession)
    billable = _number(payload.get("billable_distance_km", request_doc.get("distance_estimate_km", job.get("distance_estimate_km", 0))), "billable_distance_km")
    odometer_distance = None
    if movement.get("opening_odometer") is not None and movement.get("closing_odometer") is not None:
        odometer_distance = max(float(movement["closing_odometer"]) - float(movement["opening_odometer"]), 0)
    operational = _number(payload.get("operational_distance_km", odometer_distance if odometer_distance is not None else billable), "operational_distance_km")
    efficiency, efficiency_snapshot = _vehicle_efficiency(vehicle, dispatch_date)
    fuel_setting = _effective_setting("fuel_price_per_litre", dispatch_date)
    fuel_price = float((fuel_setting or {}).get("value") or 0)
    litres = round(operational / efficiency, 2) if efficiency > 0 else 0
    fuel_cost = round(litres * fuel_price, 2)
    reserve_setting = _effective_setting("maintenance_reserve_rate", dispatch_date)
    reserve_rate = float(reserve_setting.get("value") or 25)
    reserve = round(commercial * reserve_rate / 100, 2)
    mode = str(payload.get("driver_compensation_mode") or "amount").strip().lower()
    if mode not in COMPENSATION_MODES:
        raise ApiError("driver_compensation_mode must be AMOUNT or PERCENTAGE.", status_code=400)
    value = _number(payload.get("driver_compensation_value", 0), "driver_compensation_value")
    if mode == "percentage" and value > 100:
        raise ApiError("driver_compensation_value cannot exceed 100 percent.", status_code=400)
    base_compensation = round(commercial * value / 100, 2) if mode == "percentage" else value
    adjustments, extras = _adjustments(payload, commercial)
    approved_compensation = round(base_compensation + extras, 2)
    other_costs = _number(payload.get("other_direct_costs", 0), "other_direct_costs")
    capital_setting = _effective_setting("vehicle_capital_profit_rule", dispatch_date)
    capital = 0.0
    rule = (capital_setting or {}).get("configuration") or {}
    if rule.get("mode") == "amount":
        capital = _number(rule.get("value", 0), "vehicle capital/profit amount")
    elif rule.get("mode") == "percentage":
        capital = round(commercial * _number(rule.get("value", 0), "vehicle capital/profit percentage") / 100, 2)
    total_income = round(charge + concession, 2)
    contribution = round(total_income - fuel_cost - approved_compensation - reserve - other_costs - capital, 2)
    suggested = _number(payload.get("suggested_driver_compensation", base_compensation), "suggested_driver_compensation")
    effective_percent = round(approved_compensation / commercial * 100, 2) if commercial else 0
    warnings = []
    if efficiency <= 0: warnings.append("Vehicle fuel efficiency is not configured; estimated fuel cost is incomplete.")
    if fuel_price <= 0: warnings.append("Effective fuel price is not configured; estimated fuel cost is incomplete.")
    if contribution < 0: warnings.append("Pricing is inadequate: expected company contribution is negative.")
    return {
        "snapshot_version": 1, "basis": "estimate", "dispatch_job_id": str(job["_id"]),
        "dispatch_date": dispatch_date.isoformat(), "vehicle_id": str(job.get("vehicle_id")) if job.get("vehicle_id") else None,
        "driver_id": str(job.get("driver_id")) if job.get("driver_id") else None,
        "pricing_type": pricing_type, "commercial_value": commercial, "customer_charge": charge,
        "concession_value": concession, "funding_source": funding,
        "billable_distance_km": billable, "operational_distance_km": operational,
        "fuel": {"litres": litres, "cost": fuel_cost, "price_per_litre": fuel_price, "price_setting": _setting_snapshot(fuel_setting), "vehicle_efficiency": efficiency_snapshot},
        "driver_compensation": {"mode": mode, "value": value, "suggested_amount": suggested, "base_amount": base_compensation, "adjustments": adjustments, "extras_amount": extras, "approved_amount": approved_compensation, "effective_percentage": effective_percent, "evidence": payload.get("journey_evidence") or {}},
        "maintenance_reserve": {"rate_percent": reserve_rate, "amount": reserve, "setting": _setting_snapshot(reserve_setting), "funding_shortfall": round(concession * reserve_rate / 100, 2)},
        "other_direct_costs": other_costs, "vehicle_capital_profit_allocation": capital,
        "vehicle_capital_profit_rule": _setting_snapshot(capital_setting),
        "expected_company_contribution": contribution, "warnings": warnings,
    }


def _ensure_reserve_credit(job, record, snapshot):
    reserve_amount = float((snapshot.get("maintenance_reserve") or {}).get("amount") or 0)
    if reserve_amount <= 0 or not job.get("vehicle_id"):
        return
    reserve_entries_collection().update_one(
        {"source_key": f"dispatch:{job['_id']}:reserve"},
        {"$setOnInsert": {"source_key": f"dispatch:{job['_id']}:reserve", "entry_type": "earned", "amount": round(reserve_amount, 2), "vehicle_id": job["vehicle_id"], "dispatch_job_id": job["_id"], "financial_record_id": record["_id"], "posted_at": now_utc(), "snapshot_rate_percent": (snapshot.get("maintenance_reserve") or {}).get("rate_percent")}},
        upsert=True,
    )


def approve_finance_snapshot(job_id, payload, *, current_user_id, current_role, idempotency_key=None):
    if current_role not in {"owner", "admin", "finance", "finance_officer"}:
        raise ApiError("You do not have permission to approve dispatch finance.", status_code=403)
    job = _job(job_id)
    record = financials_collection().find_one({"dispatch_job_id": job["_id"]})
    if not record:
        from services.dispatch_financial_service import ensure_dispatch_financial_record
        record = ensure_dispatch_financial_record(job_document=job)
    if record.get("finance_snapshot"):
        _ensure_reserve_credit(job, record, record["finance_snapshot"])
        return record["finance_snapshot"]
    snapshot = build_finance_preview(job_id, payload, current_user_id=current_user_id, current_role=current_role)
    if snapshot["warnings"] and snapshot["expected_company_contribution"] < 0:
        if not payload.get("pricing_override"):
            raise ApiError("Pricing is inadequate. An authorized override and reason are required.", status_code=409)
        reason = str(payload.get("pricing_override_reason") or "").strip()
        if not reason:
            raise ApiError("pricing_override_reason is required.", status_code=400)
        snapshot["pricing_override"] = {"reason": reason, "authorized_by": current_user_id}
    timestamp = now_utc()
    snapshot.update({"approved_at": timestamp.isoformat(), "approved_by": current_user_id, "immutable": True, "idempotency_key": str(idempotency_key or payload.get("idempotency_key") or "").strip() or None})
    update = {
        "finance_snapshot": snapshot, "pricing_type": snapshot["pricing_type"],
        "commercial_value": snapshot["commercial_value"], "customer_charge": snapshot["customer_charge"],
        "concession_value": snapshot["concession_value"], "funding_source_snapshot": snapshot["funding_source"],
        "driver_compensation_amount": snapshot["driver_compensation"]["approved_amount"],
        "maintenance_reserve_amount": snapshot["maintenance_reserve"]["amount"],
        "financial_status": "verified", "verified_by": _oid(current_user_id, "current_user_id"),
        "verified_at": timestamp, "updated_at": timestamp,
    }
    result = financials_collection().update_one({"_id": record["_id"], "finance_snapshot": {"$exists": False}}, {"$set": update})
    if result.modified_count != 1:
        existing_snapshot = financials_collection().find_one({"_id": record["_id"]})["finance_snapshot"]
        _ensure_reserve_credit(job, record, existing_snapshot)
        return existing_snapshot
    _ensure_reserve_credit(job, record, snapshot)
    return snapshot


def finalize_finance_snapshot(job_id, payload, *, current_user_id, current_role):
    """Capture actual journey finance without mutating the approval snapshot."""
    if current_role not in {"owner", "admin", "finance", "finance_officer"}:
        raise ApiError("You do not have permission to finalize dispatch finance.", status_code=403)
    job = _job(job_id)
    record = financials_collection().find_one({"dispatch_job_id": job["_id"]})
    if not record or not record.get("finance_snapshot"):
        raise ApiError("Approve the estimated finance snapshot before final reconciliation.", status_code=409)
    if record.get("final_finance_snapshot"):
        return record["final_finance_snapshot"]
    estimate = record["finance_snapshot"]
    merged = {
        "commercial_value": estimate["commercial_value"], "customer_charge": estimate["customer_charge"],
        "pricing_type": estimate["pricing_type"],
        "funding_source_id": (estimate.get("funding_source") or {}).get("id"),
        "funding_source_description": (estimate.get("funding_source") or {}).get("description"),
        "billable_distance_km": payload.get("actual_billable_distance_km", estimate.get("billable_distance_km")),
        "operational_distance_km": payload.get("actual_operational_distance_km", estimate.get("operational_distance_km")),
        "driver_compensation_mode": payload.get("driver_compensation_mode", (estimate.get("driver_compensation") or {}).get("mode")),
        "driver_compensation_value": payload.get("driver_compensation_value", (estimate.get("driver_compensation") or {}).get("value")),
        "driver_adjustments": payload.get("driver_adjustments", (estimate.get("driver_compensation") or {}).get("adjustments", [])),
        "suggested_driver_compensation": payload.get("suggested_driver_compensation", (estimate.get("driver_compensation") or {}).get("suggested_amount", 0)),
        "journey_evidence": payload.get("journey_evidence") or {},
        "other_direct_costs": payload.get("actual_other_direct_costs", estimate.get("other_direct_costs", 0)),
    }
    # Existing adjustment snapshots already contain calculated amounts; retain only
    # their source inputs when they are reused for final confirmation.
    merged["driver_adjustments"] = [{k: item.get(k) for k in ("category", "reason", "mode", "value")} for item in merged["driver_adjustments"]]
    final = build_finance_preview(job_id, merged, current_user_id=current_user_id, current_role=current_role)
    # Final actuals must use the assumptions locked at approval, even if an
    # owner has since scheduled new rates.
    locked_fuel = estimate.get("fuel") or {}
    locked_efficiency = float((locked_fuel.get("vehicle_efficiency") or {}).get("km_per_litre") or 0)
    locked_price = float(locked_fuel.get("price_per_litre") or 0)
    actual_litres = round(final["operational_distance_km"] / locked_efficiency, 2) if locked_efficiency > 0 else 0
    final["fuel"] = {
        **locked_fuel, "litres": actual_litres, "cost": round(actual_litres * locked_price, 2),
    }
    if payload.get("actual_fuel_cost") not in (None, ""):
        final["fuel"]["cost"] = _number(payload.get("actual_fuel_cost"), "actual_fuel_cost")
        final["fuel"]["actual_cost_recorded"] = True
    if payload.get("actual_fuel_litres") not in (None, ""):
        final["fuel"]["litres"] = _number(payload.get("actual_fuel_litres"), "actual_fuel_litres")
    final["maintenance_reserve"] = estimate.get("maintenance_reserve") or final["maintenance_reserve"]
    final["vehicle_capital_profit_allocation"] = estimate.get("vehicle_capital_profit_allocation", 0)
    final["vehicle_capital_profit_rule"] = estimate.get("vehicle_capital_profit_rule")
    final["expected_company_contribution"] = round(
        float(final.get("customer_charge") or 0) + float(final.get("concession_value") or 0)
        - float(final["fuel"].get("cost") or 0)
        - float(final["driver_compensation"].get("approved_amount") or 0)
        - float(final["maintenance_reserve"].get("amount") or 0)
        - float(final.get("other_direct_costs") or 0)
        - float(final.get("vehicle_capital_profit_allocation") or 0), 2,
    )
    timestamp = now_utc()
    final.update({
        "basis": "actual", "finalized_at": timestamp.isoformat(), "finalized_by": current_user_id,
        "immutable": True,
        "estimated_vs_actual": {
            "operational_distance_km": {"estimated": estimate.get("operational_distance_km"), "actual": final.get("operational_distance_km")},
            "fuel_cost": {"estimated": (estimate.get("fuel") or {}).get("cost"), "actual": (final.get("fuel") or {}).get("cost")},
            "driver_compensation": {"estimated": (estimate.get("driver_compensation") or {}).get("approved_amount"), "actual": (final.get("driver_compensation") or {}).get("approved_amount")},
            "other_direct_costs": {"estimated": estimate.get("other_direct_costs"), "actual": final.get("other_direct_costs")},
            "company_contribution": {"estimated": estimate.get("expected_company_contribution"), "actual": final.get("expected_company_contribution")},
        },
    })
    result = financials_collection().update_one(
        {"_id": record["_id"], "final_finance_snapshot": {"$exists": False}},
        {"$set": {"final_finance_snapshot": final, "driver_compensation_amount": final["driver_compensation"]["approved_amount"], "actual_fuel_cost": final["fuel"]["cost"], "actual_net_revenue": final["expected_company_contribution"], "updated_at": timestamp}},
    )
    if result.modified_count != 1:
        return financials_collection().find_one({"_id": record["_id"]})["final_finance_snapshot"]
    return final


def post_reserve_spend_for_expense(expense_document, *, actor_id):
    """Debit reserve once for a paid, vehicle-linked maintenance expense."""
    maintenance_id = expense_document.get("maintenance_job_id")
    vehicle_id = expense_document.get("vehicle_id")
    if not maintenance_id or not vehicle_id:
        return None
    requested = expense_document.get("maintenance_reserve_amount")
    amount = float(requested if requested is not None else expense_document.get("amount") or 0)
    if amount <= 0:
        return None
    balance = reserve_balance(vehicle_id)["balance"]
    if amount > balance:
        raise ApiError("Vehicle maintenance reserve balance is insufficient.", status_code=400)
    key = f"expense:{expense_document['_id']}:reserve"
    reserve_entries_collection().update_one({"source_key": key}, {"$setOnInsert": {
        "source_key": key, "entry_type": "spent", "amount": round(amount, 2), "vehicle_id": vehicle_id,
        "maintenance_job_id": maintenance_id, "expense_id": expense_document["_id"],
        "posted_at": now_utc(), "posted_by": _oid(actor_id, "actor_id"),
    }}, upsert=True)
    return reserve_balance(vehicle_id)


def reserve_balance(vehicle_id):
    oid = _oid(vehicle_id, "vehicle_id")
    entries = list(reserve_entries_collection().find({"vehicle_id": oid}).sort("posted_at", 1))
    earned = round(sum(float(item.get("amount") or 0) for item in entries if item.get("entry_type") == "earned"), 2)
    spent = round(sum(float(item.get("amount") or 0) for item in entries if item.get("entry_type") == "spent"), 2)
    serialized = []
    for item in entries:
        row = {"id": str(item.get("_id"))}
        for key, value in item.items():
            if key == "_id": continue
            if isinstance(value, ObjectId): value = str(value)
            elif isinstance(value, datetime): value = value.isoformat()
            row[key] = value
        serialized.append(row)
    return {"vehicle_id": str(oid), "earned": earned, "spent": spent, "balance": round(earned-spent, 2), "entries": serialized}


def dispatch_finance_analytics(*, current_user_id, current_role, start_date=None, end_date=None, preset=None, driver_id=None, vehicle_id=None, pricing_type=None, funding_source_id=None, branch_id=None):
    today = now_utc().date(); preset = str(preset or "").lower()
    if preset == "today": start = end = today
    elif preset == "this_week": start = today - timedelta(days=today.weekday()); end = today
    elif preset == "last_week": end = today - timedelta(days=today.weekday()+1); start = end-timedelta(days=6)
    elif preset == "this_month": start = today.replace(day=1); end = today
    else: start = _date(start_date, "start_date") if start_date else date.min; end = _date(end_date, "end_date") if end_date else today
    if start > end: raise ApiError("start_date cannot be after end_date.", status_code=400)
    if current_role == "driver":
        if driver_id and str(driver_id) != str(current_user_id): raise ApiError("Drivers can only view their own analytics.", status_code=403)
        driver_id = current_user_id
    elif current_role not in PRIVILEGED_ROLES:
        raise ApiError("You do not have permission to view dispatch finance analytics.", status_code=403)
    query = {"finance_snapshot": {"$exists": True}}
    if driver_id: query["driver_id"] = _oid(driver_id, "driver_id")
    if vehicle_id: query["vehicle_id"] = _oid(vehicle_id, "vehicle_id")
    rows = []
    for record in financials_collection().find(query):
        snapshot = record.get("final_finance_snapshot") or record.get("finance_snapshot") or {}
        try: row_date = _date(snapshot.get("dispatch_date"), "dispatch_date")
        except ApiError: continue
        if not start <= row_date <= end: continue
        if pricing_type and snapshot.get("pricing_type") != pricing_type: continue
        funding = snapshot.get("funding_source") or {}
        if funding_source_id and str(funding.get("id")) != str(funding_source_id): continue
        job = jobs_collection().find_one({"_id": record.get("dispatch_job_id")}) or {}
        vehicle = get_collection("vehicles").find_one({"_id": record.get("vehicle_id")}) or {}
        if branch_id and str(job.get("branch_id") or vehicle.get("branch_id")) != str(branch_id): continue
        rows.append((record, snapshot, job, vehicle))
    def total(path):
        keys=path.split("."); value=0
        for _r,s,_j,_v in rows:
            item=s
            for key in keys: item=(item or {}).get(key)
            value += float(item or 0)
        return round(value,2)
    pricing = {kind: {"count": sum(1 for _r,s,_j,_v in rows if s.get("pricing_type")==kind), "commercial_value": round(sum(float(s.get("commercial_value") or 0) for _r,s,_j,_v in rows if s.get("pricing_type")==kind),2), "customer_revenue": round(sum(float(s.get("customer_charge") or 0) for _r,s,_j,_v in rows if s.get("pricing_type")==kind),2)} for kind in sorted(PRICING_TYPES)}
    collections = list(get_collection("collections").find({"dispatch_job_id": {"$in": [r.get("dispatch_job_id") for r,_s,_j,_v in rows]}, "status": {"$ne": "reversed"}})) if rows else []
    collections_by_job = {}
    for item in collections: collections_by_job.setdefault(item.get("dispatch_job_id"), []).append(item)
    collected=round(sum(float(i.get("amount") or 0) for i in collections),2); submitted=round(sum(float(i.get("submitted_amount") if i.get("submitted_amount") is not None else i.get("amount") or 0) for i in collections if i.get("status") in {"submitted","received","approved"}),2)
    summary={"dispatch_count":len(rows),"completed_dispatches":sum(1 for _r,_s,j,_v in rows if j.get("status") in {"completed","closed"} or j.get("return_status")=="dispatch_closed"),"commercial_value":total("commercial_value"),"customer_revenue":total("customer_charge"),"concessions":total("concession_value"),"fuel":total("fuel.cost"),"driver_compensation":total("driver_compensation.approved_amount"),"maintenance_reserve":total("maintenance_reserve.amount"),"other_direct_costs":total("other_direct_costs"),"vehicle_capital_profit":total("vehicle_capital_profit_allocation"),"company_contribution":total("expected_company_contribution"),"collections":collected,"submissions":submitted,"outstanding_reconciliation":round(max(collected-submitted,0),2),"pricing":pricing}
    driver_groups, vehicle_groups = {}, {}
    for record, snapshot, job, vehicle in rows:
        did, vid = record.get("driver_id"), record.get("vehicle_id")
        user = get_collection("users").find_one({"_id": did}) or {}
        comp = float((snapshot.get("driver_compensation") or {}).get("approved_amount") or 0)
        linked = collections_by_job.get(record.get("dispatch_job_id"), [])
        collected_row = sum(float(item.get("amount") or 0) for item in linked)
        submitted_row = sum(float(item.get("submitted_amount") if item.get("submitted_amount") is not None else item.get("amount") or 0) for item in linked if item.get("status") in {"submitted","received","approved"})
        dg = driver_groups.setdefault(did, {"driver_id":str(did) if did else None,"driver_name":user.get("full_name") or "Unassigned driver","assigned_dispatches":0,"completed_dispatches":0,"trips":0,"operational_km":0.0,"duration_minutes":0.0,"standard":0,"subsidized":0,"complimentary":0,"collections":0.0,"submissions":0.0,"compensation":0.0,"outstanding_reconciliation":0.0})
        dg["assigned_dispatches"]+=1; dg["trips"]+=1; dg["completed_dispatches"]+=int(job.get("status") in {"completed","closed"} or job.get("return_status")=="dispatch_closed")
        dg["operational_km"]+=float(snapshot.get("operational_distance_km") or 0); dg["duration_minutes"]+=float(((snapshot.get("driver_compensation") or {}).get("evidence") or {}).get("duration_minutes") or 0)
        dg[snapshot.get("pricing_type") or "standard"]+=1; dg["collections"]+=collected_row; dg["submissions"]+=submitted_row; dg["compensation"]+=comp; dg["outstanding_reconciliation"]+=max(collected_row-submitted_row,0)
        vg = vehicle_groups.setdefault(vid, {"vehicle_id":str(vid) if vid else None,"vehicle_name":vehicle.get("registration_number") or "Unassigned vehicle","trips":0,"operational_km":0.0,"commercial_value":0.0,"customer_revenue":0.0,"fuel":0.0,"maintenance_earned":0.0,"maintenance_spent":0.0,"maintenance_balance":0.0,"driver_compensation":0.0,"capital_profit_allocation":0.0,"net_contribution":0.0})
        vg["trips"]+=1; vg["operational_km"]+=float(snapshot.get("operational_distance_km") or 0); vg["commercial_value"]+=float(snapshot.get("commercial_value") or 0); vg["customer_revenue"]+=float(snapshot.get("customer_charge") or 0); vg["fuel"]+=float((snapshot.get("fuel") or {}).get("cost") or 0); vg["maintenance_earned"]+=float((snapshot.get("maintenance_reserve") or {}).get("amount") or 0); vg["driver_compensation"]+=comp; vg["capital_profit_allocation"]+=float(snapshot.get("vehicle_capital_profit_allocation") or 0); vg["net_contribution"]+=float(snapshot.get("expected_company_contribution") or 0)
    from services.finance_foundation_service import target_for_date
    for did, group in driver_groups.items():
        user = get_collection("users").find_one({"_id": did}) or {}
        target_record = target_for_date(user, end); group["target"] = float(target_record.get("target_amount") or 0); group["target_record"] = {key: target_record.get(key) for key in ("target_amount","target_frequency","effective_from","effective_to","reason")}
        group["target_achievement_percentage"] = round(group["collections"] / group["target"] * 100, 2) if group["target"] else 0
        for key in ("operational_km","duration_minutes","collections","submissions","compensation","outstanding_reconciliation"): group[key]=round(group[key],2)
    for vid, group in vehicle_groups.items():
        reserve = reserve_balance(vid) if vid else {"spent":0,"balance":0}
        group["maintenance_spent"]=reserve["spent"]; group["maintenance_balance"]=reserve["balance"]
        for key in ("operational_km","commercial_value","customer_revenue","fuel","maintenance_earned","driver_compensation","capital_profit_allocation","net_contribution"): group[key]=round(group[key],2)
    if current_role == "driver":
        summary.pop("company_contribution",None); summary.pop("vehicle_capital_profit",None); summary.pop("other_direct_costs",None)
        for group in vehicle_groups.values():
            for key in ("fuel","maintenance_earned","maintenance_spent","maintenance_balance","capital_profit_allocation","net_contribution"): group.pop(key,None)
    return {"start_date": None if start==date.min else start.isoformat(),"end_date":end.isoformat(),"summary":summary,"company":summary,"drivers":list(driver_groups.values()),"vehicles":list(vehicle_groups.values()),"records":[{"dispatch_job_id":str(r.get("dispatch_job_id")),"driver_name":(get_collection("users").find_one({"_id":r.get("driver_id")}) or {}).get("full_name") or "Unassigned driver","vehicle_registration":v.get("registration_number"),"pricing_type":s.get("pricing_type"),"commercial_value":s.get("commercial_value"),"customer_charge":s.get("customer_charge"),"driver_compensation":(s.get("driver_compensation") or {}).get("approved_amount"),"operational_distance_km":s.get("operational_distance_km")} for r,s,j,v in rows]}
