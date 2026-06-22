from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.incident_service import (
    create_incident,
    create_maintenance_job_from_incident,
    get_incident_by_id,
    list_incidents,
    update_incident,
)
from utils.decorators import role_required
from utils.responses import success_response


incidents_bp = Blueprint("incidents", __name__)


@incidents_bp.get("")
@role_required("owner", "admin", "driver")
def get_incidents_route():
    return success_response(
        data=list_incidents(
            current_user_id=get_jwt_identity(),
            current_role=get_jwt().get("role"),
        )
    )


@incidents_bp.post("")
@role_required("owner", "admin", "driver")
def create_incident_route():
    incident = create_incident(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"incident": incident},
        message="Incident reported successfully.",
        status_code=201,
    )


@incidents_bp.get("/<incident_id>")
@role_required("owner", "admin", "driver")
def get_incident_route(incident_id: str):
    incident = get_incident_by_id(
        incident_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"incident": incident})


@incidents_bp.patch("/<incident_id>")
@role_required("owner", "admin")
def update_incident_route(incident_id: str):
    incident = update_incident(
        incident_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"incident": incident},
        message="Incident updated successfully.",
    )


@incidents_bp.post("/<incident_id>/create-maintenance-job")
@role_required("owner", "admin")
def create_incident_maintenance_job_route(incident_id: str):
    payload = create_maintenance_job_from_incident(
        incident_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data=payload,
        message="Repair job created from incident successfully.",
    )
