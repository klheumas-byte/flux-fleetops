from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.expense import serialize_expense
from models.fault import serialize_fault
from models.maintenance import (
    serialize_maintenance_job,
    serialize_maintenance_progress_log,
)
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.assignment_service import get_active_assignment_for_driver
from services.expense_service import create_expense
from services.notification_service import create_notification, notify_roles
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


ALLOWED_MAINTENANCE_TYPES = {
    "repair",
    "servicing",
    "inspection",
    "oil_change",
    "tyre_change",
    "battery_replacement",
    "brake_service",
    "engine_service",
    "electrical_repair",
    "body_repair",
    "accident_repair",
    "roadworthy_inspection",
    "insurance_inspection",
    "other",
}
ALLOWED_MAINTENANCE_PRIORITIES = {"low", "medium", "high", "critical"}
ALLOWED_MAINTENANCE_STATUSES = {
    "pending",
    "approved",
    "in_progress",
    "waiting_parts",
    "completed",
    "cancelled",
}
ALLOWED_PROGRESS_UPDATE_TYPES = {
    "follow_up",
    "mechanic_update",
    "parts_update",
    "cost_update",
    "delay",
    "ready_for_test",
    "general",
}
ALLOWED_CURRENT_STAGES = {
    "assigned_to_mechanic",
    "diagnosing",
    "waiting_parts",
    "parts_received",
    "repair_in_progress",
    "testing",
    "ready_for_driver_test",
    "driver_confirmed",
    "completed",
    "delayed",
}


def now_utc():
    return datetime.now(timezone.utc)


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def maintenance_progress_collection():
    return get_collection("maintenance_progress_logs")


def vehicles_collection():
    return get_collection("vehicles")


def users_collection():
    return get_collection("users")


def faults_collection():
    return get_collection("faults")


def fault_categories_collection():
    return get_collection("fault_categories")


def fault_components_collection():
    return get_collection("fault_components")


def expenses_collection():
    return get_collection("expenses")


