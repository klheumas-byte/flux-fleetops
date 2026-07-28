from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.assignment_service import (
    create_assignment,
    accept_assignment_handover,
    complete_assignment_return,
    end_assignment,
    get_assignment,
    list_assignable_drivers,
    list_assignable_vehicles,
    list_assignments,
    list_driver_assignment_handovers,
    update_assignment,
    transfer_assignment,
)
from utils.api_error import ApiError
from utils.decorators import role_required
from utils.responses import success_response


assignments_bp = Blueprint("assignments", __name__)


@assignments_bp.get("")
@role_required("owner", "admin")
def get_assignments():
    return success_response(data={"assignments": list_assignments()})


@assignments_bp.get("/options")
@role_required("owner", "admin")
def get_assignment_options():
    return success_response(
        data={
            "drivers": list_assignable_drivers(),
            "vehicles": list_assignable_vehicles(),
        }
    )


@assignments_bp.get("/<assignment_id>")
@role_required("owner", "admin")
def get_assignment_route(assignment_id: str):
    return success_response(data={"assignment": get_assignment(assignment_id)})


@assignments_bp.post("")
@role_required("owner", "admin")
def create_assignment_route():
    payload = request.get_json(silent=True) or {}
    assignment = create_assignment(payload, get_jwt_identity())
    return success_response(
        data={"assignment": assignment},
        message="Assignment created successfully.",
        status_code=201,
    )


@assignments_bp.patch("/<assignment_id>")
@role_required("owner", "admin")
def update_assignment_route(assignment_id: str):
    payload = request.get_json(silent=True) or {}
    assignment = update_assignment(
        assignment_id,
        payload,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"assignment": assignment},
        message="Assignment updated successfully.",
    )


@assignments_bp.patch("/<assignment_id>/end")
@role_required("owner", "admin")
def end_assignment_route(assignment_id: str):
    payload = request.get_json(silent=True) or {}
    assignment = end_assignment(
        assignment_id,
        payload.get("end_date"),
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        end_reason=payload.get("reason"),
    )
    return success_response(
        data={"assignment": assignment},
        message="Assignment ended successfully.",
    )


@assignments_bp.patch("/<assignment_id>/unassign")
@role_required("owner", "admin")
def unassign_vehicle_route(assignment_id: str):
    payload = request.get_json(silent=True) or {}
    if not str(payload.get("reason") or "").strip():
        raise ApiError("reason is required.", status_code=400)
    assignment = end_assignment(
        assignment_id,
        payload.get("end_date"),
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        end_reason=payload.get("reason"),
    )
    return success_response(
        data={"assignment": assignment},
        message="Vehicle allocation released successfully.",
    )


@assignments_bp.post("/<assignment_id>/transfer")
@role_required("owner", "admin")
def transfer_assignment_route(assignment_id: str):
    assignment = transfer_assignment(
        assignment_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"assignment": assignment},
        message="Vehicle allocation transferred successfully.",
    )


@assignments_bp.get("/my-handovers")
@role_required("driver")
def get_my_assignment_handovers_route():
    return success_response(
        data={"assignments": list_driver_assignment_handovers(get_jwt_identity())}
    )


@assignments_bp.post("/<assignment_id>/handover/accept")
@role_required("owner", "admin", "driver")
def accept_assignment_handover_route(assignment_id: str):
    assignment = accept_assignment_handover(
        assignment_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"assignment": assignment},
        message="Assignment handover accepted.",
    )


@assignments_bp.post("/<assignment_id>/handover/return")
@role_required("owner", "admin", "driver")
def complete_assignment_return_route(assignment_id: str):
    assignment = complete_assignment_return(
        assignment_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"assignment": assignment},
        message="Assignment vehicle returned to company custody.",
    )
