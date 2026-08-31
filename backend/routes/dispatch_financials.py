from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.dispatch_financial_service import (
    close_dispatch_financial,
    get_dispatch_financial_detail,
    get_dispatch_financial_reference_options,
    list_dispatch_financials,
    review_dispatch_expense,
    review_dispatch_financial_incident,
    submit_dispatch_financial_incident,
    verify_dispatch_financial,
)
from services.dispatch_finance_engine_service import (
    approve_finance_snapshot,
    build_finance_preview,
    dispatch_finance_analytics,
    finalize_finance_snapshot,
    list_finance_settings,
    reserve_balance,
    schedule_finance_setting,
    schedule_vehicle_efficiency,
)
from utils.decorators import role_required
from utils.responses import success_response


dispatch_financials_bp = Blueprint("dispatch_financials", __name__)


@dispatch_financials_bp.get("/settings")
@role_required("owner", "admin", "finance", "finance_officer")
def get_dispatch_finance_settings_route():
    return success_response(data=list_finance_settings(get_jwt().get("role")))


@dispatch_financials_bp.post("/settings/<setting_type>")
@role_required("owner")
def post_dispatch_finance_setting_route(setting_type):
    return success_response(data=schedule_finance_setting(
        setting_type, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role")
    ), message="Dispatch finance setting scheduled successfully.", status_code=201)


@dispatch_financials_bp.get("/analytics")
@role_required("owner", "admin", "finance", "finance_officer")
def get_dispatch_finance_analytics_route():
    return success_response(data=dispatch_finance_analytics(
        current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"),
        start_date=request.args.get("start_date"), end_date=request.args.get("end_date"), preset=request.args.get("preset"),
        driver_id=request.args.get("driver_id"), vehicle_id=request.args.get("vehicle_id"), pricing_type=request.args.get("pricing_type"),
        funding_source_id=request.args.get("funding_source_id"), branch_id=request.args.get("branch_id"),
    ))


@dispatch_financials_bp.get("/vehicles/<vehicle_id>/maintenance-reserve")
@role_required("owner", "admin", "finance", "finance_officer")
def get_vehicle_maintenance_reserve_route(vehicle_id):
    return success_response(data=reserve_balance(vehicle_id))


@dispatch_financials_bp.post("/vehicles/<vehicle_id>/fuel-efficiency")
@role_required("owner")
def post_vehicle_fuel_efficiency_route(vehicle_id):
    return success_response(data=schedule_vehicle_efficiency(
        vehicle_id, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role")
    ), message="Vehicle efficiency scheduled successfully.", status_code=201)


@dispatch_financials_bp.post("/<job_id>/preview")
@role_required("owner", "admin", "finance", "finance_officer", "operations_administrator")
def preview_dispatch_finance_route(job_id):
    return success_response(data=build_finance_preview(
        job_id, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role")
    ))


@dispatch_financials_bp.post("/<job_id>/approve-snapshot")
@role_required("owner", "admin", "finance", "finance_officer")
def approve_dispatch_finance_snapshot_route(job_id):
    return success_response(data=approve_finance_snapshot(
        job_id, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"),
        idempotency_key=request.headers.get("Idempotency-Key"),
    ), message="Dispatch finance snapshot approved successfully.")


@dispatch_financials_bp.post("/<job_id>/finalize-snapshot")
@role_required("owner", "admin", "finance", "finance_officer")
def finalize_dispatch_finance_snapshot_route(job_id):
    return success_response(data=finalize_finance_snapshot(
        job_id, request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role")
    ), message="Actual dispatch finance confirmed successfully.")


@dispatch_financials_bp.get("")
@role_required("owner", "admin", "finance", "finance_officer")
def get_dispatch_financials_route():
    return success_response(
        data=list_dispatch_financials(
            current_role=get_jwt().get("role"),
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=20, type=int),
            search_query=request.args.get("q"),
            financial_status=request.args.get("financial_status"),
        )
    )


@dispatch_financials_bp.get("/options")
@role_required("owner", "admin", "finance", "finance_officer")
def get_dispatch_financial_options_route():
    return success_response(data=get_dispatch_financial_reference_options(current_role=get_jwt().get("role")))


@dispatch_financials_bp.get("/<job_id>")
@role_required("owner", "admin", "finance", "finance_officer")
def get_dispatch_financial_detail_route(job_id: str):
    return success_response(
        data=get_dispatch_financial_detail(
            job_id,
            current_role=get_jwt().get("role"),
        )
    )


@dispatch_financials_bp.post("/<job_id>/incidents")
@role_required("owner", "admin", "finance", "finance_officer")
def create_dispatch_financial_incident_route(job_id: str):
    return success_response(
        data=submit_dispatch_financial_incident(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Dispatch incident recorded successfully.",
        status_code=201,
    )


@dispatch_financials_bp.patch("/<job_id>/verify")
@role_required("owner", "admin", "finance", "finance_officer")
def verify_dispatch_financial_route(job_id: str):
    return success_response(
        data=verify_dispatch_financial(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Dispatch financials verified successfully.",
    )


@dispatch_financials_bp.patch("/<job_id>/close")
@role_required("owner", "admin", "finance", "finance_officer")
def close_dispatch_financial_route(job_id: str):
    return success_response(
        data=close_dispatch_financial(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Dispatch financial record closed successfully.",
    )


@dispatch_financials_bp.patch("/expenses/<expense_id>/review")
@role_required("owner", "admin", "finance", "finance_officer")
def review_dispatch_expense_route(expense_id: str):
    return success_response(
        data=review_dispatch_expense(
            expense_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Dispatch expense reviewed successfully.",
    )


@dispatch_financials_bp.patch("/incidents/<incident_id>/review")
@role_required("owner", "admin", "finance", "finance_officer")
def review_dispatch_incident_route(incident_id: str):
    return success_response(
        data=review_dispatch_financial_incident(
            incident_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        ),
        message="Dispatch incident reviewed successfully.",
    )
