from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from services.system_settings_service import get_system_settings, update_system_settings
from utils.decorators import role_required
from utils.responses import success_response


system_settings_bp = Blueprint("system_settings", __name__)


@system_settings_bp.get("")
@role_required("owner", "admin", "driver")
def get_system_settings_route():
    return success_response(data={"settings": get_system_settings()})


@system_settings_bp.patch("")
@role_required("owner")
def update_system_settings_route():
    settings = update_system_settings(
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"settings": settings},
        message="System settings updated successfully.",
    )
