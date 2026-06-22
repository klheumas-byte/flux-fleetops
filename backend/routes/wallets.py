from flask import Blueprint
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.wallet_service import (
    get_driver_wallet_summary,
    list_driver_wallet_ledger,
    list_wallet_driver_options,
)
from utils.decorators import role_required
from utils.responses import success_response


wallets_bp = Blueprint("wallets", __name__)


@wallets_bp.get("/drivers/options")
@role_required("owner", "admin")
def get_wallet_driver_options():
    return success_response(data={"drivers": list_wallet_driver_options()})


@wallets_bp.get("/drivers/<driver_id>")
@role_required("owner", "admin", "driver")
def get_driver_wallet(driver_id: str):
    data = get_driver_wallet_summary(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        driver_id=driver_id,
    )
    return success_response(data=data)


@wallets_bp.get("/drivers/<driver_id>/ledger")
@role_required("owner", "admin", "driver")
def get_driver_wallet_ledger(driver_id: str):
    data = list_driver_wallet_ledger(
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
        driver_id=driver_id,
    )
    return success_response(data=data)
