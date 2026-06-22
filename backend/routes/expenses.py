from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.expense_service import (
    approve_expense,
    create_expense,
    get_expense_by_id,
    list_expenses,
    mark_expense_paid,
    reject_expense,
)
from utils.decorators import role_required
from utils.responses import success_response


expenses_bp = Blueprint("expenses", __name__)


@expenses_bp.get("")
@role_required("owner", "admin", "driver")
def get_expenses():
    return success_response(
        data={
            "expenses": list_expenses(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )


@expenses_bp.post("")
@role_required("owner", "admin", "driver")
def create_expense_route():
    expense = create_expense(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"expense": expense},
        message="Expense submitted successfully.",
        status_code=201,
    )


@expenses_bp.get("/<expense_id>")
@role_required("owner", "admin", "driver")
def get_expense_route(expense_id: str):
    expense = get_expense_by_id(
        expense_id=expense_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"expense": expense})


@expenses_bp.patch("/<expense_id>/approve")
@role_required("owner")
def approve_expense_route(expense_id: str):
    expense = approve_expense(
        expense_id=expense_id,
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"expense": expense},
        message="Expense approved successfully.",
    )


@expenses_bp.patch("/<expense_id>/reject")
@role_required("owner")
def reject_expense_route(expense_id: str):
    payload = request.get_json(silent=True) or {}
    expense = reject_expense(
        expense_id=expense_id,
        current_user_id=get_jwt_identity(),
        rejection_reason=payload.get("rejection_reason"),
    )
    return success_response(
        data={"expense": expense},
        message="Expense rejected successfully.",
    )


@expenses_bp.patch("/<expense_id>/mark-paid")
@role_required("owner")
def mark_expense_paid_route(expense_id: str):
    expense = mark_expense_paid(
        expense_id=expense_id,
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"expense": expense},
        message="Expense marked as paid successfully.",
    )
