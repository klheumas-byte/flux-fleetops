from flask import Blueprint, Response, current_app, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.report_service import get_finance_reports
from services.commercial_analytics_service import (
    export_commercial_analytics_csv,
    get_commercial_analytics,
)
from utils.api_error import ApiError
from utils.decorators import role_required
from utils.responses import error_response
from utils.responses import success_response


reports_bp = Blueprint("reports", __name__)


def _commercial_arguments():
    return {
        "role": get_jwt().get("role"),
        "user_id": get_jwt_identity(),
        "start_date": request.args.get("start_date"),
        "end_date": request.args.get("end_date"),
        "period": request.args.get("period", "daily"),
        "vehicle_id": request.args.get("vehicle_id"),
        "driver_id": request.args.get("driver_id"),
        "fleet_owner_id": request.args.get("fleet_owner_id"),
        "operation_type": request.args.get("operation_type"),
        "status": request.args.get("status"),
    }


@reports_bp.get("/commercial")
@role_required("owner", "admin", "fleet_owner", "driver")
def get_commercial_report():
    return success_response(data=get_commercial_analytics(
        **_commercial_arguments(),
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=25, type=int),
    ))


@reports_bp.get("/commercial/export.csv")
@role_required("owner", "admin", "fleet_owner", "driver")
def export_commercial_report():
    content = export_commercial_analytics_csv(**_commercial_arguments())
    return Response(content, mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=commercial-analytics.csv"
    })


@reports_bp.get("/finance")
@role_required("owner", "admin")
def get_finance_report():
    try:
        return success_response(
            data=get_finance_reports(
                current_role=get_jwt().get("role"),
                current_user_id=get_jwt_identity(),
                date_from=request.args.get("date_from"),
                date_to=request.args.get("date_to"),
                driver_id=request.args.get("driver_id"),
                vehicle_id=request.args.get("vehicle_id"),
                branch=request.args.get("branch"),
                category=request.args.get("category"),
                asset_owner_name=request.args.get("asset_owner_name"),
                creator_role=request.args.get("creator_role"),
                customer_category_id=request.args.get("customer_category_id"),
                source=request.args.get("source"),
                page=request.args.get("page", default=1, type=int),
                page_size=request.args.get("page_size", default=25, type=int),
            )
        )
    except ApiError:
        raise
    except Exception as error:
        current_app.logger.exception("[Flux Reports] Failed to generate finance reports: %s", error)
        return error_response(
            "Enterprise report data could not be generated right now.",
            status_code=500,
            public_message="Report data is not available right now.",
            data={},
        )
