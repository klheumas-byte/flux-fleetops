from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.booking_service import list_calendar_entries
from utils.decorators import role_required
from utils.responses import success_response


calendar_bp = Blueprint("calendar", __name__)


@calendar_bp.get("")
@role_required("owner", "admin", "driver")
def get_calendar_route():
    view = request.args.get("view", "upcoming")
    return success_response(
        data=list_calendar_entries(
            get_jwt_identity(),
            get_jwt().get("role"),
            view,
        )
    )


@calendar_bp.get("/today")
@role_required("owner", "admin", "driver")
def get_calendar_today_route():
    return success_response(
        data=list_calendar_entries(
            get_jwt_identity(),
            get_jwt().get("role"),
            "today",
        )
    )


@calendar_bp.get("/upcoming")
@role_required("owner", "admin", "driver")
def get_calendar_upcoming_route():
    return success_response(
        data=list_calendar_entries(
            get_jwt_identity(),
            get_jwt().get("role"),
            "upcoming",
        )
    )
