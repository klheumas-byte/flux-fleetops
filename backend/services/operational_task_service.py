from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId

from extensions import get_collection
from utils.api_error import ApiError


TRANSFER_ACTIVE_STATUSES = ["scheduled", "released", "in_transit", "awaiting_receipt"]
REQUEST_ACTIVE_STATUSES = ["scheduled", "movement_in_progress", "awaiting_verification"]
DELIVERY_ACTIVE_STATUSES = ["scheduled", "awaiting_issue", "issued", "accepted", "in_progress", "returning", "awaiting_reconciliation"]

TRANSFER_PROJECTION = {
    "transfer_id": 1,
    "operation_type": 1,
    "supplier": 1,
    "sending_location": 1,
    "receiving_location": 1,
    "vehicle_id": 1,
    "driver_id": 1,
    "scheduled_at": 1,
    "status": 1,
    "acknowledged_at": 1,
    "supplier_arrived_at": 1,
    "pickup_confirmation": 1,
    "actual_receiver": 1,
    "linked_delivery_exception_id": 1,
    "linked_waybill_id": 1,
    "updated_at": 1,
}

REQUEST_PROJECTION = {
    "request_id": 1,
    "operation_type": 1,
    "title": 1,
    "origin": 1,
    "destination": 1,
    "vehicle_id": 1,
    "driver_id": 1,
    "planned_departure_at": 1,
    "status": 1,
    "acknowledged_at": 1,
    "opening_check_completed_at": 1,
    "receiver_confirmation": 1,
    "task_confirmation": 1,
    "destination_acceptance": 1,
    "updated_at": 1,
}


def _driver_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(str(value)):
        raise ApiError("Invalid driver identity.", status_code=400)
    return ObjectId(str(value))


