from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.fault_service import (
    approve_fault,
    create_fault,
    create_fault_category,
    create_fault_component,
    get_fault_by_id,
    list_critical_faults,
    list_fault_approvals,
    list_fault_options,
    list_faults,
    reject_fault,
    request_fault_info,
    update_fault,
    update_fault_category,
    update_fault_component,
)
from services.maintenance_service import convert_fault_to_maintenance_job
from utils.decorators import role_required
from utils.responses import success_response


faults_bp = Blueprint("faults", __name__)


@faults_bp.get("")
@role_required("owner", "admin", "driver")
def get_faults():
    return success_response(
        data={
            "faults": list_faults(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@faults_bp.get("/approvals")
@role_required("owner", "admin")
def get_fault_approvals_route():
    return success_response(
        data={
            "faults": list_fault_approvals(
                current_role=get_jwt().get("role"),
            )
        }
    )


@faults_bp.get("/critical")
@role_required("owner", "admin")
def get_critical_faults_route():
    return success_response(
        data={
            "faults": list_critical_faults(
                current_role=get_jwt().get("role"),
            )
        }
    )


@faults_bp.post("")
@role_required("owner", "admin", "driver")
def create_fault_route():
    fault = create_fault(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"fault": fault},
        message="Fault reported successfully.",
        status_code=201,
    )


@faults_bp.get("/options")
@role_required("owner", "admin", "driver")
def get_fault_options_route():
    return success_response(data=list_fault_options(get_jwt().get("role")))


@faults_bp.get("/<fault_id>")
@role_required("owner", "admin", "driver")
def get_fault_route(fault_id: str):
    fault = get_fault_by_id(
        fault_id=fault_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"fault": fault})


@faults_bp.patch("/<fault_id>")
@role_required("owner", "admin", "driver")
def update_fault_route(fault_id: str):
    fault = update_fault(
        fault_id=fault_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"fault": fault},
        message="Fault updated successfully.",
    )


@faults_bp.patch("/<fault_id>/approve")
@role_required("owner", "admin")
def approve_fault_route(fault_id: str):
    payload = request.get_json(silent=True) or {}
    fault = approve_fault(
        fault_id=fault_id,
        current_user_id=get_jwt_identity(),
        notes=payload.get("admin_notes"),
    )
    return success_response(
        data={"fault": fault},
        message="Fault approved successfully.",
    )


@faults_bp.patch("/<fault_id>/reject")
@role_required("owner", "admin")
def reject_fault_route(fault_id: str):
    payload = request.get_json(silent=True) or {}
    fault = reject_fault(
        fault_id=fault_id,
        current_user_id=get_jwt_identity(),
        notes=payload.get("admin_notes"),
    )
    return success_response(
        data={"fault": fault},
        message="Fault rejected successfully.",
    )


@faults_bp.patch("/<fault_id>/request-info")
@role_required("owner", "admin")
def request_fault_info_route(fault_id: str):
    payload = request.get_json(silent=True) or {}
    fault = request_fault_info(
        fault_id=fault_id,
        current_user_id=get_jwt_identity(),
        notes=payload.get("admin_notes"),
    )
    return success_response(
        data={"fault": fault},
        message="More information requested successfully.",
    )


@faults_bp.post("/<fault_id>/convert-to-maintenance")
@role_required("owner", "admin")
def convert_fault_to_maintenance_route(fault_id: str):
    job = convert_fault_to_maintenance_job(
        fault_id=fault_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Fault converted to maintenance successfully.",
    )


@faults_bp.post("/categories")
@role_required("owner")
def create_fault_category_route():
    category = create_fault_category(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"category": category},
        message="Fault category created successfully.",
        status_code=201,
    )


@faults_bp.patch("/categories/<category_id>")
@role_required("owner")
def update_fault_category_route(category_id: str):
    category = update_fault_category(
        category_id=category_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"category": category},
        message="Fault category updated successfully.",
    )


@faults_bp.post("/components")
@role_required("owner")
def create_fault_component_route():
    component = create_fault_component(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"component": component},
        message="Fault component created successfully.",
        status_code=201,
    )


@faults_bp.patch("/components/<component_id>")
@role_required("owner")
def update_fault_component_route(component_id: str):
    component = update_fault_component(
        component_id=component_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"component": component},
        message="Fault component updated successfully.",
    )
