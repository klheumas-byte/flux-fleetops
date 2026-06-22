from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from services.notification_service import (
    delete_notification,
    list_notifications,
    mark_all_notifications_as_read,
    mark_notification_as_read,
)
from utils.decorators import role_required
from utils.responses import success_response


notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.get("")
@role_required("owner", "admin", "driver")
def get_notifications_route():
    try:
        limit = int(request.args.get("limit", 200) or 200)
    except ValueError:
        limit = 200
    return success_response(
        data={
            "notifications": list_notifications(
                get_jwt_identity(),
                limit=limit,
            )
        }
    )


@notifications_bp.patch("/read-all")
@role_required("owner", "admin", "driver")
def mark_all_notifications_as_read_route():
    count = mark_all_notifications_as_read(get_jwt_identity())
    return success_response(
        data={"updated_count": count},
        message="Notifications marked as read.",
    )


@notifications_bp.patch("/<notification_id>/read")
@role_required("owner", "admin", "driver")
def mark_notification_as_read_route(notification_id: str):
    notification = mark_notification_as_read(notification_id, get_jwt_identity())
    return success_response(
        data={"notification": notification},
        message="Notification marked as read.",
    )


@notifications_bp.delete("/<notification_id>")
@role_required("owner", "admin", "driver")
def delete_notification_route(notification_id: str):
    delete_notification(notification_id, get_jwt_identity())
    return success_response(message="Notification deleted successfully.")
