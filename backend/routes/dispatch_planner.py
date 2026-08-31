from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.dispatch_planner_service import (
    accept_driver_dispatch_job,
    assign_dispatch_job,
    cancel_planned_operation,
    correct_dispatch_job_schedule,
    detect_dispatch_conflicts,
    get_dispatch_job,
    get_fleet_availability,
    list_dispatch_jobs,
    list_driver_dispatch_jobs,
    list_planner_options,
    list_planner_requests,
    plan_operation,
    reassign_dispatch_job,
    reassign_planned_operation,
    reject_driver_dispatch_job,
    request_dispatch_clarification,
    reserve_dispatch_resources,
    save_dispatch_job_draft,
)
from utils.decorators import role_required
from utils.responses import success_response


dispatch_planner_bp = Blueprint("dispatch_planner", __name__)


@dispatch_planner_bp.get("/requests")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_planner_requests_route():
    return success_response(
        data=list_planner_requests(
            current_role=get_jwt().get("role"),
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=20, type=int),
            search_query=request.args.get("q"),
            planning_status=request.args.get("planning_status"),
            urgency=request.args.get("urgency"),
            operation_type=request.args.get("operation_type"),
        )
    )


@dispatch_planner_bp.get("/options")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_planner_options_route():
    return success_response(
        data=list_planner_options(
            current_role=get_jwt().get("role"),
            current_user_id=get_jwt_identity(),
        )
    )


@dispatch_planner_bp.get("/availability")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_planner_availability_route():
    return success_response(data=get_fleet_availability(current_role=get_jwt().get("role")))


@dispatch_planner_bp.post("/conflicts")
@role_required("owner", "admin", "dispatcher", "customer_service")
def detect_planner_conflicts_route():
    payload = request.get_json(silent=True) or {}
    return success_response(
        data=detect_dispatch_conflicts(
            vehicle_id=payload.get("vehicle_id"),
            driver_id=payload.get("driver_id"),
            scheduled_start_time=payload.get("scheduled_start_time"),
            expected_return_time=payload.get("expected_return_time"),
            exclude_job_id=payload.get("exclude_job_id"),
            exclude_movement_id=payload.get("exclude_movement_id"),
        )
    )


@dispatch_planner_bp.get("/jobs")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_jobs_route():
    return success_response(
        data=list_dispatch_jobs(
            current_role=get_jwt().get("role"),
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=20, type=int),
            status=request.args.get("status"),
        )
    )


@dispatch_planner_bp.get("/jobs/<job_id>")
@role_required("owner", "admin", "dispatcher", "customer_service")
def get_dispatch_job_route(job_id: str):
    return success_response(
        data={
            "job": get_dispatch_job(
                job_id,
                current_role=get_jwt().get("role"),
            )
        }
    )


@dispatch_planner_bp.post("/requests/<request_id>/draft")
@role_required("owner", "admin", "dispatcher", "customer_service")
def save_dispatch_job_draft_route(request_id: str):
    job = save_dispatch_job_draft(
        request_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Dispatch planning draft saved successfully.",
        status_code=201,
    )


@dispatch_planner_bp.patch("/jobs/<job_id>/reserve")
@role_required("owner", "admin", "dispatcher", "customer_service")
def reserve_dispatch_resources_route(job_id: str):
    job = reserve_dispatch_resources(
        job_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Dispatch resources reserved successfully.",
    )


@dispatch_planner_bp.patch("/jobs/<job_id>/assign")
@role_required("owner", "admin", "dispatcher", "customer_service")
def assign_dispatch_job_route(job_id: str):
    job = assign_dispatch_job(
        job_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Dispatch assigned successfully.",
    )


@dispatch_planner_bp.patch("/jobs/<job_id>/reassign")
@role_required("owner", "admin", "dispatcher", "customer_service")
def reassign_dispatch_job_route(job_id: str):
    job = reassign_dispatch_job(
        job_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Dispatch reassigned successfully.",
    )


@dispatch_planner_bp.patch("/jobs/<job_id>/schedule")
@role_required("owner", "admin")
def correct_dispatch_job_schedule_route(job_id: str):
    job = correct_dispatch_job_schedule(
        job_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Dispatch schedule corrected and reassigned successfully.",
    )


@dispatch_planner_bp.patch("/operations/<operation_type>/<source_id>/plan")
@role_required("owner", "admin", "dispatcher", "customer_service")
def plan_operation_route(operation_type: str, source_id: str):
    result = plan_operation(
        operation_type,
        source_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data=result, message="Operation planned successfully.")


@dispatch_planner_bp.patch("/operations/<operation_type>/<source_id>/reassign")
@role_required("owner", "admin", "dispatcher", "customer_service")
def reassign_planned_operation_route(operation_type: str, source_id: str):
    result = reassign_planned_operation(
        operation_type,
        source_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data=result, message="Operation reassigned successfully.")


@dispatch_planner_bp.patch("/operations/<operation_type>/<source_id>/cancel")
@role_required("owner", "admin", "dispatcher", "customer_service")
def cancel_planned_operation_route(operation_type: str, source_id: str):
    result = cancel_planned_operation(
        operation_type,
        source_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data=result, message="Operation cancelled successfully.")


@dispatch_planner_bp.get("/driver/jobs")
@role_required("driver")
def get_driver_dispatch_jobs_route():
    return success_response(data=list_driver_dispatch_jobs(current_user_id=get_jwt_identity()))


@dispatch_planner_bp.patch("/driver/jobs/<job_id>/accept")
@role_required("driver")
def accept_driver_dispatch_job_route(job_id: str):
    job = accept_driver_dispatch_job(job_id, current_user_id=get_jwt_identity())
    return success_response(
        data={"job": job},
        message="Dispatch accepted successfully.",
    )


@dispatch_planner_bp.patch("/driver/jobs/<job_id>/clarify")
@role_required("driver")
def request_driver_dispatch_clarification_route(job_id: str):
    job = request_dispatch_clarification(
        job_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"job": job},
        message="Dispatch clarification request sent successfully.",
    )


@dispatch_planner_bp.patch("/driver/jobs/<job_id>/reject")
@role_required("driver")
def reject_driver_dispatch_job_route(job_id: str):
    job = reject_driver_dispatch_job(
        job_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"job": job},
        message="Dispatch assignment rejected successfully.",
    )
