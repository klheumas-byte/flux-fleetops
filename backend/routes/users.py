from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.auth_service import (
    create_user_as,
    get_user_by_id,
    get_viewable_user,
    list_users_for_actor,
    update_user_role_as,
    update_user_status_as,
    update_user_account_as,
    reset_user_password_as,
)
from services.user_service import update_driver_profile_as
from utils.decorators import permission_required, role_required
from utils.responses import success_response


users_bp = Blueprint("users", __name__)


@users_bp.get("")
@permission_required("users.manage_operational")
def list_users():
    actor = get_user_by_id(get_jwt_identity())
    users = list_users_for_actor(actor)
    return success_response(data={"users": users})


@users_bp.get("/me")
@role_required("owner", "admin", "driver")
def current_user_profile():
    user = get_user_by_id(get_jwt_identity())
    return success_response(data={"user": user})


@users_bp.get("/<user_id>")
@role_required("owner", "admin", "driver")
def get_user(user_id: str):
    current_role = get_jwt().get("role")
    current_user_id = get_jwt_identity()
    user = get_viewable_user(
        current_user_id=current_user_id,
        current_role=current_role,
        target_user_id=user_id,
    )
    return success_response(data={"user": user})


@users_bp.post("")
@permission_required("users.manage_operational")
def create_user():
    payload = request.get_json(silent=True) or {}
    current_role = get_jwt().get("role")
    user = create_user_as(current_role=current_role, payload=payload, current_user_id=get_jwt_identity())
    return success_response(
        data={"user": user},
        message="User account created successfully.",
        status_code=201,
    )


@users_bp.patch("/<user_id>/status")
@permission_required("users.manage_operational")
def update_user_status(user_id: str):
    payload = request.get_json(silent=True) or {}
    current_role = get_jwt().get("role")
    user = update_user_status_as(
        current_role=current_role,
        target_user_id=user_id,
        status=payload.get("status"),
        current_user_id=get_jwt_identity(),
    )
    return success_response(data={"user": user}, message="User status updated successfully.")


@users_bp.patch("/<user_id>")
@permission_required("users.manage_operational")
def update_user_account(user_id: str):
    user = update_user_account_as(get_jwt_identity(), get_jwt().get("role"), user_id, request.get_json(silent=True) or {})
    return success_response(data={"user": user}, message="User account updated successfully.")


@users_bp.post("/<user_id>/reset-password")
@permission_required("users.manage_operational")
def reset_user_password(user_id: str):
    payload = request.get_json(silent=True) or {}
    user = reset_user_password_as(get_jwt_identity(), get_jwt().get("role"), user_id, payload.get("temporary_password"))
    return success_response(data={"user": user}, message="Temporary password issued. The user must change it at next login.")


@users_bp.patch("/<user_id>/role")
@permission_required("users.manage")
def update_user_role(user_id: str):
    payload = request.get_json(silent=True) or {}
    user = update_user_role_as(
        current_user_id=get_jwt_identity(),
        target_user_id=user_id,
        role=payload.get("role"),
    )
    return success_response(
        data={"user": user},
        message="User role updated successfully.",
    )


@users_bp.patch("/<user_id>/driver-profile")
@role_required("owner", "admin", "driver")
def update_driver_profile(user_id: str):
    payload = request.get_json(silent=True) or {}
    user = update_driver_profile_as(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        target_user_id=user_id,
        payload=payload,
    )
    return success_response(
        data={"user": user},
        message="Driver profile updated successfully.",
    )
