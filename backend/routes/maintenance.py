from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.maintenance_service import (
    add_maintenance_progress_update,
    assign_maintenance_coordinator,
    create_maintenance_job,
    get_maintenance_job_by_id,
    list_due_follow_ups,
    list_maintenance_jobs,
    list_maintenance_progress_logs,
    list_overdue_follow_ups,
    update_maintenance_job,
    update_maintenance_status,
)
from utils.decorators import role_required
from utils.responses import success_response


maintenance_bp = Blueprint("maintenance", __name__)


@maintenance_bp.get("")
@role_required("owner", "admin", "driver")
def get_maintenance_jobs():
    return success_response(
        data={
            "jobs": list_maintenance_jobs(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@maintenance_bp.get("/follow-ups/due")
@role_required("owner", "admin")
def get_due_follow_ups_route():
    return success_response(
        data={
            "jobs": list_due_follow_ups(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@maintenance_bp.get("/follow-ups/overdue")
@role_required("owner", "admin")
def get_overdue_follow_ups_route():
    return success_response(
        data={
            "jobs": list_overdue_follow_ups(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@maintenance_bp.post("")
@role_required("owner", "admin")
def create_maintenance_job_route():
    job = create_maintenance_job(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Maintenance job created successfully.",
        status_code=201,
    )


@maintenance_bp.get("/<maintenance_id>/progress")
@role_required("owner", "admin", "driver")
def get_maintenance_progress_route(maintenance_id: str):
    return success_response(
        data={
            "progress_logs": list_maintenance_progress_logs(
                maintenance_id=maintenance_id,
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@maintenance_bp.post("/<maintenance_id>/progress")
@role_required("owner", "admin", "driver")
def add_maintenance_progress_route(maintenance_id: str):
    progress_log = add_maintenance_progress_update(
        maintenance_id=maintenance_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"progress_log": progress_log},
        message="Maintenance progress updated successfully.",
        status_code=201,
    )


@maintenance_bp.get("/<maintenance_id>")
@role_required("owner", "admin", "driver")
def get_maintenance_job_route(maintenance_id: str):
    job = get_maintenance_job_by_id(
        maintenance_id=maintenance_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"job": job})


@maintenance_bp.patch("/<maintenance_id>")
@role_required("owner", "admin")
def update_maintenance_job_route(maintenance_id: str):
    job = update_maintenance_job(
        maintenance_id=maintenance_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Maintenance job updated successfully.",
    )


@maintenance_bp.patch("/<maintenance_id>/assign-coordinator")
@role_required("owner", "admin")
def assign_maintenance_coordinator_route(maintenance_id: str):
    payload = request.get_json(silent=True) or {}
    job = assign_maintenance_coordinator(
        maintenance_id=maintenance_id,
        coordinator_id=payload.get("maintenance_coordinator_id"),
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Maintenance coordinator updated successfully.",
    )


@maintenance_bp.patch("/<maintenance_id>/status")
@role_required("owner", "admin")
def update_maintenance_status_route(maintenance_id: str):
    payload = request.get_json(silent=True) or {}
    job = update_maintenance_status(
        maintenance_id=maintenance_id,
        status=payload.get("status"),
        payload=payload,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Maintenance status updated successfully.",
    )
