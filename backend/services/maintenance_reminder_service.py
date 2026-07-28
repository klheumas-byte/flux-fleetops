"""Bounded, idempotent maintenance reminder reconciliation.

This is intentionally invoked by an external scheduler/CLI command rather
than by maintenance or preventive-maintenance read endpoints.
"""
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from services.notification_service import create_notification


def _now():
    return datetime.now(timezone.utc)


def _collection(name):
    return get_collection(name)


def _object_ids(values):
    return {value for value in values if isinstance(value, ObjectId)}


def _user_map(ids):
    ids = list(_object_ids(ids))
    if not ids:
        return {}
    return {item["_id"]: item for item in _collection("users").find(
        {"_id": {"$in": ids}, "status": "active"},
        {"_id": 1, "role": 1, "full_name": 1},
    )}


def _notify(recipient_id, *, title, message, priority, reference_type,
            reference_id, action_type=None, action_url=None, action_label=None,
            due_at=None):
    if not isinstance(recipient_id, ObjectId):
        return False
    dedupe_key = f"{reference_type}:{reference_id}:{action_type or title.strip().lower()}"
    existing = _collection("notifications").find_one(
        {
            "recipient_user_id": recipient_id,
            "dedupe_key": dedupe_key,
            "status": {"$nin": ["completed", "cancelled", "expired", "dismissed"]},
        },
        {"_id": 1},
    )
    if existing:
        return False
    create_notification(
        recipient_user_id=recipient_id,
        title=title,
        message=message,
        category="maintenance",
        priority=priority,
        reference_type=reference_type,
        reference_id=reference_id,
        action_type=action_type,
        action_url=action_url,
        action_label=action_label,
        due_at=due_at,
        dedupe_key=dedupe_key,
    )
    return True


