from flask import Blueprint

from flask_jwt_extended import get_jwt, get_jwt_identity

from services.accountability_service import list_admin_accountability
from services.deposit_service import list_holding_balances
from utils.decorators import role_required
from utils.responses import success_response


admins_bp = Blueprint("admins", __name__)


@admins_bp.get("/accountability")
@role_required("owner", "admin")
def get_admin_accountability():
    return success_response(data={"admins": list_admin_accountability()})


@admins_bp.get("/holding-balances")
@role_required("owner", "admin")
def get_admin_holding_balances():
    return success_response(
        data={
            "admins": list_holding_balances(
                current_user_id=get_jwt_identity(),
                current_role=get_jwt().get("role"),
            )
        }
    )
