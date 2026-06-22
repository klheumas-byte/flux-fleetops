from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from services.assignment_service import (
    create_assignment,
    end_assignment,
    get_assignment,
    list_assignable_drivers,
    list_assignable_vehicles,
    list_assignments,
    update_assignment,
)
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
    assignment = update_assignment(assignment_id, payload)
    return success_response(
        data={"assignment": assignment},
        message="Assignment updated successfully.",
    )


@assignments_bp.patch("/<assignment_id>/end")
@role_required("owner", "admin")
def end_assignment_route(assignment_id: str):
    payload = request.get_json(silent=True) or {}
    assignment = end_assignment(assignment_id, payload.get("end_date"))
    return success_response(
        data={"assignment": assignment},
        message="Assignment ended successfully.",
    )
