from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.operations_control_service import execute_control_action, get_control_center, get_control_timeline
from utils.decorators import role_required
from utils.responses import success_response

operations_control_bp = Blueprint("operations_control", __name__)

@operations_control_bp.get("")
@role_required("owner", "admin", "operations_administrator", "operations_manager")
def get_operations_control():
    return success_response(data=get_control_center(current_role=get_jwt().get("role")))

@operations_control_bp.get("/timeline")
@role_required("owner", "admin", "operations_administrator", "operations_manager")
def get_operations_control_timeline():
    return success_response(data=get_control_timeline(
        current_role=get_jwt().get("role"),
        source_type=request.args.get("source_type"), source_id=request.args.get("source_id"),
        movement_id=request.args.get("movement_id"), reservation_id=request.args.get("reservation_id"),
        assignment_id=request.args.get("assignment_id"),
    ))

@operations_control_bp.post("/actions")
@role_required("owner", "admin", "operations_administrator", "operations_manager")
def post_operations_control_action():
    payload = request.get_json(silent=True) or {}
    return success_response(data=execute_control_action(payload, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role")))
