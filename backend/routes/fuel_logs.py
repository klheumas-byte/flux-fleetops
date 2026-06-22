from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.fuel_service import (
    approve_fuel_log,
    create_fuel_log,
    get_fuel_log_by_id,
    list_fuel_logs,
    reject_fuel_log,
)
from utils.decorators import role_required
from utils.responses import success_response


fuel_logs_bp = Blueprint("fuel_logs", __name__)


@fuel_logs_bp.get("")
@role_required("owner", "admin")
def get_fuel_logs_route():
    data = list_fuel_logs(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data=data)


@fuel_logs_bp.post("")
@role_required("owner", "admin", "driver")
def create_fuel_log_route():
    log = create_fuel_log(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"log": log},
        message="Fuel log submitted successfully.",
        status_code=201,
    )


@fuel_logs_bp.get("/<log_id>")
@role_required("owner", "admin", "driver")
def get_fuel_log_route(log_id: str):
    log = get_fuel_log_by_id(
        log_id=log_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"log": log})


@fuel_logs_bp.patch("/<log_id>/approve")
@role_required("owner", "admin")
def approve_fuel_log_route(log_id: str):
    log = approve_fuel_log(
        log_id=log_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"log": log},
        message="Fuel log approved successfully.",
    )


@fuel_logs_bp.patch("/<log_id>/reject")
@role_required("owner", "admin")
def reject_fuel_log_route(log_id: str):
    payload = request.get_json(silent=True) or {}
    log = reject_fuel_log(
        log_id=log_id,
        rejection_reason=payload.get("rejection_reason"),
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"log": log},
        message="Fuel log rejected successfully.",
    )
