from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.ride_service import (
    convert_booking_to_ride,
    create_ride,
    get_ride_by_id,
    get_ride_summary,
    list_ride_options,
    list_rides,
    update_ride,
)
from utils.decorators import role_required
from utils.responses import success_response


rides_bp = Blueprint("rides", __name__)


@rides_bp.get("")
@role_required("owner", "admin", "driver")
def get_rides_route():
    return success_response(
        data={
            "rides": list_rides(
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@rides_bp.get("/options")
@role_required("owner", "admin", "driver")
def get_ride_options_route():
    return success_response(
        data=list_ride_options(
            get_jwt_identity(),
            get_jwt().get("role"),
        )
    )


@rides_bp.get("/summary")
@role_required("owner", "admin", "driver")
def get_ride_summary_route():
    return success_response(
        data={
            "summary": get_ride_summary(
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@rides_bp.post("")
@role_required("owner", "admin", "driver")
def create_ride_route():
    ride = create_ride(
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"ride": ride},
        message="Trip log created successfully.",
        status_code=201,
    )


@rides_bp.post("/from-booking/<booking_id>")
@role_required("owner", "admin", "driver")
def convert_booking_route(booking_id: str):
    ride = convert_booking_to_ride(
        booking_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"ride": ride},
        message="Booking converted to trip log successfully.",
        status_code=201,
    )


@rides_bp.get("/<ride_id>")
@role_required("owner", "admin", "driver")
def get_ride_route(ride_id: str):
    return success_response(
        data={
            "ride": get_ride_by_id(
                ride_id,
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@rides_bp.patch("/<ride_id>")
@role_required("owner", "admin", "driver")
def update_ride_route(ride_id: str):
    ride = update_ride(
        ride_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"ride": ride},
        message="Trip log updated successfully.",
    )
