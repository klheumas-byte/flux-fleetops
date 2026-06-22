from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.booking_service import (
    acknowledge_booking,
    complete_booking,
    create_booking,
    get_booking_by_id,
    get_booking_dashboard_summary,
    list_booking_options,
    list_bookings,
    mark_booking_picked_up,
    report_booking_issue,
    start_pickup,
    update_booking,
)
from utils.decorators import role_required
from utils.responses import success_response


bookings_bp = Blueprint("bookings", __name__)


@bookings_bp.get("")
@role_required("owner", "admin", "driver")
def get_bookings_route():
    return success_response(
        data={
            "bookings": list_bookings(
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@bookings_bp.get("/options")
@role_required("owner", "admin", "driver")
def get_booking_options_route():
    return success_response(
        data=list_booking_options(
            get_jwt_identity(),
            get_jwt().get("role"),
        )
    )


@bookings_bp.get("/summary")
@role_required("owner", "admin", "driver")
def get_booking_summary_route():
    return success_response(
        data={
            "summary": get_booking_dashboard_summary(
                get_jwt().get("role"),
                get_jwt_identity(),
            )
        }
    )


@bookings_bp.post("")
@role_required("owner", "admin", "driver")
def create_booking_route():
    booking = create_booking(
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"booking": booking},
        message="Booking created successfully.",
        status_code=201,
    )


@bookings_bp.get("/<booking_id>")
@role_required("owner", "admin", "driver")
def get_booking_route(booking_id: str):
    return success_response(
        data={
            "booking": get_booking_by_id(
                booking_id,
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@bookings_bp.patch("/<booking_id>")
@role_required("owner", "admin", "driver")
def update_booking_route(booking_id: str):
    booking = update_booking(
        booking_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"booking": booking},
        message="Booking updated successfully.",
    )


@bookings_bp.patch("/<booking_id>/acknowledge")
@role_required("owner", "admin", "driver")
def acknowledge_booking_route(booking_id: str):
    booking = acknowledge_booking(
        booking_id,
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"booking": booking},
        message="Booking acknowledged successfully.",
    )


@bookings_bp.patch("/<booking_id>/start-pickup")
@role_required("owner", "admin", "driver")
def start_pickup_route(booking_id: str):
    booking = start_pickup(
        booking_id,
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"booking": booking},
        message="Pickup started successfully.",
    )


@bookings_bp.patch("/<booking_id>/picked-up")
@role_required("owner", "admin", "driver")
def picked_up_route(booking_id: str):
    booking = mark_booking_picked_up(
        booking_id,
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"booking": booking},
        message="Booking marked as picked up.",
    )


@bookings_bp.patch("/<booking_id>/complete")
@role_required("owner", "admin", "driver")
def complete_booking_route(booking_id: str):
    booking = complete_booking(
        booking_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"booking": booking},
        message="Booking completed successfully.",
    )


@bookings_bp.patch("/<booking_id>/report-issue")
@role_required("owner", "admin", "driver")
def report_issue_route(booking_id: str):
    booking = report_booking_issue(
        booking_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"booking": booking},
        message="Booking issue reported successfully.",
    )
