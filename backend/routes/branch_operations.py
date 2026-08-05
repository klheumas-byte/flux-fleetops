from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity
from services.branch_operations_service import create_driver_request, create_field_agent, get_branch_operations_overview, list_branch_team, reset_field_agent_access, set_field_agent_status, update_field_agent
from utils.decorators import permission_required
from utils.responses import success_response

branch_operations_bp = Blueprint("branch_operations", __name__)

@branch_operations_bp.get("/overview")
@permission_required("branch_operations.view")
def overview(): return success_response(data=get_branch_operations_overview(get_jwt_identity()))

@branch_operations_bp.get("/team")
@permission_required("branch_operations.view")
def team(): return success_response(data=list_branch_team(get_jwt_identity()))

@branch_operations_bp.post("/team/field-agents")
@permission_required("branch_operations.manage_team")
def field_agent_create(): return success_response(data={"user": create_field_agent(get_jwt_identity(), request.get_json(silent=True) or {})}, status_code=201)

@branch_operations_bp.patch("/team/field-agents/<user_id>")
@permission_required("branch_operations.manage_team")
def field_agent_update(user_id): return success_response(data={"user": update_field_agent(get_jwt_identity(), user_id, request.get_json(silent=True) or {})})

@branch_operations_bp.patch("/team/field-agents/<user_id>/status")
@permission_required("branch_operations.manage_team")
def field_agent_status(user_id): return success_response(data={"user": set_field_agent_status(get_jwt_identity(), user_id, (request.get_json(silent=True) or {}).get("status"))})

@branch_operations_bp.post("/team/field-agents/<user_id>/reset-access")
@permission_required("branch_operations.manage_team")
def field_agent_reset(user_id): return success_response(data=reset_field_agent_access(get_jwt_identity(), user_id, (request.get_json(silent=True) or {}).get("temporary_password")))

@branch_operations_bp.post("/team/driver-requests")
@permission_required("branch_operations.manage_team")
def driver_request(): return success_response(data={"driver": create_driver_request(get_jwt_identity(), request.get_json(silent=True) or {})}, status_code=201)
