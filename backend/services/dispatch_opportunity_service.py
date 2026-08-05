from __future__ import annotations

from datetime import date, datetime, timezone
from math import ceil
from time import perf_counter
import re
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.dispatch_opportunity import serialize_dispatch_opportunity
from models.user import serialize_user
from services.master_data_service import assert_master_data_value, get_active_master_data_items
from services.notification_service import create_notification, notify_roles, resolve_action_notifications
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached


ALLOWED_OPPORTUNITY_STATUSES = {
    "draft",
    "submitted",
    "under_review",
    "needs_clarification",
    "approved",
    "converted_to_dispatch_request",
    "rejected",
    "withdrawn",
}
DRIVER_MUTABLE_STATUSES = {"draft", "submitted", "needs_clarification"}
DRIVER_WITHDRAWABLE_STATUSES = {"draft", "submitted", "needs_clarification"}
ADMIN_REVIEWABLE_STATUSES = {"submitted", "under_review", "needs_clarification", "approved"}
ADMIN_CLARIFICATION_STATUSES = {"submitted", "under_review", "needs_clarification"}
ADMIN_APPROVABLE_STATUSES = {"submitted", "under_review"}
ADMIN_CONVERTIBLE_STATUSES = {"approved"}
ADMIN_REVIEW_ROLES = {"owner", "admin", "dispatcher", "customer_service"}
TRIP_PURPOSES = {"PASSENGER", "GOODS", "MIXED", "OTHER"}
DISPATCH_CLASSIFICATIONS = {"COMMERCIAL", "COMPLIMENTARY", "COST_CONTRIBUTION"}
MASTER_DATA_GROUPS = {
    "pickup_location": "dispatch_pickup_locations",
    "vehicle_type_needed": "dispatch_vehicle_types",
    "load_type": "dispatch_load_types",
    "load_weight_category": "dispatch_load_weight_categories",
    "load_size_category": "dispatch_load_size_categories",
    "payment_status": "dispatch_payment_statuses",
}
LIST_PROJECTION = {
    "opportunity_id": 1,
    "customer_name": 1,
    "customer_phone": 1,
    "customer_company": 1,
    "pickup_location": 1,
    "pickup_landmark": 1,
    "destination": 1,
    "destination_landmark": 1,
    "trip_purpose": 1,
    "load_type": 1,
    "load_weight_category": 1,
    "load_size_category": 1,
    "vehicle_type_needed": 1,
    "preferred_pickup_date": 1,
    "preferred_pickup_time": 1,
    "proposed_charge": 1,
    "approved_charge": 1,
    "dispatch_classification": 1,
    "complimentary_reason": 1,
    "contribution_amount": 1,
    "contribution_purpose": 1,
    "contribution_payment_method": 1,
    "contribution_collected_by": 1,
    "contribution_reconciliation_status": 1,
    "payment_status": 1,
    "status": 1,
    "submitted_by_driver_id": 1,
    "reviewed_by": 1,
    "approved_by": 1,
    "dispatch_request_id": 1,
    "created_at": 1,
    "updated_at": 1,
    "submitted_at": 1,
}
DETAIL_PROJECTION = {
    **LIST_PROJECTION,
    "load_description": 1,
    "notes": 1,
    "review_notes": 1,
    "clarification_request": 1,
    "rejection_reason": 1,
    "withdrawal_reason": 1,
    "rejected_by": 1,
    "withdrawn_by": 1,
    "converted_by": 1,
    "dispatch_request_record_id": 1,
    "reviewed_at": 1,
    "approved_at": 1,
    "rejected_at": 1,
    "withdrawn_at": 1,
    "converted_at": 1,
}
USER_SUMMARY_PROJECTION = {"full_name": 1, "email": 1, "phone": 1, "role": 1, "status": 1}
DRIVER_EDITABLE_FIELDS = {
    "customer_name",
    "customer_phone",
    "customer_company",
    "pickup_location",
    "pickup_landmark",
    "destination",
    "destination_landmark",
    "trip_purpose",
    "load_description",
    "load_type",
    "load_weight_category",
    "load_size_category",
    "vehicle_type_needed",
    "preferred_pickup_date",
    "preferred_pickup_time",
    "proposed_charge",
    "dispatch_classification",
    "complimentary_reason",
    "contribution_amount",
    "contribution_purpose",
    "contribution_payment_method",
    "payment_status",
    "notes",
    "status",
}


def now_utc():
    return datetime.now(timezone.utc)


def dispatch_opportunities_collection():
    return get_collection("dispatch_opportunities")


def users_collection():
    return get_collection("users")


