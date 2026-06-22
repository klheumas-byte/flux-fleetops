from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.auth_service import (
    create_user_as,
    get_user_by_id,
    get_viewable_user,
    list_users_for_role,
    update_user_role_as,
    update_user_status_as,
)
from services.user_service import update_driver_profile_as
from utils.decorators import role_required
from utils.responses import success_response


users_bp = Blueprint("users", __name__)


@users_bp.get("")
@role_required("owner", "admin")
def list_users():
    current_role = get_jwt().get("role")
    users = list_users_for_role(current_role)
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
@role_required("owner", "admin")
def create_user():
    payload = request.get_json(silent=True) or {}
    current_role = get_jwt().get("role")
    user = create_user_as(current_role=current_role, payload=payload)
    return success_response(
        data={"user": user},
        message="User account created successfully.",
        status_code=201,
    )


@users_bp.patch("/<user_id>/status")
@role_required("owner", "admin")
def update_user_status(user_id: str):
    payload = request.get_json(silent=True) or {}
    current_role = get_jwt().get("role")
    user = update_user_status_as(
        current_role=current_role,
        target_user_id=user_id,
        status=payload.get("status"),
    )
    return success_response(
        data={"user": user},
        message="User status updated successfully.",
    )


@users_bp.patch("/<user_id>/role")
@role_required("owner")
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
