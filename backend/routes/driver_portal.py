from flask import Blueprint, Response
from flask_jwt_extended import get_jwt_identity

from services.assignment_service import get_active_assignment_for_driver
from flask import request

from services.collection_service import get_driver_dashboard_summary, submit_driver_payment
from services.dispatch_planner_service import (
    accept_driver_dispatch_job,
    get_driver_dispatch_job,
    list_driver_dispatch_jobs,
    reject_driver_dispatch_job,
    request_dispatch_clarification,
    update_driver_dispatch_job_workflow,
)
from services.dispatch_financial_service import (
    get_dispatch_financial_detail,
    list_driver_dispatch_financials,
    submit_dispatch_financial_incident,
    submit_driver_dispatch_expense,
    submit_driver_dispatch_money,
)
from services.dispatch_opportunity_service import (
    create_driver_dispatch_opportunity,
    get_dispatch_opportunity_by_id,
    list_dispatch_opportunities,
    list_dispatch_opportunity_options,
    submit_driver_dispatch_opportunity,
    update_driver_dispatch_opportunity,
    withdraw_driver_dispatch_opportunity,
)
from services.fuel_service import list_fuel_logs
from services.dispatch_fuel_service import (
    get_dispatch_fuel_accountability,
    record_dispatch_opening_fuel,
)
from services.maintenance_service import (
    get_driver_maintenance_job_by_id,
    list_driver_maintenance_jobs,
    list_driver_maintenance_progress_logs,
    submit_driver_maintenance_confirmation,
)
from services.preventive_maintenance_service import get_driver_preventive_maintenance_snapshot
from services.operational_task_service import (
    get_driver_operations_dashboard_summary,
    list_driver_operational_tasks,
)
from services.wallet_service import get_logged_in_driver_wallet
from services.driver_private_finance_service import (
    create_private_entry,
    delete_private_entry,
    export_private_entries_csv,
    list_private_entries,
    private_entry_history,
    private_finance_summary,
    update_private_entry,
)
from utils.decorators import driver_mode_required, role_required
from utils.responses import success_response


driver_portal_bp = Blueprint("driver_portal", __name__)


@driver_portal_bp.get("/private-finance")
@role_required("driver")
@driver_mode_required("targets")
def get_private_finance_entries():
    return success_response(data=list_private_entries(
        get_jwt_identity(), request.args.get("start_date"), request.args.get("end_date"),
        request.args.get("platform"), request.args.get("page", default=1, type=int),
        request.args.get("page_size", default=25, type=int),
    ))


@driver_portal_bp.post("/private-finance")
@role_required("driver")
@driver_mode_required("targets")
def post_private_finance_entry():
    return success_response(
        data={"entry": create_private_entry(get_jwt_identity(), request.get_json(silent=True) or {})},
        message="Private earnings entry saved.", status_code=201,
    )


@driver_portal_bp.patch("/private-finance/<entry_id>")
@role_required("driver")
@driver_mode_required("targets")
def patch_private_finance_entry(entry_id):
    return success_response(data={"entry": update_private_entry(
        get_jwt_identity(), entry_id, request.get_json(silent=True) or {}
    )}, message="Private earnings entry updated.")


@driver_portal_bp.delete("/private-finance/<entry_id>")
@role_required("driver")
@driver_mode_required("targets")
def remove_private_finance_entry(entry_id):
    return success_response(data=delete_private_entry(get_jwt_identity(), entry_id), message="Private earnings entry deleted.")


@driver_portal_bp.get("/private-finance/<entry_id>/history")
@role_required("driver")
@driver_mode_required("targets")
def get_private_finance_history(entry_id):
    return success_response(data={"history": private_entry_history(get_jwt_identity(), entry_id)})


@driver_portal_bp.get("/private-finance/summary")
@role_required("driver")
@driver_mode_required("targets")
def get_private_finance_summary_route():
    return success_response(data={"summary": private_finance_summary(
        get_jwt_identity(), request.args.get("start_date"), request.args.get("end_date"),
        request.args.get("platform"), request.args.get("period", "daily"),
    )})


