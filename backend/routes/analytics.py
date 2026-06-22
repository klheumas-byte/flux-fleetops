from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.driver_analytics_service import (
    get_driver_analytics_detail,
    get_driver_analytics_leaderboard,
    list_driver_analytics,
)
from utils.decorators import role_required
from utils.responses import success_response


analytics_bp = Blueprint("analytics", __name__)


def _query_filters() -> dict:
    return {
        "start_date": request.args.get("start_date"),
        "end_date": request.args.get("end_date"),
        "vehicle_id": request.args.get("vehicle_id"),
        "admin_id": request.args.get("admin_id"),
        "branch": request.args.get("branch"),
    }


@analytics_bp.get("/drivers")
@role_required("owner", "admin")
def get_driver_analytics_route():
    return success_response(
        data=list_driver_analytics(
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
            **_query_filters(),
        )
    )


@analytics_bp.get("/drivers/leaderboard")
@role_required("owner", "admin")
def get_driver_leaderboard_route():
    return success_response(
        data=get_driver_analytics_leaderboard(
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
            **_query_filters(),
        )
    )


@analytics_bp.get("/drivers/<driver_id>")
@role_required("owner", "admin", "driver")
def get_driver_analytics_detail_route(driver_id: str):
    return success_response(
        data=get_driver_analytics_detail(
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
            driver_id=driver_id,
            **_query_filters(),
        )
    )
