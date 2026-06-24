from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.preventive_maintenance_service import (
    complete_preventive_schedule,
    create_preventive_schedule,
    create_compliance_item_type,
    create_compliance_record,
    generate_default_preventive_schedules_for_vehicle,
    generate_maintenance_job_from_schedule,
    get_compliance_dashboard_summary,
    get_preventive_schedule_by_id,
    list_compliance_item_types,
    list_compliance_records,
    list_due_soon_schedules,
    list_overdue_schedules,
    list_preventive_maintenance,
    list_preventive_maintenance_for_vehicle,
    renew_compliance_record,
    update_preventive_schedule,
    update_compliance_item_type,
    update_compliance_record,
)
from utils.decorators import role_required
from utils.responses import success_response


preventive_maintenance_bp = Blueprint("preventive_maintenance", __name__)


@preventive_maintenance_bp.get("")
@role_required("owner", "admin", "driver")
def get_preventive_maintenance_route():
    vehicle_id = request.args.get("vehicle_id")
    return success_response(
        data={
            "schedules": list_preventive_maintenance(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
                vehicle_id=vehicle_id,
            )
        }
    )


@preventive_maintenance_bp.get("/due-soon")
@role_required("owner", "admin", "driver")
def get_due_soon_preventive_maintenance_route():
    vehicle_id = request.args.get("vehicle_id")
    return success_response(
        data={
            "schedules": list_due_soon_schedules(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
                vehicle_id=vehicle_id,
            )
        }
    )


@preventive_maintenance_bp.get("/vehicle/<vehicle_id>")
@role_required("owner", "admin", "driver")
def get_vehicle_preventive_maintenance_route(vehicle_id: str):
    schedules = list_preventive_maintenance_for_vehicle(
        vehicle_id=vehicle_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    if not schedules:
        return success_response(data=[], message="No preventive maintenance schedules found for this vehicle.")
    return success_response(data=schedules)


@preventive_maintenance_bp.get("/overdue")
@role_required("owner", "admin", "driver")
def get_overdue_preventive_maintenance_route():
    vehicle_id = request.args.get("vehicle_id")
    return success_response(
        data={
            "schedules": list_overdue_schedules(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
                vehicle_id=vehicle_id,
            )
        }
    )


@preventive_maintenance_bp.post("")
@role_required("owner", "admin")
def create_preventive_maintenance_route():
    schedule = create_preventive_schedule(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"schedule": schedule},
        message="Preventive maintenance schedule created successfully.",
        status_code=201,
    )


@preventive_maintenance_bp.get("/<schedule_id>")
@role_required("owner", "admin", "driver")
def get_preventive_maintenance_by_id_route(schedule_id: str):
    return success_response(
        data={
            "schedule": get_preventive_schedule_by_id(
                schedule_id=schedule_id,
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@preventive_maintenance_bp.patch("/<schedule_id>")
@role_required("owner", "admin")
def update_preventive_maintenance_route(schedule_id: str):
    schedule = update_preventive_schedule(
        schedule_id=schedule_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"schedule": schedule},
        message="Preventive maintenance schedule updated successfully.",
    )


@preventive_maintenance_bp.patch("/<schedule_id>/complete")
@role_required("owner", "admin")
def complete_preventive_maintenance_route(schedule_id: str):
    schedule = complete_preventive_schedule(
        schedule_id=schedule_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"schedule": schedule},
        message="Preventive maintenance schedule completed successfully.",
    )


@preventive_maintenance_bp.post("/<schedule_id>/generate-maintenance-job")
@role_required("owner", "admin")
def generate_maintenance_job_from_schedule_route(schedule_id: str):
    job = generate_maintenance_job_from_schedule(
        schedule_id=schedule_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"job": job},
        message="Maintenance job generated from preventive schedule successfully.",
        status_code=201,
    )


@preventive_maintenance_bp.post("/vehicles/<vehicle_id>/generate-defaults")
@role_required("owner", "admin")
def generate_default_preventive_schedules_route(vehicle_id: str):
    schedules = generate_default_preventive_schedules_for_vehicle(
        vehicle_id=vehicle_id,
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"schedules": schedules},
        message="Default preventive maintenance schedules generated successfully.",
    )


@preventive_maintenance_bp.get("/compliance/types")
@role_required("owner", "admin", "driver")
def get_compliance_item_types_route():
    return success_response(
        data={
            "types": list_compliance_item_types(
                current_role=get_jwt().get("role"),
                active_only=get_jwt().get("role") == "driver" or request.args.get("active") == "true",
            )
        }
    )


@preventive_maintenance_bp.post("/compliance/types")
@role_required("owner", "admin")
def create_compliance_item_type_route():
    item_type = create_compliance_item_type(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"type": item_type}, message="Compliance item type created successfully.", status_code=201)


@preventive_maintenance_bp.patch("/compliance/types/<type_id>")
@role_required("owner", "admin")
def update_compliance_item_type_route(type_id: str):
    item_type = update_compliance_item_type(
        type_id=type_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"type": item_type}, message="Compliance item type updated successfully.")


@preventive_maintenance_bp.get("/compliance/records")
@role_required("owner", "admin", "driver")
def get_compliance_records_route():
    vehicle_id = request.args.get("vehicle_id")
    records = list_compliance_records(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        vehicle_id=vehicle_id,
    )
    summary = get_compliance_dashboard_summary(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"records": records, "summary": summary})


@preventive_maintenance_bp.post("/compliance/records")
@role_required("owner", "admin")
def create_compliance_record_route():
    record = create_compliance_record(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"record": record}, message="Compliance record created successfully.", status_code=201)


@preventive_maintenance_bp.patch("/compliance/records/<record_id>")
@role_required("owner", "admin")
def update_compliance_record_route(record_id: str):
    record = update_compliance_record(
        record_id=record_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"record": record}, message="Compliance record updated successfully.")


@preventive_maintenance_bp.patch("/compliance/records/<record_id>/renew")
@role_required("owner", "admin")
def renew_compliance_record_route(record_id: str):
    record = renew_compliance_record(
        record_id=record_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"record": record}, message="Compliance record renewed successfully.")
