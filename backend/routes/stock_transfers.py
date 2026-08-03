from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.stock_transfer_service import (
    acknowledge_stock_transfer, approve_stock_transfer, arrive_stock_transfer, cancel_stock_transfer,
    complete_stock_transfer, create_stock_transfer, get_stock_transfer,
    list_stock_transfers, list_stock_transfer_recipient_options, receive_stock_transfer, release_stock_transfer,
    review_stock_transfer_variance,
    confirm_supplier_pickup,
    record_supplier_pickup_handover,
    report_stock_transfer_delivery_exception,
    schedule_stock_transfer, start_stock_transfer, submit_stock_transfer,
    update_stock_transfer_recipient,
    verify_stock_transfer_delivery,
    take_delivery_exception_action, transition_delivery_exception_return,
    start_delivery_exception_investigation, update_delivery_exception_investigation,
    transition_delivery_exception_investigation, complete_delivery_investigation_action,
)
from utils.decorators import role_required
from utils.responses import success_response


stock_transfers_bp = Blueprint("stock_transfers", __name__)


def _identity(): return get_jwt_identity(), get_jwt().get("role")


@stock_transfers_bp.get("")
@role_required("owner", "admin", "driver")
def list_route():
    user_id, role = _identity()
    return success_response(data=list_stock_transfers(current_user_id=user_id, current_role=role, page=request.args.get("page", 1, type=int), page_size=request.args.get("page_size", 25, type=int), status=request.args.get("status"), operation_type=request.args.get("operation_type"), active_tasks=request.args.get("active_tasks", "").strip().lower() in {"1", "true", "yes"}))


@stock_transfers_bp.post("")
@role_required("owner", "admin")
def create_route():
    user_id, role = _identity()
    payload = request.get_json(silent=True) or {}
    if request.headers.get("Idempotency-Key") and not payload.get("idempotency_key"):
        payload["idempotency_key"] = request.headers["Idempotency-Key"]
    return success_response(data={"transfer": create_stock_transfer(payload, current_user_id=user_id, current_role=role)}, status_code=201)


@stock_transfers_bp.get("/recipient-options")
@role_required("owner", "admin")
def recipient_options_route():
    user_id, role = _identity()
    return success_response(data=list_stock_transfer_recipient_options(
        branch_id=request.args.get("branch_id"), current_user_id=user_id, current_role=role,
    ))


@stock_transfers_bp.get("/<transfer_id>")
@role_required("owner", "admin", "driver")
def detail_route(transfer_id):
    user_id, role = _identity(); return success_response(data={"transfer": get_stock_transfer(transfer_id, current_user_id=user_id, current_role=role)})


def _action(transfer_id, handler, *, payload=False):
    user_id, role = _identity(); kwargs = {"current_user_id": user_id, "current_role": role}
    result = handler(transfer_id, request.get_json(silent=True) or {}, **kwargs) if payload else handler(transfer_id, **kwargs)
    return success_response(data={"transfer": result})


@stock_transfers_bp.patch("/<transfer_id>/submit")
@role_required("owner", "admin")
def submit_route(transfer_id): return _action(transfer_id, submit_stock_transfer)


@stock_transfers_bp.patch("/<transfer_id>/approve")
@role_required("owner", "admin")
def approve_route(transfer_id): return _action(transfer_id, approve_stock_transfer)


@stock_transfers_bp.patch("/<transfer_id>/schedule")
@role_required("owner", "admin")
def schedule_route(transfer_id): return _action(transfer_id, schedule_stock_transfer, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/recipient")
@role_required("owner", "admin")
def recipient_route(transfer_id): return _action(transfer_id, update_stock_transfer_recipient, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/release")
@role_required("owner", "admin", "driver")
def release_route(transfer_id): return _action(transfer_id, release_stock_transfer, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/acknowledge")
@role_required("driver")
def acknowledge_route(transfer_id): return _action(transfer_id, acknowledge_stock_transfer)


@stock_transfers_bp.patch("/<transfer_id>/start")
@role_required("owner", "admin", "driver")
def start_route(transfer_id): return _action(transfer_id, start_stock_transfer, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/arrive")
@role_required("owner", "admin", "driver")
def arrive_route(transfer_id): return _action(transfer_id, arrive_stock_transfer, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/supplier-handover")
@role_required("driver")
def supplier_handover_route(transfer_id): return _action(transfer_id, record_supplier_pickup_handover, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/pickup-confirmation")
@role_required("driver")
def pickup_confirmation_route(transfer_id): return _action(transfer_id, confirm_supplier_pickup, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/verify-delivery")
@role_required("driver")
def verify_delivery_route(transfer_id): return _action(transfer_id, verify_stock_transfer_delivery, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/report-exception")
@role_required("driver")
def report_exception_route(transfer_id): return _action(transfer_id, report_stock_transfer_delivery_exception, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/exception-action")
@role_required("owner", "admin")
def exception_action_route(transfer_id): return _action(transfer_id, take_delivery_exception_action, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/exception-return/<target>")
@role_required("owner", "admin", "driver")
def exception_return_route(transfer_id, target):
    user_id, role = _identity()
    return success_response(data={"transfer": transition_delivery_exception_return(transfer_id, target, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)})


@stock_transfers_bp.patch("/<transfer_id>/investigation/start")
@role_required("owner", "admin")
def investigation_start_route(transfer_id): return _action(transfer_id, start_delivery_exception_investigation, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/investigation/update")
@role_required("owner", "admin")
def investigation_update_route(transfer_id): return _action(transfer_id, update_delivery_exception_investigation, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/investigation/<target>")
@role_required("owner", "admin")
def investigation_transition_route(transfer_id, target):
    user_id, role = _identity()
    return success_response(data={"transfer": transition_delivery_exception_investigation(transfer_id, target, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)})


@stock_transfers_bp.patch("/<transfer_id>/investigation-action/<action_id>/complete")
@role_required("owner", "admin")
def investigation_action_complete_route(transfer_id, action_id):
    user_id, role = _identity()
    return success_response(data={"transfer": complete_delivery_investigation_action(transfer_id, action_id, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)})


@stock_transfers_bp.patch("/<transfer_id>/receive")
@role_required("owner", "admin", "branch_manager", "branch_warehouse_coordinator")
def receive_route(transfer_id): return _action(transfer_id, receive_stock_transfer, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/complete")
@role_required("owner", "admin")
def complete_route(transfer_id): return _action(transfer_id, complete_stock_transfer, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/variance")
@role_required("owner", "admin")
def variance_route(transfer_id): return _action(transfer_id, review_stock_transfer_variance, payload=True)


@stock_transfers_bp.patch("/<transfer_id>/cancel")
@role_required("owner", "admin")
def cancel_route(transfer_id): return _action(transfer_id, cancel_stock_transfer, payload=True)
