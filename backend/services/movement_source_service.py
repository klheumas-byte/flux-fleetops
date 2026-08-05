from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from utils.api_error import ApiError
from utils.operational_request_types import PERSONAL_USE_TYPE, normalize_type_token


SOURCE_MOVEMENT_OWNERSHIP = {
    "customer_dispatch": {
        "source_type": "dispatch_job",
        "owning_module": "dispatch",
        "source_module": "dispatch",
    },
    "assignment_handover": {
        "source_type": "assignment_handover",
        "owning_module": "assignments",
        "source_module": "assignments",
    },
    "maintenance_transport": {
        "source_type": "maintenance_job",
        "owning_module": "maintenance",
        "source_module": "maintenance",
    },
    "workshop_transport": {
        "source_type": "maintenance_job",
        "owning_module": "maintenance",
        "source_module": "maintenance",
    },
    "stock_transfer": {
        "source_type": "stock_transfer",
        "owning_module": "stock_transfers",
        "source_module": "inventory",
    },
    "supplier_pickup": {
        "source_type": "supplier_pickup",
        "owning_module": "supplier_pickups",
        "source_module": "inventory",
    },
    "stock_return": {
        "source_type": "delivery_return_request",
        "owning_module": "stock_transfers",
        "source_module": "inventory",
    },
    "internal_company_delivery": {
        "source_type": "vehicle_operation_request",
        "owning_module": "operational_requests",
        "source_module": "operational_requests",
    },
    "fuel_station_visit": {
        "source_type": "vehicle_operation_request",
        "owning_module": "operational_requests",
        "source_module": "operational_requests",
    },
    "compliance_inspection_visit": {
        "source_type": "vehicle_operation_request",
        "owning_module": "operational_requests",
        "source_module": "operational_requests",
    },
    "administrative_errand": {
        "source_type": "vehicle_operation_request",
        "owning_module": "operational_requests",
        "source_module": "operational_requests",
    },
    "vehicle_repositioning": {
        "source_type": "vehicle_operation_request",
        "owning_module": "operational_requests",
        "source_module": "operational_requests",
    },
    PERSONAL_USE_TYPE: {
        "source_type": "vehicle_operation_request",
        "owning_module": "operational_requests",
        "source_module": "personal_vehicle_use",
    },
}
SOURCE_MANAGED_MOVEMENT_TYPES = frozenset(SOURCE_MOVEMENT_OWNERSHIP)
SUPPORTED_SOURCE_TYPES = frozenset(
    rule["source_type"] for rule in SOURCE_MOVEMENT_OWNERSHIP.values()
)
SOURCE_MODULES = {
    rule["source_type"]: rule["source_module"]
    for rule in SOURCE_MOVEMENT_OWNERSHIP.values()
}
SOURCE_OWNERSHIP_FIELDS = frozenset(
    {"source_type", "source_id", "source_key", "source_module", "source_reference"}
)


def get_movement_source_ownership(movement_type: str | None) -> dict | None:
    normalized_type = normalize_type_token(movement_type)
    rule = SOURCE_MOVEMENT_OWNERSHIP.get(normalized_type)
    return dict(rule) if rule else None


