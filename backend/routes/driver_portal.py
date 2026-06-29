from flask import Blueprint
from flask_jwt_extended import get_jwt_identity

from services.assignment_service import get_active_assignment_for_driver
from flask import request

from services.collection_service import get_driver_dashboard_summary, submit_driver_payment
from services.fuel_service import list_fuel_logs
from services.maintenance_service import (
    get_driver_maintenance_job_by_id,
    list_driver_maintenance_jobs,
    list_driver_maintenance_progress_logs,
    submit_driver_maintenance_confirmation,
)
from services.preventive_maintenance_service import get_driver_preventive_maintenance_snapshot
from services.wallet_service import get_logged_in_driver_wallet
from utils.decorators import role_required
from utils.responses import success_response


driver_portal_bp = Blueprint("driver_portal", __name__)


@driver_portal_bp.get("/active-assignment")
@role_required("driver")
def get_active_assignment():
    assignment = get_active_assignment_for_driver(get_jwt_identity())
    return success_response(data={"assignment": assignment})


@driver_portal_bp.get("/dashboard-summary")
@role_required("driver")
def get_dashboard_summary():
    summary = get_driver_dashboard_summary(get_jwt_identity())
    return success_response(data={"summary": summary})


@driver_portal_bp.get("/wallet")
@role_required("driver")
def get_driver_wallet():
    wallet = get_logged_in_driver_wallet(get_jwt_identity())
    return success_response(data={"wallet": wallet})


@driver_portal_bp.get("/preventive-maintenance")
@role_required("driver")
def get_driver_preventive_maintenance():
    return success_response(data=get_driver_preventive_maintenance_snapshot(get_jwt_identity()))


@driver_portal_bp.get("/fuel-logs")
@role_required("driver")
def get_driver_fuel_logs():
    return success_response(
        data=list_fuel_logs(
            current_user_id=get_jwt_identity(),
            current_role="driver",
        )
    )


@driver_portal_bp.get("/maintenance")
@role_required("driver")
def get_driver_maintenance():
    return success_response(
        data={
            "jobs": list_driver_maintenance_jobs(get_jwt_identity())
        }
    )


@driver_portal_bp.get("/maintenance/<maintenance_id>")
@role_required("driver")
def get_driver_maintenance_job(maintenance_id: str):
    return success_response(
        data={
            "job": get_driver_maintenance_job_by_id(
                maintenance_id=maintenance_id,
                current_user_id=get_jwt_identity(),
            )
        }
    )


@driver_portal_bp.get("/maintenance/<maintenance_id>/progress")
@role_required("driver")
def get_driver_maintenance_progress(maintenance_id: str):
    return success_response(
        data={
            "progress_logs": list_driver_maintenance_progress_logs(
                maintenance_id=maintenance_id,
                current_user_id=get_jwt_identity(),
            )
        }
    )


@driver_portal_bp.post("/maintenance/<maintenance_id>/progress")
@role_required("driver")
def post_driver_maintenance_progress(maintenance_id: str):
    progress_log = submit_driver_maintenance_confirmation(
        maintenance_id=maintenance_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"progress_log": progress_log},
        message="Driver maintenance confirmation submitted successfully.",
        status_code=201,
    )


@driver_portal_bp.post("/payments")
@role_required("driver")
def submit_payment():
    payment = submit_driver_payment(request.get_json(silent=True) or {}, get_jwt_identity())
    return success_response(
        data={"payment": payment},
        message="Payment submitted successfully and is pending admin confirmation.",
        status_code=201,
    )
