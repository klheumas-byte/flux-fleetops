from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.deposit_service import (
    create_deposit,
    get_deposit_by_id,
    list_deposits,
    reject_deposit,
    verify_deposit,
)
from utils.decorators import role_required
from utils.responses import success_response


deposits_bp = Blueprint("deposits", __name__)


@deposits_bp.get("")
@role_required("owner", "admin")
def get_deposits():
    data = list_deposits(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=25, type=int),
        status=request.args.get("status"),
    )
    return success_response(
        data=data
    )


@deposits_bp.post("")
@role_required("owner", "admin")
def create_deposit_route():
    deposit = create_deposit(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"deposit": deposit},
        message="Deposit submitted successfully.",
        status_code=201,
    )


@deposits_bp.get("/<deposit_id>")
@role_required("owner", "admin")
def get_deposit_route(deposit_id: str):
    deposit = get_deposit_by_id(
        deposit_id=deposit_id,
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(data={"deposit": deposit})


@deposits_bp.patch("/<deposit_id>/verify")
@role_required("owner")
def verify_deposit_route(deposit_id: str):
    payload = request.get_json(silent=True) or {}
    deposit = verify_deposit(
        deposit_id=deposit_id,
        current_user_id=get_jwt_identity(),
        finance_account_id=payload.get("finance_account_id"),
    )
    return success_response(
        data={"deposit": deposit},
        message="Deposit verified successfully.",
    )


@deposits_bp.patch("/<deposit_id>/reject")
@role_required("owner")
def reject_deposit_route(deposit_id: str):
    payload = request.get_json(silent=True) or {}
    deposit = reject_deposit(
        deposit_id=deposit_id,
        current_user_id=get_jwt_identity(),
        rejection_reason=payload.get("rejection_reason"),
    )
    return success_response(
        data={"deposit": deposit},
        message="Deposit rejected successfully.",
    )
