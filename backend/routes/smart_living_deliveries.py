from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity

from services.smart_living_delivery_service import (
    acknowledge_issue, cancel_batch, confirm_delivery, correct_issue, create_batch, create_order, driver_batch_action, get_order,
    issue_batch, list_batches, list_orders, reassign_batch, reconcile_batch, record_delivery, record_return,
    cancel_daily_run, certify_order, create_certified_order, create_daily_run, get_daily_run,
    list_daily_runs, list_scheduler_queue, lock_daily_run, publish_daily_run, scheduler_metadata, update_daily_run,
    accept_run_assignment, issue_scheduler_run, reissue_scheduler_run, respond_to_custody,
    start_scheduler_run, update_scheduler_stop, complete_scheduler_run, handoff_scheduler_returns,
    list_accountability_batches, receive_scheduler_returns, create_delivery_exception,
    list_field_agent_deliveries,
    list_delivery_exceptions, update_delivery_exception, investigate_delivery_exception,
    reconcile_scheduler_batch, close_scheduler_batch, reopen_scheduler_batch, delivery_accountability_report,
)
from utils.decorators import permission_required
from utils.responses import success_response
from utils.api_error import ApiError


smart_living_deliveries_bp = Blueprint("smart_living_deliveries", __name__)


@smart_living_deliveries_bp.get("/debug/routes")
def delivery_route_audit():
    if current_app.config.get("ENV_NAME") != "development":
        raise ApiError("Route audit is available only in development.", status_code=404)
    items = []
    for rule in current_app.url_map.iter_rules():
        if rule.rule.startswith("/api/smart-living-deliveries"):
            items.append({
                "path": rule.rule,
                "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
                "endpoint": rule.endpoint,
            })
    return success_response(data={"items": sorted(items, key=lambda item: item["path"])})


@smart_living_deliveries_bp.get("/orders")
@permission_required("deliveries.view")
def orders_list():
    return success_response(data=list_orders(get_jwt_identity(), request.args.to_dict()))


@smart_living_deliveries_bp.post("/orders")
@permission_required("deliveries.create")
def orders_create():
    return success_response(data={"order": create_order(request.get_json(silent=True) or {}, get_jwt_identity())}, status_code=201)


@smart_living_deliveries_bp.get("/orders/<order_id>")
@permission_required("deliveries.view")
def orders_get(order_id):
    return success_response(data={"order": get_order(order_id, get_jwt_identity())})


@smart_living_deliveries_bp.get("/batches")
@permission_required("deliveries.view")
def batches_list():
    return success_response(data=list_batches(get_jwt_identity(), request.args.to_dict()))


@smart_living_deliveries_bp.post("/batches")
@permission_required("batches.create")
def batches_create():
    return success_response(data={"batch": create_batch(request.get_json(silent=True) or {}, get_jwt_identity())}, status_code=201)


@smart_living_deliveries_bp.patch("/batches/<batch_id>/assignment")
@permission_required("deliveries.assign")
def batch_reassign(batch_id):
    return success_response(data={"batch":reassign_batch(batch_id,request.get_json(silent=True) or {},get_jwt_identity())})


@smart_living_deliveries_bp.post("/batches/<batch_id>/cancel")
@permission_required("batches.manage")
def batch_cancel(batch_id):
    return success_response(data={"batch":cancel_batch(batch_id,(request.get_json(silent=True) or {}).get("reason"),get_jwt_identity())})


