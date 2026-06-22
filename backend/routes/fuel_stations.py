from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.fuel_service import (
    create_fuel_station,
    list_fuel_stations,
    update_fuel_station,
    update_fuel_station_status,
)
from utils.decorators import role_required
from utils.responses import success_response


fuel_stations_bp = Blueprint("fuel_stations", __name__)


@fuel_stations_bp.get("")
@role_required("owner", "admin", "driver")
def get_fuel_stations_route():
    return success_response(
        data={"stations": list_fuel_stations(current_role=get_jwt().get("role"))}
    )


@fuel_stations_bp.post("")
@role_required("owner", "admin")
def create_fuel_station_route():
    station = create_fuel_station(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"station": station},
        message="Fuel station created successfully.",
        status_code=201,
    )


@fuel_stations_bp.patch("/<station_id>")
@role_required("owner", "admin")
def update_fuel_station_route(station_id: str):
    station = update_fuel_station(
        station_id=station_id,
        payload=request.get_json(silent=True) or {},
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"station": station},
        message="Fuel station updated successfully.",
    )


@fuel_stations_bp.patch("/<station_id>/status")
@role_required("owner", "admin")
def update_fuel_station_status_route(station_id: str):
    payload = request.get_json(silent=True) or {}
    station = update_fuel_station_status(
        station_id=station_id,
        status=payload.get("status"),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"station": station},
        message="Fuel station status updated successfully.",
    )