@driver_portal_bp.get("/private-finance/export.csv")
@role_required("driver")
@driver_mode_required("targets")
def export_private_finance_route():
    content = export_private_entries_csv(
        get_jwt_identity(), request.args.get("start_date"), request.args.get("end_date"), request.args.get("platform")
    )
    return Response(content, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=my-earnings.csv"})


@driver_portal_bp.get("/active-assignment")
@role_required("driver")
def get_active_assignment():
    assignment = get_active_assignment_for_driver(get_jwt_identity())
    return success_response(data={"assignment": assignment})


@driver_portal_bp.get("/dashboard-summary")
@role_required("driver")
@driver_mode_required("targets")
def get_dashboard_summary():
    summary = get_driver_dashboard_summary(get_jwt_identity())
    return success_response(data={"summary": summary})


@driver_portal_bp.get("/operational-tasks")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_operational_tasks():
    return success_response(data=list_driver_operational_tasks(get_jwt_identity()))


@driver_portal_bp.get("/operations-summary")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_operations_summary():
    return success_response(data=get_driver_operations_dashboard_summary(get_jwt_identity()))


@driver_portal_bp.get("/wallet")
@role_required("driver")
@driver_mode_required("targets")
def get_driver_wallet():
    wallet = get_logged_in_driver_wallet(get_jwt_identity())
    return success_response(data={"wallet": wallet})


@driver_portal_bp.get("/preventive-maintenance")
@role_required("driver")
def get_driver_preventive_maintenance():
    return success_response(data=get_driver_preventive_maintenance_snapshot(get_jwt_identity()))


@driver_portal_bp.get("/fuel-logs")
@role_required("driver")
@driver_mode_required("operations")
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
@driver_mode_required("targets")
def submit_payment():
    payment = submit_driver_payment(request.get_json(silent=True) or {}, get_jwt_identity())
    return success_response(
        data={"payment": payment},
        message="Payment submitted successfully and is pending admin confirmation.",
        status_code=201,
    )


@driver_portal_bp.get("/dispatch-jobs")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_jobs():
    return success_response(
        data=list_driver_dispatch_jobs(
            current_user_id=get_jwt_identity(),
            section=request.args.get("section"),
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=10, type=int),
            include_summary=request.args.get("include_summary", default="false").lower() == "true",
        )
    )


@driver_portal_bp.get("/dispatch-jobs/<job_id>")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_job_route(job_id: str):
    return success_response(data={"job": get_driver_dispatch_job(job_id, current_user_id=get_jwt_identity())})


@driver_portal_bp.patch("/dispatch-jobs/<job_id>/accept")
@role_required("driver")
@driver_mode_required("operations")
def accept_driver_dispatch(job_id: str):
    job = accept_driver_dispatch_job(job_id, current_user_id=get_jwt_identity())
    return success_response(
        data={"job": job},
        message="Dispatch accepted successfully.",
    )


@driver_portal_bp.patch("/dispatch-jobs/<job_id>/clarify")
@role_required("driver")
@driver_mode_required("operations")
def clarify_driver_dispatch(job_id: str):
    job = request_dispatch_clarification(
        job_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"job": job},
        message="Dispatch clarification request sent successfully.",
    )


@driver_portal_bp.patch("/dispatch-jobs/<job_id>/reject")
@role_required("driver")
@driver_mode_required("operations")
def reject_driver_dispatch(job_id: str):
    job = reject_driver_dispatch_job(
        job_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"job": job},
        message="Dispatch assignment rejected successfully.",
    )


@driver_portal_bp.patch("/dispatch-jobs/<job_id>/workflow")
@role_required("driver")
@driver_mode_required("operations")
def update_driver_dispatch_workflow(job_id: str):
    job = update_driver_dispatch_job_workflow(
        job_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"job": job},
        message="Dispatch updated successfully.",
    )


@driver_portal_bp.get("/dispatch-jobs/<job_id>/fuel")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_fuel(job_id: str):
    return success_response(
        data=get_dispatch_fuel_accountability(
            job_id,
            current_user_id=get_jwt_identity(),
            current_role="driver",
        )
    )


@driver_portal_bp.patch("/dispatch-jobs/<job_id>/fuel/opening")
@role_required("driver")
@driver_mode_required("operations")
def confirm_driver_dispatch_opening_fuel(job_id: str):
    return success_response(
        data=record_dispatch_opening_fuel(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role="driver",
        ),
        message="Opening fuel and odometer confirmed successfully.",
    )


@driver_portal_bp.get("/dispatch-financials")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_financials_route():
    return success_response(
        data=list_driver_dispatch_financials(
            current_user_id=get_jwt_identity(),
            current_role="driver",
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=10, type=int),
            financial_status=request.args.get("financial_status"),
        )
    )


