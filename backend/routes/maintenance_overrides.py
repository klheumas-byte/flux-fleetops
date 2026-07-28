from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.maintenance_override_service import (
    acknowledge_override, create_override, list_overrides, override_history, transition_override,
)
from utils.decorators import role_required
from utils.responses import success_response


maintenance_overrides_bp = Blueprint("maintenance_overrides", __name__)


@maintenance_overrides_bp.get("")
@role_required("owner", "admin", "fleet_owner", "driver")
def get_overrides():
    return success_response(data=list_overrides(
        get_jwt_identity(), get_jwt().get("role"), vehicle_id=request.args.get("vehicle_id"),
        status=request.args.get("status"), page=request.args.get("page", 1, type=int), page_size=request.args.get("page_size", 50, type=int),
    ))


@maintenance_overrides_bp.post("")
@role_required("owner", "admin")
def post_override():
    return success_response(data={"override": create_override(request.get_json(silent=True) or {}, get_jwt_identity(), get_jwt().get("role"))}, message="Vehicle declared available with restriction.", status_code=201)


@maintenance_overrides_bp.patch("/<override_id>/revoke")
@role_required("owner", "admin")
def revoke_override(override_id):
    payload = request.get_json(silent=True) or {}
    return success_response(data={"override": transition_override(override_id, "revoked", get_jwt_identity(), get_jwt().get("role"), payload.get("notes"))})


@maintenance_overrides_bp.patch("/<override_id>/resolve")
@role_required("owner", "admin")
def resolve_override(override_id):
    payload = request.get_json(silent=True) or {}
    return success_response(data={"override": transition_override(override_id, "resolved", get_jwt_identity(), get_jwt().get("role"), payload.get("notes"))})


@maintenance_overrides_bp.patch("/<override_id>/acknowledge")
@role_required("driver")
def acknowledge_override_route(override_id):
    return success_response(data={"override": acknowledge_override(override_id, get_jwt_identity())}, message="Restriction acknowledged.")


@maintenance_overrides_bp.get("/<override_id>/history")
@role_required("owner", "admin", "fleet_owner", "driver")
def get_override_history(override_id):
    return success_response(data={"history": override_history(override_id, get_jwt_identity(), get_jwt().get("role"))})
