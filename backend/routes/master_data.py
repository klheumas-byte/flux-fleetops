from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.master_data_service import (
    create_master_data_item,
    list_master_data,
    update_master_data_item,
)
from utils.decorators import role_required
from utils.responses import success_response


master_data_bp = Blueprint("master_data", __name__)


@master_data_bp.get("")
@role_required("owner", "admin", "driver")
def get_master_data_route():
    active_only = request.args.get("active_only", "").strip().lower() == "true"
    return success_response(
        data=list_master_data(
            current_role=get_jwt().get("role"),
            active_only=active_only,
        )
    )


@master_data_bp.post("")
@role_required("owner", "admin")
def create_master_data_route():
    item = create_master_data_item(
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"item": item},
        message="Master data item created successfully.",
        status_code=201,
    )


@master_data_bp.patch("/<item_id>")
@role_required("owner", "admin")
def update_master_data_route(item_id: str):
    item = update_master_data_item(
        item_id,
        request.get_json(silent=True) or {},
        current_user_id=get_jwt_identity(),
        current_role=get_jwt().get("role"),
    )
    return success_response(
        data={"item": item},
        message="Master data item updated successfully.",
    )
