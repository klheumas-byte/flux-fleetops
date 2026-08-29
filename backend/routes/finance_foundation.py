from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.finance_foundation_service import (create_funding_contribution, funding_position, list_funding_contributions, reconciliation_report, vehicle_finance_history)
from services.master_data_service import get_active_master_data_items, list_master_data
from utils.decorators import role_required
from utils.responses import success_response


finance_foundation_bp = Blueprint("finance_foundation", __name__)


@finance_foundation_bp.get("/funding-sources")
@role_required("owner", "admin", "finance", "finance_officer", "driver")
def funding_sources_route():
    return success_response(data={"funding_sources": get_active_master_data_items("funding_sources")})


@finance_foundation_bp.get("/contributions")
@role_required("owner", "admin", "finance", "finance_officer")
def contributions_route():
    return success_response(data={"contributions": list_funding_contributions()})


@finance_foundation_bp.post("/contributions")
@role_required("owner", "admin", "finance", "finance_officer")
def create_contribution_route():
    contribution = create_funding_contribution(request.get_json(silent=True) or {}, current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"), idempotency_key=request.headers.get("Idempotency-Key"))
    return success_response(data={"contribution": contribution}, message="Funding contribution recorded.", status_code=201)


@finance_foundation_bp.get("/funding-position")
@role_required("owner", "admin", "finance", "finance_officer")
def funding_position_route():
    return success_response(data={"position": funding_position(start_date=request.args.get("start_date"), end_date=request.args.get("end_date"))})


@finance_foundation_bp.get("/reconciliation")
@role_required("owner", "admin", "finance", "finance_officer", "driver")
def reconciliation_route():
    return success_response(data=reconciliation_report(current_user_id=get_jwt_identity(), current_role=get_jwt().get("role"), driver_id=request.args.get("driver_id"), preset=request.args.get("period"), start_date=request.args.get("start_date"), end_date=request.args.get("end_date")))


@finance_foundation_bp.get("/vehicles/<vehicle_id>/history")
@role_required("owner", "admin", "finance", "finance_officer")
def vehicle_history_route(vehicle_id):
    return success_response(data={"history": vehicle_finance_history(vehicle_id)})