@smart_living_deliveries_bp.post("/batches/<batch_id>/issue")
@permission_required("items.issue")
def batch_issue(batch_id):
    return success_response(data={"issue": issue_batch(batch_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.patch("/batches/<batch_id>/issue")
@permission_required("items.correct")
def batch_issue_correct(batch_id):
    return success_response(data={"issue":correct_issue(batch_id,request.get_json(silent=True) or {},get_jwt_identity())})


@smart_living_deliveries_bp.post("/batches/<batch_id>/acknowledge")
@permission_required("trips.execute")
def batch_acknowledge(batch_id):
    return success_response(data={"issue": acknowledge_issue(batch_id, get_jwt_identity())})


@smart_living_deliveries_bp.post("/batches/<batch_id>/<action>")
@permission_required("trips.execute")
def batch_action(batch_id, action):
    return success_response(data={"batch": driver_batch_action(batch_id, action, get_jwt_identity())})


@smart_living_deliveries_bp.post("/orders/<order_id>/delivery")
@permission_required("trips.execute")
def order_delivery(order_id):
    return success_response(data={"order": record_delivery(order_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/orders/<order_id>/confirm")
@permission_required("delivery.confirm")
def order_confirm(order_id):
    return success_response(data={"order":confirm_delivery(order_id,request.get_json(silent=True) or {},get_jwt_identity())})


@smart_living_deliveries_bp.post("/batches/<batch_id>/returns")
@permission_required("items.receive")
def batch_returns(batch_id):
    return success_response(data={"return": record_return(batch_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/batches/<batch_id>/reconcile")
@permission_required("batches.manage")
def batch_reconcile(batch_id):
    return success_response(data={"batch": reconcile_batch(batch_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.get("/my-schedule")
@permission_required("deliveries.view_own")
def my_schedule():
    return success_response(data=list_batches(get_jwt_identity(), request.args.to_dict()))


@smart_living_deliveries_bp.get("/field-schedule")
@permission_required("deliveries.view_assigned")
def field_schedule():
    return success_response(data=list_field_agent_deliveries(get_jwt_identity(), request.args.to_dict()))


# Canonical scheduler endpoints. They share the legacy delivery collections so
# Smart Living can later create the exact same certified-order records.

@smart_living_deliveries_bp.get("/scheduler/metadata")
@permission_required("delivery_scheduler.view")
def scheduler_options():
    return success_response(data=scheduler_metadata(get_jwt_identity(), request.args.get("branch_id")))


@smart_living_deliveries_bp.get("/scheduler/queue")
@permission_required("delivery_scheduler.view")
def scheduler_queue():
    return success_response(data=list_scheduler_queue(get_jwt_identity(), request.args.to_dict()))


@smart_living_deliveries_bp.post("/scheduler/orders")
@permission_required("deliveries.create")
def certified_order_create():
    return success_response(data={"order": create_certified_order(request.get_json(silent=True) or {}, get_jwt_identity())}, status_code=201)


@smart_living_deliveries_bp.post("/scheduler/orders/<order_id>/certify")
@permission_required("deliveries.update")
def certified_order_certify(order_id):
    return success_response(data={"order": certify_order(order_id, get_jwt_identity())})


@smart_living_deliveries_bp.get("/scheduler/runs")
@permission_required("delivery_scheduler.view")
def daily_runs_list():
    return success_response(data=list_daily_runs(get_jwt_identity(), request.args.to_dict()))


@smart_living_deliveries_bp.post("/scheduler/runs")
@permission_required("delivery_scheduler.manage")
def daily_run_create():
    return success_response(data={"run": create_daily_run(request.get_json(silent=True) or {}, get_jwt_identity())}, status_code=201)


@smart_living_deliveries_bp.get("/scheduler/runs/<run_id>")
@permission_required("delivery_scheduler.view")
def daily_run_get(run_id):
    return success_response(data={"run": get_daily_run(run_id, get_jwt_identity())})


@smart_living_deliveries_bp.patch("/scheduler/runs/<run_id>")
@permission_required("delivery_scheduler.manage")
def daily_run_update(run_id):
    return success_response(data={"run": update_daily_run(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/publish")
@permission_required("delivery_runs.publish")
def daily_run_publish(run_id):
    return success_response(data={"run": publish_daily_run(run_id, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/lock")
@permission_required("delivery_runs.lock")
def daily_run_lock(run_id):
    return success_response(data={"run": lock_daily_run(run_id, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/cancel")
@permission_required("delivery_scheduler.manage")
def daily_run_cancel(run_id):
    return success_response(data={"run": cancel_daily_run(run_id, (request.get_json(silent=True) or {}).get("reason"), get_jwt_identity())})


@smart_living_deliveries_bp.get("/scheduler/assigned")
@permission_required("delivery_schedule.view_assigned")
def assigned_delivery_schedule():
    return success_response(data=list_daily_runs(get_jwt_identity(), request.args.to_dict(), assigned_only=True))


@smart_living_deliveries_bp.get("/scheduler/loading")
@permission_required("loading_schedule.view")
def loading_schedule():
    return success_response(data=list_daily_runs(get_jwt_identity(), request.args.to_dict(), loading_only=True))


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/accept")
@permission_required("delivery_routes.execute")
def daily_run_accept(run_id):
    return success_response(data={"run": accept_run_assignment(run_id, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/issue")
@permission_required("delivery_items.issue")
def daily_run_issue(run_id):
    return success_response(data={"issue": issue_scheduler_run(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/reissue")
@permission_required("delivery_items.issue")
def daily_run_reissue(run_id):
    return success_response(data={"issue": reissue_scheduler_run(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/custody")
@permission_required("delivery_items.acknowledge")
def daily_run_custody(run_id):
    return success_response(data={"issue": respond_to_custody(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/start")
@permission_required("delivery_execution.manage")
def daily_run_start(run_id):
    return success_response(data={"run": start_scheduler_run(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/stops/<stop_id>")
@permission_required("delivery_execution.manage")
def daily_run_stop_update(run_id, stop_id):
    return success_response(data={"run": update_scheduler_stop(run_id, stop_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/complete-execution")
@permission_required("delivery_execution.manage")
def daily_run_execution_complete(run_id):
    return success_response(data={"run": complete_scheduler_run(run_id, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/return-handoff")
@permission_required("delivery_execution.manage")
def daily_run_return_handoff(run_id):
    return success_response(data={"run": handoff_scheduler_returns(run_id, get_jwt_identity())})


@smart_living_deliveries_bp.get("/accountability/batches")
@permission_required("returns.manage")
def accountability_batches():
    return success_response(data=list_accountability_batches(get_jwt_identity(), request.args.to_dict()))


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/returns/receive")
@permission_required("returns.receive")
def scheduler_returns_receive(run_id):
    payload = request.get_json(silent=True) or {}
    payload["_idempotency_key"] = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    return success_response(data={"return": receive_scheduler_returns(run_id, payload, get_jwt_identity())}, status_code=201)


@smart_living_deliveries_bp.get("/exceptions")
@permission_required("exceptions.manage")
def delivery_exceptions_list():
    return success_response(data=list_delivery_exceptions(get_jwt_identity(), request.args.to_dict()))


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/exceptions")
@permission_required("exceptions.manage")
def delivery_exception_create(run_id):
    payload = request.get_json(silent=True) or {}
    payload["_idempotency_key"] = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    return success_response(data={"exception": create_delivery_exception(run_id, payload, get_jwt_identity())}, status_code=201)


@smart_living_deliveries_bp.patch("/exceptions/<exception_id>")
@permission_required("exceptions.manage")
def delivery_exception_update(exception_id):
    return success_response(data={"exception": update_delivery_exception(exception_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.put("/exceptions/<exception_id>/investigation")
@permission_required("investigations.manage")
def delivery_exception_investigate(exception_id):
    return success_response(data={"investigation": investigate_delivery_exception(exception_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/reconcile")
@permission_required("reconciliation.manage")
def scheduler_batch_reconcile(run_id):
    return success_response(data={"run": reconcile_scheduler_batch(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/close")
@permission_required("delivery_batches.close")
def scheduler_batch_close(run_id):
    return success_response(data={"run": close_scheduler_batch(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.post("/scheduler/runs/<run_id>/reopen")
@permission_required("delivery_batches.reopen")
def scheduler_batch_reopen(run_id):
    return success_response(data={"run": reopen_scheduler_batch(run_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_deliveries_bp.get("/accountability/reports")
@permission_required("returns.manage")
def accountability_reports():
    return success_response(data=delivery_accountability_report(get_jwt_identity(), request.args.to_dict()))
