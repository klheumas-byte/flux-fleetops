from datetime import datetime, timezone

from bson import ObjectId

from extensions import get_collection
from models.finance_account import serialize_finance_account_snapshot
from services.finance_account_service import (
    decrement_finance_account_balance,
    get_finance_account_document,
    post_ledger_entry,
    run_finance_transaction,
)
from services.payment_cycle_service import agreement_from_assignment
from utils.api_error import ApiError


def now_utc():
    return datetime.now(timezone.utc)


def _object_id(value, field_name):
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _positive_amount(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ApiError(f"{field_name} must be a positive number.", status_code=400)
    return round(float(value), 2)


def build_pending_fuel_advance(payload: dict, *, driver: dict | None, assignment: dict | None):
    if not driver:
        raise ApiError("A driver/person is required for a Fuel Purchase movement.", status_code=400)
    if assignment:
        agreement = agreement_from_assignment(assignment)
        if agreement.get("status") == "active" and float(agreement.get("weekly_amount") or 0) > 0:
            raise ApiError(
                "Company fuel advances cannot be issued for an active Weekly Remittance assignment.",
                status_code=409,
            )
    account = get_finance_account_document(payload.get("finance_account_id"))
    if account.get("status") != "active":
        raise ApiError("Selected finance account is inactive.", status_code=400)
    issued_amount = _positive_amount(payload.get("issued_amount"), "issued_amount")
    return {
        "status": "pending_approval",
        "issued_amount": issued_amount,
        "spent_amount": 0.0,
        "returned_amount": 0.0,
        "outstanding_amount": issued_amount,
        "finance_account_id": account["_id"],
        "finance_account_snapshot": serialize_finance_account_snapshot(account),
        "issued_to_user_id": driver["_id"],
        "issued_by": None,
        "issued_at": None,
        "fuel_log_id": None,
        "expense_id": None,
        "settled_by": None,
        "settled_at": None,
        "returns": [],
    }


def issue_fuel_purchase_advance(movement: dict, *, actor_id, actor_role: str):
    advance = movement.get("fuel_advance") or {}
    if movement.get("movement_type") != "fuel_purchase" or not advance:
        raise ApiError("Fuel advance details are missing from this movement.", status_code=400)
    if movement.get("status") not in {"draft", "pending_approval"}:
        raise ApiError(f"Vehicle movement cannot transition from {movement.get('status')} to approved.", status_code=400)
    if advance.get("status") != "pending_approval":
        raise ApiError("Fuel advance has already been issued.", status_code=409)
    account = get_finance_account_document(advance.get("finance_account_id"))
    if account.get("status") != "active":
        raise ApiError("Selected finance account is inactive.", status_code=400)
    amount = _positive_amount(advance.get("issued_amount"), "issued_amount")
    if round(float(account.get("current_balance") or 0), 2) < amount:
        raise ApiError("Finance account balance is insufficient.", status_code=400)
    timestamp = now_utc()
    actor = _object_id(actor_id, "actor_id")
    history = {"status": "approved", "timestamp": timestamp, "actor_id": actor}
    audit = {
        "event": "fuel_advance_issued", "timestamp": timestamp, "actor_id": actor,
        "actor_role": actor_role, "amount": amount,
        "finance_account_id": str(account["_id"]), "immutable": True,
    }
    update = {
        "status": "approved", "approved_by": actor, "approved_at": timestamp, "updated_at": timestamp,
        "fuel_advance.status": "issued", "fuel_advance.issued_by": actor,
        "fuel_advance.issued_at": timestamp,
        "fuel_advance.finance_account_snapshot": serialize_finance_account_snapshot(account),
    }

    def post(session):
        kwargs = {"session": session} if session else {}
        result = get_collection("vehicle_movements").update_one(
            {"_id": movement["_id"], "status": movement.get("status"), "fuel_advance.status": "pending_approval"},
            {"$set": update, "$push": {"status_history": history, "audit_log": audit}}, **kwargs,
        )
        if result.modified_count != 1:
            raise ApiError("Fuel advance was already issued or the movement changed.", status_code=409)
        decrement_finance_account_balance(
            account["_id"], amount, actor_id=actor,
            reference_type="fuel_advance_issue", reference_id=movement["_id"],
            effective_date=timestamp.date().isoformat(), session=session,
        )

    run_finance_transaction(post)
    return get_collection("vehicle_movements").find_one({"_id": movement["_id"]})


def recognize_fuel_advance_purchase(fuel_log: dict, *, actor_id, actor_role: str):
    movement_id = fuel_log.get("fuel_advance_movement_id")
    if not movement_id:
        return None
    movement = get_collection("vehicle_movements").find_one({"_id": movement_id})
    if not movement or movement.get("movement_type") != "fuel_purchase":
        raise ApiError("Linked Fuel Purchase movement was not found.", status_code=404)
    advance = movement.get("fuel_advance") or {}
    if advance.get("status") != "issued" or advance.get("fuel_log_id"):
        raise ApiError("This fuel advance is not available for a new purchase.", status_code=409)
    spent = _positive_amount(fuel_log.get("amount"), "amount")
    available = round(float(advance.get("issued_amount") or 0) - float(advance.get("returned_amount") or 0), 2)
    if spent > available:
        raise ApiError("Actual fuel spend cannot exceed the unreturned advance amount.", status_code=400)
    timestamp = now_utc()
    actor = _object_id(actor_id, "actor_id")
    outstanding = round(available - spent, 2)

    from services.expense_service import create_paid_fuel_advance_expense

    result_holder = {}
    def post(session):
        kwargs = {"session": session} if session else {}
        expense = create_paid_fuel_advance_expense(
            fuel_log=fuel_log, movement=movement, actor_id=actor, actor_role=actor_role, session=session,
        )
        log_update = get_collection("fuel_logs").update_one(
            {"_id": fuel_log["_id"], "status": "submitted", "expense_id": {"$in": [None]}},
            {"$set": {"status": "approved", "approved_by": actor, "expense_id": expense["_id"], "updated_at": timestamp}},
            **kwargs,
        )
        if log_update.modified_count != 1:
            raise ApiError("Fuel purchase was already approved.", status_code=409)
        advance_status = "settled" if outstanding == 0 else "return_outstanding"
        movement_updates = {
            "fuel_advance.status": advance_status,
            "fuel_advance.spent_amount": spent,
            "fuel_advance.outstanding_amount": outstanding,
            "fuel_advance.fuel_log_id": fuel_log["_id"],
            "fuel_advance.expense_id": expense["_id"],
            "updated_at": timestamp,
        }
        if outstanding == 0:
            movement_updates.update({"fuel_advance.settled_by": actor, "fuel_advance.settled_at": timestamp})
        movement_update = get_collection("vehicle_movements").update_one(
            {"_id": movement["_id"], "fuel_advance.status": "issued", "fuel_advance.fuel_log_id": None},
            {"$set": movement_updates, "$push": {"audit_log": {
                "event": "fuel_advance_purchase_recognized", "timestamp": timestamp,
                "actor_id": actor, "actor_role": actor_role, "amount": spent,
                "expense_id": str(expense["_id"]), "immutable": True,
            }}}, **kwargs,
        )
        if movement_update.modified_count != 1:
            raise ApiError("Fuel advance purchase was already recorded.", status_code=409)
        result_holder["expense"] = expense

    run_finance_transaction(post)
    return result_holder["expense"]


def return_fuel_advance_balance(movement_id, payload: dict, *, actor_id, actor_role: str, idempotency_key: str):
    if actor_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to record fuel advance returns.", status_code=403)
    movement_object_id = _object_id(movement_id, "movement_id")
    actor = _object_id(actor_id, "actor_id")
    key = str(idempotency_key or "").strip()
    if not key:
        raise ApiError("Idempotency-Key is required.", status_code=400)
    movement = get_collection("vehicle_movements").find_one({"_id": movement_object_id})
    if not movement or movement.get("movement_type") != "fuel_purchase":
        raise ApiError("Fuel Purchase movement not found.", status_code=404)
    advance = movement.get("fuel_advance") or {}
    if any(item.get("idempotency_key") == key for item in advance.get("returns") or []):
        return movement
    if advance.get("status") not in {"issued", "return_outstanding"}:
        raise ApiError("This fuel advance has no returnable balance.", status_code=400)
    amount = _positive_amount(payload.get("amount"), "amount")
    outstanding = round(float(advance.get("outstanding_amount") or 0), 2)
    if amount > outstanding:
        raise ApiError("Returned amount cannot exceed the outstanding advance.", status_code=400)
    if not advance.get("fuel_log_id") and amount != outstanding:
        raise ApiError("Before a purchase is recorded, the full unused advance must be returned.", status_code=400)
    destination_id = payload.get("finance_account_id") or advance.get("finance_account_id")
    destination = get_finance_account_document(destination_id)
    if destination.get("status") != "active":
        raise ApiError("Return destination account is inactive.", status_code=400)
    timestamp = now_utc()
    next_outstanding = round(outstanding - amount, 2)
    returned_total = round(float(advance.get("returned_amount") or 0) + amount, 2)
    return_event = {
        "idempotency_key": key, "amount": amount, "finance_account_id": destination["_id"],
        "reference_number": str(payload.get("reference_number") or "").strip() or None,
        "recorded_by": actor, "recorded_at": timestamp,
    }
    next_status = "settled" if next_outstanding == 0 else "return_outstanding"
    updates = {
        "fuel_advance.returned_amount": returned_total,
        "fuel_advance.outstanding_amount": next_outstanding,
        "fuel_advance.status": next_status,
        "updated_at": timestamp,
    }
    if next_outstanding == 0:
        updates.update({"fuel_advance.settled_by": actor, "fuel_advance.settled_at": timestamp})

    def post(session):
        kwargs = {"session": session} if session else {}
        post_ledger_entry(
            destination["_id"], amount, "credit",
            entry_key=f"fuel_advance_return:{movement_object_id}:{key}",
            source_type="fuel_advance_return", source_id=movement_object_id,
            actor_id=actor, effective_date=timestamp.date().isoformat(),
            description=f"Fuel advance return for {movement.get('movement_id')}", session=session,
        )
        result = get_collection("vehicle_movements").update_one(
            {"_id": movement_object_id, "fuel_advance.outstanding_amount": outstanding,
             "fuel_advance.returns.idempotency_key": {"$ne": key}},
            {"$set": updates, "$push": {
                "fuel_advance.returns": return_event,
                "audit_log": {"event": "fuel_advance_returned", "timestamp": timestamp,
                              "actor_id": actor, "actor_role": actor_role, "amount": amount,
                              "finance_account_id": str(destination["_id"]), "immutable": True},
            }}, **kwargs,
        )
        if result.modified_count != 1:
            raise ApiError("Fuel advance balance changed while the return was posted.", status_code=409)

    run_finance_transaction(post)
    return get_collection("vehicle_movements").find_one({"_id": movement_object_id})


def assert_fuel_advance_can_finish(movement: dict):
    if movement.get("movement_type") != "fuel_purchase":
        return
    advance = movement.get("fuel_advance") or {}
    if round(float(advance.get("outstanding_amount") or 0), 2) != 0:
        raise ApiError("Settle or return the outstanding fuel advance before closing this movement.", status_code=409)
