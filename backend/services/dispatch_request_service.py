from __future__ import annotations

from datetime import date, datetime, timezone
from math import ceil
from time import perf_counter
import re
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.dispatch_request import serialize_dispatch_request
from models.user import serialize_user
from services.master_data_service import assert_master_data_value, get_active_master_data_items
from services.notification_service import create_notification, notify_roles, resolve_action_notifications
from utils.api_error import ApiError
from utils.dispatch_payment_classification import (
    DISPATCH_FINANCIAL_TYPES,
    DRIVER_COMPENSATION_TYPES,
    PARTNER_BILLING_METHODS,
    calculate_driver_compensation,
    normalize_key,
    payment_status_is_recorded,
    recognizes_individual_customer_revenue,
    requires_immediate_customer_payment,
    resolve_dispatch_financial_type,
)
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached


ALLOWED_DISPATCH_REQUEST_STATUSES = {
    "new",
    "reviewing",
    "pricing_pending",
    "approved",
    "rejected",
    "converted",
    "cancelled",
}
EDITABLE_UNAPPROVED_STATUSES = {"new", "reviewing", "pricing_pending"}
BACKOFFICE_VIEW_ROLES = {"owner", "admin", "dispatcher", "customer_service"}
OWNER_ADMIN_ROLES = {"owner", "admin"}
ALLOWED_PRICING_STATUSES = {
    "pricing_pending",
    "pricing_approved",
    "pricing_rejected",
    "pricing_revised",
}
ALLOWED_SCHEDULE_TYPES = {"immediate", "scheduled", "recurring"}
ALLOWED_STOP_TYPES = {"pickup", "dropoff", "checkpoint"}
ALLOWED_STOP_STATUSES = {"pending", "ready", "completed", "skipped", "cancelled"}
ALLOWED_STOP_DELIVERY_STATUSES = {"pending", "delivered"}
ALLOWED_RECURRENCE_PATTERNS = {"daily", "weekdays", "weekly", "monthly", "custom"}
DELIVERY_CONFIRMABLE_MOVEMENT_STATUSES = {"checked_out", "in_progress"}
MASTER_DATA_GROUPS = {
    "request_type": "dispatch_request_types",
    "pickup_location": "dispatch_pickup_locations",
    "vehicle_type_needed": "dispatch_vehicle_types",
    "load_type": "dispatch_load_types",
    "load_weight_category": "dispatch_load_weight_categories",
    "load_size_category": "dispatch_load_size_categories",
    "urgency": "dispatch_urgencies",
    "payment_status": "dispatch_payment_statuses",
}
LIST_PROJECTION = {
    "request_id": 1,
    "source_dispatch_opportunity_id": 1,
    "source_dispatch_opportunity_record_id": 1,
    "submitted_by_driver_id": 1,
    "request_type": 1,
    "customer_name": 1,
    "customer_phone": 1,
    "customer_company": 1,
    "pickup_location": 1,
    "destination": 1,
    "vehicle_type_needed": 1,
    "load_type": 1,
    "load_weight_category": 1,
    "load_size_category": 1,
    "preferred_pickup_date": 1,
    "preferred_pickup_time": 1,
    "urgency": 1,
    "proposed_charge": 1,
    "approved_charge": 1,
    "pricing_status": 1,
    "distance_estimate_km": 1,
    "fuel_estimate_amount": 1,
    "fuel_estimate_cost": 1,
    "other_expected_costs": 1,
    "expected_net_revenue": 1,
    "payment_status": 1,
    "dispatch_financial_type": 1,
    "partner_organization_reference": 1,
    "partner_billing_method": 1,
    "payment_method": 1,
    "amount_paid": 1,
    "outstanding_balance": 1,
    "driver_compensation_type": 1,
    "driver_compensation_value": 1,
    "driver_compensation_amount": 1,
    "financial_type_changed_by": 1,
    "financial_type_changed_at": 1,
    "driver_compensation_approved_by": 1,
    "driver_compensation_approved_at": 1,
    "status": 1,
    "planning_status": 1,
    "active_dispatch_job_id": 1,
    "schedule_type": 1,
    "scheduled_start_time": 1,
    "scheduled_end_time": 1,
    "expected_return_time": 1,
    "recurrence_pattern": 1,
    "recurrence_end_date": 1,
    "stops_count": 1,
    "created_by": 1,
    "created_at": 1,
    "updated_at": 1,
}
DETAIL_PROJECTION = {
    **LIST_PROJECTION,
    "load_description": 1,
    "expected_delivery_time": 1,
    "notes": 1,
    "pricing_notes": 1,
    "reviewed_by": 1,
    "approved_by": 1,
    "rejected_by": 1,
    "cancelled_by": 1,
    "pricing_reviewed_by": 1,
    "reviewed_at": 1,
    "approved_at": 1,
    "rejected_at": 1,
    "cancelled_at": 1,
    "pricing_reviewed_at": 1,
    "schedule_notes": 1,
    "stops": 1,
    "pricing_history": 1,
    "rejection_reason": 1,
    "cancellation_reason": 1,
}
USER_SUMMARY_PROJECTION = {"full_name": 1, "email": 1, "phone": 1, "role": 1, "status": 1}
EDITOR_PATCHABLE_FIELDS = {
    "request_type",
    "customer_name",
    "customer_phone",
    "customer_company",
    "pickup_location",
    "destination",
    "vehicle_type_needed",
    "load_type",
    "load_weight_category",
    "load_size_category",
    "load_description",
    "preferred_pickup_date",
    "preferred_pickup_time",
    "expected_delivery_time",
    "urgency",
    "proposed_charge",
    "payment_status",
    "dispatch_financial_type",
    "partner_organization_reference",
    "partner_billing_method",
    "payment_method",
    "amount_paid",
    "driver_compensation_type",
    "driver_compensation_value",
    "notes",
    "status",
}
ADMIN_ONLY_PATCHABLE_FIELDS = {"approved_charge"}


def now_utc():
    return datetime.now(timezone.utc)


def dispatch_requests_collection():
    return get_collection("dispatch_requests")


def users_collection():
    return get_collection("users")


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def dispatch_jobs_collection():
    return get_collection("dispatch_jobs")


