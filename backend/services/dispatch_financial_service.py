from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from math import ceil
from time import perf_counter

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.dispatch_financial import (
    serialize_dispatch_financial_detail,
    serialize_dispatch_financial_expense,
    serialize_dispatch_financial_incident,
    serialize_dispatch_financial_record,
)
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.dispatch_return_service import dispatch_jobs_collection, vehicle_movements_collection
from utils.api_error import ApiError
from utils.dispatch_payment_classification import (
    DISPATCH_FINANCIAL_TYPES,
    DRIVER_COMPENSATION_TYPES,
    PARTNER_BILLING_METHODS,
    calculate_driver_compensation,
    normalize_key,
    recognizes_individual_customer_revenue,
    requires_immediate_customer_payment,
    resolve_dispatch_financial_type,
)
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import log_db_duration


FINANCIAL_STATUSES = {
    "pending_collection",
    "partially_submitted",
    "fully_submitted",
    "outstanding",
    "under_review",
    "verified",
    "disputed",
    "cancelled",
}
EXPENSE_TYPES = {
    "fuel",
    "loading",
    "offloading",
    "toll",
    "parking",
    "helper_payment",
    "customer_refund",
    "emergency_purchase",
    "other",
}
EXPENSE_STATUSES = {"pending", "approved", "rejected", "reimbursed", "cancelled"}
FINANCIAL_INCIDENT_TYPES = {
    "police_arrest",
    "traffic_fine",
    "wrong_turn_penalty",
    "wrong_parking",
    "overloading_fine",
    "vehicle_documentation_issue",
    "insurance_claim",
    "accident_cost",
    "vehicle_impound_charges",
    "towing",
    "driver_misconduct",
    "company_operational_error",
    "other",
}
RESPONSIBILITY_TYPES = {
    "driver_responsible",
    "company_responsible",
    "shared_responsibility",
    "under_investigation",
}
FINANCIAL_INCIDENT_STATUSES = {
    "reported",
    "under_review",
    "approved",
    "rejected",
    "company_paid",
    "driver_liable",
    "shared_payment",
    "closed",
    "cancelled",
}
ADMIN_ROLES = {"owner", "admin"}
ACTIVE_INCIDENT_BLOCKING_STATUSES = {"reported", "under_review", "approved", "company_paid", "driver_liable", "shared_payment"}
FINANCIAL_READY_RETURN_STATUSES = {"returned", "inspection_completed", "dispatch_closed"}
LIST_PROJECTION = {
    "dispatch_job_id": 1,
    "vehicle_id": 1,
    "driver_id": 1,
    "vehicle_movement_id": 1,
    "approved_charge": 1,
    "amount_paid": 1,
    "dispatch_financial_type": 1,
    "partner_organization_reference": 1,
    "partner_billing_method": 1,
    "driver_compensation_type": 1,
    "driver_compensation_value": 1,
    "driver_compensation_amount": 1,
    "driver_compensation_approved_by": 1,
    "driver_compensation_approved_at": 1,
    "company_operational_cost": 1,
    "amount_collected_from_customer": 1,
    "amount_submitted_by_driver": 1,
    "outstanding_balance": 1,
    "approved_expenses": 1,
    "company_incident_costs": 1,
    "driver_liability_total": 1,
    "expected_net_revenue": 1,
    "actual_net_revenue": 1,
    "financial_status": 1,
    "submitted_at": 1,
    "verified_at": 1,
    "is_financially_closed": 1,
    "updated_at": 1,
}
USER_PROJECTION = {"full_name": 1, "phone": 1, "email": 1, "role": 1, "status": 1}
VEHICLE_PROJECTION = {"registration_number": 1, "make": 1, "model": 1, "vehicle_type": 1, "status": 1}
DISPATCH_REQUEST_PROJECTION = {
    "approved_charge": 1,
    "proposed_charge": 1,
    "fuel_estimate_cost": 1,
    "other_expected_costs": 1,
    "expected_net_revenue": 1,
    "dispatch_financial_type": 1,
    "partner_organization_reference": 1,
    "partner_billing_method": 1,
    "payment_method": 1,
    "amount_paid": 1,
    "driver_compensation_type": 1,
    "driver_compensation_value": 1,
    "driver_compensation_amount": 1,
    "driver_compensation_approved_by": 1,
    "driver_compensation_approved_at": 1,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fuel_logs_collection():
    return get_collection("fuel_logs")


def dispatch_financials_collection():
    return get_collection("dispatch_financial_records")


def dispatch_financial_expenses_collection():
    return get_collection("dispatch_financial_expenses")


def dispatch_financial_incidents_collection():
    return get_collection("dispatch_financial_incidents")


def dispatch_requests_collection():
    return get_collection("dispatch_requests")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def incidents_collection():
    return get_collection("incidents")


def ensure_dispatch_financial_indexes():
    ensure_indexes_for_collection(
        dispatch_financials_collection(),
        [
            {"keys": [("dispatch_job_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("vehicle_movement_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("driver_id", ASCENDING), ("financial_status", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("financial_status", ASCENDING)]},
            {"keys": [("financial_status", ASCENDING), ("submitted_at", DESCENDING)]},
            {"keys": [("verified_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("submitted_at", DESCENDING)], "options": {"sparse": True}},
        ],
        collection_name="dispatch_financial_records",
    )
    ensure_indexes_for_collection(
        dispatch_financial_expenses_collection(),
        [
            {"keys": [("dispatch_financial_id", ASCENDING)]},
            {"keys": [("dispatch_job_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("submitted_at", DESCENDING)]},
            {"keys": [("expense_type", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("submitted_at", DESCENDING)]},
        ],
        collection_name="dispatch_financial_expenses",
    )
    ensure_indexes_for_collection(
        dispatch_financial_incidents_collection(),
        [
            {"keys": [("dispatch_financial_id", ASCENDING)]},
            {"keys": [("dispatch_job_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("submitted_at", DESCENDING)]},
            {"keys": [("incident_type", ASCENDING), ("responsibility_type", ASCENDING)]},
            {"keys": [("reviewed_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("submitted_at", DESCENDING)]},
        ],
        collection_name="dispatch_financial_incidents",
    )


def _normalize_text(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _to_object_id(value, field_name: str, *, required: bool = True) -> ObjectId | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _normalize_positive_amount(value, field_name: str, *, required: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    numeric = round(float(value), 2)
    if numeric <= 0:
        raise ApiError(f"{field_name} must be greater than zero.", status_code=400)
    return numeric


def _normalize_non_negative_amount(value, field_name: str, *, required: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    numeric = round(float(value), 2)
    if numeric < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return numeric


def _normalize_status(value: str | None, allowed_values: set[str], field_name: str, *, default: str | None = None) -> str:
    normalized = (_normalize_text(value) or default or "").lower()
    if normalized not in allowed_values:
        raise ApiError(f"Invalid {field_name}.", status_code=400)
    return normalized


def _parse_date(value, field_name: str, *, required: bool = False) -> str | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    candidate = str(value).strip()
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat() if "T" in candidate else datetime.strptime(candidate[:10], "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ApiError(f"{field_name} must be a valid date.", status_code=400) from error


def _get_dispatch_job(job_id: str | ObjectId) -> dict:
    job_object_id = _to_object_id(job_id, "dispatch_job_id")
    document = dispatch_jobs_collection().find_one({"_id": job_object_id})
    if not document:
        raise ApiError("Dispatch job not found.", status_code=404)
    return document


def _get_dispatch_request(job_document: dict) -> dict | None:
    request_id = job_document.get("dispatch_request_id")
    if not isinstance(request_id, ObjectId):
        return None
    return dispatch_requests_collection().find_one({"_id": request_id}, DISPATCH_REQUEST_PROJECTION)


def _get_vehicle_movement_for_job(job_document: dict) -> dict | None:
    movement_id = job_document.get("linked_vehicle_movement_id")
    if isinstance(movement_id, ObjectId):
        movement = vehicle_movements_collection().find_one({"_id": movement_id})
        if movement:
            return movement
    return vehicle_movements_collection().find_one({"dispatch_job_id": job_document["_id"]})


def _get_financial_record_by_id(financial_id: str | ObjectId) -> dict:
    document = dispatch_financials_collection().find_one({"_id": _to_object_id(financial_id, "dispatch_financial_id")})
    if not document:
        raise ApiError("Dispatch financial record not found.", status_code=404)
    return document


def _get_financial_record_for_job(job_document: dict) -> dict:
    document = dispatch_financials_collection().find_one({"dispatch_job_id": job_document["_id"]})
    if document:
        return _sync_financial_record(document, job_document=job_document)
    return _create_financial_record(job_document)


def _ensure_financial_records_for_completed_dispatches(*, driver_id: ObjectId | None = None):
    query: dict = {"return_status": {"$in": sorted(FINANCIAL_READY_RETURN_STATUSES)}}
    if driver_id is not None:
        query["driver_id"] = driver_id
    jobs = list(
        dispatch_jobs_collection().find(
            query,
            {
                "_id": 1,
                "dispatch_request_id": 1,
                "linked_vehicle_movement_id": 1,
                "vehicle_id": 1,
                "driver_id": 1,
                "return_status": 1,
            },
        )
    )
    if not jobs:
        return
    existing_job_ids = {
        item["dispatch_job_id"]
        for item in dispatch_financials_collection().find(
            {"dispatch_job_id": {"$in": [job["_id"] for job in jobs]}},
            {"dispatch_job_id": 1},
        )
    }
    for job in jobs:
        if job["_id"] not in existing_job_ids:
            _create_financial_record(job)


def ensure_dispatch_financial_record(*, job_id: str | None = None, job_document: dict | None = None) -> dict:
    job = job_document or _get_dispatch_job(job_id or "")
    return _get_financial_record_for_job(job)


def _create_financial_record(job_document: dict) -> dict:
    timestamp = now_utc()
    request_document = _get_dispatch_request(job_document) or {}
    movement_document = _get_vehicle_movement_for_job(job_document)
    approved_charge = round(float(request_document.get("approved_charge") if request_document.get("approved_charge") is not None else request_document.get("proposed_charge") or 0), 2)
    classification_source = {**job_document, **request_document}
    financial_type, is_legacy = resolve_dispatch_financial_type(classification_source)
    billing_method = normalize_key(classification_source.get("partner_billing_method"))
    immediate_payment = requires_immediate_customer_payment(financial_type, billing_method)
    compensation_type = normalize_key(classification_source.get("driver_compensation_type")) or "none"
    compensation_value = float(classification_source.get("driver_compensation_value") or 0)
    compensation_amount = calculate_driver_compensation(compensation_type, compensation_value, approved_charge)
    recorded_amount_paid = round(float(classification_source.get("amount_paid") or 0), 2)
    expected_fuel_cost = round(float(request_document.get("fuel_estimate_cost") or 0), 2)
    estimated_other_costs = round(float(request_document.get("other_expected_costs") or 0), 2)
    expected_net_revenue = round(
        float(request_document.get("expected_net_revenue"))
        if request_document.get("expected_net_revenue") is not None
        else (approved_charge if recognizes_individual_customer_revenue(financial_type, billing_method) else 0)
        - compensation_amount - expected_fuel_cost - estimated_other_costs,
        2,
    )
    document = {
        "dispatch_job_id": job_document["_id"],
        "dispatch_request_id": job_document.get("dispatch_request_id"),
        "vehicle_movement_id": movement_document.get("_id") if movement_document else None,
        "vehicle_id": job_document.get("vehicle_id"),
        "driver_id": job_document.get("driver_id"),
        "approved_charge": approved_charge,
        "dispatch_financial_type": financial_type,
        "dispatch_financial_type_is_legacy": is_legacy,
        "partner_organization_reference": classification_source.get("partner_organization_reference"),
        "partner_billing_method": billing_method,
        "driver_compensation_type": compensation_type,
        "driver_compensation_value": compensation_value,
        "driver_compensation_amount": compensation_amount,
        "driver_compensation_approved_by": classification_source.get("driver_compensation_approved_by"),
        "driver_compensation_approved_at": classification_source.get("driver_compensation_approved_at"),
        "amount_paid": recorded_amount_paid,
        "amount_collected_from_customer": recorded_amount_paid,
        "amount_submitted_by_driver": 0.0,
        "outstanding_balance": approved_charge if immediate_payment else 0.0,
        "expected_fuel_cost": expected_fuel_cost,
        "actual_fuel_cost": 0.0,
        "estimated_other_costs": estimated_other_costs,
        "approved_expenses": 0.0,
        "company_incident_costs": 0.0,
        "driver_liability_total": 0.0,
        "company_operational_cost": compensation_amount,
        "expected_net_revenue": expected_net_revenue,
        "actual_net_revenue": 0.0,
        "finance_notes": None,
        "payment_method": None,
        "payment_reference": None,
        "submitted_by": None,
        "submitted_at": None,
        "verified_by": None,
        "verified_at": None,
        "financial_status": "pending_collection" if immediate_payment else "fully_submitted",
        "is_financially_closed": False,
        "financial_closed_at": None,
        "financial_closed_by": None,
        "last_submission": {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    try:
        document["_id"] = dispatch_financials_collection().insert_one(document).inserted_id
    except DuplicateKeyError:
        existing = dispatch_financials_collection().find_one({"dispatch_job_id": job_document["_id"]})
        if not existing:
            raise
        return _sync_financial_record(existing, job_document=job_document)
    return _sync_financial_record(document, job_document=job_document)


def _build_driver_money_submission_response(record: dict) -> dict:
    serialized = serialize_dispatch_financial_record(record)
    return {
        "dispatch_financial_id": serialized.get("dispatch_financial_id"),
        "dispatch_job_id": serialized.get("dispatch_job_id"),
        "vehicle_movement_id": serialized.get("vehicle_movement_id"),
        "financial_status": serialized.get("financial_status"),
        "amount_collected": serialized.get("amount_collected_from_customer"),
        "amount_submitted": serialized.get("amount_submitted_by_driver"),
        "outstanding_balance": serialized.get("outstanding_balance"),
        "updated_at": serialized.get("updated_at"),
        "record": serialized,
    }


def _expense_status_included_for_approved_totals(status: str | None) -> bool:
    return status in {"approved", "reimbursed"}


def _incident_company_share(document: dict) -> float:
    status = document.get("status")
    responsibility = document.get("responsibility_type")
    if status in {"rejected", "cancelled"}:
        return 0.0
    if responsibility == "company_responsible":
        return round(float(document.get("amount") or 0), 2)
    if responsibility == "shared_responsibility":
        return round(float(document.get("company_share") or 0), 2)
    return 0.0


def _incident_driver_share(document: dict) -> float:
    status = document.get("status")
    responsibility = document.get("responsibility_type")
    if status in {"rejected", "cancelled"}:
        return 0.0
    if responsibility == "driver_responsible":
        return round(float(document.get("amount") or 0), 2)
    if responsibility == "shared_responsibility":
        return round(float(document.get("driver_share") or 0), 2)
    return 0.0


def _derive_financial_status(document: dict, *, outstanding_balance: float, has_pending_review: bool, immediate_payment: bool = True) -> str:
    if document.get("financial_status") == "cancelled":
        return "cancelled"
    if document.get("financial_status") == "disputed":
        return "disputed"
    if document.get("verified_at"):
        return "verified" if outstanding_balance <= 0 else "outstanding"
    submitted_amount = round(float(document.get("amount_submitted_by_driver") or 0), 2)
    if has_pending_review:
        return "under_review"
    if not immediate_payment:
        return "fully_submitted"
    if outstanding_balance <= 0 and float(document.get("approved_charge") or 0) > 0:
        return "fully_submitted"
    if submitted_amount <= 0:
        return "pending_collection"
    if submitted_amount < round(float(document.get("approved_charge") or 0), 2):
        return "partially_submitted"
    return "fully_submitted"


def _sync_financial_record(document: dict, *, job_document: dict | None = None, persist: bool = True) -> dict:
    job = job_document or _get_dispatch_job(document.get("dispatch_job_id"))
    request_document = _get_dispatch_request(job) or {}
    movement_document = _get_vehicle_movement_for_job(job)
    approved_charge = round(float(request_document.get("approved_charge") if request_document.get("approved_charge") is not None else request_document.get("proposed_charge") or document.get("approved_charge") or 0), 2)
    classification_source = {**job, **request_document, **document}
    financial_type, is_legacy = resolve_dispatch_financial_type(classification_source)
    billing_method = normalize_key(classification_source.get("partner_billing_method"))
    immediate_payment = requires_immediate_customer_payment(financial_type, billing_method)
    recognizes_revenue = recognizes_individual_customer_revenue(financial_type, billing_method)
    compensation_type = normalize_key(classification_source.get("driver_compensation_type")) or "none"
    compensation_value = float(classification_source.get("driver_compensation_value") or 0)
    compensation_amount = calculate_driver_compensation(compensation_type, compensation_value, approved_charge)
    recorded_amount_paid = round(float(classification_source.get("amount_paid") or 0), 2)
    expected_fuel_cost = round(float(request_document.get("fuel_estimate_cost") or document.get("expected_fuel_cost") or 0), 2)
    estimated_other_costs = round(float(request_document.get("other_expected_costs") or document.get("estimated_other_costs") or 0), 2)
    expected_net_revenue = round(
        float(request_document.get("expected_net_revenue"))
        if request_document.get("expected_net_revenue") is not None
        else (approved_charge if recognizes_revenue else 0) - compensation_amount - expected_fuel_cost - estimated_other_costs,
        2,
    )
    expenses = list(dispatch_financial_expenses_collection().find({"dispatch_financial_id": document["_id"]}))
    incidents = list(dispatch_financial_incidents_collection().find({"dispatch_financial_id": document["_id"]}))
    dispatch_fuel_logs = list(
        fuel_logs_collection().find({"dispatch_job_id": job["_id"], "status": "approved"})
    )
    approved_dispatch_fuel_cost = sum(float(item.get("amount") or 0) for item in dispatch_fuel_logs)
    approved_legacy_fuel_expenses = round(
        sum(
            float(item.get("amount") or 0)
            for item in expenses
            if item.get("expense_type") == "fuel"
            and _expense_status_included_for_approved_totals(item.get("status"))
        ),
        2,
    )
    approved_non_fuel_expenses = round(
        sum(
            float(item.get("amount") or 0)
            for item in expenses
            if item.get("expense_type") != "fuel"
            and _expense_status_included_for_approved_totals(item.get("status"))
        ),
        2,
    )
    authoritative_fuel_cost = (
        round(approved_dispatch_fuel_cost, 2)
        if dispatch_fuel_logs
        else approved_legacy_fuel_expenses
    )
    approved_expenses = round(
        approved_non_fuel_expenses + authoritative_fuel_cost,
        2,
    )
    actual_fuel_cost = authoritative_fuel_cost
    company_incident_costs = round(sum(_incident_company_share(item) for item in incidents), 2)
    driver_liability_total = round(sum(_incident_driver_share(item) for item in incidents), 2)
    amount_submitted_by_driver = round(float(document.get("amount_submitted_by_driver") or 0), 2)
    amount_collected_from_customer = round(float(document.get("amount_collected_from_customer") or 0), 2)
    settled_amount = max(recorded_amount_paid, amount_submitted_by_driver)
    outstanding_balance = round(max(approved_charge - settled_amount, 0), 2) if immediate_payment else 0.0
    company_operational_cost = round(compensation_amount + approved_expenses + company_incident_costs, 2)
    recognized_actual_revenue = settled_amount if recognizes_revenue else 0.0
    actual_net_revenue = round(recognized_actual_revenue - company_operational_cost, 2)
    has_pending_review = any(item.get("status") == "pending" for item in expenses) or any(
        item.get("status") in {"reported", "under_review"} for item in incidents
    )
    financial_status = _derive_financial_status(
        document, outstanding_balance=outstanding_balance, has_pending_review=has_pending_review,
        immediate_payment=immediate_payment,
    )
    update_fields = {
        "dispatch_request_id": job.get("dispatch_request_id"),
        "vehicle_movement_id": movement_document.get("_id") if movement_document else document.get("vehicle_movement_id"),
        "vehicle_id": job.get("vehicle_id"),
        "driver_id": job.get("driver_id"),
        "approved_charge": approved_charge,
        "dispatch_financial_type": financial_type,
        "dispatch_financial_type_is_legacy": is_legacy,
        "partner_organization_reference": classification_source.get("partner_organization_reference"),
        "partner_billing_method": billing_method,
        "driver_compensation_type": compensation_type,
        "driver_compensation_value": compensation_value,
        "driver_compensation_amount": compensation_amount,
        "driver_compensation_approved_by": classification_source.get("driver_compensation_approved_by"),
        "driver_compensation_approved_at": classification_source.get("driver_compensation_approved_at"),
        "amount_paid": recorded_amount_paid,
        "expected_fuel_cost": expected_fuel_cost,
        "estimated_other_costs": estimated_other_costs,
        "expected_net_revenue": expected_net_revenue,
        "amount_collected_from_customer": amount_collected_from_customer,
        "amount_submitted_by_driver": amount_submitted_by_driver,
        "outstanding_balance": outstanding_balance,
        "actual_fuel_cost": actual_fuel_cost,
        "approved_expenses": approved_expenses,
        "company_incident_costs": company_incident_costs,
        "driver_liability_total": driver_liability_total,
        "company_operational_cost": company_operational_cost,
        "actual_net_revenue": actual_net_revenue,
        "financial_status": financial_status,
        "updated_at": now_utc(),
    }
    if persist:
        dispatch_financials_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return document


def _assert_admin_role(current_role: str):
    if (_normalize_text(current_role) or "").lower() not in ADMIN_ROLES:
        raise ApiError("You do not have permission to manage dispatch financials.", status_code=403)


def _assert_driver_role(current_role: str):
    if (_normalize_text(current_role) or "").lower() != "driver":
        raise ApiError("You do not have permission to submit driver dispatch financials.", status_code=403)


def _assert_driver_scope(job_document: dict, current_user_id: str):
    if str(job_document.get("driver_id")) != str(current_user_id):
        raise ApiError("Drivers may only manage financials for their assigned dispatches.", status_code=403)


def _assert_financial_stage_ready(job_document: dict):
    if _normalize_text(job_document.get("return_status")) not in FINANCIAL_READY_RETURN_STATUSES:
        raise ApiError("Dispatch financials become available after vehicle return has been confirmed.", status_code=400)


def _vehicle_lookup(records: list[dict]) -> dict[ObjectId, dict]:
    ids = {record.get("vehicle_id") for record in records if isinstance(record.get("vehicle_id"), ObjectId)}
    if not ids:
        return {}
    return {item["_id"]: item for item in vehicles_collection().find({"_id": {"$in": list(ids)}}, VEHICLE_PROJECTION)}


def _user_lookup(records: list[dict]) -> dict[ObjectId, dict]:
    ids = {record.get("driver_id") for record in records if isinstance(record.get("driver_id"), ObjectId)}
    if not ids:
        return {}
    return {item["_id"]: item for item in users_collection().find({"_id": {"$in": list(ids)}}, USER_PROJECTION)}


def _job_lookup(records: list[dict]) -> dict[ObjectId, dict]:
    ids = {record.get("dispatch_job_id") for record in records if isinstance(record.get("dispatch_job_id"), ObjectId)}
    if not ids:
        return {}
    return {item["_id"]: item for item in dispatch_jobs_collection().find({"_id": {"$in": list(ids)}})}


def _movement_lookup(records: list[dict]) -> dict[ObjectId, dict]:
    ids = {record.get("vehicle_movement_id") for record in records if isinstance(record.get("vehicle_movement_id"), ObjectId)}
    if not ids:
        return {}
    return {item["_id"]: item for item in vehicle_movements_collection().find({"_id": {"$in": list(ids)}})}


def _build_list_item(record: dict, *, vehicle_document: dict | None, driver_document: dict | None, job_document: dict | None, movement_document: dict | None) -> dict:
    payload = serialize_dispatch_financial_record(record)
    payload["vehicle"] = serialize_vehicle(vehicle_document, include_sensitive=False) if vehicle_document else None
    payload["driver"] = serialize_user(driver_document) if driver_document else None
    payload["job"] = {
        "id": str(job_document.get("_id")),
        "dispatch_job_id": job_document.get("dispatch_job_id"),
        "status": job_document.get("status"),
        "return_status": job_document.get("return_status"),
        "dispatch_date": job_document.get("dispatch_date"),
        "scheduled_start_time": job_document.get("scheduled_start_time").isoformat() if job_document.get("scheduled_start_time") else None,
    } if job_document else None
    payload["movement"] = {
        "id": str(movement_document.get("_id")),
        "status": movement_document.get("status"),
        "actual_return_time": movement_document.get("actual_return_time").isoformat() if movement_document and movement_document.get("actual_return_time") else None,
    } if movement_document else None
    return payload


def _build_dashboard_summary(records: list[dict], incidents: list[dict]) -> dict:
    external_records = [item for item in records if resolve_dispatch_financial_type(item)[0] == "external_paid"]
    internal_records = [item for item in records if resolve_dispatch_financial_type(item)[0] == "internal_company"]
    partner_records = [item for item in records if resolve_dispatch_financial_type(item)[0] == "partner_contract"]
    complimentary_records = [item for item in records if resolve_dispatch_financial_type(item)[0] == "complimentary"]
    dispatch_revenue = round(sum(float(item.get("amount_submitted_by_driver") or 0) for item in external_records), 2)
    outstanding_dispatch_payments = round(sum(float(item.get("outstanding_balance") or 0) for item in records), 2)
    driver_liabilities = round(sum(float(item.get("driver_liability_total") or 0) for item in records), 2)
    company_operational_costs = round(sum(float(item.get("company_operational_cost") or 0) for item in records), 2)
    dispatch_profitability = round(sum(float(item.get("actual_net_revenue") or 0) for item in records), 2)
    driver_dispatch_compensation = round(sum(float(item.get("driver_compensation_amount") or 0) for item in records), 2)
    incident_trends = {
        "total": len(incidents),
        "under_investigation": len([item for item in incidents if item.get("responsibility_type") == "under_investigation"]),
        "driver_responsible": len([item for item in incidents if item.get("responsibility_type") == "driver_responsible"]),
        "company_responsible": len([item for item in incidents if item.get("responsibility_type") == "company_responsible"]),
        "shared": len([item for item in incidents if item.get("responsibility_type") == "shared_responsibility"]),
    }
    by_vehicle: dict[str, float] = {}
    by_driver: dict[str, float] = {}
    for item in records:
        vehicle_key = str(item.get("vehicle_id") or "")
        driver_key = str(item.get("driver_id") or "")
        by_vehicle[vehicle_key] = round(by_vehicle.get(vehicle_key, 0) + float(item.get("company_operational_cost") or 0), 2)
        by_driver[driver_key] = round(by_driver.get(driver_key, 0) + float(item.get("actual_net_revenue") or 0), 2)
    most_expensive_vehicle_id = max(by_vehicle, key=by_vehicle.get) if by_vehicle else None
    top_driver_id = max(by_driver, key=by_driver.get) if by_driver else None
    return {
        "dispatch_revenue": dispatch_revenue,
        "paid_dispatch_revenue": dispatch_revenue,
        "internal_dispatch_operating_costs": round(sum(float(item.get("company_operational_cost") or 0) for item in internal_records), 2),
        "partner_contract_dispatches": len(partner_records),
        "partner_contract_revenue": round(sum(float(item.get("approved_charge") or 0) for item in partner_records), 2),
        "partner_contract_costs": round(sum(float(item.get("company_operational_cost") or 0) for item in partner_records), 2),
        "complimentary_dispatch_costs": round(sum(float(item.get("company_operational_cost") or 0) for item in complimentary_records), 2),
        "driver_dispatch_compensation": driver_dispatch_compensation,
        "outstanding_dispatch_payments": outstanding_dispatch_payments,
        "driver_liabilities": driver_liabilities,
        "company_operational_costs": company_operational_costs,
        "dispatch_profitability": dispatch_profitability,
        "incident_trends": incident_trends,
        "most_expensive_vehicle_id": most_expensive_vehicle_id,
        "revenue_by_driver_id": top_driver_id,
    }


def list_dispatch_financials(*, current_role: str, page: int = 1, page_size: int = 20, search_query: str | None = None, financial_status: str | None = None) -> dict:
    _assert_admin_role(current_role)
    # Financial records are created by the explicit return/closure workflow.
    # Listing must remain read-only and must not fabricate missing records.
    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 20, 1), 50)
    query: dict = {}
    if financial_status:
        query["financial_status"] = _normalize_status(financial_status, FINANCIAL_STATUSES, "financial_status")
    if search_query:
        matching_jobs = list(
            dispatch_jobs_collection().find(
                {"dispatch_job_id": {"$regex": _normalize_text(search_query), "$options": "i"}},
                {"_id": 1},
            )
        )
        job_ids = [item["_id"] for item in matching_jobs]
        if not job_ids:
            return {
                "records": [],
                "pagination": {"page": normalized_page, "page_size": normalized_page_size, "total": 0, "total_pages": 1},
                "summary": _build_dashboard_summary([], []),
                "filters": {"q": search_query, "financial_status": financial_status},
            }
        query["dispatch_job_id"] = {"$in": job_ids}
    skip = (normalized_page - 1) * normalized_page_size
    list_started_at = perf_counter()
    records = list(
        dispatch_financials_collection().find(query, LIST_PROJECTION).sort([("updated_at", DESCENDING), ("submitted_at", DESCENDING)]).skip(skip).limit(normalized_page_size)
    )
    log_db_duration("dispatch_financials.list", list_started_at)
    # The list endpoint is intentionally read-only. Financial totals are
    # persisted by the submit/approval/closure workflows; recomputing and
    # writing each record here caused slow N+1 reads and write-on-read.
    full_records = records
    financial_collection = dispatch_financials_collection()
    financial_incident_collection = dispatch_financial_incidents_collection()
    vehicle_collection = vehicles_collection()
    user_collection = users_collection()
    job_collection = dispatch_jobs_collection()
    movement_collection = vehicle_movements_collection()
    vehicle_ids = {record.get("vehicle_id") for record in full_records if isinstance(record.get("vehicle_id"), ObjectId)}
    driver_ids = {record.get("driver_id") for record in full_records if isinstance(record.get("driver_id"), ObjectId)}
    job_ids = {record.get("dispatch_job_id") for record in full_records if isinstance(record.get("dispatch_job_id"), ObjectId)}
    movement_ids = {record.get("vehicle_movement_id") for record in full_records if isinstance(record.get("vehicle_movement_id"), ObjectId)}

    def load_summary() -> dict:
        summary_records = list(financial_collection.find(query, LIST_PROJECTION))
        summary_incidents = list(
            financial_incident_collection.find(
                {"dispatch_financial_id": {"$in": [item["_id"] for item in summary_records]}}
            )
        ) if summary_records else []
        return _build_dashboard_summary(summary_records, summary_incidents)

    enrichment_started_at = perf_counter()
    # Atlas round-trip latency dominates this endpoint. These reads are
    # independent, and PyMongo collection handles are thread-safe, so run them
    # in one batch instead of paying for each network trip sequentially.
    with ThreadPoolExecutor(max_workers=6) as executor:
        total_future = executor.submit(financial_collection.count_documents, query)
        vehicle_future = executor.submit(
            lambda: {item["_id"]: item for item in vehicle_collection.find({"_id": {"$in": list(vehicle_ids)}}, VEHICLE_PROJECTION)}
            if vehicle_ids else {}
        )
        user_future = executor.submit(
            lambda: {item["_id"]: item for item in user_collection.find({"_id": {"$in": list(driver_ids)}}, USER_PROJECTION)}
            if driver_ids else {}
        )
        job_future = executor.submit(
            lambda: {item["_id"]: item for item in job_collection.find({"_id": {"$in": list(job_ids)}})}
            if job_ids else {}
        )
        movement_future = executor.submit(
            lambda: {item["_id"]: item for item in movement_collection.find({"_id": {"$in": list(movement_ids)}})}
            if movement_ids else {}
        )
        summary_future = executor.submit(load_summary)
        total = total_future.result()
        vehicle_map = vehicle_future.result()
        user_map = user_future.result()
        job_map = job_future.result()
        movement_map = movement_future.result()
        summary = summary_future.result()
    log_db_duration("dispatch_financials.enrichment_and_summary", enrichment_started_at)

    page_payload = [
        _build_list_item(
            record,
            vehicle_document=vehicle_map.get(record.get("vehicle_id")),
            driver_document=user_map.get(record.get("driver_id")),
            job_document=job_map.get(record.get("dispatch_job_id")),
            movement_document=movement_map.get(record.get("vehicle_movement_id")),
        )
        for record in full_records
    ]
    return {
        "records": page_payload,
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "summary": summary,
        "filters": {"q": search_query, "financial_status": financial_status},
    }


def get_dispatch_financial_detail(job_id: str, *, current_user_id: str | None = None, current_role: str) -> dict:
    job_document = _get_dispatch_job(job_id)
    _assert_financial_stage_ready(job_document)
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role == "driver":
        _assert_driver_scope(job_document, current_user_id or "")
    elif normalized_role not in ADMIN_ROLES:
        raise ApiError("You do not have permission to access dispatch financial details.", status_code=403)
    record = _get_financial_record_for_job(job_document)
    expenses = list(dispatch_financial_expenses_collection().find({"dispatch_financial_id": record["_id"]}).sort([("submitted_at", DESCENDING), ("created_at", DESCENDING)]))
    incidents = list(dispatch_financial_incidents_collection().find({"dispatch_financial_id": record["_id"]}).sort([("submitted_at", DESCENDING), ("created_at", DESCENDING)]))
    linked_incident_ids = [item.get("linked_incident_id") for item in incidents if isinstance(item.get("linked_incident_id"), ObjectId)]
    linked_incident_lookup = {
        item["_id"]: item
        for item in incidents_collection().find({"_id": {"$in": linked_incident_ids}})
    } if linked_incident_ids else {}
    return serialize_dispatch_financial_detail(
        record,
        job_document=job_document,
        movement_document=_get_vehicle_movement_for_job(job_document),
        vehicle_document=vehicles_collection().find_one({"_id": job_document.get("vehicle_id")}) if isinstance(job_document.get("vehicle_id"), ObjectId) else None,
        driver_document=users_collection().find_one({"_id": job_document.get("driver_id")}, USER_PROJECTION) if isinstance(job_document.get("driver_id"), ObjectId) else None,
        linked_incident_documents=linked_incident_lookup,
        expenses=expenses,
        incidents=incidents,
    )


def submit_driver_dispatch_money(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    _assert_driver_role(current_role)
    job_document = _get_dispatch_job(job_id)
    _assert_financial_stage_ready(job_document)
    _assert_driver_scope(job_document, current_user_id)
    record = _get_financial_record_for_job(job_document)
    financial_type, _ = resolve_dispatch_financial_type(record)
    if not requires_immediate_customer_payment(financial_type, record.get("partner_billing_method")):
        raise ApiError("This dispatch classification does not accept an individual customer payment.", status_code=400)
    if record.get("is_financially_closed"):
        raise ApiError("Closed financial records cannot be modified.", status_code=400)
    amount_collected = _normalize_positive_amount((payload or {}).get("amount_collected_from_customer"), "amount_collected_from_customer", required=True)
    amount_submitted = _normalize_positive_amount((payload or {}).get("amount_submitted_by_driver"), "amount_submitted_by_driver", required=True)
    timestamp = now_utc()
    update_fields = {
        "amount_collected_from_customer": amount_collected,
        "amount_submitted_by_driver": amount_submitted,
        "payment_method": _normalize_text((payload or {}).get("payment_method")),
        "payment_reference": _normalize_text((payload or {}).get("payment_reference")),
        "finance_notes": _normalize_text((payload or {}).get("finance_notes")),
        "submitted_by": _to_object_id(current_user_id, "current_user_id"),
        "submitted_at": timestamp,
        "verified_by": None,
        "verified_at": None,
        "last_submission": {
            "amount_collected_from_customer": amount_collected,
            "amount_submitted_by_driver": amount_submitted,
            "payment_method": _normalize_text((payload or {}).get("payment_method")),
            "payment_reference": _normalize_text((payload or {}).get("payment_reference")),
            "finance_notes": _normalize_text((payload or {}).get("finance_notes")),
            "submitted_at": timestamp.isoformat(),
        },
        "updated_at": timestamp,
    }
    dispatch_financials_collection().update_one({"_id": record["_id"]}, {"$set": update_fields})
    record.update(update_fields)
    record = _sync_financial_record(record, job_document=job_document)
    return _build_driver_money_submission_response(record)


def submit_driver_dispatch_expense(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    _assert_driver_role(current_role)
    job_document = _get_dispatch_job(job_id)
    _assert_financial_stage_ready(job_document)
    _assert_driver_scope(job_document, current_user_id)
    record = _get_financial_record_for_job(job_document)
    if record.get("is_financially_closed"):
        raise ApiError("Closed financial records cannot be modified.", status_code=400)
    expense_type = _normalize_status((payload or {}).get("expense_type"), EXPENSE_TYPES, "expense_type")
    amount = _normalize_positive_amount((payload or {}).get("amount"), "amount", required=True)
    note = _normalize_text((payload or {}).get("note"))
    if not note:
        raise ApiError("note is required.", status_code=400)
    timestamp = now_utc()
    expense_document = {
        "dispatch_financial_id": record["_id"],
        "dispatch_job_id": job_document["_id"],
        "vehicle_movement_id": record.get("vehicle_movement_id"),
        "vehicle_id": job_document.get("vehicle_id"),
        "driver_id": job_document.get("driver_id"),
        "expense_type": expense_type,
        "amount": amount,
        "note": note,
        "receipt_reference": _normalize_text((payload or {}).get("receipt_reference")),
        "status": "pending",
        "rejection_reason": None,
        "submitted_by": _to_object_id(current_user_id, "submitted_by"),
        "submitted_at": timestamp,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_financial_expenses_collection().insert_one(expense_document)
    dispatch_financials_collection().update_one(
        {"_id": record["_id"]},
        {"$set": {"verified_by": None, "verified_at": None, "updated_at": timestamp}},
    )
    record["verified_by"] = None
    record["verified_at"] = None
    _sync_financial_record(record, job_document=job_document)
    return get_dispatch_financial_detail(job_id, current_user_id=current_user_id, current_role=current_role)


def _validate_linked_incident_scope(linked_incident_id: str | None, *, job_document: dict) -> ObjectId | None:
    linked_object_id = _to_object_id(linked_incident_id, "linked_incident_id", required=False)
    if linked_object_id is None:
        return None
    incident_document = incidents_collection().find_one({"_id": linked_object_id})
    if not incident_document:
        raise ApiError("Linked incident not found.", status_code=404)
    if incident_document.get("vehicle_id") != job_document.get("vehicle_id") or incident_document.get("driver_id") != job_document.get("driver_id"):
        raise ApiError("Linked incident must belong to the same vehicle and driver.", status_code=400)
    return linked_object_id


def submit_dispatch_financial_incident(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = (_normalize_text(current_role) or "").lower()
    if normalized_role not in {*ADMIN_ROLES, "driver"}:
        raise ApiError("You do not have permission to submit dispatch incidents.", status_code=403)
    job_document = _get_dispatch_job(job_id)
    _assert_financial_stage_ready(job_document)
    if normalized_role == "driver":
        _assert_driver_scope(job_document, current_user_id)
    record = _get_financial_record_for_job(job_document)
    if record.get("is_financially_closed"):
        raise ApiError("Closed financial records cannot be modified.", status_code=400)
    responsibility_type = _normalize_status((payload or {}).get("responsibility_type"), RESPONSIBILITY_TYPES, "responsibility_type", default="under_investigation")
    amount = _normalize_positive_amount((payload or {}).get("amount"), "amount", required=True)
    company_share = _normalize_non_negative_amount((payload or {}).get("company_share"), "company_share", required=False) or 0.0
    driver_share = _normalize_non_negative_amount((payload or {}).get("driver_share"), "driver_share", required=False) or 0.0
    if responsibility_type == "shared_responsibility" and (company_share <= 0 or driver_share <= 0):
        raise ApiError("Shared responsibility requires company_share and driver_share.", status_code=400)
    if responsibility_type == "company_responsible":
        company_share = amount
        driver_share = 0.0
    elif responsibility_type == "driver_responsible":
        company_share = 0.0
        driver_share = amount
    elif responsibility_type == "under_investigation":
        company_share = 0.0
        driver_share = 0.0
    incident_type = _normalize_status((payload or {}).get("incident_type"), FINANCIAL_INCIDENT_TYPES, "incident_type")
    incident_location = _normalize_text((payload or {}).get("incident_location"))
    description = _normalize_text((payload or {}).get("description"))
    if not incident_location:
        raise ApiError("incident_location is required.", status_code=400)
    if not description:
        raise ApiError("description is required.", status_code=400)
    timestamp = now_utc()
    incident_document = {
        "dispatch_financial_id": record["_id"],
        "dispatch_job_id": job_document["_id"],
        "vehicle_movement_id": record.get("vehicle_movement_id"),
        "vehicle_id": job_document.get("vehicle_id"),
        "driver_id": job_document.get("driver_id"),
        "linked_incident_id": _validate_linked_incident_scope((payload or {}).get("linked_incident_id"), job_document=job_document),
        "incident_type": incident_type,
        "incident_date": _parse_date((payload or {}).get("incident_date"), "incident_date", required=True),
        "incident_location": incident_location,
        "amount": amount,
        "responsibility_type": responsibility_type,
        "company_share": company_share,
        "driver_share": driver_share,
        "final_responsible_party": _normalize_text((payload or {}).get("final_responsible_party")),
        "description": description,
        "evidence_reference": _normalize_text((payload or {}).get("evidence_reference")),
        "admin_notes": _normalize_text((payload or {}).get("admin_notes")),
        "status": "reported",
        "rejection_reason": None,
        "submitted_by": _to_object_id(current_user_id, "submitted_by"),
        "submitted_at": timestamp,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_financial_incidents_collection().insert_one(incident_document)
    dispatch_financials_collection().update_one(
        {"_id": record["_id"]},
        {"$set": {"verified_by": None, "verified_at": None, "updated_at": timestamp}},
    )
    record["verified_by"] = None
    record["verified_at"] = None
    _sync_financial_record(record, job_document=job_document)
    return get_dispatch_financial_detail(job_id, current_user_id=current_user_id, current_role=current_role)


def review_dispatch_expense(expense_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    _assert_admin_role(current_role)
    expense = dispatch_financial_expenses_collection().find_one({"_id": _to_object_id(expense_id, "expense_id")})
    if not expense:
        raise ApiError("Dispatch expense not found.", status_code=404)
    record = _get_financial_record_by_id(expense["dispatch_financial_id"])
    if record.get("is_financially_closed"):
        raise ApiError("Closed financial records cannot be modified.", status_code=400)
    status = _normalize_status((payload or {}).get("status"), EXPENSE_STATUSES, "status")
    rejection_reason = _normalize_text((payload or {}).get("rejection_reason"))
    if status == "rejected" and not rejection_reason:
        raise ApiError("Rejected expenses require a reason.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "status": status,
        "rejection_reason": rejection_reason if status == "rejected" else None,
        "reviewed_by": _to_object_id(current_user_id, "reviewed_by"),
        "reviewed_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_financial_expenses_collection().update_one({"_id": expense["_id"]}, {"$set": update_fields})
    record = _sync_financial_record(record)
    return get_dispatch_financial_detail(str(record["dispatch_job_id"]), current_role=current_role)


def review_dispatch_financial_incident(incident_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    _assert_admin_role(current_role)
    incident = dispatch_financial_incidents_collection().find_one({"_id": _to_object_id(incident_id, "incident_id")})
    if not incident:
        raise ApiError("Dispatch incident not found.", status_code=404)
    record = _get_financial_record_by_id(incident["dispatch_financial_id"])
    if record.get("is_financially_closed"):
        raise ApiError("Closed financial records cannot be modified.", status_code=400)
    status = _normalize_status((payload or {}).get("status"), FINANCIAL_INCIDENT_STATUSES, "status")
    responsibility_type = _normalize_status(
        (payload or {}).get("responsibility_type") or incident.get("responsibility_type"),
        RESPONSIBILITY_TYPES,
        "responsibility_type",
    )
    amount = _normalize_positive_amount((payload or {}).get("amount") if "amount" in (payload or {}) else incident.get("amount"), "amount", required=True)
    rejection_reason = _normalize_text((payload or {}).get("rejection_reason"))
    if status == "rejected" and not rejection_reason:
        raise ApiError("Rejected incidents require a reason.", status_code=400)
    company_share = _normalize_non_negative_amount((payload or {}).get("company_share") if "company_share" in (payload or {}) else incident.get("company_share"), "company_share") or 0.0
    driver_share = _normalize_non_negative_amount((payload or {}).get("driver_share") if "driver_share" in (payload or {}) else incident.get("driver_share"), "driver_share") or 0.0
    if responsibility_type == "shared_responsibility" and (company_share <= 0 or driver_share <= 0):
        raise ApiError("Shared responsibility requires company_share and driver_share.", status_code=400)
    if responsibility_type == "company_responsible":
        company_share = amount
        driver_share = 0.0
    elif responsibility_type == "driver_responsible":
        company_share = 0.0
        driver_share = amount
    elif responsibility_type == "under_investigation":
        company_share = 0.0
        driver_share = 0.0
    timestamp = now_utc()
    update_fields = {
        "status": status,
        "amount": amount,
        "responsibility_type": responsibility_type,
        "company_share": company_share,
        "driver_share": driver_share,
        "final_responsible_party": _normalize_text((payload or {}).get("final_responsible_party")) or incident.get("final_responsible_party"),
        "admin_notes": _normalize_text((payload or {}).get("admin_notes")) or incident.get("admin_notes"),
        "evidence_reference": _normalize_text((payload or {}).get("evidence_reference")) or incident.get("evidence_reference"),
        "rejection_reason": rejection_reason if status == "rejected" else None,
        "reviewed_by": _to_object_id(current_user_id, "reviewed_by"),
        "reviewed_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_financial_incidents_collection().update_one({"_id": incident["_id"]}, {"$set": update_fields})
    record = _sync_financial_record(record)
    return get_dispatch_financial_detail(str(record["dispatch_job_id"]), current_role=current_role)


def verify_dispatch_financial(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    _assert_admin_role(current_role)
    job_document = _get_dispatch_job(job_id)
    if job_document.get("return_status") not in {"inspection_completed", "dispatch_closed"}:
        raise ApiError("Financial verification requires completed vehicle return.", status_code=400)
    record = _get_financial_record_for_job(job_document)
    pending_expenses = dispatch_financial_expenses_collection().count_documents(
        {
            "dispatch_financial_id": record["_id"],
            "status": "pending",
        }
    )
    if pending_expenses:
        raise ApiError("Financial verification requires all pending expenses to be reviewed.", status_code=400)
    unresolved_investigation = dispatch_financial_incidents_collection().count_documents(
        {
            "dispatch_financial_id": record["_id"],
            "responsibility_type": "under_investigation",
            "status": {"$in": sorted(ACTIVE_INCIDENT_BLOCKING_STATUSES)},
        }
    )
    if unresolved_investigation:
        raise ApiError("Financial verification requires all incidents under investigation to be resolved.", status_code=400)
    timestamp = now_utc()
    compensation_type = normalize_key((payload or {}).get("driver_compensation_type")) or record.get("driver_compensation_type") or "none"
    compensation_value = (
        (payload or {}).get("driver_compensation_value")
        if "driver_compensation_value" in (payload or {})
        else record.get("driver_compensation_value", 0)
    )
    compensation_amount = calculate_driver_compensation(compensation_type, compensation_value, record.get("approved_charge"))
    update_fields = {
        "finance_notes": _normalize_text((payload or {}).get("finance_notes")) or record.get("finance_notes"),
        "verified_by": _to_object_id(current_user_id, "verified_by"),
        "verified_at": timestamp,
        "driver_compensation_type": compensation_type,
        "driver_compensation_value": float(compensation_value or 0),
        "driver_compensation_amount": compensation_amount,
        "driver_compensation_approved_by": _to_object_id(current_user_id, "driver_compensation_approved_by"),
        "driver_compensation_approved_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_financials_collection().update_one({"_id": record["_id"]}, {"$set": update_fields})
    record.update(update_fields)
    _sync_financial_record(record, job_document=job_document)
    return get_dispatch_financial_detail(job_id, current_role=current_role)


def close_dispatch_financial(job_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    _assert_admin_role(current_role)
    job_document = _get_dispatch_job(job_id)
    record = _get_financial_record_for_job(job_document)
    if record.get("is_financially_closed"):
        return get_dispatch_financial_detail(job_id, current_role=current_role)
    if record.get("verified_at") is None:
        raise ApiError("Financial record cannot be closed until it has been verified.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "finance_notes": _normalize_text((payload or {}).get("finance_notes")) or record.get("finance_notes"),
        "is_financially_closed": True,
        "financial_closed_at": timestamp,
        "financial_closed_by": _to_object_id(current_user_id, "financial_closed_by"),
        "updated_at": timestamp,
    }
    dispatch_financials_collection().update_one({"_id": record["_id"]}, {"$set": update_fields})
    record.update(update_fields)
    return get_dispatch_financial_detail(job_id, current_role=current_role)


def list_driver_dispatch_financials(*, current_user_id: str, current_role: str, page: int = 1, page_size: int = 10, financial_status: str | None = None) -> dict:
    _assert_driver_role(current_role)
    driver_object_id = _to_object_id(current_user_id, "current_user_id")
    # Financial records are provisioned during the explicit return/closure
    # workflow; a driver read must not create or reconcile records.
    query: dict = {"driver_id": driver_object_id}
    if financial_status:
        query["financial_status"] = _normalize_status(financial_status, FINANCIAL_STATUSES, "financial_status")
    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 10, 1), 25)
    skip = (normalized_page - 1) * normalized_page_size
    records = list(dispatch_financials_collection().find(query).sort([("updated_at", DESCENDING)]).skip(skip).limit(normalized_page_size))
    total = dispatch_financials_collection().count_documents(query)
    vehicle_map = _vehicle_lookup(records)
    user_map = _user_lookup(records)
    job_map = _job_lookup(records)
    movement_map = _movement_lookup(records)
    return {
        "records": [
            _build_list_item(
                record,
                vehicle_document=vehicle_map.get(record.get("vehicle_id")),
                driver_document=user_map.get(record.get("driver_id")),
                job_document=job_map.get(record.get("dispatch_job_id")),
                movement_document=movement_map.get(record.get("vehicle_movement_id")),
            )
            for record in records
        ],
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "statuses": sorted(FINANCIAL_STATUSES),
    }


def get_dispatch_financial_reference_options(*, current_role: str) -> dict:
    _assert_admin_role(current_role)
    return {
        "financial_statuses": sorted(FINANCIAL_STATUSES),
        "dispatch_financial_types": sorted(DISPATCH_FINANCIAL_TYPES),
        "partner_billing_methods": sorted(PARTNER_BILLING_METHODS),
        "driver_compensation_types": sorted(DRIVER_COMPENSATION_TYPES),
        "expense_types": sorted(EXPENSE_TYPES),
        "expense_statuses": sorted(EXPENSE_STATUSES),
        "incident_types": sorted(FINANCIAL_INCIDENT_TYPES),
        "responsibility_types": sorted(RESPONSIBILITY_TYPES),
        "incident_statuses": sorted(FINANCIAL_INCIDENT_STATUSES),
    }
