from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging

from bson import ObjectId
from flask import current_app, has_app_context
from pymongo import ASCENDING, DESCENDING, UpdateOne

from extensions import get_collection
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


LOGGER = logging.getLogger(__name__)
_NOTIFICATION_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="notification-events"
)
_SIDEBAR_COUNT_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="sidebar-counts")
ACTION_PENDING_STATUSES = {"action_pending", "pending_action", "snoozed"}
ACTIVE_STATES = {"unread", "viewed", *ACTION_PENDING_STATUSES}
VALID_STATES = ACTIVE_STATES | {"completed", "dismissed", "cancelled", "expired"}
VALID_TYPES = {"info", "reminder", "action_required", "success", "critical"}


def now_utc():
    return datetime.now(timezone.utc)


def _serialize_datetime(value):
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def notifications_collection():
    return get_collection("notifications")


def users_collection():
    return get_collection("users")


def _to_object_id(value, field_name: str):
    if not value or not ObjectId.is_valid(value):
        raise ApiError(f"Invalid {field_name}.", status_code=400)
    return ObjectId(value)


def _default_type(priority: str, required_action) -> str:
    if priority == "critical":
        return "critical"
    if required_action:
        return "action_required"
    if priority in {"high", "medium"}:
        return "reminder"
    return "info"


