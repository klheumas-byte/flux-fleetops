from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.vehicle_operation_request_service import (
    acknowledge_operational_request,
    approve_operational_request,
    cancel_operational_request,
    confirm_operational_task,
    create_operational_request,
    get_operational_request,
    list_operational_request_options,
    list_operational_requests,
    open_operational_movement,
    reject_operational_request,
    return_operational_request,
    schedule_operational_request,
    start_operational_request,
    submit_operational_request,
    update_operational_request,
    verify_operational_request,
)
from utils.decorators import role_required
from utils.responses import success_response


operational_requests_bp = Blueprint("operational_requests", __name__)


def _identity():
    return get_jwt_identity(), get_jwt().get("role")


@operational_requests_bp.get("")
@role_required("owner", "admin", "driver")
def list_route():
    user_id, role = _identity()
    return success_response(data=list_operational_requests(current_user_id=user_id, current_role=role, page=request.args.get("page", 1, type=int), page_size=request.args.get("page_size", 25, type=int), status=request.args.get("status"), operation_type=request.args.get("operation_type")))


@operational_requests_bp.get("/options")
@role_required("owner", "admin", "driver")
def options_route():
    _user_id, role = _identity()
    return success_response(data=list_operational_request_options(current_role=role))


@operational_requests_bp.post("")
@role_required("owner", "admin")
def create_route():
    user_id, role = _identity()
    return success_response(data={"request": create_operational_request(request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)}, message="Operational request created.", status_code=201)


@operational_requests_bp.get("/<request_id>")
@role_required("owner", "admin", "driver")
def detail_route(request_id):
    user_id, role = _identity()
    return success_response(data={"request": get_operational_request(request_id, current_user_id=user_id, current_role=role)})


@operational_requests_bp.patch("/<request_id>")
@role_required("owner", "admin")
def update_route(request_id):
    user_id, role = _identity()
    return success_response(data={"request": update_operational_request(request_id, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)})


def _action(request_id, handler, *, payload=False):
    user_id, role = _identity()
    kwargs = {"current_user_id": user_id, "current_role": role}
    result = handler(request_id, request.get_json(silent=True) or {}, **kwargs) if payload else handler(request_id, **kwargs)
    return success_response(data={"request": result})


@operational_requests_bp.patch("/<request_id>/submit")
@role_required("owner", "admin")
def submit_route(request_id): return _action(request_id, submit_operational_request)


@operational_requests_bp.patch("/<request_id>/approve")
@role_required("owner", "admin")
def approve_route(request_id): return _action(request_id, approve_operational_request)


@operational_requests_bp.patch("/<request_id>/reject")
@role_required("owner", "admin")
def reject_route(request_id):
    user_id, role = _identity(); payload = request.get_json(silent=True) or {}
    return success_response(data={"request": reject_operational_request(request_id, payload.get("reason"), current_user_id=user_id, current_role=role)})


@operational_requests_bp.patch("/<request_id>/schedule")
@role_required("owner", "admin")
def schedule_route(request_id): return _action(request_id, schedule_operational_request, payload=True)


@operational_requests_bp.patch("/<request_id>/acknowledge")
@role_required("driver")
def acknowledge_route(request_id): return _action(request_id, acknowledge_operational_request)


@operational_requests_bp.patch("/<request_id>/opening-check")
@role_required("owner", "admin", "driver")
def opening_route(request_id): return _action(request_id, open_operational_movement, payload=True)


@operational_requests_bp.patch("/<request_id>/start")
@role_required("owner", "admin", "driver")
def start_route(request_id): return _action(request_id, start_operational_request, payload=True)


@operational_requests_bp.patch("/<request_id>/confirm-task")
@role_required("owner", "admin", "driver")
def confirm_route(request_id): return _action(request_id, confirm_operational_task, payload=True)


@operational_requests_bp.patch("/<request_id>/return")
@role_required("owner", "admin", "driver")
def return_route(request_id): return _action(request_id, return_operational_request, payload=True)


@operational_requests_bp.patch("/<request_id>/verify")
@role_required("owner", "admin")
def verify_route(request_id): return _action(request_id, verify_operational_request, payload=True)


@operational_requests_bp.patch("/<request_id>/cancel")
@role_required("owner", "admin")
def cancel_route(request_id): return _action(request_id, cancel_operational_request, payload=True)
