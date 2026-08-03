from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.driver_scope_service import create_temporary_branch_assignment, list_temporary_branch_assignments
from utils.decorators import role_required
from utils.responses import success_response


driver_scope_bp = Blueprint("driver_scope", __name__)


@driver_scope_bp.get("")
@role_required("owner", "admin")
def list_assignments():
    return success_response(data={"assignments": list_temporary_branch_assignments(current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"))})


@driver_scope_bp.post("")
@role_required("owner", "admin")
def create_assignment():
    result = create_temporary_branch_assignment(request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"))
    return success_response(data={"assignment": result}, status_code=201)