def _acquire_lease(now, lease_seconds=600):
    locks = _collection("maintenance_sweep_locks")
    try:
        return locks.find_one_and_update(
            {
                "_id": "maintenance-reminder-sweep",
                "$or": [{"lease_until": {"$lt": now}}, {"lease_until": {"$exists": False}}],
            },
            {"$set": {"lease_until": now + timedelta(seconds=lease_seconds), "updated_at": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return None


def _release_lease(now):
    _collection("maintenance_sweep_locks").update_one(
        {"_id": "maintenance-reminder-sweep"},
        {"$set": {"lease_until": now, "updated_at": now}},
    )


def run_maintenance_reminder_sweep(*, batch_size=50, schedule_ids=None):
    """Process at most ``batch_size`` records per source collection."""
    batch_size = max(1, min(int(batch_size or 50), 250))
    now = _now()
    lease = _acquire_lease(now)
    if lease is None:
        return {"skipped": True, "reason": "another sweep holds the lease"}

    summary = {"skipped": False, "schedules": 0, "maintenance_jobs": 0,
               "movements": 0, "overrides_expired": 0, "notifications": 0, "errors": 0}
    try:
        # Date-driven schedule reminders intentionally do not resolve odometers.
        # Missing mileage therefore falls back to the time rule.
        schedule_query = {
            "status": {"$nin": ["paused", "completed"]},
            "next_due_date": {"$lte": (date.today() + timedelta(days=31)).isoformat()},
        }
        if schedule_ids:
            schedule_query["_id"] = {"$in": [item for item in schedule_ids if isinstance(item, ObjectId)]}
        schedules = list(_collection("preventive_maintenance").find(
            schedule_query,
            {"_id": 1, "vehicle_id": 1, "assigned_admin_id": 1, "title": 1,
             "next_due_date": 1, "warning_days_before": 1, "status": 1,
             "last_notification_status": 1},
        ).limit(batch_size))
        vehicle_ids = _object_ids(item.get("vehicle_id") for item in schedules)
        vehicles = {item["_id"]: item for item in _collection("vehicles").find(
            {"_id": {"$in": list(vehicle_ids)}}, {"_id": 1, "assigned_driver_id": 1, "registration_number": 1}
        )} if vehicle_ids else {}
        users = _user_map(
            [item.get("assigned_admin_id") for item in schedules]
            + [vehicles.get(item.get("vehicle_id"), {}).get("assigned_driver_id") for item in schedules]
        )
        for item in schedules:
            try:
                due_date = item.get("next_due_date")
                if not due_date:
                    continue
                warning_days = int(item.get("warning_days_before") or 0)
                if due_date < date.today().isoformat():
                    status = "overdue"
                elif due_date == date.today().isoformat():
                    status = "due"
                elif due_date <= (date.today() + timedelta(days=warning_days)).isoformat():
                    status = "due_soon"
                else:
                    continue
                marker = f"{status}:{date.today().isoformat()}"
                if item.get("last_notification_status") == marker:
                    continue
                vehicle = vehicles.get(item.get("vehicle_id"), {})
                label = vehicle.get("registration_number") or "vehicle"
                priority = "high" if status in {"due", "overdue"} else "medium"
                action = "generate_maintenance_job" if status in {"due", "overdue"} else None
                action_url = "preventive-maintenance" if action else None
                for recipient in (item.get("assigned_admin_id"), vehicle.get("assigned_driver_id")):
                    if recipient not in users:
                        continue
                    created = _notify(
                        recipient,
                        title="Preventive Maintenance Alert",
                        message=f"{label} is {status.replace('_', ' ')} for {item.get('title') or 'scheduled service'}.",
                        priority=priority,
                        reference_type="preventive_maintenance",
                        reference_id=item["_id"],
                        action_type=action if recipient == item.get("assigned_admin_id") else None,
                        action_url=action_url if recipient == item.get("assigned_admin_id") else None,
                        action_label="Generate maintenance job" if action else None,
                        due_at=due_date,
                    )
                    if created:
                        summary["notifications"] += 1
                _collection("preventive_maintenance").update_one(
                    {"_id": item["_id"]}, {"$set": {"last_notification_status": marker, "updated_at": now}}
                )
                summary["schedules"] += 1
            except Exception:
                summary["errors"] += 1

        jobs = list(_collection("maintenance_jobs").find(
            {"status": {"$nin": ["completed", "cancelled"]},
             "next_follow_up_date": {"$lt": date.today().isoformat()}},
            {"_id": 1, "title": 1, "maintenance_coordinator_id": 1, "next_follow_up_date": 1},
        ).limit(batch_size))
        coordinators = _user_map(item.get("maintenance_coordinator_id") for item in jobs)
        for item in jobs:
            try:
                recipient = item.get("maintenance_coordinator_id")
                if recipient not in coordinators:
                    continue
                created = _notify(
                    recipient,
                    title="Maintenance Follow-up Overdue",
                    message=f"Maintenance job {item.get('title') or item['_id']} has an overdue follow-up.",
                    priority="high",
                    reference_type="maintenance",
                    reference_id=item["_id"],
                    action_type="resolve_overdue_follow_up",
                    action_url="maintenance",
                    action_label="Review maintenance job",
                    due_at=item.get("next_follow_up_date"),
                )
                if created:
                    summary["notifications"] += 1
                summary["maintenance_jobs"] += 1
            except Exception:
                summary["errors"] += 1

        movements = list(_collection("vehicle_movements").find(
            {"completion_status": "awaiting_admin_verification"},
            {"_id": 1, "movement_id": 1, "maintenance_job_id": 1},
        ).limit(batch_size))
        admin_ids = [item["_id"] for item in _collection("users").find(
            {"role": {"$in": ["owner", "admin"]}, "status": "active"}, {"_id": 1}
        ).limit(batch_size)]
        for item in movements:
            try:
                for recipient in admin_ids:
                    created = _notify(
                        recipient,
                        title="Maintenance Completion Awaiting Review",
                        message=f"Movement {item.get('movement_id') or item['_id']} has maintenance work awaiting verification.",
                        priority="high",
                        reference_type="vehicle_movement",
                        reference_id=item["_id"],
                        action_type="approve_maintenance_completion",
                        action_url="vehicle-movements",
                        action_label="Review completion",
                    )
                    if created:
                        summary["notifications"] += 1
                summary["movements"] += 1
            except Exception:
                summary["errors"] += 1

        # Driver/custodian actions are reconciled separately so an admin
        # verification reminder cannot suppress an acceptance or correction
        # reminder for the same movement.
        pending_tasks = list(_collection("vehicle_movements").find(
            {
                "movement_type": {"$in": ["maintenance", "workshop"]},
                "custodian_response_status": "pending",
            },
            {"_id": 1, "movement_id": 1, "movement_custodian_id": 1, "driver_id": 1},
        ).limit(batch_size))
        task_users = _user_map(
            [item.get("movement_custodian_id") or item.get("driver_id") for item in pending_tasks]
        )
        for item in pending_tasks:
            try:
                recipient = item.get("movement_custodian_id") or item.get("driver_id")
                if recipient not in task_users:
                    continue
                if _notify(
                    recipient,
                    title="Maintenance Task Awaiting Acceptance",
                    message=f"Maintenance movement {item.get('movement_id') or item['_id']} is awaiting your acceptance.",
                    priority="high",
                    reference_type="vehicle_movement",
                    reference_id=item["_id"],
                    action_type="accept_maintenance_task",
                    action_url="my-vehicle",
                    action_label="Accept maintenance task",
                ):
                    summary["notifications"] += 1
            except Exception:
                summary["errors"] += 1

        corrections = list(_collection("vehicle_movements").find(
            {"completion_status": "returned_for_correction"},
            {"_id": 1, "movement_id": 1, "movement_custodian_id": 1, "driver_id": 1},
        ).limit(batch_size))
        correction_users = _user_map(
            [item.get("movement_custodian_id") or item.get("driver_id") for item in corrections]
        )
        for item in corrections:
            try:
                recipient = item.get("movement_custodian_id") or item.get("driver_id")
                if recipient not in correction_users:
                    continue
                if _notify(
                    recipient,
                    title="Maintenance Completion Needs Correction",
                    message=f"Maintenance movement {item.get('movement_id') or item['_id']} needs a response.",
                    priority="high",
                    reference_type="vehicle_movement",
                    reference_id=item["_id"],
                    action_type="respond_to_correction",
                    action_url="my-vehicle",
                    action_label="Respond to correction",
                ):
                    summary["notifications"] += 1
            except Exception:
                summary["errors"] += 1

        overdue_workshop = list(_collection("vehicle_movements").find(
            {
                "movement_type": {"$in": ["maintenance", "workshop"]},
                "expected_return_time": {"$lt": now},
                "actual_return_time": {"$exists": False},
                "status": {"$nin": ["completed", "cancelled", "rejected"]},
            },
            {"_id": 1, "movement_id": 1, "expected_return_time": 1},
        ).limit(batch_size))
        for item in overdue_workshop:
            try:
                for recipient in admin_ids:
                    if _notify(
                        recipient,
                        title="Vehicle Overdue From Workshop",
                        message=f"Movement {item.get('movement_id') or item['_id']} is overdue from workshop.",
                        priority="high",
                        reference_type="vehicle_movement",
                        reference_id=item["_id"],
                        action_type="confirm_vehicle_return",
                        action_url="vehicle-movements",
                        action_label="Confirm vehicle return",
                        due_at=item.get("expected_return_time"),
                    ):
                        summary["notifications"] += 1
            except Exception:
                summary["errors"] += 1
        try:
            from services.maintenance_override_service import reconcile_expired_overrides
            summary["overrides_expired"] = reconcile_expired_overrides()
        except Exception:
            summary["errors"] += 1
        return summary
    finally:
        try:
            _release_lease(_now())
        except Exception:
            pass
