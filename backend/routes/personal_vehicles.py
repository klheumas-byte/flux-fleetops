from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from services.personal_vehicle_service import (
    create_record, create_vehicle, dashboard, expense_summary, get_profile, get_vehicle,
    list_records, list_vehicles, renew_document, update_profile, update_record, update_vehicle,
    vehicle_health, vehicle_timeline,
)
from utils.decorators import role_required
from utils.responses import success_response


personal_vehicles_bp = Blueprint("personal_vehicles", __name__)


@personal_vehicles_bp.get("/dashboard")
@role_required("personal_vehicle_owner")
def dashboard_route():
    return success_response(data=dashboard(get_jwt_identity(), vehicle_id=request.args.get("vehicle_id"), start_date=request.args.get("start_date"), end_date=request.args.get("end_date")))


@personal_vehicles_bp.get("/vehicles")
@role_required("personal_vehicle_owner")
def vehicles_route():
    return success_response(data={"vehicles": list_vehicles(get_jwt_identity())})


@personal_vehicles_bp.post("/vehicles")
@role_required("personal_vehicle_owner")
def create_vehicle_route():
    return success_response(data={"vehicle": create_vehicle(get_jwt_identity(), request.get_json(silent=True) or {})}, message="Personal vehicle added.", status_code=201)


@personal_vehicles_bp.get("/vehicles/<vehicle_id>")
@role_required("personal_vehicle_owner")
def vehicle_route(vehicle_id):
    return success_response(data={"vehicle": get_vehicle(get_jwt_identity(), vehicle_id)})


@personal_vehicles_bp.patch("/vehicles/<vehicle_id>")
@role_required("personal_vehicle_owner")
def update_vehicle_route(vehicle_id):
    return success_response(data={"vehicle": update_vehicle(get_jwt_identity(), vehicle_id, request.get_json(silent=True) or {})}, message="Vehicle updated.")


@personal_vehicles_bp.get("/records/<kind>")
@role_required("personal_vehicle_owner")
def records_route(kind):
    return success_response(data=list_records(get_jwt_identity(), kind, vehicle_id=request.args.get("vehicle_id"), page=request.args.get("page", 1), page_size=request.args.get("page_size", 25), start_date=request.args.get("start_date"), end_date=request.args.get("end_date")))


@personal_vehicles_bp.post("/records/<kind>")
@role_required("personal_vehicle_owner")
def create_record_route(kind):
    return success_response(data={"record": create_record(get_jwt_identity(), kind, request.get_json(silent=True) or {})}, message="Vehicle record saved.", status_code=201)


@personal_vehicles_bp.patch("/records/<kind>/<record_id>")
@role_required("personal_vehicle_owner")
def update_record_route(kind, record_id):
    return success_response(data={"record": update_record(get_jwt_identity(), kind, record_id, request.get_json(silent=True) or {})}, message="Vehicle record updated.")


@personal_vehicles_bp.post("/documents/<document_id>/renew")
@role_required("personal_vehicle_owner")
def renew_document_route(document_id):
    return success_response(data={"document": renew_document(get_jwt_identity(), document_id, request.get_json(silent=True) or {})}, message="Document renewed; previous history preserved.", status_code=201)


@personal_vehicles_bp.get("/expenses/summary")
@role_required("personal_vehicle_owner")
def expense_summary_route():
    return success_response(data=expense_summary(get_jwt_identity(), vehicle_id=request.args.get("vehicle_id"), start_date=request.args.get("start_date"), end_date=request.args.get("end_date")))


@personal_vehicles_bp.get("/timeline")
@role_required("personal_vehicle_owner")
def timeline_route():
    return success_response(data=vehicle_timeline(get_jwt_identity(), vehicle_id=request.args.get("vehicle_id"), page=request.args.get("page", 1), page_size=request.args.get("page_size", 25), event_type=request.args.get("event_type")))


@personal_vehicles_bp.get("/vehicles/<vehicle_id>/health")
@role_required("personal_vehicle_owner")
def health_route(vehicle_id):
    return success_response(data={"health": vehicle_health(get_jwt_identity(), vehicle_id)})


@personal_vehicles_bp.get("/profile")
@role_required("personal_vehicle_owner")
def profile_route():
    return success_response(data={"user": get_profile(get_jwt_identity())})


@personal_vehicles_bp.patch("/profile")
@role_required("personal_vehicle_owner")
def update_profile_route():
    return success_response(data={"user": update_profile(get_jwt_identity(), request.get_json(silent=True) or {})}, message="Profile updated.")
