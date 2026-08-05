from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.vehicle_movement_service import (
    approve_vehicle_movement,
    cancel_vehicle_movement,
    check_out_vehicle_movement,
    close_vehicle_movement,
    confirm_vehicle_movement_delivery,
    create_vehicle_movement,
    get_vehicle_movement_by_id,
    list_vehicle_movement_options,
    list_vehicle_movements,
    return_vehicle_movement,
    start_vehicle_movement,
    update_vehicle_movement,
    respond_to_maintenance_movement,
    submit_maintenance_completion,
    review_maintenance_completion,
)
from services.movement_custody_service import (
    accept_movement_custody,
    append_custody_event,
    return_movement_custody,
    transfer_movement_custody,
)
from utils.decorators import role_required
from utils.responses import success_response


vehicle_movements_bp = Blueprint("vehicle_movements", __name__)


@vehicle_movements_bp.get("")
@role_required("owner", "admin", "driver")
def get_vehicle_movements_route():
    data = list_vehicle_movements(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=25, type=int),
        vehicle_id=request.args.get("vehicle_id"),
        driver_id=request.args.get("driver_id"),
        branch_id=request.args.get("branch_id"),
        status=request.args.get("status"),
        movement_type=request.args.get("movement_type"),
        search_query=request.args.get("q"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return success_response(data=data)


@vehicle_movements_bp.get("/options")
@role_required("owner", "admin", "driver")
def get_vehicle_movement_options_route():
    return success_response(
        data=list_vehicle_movement_options(
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        )
    )


@vehicle_movements_bp.post("")
@role_required("owner", "admin")
def create_vehicle_movement_route():
    movement = create_vehicle_movement(
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement created successfully.",
        status_code=201,
    )


@vehicle_movements_bp.get("/<movement_id>")
@role_required("owner", "admin", "driver")
def get_vehicle_movement_route(movement_id: str):
    return success_response(
        data={
            "movement": get_vehicle_movement_by_id(
                movement_id,
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@vehicle_movements_bp.patch("/<movement_id>")
@role_required("owner", "admin", "driver")
def update_vehicle_movement_route(movement_id: str):
    movement = update_vehicle_movement(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement updated successfully.",
    )


@vehicle_movements_bp.patch("/<movement_id>/approve")
@role_required("owner", "admin")
def approve_vehicle_movement_route(movement_id: str):
    movement = approve_vehicle_movement(
        movement_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement approved successfully.",
    )


@vehicle_movements_bp.patch("/<movement_id>/check-out")
@role_required("owner", "admin", "driver")
def check_out_vehicle_movement_route(movement_id: str):
    movement = check_out_vehicle_movement(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement checked out successfully.",
    )


@vehicle_movements_bp.patch("/<movement_id>/start")
@role_required("owner", "admin", "driver")
def start_vehicle_movement_route(movement_id: str):
    movement = start_vehicle_movement(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement started successfully.",
    )


@vehicle_movements_bp.patch("/<movement_id>/return")
@role_required("owner", "admin", "driver")
def return_vehicle_movement_route(movement_id: str):
    movement = return_vehicle_movement(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement returned successfully.",
    )


@vehicle_movements_bp.patch("/<movement_id>/deliver")
@role_required("owner", "admin", "driver")
def confirm_vehicle_movement_delivery_route(movement_id: str):
    movement = confirm_vehicle_movement_delivery(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement delivery confirmed successfully.",
    )


@vehicle_movements_bp.patch("/<movement_id>/close")
@role_required("owner", "admin")
def close_vehicle_movement_route(movement_id: str):
    movement = close_vehicle_movement(
        movement_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement closed successfully.",
    )


@vehicle_movements_bp.patch("/<movement_id>/cancel")
@role_required("owner", "admin")
def cancel_vehicle_movement_route(movement_id: str):
    movement = cancel_vehicle_movement(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": movement},
        message="Vehicle movement cancelled successfully.",
    )


@vehicle_movements_bp.post("/<movement_id>/custody/transfer")
@role_required("owner", "admin", "driver")
def transfer_vehicle_movement_custody_route(movement_id: str):
    result = transfer_movement_custody(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": get_vehicle_movement_by_id(
            movement_id,
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ), "custody_event": result["event"]},
        message="Vehicle custody transfer recorded.",
        status_code=201 if result["created"] else 200,
    )


@vehicle_movements_bp.post("/<movement_id>/custody/accept")
@role_required("owner", "admin", "driver")
def accept_vehicle_movement_custody_route(movement_id: str):
    result = accept_movement_custody(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": get_vehicle_movement_by_id(
            movement_id,
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ), "custody_event": result["event"]},
        message="Vehicle custody accepted.",
        status_code=201 if result["created"] else 200,
    )


@vehicle_movements_bp.post("/<movement_id>/custody/return")
@role_required("owner", "admin", "driver")
def return_vehicle_movement_custody_route(movement_id: str):
    result = return_movement_custody(
        movement_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"movement": get_vehicle_movement_by_id(
            movement_id,
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ), "custody_event": result["event"]},
        message="Vehicle custody returned.",
        status_code=201 if result["created"] else 200,
    )


@vehicle_movements_bp.post("/<movement_id>/custody/corrections")
@role_required("owner", "admin")
def correct_vehicle_movement_custody_route(movement_id: str):
    payload = request.get_json(silent=True) or {}
    result = append_custody_event(
        movement_id,
        event_type=payload.get("event_type") or "other",
        initiated_by=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        payload={**payload, "is_correction": True},
        source_event_key=payload.get("event_key"),
    )
    return success_response(
        data={"movement": get_vehicle_movement_by_id(
            movement_id,
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ), "custody_event": result["event"]},
        message="Audited custody correction recorded.",
        status_code=201 if result["created"] else 200,
    )


@vehicle_movements_bp.patch("/<movement_id>/maintenance-response")
@role_required("driver")
def respond_to_maintenance_movement_route(movement_id: str):
    movement = respond_to_maintenance_movement(movement_id, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"))
    return success_response(data={"movement": movement}, message="Maintenance assignment response saved.")


@vehicle_movements_bp.patch("/<movement_id>/submit-maintenance-completion")
@role_required("owner", "admin", "driver")
def submit_maintenance_completion_route(movement_id: str):
    movement = submit_maintenance_completion(movement_id, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"))
    return success_response(data={"movement": movement}, message="Maintenance completion submitted for review.")


@vehicle_movements_bp.patch("/<movement_id>/review-maintenance-completion")
@role_required("owner", "admin")
def review_maintenance_completion_route(movement_id: str):
    movement = review_maintenance_completion(movement_id, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"))
    return success_response(data={"movement": movement}, message="Maintenance completion review saved.")
