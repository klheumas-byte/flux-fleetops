from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.dispatch_request_service import (
    add_dispatch_request_stop,
    approve_dispatch_request,
    approve_dispatch_request_pricing,
    cancel_dispatch_request,
    confirm_dispatch_request_stop_delivery,
    create_dispatch_request,
    delete_dispatch_request_stop,
    get_dispatch_request_by_id,
    list_scheduled_dispatch_requests,
    list_dispatch_request_options,
    list_dispatch_requests,
    reject_dispatch_request_pricing,
    reject_dispatch_request,
    revise_dispatch_request_pricing,
    update_dispatch_request_schedule,
    update_dispatch_request_stop,
    update_dispatch_request,
)
from utils.decorators import role_required
from utils.responses import success_response


dispatch_requests_bp = Blueprint("dispatch_requests", __name__)


@dispatch_requests_bp.get("")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_requests_route():
    data = list_dispatch_requests(
        current_role=get_jwt().get("role"),
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=25, type=int),
        search_query=request.args.get("q"),
        status=request.args.get("status"),
        vehicle_type_needed=request.args.get("vehicle_type_needed"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return success_response(data=data)


@dispatch_requests_bp.get("/schedule")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_schedule_route():
    data = list_scheduled_dispatch_requests(
        current_role=get_jwt().get("role"),
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=25, type=int),
        status=request.args.get("status"),
        vehicle_type_needed=request.args.get("vehicle_type_needed"),
        pricing_status=request.args.get("pricing_status"),
        schedule_type=request.args.get("schedule_type"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return success_response(data=data)


@dispatch_requests_bp.get("/options")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_request_options_route():
    return success_response(
        data=list_dispatch_request_options(
            current_role=get_jwt().get("role"),
            current_user_id=get_jwt_identity(),
        )
    )


@dispatch_requests_bp.post("")
@role_required("owner", "admin", "dispatcher", "customer_service")
def create_dispatch_request_route():
    dispatch_request = create_dispatch_request(
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch request created successfully.",
        status_code=201,
    )


@dispatch_requests_bp.get("/<request_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_request_route(request_id: str):
    return success_response(
        data={
            "request": get_dispatch_request_by_id(
                request_id,
                current_role=get_jwt().get("role"),
            )
        }
    )


@dispatch_requests_bp.patch("/<request_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def update_dispatch_request_route(request_id: str):
    dispatch_request = update_dispatch_request(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch request updated successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/approve")
@role_required("owner", "admin")
def approve_dispatch_request_route(request_id: str):
    dispatch_request = approve_dispatch_request(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch request approved successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/reject")
@role_required("owner", "admin")
def reject_dispatch_request_route(request_id: str):
    dispatch_request = reject_dispatch_request(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch request rejected successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/cancel")
@role_required("owner", "admin")
def cancel_dispatch_request_route(request_id: str):
    dispatch_request = cancel_dispatch_request(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch request cancelled successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/pricing/approve")
@role_required("owner", "admin")
def approve_dispatch_request_pricing_route(request_id: str):
    dispatch_request = approve_dispatch_request_pricing(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch pricing approved successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/pricing/reject")
@role_required("owner", "admin")
def reject_dispatch_request_pricing_route(request_id: str):
    dispatch_request = reject_dispatch_request_pricing(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch pricing rejected successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/pricing/revise")
@role_required("owner", "admin", "dispatcher", "customer_service")
def revise_dispatch_request_pricing_route(request_id: str):
    dispatch_request = revise_dispatch_request_pricing(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch pricing updated successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/schedule")
@role_required("owner", "admin", "dispatcher", "customer_service")
def update_dispatch_request_schedule_route(request_id: str):
    dispatch_request = update_dispatch_request_schedule(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch schedule updated successfully.",
    )


@dispatch_requests_bp.post("/<request_id>/stops")
@role_required("owner", "admin", "dispatcher", "customer_service")
def add_dispatch_request_stop_route(request_id: str):
    dispatch_request = add_dispatch_request_stop(
        request_id,
        request.get_json(silent=True) or {},
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch stop added successfully.",
        status_code=201,
    )


@dispatch_requests_bp.patch("/<request_id>/stops/<stop_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def update_dispatch_request_stop_route(request_id: str, stop_id: str):
    dispatch_request = update_dispatch_request_stop(
        request_id,
        stop_id,
        request.get_json(silent=True) or {},
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch stop updated successfully.",
    )


@dispatch_requests_bp.delete("/<request_id>/stops/<stop_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def delete_dispatch_request_stop_route(request_id: str, stop_id: str):
    dispatch_request = delete_dispatch_request_stop(
        request_id,
        stop_id,
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch stop removed successfully.",
    )


@dispatch_requests_bp.patch("/<request_id>/stops/<stop_id>/deliver")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def confirm_dispatch_request_stop_delivery_route(request_id: str, stop_id: str):
    dispatch_request = confirm_dispatch_request_stop_delivery(
        request_id,
        stop_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"request": dispatch_request},
        message="Dispatch stop delivery confirmed successfully.",
    )
