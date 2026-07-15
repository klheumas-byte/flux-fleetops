from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.notification_service import (
    administratively_resolve_notification,
    actionable_notification_counts,
    delete_notification,
    list_notifications_page,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    update_notification_state,
    sidebar_work_queue_counts,
)
from utils.decorators import role_required
from utils.responses import success_response


notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.get("/actionable-count")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def get_actionable_notification_count_route():
    return success_response(data=actionable_notification_counts(get_jwt_identity()))


@notifications_bp.get("/work-queue-counts")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def get_sidebar_work_queue_counts_route():
    return success_response(data=sidebar_work_queue_counts(get_jwt_identity(), get_jwt().get("role")))


@notifications_bp.get("")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def get_notifications_route():
    try:
        page = int(request.args.get("page", 1) or 1)
        page_size = int(request.args.get("page_size", request.args.get("limit", 50)) or 50)
    except ValueError:
        page, page_size = 1, 50
    return success_response(data=list_notifications_page(
        get_jwt_identity(), page=page, page_size=page_size,
        filters={
            "category": request.args.get("category"),
            "module": request.args.get("module"),
            "priority": request.args.get("priority"),
            "state": request.args.get("state"),
            "q": request.args.get("q"),
            "unread_only": request.args.get("unread_only") in {"1", "true"},
        },
    ))


@notifications_bp.patch("/read-all")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def mark_all_notifications_as_read_route():
    count = mark_all_notifications_as_read(get_jwt_identity())
    return success_response(
        data={"updated_count": count},
        message="Notifications marked as read.",
    )


@notifications_bp.patch("/<notification_id>/read")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def mark_notification_as_read_route(notification_id: str):
    notification = mark_notification_as_read(notification_id, get_jwt_identity())
    return success_response(
        data={"notification": notification},
        message="Notification marked as read.",
    )


@notifications_bp.patch("/<notification_id>/state")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def update_notification_state_route(notification_id: str):
    payload = request.get_json(silent=True) or {}
    notification = update_notification_state(
        notification_id,
        get_jwt_identity(),
        payload.get("state"),
        snoozed_until=payload.get("snoozed_until"),
    )
    return success_response(data={"notification": notification}, message="Notification updated.")


@notifications_bp.patch("/<notification_id>/resolve")
@role_required("owner", "admin")
def administratively_resolve_notification_route(notification_id: str):
    notification = administratively_resolve_notification(notification_id, get_jwt_identity())
    return success_response(data={"notification": notification}, message="Notification resolved.")


@notifications_bp.delete("/<notification_id>")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def delete_notification_route(notification_id: str):
    delete_notification(notification_id, get_jwt_identity())
    return success_response(message="Notification deleted successfully.")
