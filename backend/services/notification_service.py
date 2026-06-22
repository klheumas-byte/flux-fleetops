from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


def now_utc():
    return datetime.now(timezone.utc)


def _serialize_datetime(value):
    if value is None:
        return None
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


def serialize_notification(notification_document: dict) -> dict:
    return {
        "id": str(notification_document.get("_id")),
        "title": notification_document.get("title"),
        "message": notification_document.get("message"),
        "category": notification_document.get("category"),
        "priority": notification_document.get("priority"),
        "reference_type": notification_document.get("reference_type"),
        "reference_id": str(notification_document.get("reference_id"))
        if notification_document.get("reference_id")
        else None,
        "is_read": bool(notification_document.get("is_read")),
        "created_at": _serialize_datetime(notification_document.get("created_at")),
    }


def ensure_notification_indexes():
    ensure_indexes_for_collection(
        notifications_collection(),
        [
            {"keys": [("recipient_user_id", ASCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("recipient_user_id", ASCENDING), ("is_read", ASCENDING)]},
            {"keys": [("category", ASCENDING)]},
            {"keys": [("priority", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
        ],
        collection_name="notifications",
    )


def create_notification(
    recipient_user_id: ObjectId,
    title: str,
    message: str,
    *,
    category: str,
    priority: str,
    reference_type: str,
    reference_id: ObjectId,
):
    notifications_collection().insert_one(
        {
            "recipient_user_id": recipient_user_id,
            "title": title,
            "message": message,
            "category": category,
            "priority": priority,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "is_read": False,
            "created_at": now_utc(),
        }
    )


def notify_roles(
    roles: list[str],
    title: str,
    message: str,
    *,
    category: str,
    priority: str,
    reference_type: str,
    reference_id: ObjectId,
):
    recipients = users_collection().find({"role": {"$in": roles}, "status": "active"})
    for recipient in recipients:
        create_notification(
            recipient_user_id=recipient["_id"],
            title=title,
            message=message,
            category=category,
            priority=priority,
            reference_type=reference_type,
            reference_id=reference_id,
        )


def list_notifications(current_user_id: str, *, limit: int = 200) -> list[dict]:
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    safe_limit = max(1, min(limit, 500))
    notifications = (
        notifications_collection()
        .find(
            {"recipient_user_id": user_object_id},
            {
                "title": 1,
                "message": 1,
                "category": 1,
                "priority": 1,
                "reference_type": 1,
                "reference_id": 1,
                "is_read": 1,
                "created_at": 1,
            },
        )
        .sort([("created_at", DESCENDING)])
        .limit(safe_limit)
    )
    return [serialize_notification(notification) for notification in notifications]


def mark_notification_as_read(notification_id: str, current_user_id: str) -> dict:
    notification_object_id = _to_object_id(notification_id, "notification_id")
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    notification = notifications_collection().find_one(
        {"_id": notification_object_id, "recipient_user_id": user_object_id}
    )
    if not notification:
        raise ApiError("Notification not found.", status_code=404)

    notifications_collection().update_one(
        {"_id": notification_object_id},
        {"$set": {"is_read": True}},
    )
    notification["is_read"] = True
    return serialize_notification(notification)


def mark_all_notifications_as_read(current_user_id: str) -> int:
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    result = notifications_collection().update_many(
        {"recipient_user_id": user_object_id, "is_read": False},
        {"$set": {"is_read": True}},
    )
    return result.modified_count


def delete_notification(notification_id: str, current_user_id: str) -> None:
    notification_object_id = _to_object_id(notification_id, "notification_id")
    user_object_id = _to_object_id(current_user_id, "current_user_id")
    result = notifications_collection().delete_one(
        {"_id": notification_object_id, "recipient_user_id": user_object_id}
    )
    if result.deleted_count == 0:
        raise ApiError("Notification not found.", status_code=404)
