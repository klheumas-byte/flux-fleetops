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
from utils.decorators import role_required
from utils.responses import success_response


dispatch_financials_bp = Blueprint("dispatch_financials", __name__)


@dispatch_financials_bp.get("")
@role_required("owner", "admin")
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
@role_required("owner", "admin")
def get_dispatch_financial_options_route():
    return success_response(data=get_dispatch_financial_reference_options(current_role=get_jwt().get("role")))


@dispatch_financials_bp.get("/<job_id>")
@role_required("owner", "admin")
def get_dispatch_financial_detail_route(job_id: str):
    return success_response(
        data=get_dispatch_financial_detail(
            job_id,
            current_role=get_jwt().get("role"),
        )
    )


@dispatch_financials_bp.post("/<job_id>/incidents")
@role_required("owner", "admin")
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
@role_required("owner", "admin")
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
@role_required("owner", "admin")
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
@role_required("owner", "admin")
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
@role_required("owner", "admin")
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