def ensure_maintenance_indexes():
    ensure_indexes_for_collection(
        maintenance_jobs_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("fault_report_id", ASCENDING)], "options": {"unique": True, "sparse": True}},
            {"keys": [("expense_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("maintenance_type", ASCENDING)]},
            {"keys": [("priority", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("maintenance_coordinator_id", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("next_follow_up_date", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("target_completion_date", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("current_stage", ASCENDING)], "options": {"sparse": True}},
            {"keys": [("start_date", DESCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("updated_at", DESCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="maintenance_jobs",
    )
    ensure_indexes_for_collection(
        maintenance_progress_collection(),
        [
            {"keys": [("maintenance_job_id", ASCENDING)]},
            {"keys": [("update_type", ASCENDING)]},
            {"keys": [("current_stage", ASCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
        ],
        collection_name="maintenance_progress_logs",
    )


def _to_object_id(value, field_name: str, required: bool = True):
    if value is None or value == "":
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _parse_date(value, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        raise ApiError(f"{field_name} must be a date string in YYYY-MM-DD format.", status_code=400)
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ApiError(f"{field_name} must be a valid YYYY-MM-DD date.", status_code=400) from exc


def _serialize_date(value: date | None):
    return value.isoformat() if value else None


def _validate_non_negative_amount(value, field_name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _validate_maintenance_type(value: str | None):
    maintenance_type = (value or "").strip().lower()
    if maintenance_type not in ALLOWED_MAINTENANCE_TYPES:
        raise ApiError(
            "maintenance_type must be one of: repair, servicing, inspection, oil_change, tyre_change, battery_replacement, brake_service, engine_service, electrical_repair, body_repair, accident_repair, roadworthy_inspection, insurance_inspection, other.",
            status_code=400,
        )
    return maintenance_type


def _validate_priority(value: str | None):
    priority = (value or "").strip().lower()
    if priority not in ALLOWED_MAINTENANCE_PRIORITIES:
        raise ApiError("priority must be one of: low, medium, high, critical.", status_code=400)
    return priority


def _validate_status(value: str | None):
    status = (value or "").strip().lower()
    if status not in ALLOWED_MAINTENANCE_STATUSES:
        raise ApiError(
            "status must be one of: pending, approved, in_progress, waiting_parts, completed, cancelled.",
            status_code=400,
        )
    return status


def _validate_current_stage(value: str | None, required: bool = False):
    if value in (None, ""):
        if required:
            raise ApiError("current_stage is required.", status_code=400)
        return None
    current_stage = str(value).strip().lower()
    if current_stage not in ALLOWED_CURRENT_STAGES:
        raise ApiError(
            "current_stage must be one of: assigned_to_mechanic, diagnosing, waiting_parts, parts_received, repair_in_progress, testing, ready_for_driver_test, driver_confirmed, completed, delayed.",
            status_code=400,
        )
    return current_stage


def _validate_progress_update_type(value: str | None):
    update_type = (value or "").strip().lower()
    if update_type not in ALLOWED_PROGRESS_UPDATE_TYPES:
        raise ApiError(
            "update_type must be one of: follow_up, mechanic_update, parts_update, cost_update, delay, ready_for_test, general.",
            status_code=400,
        )
    return update_type


def _validate_odometer(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("odometer_reading must be numeric.", status_code=400)
    if value < 0:
        raise ApiError("odometer_reading cannot be negative.", status_code=400)
    return round(float(value), 2)


def _get_user_document(user_id: str | ObjectId, field_name: str = "user_id"):
    user_object_id = _to_object_id(user_id, field_name)
    document = users_collection().find_one({"_id": user_object_id})
    if not document:
        raise ApiError("User not found.", status_code=404)
    return document


def _get_vehicle_document(vehicle_id: str | ObjectId):
    vehicle_object_id = _to_object_id(vehicle_id, "vehicle_id")
    document = vehicles_collection().find_one({"_id": vehicle_object_id})
    if not document:
        raise ApiError("Vehicle not found.", status_code=404)
    return document


def _get_fault_document(fault_id: str | ObjectId):
    fault_object_id = _to_object_id(fault_id, "fault_report_id")
    document = faults_collection().find_one({"_id": fault_object_id})
    if not document:
        raise ApiError("Fault not found.", status_code=404)
    return document


def _get_expense_document(expense_id: str | ObjectId):
    expense_object_id = _to_object_id(expense_id, "expense_id")
    document = expenses_collection().find_one({"_id": expense_object_id})
    if not document:
        raise ApiError("Expense not found.", status_code=404)
    return document


def _get_maintenance_document(maintenance_id: str | ObjectId):
    maintenance_object_id = _to_object_id(maintenance_id, "maintenance_id")
    document = maintenance_jobs_collection().find_one({"_id": maintenance_object_id})
    if not document:
        raise ApiError("Maintenance job not found.", status_code=404)
    return document


def _resolve_driver_vehicle_for_driver(current_user_id: str):
    assignment = get_active_assignment_for_driver(current_user_id)
    if not assignment:
        return None
    return _to_object_id(assignment.get("vehicle_id"), "vehicle_id")


def _get_coordinator_document(coordinator_id: str | ObjectId | None, current_user_id: str, required: bool = False):
    if coordinator_id in (None, ""):
        if required:
            coordinator_id = current_user_id
        else:
            return None
    coordinator_document = _get_user_document(coordinator_id, "maintenance_coordinator_id")
    if coordinator_document.get("role") not in {"owner", "admin"}:
        raise ApiError("Maintenance coordinator must be an owner or admin user.", status_code=400)
    if coordinator_document.get("status") != "active":
        raise ApiError("Maintenance coordinator must be active.", status_code=400)
    return coordinator_document


def _create_user_notification(recipient_id: ObjectId | None, *, title: str, message: str, priority: str, reference_id: ObjectId):
    if recipient_id is None:
        return
    create_notification(
        recipient_user_id=recipient_id,
        title=title,
        message=message,
        category="maintenance",
        priority=priority,
        reference_type="maintenance",
        reference_id=reference_id,
    )


def _set_vehicle_status_for_maintenance(vehicle_document: dict, priority: str, status: str):
    if priority != "critical":
        return
    if status in {"completed", "cancelled"}:
        return
    timestamp = now_utc()
    vehicles_collection().update_one(
        {"_id": vehicle_document["_id"]},
        {"$set": {"status": "maintenance", "updated_at": timestamp}},
    )
    vehicle_document["status"] = "maintenance"
    vehicle_document["updated_at"] = timestamp


def _restore_vehicle_status_after_completion(vehicle_document: dict):
    next_status = "assigned" if vehicle_document.get("assigned_driver_id") else "available"
    timestamp = now_utc()
    vehicles_collection().update_one(
        {"_id": vehicle_document["_id"]},
        {"$set": {"status": next_status, "updated_at": timestamp}},
    )
    vehicle_document["status"] = next_status
    vehicle_document["updated_at"] = timestamp


def _append_vehicle_maintenance_history(vehicle_id: ObjectId, maintenance_document: dict):
    history_entry = {
        "maintenance_job_id": maintenance_document["_id"],
        "maintenance_type": maintenance_document.get("maintenance_type"),
        "title": maintenance_document.get("title"),
        "priority": maintenance_document.get("priority"),
        "status": maintenance_document.get("status"),
        "fault_report_id": maintenance_document.get("fault_report_id"),
        "estimated_cost": maintenance_document.get("estimated_cost"),
        "actual_cost": maintenance_document.get("actual_cost"),
        "vendor_name": maintenance_document.get("vendor_name"),
        "completed_at": maintenance_document.get("completion_date") or maintenance_document.get("updated_at"),
    }
    vehicles_collection().update_one(
        {"_id": vehicle_id},
        {
            "$push": {"maintenance_history": history_entry},
            "$set": {"updated_at": now_utc()},
        },
    )


def _link_existing_or_new_expense(
    *,
    payload: dict,
    current_user_id: str,
    current_role: str,
    job_title: str,
    vehicle_id: ObjectId,
    driver_id: ObjectId | None,
    estimated_cost: float | None,
) -> ObjectId | None:
    expense_id = payload.get("expense_id")
    create_linked_expense = payload.get("create_linked_expense")

    if expense_id and create_linked_expense:
        raise ApiError("Provide either expense_id or create_linked_expense, not both.", status_code=400)

    if expense_id:
        expense_document = _get_expense_document(expense_id)
        return expense_document["_id"]

    if not create_linked_expense:
        return None
    if not isinstance(create_linked_expense, dict):
        raise ApiError("create_linked_expense must be an object.", status_code=400)

    expense_payload = {
        "expense_title": create_linked_expense.get("expense_title") or job_title,
        "expense_category": create_linked_expense.get("expense_category") or "repairs",
        "amount": create_linked_expense.get("amount")
        if create_linked_expense.get("amount") is not None
        else estimated_cost,
        "expense_date": create_linked_expense.get("expense_date")
        or payload.get("start_date")
        or now_utc().date().isoformat(),
        "vehicle_id": str(vehicle_id),
        "driver_id": str(driver_id) if driver_id else None,
        "finance_account_id": create_linked_expense.get("finance_account_id"),
        "payment_method": create_linked_expense.get("payment_method") or "cash",
        "reference_number": create_linked_expense.get("reference_number"),
        "receipt_image": create_linked_expense.get("receipt_image"),
        "notes": create_linked_expense.get("notes") or f"Linked to maintenance job: {job_title}",
    }
    if expense_payload["amount"] in (None, ""):
        raise ApiError("Linked expense amount is required.", status_code=400)

    expense = create_expense(expense_payload, current_user_id=current_user_id, current_role=current_role)
    return ObjectId(expense["id"])


def _serialize_progress_timeline_entry(document: dict):
    progress_log = serialize_maintenance_progress_log(document)
    updated_by_document = users_collection().find_one({"_id": document.get("updated_by")})
    progress_log["updated_by_user"] = serialize_user(updated_by_document) if updated_by_document else None
    return progress_log


def _get_driver_accessible_maintenance_document(maintenance_id: str, current_user_id: str) -> dict:
    document = _get_maintenance_document(maintenance_id)
    assigned_vehicle_id = _resolve_driver_vehicle_for_driver(current_user_id)
    if assigned_vehicle_id is None or document.get("vehicle_id") != assigned_vehicle_id:
        raise ApiError("You do not have permission to view this maintenance job.", status_code=403)
    return document


def _get_latest_driver_progress_log(maintenance_id: ObjectId, driver_user_id: str):
    if not ObjectId.is_valid(driver_user_id):
        return None
    return maintenance_progress_collection().find_one(
        {
            "maintenance_job_id": maintenance_id,
            "updated_by": ObjectId(driver_user_id),
        },
        sort=[("updated_at", DESCENDING)],
    )


def _derive_driver_confirmation_status(document: dict, current_user_id: str) -> str | None:
    if document.get("current_stage") == "driver_confirmed":
        return "confirmed"
    if document.get("current_stage") == "ready_for_driver_test":
        return "pending"

    latest_driver_log = _get_latest_driver_progress_log(document["_id"], current_user_id)
    if not latest_driver_log:
        return None
    if latest_driver_log.get("current_stage") == "driver_confirmed":
        return "confirmed"
    if latest_driver_log.get("current_stage") == "delayed":
        return "rejected"
    return None


def _serialize_driver_maintenance_job(document: dict, current_user_id: str) -> dict:
    vehicle_document = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
    return {
        "id": str(document.get("_id")),
        "maintenance_type": document.get("maintenance_type"),
        "title": document.get("title"),
        "status": document.get("status"),
        "current_stage": document.get("current_stage"),
        "start_date": document.get("start_date"),
        "target_completion_date": document.get("target_completion_date"),
        "completion_date": document.get("completion_date"),
        "next_follow_up_date": document.get("next_follow_up_date"),
        "service_note": document.get("description"),
        "next_action": document.get("next_action"),
        "driver_confirmation_status": _derive_driver_confirmation_status(document, current_user_id),
        "vehicle": {
            "id": str(vehicle_document.get("_id")),
            "registration_number": vehicle_document.get("registration_number"),
        } if vehicle_document else None,
    }


def _serialize_driver_progress_timeline_entry(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "update_type": document.get("update_type"),
        "progress_note": document.get("progress_note"),
        "current_stage": document.get("current_stage"),
        "next_action": document.get("next_action"),
        "next_follow_up_date": document.get("next_follow_up_date"),
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


def _derive_status_from_stage(current_stage: str | None, fallback_status: str):
    if current_stage == "waiting_parts":
        return "waiting_parts"
    if current_stage == "completed":
        return "completed"
    if current_stage in {
        "assigned_to_mechanic",
        "diagnosing",
        "parts_received",
        "repair_in_progress",
        "testing",
        "ready_for_driver_test",
        "driver_confirmed",
        "delayed",
    }:
        return "in_progress"
    return fallback_status


def _process_maintenance_reminders(documents: list[dict]):
    if not documents:
        return

    timestamp = now_utc()
    today = timestamp.date()

    for document in documents:
        if document.get("status") in {"completed", "cancelled"}:
            update_fields = {}
            if document.get("follow_up_overdue"):
                update_fields["follow_up_overdue"] = False
            if document.get("is_overdue"):
                update_fields["is_overdue"] = False
            if update_fields:
                maintenance_jobs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
                document.update(update_fields)
            continue

        update_fields = {}
        coordinator_id = document.get("maintenance_coordinator_id")
        next_follow_up_date = _parse_date(document.get("next_follow_up_date"), "next_follow_up_date", required=False)
        last_progress_updated_at = document.get("last_progress_updated_at")
        target_completion_date = _parse_date(document.get("target_completion_date"), "target_completion_date", required=False)
        current_stage = document.get("current_stage")

        is_follow_up_overdue = False
        if next_follow_up_date:
          # noqa: E111
            if next_follow_up_date == today and document.get("due_today_notification_sent_for") != today.isoformat():
                _create_user_notification(
                    coordinator_id,
                    title="Maintenance Follow-up Due Today",
                    message=f"Follow up on maintenance job {document.get('title')} today.",
                    priority="medium",
                    reference_id=document["_id"],
                )
                update_fields["due_today_notification_sent_for"] = today.isoformat()

            if next_follow_up_date < today and (
                last_progress_updated_at is None or last_progress_updated_at.date() < next_follow_up_date
            ):
                is_follow_up_overdue = True
                if document.get("follow_up_overdue_notification_sent_for") != today.isoformat():
                    _create_user_notification(
                        coordinator_id,
                        title="Maintenance Follow-up Overdue",
                        message=f"Maintenance job {document.get('title')} has an overdue follow-up.",
                        priority="high",
                        reference_id=document["_id"],
                    )
                    update_fields["follow_up_overdue_notification_sent_for"] = today.isoformat()

        update_fields["follow_up_overdue"] = is_follow_up_overdue

        is_job_overdue = bool(target_completion_date and target_completion_date < today)
        update_fields["is_overdue"] = is_job_overdue

        if (
            is_job_overdue
            and document.get("priority") == "critical"
            and document.get("critical_overdue_notification_sent_for") != today.isoformat()
        ):
            notify_roles(
                ["owner"],
                title="Critical Maintenance Overdue",
                message=f"Critical maintenance job {document.get('title')} is overdue.",
                category="maintenance",
                priority="critical",
                reference_type="maintenance",
                reference_id=document["_id"],
            )
            update_fields["critical_overdue_notification_sent_for"] = today.isoformat()

        waiting_parts_since = document.get("waiting_parts_since")
        if current_stage == "waiting_parts" and waiting_parts_since:
            waiting_parts_age = timestamp - waiting_parts_since
            if (
                waiting_parts_age >= timedelta(days=2)
                and document.get("waiting_parts_notification_sent_for") != today.isoformat()
            ):
                notify_roles(
                    ["admin", "owner"],
                    title="Maintenance Waiting On Parts",
                    message=f"Maintenance job {document.get('title')} has been waiting on parts for more than 2 days.",
                    category="maintenance",
                    priority="high" if document.get("priority") != "critical" else "critical",
                    reference_type="maintenance",
                    reference_id=document["_id"],
                )
                update_fields["waiting_parts_notification_sent_for"] = today.isoformat()

        ready_for_driver_test_since = document.get("ready_for_driver_test_since")
        if current_stage == "ready_for_driver_test":
            if not document.get("ready_for_driver_test_notified_at") and document.get("driver_id"):
                _create_user_notification(
                    document.get("driver_id"),
                    title="Vehicle Ready For Driver Test",
                    message=f"Your assigned vehicle is ready for testing: {document.get('title')}.",
                    priority="medium",
                    reference_id=document["_id"],
                )
                update_fields["ready_for_driver_test_notified_at"] = timestamp

            if (
                ready_for_driver_test_since
                and timestamp - ready_for_driver_test_since >= timedelta(hours=24)
                and document.get("driver_test_reminder_sent_for") != today.isoformat()
            ):
                if document.get("driver_id"):
                    _create_user_notification(
                        document.get("driver_id"),
                        title="Driver Test Confirmation Needed",
                        message=f"Please confirm the maintenance test result for {document.get('title')}.",
                        priority="high",
                        reference_id=document["_id"],
                    )
                _create_user_notification(
                    coordinator_id,
                    title="Driver Test Confirmation Still Pending",
                    message=f"Driver confirmation is still pending for maintenance job {document.get('title')}.",
                    priority="high",
                    reference_id=document["_id"],
                )
                update_fields["driver_test_reminder_sent_for"] = today.isoformat()

        if update_fields:
            maintenance_jobs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
            document.update(update_fields)


def _enrich_maintenance_job(document: dict) -> dict:
    job = serialize_maintenance_job(document)
    vehicle_document = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
    driver_document = users_collection().find_one({"_id": document.get("driver_id")})
    fault_document = (
        faults_collection().find_one({"_id": document.get("fault_report_id")})
        if document.get("fault_report_id")
        else None
    )
    expense_document = (
        expenses_collection().find_one({"_id": document.get("expense_id")})
        if document.get("expense_id")
        else None
    )
    created_by_document = users_collection().find_one({"_id": document.get("created_by")})
    approved_by_document = users_collection().find_one({"_id": document.get("approved_by")})
    completed_by_document = users_collection().find_one({"_id": document.get("completed_by")})
    coordinator_document = users_collection().find_one({"_id": document.get("maintenance_coordinator_id")})

    job["vehicle"] = serialize_vehicle(vehicle_document) if vehicle_document else None
    job["driver"] = serialize_user(driver_document) if driver_document else None
    job["fault_report"] = serialize_fault(fault_document) if fault_document else None
    job["expense"] = serialize_expense(expense_document) if expense_document else None
    job["created_by_user"] = serialize_user(created_by_document) if created_by_document else None
    job["approved_by_user"] = serialize_user(approved_by_document) if approved_by_document else None
    job["completed_by_user"] = serialize_user(completed_by_document) if completed_by_document else None
    job["maintenance_coordinator"] = serialize_user(coordinator_document) if coordinator_document else None
    return job


def list_maintenance_jobs(current_user_id: str, current_role: str) -> list[dict]:
    query = {}

    documents = list(
        maintenance_jobs_collection()
        .find(query)
        .sort([("priority", ASCENDING), ("start_date", DESCENDING), ("created_at", DESCENDING)])
    )
    _process_maintenance_reminders(documents)
    return [_enrich_maintenance_job(document) for document in documents]


def get_maintenance_job_by_id(maintenance_id: str, current_user_id: str, current_role: str) -> dict:
    document = _get_maintenance_document(maintenance_id)
    _process_maintenance_reminders([document])
    return _enrich_maintenance_job(document)


def list_maintenance_progress_logs(maintenance_id: str, current_user_id: str, current_role: str) -> list[dict]:
    _ = get_maintenance_job_by_id(maintenance_id, current_user_id, current_role)
    logs = (
        maintenance_progress_collection()
        .find({"maintenance_job_id": _to_object_id(maintenance_id, "maintenance_id")})
        .sort([("updated_at", DESCENDING)])
    )
    return [_serialize_progress_timeline_entry(log) for log in logs]


def list_due_follow_ups(current_user_id: str, current_role: str) -> list[dict]:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to view maintenance follow-ups.", status_code=403)

    today = date.today().isoformat()
    query = {
        "next_follow_up_date": today,
        "status": {"$nin": ["completed", "cancelled"]},
    }
    if current_role == "admin":
        query["maintenance_coordinator_id"] = _to_object_id(current_user_id, "current_user_id")

    documents = list(
        maintenance_jobs_collection()
        .find(query)
        .sort([("priority", ASCENDING), ("next_follow_up_date", ASCENDING), ("updated_at", DESCENDING)])
    )
    _process_maintenance_reminders(documents)
    return [_enrich_maintenance_job(document) for document in documents]


def list_overdue_follow_ups(current_user_id: str, current_role: str) -> list[dict]:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to view maintenance follow-ups.", status_code=403)

    today = date.today().isoformat()
    query = {
        "next_follow_up_date": {"$lt": today},
        "status": {"$nin": ["completed", "cancelled"]},
    }
    if current_role == "admin":
        query["maintenance_coordinator_id"] = _to_object_id(current_user_id, "current_user_id")

    documents = list(
        maintenance_jobs_collection()
        .find(query)
        .sort([("priority", ASCENDING), ("next_follow_up_date", ASCENDING), ("updated_at", DESCENDING)])
    )
    _process_maintenance_reminders(documents)
    return [_enrich_maintenance_job(document) for document in documents]


def list_driver_maintenance_jobs(current_user_id: str) -> list[dict]:
    assigned_vehicle_id = _resolve_driver_vehicle_for_driver(current_user_id)
    if assigned_vehicle_id is None:
        return []

    documents = list(
        maintenance_jobs_collection()
        .find({"vehicle_id": assigned_vehicle_id})
        .sort([("start_date", DESCENDING), ("created_at", DESCENDING)])
    )
    _process_maintenance_reminders(documents)
    return [_serialize_driver_maintenance_job(document, current_user_id) for document in documents]


def get_driver_maintenance_job_by_id(maintenance_id: str, current_user_id: str) -> dict:
    document = _get_driver_accessible_maintenance_document(maintenance_id, current_user_id)
    _process_maintenance_reminders([document])
    return _serialize_driver_maintenance_job(document, current_user_id)


def list_driver_maintenance_progress_logs(maintenance_id: str, current_user_id: str) -> list[dict]:
    document = _get_driver_accessible_maintenance_document(maintenance_id, current_user_id)
    _process_maintenance_reminders([document])
    logs = (
        maintenance_progress_collection()
        .find({"maintenance_job_id": document["_id"]})
        .sort([("updated_at", DESCENDING)])
    )
    return [_serialize_driver_progress_timeline_entry(log) for log in logs]


def create_maintenance_job(payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to create maintenance jobs.", status_code=403)

    vehicle_document = _get_vehicle_document(payload.get("vehicle_id"))
    driver_object_id = _to_object_id(payload.get("driver_id"), "driver_id", required=False)
    if driver_object_id is not None:
        driver_document = _get_user_document(driver_object_id, "driver_id")
        if driver_document.get("role") != "driver":
            raise ApiError("Selected driver must have the driver role.", status_code=400)

    fault_report_id = payload.get("fault_report_id")
    fault_document = None
    if fault_report_id:
        fault_document = _get_fault_document(fault_report_id)
        if fault_document.get("status") not in {"approved", "converted_to_maintenance"}:
            raise ApiError("Only approved faults can be linked to maintenance jobs.", status_code=400)

    maintenance_type = _validate_maintenance_type(payload.get("maintenance_type"))
    title = (payload.get("title") or "").strip()
    if not title:
        raise ApiError("title is required.", status_code=400)
    description = (payload.get("description") or "").strip()
    if not description:
        raise ApiError("description is required.", status_code=400)

    priority = _validate_priority(payload.get("priority"))
    status = _validate_status(payload.get("status") or "pending")
    current_stage = _validate_current_stage(payload.get("current_stage")) or "assigned_to_mechanic"
    derived_status = _derive_status_from_stage(current_stage, status)
    estimated_cost = _validate_non_negative_amount(payload.get("estimated_cost"), "estimated_cost")
    actual_cost = _validate_non_negative_amount(payload.get("actual_cost"), "actual_cost")
    coordinator_document = _get_coordinator_document(
        payload.get("maintenance_coordinator_id"),
        current_user_id=current_user_id,
        required=True,
    )
    expense_object_id = _link_existing_or_new_expense(
        payload=payload,
        current_user_id=current_user_id,
        current_role=current_role,
        job_title=title,
        vehicle_id=vehicle_document["_id"],
        driver_id=driver_object_id,
        estimated_cost=estimated_cost,
    )

    timestamp = now_utc()
    next_follow_up_date = _parse_date(payload.get("next_follow_up_date"), "next_follow_up_date", required=False)
    target_completion_date = _parse_date(payload.get("target_completion_date"), "target_completion_date", required=False)

    document = {
        "vehicle_id": vehicle_document["_id"],
        "driver_id": driver_object_id,
        "fault_report_id": fault_document["_id"] if fault_document else None,
        "maintenance_type": maintenance_type,
        "title": title,
        "description": description,
        "priority": priority,
        "vendor_name": (payload.get("vendor_name") or "").strip() or None,
        "vendor_contact": (payload.get("vendor_contact") or "").strip() or None,
        "estimated_cost": estimated_cost,
        "actual_cost": actual_cost,
        "expense_id": expense_object_id,
        "odometer_reading": _validate_odometer(payload.get("odometer_reading")),
        "start_date": (payload.get("start_date") or "").strip() or None,
        "target_completion_date": _serialize_date(target_completion_date),
        "completion_date": (payload.get("completion_date") or "").strip() or None,
        "status": derived_status,
        "notes": (payload.get("notes") or "").strip() or None,
        "maintenance_coordinator_id": coordinator_document["_id"],
        "assigned_admin_name": coordinator_document.get("full_name"),
        "assigned_at": timestamp,
        "current_stage": current_stage,
        "next_action": (payload.get("next_action") or "").strip() or None,
        "next_follow_up_date": _serialize_date(next_follow_up_date),
        "follow_up_overdue": False,
        "is_overdue": False,
        "last_progress_updated_at": None,
        "waiting_parts_since": timestamp if current_stage == "waiting_parts" else None,
        "ready_for_driver_test_since": timestamp if current_stage == "ready_for_driver_test" else None,
        "ready_for_driver_test_notified_at": None,
        "driver_test_reminder_sent_for": None,
        "due_today_notification_sent_for": None,
        "follow_up_overdue_notification_sent_for": None,
        "waiting_parts_notification_sent_for": None,
        "critical_overdue_notification_sent_for": None,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "approved_by": _to_object_id(current_user_id, "approved_by") if derived_status != "pending" else None,
        "completed_by": _to_object_id(current_user_id, "completed_by") if derived_status == "completed" else None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = maintenance_jobs_collection().insert_one(document)
    document["_id"] = result.inserted_id

    if fault_document:
        faults_collection().update_one(
            {"_id": fault_document["_id"]},
            {
                "$set": {
                    "status": "converted_to_maintenance",
                    "maintenance_job_id": document["_id"],
                    "converted_by": _to_object_id(current_user_id, "converted_by"),
                    "converted_to_maintenance_by": _to_object_id(current_user_id, "converted_to_maintenance_by"),
                    "converted_to_maintenance_at": timestamp,
                    "updated_by": _to_object_id(current_user_id, "updated_by"),
                    "updated_at": timestamp,
                }
            },
        )

    _set_vehicle_status_for_maintenance(vehicle_document, priority, derived_status)

    if derived_status == "completed":
        document["completion_date"] = document.get("completion_date") or timestamp.date().isoformat()
        maintenance_jobs_collection().update_one(
            {"_id": document["_id"]},
            {
                "$set": {
                    "completion_date": document["completion_date"],
                    "updated_at": timestamp,
                    "current_stage": "completed",
                }
            },
        )
        document["current_stage"] = "completed"
        if fault_document:
            faults_collection().update_one(
                {"_id": fault_document["_id"]},
                {
                    "$set": {
                        "status": "resolved",
                        "resolved_at": timestamp,
                        "resolution_notes": document.get("notes"),
                        "updated_by": _to_object_id(current_user_id, "updated_by"),
                        "updated_at": timestamp,
                    }
                },
            )
        _restore_vehicle_status_after_completion(vehicle_document)
        _append_vehicle_maintenance_history(vehicle_document["_id"], document)

    maintenance_progress_collection().insert_one(
        {
            "maintenance_job_id": document["_id"],
            "update_type": "general",
            "progress_note": f"Maintenance job created and assigned to {document.get('assigned_admin_name')}.",
            "current_stage": current_stage,
            "next_action": document.get("next_action"),
            "next_follow_up_date": document.get("next_follow_up_date"),
            "updated_by": _to_object_id(current_user_id, "updated_by"),
            "updated_at": timestamp,
        }
    )

    document["last_progress_updated_at"] = timestamp
    maintenance_jobs_collection().update_one(
        {"_id": document["_id"]},
        {"$set": {"last_progress_updated_at": timestamp}},
    )
    _process_maintenance_reminders([document])
    return _enrich_maintenance_job(document)


def update_maintenance_job(maintenance_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update maintenance jobs.", status_code=403)

    document = _get_maintenance_document(maintenance_id)
    if document.get("status") == "completed":
        raise ApiError("Completed maintenance jobs cannot be edited directly.", status_code=400)

    update_fields = {}

    if "vehicle_id" in payload:
        vehicle_document = _get_vehicle_document(payload.get("vehicle_id"))
        update_fields["vehicle_id"] = vehicle_document["_id"]
    else:
        vehicle_document = _get_vehicle_document(document.get("vehicle_id"))

    if "driver_id" in payload:
        driver_object_id = _to_object_id(payload.get("driver_id"), "driver_id", required=False)
        if driver_object_id is not None:
            driver_document = _get_user_document(driver_object_id, "driver_id")
            if driver_document.get("role") != "driver":
                raise ApiError("Selected driver must have the driver role.", status_code=400)
        update_fields["driver_id"] = driver_object_id
    else:
        driver_object_id = document.get("driver_id")

    if "maintenance_type" in payload:
        update_fields["maintenance_type"] = _validate_maintenance_type(payload.get("maintenance_type"))
    if "title" in payload:
        title = (payload.get("title") or "").strip()
        if not title:
            raise ApiError("title cannot be empty.", status_code=400)
        update_fields["title"] = title
    if "description" in payload:
        description = (payload.get("description") or "").strip()
        if not description:
            raise ApiError("description cannot be empty.", status_code=400)
        update_fields["description"] = description
    if "priority" in payload:
        update_fields["priority"] = _validate_priority(payload.get("priority"))
    if "vendor_name" in payload:
        update_fields["vendor_name"] = (payload.get("vendor_name") or "").strip() or None
    if "vendor_contact" in payload:
        update_fields["vendor_contact"] = (payload.get("vendor_contact") or "").strip() or None
    if "estimated_cost" in payload:
        update_fields["estimated_cost"] = _validate_non_negative_amount(
            payload.get("estimated_cost"), "estimated_cost"
        )
    if "actual_cost" in payload:
        update_fields["actual_cost"] = _validate_non_negative_amount(payload.get("actual_cost"), "actual_cost")
    if "expense_id" in payload or "create_linked_expense" in payload:
        update_fields["expense_id"] = _link_existing_or_new_expense(
            payload=payload,
            current_user_id=current_user_id,
            current_role=current_role,
            job_title=update_fields.get("title") or document.get("title"),
            vehicle_id=vehicle_document["_id"],
            driver_id=driver_object_id,
            estimated_cost=update_fields.get("estimated_cost")
            if "estimated_cost" in update_fields
            else document.get("estimated_cost"),
        )
    if "odometer_reading" in payload:
        update_fields["odometer_reading"] = _validate_odometer(payload.get("odometer_reading"))
    if "start_date" in payload:
        update_fields["start_date"] = (payload.get("start_date") or "").strip() or None
    if "target_completion_date" in payload:
        update_fields["target_completion_date"] = _serialize_date(
            _parse_date(payload.get("target_completion_date"), "target_completion_date", required=False)
        )
    if "completion_date" in payload:
        update_fields["completion_date"] = (payload.get("completion_date") or "").strip() or None
    if "notes" in payload:
        update_fields["notes"] = (payload.get("notes") or "").strip() or None
    if "next_action" in payload:
        update_fields["next_action"] = (payload.get("next_action") or "").strip() or None
    if "next_follow_up_date" in payload:
        update_fields["next_follow_up_date"] = _serialize_date(
            _parse_date(payload.get("next_follow_up_date"), "next_follow_up_date", required=False)
        )
        update_fields["follow_up_overdue"] = False
    if "current_stage" in payload:
        next_stage = _validate_current_stage(payload.get("current_stage"))
        update_fields["current_stage"] = next_stage
        update_fields["status"] = _derive_status_from_stage(next_stage, document.get("status"))
        if next_stage == "waiting_parts":
            update_fields["waiting_parts_since"] = now_utc()
        elif next_stage != "waiting_parts":
            update_fields["waiting_parts_since"] = None
        if next_stage == "ready_for_driver_test":
            update_fields["ready_for_driver_test_since"] = now_utc()
            update_fields["ready_for_driver_test_notified_at"] = None
            update_fields["driver_test_reminder_sent_for"] = None
        elif next_stage != "ready_for_driver_test":
            update_fields["ready_for_driver_test_since"] = None

    if not update_fields:
        raise ApiError("No valid maintenance fields provided for update.", status_code=400)

    update_fields["updated_at"] = now_utc()
    maintenance_jobs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)

    _set_vehicle_status_for_maintenance(
        vehicle_document,
        document.get("priority"),
        document.get("status"),
    )

    _process_maintenance_reminders([document])
    return _enrich_maintenance_job(document)


def update_maintenance_status(
    maintenance_id: str,
    status: str,
    payload: dict,
    current_user_id: str,
    current_role: str,
) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to update maintenance status.", status_code=403)

    document = _get_maintenance_document(maintenance_id)
    next_status = _validate_status(status)
    current_status = document.get("status")
    if current_status == next_status:
        raise ApiError("Maintenance job already has that status.", status_code=400)
    if current_status == "completed":
        raise ApiError("Completed maintenance jobs cannot change status.", status_code=400)

    vehicle_document = _get_vehicle_document(document.get("vehicle_id"))
    fault_document = _get_fault_document(document.get("fault_report_id")) if document.get("fault_report_id") else None
    timestamp = now_utc()
    update_fields = {
        "status": next_status,
        "updated_at": timestamp,
    }

    if "notes" in payload:
        update_fields["notes"] = (payload.get("notes") or "").strip() or None
    if "actual_cost" in payload:
        update_fields["actual_cost"] = _validate_non_negative_amount(payload.get("actual_cost"), "actual_cost")
    if "estimated_cost" in payload:
        update_fields["estimated_cost"] = _validate_non_negative_amount(
            payload.get("estimated_cost"), "estimated_cost"
        )
    if "vendor_name" in payload:
        update_fields["vendor_name"] = (payload.get("vendor_name") or "").strip() or None
    if "vendor_contact" in payload:
        update_fields["vendor_contact"] = (payload.get("vendor_contact") or "").strip() or None
    if "completion_date" in payload:
        update_fields["completion_date"] = (payload.get("completion_date") or "").strip() or None

    if next_status != "pending" and document.get("approved_by") is None:
        update_fields["approved_by"] = _to_object_id(current_user_id, "approved_by")
    if next_status == "approved":
        update_fields["current_stage"] = "assigned_to_mechanic"
    if next_status == "in_progress" and document.get("current_stage") in {None, "assigned_to_mechanic"}:
        update_fields["current_stage"] = "diagnosing"
    if next_status == "waiting_parts":
        update_fields["current_stage"] = "waiting_parts"
        update_fields["waiting_parts_since"] = timestamp
    if next_status == "completed":
        update_fields["completed_by"] = _to_object_id(current_user_id, "completed_by")
        update_fields["completion_date"] = update_fields.get("completion_date") or timestamp.date().isoformat()
        update_fields["current_stage"] = "completed"
        if fault_document:
            faults_collection().update_one(
                {"_id": fault_document["_id"]},
                {
                    "$set": {
                        "status": "resolved",
                        "resolved_at": timestamp,
                        "resolution_notes": update_fields.get("notes") or document.get("notes"),
                        "updated_by": _to_object_id(current_user_id, "updated_by"),
                        "updated_at": timestamp,
                    }
                },
            )
        _restore_vehicle_status_after_completion(vehicle_document)
    elif next_status == "cancelled":
        _restore_vehicle_status_after_completion(vehicle_document)
    else:
        _set_vehicle_status_for_maintenance(vehicle_document, document.get("priority"), next_status)

    maintenance_jobs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)

    if next_status == "completed":
        _append_vehicle_maintenance_history(vehicle_document["_id"], document)

    _process_maintenance_reminders([document])
    return _enrich_maintenance_job(document)


def assign_maintenance_coordinator(
    maintenance_id: str,
    coordinator_id: str | None,
    current_user_id: str,
    current_role: str,
) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to assign maintenance coordinators.", status_code=403)

    document = _get_maintenance_document(maintenance_id)
    coordinator_document = _get_coordinator_document(coordinator_id, current_user_id=current_user_id, required=True)
    timestamp = now_utc()
    update_fields = {
        "maintenance_coordinator_id": coordinator_document["_id"],
        "assigned_admin_name": coordinator_document.get("full_name"),
        "assigned_at": timestamp,
        "updated_at": timestamp,
    }
    maintenance_jobs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)

    maintenance_progress_collection().insert_one(
        {
            "maintenance_job_id": document["_id"],
            "update_type": "general",
            "progress_note": f"Maintenance coordinator assigned to {coordinator_document.get('full_name')}.",
            "current_stage": document.get("current_stage"),
            "next_action": document.get("next_action"),
            "next_follow_up_date": document.get("next_follow_up_date"),
            "updated_by": _to_object_id(current_user_id, "updated_by"),
            "updated_at": timestamp,
        }
    )
    document["last_progress_updated_at"] = timestamp
    maintenance_jobs_collection().update_one(
        {"_id": document["_id"]},
        {"$set": {"last_progress_updated_at": timestamp}},
    )
    return _enrich_maintenance_job(document)


def add_maintenance_progress_update(
    maintenance_id: str,
    payload: dict,
    current_user_id: str,
    current_role: str,
) -> dict:
    document = _get_maintenance_document(maintenance_id)
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to add maintenance progress updates.", status_code=403)

    update_type = _validate_progress_update_type(payload.get("update_type") or "general")
    progress_note = (payload.get("progress_note") or "").strip()
    if not progress_note:
        raise ApiError("progress_note is required.", status_code=400)

    timestamp = now_utc()
    next_stage = _validate_current_stage(payload.get("current_stage")) or document.get("current_stage")
    next_action = (payload.get("next_action") or "").strip() or None
    next_follow_up_date = _serialize_date(
        _parse_date(payload.get("next_follow_up_date"), "next_follow_up_date", required=False)
    )

    update_fields = {
        "current_stage": next_stage,
        "next_action": next_action,
        "next_follow_up_date": next_follow_up_date,
        "last_progress_updated_at": timestamp,
        "updated_at": timestamp,
        "follow_up_overdue": False,
    }

    update_fields["status"] = _derive_status_from_stage(next_stage, document.get("status"))
    if next_stage == "waiting_parts":
        update_fields["waiting_parts_since"] = timestamp
    elif next_stage != "waiting_parts":
        update_fields["waiting_parts_since"] = None

    if next_stage == "ready_for_driver_test":
        update_fields["ready_for_driver_test_since"] = timestamp
        update_fields["ready_for_driver_test_notified_at"] = None
        update_fields["driver_test_reminder_sent_for"] = None
        update_type = "ready_for_test" if update_type == "general" else update_type
    elif next_stage != "ready_for_driver_test":
        update_fields["ready_for_driver_test_since"] = None

    if "actual_cost" in payload:
        update_fields["actual_cost"] = _validate_non_negative_amount(payload.get("actual_cost"), "actual_cost")
    if "estimated_cost" in payload:
        update_fields["estimated_cost"] = _validate_non_negative_amount(
            payload.get("estimated_cost"), "estimated_cost"
        )

    maintenance_jobs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)

    progress_document = {
        "maintenance_job_id": document["_id"],
        "update_type": update_type,
        "progress_note": progress_note,
        "current_stage": document.get("current_stage"),
        "next_action": document.get("next_action"),
        "next_follow_up_date": document.get("next_follow_up_date"),
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "updated_at": timestamp,
    }
    result = maintenance_progress_collection().insert_one(progress_document)
    progress_document["_id"] = result.inserted_id

    if document.get("current_stage") == "ready_for_driver_test" and document.get("driver_id"):
        _create_user_notification(
            document.get("driver_id"),
            title="Vehicle Ready For Driver Test",
            message=f"Your assigned vehicle is ready to test after maintenance: {document.get('title')}.",
            priority="medium",
            reference_id=document["_id"],
        )
        maintenance_jobs_collection().update_one(
            {"_id": document["_id"]},
            {"$set": {"ready_for_driver_test_notified_at": timestamp}},
        )
        document["ready_for_driver_test_notified_at"] = timestamp

    _process_maintenance_reminders([document])
    return _serialize_progress_timeline_entry(progress_document)


def submit_driver_maintenance_confirmation(
    maintenance_id: str,
    payload: dict,
    current_user_id: str,
) -> dict:
    document = _get_driver_accessible_maintenance_document(maintenance_id, current_user_id)
    if document.get("current_stage") != "ready_for_driver_test":
        raise ApiError("Driver confirmation is only available when the vehicle is ready for driver test.", status_code=403)
    allowed_fields = {"driver_confirmation", "driver_note"}
    if set(payload.keys()) - allowed_fields:
        raise ApiError("You do not have permission to submit that type of maintenance update.", status_code=403)

    driver_confirmation = (payload.get("driver_confirmation") or "").strip().lower()
    if driver_confirmation not in {"confirmed", "rejected"}:
        raise ApiError("driver_confirmation must be either confirmed or rejected.", status_code=400)

    driver_note = (payload.get("driver_note") or "").strip()
    progress_note = driver_note
    if not progress_note:
        progress_note = (
            "Driver confirmed that the vehicle repair was successful."
            if driver_confirmation == "confirmed"
            else "Driver reported that the vehicle still needs more work."
        )

    timestamp = now_utc()
    next_follow_up_date = date.today().isoformat()
    update_fields = {
        "last_progress_updated_at": timestamp,
        "updated_at": timestamp,
        "follow_up_overdue": False,
        "next_follow_up_date": next_follow_up_date,
    }
    if driver_confirmation == "confirmed":
        update_fields["current_stage"] = "driver_confirmed"
        update_fields["next_action"] = "Admin or owner to close the maintenance job after confirmation."
    else:
        update_fields["current_stage"] = "delayed"
        update_fields["status"] = "in_progress"
        update_fields["next_action"] = "Coordinator to reopen diagnosis after failed driver test."

    maintenance_jobs_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)

    progress_document = {
        "maintenance_job_id": document["_id"],
        "update_type": "general",
        "progress_note": progress_note,
        "current_stage": document.get("current_stage"),
        "next_action": document.get("next_action"),
        "next_follow_up_date": document.get("next_follow_up_date"),
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "updated_at": timestamp,
    }
    result = maintenance_progress_collection().insert_one(progress_document)
    progress_document["_id"] = result.inserted_id

    _process_maintenance_reminders([document])
    return _serialize_driver_progress_timeline_entry(progress_document)


def convert_fault_to_maintenance_job(fault_id: str, current_user_id: str, current_role: str) -> dict:
    fault_document = _get_fault_document(fault_id)
    if fault_document.get("status") != "approved":
        raise ApiError("Only approved faults can be converted to maintenance.", status_code=400)
    if fault_document.get("maintenance_job_id"):
        raise ApiError("This fault has already been converted to a maintenance job.", status_code=400)

    category_name = "Repair"
    component_name = "Fault"
    category_document = fault_categories_collection().find_one({"_id": fault_document.get("category_id")})
    component_document = fault_components_collection().find_one({"_id": fault_document.get("component_id")})
    if category_document:
        category_name = category_document.get("name") or category_name
    if component_document:
        component_name = component_document.get("name") or component_name

    payload = {
        "vehicle_id": str(fault_document.get("vehicle_id")),
        "driver_id": str(fault_document.get("driver_id")) if fault_document.get("driver_id") else None,
        "fault_report_id": str(fault_document["_id"]),
        "maintenance_type": "repair",
        "title": f"{category_name} - {component_name}",
        "description": fault_document.get("description") or "Converted from approved fault report.",
        "priority": fault_document.get("severity") or "medium",
        "status": "pending",
        "current_stage": "assigned_to_mechanic",
        "notes": fault_document.get("admin_notes") or None,
        "next_action": "Assign mechanic/workshop and start diagnosis.",
    }
    return create_maintenance_job(payload, current_user_id=current_user_id, current_role=current_role)