def source_ownership_error(
    movement_type: str | None,
    *,
    code: str,
    message: str,
    status_code: int,
) -> ApiError:
    normalized_type = str(movement_type or "").strip().lower() or None
    rule = get_movement_source_ownership(normalized_type)
    return ApiError(
        message,
        status_code=status_code,
        errors=[
            {
                "code": code,
                "message": message,
                "movement_type": normalized_type,
                "owning_module": rule["owning_module"] if rule else None,
            }
        ],
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def vehicle_movements_collection():
    return get_collection("vehicle_movements")


def dispatch_jobs_collection():
    return get_collection("dispatch_jobs")


def build_source_key(source_type: str, source_record_id: str | ObjectId) -> str:
    normalized_type = str(source_type or "").strip().lower()
    normalized_id = str(source_record_id or "").strip()
    if normalized_type not in SUPPORTED_SOURCE_TYPES:
        raise ApiError("Unsupported vehicle movement source type.", status_code=400)
    if not normalized_id:
        raise ApiError("source_record_id is required.", status_code=400)
    return f"{normalized_type}:{normalized_id}"


def _source_id(value: str | ObjectId):
    if isinstance(value, ObjectId):
        return value
    return ObjectId(value) if ObjectId.is_valid(str(value)) else str(value)


def _source_fields(
    *,
    source_type: str,
    source_record_id: str | ObjectId,
    source_reference: str | None,
) -> dict:
    return {
        "source_type": source_type,
        "source_id": _source_id(source_record_id),
        "source_key": build_source_key(source_type, source_record_id),
        "source_module": SOURCE_MODULES[source_type],
        "source_reference": str(source_reference).strip() if source_reference else None,
    }


def _attach_source_traceability(movement: dict, source_fields: dict) -> dict:
    existing_key = movement.get("source_key")
    if existing_key and existing_key != source_fields["source_key"]:
        raise ApiError(
            "Vehicle movement is already linked to a different source.",
            status_code=409,
        )
    missing_fields = {
        key: value
        for key, value in source_fields.items()
        if movement.get(key) is None and value is not None
    }
    if missing_fields:
        try:
            vehicle_movements_collection().update_one(
                {
                    "_id": movement["_id"],
                    "$or": [
                        {"source_key": source_fields["source_key"]},
                        {"source_key": None},
                        {"source_key": {"$exists": False}},
                    ],
                },
                {"$set": {**missing_fields, "updated_at": now_utc()}},
            )
        except DuplicateKeyError:
            winner = vehicle_movements_collection().find_one({"source_key": source_fields["source_key"]})
            if winner:
                return winner
            raise ApiError("Vehicle movement source is already linked.", status_code=409) from None
        movement.update(missing_fields)
    return movement


def ensure_movement_for_source(
    *,
    source_type: str,
    source_record_id: str | ObjectId,
    movement_defaults: dict,
    source_reference: str | None = None,
    existing_movement: dict | None = None,
    legacy_query: dict | None = None,
) -> dict:
    """Return one movement for a source, creating it atomically when absent.

    The result shape is stable for all source modules:
    ``{"movement": document, "created": bool, "source_key": str}``.
    """

    normalized_type = str(source_type or "").strip().lower()
    movement_type = str(movement_defaults.get("movement_type") or "").strip().lower()
    ownership = get_movement_source_ownership(movement_type)
    if ownership is None or ownership["source_type"] != normalized_type:
        raise source_ownership_error(
            movement_type,
            code="invalid_movement_source_owner",
            message="Vehicle movement type is not owned by this source workflow.",
            status_code=409,
        )
    source_fields = _source_fields(
        source_type=normalized_type,
        source_record_id=source_record_id,
        source_reference=source_reference,
    )

    movement = existing_movement
    if movement is None:
        movement = vehicle_movements_collection().find_one(
            {"source_key": source_fields["source_key"]}
        )
    if movement is None and legacy_query:
        movement = vehicle_movements_collection().find_one(legacy_query)
    if movement is not None:
        movement = _attach_source_traceability(movement, source_fields)
        return {
            "movement": movement,
            "created": False,
            "source_key": source_fields["source_key"],
        }

    timestamp = now_utc()
    document = {
        **movement_defaults,
        **source_fields,
        "movement_id": movement_defaults.get("movement_id")
        or f"VM-{timestamp.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6].upper()}",
        "created_at": movement_defaults.get("created_at") or timestamp,
        "updated_at": timestamp,
    }
    try:
        document["_id"] = vehicle_movements_collection().insert_one(document).inserted_id
        return {
            "movement": document,
            "created": True,
            "source_key": source_fields["source_key"],
        }
    except DuplicateKeyError:
        winner = vehicle_movements_collection().find_one(
            {"source_key": source_fields["source_key"]}
        )
        if winner is None and legacy_query:
            winner = vehicle_movements_collection().find_one(legacy_query)
        if winner is None:
            raise ApiError(
                "Vehicle already has another open movement.",
                status_code=409,
            ) from None
        winner = _attach_source_traceability(winner, source_fields)
        return {
            "movement": winner,
            "created": False,
            "source_key": source_fields["source_key"],
        }


def build_dispatch_movement_defaults(
    job_document: dict,
    *,
    current_user_id: str | ObjectId,
    initial_status: str,
    departure_at: datetime | None = None,
) -> dict:
    if not isinstance(job_document.get("_id"), ObjectId):
        raise ApiError("Invalid dispatch job.", status_code=400)
    if not isinstance(job_document.get("vehicle_id"), ObjectId):
        raise ApiError("This dispatch job does not have an assigned vehicle.", status_code=400)
    if initial_status not in {"approved", "in_progress"}:
        raise ApiError("Invalid initial dispatch movement status.", status_code=400)

    actor_id = (
        current_user_id
        if isinstance(current_user_id, ObjectId)
        else ObjectId(current_user_id)
        if ObjectId.is_valid(str(current_user_id))
        else None
    )
    if actor_id is None:
        raise ApiError("Invalid user identity.", status_code=400)

    timestamp = now_utc()
    actual_departure = (
        departure_at
        or job_document.get("actual_departure_at")
        or job_document.get("started_at")
    )
    started = initial_status == "in_progress"
    financial_type = str(job_document.get("dispatch_financial_type") or "external_paid").lower()
    movement_category = {
        "external_paid": "COMMERCIAL_DISPATCH",
        "complimentary": "COMPLIMENTARY_DISPATCH",
        "cost_contribution": "COST_CONTRIBUTION_DISPATCH",
    }.get(financial_type, "COMMERCIAL_DISPATCH")
    return {
        "vehicle_id": job_document["vehicle_id"],
        "driver_id": job_document.get("driver_id"),
        "movement_custodian_id": job_document.get("driver_id"),
        "assignment_id": job_document.get("primary_assignment_id"),
        "primary_assignment_id": job_document.get("primary_assignment_id"),
        "dispatch_job_id": job_document["_id"],
        "dispatch_request_id": job_document.get("dispatch_request_id"),
        "reservation_id": job_document.get("vehicle_reservation_id"),
        "movement_type": "customer_dispatch",
        "movement_category": movement_category,
        "status": initial_status,
        "requested_departure_time": job_document.get("scheduled_start_time"),
        "actual_departure_at": actual_departure if started else None,
        "departure_time": actual_departure if started else None,
        "expected_return_time": job_document.get("expected_return_time"),
        "actual_return_at": None,
        "actual_return_time": None,
        "origin": job_document.get("pickup"),
        "destination": job_document.get("destination"),
        "purpose": job_document.get("dispatch_job_id"),
        "opening_odometer": None,
        "closing_odometer": None,
        "opening_fuel_level": None,
        "closing_fuel_level": None,
        "delivery_status": (
            "delivered"
            if job_document.get("driver_workflow_status") == "delivered"
            else "pending"
        ),
        "delivered_at": None,
        "delivery_note": None,
        "delivered_by": None,
        "notes": job_document.get("dispatch_instructions"),
        "cancellation_reason": None,
        "approved_by": actor_id,
        "approved_at": timestamp,
        "checked_out_by": actor_id if started else None,
        "checked_out_at": actual_departure or timestamp if started else None,
        "returned_by": None,
        "returned_at": None,
        "closed_by": None,
        "closed_at": None,
        "return_checklist": None,
        "created_by": actor_id,
        "created_at": timestamp,
    }


def ensure_dispatch_movement(
    job_document: dict,
    *,
    current_user_id: str | ObjectId,
    initial_status: str = "approved",
    departure_at: datetime | None = None,
) -> dict:
    linked_movement = None
    linked_id = job_document.get("linked_vehicle_movement_id")
    if isinstance(linked_id, ObjectId):
        linked_movement = vehicle_movements_collection().find_one({"_id": linked_id})
    if linked_movement:
        if linked_movement.get("dispatch_job_id") not in (None, job_document["_id"]):
            raise ApiError(
                "Linked vehicle movement belongs to a different dispatch job.",
                status_code=409,
            )
        if linked_movement.get("vehicle_id") != job_document.get("vehicle_id"):
            raise ApiError(
                "Linked vehicle movement belongs to a different vehicle.",
                status_code=409,
            )

    result = ensure_movement_for_source(
        source_type="dispatch_job",
        source_record_id=job_document["_id"],
        source_reference=job_document.get("dispatch_job_id"),
        movement_defaults=build_dispatch_movement_defaults(
            job_document,
            current_user_id=current_user_id,
            initial_status=initial_status,
            departure_at=departure_at,
        ),
        existing_movement=linked_movement,
        legacy_query={"dispatch_job_id": job_document["_id"]},
    )
    movement = result["movement"]
    if movement.get("dispatch_job_id") not in (None, job_document["_id"]):
        raise ApiError(
            "Vehicle movement belongs to a different dispatch job.",
            status_code=409,
        )
    if movement.get("vehicle_id") != job_document.get("vehicle_id"):
        raise ApiError(
            "Vehicle movement belongs to a different dispatch vehicle.",
            status_code=409,
        )
    if movement.get("status") in {"draft", "pending_approval", "approved"}:
        sync_fields = {
            "dispatch_job_id": job_document["_id"],
            "dispatch_request_id": job_document.get("dispatch_request_id"),
            "reservation_id": job_document.get("vehicle_reservation_id"),
            "driver_id": job_document.get("driver_id"),
            "assignment_id": job_document.get("primary_assignment_id"),
            "primary_assignment_id": job_document.get("primary_assignment_id"),
            "requested_departure_time": job_document.get("scheduled_start_time"),
            "expected_return_time": job_document.get("expected_return_time"),
            "origin": job_document.get("pickup"),
            "destination": job_document.get("destination"),
            "purpose": job_document.get("dispatch_job_id"),
            "updated_at": now_utc(),
        }
        if any(movement.get(key) != value for key, value in sync_fields.items() if key != "updated_at"):
            vehicle_movements_collection().update_one(
                {"_id": movement["_id"]},
                {"$set": sync_fields},
            )
            movement.update(sync_fields)
    if job_document.get("linked_vehicle_movement_id") != movement["_id"]:
        dispatch_jobs_collection().update_one(
            {"_id": job_document["_id"]},
            {"$set": {"linked_vehicle_movement_id": movement["_id"], "updated_at": now_utc()}},
        )
        job_document["linked_vehicle_movement_id"] = movement["_id"]
    from services.waybill_service import ensure_waybill_for_source

    waybill_result = ensure_waybill_for_source(
        source_type="dispatch_job",
        source_document=job_document,
        movement_document=movement,
        current_user_id=current_user_id,
        collection=get_collection("waybills"),
    )
    waybill = waybill_result["waybill"]
    if job_document.get("linked_waybill_id") != waybill["_id"]:
        dispatch_jobs_collection().update_one(
            {"_id": job_document["_id"]},
            {"$set": {"linked_waybill_id": waybill["_id"], "updated_at": now_utc()}},
        )
        job_document["linked_waybill_id"] = waybill["_id"]
    result["waybill"] = waybill
    return result