def serialize_notification(document: dict) -> dict:
    state = document.get("state")
    if not state:
        state = "viewed" if document.get("is_read") else "unread"
    return {
        "id": str(document.get("_id")),
        "title": document.get("title"),
        "message": document.get("message"),
        "description": document.get("message"),
        "category": document.get("category"),
        "module": document.get("module") or document.get("category"),
        "priority": document.get("priority", "low"),
        "notification_type": document.get("notification_type")
        or _default_type(document.get("priority"), document.get("required_action")),
        "reference_type": document.get("reference_type"),
        "reference_id": str(document.get("reference_id"))
        if document.get("reference_id")
        else None,
        "entity": document.get("entity_type") or document.get("entity"),
        "entity_type": document.get("entity_type") or document.get("entity") or document.get("reference_type"),
        "entity_id": str(document.get("entity_id") or document.get("reference_id")) if (document.get("entity_id") or document.get("reference_id")) else None,
        "state": state,
        "status": state,
        "required_action": document.get("action_type") or document.get("required_action"),
        "action_type": document.get("action_type") or document.get("required_action"),
        "action_url": document.get("action_url"),
        "action_label": document.get("action_label"),
        "is_read": bool(document.get("is_read")),
        "scheduled_for": _serialize_datetime(document.get("scheduled_for")),
        "snoozed_until": _serialize_datetime(document.get("snoozed_until")),
        "expires_at": _serialize_datetime(document.get("expires_at") or document.get("due_at")),
        "due_at": _serialize_datetime(document.get("due_at") or document.get("expires_at")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
        "completed_at": _serialize_datetime(document.get("completed_at")),
        "completed_by": str(document.get("completed_by")) if document.get("completed_by") else None,
    }


def ensure_notification_indexes():
    ensure_indexes_for_collection(
        notifications_collection(),
        [
            {"keys": [("recipient_user_id", ASCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("is_read", ASCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("state", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("status", ASCENDING), ("priority", ASCENDING), ("due_at", ASCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("status", ASCENDING), ("notification_type", ASCENDING), ("priority", ASCENDING), ("due_at", ASCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("status", ASCENDING), ("completed_at", DESCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("dedupe_key", ASCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("action_key", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("category", ASCENDING)]},
            {"keys": [("priority", ASCENDING)]},
            {"keys": [("scheduled_for", ASCENDING)]},
            {"keys": [("due_at", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
        ],
        collection_name="notifications",
    )


def reconcile_legacy_actionable_notifications() -> dict:
    """Add action metadata to legacy notifications only when the linked record still needs work."""
    collection = notifications_collection()
    legacy = list(collection.find(
        {"action_type": {"$exists": False}, "reference_id": {"$ne": None}},
        {"recipient_user_id": 1, "reference_type": 1, "reference_id": 1, "created_at": 1},
    ))
    if not legacy:
        return {"reviewed": 0, "activated": 0, "duplicates_dismissed": 0}

    rules = {
        "maintenance": ("maintenance_jobs", {"status": {"$nin": ["completed", "cancelled"]}}, "manage_maintenance_job", "maintenance", "Review maintenance job"),
        "preventive_maintenance": ("preventive_maintenance", {"status": {"$in": ["due", "overdue"]}}, "generate_maintenance_job", "preventive-maintenance", "Generate maintenance job"),
        "incident": ("incidents", {"status": {"$nin": ["resolved", "rejected", "closed"]}}, "review_incident", "incidents", "Review incident"),
        "fuel_log": ("fuel_logs", {"status": "submitted"}, "review_fuel_log", "fuel", "Review fuel log"),
        "fault": ("faults", {"status": {"$in": ["reported", "under_review"]}}, "review_fault", "fault-approvals", "Review fault"),
        "dispatch_opportunity": ("dispatch_opportunities", {"status": {"$in": ["submitted", "under_review"]}}, "review_opportunity", "dispatch-opportunities", "Review opportunity"),
        "dispatch_job": ("dispatch_jobs", {"status": "assigned", "driver_response_status": {"$in": [None, "pending"]}}, "accept_dispatch", "my-dispatches", "Review dispatch"),
    }
    active_ids = {}
    for reference_type, (collection_name, state_query, *_rest) in rules.items():
        ids = list({item.get("reference_id") for item in legacy if item.get("reference_type") == reference_type and item.get("reference_id")})
        if not ids:
            active_ids[reference_type] = set()
            continue
        active_ids[reference_type] = {
            item["_id"] for item in get_collection(collection_name).find({"_id": {"$in": ids}, **state_query}, {"_id": 1})
        }

    operations = []
    activated_keys = set()
    activated = 0
    duplicates = 0
    for item in sorted(legacy, key=lambda value: (value.get("created_at").timestamp() if isinstance(value.get("created_at"), datetime) else 0), reverse=True):
        reference_type = item.get("reference_type")
        rule = rules.get(reference_type)
        if not rule or item.get("reference_id") not in active_ids.get(reference_type, set()):
            continue
        _collection_name, _query, action_type, action_url, action_label = rule
        action_key = f"{reference_type}:{item.get('reference_id')}:{action_type}"
        recipient_key = (item.get("recipient_user_id"), action_key)
        if recipient_key in activated_keys:
            operations.append(UpdateOne({"_id": item["_id"]}, {"$set": {"action_type": action_type, "action_key": action_key, "status": "dismissed", "state": "dismissed", "is_read": True, "updated_at": now_utc(), "resolution_source": "legacy_duplicate"}}))
            duplicates += 1
            continue
        activated_keys.add(recipient_key)
        operations.append(UpdateOne({"_id": item["_id"]}, {"$set": {
            "entity_type": reference_type,
            "entity_id": item.get("reference_id"),
            "action_type": action_type,
            "required_action": action_type,
            "action_url": action_url,
            "action_label": action_label,
            "action_key": action_key,
            "dedupe_key": action_key,
            "notification_type": "action_required",
            "status": "action_pending",
            "state": "action_pending",
            "updated_at": now_utc(),
        }}))
        activated += 1
    if operations:
        collection.bulk_write(operations, ordered=False)
    LOGGER.info("Legacy notification reconciliation reviewed=%s activated=%s duplicates_dismissed=%s", len(legacy), activated, duplicates)
    return {"reviewed": len(legacy), "activated": activated, "duplicates_dismissed": duplicates}


def _run_safely(app, callback, *args, **kwargs):
    try:
        with app.app_context():
            callback(*args, **kwargs)
    except Exception:
        LOGGER.exception("Notification event failed without affecting the business action.")


def _submit(callback, *args, **kwargs):
    if not has_app_context():
        try:
            callback(*args, **kwargs)
        except Exception:
            LOGGER.exception("Notification event failed outside an application context.")
        return
    app = current_app._get_current_object()
    _NOTIFICATION_EXECUTOR.submit(_run_safely, app, callback, *args, **kwargs)


def _store_notification(payload: dict):
    collection = notifications_collection()
    dedupe_key = payload.get("dedupe_key")
    if dedupe_key:
        existing = collection.find_one(
            {
                "recipient_user_id": payload["recipient_user_id"],
                "dedupe_key": dedupe_key,
                "$or": [
                    {"state": {"$in": list(ACTIVE_STATES)}},
                    {"state": {"$exists": False}, "is_read": False},
                ],
            },
            {"_id": 1},
        )
        if existing:
            payload.pop("created_at", None)
            payload["updated_at"] = now_utc()
            collection.update_one({"_id": existing["_id"]}, {"$set": payload})
            return
    collection.insert_one(payload)


def create_notification(
    recipient_user_id: ObjectId,
    title: str,
    message: str,
    *,
    category: str,
    priority: str,
    reference_type: str,
    reference_id: ObjectId,
    notification_type: str | None = None,
    module: str | None = None,
    entity: str | None = None,
    state: str | None = None,
    required_action: str | None = None,
    action_type: str | None = None,
    action_url: str | None = None,
    action_label: str | None = None,
    dedupe_key: str | None = None,
    scheduled_for: datetime | None = None,
    expires_at: datetime | None = None,
    due_at: datetime | None = None,
    metadata: dict | None = None,
):
    """Queue an in-app notification. Failure never fails the originating action."""
    resolved_action = action_type or required_action
    resolved_type = notification_type if notification_type in VALID_TYPES else _default_type(priority, resolved_action)
    resolved_state = state if state in VALID_STATES else ("action_pending" if resolved_action else "unread")
    resolved_dedupe_key = dedupe_key or f"{reference_type}:{reference_id}:{resolved_action or title.strip().lower()}"
    payload = {
        "recipient_user_id": recipient_user_id,
        "title": title,
        "message": message,
        "category": category,
        "module": module or category,
        "priority": priority,
        "notification_type": resolved_type,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "entity": entity or reference_type,
        "entity_type": entity or reference_type,
        "entity_id": reference_id,
        "state": resolved_state,
        "status": resolved_state,
        "required_action": resolved_action,
        "action_type": resolved_action,
        "action_url": action_url,
        "action_label": action_label,
        "dedupe_key": resolved_dedupe_key,
        "action_key": resolved_dedupe_key if resolved_action else None,
        "scheduled_for": scheduled_for,
        "expires_at": expires_at,
        "due_at": due_at or expires_at,
        "metadata": metadata or {},
        "delivery_channels": ["in_app"],
        "is_read": False,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    _submit(_store_notification, payload)


def _notify_roles(roles: list[str], payload: dict):
    recipients = users_collection().find(
        {"role": {"$in": roles}, "status": "active"}, {"_id": 1}
    )
    for recipient in recipients:
        _store_notification({**payload, "recipient_user_id": recipient["_id"]})


def notify_roles(roles: list[str], title: str, message: str, **kwargs):
    resolved_type = kwargs.pop("notification_type", None)
    priority = kwargs.get("priority", "low")
    required_action = kwargs.pop("action_type", None) or kwargs.pop("required_action", None)
    state = kwargs.pop("state", None)
    category = kwargs.get("category", "system")
    reference_type = kwargs.get("reference_type", "system")
    reference_id = kwargs.get("reference_id", "global")
    dedupe_key = kwargs.pop("dedupe_key", None) or f"{reference_type}:{reference_id}:{title.strip().lower()}"
    payload = {
        **kwargs,
        "title": title,
        "message": message,
        "module": kwargs.pop("module", category),
        "notification_type": resolved_type if resolved_type in VALID_TYPES else _default_type(priority, required_action),
        "state": state if state in VALID_STATES else ("action_pending" if required_action else "unread"),
        "status": state if state in VALID_STATES else ("action_pending" if required_action else "unread"),
        "required_action": required_action,
        "action_type": required_action,
        "dedupe_key": dedupe_key,
        "action_key": dedupe_key if required_action else None,
        "entity": kwargs.pop("entity", kwargs.get("reference_type")),
        "entity_type": kwargs.get("reference_type"),
        "entity_id": kwargs.get("reference_id"),
        "due_at": kwargs.get("due_at") or kwargs.get("expires_at"),
        "delivery_channels": ["in_app"],
        "is_read": False,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    _submit(_notify_roles, roles, payload)


def list_notifications_page(current_user_id: str, *, page=1, page_size=50, filters=None) -> dict:
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    query = {"recipient_user_id": user_object_id}
    filters = filters or {}
    for key in ("category", "module", "priority"):
        if filters.get(key):
            query[key] = filters[key]
    if filters.get("state") == "needs_action":
        actionable = _actionable_query(user_object_id)
        query.update({key: value for key, value in actionable.items() if key != "recipient_user_id"})
    elif filters.get("state"):
        query["state"] = filters["state"]
    if filters.get("unread_only"):
        query["is_read"] = False
    if filters.get("q"):
        escaped = __import__("re").escape(filters["q"][:100])
        query["$or"] = [{"title": {"$regex": escaped, "$options": "i"}}, {"message": {"$regex": escaped, "$options": "i"}}]
    collection = notifications_collection()
    total = collection.count_documents(query)
    cursor = collection.find(query).sort([("created_at", DESCENDING)]).skip((page - 1) * page_size).limit(page_size)
    unread_count = collection.count_documents({"recipient_user_id": user_object_id, "is_read": False})
    notification_counts = actionable_notification_counts(current_user_id)
    return {
        "notifications": [serialize_notification(item) for item in cursor],
        "pagination": {"page": page, "page_size": page_size, "total": total, "has_more": page * page_size < total},
        "counts": {"unread": unread_count, "pending_action": notification_counts["total_actionable"], **notification_counts},
    }


def _actionable_query(user_object_id: ObjectId) -> dict:
    active_statuses = ["unread", "viewed", "action_pending", "pending_action", "snoozed", "reminder", "critical"]
    return {
        "recipient_user_id": user_object_id,
        "$and": [
            {"$or": [{"action_type": {"$exists": True, "$ne": None}}, {"required_action": {"$exists": True, "$ne": None}}]},
            {"$or": [{"status": {"$in": active_statuses}}, {"status": {"$exists": False}, "state": {"$in": active_statuses}}]},
            {"$or": [{"due_at": {"$exists": False}}, {"due_at": None}, {"due_at": {"$gt": now_utc()}}]},
        ],
    }


def actionable_notification_counts(current_user_id: str) -> dict:
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    today_start = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    active_match = _actionable_query(user_object_id)
    rows = list(notifications_collection().aggregate([
        {"$match": {"recipient_user_id": user_object_id}},
        {"$facet": {
            "active": [
                {"$match": {key: value for key, value in active_match.items() if key != "recipient_user_id"}},
                {"$group": {
                    "_id": None,
                    "total_actionable": {"$sum": 1},
                    "critical": {"$sum": {"$cond": [{"$or": [{"$eq": ["$notification_type", "critical"]}, {"$eq": ["$priority", "critical"]}]}, 1, 0]}},
                    "reminders": {"$sum": {"$cond": [{"$eq": ["$notification_type", "reminder"]}, 1, 0]}},
                }},
            ],
            "completed_today": [
                {"$match": {"status": "completed", "completed_at": {"$gte": today_start}}},
                {"$count": "count"},
            ],
        }},
    ]))
    result = rows[0] if rows else {}
    active = (result.get("active") or [{}])[0]
    total = int(active.get("total_actionable") or 0)
    critical = int(active.get("critical") or 0)
    reminders = int(active.get("reminders") or 0)
    action_required = max(0, total - critical - reminders)
    completed_today = int(((result.get("completed_today") or [{}])[0]).get("count") or 0)
    highest_priority = "critical" if critical else "action_required" if action_required else "reminder" if reminders else None
    return {
        "critical": critical,
        "action_required": action_required,
        "reminders": reminders,
        "total_actionable": total,
        "completed_today": completed_today,
        "highest_priority": highest_priority,
    }


def actionable_notification_count(current_user_id: str) -> int:
    return actionable_notification_counts(current_user_id)["total_actionable"]


def _module_count(collection_name: str, query: dict, *, critical_query=None, reminder_query=None) -> dict:
    collection = get_collection(collection_name)
    count = collection.count_documents(query)
    critical = collection.count_documents({"$and": [query, critical_query]}) if count and critical_query else 0
    reminders = collection.count_documents({"$and": [query, reminder_query]}) if count and reminder_query else 0
    priority = "critical" if critical else "action_required" if count > reminders else "reminder" if reminders else None
    return {"status": "ok", "count": count, "priority": priority, "critical_count": critical}


def sidebar_work_queue_counts(current_user_id: str, current_role: str) -> dict:
    """Return role-scoped sidebar counts without hydrating module records."""
    user_id = _to_object_id(current_user_id, "current_user_id")
    role = (current_role or "").strip().lower()
    now = now_utc()
    jobs_active = {"$nin": ["completed", "cancelled"]}
    definitions = {}

    if role in {"owner", "admin", "dispatcher", "customer_service"}:
        definitions["dispatch_requests"] = lambda: _module_count(
            "dispatch_requests",
            {"$or": [
                {"pricing_status": "pricing_pending"},
                {"status": "reviewing"},
                {"status": "approved", "planning_status": {"$in": [None, "unplanned", "rejected", "clarification_requested"]}, "active_dispatch_job_id": {"$in": [None]}},
            ]},
        )
        definitions["dispatch_planner"] = lambda: _module_count(
            "dispatch_jobs",
            {"$or": [
                {"$and": [{"status": {"$in": ["draft", "reserved"]}}, {"$or": [{"vehicle_id": None}, {"driver_id": None}]}]},
                {"status": "assigned", "driver_response_status": {"$in": [None, "pending"]}},
            ]},
            critical_query={"scheduled_start_time": {"$ne": None, "$lt": now}},
        )
        definitions["vehicle_return"] = lambda: _module_count(
            "dispatch_jobs",
            {"status": "completed", "return_status": {"$in": [None, "awaiting_return", "returned", "inspection_completed"]}},
            critical_query={"expected_return_time": {"$ne": None, "$lt": now}},
        )

    if role in {"owner", "admin"}:
        definitions["maintenance_jobs"] = lambda: _module_count(
            "maintenance_jobs",
            {"status": jobs_active},
            critical_query={"$or": [{"priority": "critical"}, {"is_overdue": True}]},
            reminder_query={"follow_up_overdue": True},
        )
        definitions["preventive_maintenance"] = lambda: _module_count(
            "preventive_maintenance",
            {"status": {"$in": ["due", "overdue", "due_soon"]}},
            critical_query={"status": "overdue"},
            reminder_query={"status": "due_soon"},
        )
        definitions["fault_approvals"] = lambda: _module_count(
            "faults",
            {"status": {"$in": ["reported", "under_review"]}},
            critical_query={"severity": "critical"},
        )
        definitions["accidents_incidents"] = lambda: _module_count(
            "incidents",
            {"status": {"$nin": ["resolved", "rejected", "closed"]}},
            critical_query={"$or": [{"severity": "critical"}, {"vehicle_status_after_incident": "out_of_service"}]},
        )

    if role == "driver":
        definitions["dispatch_planner"] = lambda: _module_count(
            "dispatch_jobs",
            {"driver_id": user_id, "status": {"$in": ["assigned", "clarification_requested"]}},
            critical_query={"scheduled_start_time": {"$ne": None, "$lt": now}},
        )
        definitions["vehicle_return"] = lambda: _module_count(
            "dispatch_jobs",
            {"driver_id": user_id, "status": "completed", "return_status": {"$in": [None, "awaiting_return"]}},
            critical_query={"expected_return_time": {"$ne": None, "$lt": now}},
        )
        definitions["maintenance_jobs"] = lambda: _module_count(
            "maintenance_jobs",
            {"driver_id": user_id, "status": jobs_active, "current_stage": {"$in": ["assigned_to_mechanic", "ready_for_driver_test", "delayed"]}},
            critical_query={"$or": [{"priority": "critical"}, {"is_overdue": True}]},
        )

    def notification_sidebar_count():
        counts = actionable_notification_counts(current_user_id)
        latest = notifications_collection().find_one(
            _actionable_query(user_id),
            {"_id": 1, "created_at": 1, "notification_type": 1, "priority": 1},
            sort=[("created_at", DESCENDING)],
        )
        return {
            "status": "ok",
            "count": counts["total_actionable"],
            "priority": counts["highest_priority"],
            "critical_count": counts["critical"],
            "latest_actionable": {
                "id": str(latest["_id"]),
                "created_at": latest.get("created_at").isoformat() if latest.get("created_at") else None,
                "priority": (
                    "critical" if latest.get("notification_type") == "critical" or latest.get("priority") == "critical"
                    else "reminder" if latest.get("notification_type") == "reminder"
                    else "action_required"
                ),
            } if latest else None,
        }

    definitions["notifications"] = notification_sidebar_count

    modules = {}
    app = current_app._get_current_object()
    def run_with_context(callback):
        with app.app_context():
            return callback()
    futures = {_SIDEBAR_COUNT_EXECUTOR.submit(run_with_context, callback): name for name, callback in definitions.items()}
    for future in as_completed(futures):
        name = futures[future]
        try:
            modules[name] = future.result()
        except Exception:
            LOGGER.exception("Sidebar work-queue count failed for %s.", name)
            modules[name] = {"status": "error", "count": None, "priority": None, "critical_count": None}

    rank = {None: 0, "reminder": 1, "action_required": 2, "critical": 3}
    successful = [item for item in modules.values() if item.get("status") == "ok"]
    return {
        "generated_at": now.isoformat(),
        "total_actionable": None,
        "highest_priority": max((item["priority"] for item in successful), key=lambda value: rank.get(value, 0), default=None),
        "sections": {},
        "modules": modules,
    }


def resolve_action_notifications(
    entity_type: str,
    entity_id,
    *,
    action_type: str | None = None,
    resolution: str = "completed",
    completed_by=None,
) -> int:
    """Resolve linked actions after a business transition; never fail that transition."""
    if resolution not in {"completed", "cancelled", "expired", "dismissed"}:
        return 0
    try:
        object_id = ObjectId(entity_id) if ObjectId.is_valid(str(entity_id)) else entity_id
        query = {
            "$and": [
                {"$or": [{"entity_type": entity_type, "entity_id": object_id}, {"reference_type": entity_type, "reference_id": object_id}]},
                {"$or": [{"status": {"$in": list(ACTION_PENDING_STATUSES)}}, {"state": {"$in": list(ACTION_PENDING_STATUSES)}}]},
            ]
        }
        if action_type:
            query["$and"].append({"$or": [{"action_type": action_type}, {"required_action": action_type}]})
        timestamp = now_utc()
        updates = {
            "status": resolution,
            "state": resolution,
            "is_read": True,
            "updated_at": timestamp,
            "completed_at": timestamp,
        }
        if completed_by and ObjectId.is_valid(str(completed_by)):
            updates["completed_by"] = ObjectId(completed_by)
        return notifications_collection().update_many(query, {"$set": updates}).modified_count
    except Exception:
        LOGGER.exception("Linked notifications could not be resolved after %s:%s.", entity_type, entity_id)
        return 0


def list_notifications(current_user_id: str, *, limit: int = 200) -> list[dict]:
    return list_notifications_page(current_user_id, page_size=min(limit, 100))["notifications"]


def mark_notification_as_read(notification_id: str, current_user_id: str) -> dict:
    notification_object_id = _to_object_id(notification_id, "notification_id")
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    notification = notifications_collection().find_one({"_id": notification_object_id, "recipient_user_id": user_object_id})
    if not notification:
        raise ApiError("Notification not found.", status_code=404)
    updates = {"is_read": True, "viewed_at": now_utc(), "updated_at": now_utc()}
    if notification.get("state") in {None, "unread"}:
        updates["state"] = "viewed"
    notifications_collection().update_one({"_id": notification_object_id}, {"$set": updates})
    notification.update(updates)
    return serialize_notification(notification)


def update_notification_state(notification_id: str, current_user_id: str, state: str, *, snoozed_until=None) -> dict:
    if state not in VALID_STATES:
        raise ApiError("Invalid notification state.", status_code=400)
    notification_object_id = _to_object_id(notification_id, "notification_id")
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    current = notifications_collection().find_one(
        {"_id": notification_object_id, "recipient_user_id": user_object_id},
        {"status": 1, "state": 1, "action_type": 1, "required_action": 1},
    )
    if not current:
        raise ApiError("Notification not found.", status_code=404)
    is_actionable = bool(current.get("action_type") or current.get("required_action")) and (
        current.get("status") in ACTION_PENDING_STATUSES or current.get("state") in ACTION_PENDING_STATUSES
    )
    if is_actionable and state in {"completed", "dismissed", "cancelled", "expired"}:
        raise ApiError("Complete or cancel the linked business action instead.", status_code=409)
    updates = {"state": state, "status": state, "updated_at": now_utc()}
    if state in {"viewed", "completed", "dismissed"}:
        updates["is_read"] = True
    if state == "completed":
        updates["completed_at"] = now_utc()
    if state == "snoozed":
        if not snoozed_until:
            raise ApiError("snoozed_until is required.", status_code=400)
        if isinstance(snoozed_until, str):
            try:
                snoozed_until = datetime.fromisoformat(snoozed_until.replace("Z", "+00:00"))
            except ValueError as error:
                raise ApiError("snoozed_until must be an ISO date.", status_code=400) from error
        updates["snoozed_until"] = snoozed_until
    notification = notifications_collection().find_one_and_update(
        {"_id": notification_object_id, "recipient_user_id": user_object_id},
        {"$set": updates}, return_document=True,
    )
    if not notification:
        raise ApiError("Notification not found.", status_code=404)
    return serialize_notification(notification)


def mark_all_notifications_as_read(current_user_id: str) -> int:
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    result = notifications_collection().update_many(
        {"recipient_user_id": user_object_id, "is_read": False},
        {"$set": {"is_read": True, "viewed_at": now_utc(), "updated_at": now_utc()}},
    )
    return result.modified_count


def administratively_resolve_notification(notification_id: str, current_user_id: str) -> dict:
    notification_object_id = _to_object_id(notification_id, "notification_id")
    resolver_id = _to_object_id(current_user_id, "current_user_id")
    timestamp = now_utc()
    notification = notifications_collection().find_one_and_update(
        {"_id": notification_object_id},
        {"$set": {
            "status": "completed",
            "state": "completed",
            "is_read": True,
            "completed_at": timestamp,
            "completed_by": resolver_id,
            "updated_at": timestamp,
            "resolution_source": "administrative",
        }},
        return_document=True,
    )
    if not notification:
        raise ApiError("Notification not found.", status_code=404)
    return serialize_notification(notification)


def delete_notification(notification_id: str, current_user_id: str) -> None:
    notification_object_id = _to_object_id(notification_id, "notification_id")
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    query = {"_id": notification_object_id, "recipient_user_id": user_object_id}
    current = notifications_collection().find_one(query, {"status": 1, "state": 1, "action_type": 1, "required_action": 1})
    if current and bool(current.get("action_type") or current.get("required_action")) and (
        current.get("status") in ACTION_PENDING_STATUSES or current.get("state") in ACTION_PENDING_STATUSES
    ):
        raise ApiError("Pending business actions cannot be archived.", status_code=409)
    result = notifications_collection().delete_one(query)
    if result.deleted_count == 0:
        raise ApiError("Notification not found.", status_code=404)
