from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.dispatch_opportunity_service import (
    approve_dispatch_opportunity,
    convert_dispatch_opportunity_to_request,
    get_dispatch_opportunity_by_id,
    list_dispatch_opportunities,
    list_dispatch_opportunity_options,
    reject_dispatch_opportunity,
    request_dispatch_opportunity_clarification,
    review_dispatch_opportunity,
)
from utils.decorators import role_required
from utils.responses import success_response


dispatch_opportunities_bp = Blueprint("dispatch_opportunities", __name__)


@dispatch_opportunities_bp.get("")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_opportunities_route():
    return success_response(
        data=list_dispatch_opportunities(
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=20, type=int),
            search_query=request.args.get("q"),
            status=request.args.get("status"),
            driver_id=request.args.get("driver_id"),
            date_from=request.args.get("date_from"),
            date_to=request.args.get("date_to"),
        )
    )


@dispatch_opportunities_bp.get("/options")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_opportunity_options_route():
    return success_response(data=list_dispatch_opportunity_options(current_role=get_jwt().get("role")))


@dispatch_opportunities_bp.get("/<opportunity_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_opportunity_route(opportunity_id: str):
    return success_response(
        data={
            "opportunity": get_dispatch_opportunity_by_id(
                opportunity_id,
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@dispatch_opportunities_bp.patch("/<opportunity_id>/review")
@role_required("owner", "admin", "dispatcher", "customer_service")
def review_dispatch_opportunity_route(opportunity_id: str):
    return success_response(
        data={
            "opportunity": review_dispatch_opportunity(
                opportunity_id,
                request.get_json(silent=True) or {},
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        },
        message="Dispatch opportunity review updated successfully.",
    )


@dispatch_opportunities_bp.patch("/<opportunity_id>/clarification")
@role_required("owner", "admin", "dispatcher", "customer_service")
def request_dispatch_opportunity_clarification_route(opportunity_id: str):
    return success_response(
        data={
            "opportunity": request_dispatch_opportunity_clarification(
                opportunity_id,
                request.get_json(silent=True) or {},
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        },
        message="Clarification requested successfully.",
    )


@dispatch_opportunities_bp.patch("/<opportunity_id>/approve")
@role_required("owner", "admin", "dispatcher", "customer_service")
def approve_dispatch_opportunity_route(opportunity_id: str):
    return success_response(
        data={
            "opportunity": approve_dispatch_opportunity(
                opportunity_id,
                request.get_json(silent=True) or {},
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        },
        message="Dispatch opportunity approved successfully.",
    )


@dispatch_opportunities_bp.patch("/<opportunity_id>/reject")
@role_required("owner", "admin", "dispatcher", "customer_service")
def reject_dispatch_opportunity_route(opportunity_id: str):
    return success_response(
        data={
            "opportunity": reject_dispatch_opportunity(
                opportunity_id,
                request.get_json(silent=True) or {},
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        },
        message="Dispatch opportunity rejected successfully.",
    )


@dispatch_opportunities_bp.post("/<opportunity_id>/convert")
@role_required("owner", "admin", "dispatcher", "customer_service")
def convert_dispatch_opportunity_route(opportunity_id: str):
    data = convert_dispatch_opportunity_to_request(
        opportunity_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data=data,
        message="Dispatch opportunity converted successfully.",
        status_code=201,
    )