def ensure_dispatch_request_indexes():
    ensure_indexes_for_collection(
        dispatch_requests_collection(),
        [
            {"keys": [("request_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("source_dispatch_opportunity_record_id", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("submitted_by_driver_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("customer_phone", ASCENDING)]},
            {"keys": [("customer_name", ASCENDING)]},
            {"keys": [("vehicle_type_needed", ASCENDING)]},
            {"keys": [("preferred_pickup_date", DESCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_type_needed", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("customer_phone", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("preferred_pickup_date", DESCENDING), ("created_at", DESCENDING)]},
            {"keys": [("pricing_status", ASCENDING)]},
            {"keys": [("schedule_type", ASCENDING)]},
            {"keys": [("scheduled_start_time", ASCENDING)]},
            {"keys": [("scheduled_end_time", ASCENDING)]},
            {"keys": [("expected_return_time", ASCENDING)]},
            {"keys": [("recurrence_end_date", ASCENDING)]},
            {"keys": [("pricing_status", ASCENDING), ("scheduled_start_time", ASCENDING)]},
            {"keys": [("schedule_type", ASCENDING), ("scheduled_start_time", ASCENDING)]},
            {"keys": [("status", ASCENDING), ("scheduled_start_time", ASCENDING)]},
        ],
        collection_name="dispatch_requests",
    )


def _normalize_role(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _normalize_text(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_phone(value):
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return re.sub(r"\s+", "", normalized)


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


def _parse_datetime(value, field_name: str, *, required: bool = False) -> datetime | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError as error:
        raise ApiError(f"{field_name} must be a valid ISO datetime.", status_code=400) from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_date(value, field_name: str, *, required: bool = False) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as error:
        raise ApiError(f"{field_name} must be a valid ISO date.", status_code=400) from error


def _parse_time(value, field_name: str, *, required: bool = False) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    candidate = normalized[:5]
    if not re.fullmatch(r"\d{2}:\d{2}", candidate):
        raise ApiError(f"{field_name} must be a valid HH:MM time.", status_code=400)
    return candidate


def _validate_non_negative_number(value, field_name: str):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} must be zero or greater.", status_code=400)
    return round(float(value), 2)


def _validate_enum(value, field_name: str, allowed: set[str], *, required: bool = False, default: str | None = None):
    normalized = _normalize_text(value)
    if not normalized:
        if default is not None:
            return default
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    normalized = normalized.lower()
    if normalized not in allowed:
        raise ApiError(f"Invalid {field_name}.", status_code=400)
    return normalized


def _validate_master_data_value(
    value,
    field_name: str,
    *,
    required: bool = False,
    default: str | None = None,
):
    normalized = _normalize_text(value)
    if not normalized:
        if default is not None:
            normalized = default
        elif required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        else:
            return None
    return assert_master_data_value(MASTER_DATA_GROUPS[field_name], normalized)


def _parse_positive_integer(value, field_name: str, *, required: bool = False) -> int | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool):
        raise ApiError(f"{field_name} must be a whole number.", status_code=400)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ApiError(f"{field_name} must be a whole number.", status_code=400) from error
    if parsed <= 0:
        raise ApiError(f"{field_name} must be greater than zero.", status_code=400)
    return parsed


def _compute_expected_net_revenue(
    *, approved_charge, proposed_charge, fuel_estimate_cost, other_expected_costs,
    dispatch_financial_type="external_paid", partner_billing_method=None, driver_compensation_amount=0,
):
    base_charge = approved_charge if approved_charge is not None else proposed_charge
    if base_charge is None:
        return None
    recognized_charge = float(base_charge) if recognizes_individual_customer_revenue(
        dispatch_financial_type, partner_billing_method
    ) else 0.0
    return round(
        recognized_charge
        - float(driver_compensation_amount or 0)
        - float(fuel_estimate_cost or 0)
        - float(other_expected_costs or 0),
        2,
    )


def _validate_financial_classification(document: dict, *, require_explicit: bool = False) -> dict:
    financial_type, is_legacy = resolve_dispatch_financial_type(document)
    if require_explicit and is_legacy:
        raise ApiError("dispatch_financial_type is required.", status_code=400)
    billing_method = normalize_key(document.get("partner_billing_method"))
    partner_reference = _normalize_text(document.get("partner_organization_reference"))
    charge = document.get("approved_charge")
    if charge is None:
        charge = document.get("proposed_charge")
    charge = float(charge or 0)
    amount_paid = float(document.get("amount_paid") or 0)
    payment_method = _normalize_text(document.get("payment_method"))

    if financial_type == "partner_contract":
        if not partner_reference:
            raise ApiError("partner_organization_reference is required for partner contract dispatches.", status_code=400)
        if billing_method not in PARTNER_BILLING_METHODS:
            raise ApiError("A valid partner_billing_method is required for partner contract dispatches.", status_code=400)
    elif billing_method or partner_reference:
        raise ApiError("Partner billing fields are only valid for partner contract dispatches.", status_code=400)

    immediate_payment = requires_immediate_customer_payment(financial_type, billing_method)
    if financial_type in {"internal_company", "complimentary"}:
        if charge != 0 or amount_paid != 0 or payment_method:
            raise ApiError(f"{financial_type} dispatches cannot record a customer charge or payment.", status_code=400)
    elif immediate_payment and charge <= 0:
        raise ApiError("A customer charge greater than zero is required for this dispatch classification.", status_code=400)
    if amount_paid < 0 or amount_paid > charge:
        raise ApiError("amount_paid must be between zero and the customer charge.", status_code=400)
    if (amount_paid > 0 or payment_status_is_recorded(document.get("payment_status"))) and immediate_payment and not payment_method:
        raise ApiError("payment_method is required when a customer payment is recorded.", status_code=400)

    compensation_type = normalize_key(document.get("driver_compensation_type")) or "none"
    if compensation_type not in DRIVER_COMPENSATION_TYPES:
        raise ApiError("Invalid driver_compensation_type.", status_code=400)
    compensation_value = float(document.get("driver_compensation_value") or 0)
    compensation_amount = calculate_driver_compensation(compensation_type, compensation_value, charge)
    outstanding = round(max(charge - amount_paid, 0), 2) if immediate_payment else 0.0
    return {
        "dispatch_financial_type": financial_type,
        "partner_organization_reference": partner_reference if financial_type == "partner_contract" else None,
        "partner_billing_method": billing_method if financial_type == "partner_contract" else None,
        "payment_method": payment_method if immediate_payment else None,
        "amount_paid": round(amount_paid, 2) if immediate_payment else 0.0,
        "outstanding_balance": outstanding,
        "payment_status": document.get("payment_status") if immediate_payment else "Not Required",
        "driver_compensation_type": compensation_type,
        "driver_compensation_value": round(compensation_value, 2),
        "driver_compensation_amount": compensation_amount,
    }


def _assert_view_role(current_role: str):
    if current_role not in BACKOFFICE_VIEW_ROLES:
        raise ApiError("You do not have permission to access dispatch requests.", status_code=403)


def _assert_edit_role(current_role: str):
    if current_role not in BACKOFFICE_VIEW_ROLES:
        raise ApiError("You do not have permission to update dispatch requests.", status_code=403)


def _assert_admin_role(current_role: str):
    if current_role not in OWNER_ADMIN_ROLES:
        raise ApiError("You do not have permission to perform this dispatch request action.", status_code=403)


def _get_dispatch_request_document(request_id: str, *, projection: dict | None = None) -> dict:
    if not ObjectId.is_valid(request_id):
        raise ApiError("Dispatch request not found.", status_code=404)
    document = dispatch_requests_collection().find_one({"_id": ObjectId(request_id)}, projection)
    if not document:
        raise ApiError("Dispatch request not found.", status_code=404)
    return document


def _build_user_lookup(documents: list[dict]) -> dict[ObjectId, dict]:
    user_ids = {
        value
        for document in documents
        for value in (
            document.get("submitted_by_driver_id"),
            document.get("created_by"),
            document.get("reviewed_by"),
            document.get("approved_by"),
            document.get("rejected_by"),
            document.get("cancelled_by"),
            document.get("pricing_reviewed_by"),
        )
        if isinstance(value, ObjectId)
    }
    if not user_ids:
        return {}
    return {
        item["_id"]: item
        for item in users_collection().find({"_id": {"$in": list(user_ids)}}, USER_SUMMARY_PROJECTION)
    }


def _enrich_dispatch_request(document: dict, *, user_lookup: dict[ObjectId, dict] | None = None) -> dict:
    payload = serialize_dispatch_request(document)
    lookup = user_lookup or {}
    payload["submitted_by_driver_user"] = serialize_user(lookup[document["submitted_by_driver_id"]]) if lookup.get(document.get("submitted_by_driver_id")) else None
    payload["created_by_user"] = serialize_user(lookup[document["created_by"]]) if lookup.get(document.get("created_by")) else None
    payload["reviewed_by_user"] = serialize_user(lookup[document["reviewed_by"]]) if lookup.get(document.get("reviewed_by")) else None
    payload["approved_by_user"] = serialize_user(lookup[document["approved_by"]]) if lookup.get(document.get("approved_by")) else None
    payload["rejected_by_user"] = serialize_user(lookup[document["rejected_by"]]) if lookup.get(document.get("rejected_by")) else None
    payload["cancelled_by_user"] = serialize_user(lookup[document["cancelled_by"]]) if lookup.get(document.get("cancelled_by")) else None
    payload["pricing_reviewed_by_user"] = serialize_user(lookup[document["pricing_reviewed_by"]]) if lookup.get(document.get("pricing_reviewed_by")) else None
    return payload


def _batch_enrich_dispatch_requests(documents: list[dict]) -> list[dict]:
    if not documents:
        return []
    user_lookup = _build_user_lookup(documents)
    return [_enrich_dispatch_request(document, user_lookup=user_lookup) for document in documents]


def _generate_request_id() -> str:
    timestamp = now_utc().strftime("%Y%m%d%H%M%S")
    return f"DR-{timestamp}-{uuid4().hex[:6].upper()}"


def _resolve_default_dispatch_request_type() -> str:
    request_types = get_active_master_data_items("dispatch_request_types")
    if not request_types:
        raise ApiError("No active dispatch request types are configured.", status_code=400)
    for item in request_types:
        name = _normalize_text(item.get("name"))
        if name and name.lower() == "delivery":
            return name
    fallback = _normalize_text(request_types[0].get("name"))
    if not fallback:
        raise ApiError("No valid dispatch request types are configured.", status_code=400)
    return fallback


def _normalize_dispatch_request_payload(payload: dict, *, partial: bool = False, current_role: str | None = None) -> dict:
    normalized: dict = {}
    if "request_type" in payload or not partial:
        normalized["request_type"] = _validate_master_data_value(
            payload.get("request_type"),
            "request_type",
            required=not partial,
            default="Delivery" if not partial else None,
        )
    if "customer_name" in payload or not partial:
        normalized["customer_name"] = _normalize_text(payload.get("customer_name"))
        if not normalized["customer_name"]:
            raise ApiError("customer_name is required.", status_code=400)
    if "customer_phone" in payload or not partial:
        normalized["customer_phone"] = _normalize_phone(payload.get("customer_phone"))
        if not normalized["customer_phone"]:
            raise ApiError("customer_phone is required.", status_code=400)
    if "customer_company" in payload or not partial:
        normalized["customer_company"] = _normalize_text(payload.get("customer_company"))
    if "pickup_location" in payload or not partial:
        normalized["pickup_location"] = _validate_master_data_value(
            payload.get("pickup_location"),
            "pickup_location",
            required=not partial,
        )
        if not normalized["pickup_location"]:
            raise ApiError("pickup_location is required.", status_code=400)
    if "destination" in payload or not partial:
        normalized["destination"] = _normalize_text(payload.get("destination"))
        if not normalized["destination"]:
            raise ApiError("destination is required.", status_code=400)
    if "vehicle_type_needed" in payload or not partial:
        normalized["vehicle_type_needed"] = _validate_master_data_value(
            payload.get("vehicle_type_needed"),
            "vehicle_type_needed",
            required=not partial,
        )
    if "load_type" in payload or not partial:
        normalized["load_type"] = _validate_master_data_value(
            payload.get("load_type"),
            "load_type",
            required=False,
            default="Other" if not partial else None,
        )
    if "load_weight_category" in payload or not partial:
        normalized["load_weight_category"] = _validate_master_data_value(
            payload.get("load_weight_category"),
            "load_weight_category",
            required=False,
        )
    if "load_size_category" in payload or not partial:
        normalized["load_size_category"] = _validate_master_data_value(
            payload.get("load_size_category"),
            "load_size_category",
            required=False,
        )
    if "load_description" in payload or not partial:
        normalized["load_description"] = _normalize_text(payload.get("load_description"))
    if "preferred_pickup_date" in payload or not partial:
        normalized["preferred_pickup_date"] = _parse_date(
            payload.get("preferred_pickup_date"),
            "preferred_pickup_date",
            required=not partial,
        )
    if "preferred_pickup_time" in payload or not partial:
        normalized["preferred_pickup_time"] = _parse_time(
            payload.get("preferred_pickup_time"),
            "preferred_pickup_time",
            required=not partial,
        )
    if "expected_delivery_time" in payload or not partial:
        normalized["expected_delivery_time"] = _parse_datetime(
            payload.get("expected_delivery_time"),
            "expected_delivery_time",
            required=False,
        )
    if "urgency" in payload or not partial:
        normalized["urgency"] = _validate_master_data_value(
            payload.get("urgency"),
            "urgency",
            required=False,
            default="Normal" if not partial else None,
        )
    if "proposed_charge" in payload or not partial:
        normalized["proposed_charge"] = _validate_non_negative_number(payload.get("proposed_charge"), "proposed_charge")
        if normalized["proposed_charge"] is None and not partial:
            normalized["proposed_charge"] = 0.0
    if "approved_charge" in payload:
        if current_role not in OWNER_ADMIN_ROLES:
            raise ApiError("approved_charge can only be set by owner or admin.", status_code=403)
        normalized["approved_charge"] = _validate_non_negative_number(payload.get("approved_charge"), "approved_charge")
    elif not partial:
        normalized["approved_charge"] = None
    if "payment_status" in payload or not partial:
        normalized["payment_status"] = _validate_master_data_value(
            payload.get("payment_status"),
            "payment_status",
            required=False,
            default="Unpaid" if not partial else None,
        )
    if "dispatch_financial_type" in payload or not partial:
        financial_type = normalize_key(payload.get("dispatch_financial_type"))
        if financial_type not in DISPATCH_FINANCIAL_TYPES:
            raise ApiError("A valid dispatch_financial_type is required.", status_code=400)
        normalized["dispatch_financial_type"] = financial_type
    for field_name in ("partner_organization_reference", "payment_method"):
        if field_name in payload or not partial:
            normalized[field_name] = _normalize_text(payload.get(field_name))
    if "partner_billing_method" in payload or not partial:
        normalized["partner_billing_method"] = normalize_key(payload.get("partner_billing_method"))
    if "amount_paid" in payload or not partial:
        normalized["amount_paid"] = _validate_non_negative_number(payload.get("amount_paid"), "amount_paid") or 0.0
    if "driver_compensation_type" in payload or not partial:
        compensation_type = normalize_key(payload.get("driver_compensation_type")) or "none"
        if compensation_type not in DRIVER_COMPENSATION_TYPES:
            raise ApiError("Invalid driver_compensation_type.", status_code=400)
        normalized["driver_compensation_type"] = compensation_type
    if "driver_compensation_value" in payload or not partial:
        normalized["driver_compensation_value"] = (
            _validate_non_negative_number(payload.get("driver_compensation_value"), "driver_compensation_value") or 0.0
        )
    if "notes" in payload or not partial:
        normalized["notes"] = _normalize_text(payload.get("notes"))
    if "status" in payload:
        normalized["status"] = _validate_enum(
            payload.get("status"),
            "status",
            ALLOWED_DISPATCH_REQUEST_STATUSES,
            required=True,
        )
    elif not partial:
        normalized["status"] = "new"
    if not partial:
        normalized["pricing_status"] = "pricing_pending"
        normalized["pricing_notes"] = None
        normalized["distance_estimate_km"] = None
        normalized["fuel_estimate_amount"] = None
        normalized["fuel_estimate_cost"] = None
        normalized["other_expected_costs"] = None
        normalized.update(_validate_financial_classification(normalized, require_explicit=True))
        normalized["expected_net_revenue"] = _compute_expected_net_revenue(
            approved_charge=None,
            proposed_charge=normalized.get("proposed_charge"),
            fuel_estimate_cost=None,
            other_expected_costs=None,
            dispatch_financial_type=normalized.get("dispatch_financial_type"),
            partner_billing_method=normalized.get("partner_billing_method"),
            driver_compensation_amount=normalized.get("driver_compensation_amount"),
        )
        normalized["scheduled_start_time"] = None
        normalized["scheduled_end_time"] = None
        normalized["expected_return_time"] = None
        normalized["schedule_type"] = "immediate"
        normalized["recurrence_pattern"] = None
        normalized["recurrence_end_date"] = None
        normalized["schedule_notes"] = None
        normalized["stops"] = []
        normalized["stops_count"] = 0
        normalized["pricing_history"] = []
    return normalized


def _validate_request_timing(document: dict):
    pickup_date = document.get("preferred_pickup_date")
    pickup_time = document.get("preferred_pickup_time")
    if not pickup_date or not pickup_time:
        raise ApiError("preferred_pickup_date and preferred_pickup_time are required.", status_code=400)
    expected_delivery_time = document.get("expected_delivery_time")
    if expected_delivery_time is None:
        return
    pickup_datetime = _parse_datetime(f"{pickup_date}T{pickup_time}:00", "preferred_pickup_datetime", required=True)
    if expected_delivery_time <= pickup_datetime:
        raise ApiError("expected_delivery_time must be after the preferred pickup time.", status_code=400)


def _validate_edit_status(document: dict, *, current_role: str):
    current_status = document.get("status")
    if current_status == "converted" and current_role not in OWNER_ADMIN_ROLES:
        raise ApiError("Converted dispatch requests can only be edited by owner or admin.", status_code=403)
    if current_role in OWNER_ADMIN_ROLES:
        return
    if current_status not in EDITABLE_UNAPPROVED_STATUSES:
        raise ApiError("Only unapproved dispatch requests can be edited from this role.", status_code=403)


def _validate_planning_status(document: dict, *, current_role: str):
    current_status = document.get("status")
    if current_status == "converted" and current_role not in OWNER_ADMIN_ROLES:
        raise ApiError("Converted dispatch requests can only be updated by owner or admin.", status_code=403)
    if current_role in OWNER_ADMIN_ROLES:
        return
    if current_status not in EDITABLE_UNAPPROVED_STATUSES | {"approved"}:
        raise ApiError("This dispatch request cannot be updated from this role right now.", status_code=403)


def _build_pricing_history_entry(*, action: str, actor_id: str, payload: dict) -> dict:
    return {
        "id": uuid4().hex,
        "action": action,
        "actor_id": actor_id,
        "acted_at": now_utc(),
        "pricing_status": payload.get("pricing_status"),
        "proposed_charge": payload.get("proposed_charge"),
        "approved_charge": payload.get("approved_charge"),
        "distance_estimate_km": payload.get("distance_estimate_km"),
        "fuel_estimate_amount": payload.get("fuel_estimate_amount"),
        "fuel_estimate_cost": payload.get("fuel_estimate_cost"),
        "other_expected_costs": payload.get("other_expected_costs"),
        "expected_net_revenue": payload.get("expected_net_revenue"),
        "pricing_notes": payload.get("pricing_notes"),
    }


def _normalize_pricing_payload(payload: dict, *, current_role: str) -> dict:
    normalized: dict = {}
    if "proposed_charge" in payload:
        normalized["proposed_charge"] = _validate_non_negative_number(payload.get("proposed_charge"), "proposed_charge")
    if "approved_charge" in payload:
        if current_role not in OWNER_ADMIN_ROLES:
            raise ApiError("approved_charge can only be set by owner or admin.", status_code=403)
        normalized["approved_charge"] = _validate_non_negative_number(payload.get("approved_charge"), "approved_charge")
    if "pricing_notes" in payload:
        normalized["pricing_notes"] = _normalize_text(payload.get("pricing_notes"))
    if "distance_estimate_km" in payload:
        normalized["distance_estimate_km"] = _validate_non_negative_number(
            payload.get("distance_estimate_km"),
            "distance_estimate_km",
        )
    if "fuel_estimate_amount" in payload:
        normalized["fuel_estimate_amount"] = _validate_non_negative_number(
            payload.get("fuel_estimate_amount"),
            "fuel_estimate_amount",
        )
    if "fuel_estimate_cost" in payload:
        normalized["fuel_estimate_cost"] = _validate_non_negative_number(
            payload.get("fuel_estimate_cost"),
            "fuel_estimate_cost",
        )
    if "other_expected_costs" in payload:
        normalized["other_expected_costs"] = _validate_non_negative_number(
            payload.get("other_expected_costs"),
            "other_expected_costs",
        )
    return normalized


def _validate_pricing_state(document: dict, update_fields: dict, *, action: str):
    merged = {**document, **update_fields}
    base_charge = merged.get("approved_charge") if merged.get("approved_charge") is not None else merged.get("proposed_charge")
    if action == "approve" and base_charge is None:
        raise ApiError("Pricing cannot be approved without proposed or approved charge.", status_code=400)
    if action == "reject" and not _normalize_text(merged.get("pricing_notes")):
        raise ApiError("pricing_notes is required when rejecting pricing.", status_code=400)
    classification = _validate_financial_classification(merged)
    merged.update(classification)
    merged["expected_net_revenue"] = _compute_expected_net_revenue(
        approved_charge=merged.get("approved_charge"),
        proposed_charge=merged.get("proposed_charge"),
        fuel_estimate_cost=merged.get("fuel_estimate_cost"),
        other_expected_costs=merged.get("other_expected_costs"),
        dispatch_financial_type=classification["dispatch_financial_type"],
        partner_billing_method=classification["partner_billing_method"],
        driver_compensation_amount=classification["driver_compensation_amount"],
    )
    return merged


def _normalize_schedule_payload(payload: dict) -> dict:
    normalized: dict = {}
    if "schedule_type" in payload:
        normalized["schedule_type"] = _validate_enum(
            payload.get("schedule_type"),
            "schedule_type",
            ALLOWED_SCHEDULE_TYPES,
            required=True,
        )
    if "scheduled_start_time" in payload:
        normalized["scheduled_start_time"] = _parse_datetime(
            payload.get("scheduled_start_time"),
            "scheduled_start_time",
            required=False,
        )
    if "scheduled_end_time" in payload:
        normalized["scheduled_end_time"] = _parse_datetime(
            payload.get("scheduled_end_time"),
            "scheduled_end_time",
            required=False,
        )
    if "expected_return_time" in payload:
        normalized["expected_return_time"] = _parse_datetime(
            payload.get("expected_return_time"),
            "expected_return_time",
            required=False,
        )
    if "recurrence_pattern" in payload:
        normalized["recurrence_pattern"] = _validate_enum(
            payload.get("recurrence_pattern"),
            "recurrence_pattern",
            ALLOWED_RECURRENCE_PATTERNS,
            required=False,
        )
    if "recurrence_end_date" in payload:
        normalized["recurrence_end_date"] = _parse_date(
            payload.get("recurrence_end_date"),
            "recurrence_end_date",
            required=False,
        )
    if "schedule_notes" in payload:
        normalized["schedule_notes"] = _normalize_text(payload.get("schedule_notes"))
    return normalized


def _validate_schedule_state(document: dict, update_fields: dict):
    merged = {**document, **update_fields}
    schedule_type = merged.get("schedule_type") or "immediate"
    scheduled_start_time = merged.get("scheduled_start_time")
    scheduled_end_time = merged.get("scheduled_end_time")
    expected_return_time = merged.get("expected_return_time")
    recurrence_pattern = merged.get("recurrence_pattern")
    recurrence_end_date = merged.get("recurrence_end_date")

    if schedule_type in {"scheduled", "recurring"} and scheduled_start_time is None:
        raise ApiError("scheduled_start_time is required for scheduled or recurring dispatch.", status_code=400)
    if scheduled_end_time is not None and scheduled_start_time is not None and scheduled_end_time <= scheduled_start_time:
        raise ApiError("scheduled_end_time must be after scheduled_start_time.", status_code=400)
    if expected_return_time is not None and scheduled_start_time is not None and expected_return_time <= scheduled_start_time:
        raise ApiError("expected_return_time must be after scheduled_start_time.", status_code=400)
    if schedule_type == "recurring" and not recurrence_pattern:
        raise ApiError("recurrence_pattern is required for recurring dispatch.", status_code=400)
    if recurrence_end_date and scheduled_start_time:
        if date.fromisoformat(recurrence_end_date) <= scheduled_start_time.date():
            raise ApiError("recurrence_end_date must be after scheduled_start_time.", status_code=400)
    if schedule_type != "recurring":
        merged["recurrence_pattern"] = None
        merged["recurrence_end_date"] = None
    return merged


def _normalize_stop_payload(payload: dict, *, existing_stop: dict | None = None) -> dict:
    normalized = dict(existing_stop or {})
    if "stop_sequence" in payload or existing_stop is None:
        normalized["stop_sequence"] = _parse_positive_integer(
            payload.get("stop_sequence"),
            "stop_sequence",
            required=existing_stop is None,
        )
    if "stop_type" in payload or existing_stop is None:
        normalized["stop_type"] = _validate_enum(
            payload.get("stop_type"),
            "stop_type",
            ALLOWED_STOP_TYPES,
            required=existing_stop is None,
        )
    if "location" in payload or existing_stop is None:
        normalized["location"] = _normalize_text(payload.get("location"))
        if not normalized.get("location"):
            raise ApiError("location is required.", status_code=400)
    if "contact_name" in payload or existing_stop is None:
        normalized["contact_name"] = _normalize_text(payload.get("contact_name"))
    if "contact_phone" in payload or existing_stop is None:
        normalized["contact_phone"] = _normalize_phone(payload.get("contact_phone"))
    if "load_note" in payload or existing_stop is None:
        normalized["load_note"] = _normalize_text(payload.get("load_note"))
    if "planned_arrival_time" in payload or existing_stop is None:
        normalized["planned_arrival_time"] = _parse_datetime(
            payload.get("planned_arrival_time"),
            "planned_arrival_time",
            required=False,
        )
    if "planned_departure_time" in payload or existing_stop is None:
        normalized["planned_departure_time"] = _parse_datetime(
            payload.get("planned_departure_time"),
            "planned_departure_time",
            required=False,
        )
    if "stop_charge" in payload or existing_stop is None:
        normalized["stop_charge"] = _validate_non_negative_number(payload.get("stop_charge"), "stop_charge")
    if "stop_status" in payload or existing_stop is None:
        normalized["stop_status"] = _validate_enum(
            payload.get("stop_status"),
            "stop_status",
            ALLOWED_STOP_STATUSES,
            required=False,
            default=(existing_stop or {}).get("stop_status") or "pending",
        )
    normalized["linked_movement_id"] = (existing_stop or {}).get("linked_movement_id")
    normalized["delivery_status"] = (existing_stop or {}).get("delivery_status") or "pending"
    normalized["delivered_at"] = (existing_stop or {}).get("delivered_at")
    normalized["delivery_note"] = (existing_stop or {}).get("delivery_note")
    normalized["delivered_by"] = (existing_stop or {}).get("delivered_by")
    if (
        normalized.get("planned_arrival_time") is not None
        and normalized.get("planned_departure_time") is not None
        and normalized["planned_departure_time"] <= normalized["planned_arrival_time"]
    ):
        raise ApiError("planned_departure_time must be after planned_arrival_time.", status_code=400)
    normalized["stop_id"] = (existing_stop or {}).get("stop_id") or uuid4().hex
    return normalized


def _validate_stops(stops: list[dict]):
    if not stops:
        return
    sequences = [stop.get("stop_sequence") for stop in stops]
    if len(sequences) != len(set(sequences)):
        raise ApiError("Multi-stop sequence must be unique per request.", status_code=400)
    if len(stops) > 1:
        stop_types = {stop.get("stop_type") for stop in stops}
        if "pickup" not in stop_types or "dropoff" not in stop_types:
            raise ApiError(
                "At least one pickup and one dropoff should exist for multi-stop dispatch.",
                status_code=400,
            )


def _get_linked_vehicle_movement_for_stop(movement_id: str, *, current_user_id: str, current_role: str) -> dict:
    movement_object_id = _to_object_id(movement_id, "movement_id")
    movement = vehicle_movements_collection().find_one({"_id": movement_object_id})
    if not movement:
        raise ApiError("Linked vehicle movement not found.", status_code=404)
    if movement.get("movement_type") != "customer_dispatch":
        raise ApiError("Only customer dispatch movements support delivery confirmation.", status_code=400)
    if movement.get("status") not in DELIVERY_CONFIRMABLE_MOVEMENT_STATUSES:
        raise ApiError("Delivery can only be confirmed after check-out or while in progress.", status_code=400)
    if current_role == "driver" and movement.get("driver_id") != _to_object_id(current_user_id, "current_user_id"):
        raise ApiError("You can only confirm delivery for your own dispatch movement.", status_code=403)
    return movement


def list_dispatch_request_options(*, current_role: str, current_user_id: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_view_role(normalized_role)
    cache_key = build_cache_key("dispatch_requests:options", role=normalized_role, user_id=current_user_id if normalized_role not in OWNER_ADMIN_ROLES else None)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    started_at = perf_counter()
    payload = {
        "request_types": [item["name"] for item in get_active_master_data_items("dispatch_request_types")],
        "pickup_locations": [item["name"] for item in get_active_master_data_items("dispatch_pickup_locations")],
        "vehicle_types": [item["name"] for item in get_active_master_data_items("dispatch_vehicle_types")],
        "load_types": [item["name"] for item in get_active_master_data_items("dispatch_load_types")],
        "load_weight_categories": [item["name"] for item in get_active_master_data_items("dispatch_load_weight_categories")],
        "load_size_categories": [item["name"] for item in get_active_master_data_items("dispatch_load_size_categories")],
        "urgencies": [item["name"] for item in get_active_master_data_items("dispatch_urgencies")],
        "payment_statuses": [item["name"] for item in get_active_master_data_items("dispatch_payment_statuses")],
        "dispatch_financial_types": sorted(DISPATCH_FINANCIAL_TYPES),
        "partner_billing_methods": sorted(PARTNER_BILLING_METHODS),
        "driver_compensation_types": sorted(DRIVER_COMPENSATION_TYPES),
        "statuses": sorted(ALLOWED_DISPATCH_REQUEST_STATUSES),
        "editable_statuses": sorted(EDITABLE_UNAPPROVED_STATUSES),
        "pricing_statuses": sorted(ALLOWED_PRICING_STATUSES),
        "schedule_types": sorted(ALLOWED_SCHEDULE_TYPES),
        "recurrence_patterns": sorted(ALLOWED_RECURRENCE_PATTERNS),
        "stop_types": sorted(ALLOWED_STOP_TYPES),
        "stop_statuses": sorted(ALLOWED_STOP_STATUSES),
    }
    log_db_duration("dispatch_requests.options.master_data", started_at)
    return set_ttl_cached(cache_key, payload, ttl_seconds=30)


def list_dispatch_requests(
    *,
    current_role: str,
    page: int = 1,
    page_size: int = 25,
    search_query: str | None = None,
    status: str | None = None,
    vehicle_type_needed: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_view_role(normalized_role)
    request_started_at = perf_counter()
    query: dict = {}

    if status:
        query["status"] = _validate_enum(status, "status", ALLOWED_DISPATCH_REQUEST_STATUSES, required=True)
    if vehicle_type_needed:
        query["vehicle_type_needed"] = _validate_master_data_value(
            vehicle_type_needed,
            "vehicle_type_needed",
            required=True,
        )

    normalized_search_query = _normalize_text(search_query)
    if normalized_search_query:
        escaped = re.escape(normalized_search_query)
        query["$or"] = [
            {"request_id": {"$regex": escaped, "$options": "i"}},
            {"customer_name": {"$regex": escaped, "$options": "i"}},
            {"customer_phone": {"$regex": escaped, "$options": "i"}},
            {"pickup_location": {"$regex": escaped, "$options": "i"}},
            {"destination": {"$regex": escaped, "$options": "i"}},
        ]

    preferred_pickup_date_filter = {}
    if date_from:
        preferred_pickup_date_filter["$gte"] = _parse_date(date_from, "date_from", required=True)
    if date_to:
        preferred_pickup_date_filter["$lte"] = _parse_date(date_to, "date_to", required=True)
    if preferred_pickup_date_filter:
        query["preferred_pickup_date"] = preferred_pickup_date_filter

    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 25, 1), 100)
    skip = (normalized_page - 1) * normalized_page_size

    aggregate_started_at = perf_counter()
    pipeline = [
        {"$match": query},
        {
            "$facet": {
                "records": [
                    {"$sort": {"preferred_pickup_date": -1, "created_at": -1, "_id": -1}},
                    {"$skip": skip},
                    {"$limit": normalized_page_size},
                    {"$project": LIST_PROJECTION},
                ],
                "counts": [{"$count": "total"}],
            }
        },
    ]
    aggregate_result = list(dispatch_requests_collection().aggregate(pipeline))
    log_db_duration("dispatch_requests.list.aggregate", aggregate_started_at)
    aggregate_payload = aggregate_result[0] if aggregate_result else {}
    documents = aggregate_payload.get("records") or []
    total = int(((aggregate_payload.get("counts") or [{}])[0]).get("total") or 0)

    return {
        "requests": [serialize_dispatch_request(document) for document in documents],
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "filters": {
            "q": search_query,
            "status": status,
            "vehicle_type_needed": vehicle_type_needed,
            "date_from": date_from,
            "date_to": date_to,
        },
        "generated_at": now_utc().isoformat(),
        "duration_ms": round((perf_counter() - request_started_at) * 1000, 2),
    }


def get_dispatch_request_by_id(request_id: str, *, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_view_role(normalized_role)
    document = _get_dispatch_request_document(request_id, projection=DETAIL_PROJECTION)
    return _batch_enrich_dispatch_requests([document])[0]


def list_scheduled_dispatch_requests(
    *,
    current_role: str,
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
    vehicle_type_needed: str | None = None,
    pricing_status: str | None = None,
    schedule_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_view_role(normalized_role)
    request_started_at = perf_counter()

    query: dict = {"scheduled_start_time": {"$ne": None}}
    if status:
        query["status"] = _validate_enum(status, "status", ALLOWED_DISPATCH_REQUEST_STATUSES, required=True)
    if vehicle_type_needed:
        query["vehicle_type_needed"] = _validate_master_data_value(
            vehicle_type_needed,
            "vehicle_type_needed",
            required=True,
        )
    if pricing_status:
        query["pricing_status"] = _validate_enum(
            pricing_status,
            "pricing_status",
            ALLOWED_PRICING_STATUSES,
            required=True,
        )
    if schedule_type:
        query["schedule_type"] = _validate_enum(
            schedule_type,
            "schedule_type",
            ALLOWED_SCHEDULE_TYPES,
            required=True,
        )

    scheduled_range = {}
    if date_from:
        scheduled_range["$gte"] = _parse_datetime(f"{_parse_date(date_from, 'date_from', required=True)}T00:00:00", "date_from")
    if date_to:
        scheduled_range["$lte"] = _parse_datetime(f"{_parse_date(date_to, 'date_to', required=True)}T23:59:59", "date_to")
    if scheduled_range:
        query["scheduled_start_time"] = scheduled_range

    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 25, 1), 100)
    skip = (normalized_page - 1) * normalized_page_size

    pipeline = [
        {"$match": query},
        {
            "$facet": {
                "records": [
                    {"$sort": {"scheduled_start_time": 1, "created_at": -1, "_id": -1}},
                    {"$skip": skip},
                    {"$limit": normalized_page_size},
                    {"$project": LIST_PROJECTION},
                ],
                "counts": [{"$count": "total"}],
            }
        },
    ]
    aggregate_started_at = perf_counter()
    aggregate_result = list(dispatch_requests_collection().aggregate(pipeline))
    log_db_duration("dispatch_requests.schedule.aggregate", aggregate_started_at)
    aggregate_payload = aggregate_result[0] if aggregate_result else {}
    documents = aggregate_payload.get("records") or []
    total = int(((aggregate_payload.get("counts") or [{}])[0]).get("total") or 0)

    return {
        "requests": [serialize_dispatch_request(document) for document in documents],
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "filters": {
            "status": status,
            "vehicle_type_needed": vehicle_type_needed,
            "pricing_status": pricing_status,
            "schedule_type": schedule_type,
            "date_from": date_from,
            "date_to": date_to,
        },
        "generated_at": now_utc().isoformat(),
        "duration_ms": round((perf_counter() - request_started_at) * 1000, 2),
    }


def create_dispatch_request(payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    normalized_payload = _normalize_dispatch_request_payload(payload or {}, partial=False, current_role=normalized_role)
    _validate_request_timing(normalized_payload)
    timestamp = now_utc()
    actor_id = _to_object_id(current_user_id, "current_user_id")
    document = {
        **normalized_payload,
        "request_id": _generate_request_id(),
        "rejection_reason": None,
        "cancellation_reason": None,
        "created_by": actor_id,
        "financial_type_changed_by": actor_id,
        "financial_type_changed_at": timestamp,
        "driver_compensation_approved_by": actor_id if normalized_role in OWNER_ADMIN_ROLES else None,
        "driver_compensation_approved_at": timestamp if normalized_role in OWNER_ADMIN_ROLES else None,
        "reviewed_by": None,
        "approved_by": None,
        "rejected_by": None,
        "cancelled_by": None,
        "pricing_reviewed_by": None,
        "reviewed_at": None,
        "approved_at": None,
        "rejected_at": None,
        "cancelled_at": None,
        "pricing_reviewed_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = dispatch_requests_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _batch_enrich_dispatch_requests([document])[0]


def find_dispatch_request_by_source_opportunity(opportunity_record_id: ObjectId) -> dict | None:
    document = dispatch_requests_collection().find_one(
        {"source_dispatch_opportunity_record_id": opportunity_record_id},
        projection=DETAIL_PROJECTION,
    )
    if not document:
        return None
    return _batch_enrich_dispatch_requests([document])[0]


def create_dispatch_request_from_opportunity(opportunity_document: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    existing = find_dispatch_request_by_source_opportunity(opportunity_document["_id"])
    if existing is not None:
        return existing

    normalized_payload = _normalize_dispatch_request_payload(
        {
            "request_type": _resolve_default_dispatch_request_type(),
            "customer_name": opportunity_document.get("customer_name"),
            "customer_phone": opportunity_document.get("customer_phone"),
            "customer_company": opportunity_document.get("customer_company"),
            "pickup_location": opportunity_document.get("pickup_location"),
            "destination": opportunity_document.get("destination"),
            "vehicle_type_needed": opportunity_document.get("vehicle_type_needed"),
            "load_type": opportunity_document.get("load_type"),
            "load_weight_category": opportunity_document.get("load_weight_category"),
            "load_size_category": opportunity_document.get("load_size_category"),
            "load_description": opportunity_document.get("load_description"),
            "preferred_pickup_date": opportunity_document.get("preferred_pickup_date"),
            "preferred_pickup_time": opportunity_document.get("preferred_pickup_time"),
            "proposed_charge": opportunity_document.get("proposed_charge"),
            "dispatch_financial_type": "external_paid",
            "amount_paid": 0,
            "driver_compensation_type": "none",
            "driver_compensation_value": 0,
            "payment_status": opportunity_document.get("payment_status") or "Unpaid",
            "notes": opportunity_document.get("notes"),
            "status": "new",
        },
        partial=False,
        current_role=normalized_role,
    )
    normalized_payload["approved_charge"] = opportunity_document.get("approved_charge")
    normalized_payload["pricing_notes"] = opportunity_document.get("review_notes")
    normalized_payload["expected_net_revenue"] = _compute_expected_net_revenue(
        approved_charge=normalized_payload.get("approved_charge"),
        proposed_charge=normalized_payload.get("proposed_charge"),
        fuel_estimate_cost=normalized_payload.get("fuel_estimate_cost"),
        other_expected_costs=normalized_payload.get("other_expected_costs"),
        dispatch_financial_type=normalized_payload.get("dispatch_financial_type"),
        partner_billing_method=normalized_payload.get("partner_billing_method"),
        driver_compensation_amount=normalized_payload.get("driver_compensation_amount"),
    )
    _validate_request_timing(normalized_payload)

    timestamp = now_utc()
    actor_id = _to_object_id(current_user_id, "current_user_id")
    document = {
        **normalized_payload,
        "request_id": _generate_request_id(),
        "source_dispatch_opportunity_id": opportunity_document.get("opportunity_id"),
        "source_dispatch_opportunity_record_id": opportunity_document["_id"],
        "submitted_by_driver_id": opportunity_document.get("submitted_by_driver_id"),
        "rejection_reason": None,
        "cancellation_reason": None,
        "created_by": actor_id,
        "financial_type_changed_by": actor_id,
        "financial_type_changed_at": timestamp,
        "driver_compensation_approved_by": actor_id if normalized_role in OWNER_ADMIN_ROLES else None,
        "driver_compensation_approved_at": timestamp if normalized_role in OWNER_ADMIN_ROLES else None,
        "reviewed_by": None,
        "approved_by": None,
        "rejected_by": None,
        "cancelled_by": None,
        "pricing_reviewed_by": None,
        "reviewed_at": None,
        "approved_at": None,
        "rejected_at": None,
        "cancelled_at": None,
        "pricing_reviewed_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = dispatch_requests_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _batch_enrich_dispatch_requests([document])[0]


def update_dispatch_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    _validate_edit_status(document, current_role=normalized_role)

    allowed_fields = set(EDITOR_PATCHABLE_FIELDS)
    if normalized_role in OWNER_ADMIN_ROLES:
        allowed_fields |= ADMIN_ONLY_PATCHABLE_FIELDS
    filtered_payload = {key: value for key, value in (payload or {}).items() if key in allowed_fields}
    if not filtered_payload:
        raise ApiError("No valid dispatch request fields provided for update.", status_code=400)

    normalized_payload = _normalize_dispatch_request_payload(filtered_payload, partial=True, current_role=normalized_role)
    next_status = normalized_payload.get("status")
    if next_status and next_status not in EDITABLE_UNAPPROVED_STATUSES:
        raise ApiError("Use the dedicated action endpoints to approve, reject, or cancel requests.", status_code=400)
    if document.get("status") == "approved" and next_status:
        raise ApiError("Approved dispatch requests cannot be moved back through edit.", status_code=400)

    updated_document = {**document, **normalized_payload}
    _validate_request_timing(updated_document)
    classification = _validate_financial_classification(updated_document)
    normalized_payload.update(classification)
    timestamp = now_utc()
    update_fields = {**normalized_payload, "updated_at": timestamp}
    if classification["dispatch_financial_type"] != resolve_dispatch_financial_type(document)[0]:
        update_fields["financial_type_changed_by"] = _to_object_id(current_user_id, "current_user_id")
        update_fields["financial_type_changed_at"] = timestamp
    if any(key in filtered_payload for key in {"driver_compensation_type", "driver_compensation_value"}):
        update_fields["driver_compensation_approved_by"] = (
            _to_object_id(current_user_id, "current_user_id") if normalized_role in OWNER_ADMIN_ROLES else None
        )
        update_fields["driver_compensation_approved_at"] = timestamp if normalized_role in OWNER_ADMIN_ROLES else None
    update_fields["expected_net_revenue"] = _compute_expected_net_revenue(
        approved_charge=updated_document.get("approved_charge"), proposed_charge=updated_document.get("proposed_charge"),
        fuel_estimate_cost=updated_document.get("fuel_estimate_cost"), other_expected_costs=updated_document.get("other_expected_costs"),
        dispatch_financial_type=classification["dispatch_financial_type"],
        partner_billing_method=classification["partner_billing_method"],
        driver_compensation_amount=classification["driver_compensation_amount"],
    )
    if next_status in {"reviewing", "pricing_pending"}:
        update_fields["reviewed_by"] = _to_object_id(current_user_id, "current_user_id")
        update_fields["reviewed_at"] = timestamp
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    if next_status == "pricing_pending":
        notify_roles(
            ["owner", "admin"],
            title="Pricing approval required",
            message=f"Dispatch request {document.get('request_id')} is awaiting pricing approval.",
            category="dispatch_pricing",
            priority="high",
            reference_type="dispatch_request",
            reference_id=document["_id"],
            action_type="approve_pricing",
            action_url="dispatch-requests",
            action_label="Review pricing",
        )
    return _batch_enrich_dispatch_requests([document])[0]


def revise_dispatch_request_pricing(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    _validate_planning_status(document, current_role=normalized_role)

    normalized_payload = _normalize_pricing_payload(payload or {}, current_role=normalized_role)
    if not normalized_payload:
        raise ApiError("No pricing fields were provided.", status_code=400)

    timestamp = now_utc()
    merged_document = _validate_pricing_state(
        document,
        {**normalized_payload, "pricing_status": "pricing_revised"},
        action="revise",
    )
    update_fields = {
        **normalized_payload,
        **{key: merged_document.get(key) for key in (
            "outstanding_balance", "driver_compensation_amount", "payment_status",
        )},
        "pricing_status": "pricing_revised",
        "expected_net_revenue": merged_document.get("expected_net_revenue"),
        "pricing_reviewed_by": _to_object_id(current_user_id, "current_user_id"),
        "pricing_reviewed_at": timestamp,
        "updated_at": timestamp,
    }
    history_entry = _build_pricing_history_entry(
        action="revise",
        actor_id=current_user_id,
        payload={**merged_document, **update_fields},
    )
    dispatch_requests_collection().update_one(
        {"_id": document["_id"]},
        {"$set": update_fields, "$push": {"pricing_history": history_entry}},
    )
    document.update(update_fields)
    document.setdefault("pricing_history", []).append(history_entry)
    return _batch_enrich_dispatch_requests([document])[0]


def approve_dispatch_request_pricing(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    if document.get("status") == "converted" and normalized_role not in OWNER_ADMIN_ROLES:
        raise ApiError("Converted requests can only be repriced by owner or admin.", status_code=403)

    normalized_payload = _normalize_pricing_payload(payload or {}, current_role=normalized_role)
    timestamp = now_utc()
    merged_document = _validate_pricing_state(
        document,
        {**normalized_payload, "pricing_status": "pricing_approved"},
        action="approve",
    )
    update_fields = {
        **normalized_payload,
        "pricing_status": "pricing_approved",
        "approved_charge": merged_document.get("approved_charge")
        if merged_document.get("approved_charge") is not None
        else merged_document.get("proposed_charge"),
        **{key: merged_document.get(key) for key in (
            "outstanding_balance", "driver_compensation_amount", "payment_status",
        )},
        "expected_net_revenue": merged_document.get("expected_net_revenue"),
        "pricing_reviewed_by": _to_object_id(current_user_id, "current_user_id"),
        "pricing_reviewed_at": timestamp,
        "updated_at": timestamp,
    }
    history_entry = _build_pricing_history_entry(
        action="approve",
        actor_id=current_user_id,
        payload={**merged_document, **update_fields},
    )
    dispatch_requests_collection().update_one(
        {"_id": document["_id"]},
        {"$set": update_fields, "$push": {"pricing_history": history_entry}},
    )
    document.update(update_fields)
    document.setdefault("pricing_history", []).append(history_entry)
    resolve_action_notifications("dispatch_request", document["_id"], action_type="approve_pricing", completed_by=current_user_id)
    return _batch_enrich_dispatch_requests([document])[0]


def reject_dispatch_request_pricing(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    normalized_payload = _normalize_pricing_payload(payload or {}, current_role=normalized_role)
    timestamp = now_utc()
    merged_document = _validate_pricing_state(
        document,
        {**normalized_payload, "pricing_status": "pricing_rejected"},
        action="reject",
    )
    update_fields = {
        **normalized_payload,
        "pricing_status": "pricing_rejected",
        "expected_net_revenue": merged_document.get("expected_net_revenue"),
        "pricing_reviewed_by": _to_object_id(current_user_id, "current_user_id"),
        "pricing_reviewed_at": timestamp,
        "updated_at": timestamp,
    }
    history_entry = _build_pricing_history_entry(
        action="reject",
        actor_id=current_user_id,
        payload={**merged_document, **update_fields},
    )
    dispatch_requests_collection().update_one(
        {"_id": document["_id"]},
        {"$set": update_fields, "$push": {"pricing_history": history_entry}},
    )
    document.update(update_fields)
    document.setdefault("pricing_history", []).append(history_entry)
    resolve_action_notifications("dispatch_request", document["_id"], action_type="approve_pricing", resolution="cancelled", completed_by=current_user_id)
    return _batch_enrich_dispatch_requests([document])[0]


def update_dispatch_request_schedule(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    _validate_planning_status(document, current_role=normalized_role)

    normalized_payload = _normalize_schedule_payload(payload or {})
    if not normalized_payload:
        raise ApiError("No schedule fields were provided.", status_code=400)

    merged_document = _validate_schedule_state(document, normalized_payload)
    timestamp = now_utc()
    update_fields = {
        **normalized_payload,
        "recurrence_pattern": merged_document.get("recurrence_pattern"),
        "recurrence_end_date": merged_document.get("recurrence_end_date"),
        "updated_at": timestamp,
    }
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_dispatch_requests([document])[0]


def add_dispatch_request_stop(request_id: str, payload: dict, *, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    _validate_planning_status(document, current_role=normalized_role)

    stops = list(document.get("stops") or [])
    new_stop = _normalize_stop_payload(payload or {})
    stops.append(new_stop)
    _validate_stops(stops)
    update_fields = {"stops": sorted(stops, key=lambda item: item["stop_sequence"]), "stops_count": len(stops), "updated_at": now_utc()}
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_dispatch_requests([document])[0]


def update_dispatch_request_stop(request_id: str, stop_id: str, payload: dict, *, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    _validate_planning_status(document, current_role=normalized_role)

    stops = list(document.get("stops") or [])
    stop_index = next((index for index, stop in enumerate(stops) if stop.get("stop_id") == stop_id), None)
    if stop_index is None:
        raise ApiError("Dispatch stop not found.", status_code=404)
    stops[stop_index] = _normalize_stop_payload(payload or {}, existing_stop=stops[stop_index])
    _validate_stops(stops)
    update_fields = {"stops": sorted(stops, key=lambda item: item["stop_sequence"]), "stops_count": len(stops), "updated_at": now_utc()}
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_dispatch_requests([document])[0]


def delete_dispatch_request_stop(request_id: str, stop_id: str, *, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_edit_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    _validate_planning_status(document, current_role=normalized_role)

    stops = [stop for stop in list(document.get("stops") or []) if stop.get("stop_id") != stop_id]
    if len(stops) == len(list(document.get("stops") or [])):
        raise ApiError("Dispatch stop not found.", status_code=404)
    _validate_stops(stops)
    update_fields = {"stops": sorted(stops, key=lambda item: item["stop_sequence"]), "stops_count": len(stops), "updated_at": now_utc()}
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_dispatch_requests([document])[0]


def confirm_dispatch_request_stop_delivery(
    request_id: str,
    stop_id: str,
    payload: dict,
    *,
    current_user_id: str,
    current_role: str,
) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    if normalized_role not in BACKOFFICE_VIEW_ROLES | {"driver"}:
        raise ApiError("You do not have permission to confirm dispatch stop delivery.", status_code=403)
    document = _get_dispatch_request_document(request_id)
    stops = list(document.get("stops") or [])
    stop_index = next((index for index, stop in enumerate(stops) if stop.get("stop_id") == stop_id), None)
    if stop_index is None:
        raise ApiError("Dispatch stop not found.", status_code=404)

    stop = dict(stops[stop_index])
    linked_movement_id = _normalize_text((payload or {}).get("movement_id")) or _normalize_text(stop.get("linked_movement_id"))
    if normalized_role == "driver":
        if not linked_movement_id:
            raise ApiError("movement_id is required for driver stop delivery confirmation.", status_code=400)
        _get_linked_vehicle_movement_for_stop(
            linked_movement_id,
            current_user_id=current_user_id,
            current_role=normalized_role,
        )
    elif linked_movement_id:
        _get_linked_vehicle_movement_for_stop(
            linked_movement_id,
            current_user_id=current_user_id,
            current_role="admin",
        )

    stop["linked_movement_id"] = _to_object_id(linked_movement_id, "movement_id", required=False) if linked_movement_id else None
    stop["delivery_status"] = "delivered"
    stop["delivered_at"] = _parse_datetime((payload or {}).get("delivered_at"), "delivered_at", required=False) or now_utc()
    stop["delivery_note"] = _normalize_text((payload or {}).get("delivery_note"))
    stop["delivered_by"] = _to_object_id(current_user_id, "current_user_id")
    stops[stop_index] = stop

    update_fields = {"stops": stops, "updated_at": now_utc()}
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_dispatch_requests([document])[0]


def approve_dispatch_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    if document.get("status") not in EDITABLE_UNAPPROVED_STATUSES:
        raise ApiError("Only unapproved dispatch requests can be approved.", status_code=400)

    approved_charge = _validate_non_negative_number(payload.get("approved_charge"), "approved_charge")
    final_charge = approved_charge if approved_charge is not None else document.get("proposed_charge") or 0.0
    classification = _validate_financial_classification({**document, "approved_charge": final_charge})
    timestamp = now_utc()
    update_fields = {
        "status": "approved",
        "approved_charge": final_charge,
        **classification,
        "pricing_status": "pricing_approved",
        "expected_net_revenue": _compute_expected_net_revenue(
            approved_charge=final_charge,
            proposed_charge=document.get("proposed_charge"),
            fuel_estimate_cost=document.get("fuel_estimate_cost"),
            other_expected_costs=document.get("other_expected_costs"),
            dispatch_financial_type=classification["dispatch_financial_type"],
            partner_billing_method=classification["partner_billing_method"],
            driver_compensation_amount=classification["driver_compensation_amount"],
        ),
        "reviewed_by": _to_object_id(current_user_id, "current_user_id"),
        "approved_by": _to_object_id(current_user_id, "current_user_id"),
        "pricing_reviewed_by": _to_object_id(current_user_id, "current_user_id"),
        "reviewed_at": timestamp,
        "approved_at": timestamp,
        "pricing_reviewed_at": timestamp,
        "updated_at": timestamp,
    }
    history_entry = _build_pricing_history_entry(
        action="approve_request",
        actor_id=current_user_id,
        payload={**document, **update_fields},
    )
    dispatch_requests_collection().update_one(
        {"_id": document["_id"]},
        {"$set": update_fields, "$push": {"pricing_history": history_entry}},
    )
    document.update(update_fields)
    document.setdefault("pricing_history", []).append(history_entry)
    return _batch_enrich_dispatch_requests([document])[0]


def reject_dispatch_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    if document.get("status") not in EDITABLE_UNAPPROVED_STATUSES:
        raise ApiError("Only unapproved dispatch requests can be rejected.", status_code=400)

    rejection_reason = _normalize_text((payload or {}).get("rejection_reason"))
    if not rejection_reason:
        raise ApiError("rejection_reason is required when rejecting a dispatch request.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "status": "rejected",
        "rejection_reason": rejection_reason,
        "reviewed_by": _to_object_id(current_user_id, "current_user_id"),
        "rejected_by": _to_object_id(current_user_id, "current_user_id"),
        "reviewed_at": timestamp,
        "rejected_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_dispatch_requests([document])[0]


def cancel_dispatch_request(request_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_role(normalized_role)
    document = _get_dispatch_request_document(request_id)
    if document.get("status") in {"converted", "cancelled"}:
        raise ApiError("This dispatch request can no longer be cancelled.", status_code=400)

    cancellation_reason = _normalize_text((payload or {}).get("cancellation_reason"))
    if not cancellation_reason:
        raise ApiError("cancellation_reason is required when cancelling a dispatch request.", status_code=400)
    linked_job_id = document.get("active_dispatch_job_id")
    linked_job = dispatch_jobs_collection().find_one({"_id": linked_job_id}) if isinstance(linked_job_id, ObjectId) else None
    if linked_job and linked_job.get("status") in {"in_progress", "completed"}:
        raise ApiError("Dispatch requests cannot be cancelled after the linked dispatch has started.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "status": "cancelled",
        "planning_status": "cancelled",
        "active_dispatch_job_id": None,
        "cancellation_reason": cancellation_reason,
        "cancelled_by": _to_object_id(current_user_id, "current_user_id"),
        "cancelled_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_requests_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    reservation_release_result = {
        "reservation_ids": [],
        "released_count": 0,
        "reason": None,
    }
    if linked_job and linked_job.get("status") not in {"completed", "cancelled"}:
        from services.dispatch_planner_service import _release_reservations

        dispatch_jobs_collection().update_one(
            {"_id": linked_job_id},
            {
                "$set": {
                    "status": "cancelled",
                    "cancelled_at": timestamp,
                    "updated_at": timestamp,
                    "updated_by": _to_object_id(current_user_id, "current_user_id"),
                }
            },
        )
        reservation_release_result = _release_reservations(linked_job, reason="dispatch request cancelled")
        if isinstance(linked_job.get("driver_id"), ObjectId):
            create_notification(
                recipient_user_id=linked_job["driver_id"],
                title="Dispatch cancelled",
                message=f"Dispatch {linked_job.get('dispatch_job_id')} has been cancelled by operations.",
                category="dispatch_cancelled",
                priority="high",
                reference_type="dispatch_job",
                reference_id=linked_job_id,
            )
    persisted_document = _get_dispatch_request_document(request_id, projection=DETAIL_PROJECTION)
    response_payload = _batch_enrich_dispatch_requests([persisted_document])[0]
    response_payload["reservation_release_result"] = reservation_release_result
    return response_payload