def ensure_dispatch_opportunity_indexes():
    cleanup_result = dispatch_opportunities_collection().update_many(
        {"dispatch_request_record_id": None},
        {"$unset": {"dispatch_request_record_id": ""}},
    )
    if cleanup_result.modified_count:
        try:
            from flask import current_app

            current_app.logger.info(
                "[Flux Indexes] Removed null dispatch_request_record_id from %s dispatch opportunities",
                cleanup_result.modified_count,
            )
        except RuntimeError:
            pass
    ensure_indexes_for_collection(
        dispatch_opportunities_collection(),
        [
            {"keys": [("opportunity_id", ASCENDING)], "options": {"unique": True}},
            {"keys": [("submitted_by_driver_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("submitted_at", DESCENDING)], "options": {"sparse": True}},
            {"keys": [("customer_phone", ASCENDING)]},
            {"keys": [("pickup_location", ASCENDING)]},
            {"keys": [("destination", ASCENDING)]},
            {"keys": [("submitted_by_driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("submitted_by_driver_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("customer_phone", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("pickup_location", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("destination", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("dispatch_request_record_id", ASCENDING)], "options": {"unique": True, "sparse": True}},
        ],
        collection_name="dispatch_opportunities",
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


def _validate_master_data_value(value, field_name: str, *, required: bool = False):
    normalized = _normalize_text(value)
    if not normalized:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    return assert_master_data_value(MASTER_DATA_GROUPS[field_name], normalized)


def _validate_status(value: str | None) -> str:
    normalized = _normalize_text(value) or "draft"
    normalized = normalized.lower()
    if normalized not in ALLOWED_OPPORTUNITY_STATUSES:
        raise ApiError("Invalid dispatch opportunity status.", status_code=400)
    return normalized


def _assert_driver_role(current_role: str):
    if current_role != "driver":
        raise ApiError("You do not have permission to manage driver dispatch opportunities.", status_code=403)


def _assert_admin_review_role(current_role: str):
    if current_role not in ADMIN_REVIEW_ROLES:
        raise ApiError("You do not have permission to review dispatch opportunities.", status_code=403)


def _get_driver_document(driver_id: str) -> dict:
    document = users_collection().find_one({"_id": _to_object_id(driver_id, "driver_id"), "role": "driver"}, USER_SUMMARY_PROJECTION)
    if not document:
        raise ApiError("Driver not found.", status_code=404)
    return document


def _build_user_lookup(documents: list[dict]) -> dict[ObjectId, dict]:
    user_ids = {
        value
        for document in documents
        for value in (
            document.get("submitted_by_driver_id"),
            document.get("reviewed_by"),
            document.get("approved_by"),
            document.get("rejected_by"),
            document.get("withdrawn_by"),
            document.get("converted_by"),
        )
        if isinstance(value, ObjectId)
    }
    if not user_ids:
        return {}
    return {
        item["_id"]: item
        for item in users_collection().find({"_id": {"$in": list(user_ids)}}, USER_SUMMARY_PROJECTION)
    }


def _enrich_dispatch_opportunity(document: dict, *, user_lookup: dict[ObjectId, dict] | None = None) -> dict:
    payload = serialize_dispatch_opportunity(document)
    lookup = user_lookup or {}
    payload["submitted_by_driver"] = serialize_user(lookup[document["submitted_by_driver_id"]]) if lookup.get(document.get("submitted_by_driver_id")) else None
    payload["reviewed_by_user"] = serialize_user(lookup[document["reviewed_by"]]) if lookup.get(document.get("reviewed_by")) else None
    payload["approved_by_user"] = serialize_user(lookup[document["approved_by"]]) if lookup.get(document.get("approved_by")) else None
    payload["rejected_by_user"] = serialize_user(lookup[document["rejected_by"]]) if lookup.get(document.get("rejected_by")) else None
    payload["withdrawn_by_user"] = serialize_user(lookup[document["withdrawn_by"]]) if lookup.get(document.get("withdrawn_by")) else None
    payload["converted_by_user"] = serialize_user(lookup[document["converted_by"]]) if lookup.get(document.get("converted_by")) else None
    return payload


def _batch_enrich_dispatch_opportunities(documents: list[dict]) -> list[dict]:
    if not documents:
        return []
    user_lookup = _build_user_lookup(documents)
    return [_enrich_dispatch_opportunity(document, user_lookup=user_lookup) for document in documents]


def _generate_opportunity_id() -> str:
    timestamp = now_utc().strftime("%Y%m%d%H%M%S")
    return f"DO-{timestamp}-{uuid4().hex[:6].upper()}"


def _normalize_dispatch_opportunity_payload(payload: dict, *, partial: bool = False) -> dict:
    normalized: dict = {}
    if "customer_name" in payload or not partial:
        normalized["customer_name"] = _normalize_text(payload.get("customer_name"))
    if "customer_phone" in payload or not partial:
        normalized["customer_phone"] = _normalize_phone(payload.get("customer_phone"))
    if "customer_company" in payload or not partial:
        normalized["customer_company"] = _normalize_text(payload.get("customer_company"))
    if "pickup_location" in payload or not partial:
        normalized["pickup_location"] = _normalize_text(payload.get("pickup_location"))
    if "pickup_landmark" in payload or not partial:
        normalized["pickup_landmark"] = _normalize_text(payload.get("pickup_landmark"))
    if "destination" in payload or not partial:
        normalized["destination"] = _normalize_text(payload.get("destination"))
    if "destination_landmark" in payload or not partial:
        normalized["destination_landmark"] = _normalize_text(payload.get("destination_landmark"))
    if "trip_purpose" in payload or not partial:
        purpose = str(payload.get("trip_purpose") or "GOODS").strip().upper()
        if purpose not in TRIP_PURPOSES:
            raise ApiError("trip_purpose must be PASSENGER, GOODS, MIXED, or OTHER.", status_code=400)
        normalized["trip_purpose"] = purpose
    if "load_description" in payload or not partial:
        normalized["load_description"] = _normalize_text(payload.get("load_description"))
    if "load_type" in payload or not partial:
        normalized["load_type"] = _validate_master_data_value(payload.get("load_type"), "load_type", required=False)
    if "load_weight_category" in payload or not partial:
        normalized["load_weight_category"] = _validate_master_data_value(payload.get("load_weight_category"), "load_weight_category", required=False)
    if "load_size_category" in payload or not partial:
        normalized["load_size_category"] = _validate_master_data_value(payload.get("load_size_category"), "load_size_category", required=False)
    if "vehicle_type_needed" in payload or not partial:
        normalized["vehicle_type_needed"] = _validate_master_data_value(payload.get("vehicle_type_needed"), "vehicle_type_needed", required=False)
    if "preferred_pickup_date" in payload or not partial:
        normalized["preferred_pickup_date"] = _parse_date(payload.get("preferred_pickup_date"), "preferred_pickup_date", required=False)
    if "preferred_pickup_time" in payload or not partial:
        normalized["preferred_pickup_time"] = _parse_time(payload.get("preferred_pickup_time"), "preferred_pickup_time", required=False)
    if "proposed_charge" in payload or not partial:
        normalized["proposed_charge"] = _validate_non_negative_number(payload.get("proposed_charge"), "proposed_charge")
    if "approved_charge" in payload:
        normalized["approved_charge"] = _validate_non_negative_number(payload.get("approved_charge"), "approved_charge")
    if "dispatch_classification" in payload or not partial:
        classification = str(payload.get("dispatch_classification") or "COMMERCIAL").strip().upper()
        if classification not in DISPATCH_CLASSIFICATIONS:
            raise ApiError("Invalid dispatch_classification.", status_code=400)
        normalized["dispatch_classification"] = classification
    for field in ("complimentary_reason", "contribution_purpose", "contribution_payment_method"):
        if field in payload or not partial:
            normalized[field] = _normalize_text(payload.get(field))
    if "contribution_amount" in payload or not partial:
        normalized["contribution_amount"] = _validate_non_negative_number(payload.get("contribution_amount"), "contribution_amount")
    if "payment_status" in payload or not partial:
        normalized["payment_status"] = _validate_master_data_value(payload.get("payment_status"), "payment_status", required=False)
    if "notes" in payload or not partial:
        normalized["notes"] = _normalize_text(payload.get("notes"))
    if "review_notes" in payload:
        normalized["review_notes"] = _normalize_text(payload.get("review_notes"))
    if "status" in payload:
        normalized["status"] = _validate_status(payload.get("status"))
    return normalized


def _validate_complete_opportunity(document: dict):
    required_text_fields = (
        "customer_name",
        "customer_phone",
        "pickup_location",
        "destination",
        "vehicle_type_needed",
        "preferred_pickup_date",
        "preferred_pickup_time",
        "trip_purpose",
        "dispatch_classification",
    )
    for field_name in required_text_fields:
        if not document.get(field_name):
            raise ApiError(f"{field_name} is required before submitting a dispatch opportunity.", status_code=400)
    if document.get("trip_purpose") in {"GOODS", "MIXED"}:
        for field_name in ("load_description", "load_type", "load_weight_category", "load_size_category"):
            if not document.get(field_name):
                raise ApiError(f"{field_name} is required for goods or mixed dispatches.", status_code=400)
    classification = document.get("dispatch_classification") or "COMMERCIAL"
    charge = float(document.get("proposed_charge") or 0)
    if classification == "COMMERCIAL" and charge <= 0:
        raise ApiError("Commercial dispatches require a proposed charge greater than zero.", status_code=400)
    if classification == "COMPLIMENTARY":
        if charge != 0 or not document.get("complimentary_reason"):
            raise ApiError("Complimentary dispatches require zero charge and a reason.", status_code=400)
    if classification == "COST_CONTRIBUTION":
        if charge != 0 or float(document.get("contribution_amount") or 0) <= 0 or not document.get("contribution_purpose"):
            raise ApiError("Cost Contribution requires zero customer charge, a contribution amount, and a purpose.", status_code=400)


def _get_dispatch_opportunity_document(opportunity_id: str, *, projection: dict | None = None) -> dict:
    if not ObjectId.is_valid(opportunity_id):
        raise ApiError("Dispatch opportunity not found.", status_code=404)
    document = dispatch_opportunities_collection().find_one({"_id": ObjectId(opportunity_id)}, projection)
    if not document:
        raise ApiError("Dispatch opportunity not found.", status_code=404)
    return document


def _assert_driver_access(document: dict, *, current_user_id: str):
    if document.get("submitted_by_driver_id") != _to_object_id(current_user_id, "current_user_id"):
        raise ApiError("You can only access your own dispatch opportunities.", status_code=403)


def _load_existing_converted_request(document: dict):
    from services.dispatch_request_service import find_dispatch_request_by_source_opportunity

    return find_dispatch_request_by_source_opportunity(document["_id"])


def _raise_review_state_error(document: dict):
    status = document.get("status")
    if status == "draft":
        raise ApiError("This dispatch opportunity must be submitted before it can be reviewed.", status_code=400)
    if status == "rejected":
        raise ApiError("This dispatch opportunity has already been rejected and cannot be reviewed.", status_code=409)
    if status == "withdrawn":
        raise ApiError("This dispatch opportunity was withdrawn by the driver and cannot be reviewed.", status_code=409)
    if status == "converted_to_dispatch_request":
        raise ApiError("This dispatch opportunity has already been converted to a dispatch request.", status_code=409)
    raise ApiError("This dispatch opportunity cannot be reviewed right now.", status_code=400)


def _raise_approval_state_error(document: dict):
    status = document.get("status")
    if status == "draft":
        raise ApiError("This dispatch opportunity must be submitted before it can be approved.", status_code=400)
    if status == "needs_clarification":
        raise ApiError(
            "This dispatch opportunity is waiting on driver clarification and must be resubmitted before approval.",
            status_code=409,
        )
    if status == "approved":
        raise ApiError("This dispatch opportunity has already been approved.", status_code=409)
    if status == "rejected":
        raise ApiError("Rejected dispatch opportunities cannot be approved.", status_code=409)
    if status == "withdrawn":
        raise ApiError("Withdrawn dispatch opportunities cannot be approved.", status_code=409)
    if status == "converted_to_dispatch_request":
        raise ApiError("This dispatch opportunity has already been converted to a dispatch request.", status_code=409)
    raise ApiError("This dispatch opportunity cannot be approved.", status_code=400)


def _raise_conversion_state_error(document: dict):
    status = document.get("status")
    if status == "converted_to_dispatch_request":
        request_id = document.get("dispatch_request_id")
        message = "This dispatch opportunity has already been converted to a dispatch request."
        if request_id:
            message = f"This dispatch opportunity has already been converted to dispatch request {request_id}."
        raise ApiError(message, status_code=409)
    if status == "approved":
        raise ApiError("This dispatch opportunity cannot be converted right now.", status_code=400)
    if status == "draft":
        raise ApiError("This dispatch opportunity must be approved before it can be converted.", status_code=400)
    if status == "submitted":
        raise ApiError("Approve this dispatch opportunity before converting it to a dispatch request.", status_code=409)
    if status == "under_review":
        raise ApiError("This dispatch opportunity is still under review and must be approved before conversion.", status_code=409)
    if status == "needs_clarification":
        raise ApiError("This dispatch opportunity needs clarification before it can be approved and converted.", status_code=409)
    if status == "rejected":
        raise ApiError("Rejected dispatch opportunities cannot be converted.", status_code=409)
    if status == "withdrawn":
        raise ApiError("Withdrawn dispatch opportunities cannot be converted.", status_code=409)
    raise ApiError("Only approved opportunities can be converted to dispatch requests.", status_code=400)


def list_dispatch_opportunity_options(*, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    if normalized_role not in ADMIN_REVIEW_ROLES | {"driver"}:
        raise ApiError("You do not have permission to access dispatch opportunity options.", status_code=403)
    cache_key = build_cache_key("dispatch_opportunities:options", role=normalized_role)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    started_at = perf_counter()
    payload = {
        "pickup_locations": [item["name"] for item in get_active_master_data_items("dispatch_pickup_locations")],
        "vehicle_types": [item["name"] for item in get_active_master_data_items("dispatch_vehicle_types")],
        "load_types": [item["name"] for item in get_active_master_data_items("dispatch_load_types")],
        "load_weight_categories": [item["name"] for item in get_active_master_data_items("dispatch_load_weight_categories")],
        "load_size_categories": [item["name"] for item in get_active_master_data_items("dispatch_load_size_categories")],
        "payment_statuses": [item["name"] for item in get_active_master_data_items("dispatch_payment_statuses")],
        "trip_purposes": sorted(TRIP_PURPOSES),
        "dispatch_classifications": sorted(DISPATCH_CLASSIFICATIONS),
        "statuses": sorted(ALLOWED_OPPORTUNITY_STATUSES),
        "driver_editable_statuses": sorted(DRIVER_MUTABLE_STATUSES),
    }
    log_db_duration("dispatch_opportunities.options.master_data", started_at)
    return set_ttl_cached(cache_key, payload, ttl_seconds=30)


def list_dispatch_opportunities(
    *,
    current_user_id: str,
    current_role: str,
    page: int = 1,
    page_size: int = 20,
    search_query: str | None = None,
    status: str | None = None,
    driver_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    request_started_at = perf_counter()
    query: dict = {}

    if normalized_role == "driver":
        query["submitted_by_driver_id"] = _to_object_id(current_user_id, "current_user_id")
    elif normalized_role in ADMIN_REVIEW_ROLES:
        if driver_id:
            query["submitted_by_driver_id"] = _to_object_id(driver_id, "driver_id")
    else:
        raise ApiError("You do not have permission to access dispatch opportunities.", status_code=403)

    if status:
        query["status"] = _validate_status(status)

    normalized_search_query = _normalize_text(search_query)
    if normalized_search_query:
        escaped = re.escape(normalized_search_query)
        query["$or"] = [
            {"opportunity_id": {"$regex": escaped, "$options": "i"}},
            {"customer_name": {"$regex": escaped, "$options": "i"}},
            {"customer_phone": {"$regex": escaped, "$options": "i"}},
            {"pickup_location": {"$regex": escaped, "$options": "i"}},
            {"destination": {"$regex": escaped, "$options": "i"}},
        ]

    created_at_filter = {}
    if date_from:
        created_at_filter["$gte"] = datetime.fromisoformat(f"{_parse_date(date_from, 'date_from', required=True)}T00:00:00").replace(tzinfo=timezone.utc)
    if date_to:
        created_at_filter["$lte"] = datetime.fromisoformat(f"{_parse_date(date_to, 'date_to', required=True)}T23:59:59").replace(tzinfo=timezone.utc)
    if created_at_filter:
        query["created_at"] = created_at_filter

    normalized_page = max(page or 1, 1)
    normalized_page_size = min(max(page_size or 20, 1), 100)
    skip = (normalized_page - 1) * normalized_page_size

    aggregate_started_at = perf_counter()
    pipeline = [
        {"$match": query},
        {
            "$facet": {
                "records": [
                    {"$sort": {"created_at": -1, "_id": -1}},
                    {"$skip": skip},
                    {"$limit": normalized_page_size},
                    {"$project": LIST_PROJECTION},
                ],
                "counts": [{"$count": "total"}],
            }
        },
    ]
    aggregate_result = list(dispatch_opportunities_collection().aggregate(pipeline))
    log_db_duration("dispatch_opportunities.list.aggregate", aggregate_started_at)
    aggregate_payload = aggregate_result[0] if aggregate_result else {}
    documents = aggregate_payload.get("records") or []
    total = int(((aggregate_payload.get("counts") or [{}])[0]).get("total") or 0)
    opportunities = _batch_enrich_dispatch_opportunities(documents)

    return {
        "opportunities": opportunities,
        "pagination": {
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total": total,
            "total_pages": max(1, ceil(total / normalized_page_size)) if normalized_page_size else 1,
        },
        "filters": {
            "q": search_query,
            "status": status,
            "driver_id": driver_id,
            "date_from": date_from,
            "date_to": date_to,
        },
        "generated_at": now_utc().isoformat(),
        "duration_ms": round((perf_counter() - request_started_at) * 1000, 2),
    }


def get_dispatch_opportunity_by_id(opportunity_id: str, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    document = _get_dispatch_opportunity_document(opportunity_id, projection=DETAIL_PROJECTION)
    if normalized_role == "driver":
        _assert_driver_access(document, current_user_id=current_user_id)
    elif normalized_role not in ADMIN_REVIEW_ROLES:
        raise ApiError("You do not have permission to access dispatch opportunities.", status_code=403)
    return _batch_enrich_dispatch_opportunities([document])[0]


def create_driver_dispatch_opportunity(payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_driver_role(normalized_role)
    _get_driver_document(current_user_id)
    normalized_payload = _normalize_dispatch_opportunity_payload(payload or {}, partial=False)
    requested_status = _validate_status((payload or {}).get("status"))
    if requested_status not in {"draft", "submitted"}:
        raise ApiError("Drivers can only create dispatch opportunities as draft or submitted.", status_code=400)
    timestamp = now_utc()
    document = {
        **normalized_payload,
        "opportunity_id": _generate_opportunity_id(),
        "status": requested_status,
        "review_notes": None,
        "clarification_request": None,
        "rejection_reason": None,
        "withdrawal_reason": None,
        "submitted_by_driver_id": _to_object_id(current_user_id, "current_user_id"),
        "reviewed_by": None,
        "approved_by": None,
        "rejected_by": None,
        "withdrawn_by": None,
        "converted_by": None,
        "submitted_at": timestamp if requested_status == "submitted" else None,
        "reviewed_at": None,
        "approved_at": None,
        "rejected_at": None,
        "withdrawn_at": None,
        "converted_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if requested_status == "submitted":
        _validate_complete_opportunity(document)
    result = dispatch_opportunities_collection().insert_one(document)
    document["_id"] = result.inserted_id
    if requested_status == "submitted":
        notify_roles(
            ["owner", "admin", "dispatcher", "customer_service"],
            title="New dispatch opportunity submitted",
            message=f"Driver submitted {document.get('opportunity_id')} for review.",
            category="dispatch_opportunity_submitted",
            priority="medium",
            reference_type="dispatch_opportunity",
            reference_id=document["_id"],
            action_type="review_opportunity",
            action_url="dispatch-opportunities",
            action_label="Review opportunity",
        )
    return _batch_enrich_dispatch_opportunities([document])[0]


def update_driver_dispatch_opportunity(opportunity_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_driver_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    _assert_driver_access(document, current_user_id=current_user_id)
    if document.get("status") not in DRIVER_MUTABLE_STATUSES:
        raise ApiError("This dispatch opportunity can no longer be edited by the driver.", status_code=403)

    filtered_payload = {key: value for key, value in (payload or {}).items() if key in DRIVER_EDITABLE_FIELDS}
    if not filtered_payload:
        raise ApiError("No valid dispatch opportunity fields provided for update.", status_code=400)

    normalized_payload = _normalize_dispatch_opportunity_payload(filtered_payload, partial=True)
    next_status = normalized_payload.get("status")
    if next_status is not None:
        next_status = _validate_status(next_status)
        if next_status not in {"draft", "submitted"}:
            raise ApiError("Drivers can only save as draft or submit for review.", status_code=400)
        normalized_payload["status"] = next_status

    merged_document = {**document, **normalized_payload}
    if merged_document.get("status") == "submitted":
        _validate_complete_opportunity(merged_document)

    timestamp = now_utc()
    update_fields = {**normalized_payload, "updated_at": timestamp}
    if merged_document.get("status") == "submitted":
        update_fields["submitted_at"] = timestamp
        update_fields["clarification_request"] = None
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    if merged_document.get("status") == "submitted":
        resolve_action_notifications("dispatch_opportunity", document["_id"], action_type="clarify_opportunity", completed_by=current_user_id)
    return _batch_enrich_dispatch_opportunities([document])[0]


def submit_driver_dispatch_opportunity(opportunity_id: str, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_driver_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    _assert_driver_access(document, current_user_id=current_user_id)
    if document.get("status") not in {"draft", "needs_clarification"}:
        raise ApiError("Only draft or clarification-needed opportunities can be submitted.", status_code=400)
    _validate_complete_opportunity(document)
    timestamp = now_utc()
    update_fields = {
        "status": "submitted",
        "submitted_at": timestamp,
        "updated_at": timestamp,
        "clarification_request": None,
    }
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    notify_roles(
        ["owner", "admin", "dispatcher", "customer_service"],
        title="Dispatch opportunity submitted",
        message=f"Driver submitted {document.get('opportunity_id')} for review.",
        category="dispatch_opportunity_submitted",
        priority="medium",
        reference_type="dispatch_opportunity",
        reference_id=document["_id"],
        action_type="review_opportunity",
        action_url="dispatch-opportunities",
        action_label="Review opportunity",
    )
    return _batch_enrich_dispatch_opportunities([document])[0]


def withdraw_driver_dispatch_opportunity(opportunity_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_driver_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    _assert_driver_access(document, current_user_id=current_user_id)
    if document.get("status") not in DRIVER_WITHDRAWABLE_STATUSES:
        raise ApiError("This dispatch opportunity can no longer be withdrawn.", status_code=400)
    timestamp = now_utc()
    update_fields = {
        "status": "withdrawn",
        "withdrawal_reason": _normalize_text((payload or {}).get("withdrawal_reason")),
        "withdrawn_by": _to_object_id(current_user_id, "current_user_id"),
        "withdrawn_at": timestamp,
        "updated_at": timestamp,
    }
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    resolve_action_notifications("dispatch_opportunity", document["_id"], action_type="clarify_opportunity", completed_by=current_user_id)
    return _batch_enrich_dispatch_opportunities([document])[0]


def review_dispatch_opportunity(opportunity_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_review_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    if document.get("status") not in ADMIN_REVIEWABLE_STATUSES:
        _raise_review_state_error(document)
    normalized_payload = _normalize_dispatch_opportunity_payload(payload or {}, partial=True)
    timestamp = now_utc()
    update_fields = {
        key: value
        for key, value in normalized_payload.items()
        if key in {"proposed_charge", "approved_charge", "review_notes", "payment_status", "dispatch_classification", "complimentary_reason", "contribution_amount", "contribution_purpose", "contribution_payment_method"}
    }
    update_fields["status"] = "under_review" if document.get("status") == "submitted" else document.get("status")
    update_fields["reviewed_by"] = _to_object_id(current_user_id, "current_user_id")
    update_fields["reviewed_at"] = timestamp
    update_fields["updated_at"] = timestamp
    if document.get("status") == "submitted":
        update_fields["clarification_request"] = None
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _batch_enrich_dispatch_opportunities([document])[0]


def request_dispatch_opportunity_clarification(opportunity_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_review_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    if document.get("status") not in ADMIN_CLARIFICATION_STATUSES:
        raise ApiError("Clarification can only be requested on pending opportunities.", status_code=400)
    clarification_request = _normalize_text((payload or {}).get("clarification_request"))
    if not clarification_request:
        raise ApiError("clarification_request is required.", status_code=400)
    normalized_payload = _normalize_dispatch_opportunity_payload(payload or {}, partial=True)
    timestamp = now_utc()
    classification = merged_document.get("dispatch_classification") or "COMMERCIAL"
    approved_charge = merged_document.get("approved_charge") if merged_document.get("approved_charge") is not None else merged_document.get("proposed_charge")
    if classification != "COMMERCIAL":
        approved_charge = 0.0
    update_fields = {
        key: value
        for key, value in normalized_payload.items()
        if key in {"proposed_charge", "approved_charge", "review_notes", "payment_status"}
    }
    update_fields.update(
        {
            "status": "needs_clarification",
            "clarification_request": clarification_request,
            "reviewed_by": _to_object_id(current_user_id, "current_user_id"),
            "reviewed_at": timestamp,
            "updated_at": timestamp,
        }
    )
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    resolve_action_notifications("dispatch_opportunity", document["_id"], action_type="review_opportunity", completed_by=current_user_id)
    if isinstance(document.get("submitted_by_driver_id"), ObjectId):
        create_notification(
            recipient_user_id=document["submitted_by_driver_id"],
            title="Dispatch opportunity needs clarification",
            message=f"{document.get('opportunity_id')} needs clarification before approval.",
            category="dispatch_opportunity_clarification",
            priority="medium",
            reference_type="dispatch_opportunity",
            reference_id=document["_id"],
            action_type="clarify_opportunity",
            action_url="my-dispatch-opportunities",
            action_label="Provide clarification",
        )
    return _batch_enrich_dispatch_opportunities([document])[0]


def approve_dispatch_opportunity(opportunity_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_review_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    if document.get("status") not in ADMIN_APPROVABLE_STATUSES:
        _raise_approval_state_error(document)
    merged_document = {**document, **_normalize_dispatch_opportunity_payload(payload or {}, partial=True)}
    _validate_complete_opportunity(merged_document)
    timestamp = now_utc()
    update_fields = {
        "status": "approved",
        "proposed_charge": merged_document.get("proposed_charge"),
        "approved_charge": approved_charge,
        "dispatch_classification": classification,
        "complimentary_reason": merged_document.get("complimentary_reason"),
        "contribution_amount": merged_document.get("contribution_amount"),
        "contribution_purpose": merged_document.get("contribution_purpose"),
        "contribution_payment_method": merged_document.get("contribution_payment_method"),
        "contribution_collected_by": _to_object_id(current_user_id, "current_user_id") if classification == "COST_CONTRIBUTION" and merged_document.get("contribution_payment_method") else None,
        "contribution_reconciliation_status": "pending" if classification == "COST_CONTRIBUTION" else None,
        "payment_status": merged_document.get("payment_status"),
        "review_notes": merged_document.get("review_notes"),
        "reviewed_by": _to_object_id(current_user_id, "current_user_id"),
        "approved_by": _to_object_id(current_user_id, "current_user_id"),
        "reviewed_at": timestamp,
        "approved_at": timestamp,
        "updated_at": timestamp,
        "clarification_request": None,
    }
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    resolve_action_notifications("dispatch_opportunity", document["_id"], action_type="review_opportunity", completed_by=current_user_id)
    if isinstance(document.get("submitted_by_driver_id"), ObjectId):
        create_notification(
            recipient_user_id=document["submitted_by_driver_id"],
            title="Dispatch opportunity approved",
            message=f"{document.get('opportunity_id')} has been approved for conversion.",
            category="dispatch_opportunity_approved",
            priority="medium",
            reference_type="dispatch_opportunity",
            reference_id=document["_id"],
        )
    return _batch_enrich_dispatch_opportunities([document])[0]


def reject_dispatch_opportunity(opportunity_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_review_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    if document.get("status") in {"converted_to_dispatch_request", "withdrawn"}:
        raise ApiError("This dispatch opportunity can no longer be rejected.", status_code=400)
    rejection_reason = _normalize_text((payload or {}).get("rejection_reason"))
    if not rejection_reason:
        raise ApiError("rejection_reason is required.", status_code=400)
    normalized_payload = _normalize_dispatch_opportunity_payload(payload or {}, partial=True)
    timestamp = now_utc()
    update_fields = {
        key: value
        for key, value in normalized_payload.items()
        if key in {"proposed_charge", "approved_charge", "review_notes", "payment_status"}
    }
    update_fields.update(
        {
            "status": "rejected",
            "rejection_reason": rejection_reason,
            "reviewed_by": _to_object_id(current_user_id, "current_user_id"),
            "rejected_by": _to_object_id(current_user_id, "current_user_id"),
            "reviewed_at": timestamp,
            "rejected_at": timestamp,
            "updated_at": timestamp,
        }
    )
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    resolve_action_notifications("dispatch_opportunity", document["_id"], action_type="review_opportunity", resolution="cancelled", completed_by=current_user_id)
    if isinstance(document.get("submitted_by_driver_id"), ObjectId):
        create_notification(
            recipient_user_id=document["submitted_by_driver_id"],
            title="Dispatch opportunity rejected",
            message=f"{document.get('opportunity_id')} was rejected. Review the rejection reason in your portal.",
            category="dispatch_opportunity_rejected",
            priority="high",
            reference_type="dispatch_opportunity",
            reference_id=document["_id"],
        )
    return _batch_enrich_dispatch_opportunities([document])[0]


def convert_dispatch_opportunity_to_request(opportunity_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    normalized_role = _normalize_role(current_role) or current_role
    _assert_admin_review_role(normalized_role)
    document = _get_dispatch_opportunity_document(opportunity_id)
    existing_request = _load_existing_converted_request(document)
    if document.get("status") == "converted_to_dispatch_request":
        _raise_conversion_state_error(document)
    if document.get("status") not in ADMIN_CONVERTIBLE_STATUSES and existing_request is None:
        _raise_conversion_state_error(document)

    timestamp = now_utc()
    if existing_request is None:
        review_note = _normalize_text((payload or {}).get("review_notes"))
        if review_note:
            dispatch_opportunities_collection().update_one(
                {"_id": document["_id"]},
                {"$set": {"review_notes": review_note, "updated_at": timestamp}},
            )
            document["review_notes"] = review_note
            document["updated_at"] = timestamp
        from services.dispatch_request_service import create_dispatch_request_from_opportunity

        existing_request = create_dispatch_request_from_opportunity(
            document,
            current_user_id=current_user_id,
            current_role=current_role,
        )

    update_fields = {
        "status": "converted_to_dispatch_request",
        "dispatch_request_id": existing_request.get("request_id"),
        "dispatch_request_record_id": _to_object_id(existing_request.get("id"), "dispatch_request_id"),
        "converted_by": _to_object_id(current_user_id, "current_user_id"),
        "converted_at": document.get("converted_at") or timestamp,
        "updated_at": timestamp,
    }
    dispatch_opportunities_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    if isinstance(document.get("submitted_by_driver_id"), ObjectId):
        create_notification(
            recipient_user_id=document["submitted_by_driver_id"],
            title="Dispatch opportunity converted",
            message=f"{document.get('opportunity_id')} is now an official dispatch request.",
            category="dispatch_opportunity_converted",
            priority="medium",
            reference_type="dispatch_opportunity",
            reference_id=document["_id"],
        )
    return {
        "opportunity": _batch_enrich_dispatch_opportunities([document])[0],
        "dispatch_request": existing_request,
    }