def _value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, dict):
        return {str(key): _value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return fallback


def _object_id_or_none(value):
    if isinstance(value, ObjectId):
        return value
    if value is not None and ObjectId.is_valid(str(value)):
        return ObjectId(str(value))
    return None


def _label(value: str) -> str:
    return str(value or "").replace("_", " ").title()


def _transfer_action(document: dict) -> dict:
    supplier_pickup = document.get("operation_type") == "supplier_pickup"
    status = document.get("status")
    if status == "scheduled" and not document.get("acknowledged_at"):
        return {"key": "acknowledge", "label": "Accept Pickup" if supplier_pickup else "Accept Transfer"}
    if supplier_pickup and status == "scheduled" and not document.get("supplier_arrived_at"):
        return {"key": "arrive", "label": "Arrive at Supplier"}
    if supplier_pickup and status == "scheduled" and not document.get("pickup_confirmation"):
        return {"key": "pickup_confirmation", "label": "Confirm Pickup"}
    if status == "scheduled":
        return {"key": "awaiting_release", "label": "Await Loading"}
    if status == "released":
        return {"key": "start", "label": "Start Journey"}
    if status == "in_transit":
        return {"key": "arrive", "label": "Mark Delivered"}
    if status == "awaiting_receipt" and document.get("linked_delivery_exception_id"):
        return {"key": "review_exception", "label": "Review Delivery Exception"}
    if status == "awaiting_receipt":
        return {"key": "confirm_delivery", "label": "Confirm Delivery"}
    return {"key": "view", "label": "View Task"}


def _request_action(document: dict) -> dict:
    status = document.get("status")
    if status == "scheduled" and not document.get("acknowledged_at"):
        return {"key": "acknowledge", "label": "Acknowledge"}
    if status == "scheduled" and not document.get("opening_check_completed_at"):
        return {"key": "opening_check", "label": "Opening Check"}
    if status == "scheduled":
        return {"key": "start", "label": "Start Movement"}
    if status == "movement_in_progress":
        evidence_fields = ("receiver_confirmation", "task_confirmation", "destination_acceptance")
        if not any(document.get(field) for field in evidence_fields):
            return {"key": "confirm_task", "label": "Confirm Task"}
        return {"key": "return", "label": "Return Vehicle"}
    return {"key": "awaiting_verification", "label": "Await Verification"}


def _vehicle_map(documents: list[dict]) -> dict:
    vehicle_ids = {
        _object_id_or_none(item.get("vehicle_id"))
        for item in documents
        if _object_id_or_none(item.get("vehicle_id")) is not None
    }
    if not vehicle_ids:
        return {}
    vehicles = get_collection("vehicles").find(
        {"_id": {"$in": list(vehicle_ids)}},
        {"registration_number": 1, "make": 1, "model": 1},
    )
    return {item["_id"]: item for item in vehicles}


def _vehicle_payload(document: dict, vehicles: dict):
    vehicle = vehicles.get(_object_id_or_none(document.get("vehicle_id")))
    if not vehicle:
        return None
    return {
        "id": str(vehicle["_id"]),
        "registration_number": _text(vehicle.get("registration_number")),
        "make": _text(vehicle.get("make")),
        "model": _text(vehicle.get("model")),
    }


def _transfer_summary(document: dict, vehicles: dict) -> dict:
    operation_type = (
        "supplier_pickup"
        if document.get("operation_type") == "supplier_pickup"
        else "stock_transfer"
    )
    supplier = _mapping(document.get("supplier"))
    origin = (
        _text(supplier.get("pickup_address")) or _text(document.get("sending_location"))
        if operation_type == "supplier_pickup"
        else _text(document.get("sending_location"))
    )
    status = _text(document.get("status"), "scheduled")
    return {
        "id": str(document["_id"]),
        "task_key": f"{operation_type}:{document['_id']}",
        "operation_type": operation_type,
        "operation_label": "Supplier Pickup" if operation_type == "supplier_pickup" else "Stock Transfer",
        "reference": _text(document.get("transfer_id"), str(document["_id"])),
        "title": _text(supplier.get("supplier_name"), "Supplier") if operation_type == "supplier_pickup" else "Stock Transfer",
        "schedule": _value(document.get("scheduled_at")),
        "origin": origin,
        "destination": _text(document.get("receiving_location")),
        "vehicle": _vehicle_payload(document, vehicles),
        "status": status,
        "status_label": _label(status),
        "current_action": _transfer_action(document),
        "linked_waybill_id": _value(document.get("linked_waybill_id")),
        "updated_at": _value(document.get("updated_at")),
    }


def _request_summary(document: dict, vehicles: dict) -> dict:
    status = _text(document.get("status"), "scheduled")
    subtype = _text(document.get("operation_type"), "operational_request")
    return {
        "id": str(document["_id"]),
        "task_key": f"operational_request:{document['_id']}",
        "operation_type": "operational_request",
        "operation_subtype": subtype,
        "operation_label": _label(subtype),
        "reference": _text(document.get("request_id"), str(document["_id"])),
        "title": _text(document.get("title")) or _label(subtype) or "Operational Request",
        "schedule": _value(document.get("planned_departure_at")),
        "origin": _text(document.get("origin")),
        "destination": _text(document.get("destination")),
        "vehicle": _vehicle_payload(document, vehicles),
        "status": status,
        "status_label": _label(status),
        "current_action": _request_action(document),
        "linked_waybill_id": None,
        "updated_at": _value(document.get("updated_at")),
    }


def _delivery_summary(document: dict, vehicles: dict) -> dict:
    status = _text(document.get("status"), "scheduled")
    action = {"scheduled": {"key":"view","label":"View Schedule"}, "awaiting_issue":{"key":"acknowledge","label":"Acknowledge Items"}, "issued":{"key":"accept","label":"Accept Batch"}, "accepted":{"key":"start","label":"Start Trip"}, "in_progress":{"key":"continue","label":"Continue Deliveries"}, "returning":{"key":"return","label":"Return Products"}, "awaiting_reconciliation":{"key":"view","label":"Await Reconciliation"}}.get(status,{"key":"view","label":"View Batch"})
    return {"id":str(document["_id"]),"task_key":f"smart_living_delivery:{document['_id']}","operation_type":"smart_living_delivery","operation_label":"Smart Living Delivery","reference":document.get("batch_number"),"title":f"{len(document.get('delivery_order_ids') or [])} customer delivery batch","schedule":document.get("delivery_date"),"origin":"Assigned branch","destination":"Delivery route","vehicle":_vehicle_payload(document,vehicles),"status":status,"status_label":_label(status),"current_action":action,"linked_waybill_id":None,"updated_at":_value(document.get("updated_at"))}


def _sort_value(task: dict) -> tuple:
    raw = task.get("schedule") or task.get("updated_at")
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return (0, parsed.timestamp())
    except (TypeError, ValueError, OverflowError, OSError):
        return (1, 0)


def list_driver_operational_tasks(current_user_id: str) -> dict:
    driver_id = _driver_id(current_user_id)
    driver_values = [driver_id, str(driver_id)]
    transfers = list(
        get_collection("stock_transfers").find(
            {"driver_id": {"$in": driver_values}, "status": {"$in": TRANSFER_ACTIVE_STATUSES}},
            TRANSFER_PROJECTION,
        )
    )
    requests = list(
        get_collection("vehicle_operation_requests").find(
            {"driver_id": {"$in": driver_values}, "status": {"$in": REQUEST_ACTIVE_STATUSES}},
            REQUEST_PROJECTION,
        )
    )
    deliveries = list(get_collection("delivery_batches").find({"driver_id":{"$in":driver_values},"status":{"$in":DELIVERY_ACTIVE_STATUSES}}))
    vehicles = _vehicle_map([*transfers, *requests, *deliveries])
    tasks = [_transfer_summary(item, vehicles) for item in transfers]
    tasks.extend(_request_summary(item, vehicles) for item in requests)
    tasks.extend(_delivery_summary(item, vehicles) for item in deliveries)

    # Source IDs are canonical task IDs, so retries or duplicate assignment records
    # cannot create a second queue entry.
    unique = {task["task_key"]: task for task in tasks}
    ordered = sorted(unique.values(), key=_sort_value)
    return {"tasks": ordered, "count": len(ordered)}


DISPATCH_ACTIVE_STATUSES = ["assigned", "accepted", "clarification_requested", "in_progress"]
DISPATCH_PROJECTION = {
    "dispatch_job_id": 1,
    "driver_id": 1,
    "status": 1,
    "driver_response_status": 1,
    "driver_workflow_status": 1,
    "is_paused": 1,
    "pickup": 1,
    "destination": 1,
    "scheduled_start_time": 1,
    "completed_at": 1,
    "updated_at": 1,
}
DASHBOARD_TRANSFER_PROJECTION = {
    **TRANSFER_PROJECTION,
    "completed_at": 1,
}
DASHBOARD_REQUEST_PROJECTION = {
    **REQUEST_PROJECTION,
    "verified_at": 1,
}


def _dispatch_action(document: dict) -> dict:
    status = document.get("status")
    response = document.get("driver_response_status")
    workflow = document.get("driver_workflow_status")
    if status == "assigned" and response == "pending":
        return {"key": "accept", "label": "Accept Dispatch"}
    if status == "clarification_requested":
        return {"key": "review", "label": "Review Clarification"}
    if status == "accepted":
        return {"key": "start", "label": "Start Dispatch"}
    if status == "in_progress" and document.get("is_paused"):
        return {"key": "resume", "label": "Resume Dispatch"}
    if status == "in_progress" and workflow in {"accepted", "travelling_to_pickup"}:
        return {"key": "goods_loaded", "label": "Confirm Goods Loaded"}
    if status == "in_progress" and workflow == "goods_loaded":
        return {"key": "delivery_completed", "label": "Confirm Delivery"}
    if status == "in_progress":
        return {"key": "continue", "label": "Continue Dispatch"}
    return {"key": "view", "label": "View Dispatch"}


def _dashboard_transfer(document: dict) -> dict:
    task = _transfer_summary(document, {})
    task.pop("vehicle", None)
    task.pop("linked_waybill_id", None)
    return task


def _dashboard_request(document: dict) -> dict:
    task = _request_summary(document, {})
    task.pop("vehicle", None)
    task.pop("linked_waybill_id", None)
    return task


def _dashboard_dispatch(document: dict) -> dict:
    return {
        "id": str(document["_id"]),
        "task_key": f"dispatch:{document['_id']}",
        "operation_type": "dispatch",
        "operation_label": "Dispatch",
        "reference": document.get("dispatch_job_id"),
        "title": f"{document.get('pickup') or 'Pickup'} to {document.get('destination') or 'Destination'}",
        "schedule": _value(document.get("scheduled_start_time")),
        "origin": document.get("pickup"),
        "destination": document.get("destination"),
        "status": document.get("status"),
        "status_label": _label(document.get("status")),
        "current_action": _dispatch_action(document),
        "updated_at": _value(document.get("updated_at")),
    }


def _as_datetime(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _is_between(value, start: datetime, end: datetime) -> bool:
    parsed = _as_datetime(value)
    return parsed is not None and start <= parsed < end


def _current_rank(task: dict) -> tuple:
    underway = {
        "in_progress",
        "in_transit",
        "movement_in_progress",
        "released",
        "awaiting_receipt",
        "awaiting_verification",
    }
    pending_acceptance = task.get("current_action", {}).get("key") in {"accept", "acknowledge"}
    return (
        0 if task.get("status") in underway else 1 if not pending_acceptance else 2,
        _sort_value(task),
    )


def get_driver_operations_dashboard_summary(
    current_user_id: str,
    *,
    now_value: datetime | None = None,
) -> dict:
    driver_id = _driver_id(current_user_id)
    now_value = _as_datetime(now_value) or datetime.now(timezone.utc)
    today_start = now_value.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    transfers = list(get_collection("stock_transfers").find(
        {
            "driver_id": driver_id,
            "$or": [
                {"status": {"$in": TRANSFER_ACTIVE_STATUSES}},
                {"status": "completed", "completed_at": {"$gte": today_start, "$lt": tomorrow_start}},
            ],
        },
        DASHBOARD_TRANSFER_PROJECTION,
    ))
    requests = list(get_collection("vehicle_operation_requests").find(
        {
            "driver_id": driver_id,
            "$or": [
                {"status": {"$in": REQUEST_ACTIVE_STATUSES}},
                {"status": "completed", "verified_at": {"$gte": today_start, "$lt": tomorrow_start}},
            ],
        },
        DASHBOARD_REQUEST_PROJECTION,
    ))
    dispatches = list(get_collection("dispatch_jobs").find(
        {
            "driver_id": driver_id,
            "$or": [
                {"status": {"$in": DISPATCH_ACTIVE_STATUSES}},
                {"status": "completed", "completed_at": {"$gte": today_start, "$lt": tomorrow_start}},
            ],
        },
        DISPATCH_PROJECTION,
    ))

    task_rows = [
        *[
            {
                "task": _dashboard_transfer(item),
                "schedule": item.get("scheduled_at"),
                "completed": item.get("completed_at"),
            }
            for item in transfers
        ],
        *[
            {
                "task": _dashboard_request(item),
                "schedule": item.get("planned_departure_at"),
                "completed": item.get("verified_at"),
            }
            for item in requests
        ],
        *[
            {
                "task": _dashboard_dispatch(item),
                "schedule": item.get("scheduled_start_time"),
                "completed": item.get("completed_at"),
            }
            for item in dispatches
        ],
    ]
    unique_rows = {row["task"]["task_key"]: row for row in task_rows}
    rows = list(unique_rows.values())
    active_rows = [
        row for row in rows
        if row["task"]["status"] not in {"completed", "cancelled", "rejected", "aborted"}
    ]
    current_task = (
        sorted((row["task"] for row in active_rows), key=_current_rank)[0]
        if active_rows else None
    )
    upcoming = sorted(
        (
            row["task"]
            for row in active_rows
            if (_as_datetime(row["schedule"]) or today_start) >= tomorrow_start
        ),
        key=_sort_value,
    )[:3]
    pending_acceptance = sum(
        1
        for row in active_rows
        if row["task"].get("current_action", {}).get("key") in {"accept", "acknowledge"}
    )
    return {
        "counts": {
            "current_task": 1 if current_task else 0,
            "today": sum(1 for row in rows if _is_between(row["schedule"], today_start, tomorrow_start)),
            "upcoming": sum(
                1
                for row in active_rows
                if (_as_datetime(row["schedule"]) or today_start) >= tomorrow_start
            ),
            "pending_acceptance": pending_acceptance,
            "completed_today": sum(
                1 for row in rows if _is_between(row["completed"], today_start, tomorrow_start)
            ),
        },
        "current_task": current_task,
        "upcoming_tasks": upcoming,
        "generated_at": now_value.isoformat(),
    }
