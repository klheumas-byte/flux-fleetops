from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.user_service import (
    get_driver_for_role,
    list_drivers_for_role,
    update_driver_approval_status_as,
    update_driver_profile_as,
    update_driver_status_as,
    schedule_driver_target,
)
from utils.decorators import role_required
from utils.responses import success_response
from services.vehicle_availability_service import resolve_driver_availability, update_driver_manual_availability
from utils.api_error import ApiError


drivers_bp = Blueprint("drivers", __name__)


@drivers_bp.get("")
@role_required("owner", "admin", "driver")
def list_drivers():
    drivers = list_drivers_for_role(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"drivers": drivers})


@drivers_bp.get("/<driver_id>")
@role_required("owner", "admin", "driver")
def get_driver(driver_id: str):
    driver = get_driver_for_role(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        driver_id=driver_id,
    )
    return success_response(data={"driver": driver})


@drivers_bp.patch("/<driver_id>/profile")
@role_required("owner", "admin", "driver")
def update_driver_profile(driver_id: str):
    driver = update_driver_profile_as(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        target_user_id=driver_id,
        payload=request.get_json(silent=True) or {},
    )
    return success_response(
        data={"driver": driver},
        message="Driver profile updated successfully.",
    )


@drivers_bp.post("/<driver_id>/targets")
@role_required("owner")
def schedule_driver_target_route(driver_id: str):
    driver = schedule_driver_target(
        driver_id=driver_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"driver": driver}, message="Driver target scheduled successfully.", status_code=201)


@drivers_bp.patch("/<driver_id>/approval-status")
@role_required("owner", "admin")
def update_driver_approval_status(driver_id: str):
    payload = request.get_json(silent=True) or {}
    driver = update_driver_approval_status_as(
        current_role=get_jwt().get("role"),
        driver_id=driver_id,
        approval_status=payload.get("approval_status"),
    )
    return success_response(
        data={"driver": driver},
        message="Driver approval status updated successfully.",
    )


@drivers_bp.patch("/<driver_id>/status")
@role_required("owner", "admin")
def update_driver_status(driver_id: str):
    payload = request.get_json(silent=True) or {}
    driver = update_driver_status_as(
        current_role=get_jwt().get("role"),
        driver_id=driver_id,
        status=payload.get("status"),
    )
    return success_response(
        data={"driver": driver},
        message="Driver status updated successfully.",
    )


@drivers_bp.patch("/<driver_id>/live-availability")
@role_required("owner", "admin", "operations_administrator", "operations_manager", "driver")
def update_driver_live_availability_route(driver_id: str):
    availability = update_driver_manual_availability(
        driver_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"availability": availability}, message="Driver live availability updated.")


@drivers_bp.get("/<driver_id>/live-availability")
@role_required("owner", "admin", "operations_administrator", "operations_manager", "driver")
def get_driver_live_availability_route(driver_id: str):
    if get_jwt().get("role") == "driver" and str(get_jwt_identity()) != str(driver_id):
        raise ApiError("You can only view your own live availability.", status_code=403)
    return success_response(data={"availability": resolve_driver_availability(driver_id)})
