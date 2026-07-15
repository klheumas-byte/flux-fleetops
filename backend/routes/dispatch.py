from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.dispatch_request_service import (
    add_dispatch_request_stop,
    approve_dispatch_request_pricing,
    confirm_dispatch_request_stop_delivery,
    delete_dispatch_request_stop,
    list_scheduled_dispatch_requests,
    reject_dispatch_request_pricing,
    revise_dispatch_request_pricing,
    update_dispatch_request_schedule,
    update_dispatch_request_stop,
)
from services.dispatch_return_service import (
    close_dispatch_return,
    confirm_dispatch_return,
    get_dispatch_return_detail,
    link_or_create_return_fault,
    list_dispatch_returns,
    save_dispatch_return_inspection,
)
from utils.decorators import role_required
from utils.responses import success_response


dispatch_bp = Blueprint("dispatch", __name__)


@dispatch_bp.get("/schedule")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_schedule_alias_route():
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


@dispatch_bp.patch("/requests/<request_id>/pricing/approve")
@role_required("owner", "admin")
def approve_dispatch_request_pricing_alias_route(request_id: str):
    dispatch_request = approve_dispatch_request_pricing(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"request": dispatch_request}, message="Dispatch pricing approved successfully.")


@dispatch_bp.patch("/requests/<request_id>/pricing/reject")
@role_required("owner", "admin")
def reject_dispatch_request_pricing_alias_route(request_id: str):
    dispatch_request = reject_dispatch_request_pricing(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"request": dispatch_request}, message="Dispatch pricing rejected successfully.")


@dispatch_bp.patch("/requests/<request_id>/pricing/revise")
@role_required("owner", "admin", "dispatcher", "customer_service")
def revise_dispatch_request_pricing_alias_route(request_id: str):
    dispatch_request = revise_dispatch_request_pricing(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"request": dispatch_request}, message="Dispatch pricing updated successfully.")


@dispatch_bp.patch("/requests/<request_id>/schedule")
@role_required("owner", "admin", "dispatcher", "customer_service")
def update_dispatch_request_schedule_alias_route(request_id: str):
    dispatch_request = update_dispatch_request_schedule(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"request": dispatch_request}, message="Dispatch schedule updated successfully.")


@dispatch_bp.post("/requests/<request_id>/stops")
@role_required("owner", "admin", "dispatcher", "customer_service")
def add_dispatch_request_stop_alias_route(request_id: str):
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


@dispatch_bp.patch("/requests/<request_id>/stops/<stop_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def update_dispatch_request_stop_alias_route(request_id: str, stop_id: str):
    dispatch_request = update_dispatch_request_stop(
        request_id,
        stop_id,
        request.get_json(silent=True) or {},
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"request": dispatch_request}, message="Dispatch stop updated successfully.")


@dispatch_bp.delete("/requests/<request_id>/stops/<stop_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def delete_dispatch_request_stop_alias_route(request_id: str, stop_id: str):
    dispatch_request = delete_dispatch_request_stop(
        request_id,
        stop_id,
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"request": dispatch_request}, message="Dispatch stop removed successfully.")


@dispatch_bp.patch("/requests/<request_id>/stops/<stop_id>/deliver")
@role_required("owner", "admin", "dispatcher", "customer_service", "driver")
def confirm_dispatch_request_stop_delivery_alias_route(request_id: str, stop_id: str):
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


@dispatch_bp.get("/returns")
@role_required("owner", "admin", "dispatcher")
def get_dispatch_returns_route():
    data = list_dispatch_returns(
        current_role=get_jwt().get("role"),
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=20, type=int),
        search_query=request.args.get("q"),
        return_status=request.args.get("return_status"),
    )
    return success_response(data=data)


@dispatch_bp.get("/returns/<job_id>")
@role_required("owner", "admin", "dispatcher")
def get_dispatch_return_detail_route(job_id: str):
    return success_response(
        data=get_dispatch_return_detail(
            job_id,
            current_role=get_jwt().get("role"),
        )
    )


@dispatch_bp.patch("/returns/<job_id>/confirm-return")
@role_required("owner", "admin", "dispatcher")
def confirm_dispatch_return_route(job_id: str):
    return success_response(
        data=confirm_dispatch_return(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Vehicle return confirmed successfully.",
    )


@dispatch_bp.patch("/returns/<job_id>/inspection")
@role_required("owner", "admin", "dispatcher")
def save_dispatch_return_inspection_route(job_id: str):
    return success_response(
        data=save_dispatch_return_inspection(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Return inspection saved successfully.",
    )


@dispatch_bp.patch("/returns/<job_id>/fault")
@role_required("owner", "admin", "dispatcher")
def link_or_create_return_fault_route(job_id: str):
    return success_response(
        data=link_or_create_return_fault(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Return fault linked successfully.",
    )


@dispatch_bp.patch("/returns/<job_id>/close")
@role_required("owner", "admin", "dispatcher")
def close_dispatch_return_route(job_id: str):
    return success_response(
        data=close_dispatch_return(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Dispatch closed successfully.",
    )
