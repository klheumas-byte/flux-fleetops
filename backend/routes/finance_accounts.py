from flask import Blueprint, request
from flask_jwt_extended import get_jwt

from services.finance_account_service import (
    create_finance_account,
    get_finance_account_by_id,
    get_finance_accounts_summary,
    list_finance_accounts,
    update_finance_account,
    update_finance_account_status,
)
from utils.decorators import role_required
from utils.responses import success_response


finance_accounts_bp = Blueprint("finance_accounts", __name__)


@finance_accounts_bp.get("/accounts")
@role_required("owner", "admin")
def get_finance_accounts():
    return success_response(
        data={"accounts": list_finance_accounts(get_jwt().get("role"))}
    )


@finance_accounts_bp.post("/accounts")
@role_required("owner")
def create_finance_account_route():
    from flask_jwt_extended import get_jwt_identity

    account = create_finance_account(
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"account": account},
        message="Finance account created successfully.",
        status_code=201,
    )


@finance_accounts_bp.get("/accounts/<account_id>")
@role_required("owner", "admin")
def get_finance_account_route(account_id: str):
    account = get_finance_account_by_id(account_id, get_jwt().get("role"))
    return success_response(data={"account": account})


@finance_accounts_bp.patch("/accounts/<account_id>")
@role_required("owner")
def update_finance_account_route(account_id: str):
    from flask_jwt_extended import get_jwt_identity

    account = update_finance_account(
        account_id=account_id,
        payload=request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"account": account},
        message="Finance account updated successfully.",
    )


@finance_accounts_bp.patch("/accounts/<account_id>/status")
@role_required("owner")
def update_finance_account_status_route(account_id: str):
    from flask_jwt_extended import get_jwt_identity

    account = update_finance_account_status(
        account_id=account_id,
        status=(request.get_json(silent=True) or {}).get("status"),
        current_user_id=get_jwt_identity(),
    )
    return success_response(
        data={"account": account},
        message="Finance account status updated successfully.",
    )


@finance_accounts_bp.get("/summary")
@role_required("owner", "admin")
def get_finance_accounts_summary_route():
    return success_response(data={"summary": get_finance_accounts_summary(get_jwt().get("role"))})
