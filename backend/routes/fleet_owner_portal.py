from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from services.fleet_owner_service import (
    create_owner_account,
    link_owner_vehicles,
    list_owner_accounts,
    owner_dashboard,
    owner_vehicle_detail,
    update_owner_account,
    add_owned_case_comment,
    create_participation_request,
    list_participation_requests,
    review_participation_request,
)
from utils.decorators import role_required
from utils.responses import success_response


fleet_owner_portal_bp = Blueprint("fleet_owner_portal", __name__)


@fleet_owner_portal_bp.get("/accounts")
@role_required("owner", "admin")
def list_accounts():
    return success_response(data={"fleet_owners": list_owner_accounts()})


@fleet_owner_portal_bp.post("/accounts")
@role_required("owner", "admin")
def create_account():
    result = create_owner_account(request.get_json(silent=True) or {}, get_jwt_identity())
    return success_response(data={"fleet_owner": result}, message="Fleet Owner account created.", status_code=201)


@fleet_owner_portal_bp.patch("/accounts/<owner_id>")
@role_required("owner", "admin")
def update_account(owner_id):
    result = update_owner_account(owner_id, request.get_json(silent=True) or {}, get_jwt_identity())
    return success_response(data={"fleet_owner": result}, message="Fleet Owner account updated.")


@fleet_owner_portal_bp.post("/accounts/<owner_id>/vehicles")
@role_required("owner", "admin")
def link_vehicles(owner_id):
    payload = request.get_json(silent=True) or {}
    result = link_owner_vehicles(owner_id, payload.get("vehicle_ids"), get_jwt_identity())
    return success_response(data=result, message="Vehicles linked to Fleet Owner.")


@fleet_owner_portal_bp.get("/dashboard")
@role_required("fleet_owner")
def dashboard():
    return success_response(data=owner_dashboard(
        get_jwt_identity(),
        request.args.get("start_date"),
        request.args.get("end_date"),
        request.args.get("vehicle_id"),
    ))


@fleet_owner_portal_bp.get("/vehicles/<vehicle_id>")
@role_required("fleet_owner")
def vehicle_detail(vehicle_id):
    return success_response(data=owner_vehicle_detail(
        get_jwt_identity(),
        vehicle_id,
        request.args.get("start_date"),
        request.args.get("end_date"),
    ))


@fleet_owner_portal_bp.get("/requests")
@role_required("owner", "admin", "fleet_owner")
def participation_requests():
    from flask_jwt_extended import get_jwt
    return success_response(data={"requests": list_participation_requests(get_jwt_identity(), get_jwt().get("role"), request.args.get("status"))})


@fleet_owner_portal_bp.post("/requests")
@role_required("fleet_owner")
def post_participation_request():
    result = create_participation_request(get_jwt_identity(), request.get_json(silent=True) or {})
    return success_response(data={"request": result}, message="Request submitted for review.", status_code=201)


@fleet_owner_portal_bp.patch("/requests/<request_id>/review")
@role_required("owner", "admin")
def review_request(request_id):
    from flask_jwt_extended import get_jwt
    result = review_participation_request(request_id, request.get_json(silent=True) or {}, get_jwt_identity(), get_jwt().get("role"))
    return success_response(data={"request": result}, message="Request reviewed.")


@fleet_owner_portal_bp.post("/cases/<case_type>/<case_id>/comments")
@role_required("fleet_owner")
def add_case_comment(case_type, case_id):
    result = add_owned_case_comment(get_jwt_identity(), case_type, case_id, (request.get_json(silent=True) or {}).get("comment"))
    return success_response(data={"comment": result}, message="Comment added.", status_code=201)