@driver_portal_bp.get("/dispatch-financials/<job_id>")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_financial_detail_route(job_id: str):
    return success_response(
        data=get_dispatch_financial_detail(
            job_id,
            current_user_id=get_jwt_identity(),
            current_role="driver",
        )
    )


@driver_portal_bp.post("/dispatch-financials/<job_id>/money")
@role_required("driver")
@driver_mode_required("operations")
def submit_driver_dispatch_money_route(job_id: str):
    return success_response(
        data=submit_driver_dispatch_money(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role="driver",
        ),
        message="Dispatch money submitted successfully.",
        status_code=201,
    )


@driver_portal_bp.post("/dispatch-financials/<job_id>/expenses")
@role_required("driver")
@driver_mode_required("operations")
def submit_driver_dispatch_expense_route(job_id: str):
    return success_response(
        data=submit_driver_dispatch_expense(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role="driver",
        ),
        message="Dispatch expense submitted successfully.",
        status_code=201,
    )


@driver_portal_bp.post("/dispatch-financials/<job_id>/incidents")
@role_required("driver")
@driver_mode_required("operations")
def submit_driver_dispatch_incident_route(job_id: str):
    return success_response(
        data=submit_dispatch_financial_incident(
            job_id,
            request.get_json(silent=True) or {},
            current_user_id=get_jwt_identity(),
            current_role="driver",
        ),
        message="Dispatch incident submitted successfully.",
        status_code=201,
    )


@driver_portal_bp.get("/dispatch-opportunities/options")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_opportunity_options_route():
    return success_response(data=list_dispatch_opportunity_options(current_role="driver"))


@driver_portal_bp.get("/dispatch-opportunities")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_opportunities_route():
    return success_response(
        data=list_dispatch_opportunities(
            current_user_id=get_jwt_identity(),
            current_role="driver",
            page=request.args.get("page", default=1, type=int),
            page_size=request.args.get("page_size", default=10, type=int),
            search_query=request.args.get("q"),
            status=request.args.get("status"),
            date_from=request.args.get("date_from"),
            date_to=request.args.get("date_to"),
        )
    )


@driver_portal_bp.post("/dispatch-opportunities")
@role_required("driver")
@driver_mode_required("operations")
def create_driver_dispatch_opportunity_route():
    opportunity = create_driver_dispatch_opportunity(
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role="driver",
    )
    return success_response(
        data={"opportunity": opportunity},
        message="Dispatch opportunity saved successfully.",
        status_code=201,
    )


@driver_portal_bp.get("/dispatch-opportunities/<opportunity_id>")
@role_required("driver")
@driver_mode_required("operations")
def get_driver_dispatch_opportunity_route(opportunity_id: str):
    return success_response(
        data={
            "opportunity": get_dispatch_opportunity_by_id(
                opportunity_id,
                current_user_id=get_jwt_identity(),
                current_role="driver",
            )
        }
    )


@driver_portal_bp.patch("/dispatch-opportunities/<opportunity_id>")
@role_required("driver")
@driver_mode_required("operations")
def update_driver_dispatch_opportunity_route(opportunity_id: str):
    opportunity = update_driver_dispatch_opportunity(
        opportunity_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role="driver",
    )
    return success_response(
        data={"opportunity": opportunity},
        message="Dispatch opportunity updated successfully.",
    )


@driver_portal_bp.patch("/dispatch-opportunities/<opportunity_id>/submit")
@role_required("driver")
@driver_mode_required("operations")
def submit_driver_dispatch_opportunity_route(opportunity_id: str):
    opportunity = submit_driver_dispatch_opportunity(
        opportunity_id,
        current_user_id=get_jwt_identity(),
        current_role="driver",
    )
    return success_response(
        data={"opportunity": opportunity},
        message="Dispatch opportunity submitted for review successfully.",
    )


@driver_portal_bp.patch("/dispatch-opportunities/<opportunity_id>/withdraw")
@role_required("driver")
@driver_mode_required("operations")
def withdraw_driver_dispatch_opportunity_route(opportunity_id: str):
    opportunity = withdraw_driver_dispatch_opportunity(
        opportunity_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role="driver",
    )
    return success_response(
        data={"opportunity": opportunity},
        message="Dispatch opportunity withdrawn successfully.",
    )
