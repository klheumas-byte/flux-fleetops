from time import perf_counter

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.vehicle_service import (
    create_vehicle_cost_item,
    create_vehicle,
    delete_vehicle,
    get_vehicle_by_id,
    get_vehicle_economics_by_id,
    get_vehicle_economics_dashboard,
    list_vehicle_cost_items,
    list_vehicles,
    update_vehicle,
    update_vehicle_status,
)
from services.preventive_maintenance_service import generate_default_preventive_schedules_for_vehicle
from utils.decorators import role_required
from utils.responses import success_response


vehicles_bp = Blueprint("vehicles", __name__)


@vehicles_bp.get("")
@role_required("owner", "admin")
def get_vehicles():
    started_at = perf_counter()
    vehicles = list_vehicles(current_role=get_jwt().get("role"))
    current_app.logger.info(
        "[Flux Performance] GET /api/vehicles returned %s records in %.2fms",
        len(vehicles),
        (perf_counter() - started_at) * 1000,
    )
    return success_response(data={"vehicles": vehicles})


@vehicles_bp.get("/<vehicle_id>")
@role_required("owner", "admin")
def get_vehicle(vehicle_id: str):
    started_at = perf_counter()
    include_economics = request.args.get("include_economics", "false").strip().lower() in {"1", "true", "yes"}
    current_app.logger.info(
        "[Flux Performance] vehicle details request received vehicle_id=%s include_economics=%s",
        vehicle_id,
        include_economics,
    )
    vehicle = get_vehicle_by_id(
        vehicle_id,
        current_role=get_jwt().get("role"),
        include_economics=include_economics,
    )
    current_app.logger.info(
        "[Flux Performance] vehicle details response completed vehicle_id=%s include_economics=%s responseTimeMs=%.2f",
        vehicle_id,
        include_economics,
        (perf_counter() - started_at) * 1000,
    )
    return success_response(data={"vehicle": vehicle})


@vehicles_bp.get("/<vehicle_id>/economics")
@role_required("owner", "admin")
def get_vehicle_economics_route(vehicle_id: str):
    started_at = perf_counter()
    current_app.logger.info(
        "[Flux Performance] GET /api/vehicles/%s/economics started",
        vehicle_id,
    )
    payload = get_vehicle_economics_by_id(vehicle_id, current_role=get_jwt().get("role"))
    current_app.logger.info(
        "[Flux Performance] GET /api/vehicles/%s/economics completed in %.2fms",
        vehicle_id,
        (perf_counter() - started_at) * 1000,
    )
    return success_response(data=payload)


@vehicles_bp.post("")
@role_required("owner", "admin")
def create_vehicle_route():
    payload = request.get_json(silent=True) or {}
    vehicle = create_vehicle(payload, get_jwt_identity(), current_role=get_jwt().get("role"))
    return success_response(
        data={"vehicle": vehicle},
        message="Vehicle created successfully.",
        status_code=201,
    )


@vehicles_bp.patch("/<vehicle_id>")
@role_required("owner", "admin")
def update_vehicle_route(vehicle_id: str):
    payload = request.get_json(silent=True) or {}
    vehicle = update_vehicle(vehicle_id, payload, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"))
    return success_response(
        data={"vehicle": vehicle},
        message="Vehicle updated successfully.",
    )


@vehicles_bp.patch("/<vehicle_id>/status")
@role_required("owner", "admin")
def update_vehicle_status_route(vehicle_id: str):
    payload = request.get_json(silent=True) or {}
    vehicle = update_vehicle_status(vehicle_id, payload.get("status"), current_role=get_jwt().get("role"))
    return success_response(
        data={"vehicle": vehicle},
        message="Vehicle status updated successfully.",
    )


@vehicles_bp.delete("/<vehicle_id>")
@role_required("owner")
def delete_vehicle_route(vehicle_id: str):
    delete_vehicle(vehicle_id)
    return success_response(message="Vehicle deleted successfully.")


@vehicles_bp.post("/<vehicle_id>/generate-default-maintenance")
@role_required("owner", "admin")
def generate_default_vehicle_maintenance_route(vehicle_id: str):
    schedules = generate_default_preventive_schedules_for_vehicle(vehicle_id, get_jwt_identity())
    return success_response(
        data={"schedules": schedules},
        message="Default maintenance schedules generated successfully.",
    )


@vehicles_bp.get("/economics/dashboard")
@role_required("owner", "admin")
def get_vehicle_economics_dashboard_route():
    return success_response(data={"dashboard": get_vehicle_economics_dashboard(current_role=get_jwt().get("role"))})


@vehicles_bp.get("/<vehicle_id>/cost-items")
@role_required("owner", "admin")
def get_vehicle_cost_items_route(vehicle_id: str):
    return success_response(
        data={"cost_items": list_vehicle_cost_items(vehicle_id, current_role=get_jwt().get("role"))}
    )


@vehicles_bp.post("/<vehicle_id>/cost-items")
@role_required("owner", "admin")
def create_vehicle_cost_item_route(vehicle_id: str):
    cost_item = create_vehicle_cost_item(
        vehicle_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"cost_item": cost_item}, message="Vehicle cost item created successfully.", status_code=201)
