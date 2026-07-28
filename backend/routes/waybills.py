from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.waybill_service import (
    ensure_waybill_from_registered_source,
    get_waybill,
    list_waybills,
    record_waybill_custody,
    replace_waybill_items,
    review_waybill_variance,
    save_waybill_signature,
    search_waybill_products,
    transition_waybill,
)
from utils.decorators import role_required
from utils.responses import success_response


waybills_bp = Blueprint("waybills", __name__)


def _identity():
    return get_jwt_identity(), get_jwt().get("role")


@waybills_bp.get("")
@role_required("owner", "admin", "driver")
def list_route():
    user_id, role = _identity()
    return success_response(
        data=list_waybills(
            current_user_id=user_id,
            current_role=role,
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", 25, type=int),
            status=request.args.get("status"),
            source_type=request.args.get("source_type"),
        )
    )


@waybills_bp.get("/products")
@role_required("owner", "admin", "driver")
def product_search_route():
    _user_id, role = _identity()
    return success_response(data=search_waybill_products(request.args.get("q", ""), current_role=role))


@waybills_bp.post("/sources/<source_type>/<source_id>")
@role_required("owner", "admin")
def ensure_source_route(source_type, source_id):
    user_id, role = _identity()
    waybill = ensure_waybill_from_registered_source(
        source_type,
        source_id,
        current_user_id=user_id,
        current_role=role,
    )
    return success_response(data={"waybill": waybill}, message="Digital Waybill is ready.", status_code=201)


@waybills_bp.get("/<waybill_id>")
@role_required("owner", "admin", "driver")
def detail_route(waybill_id):
    user_id, role = _identity()
    return success_response(data={"waybill": get_waybill(waybill_id, current_user_id=user_id, current_role=role)})


@waybills_bp.put("/<waybill_id>/items")
@role_required("owner", "admin")
def items_route(waybill_id):
    user_id, role = _identity()
    waybill = replace_waybill_items(waybill_id, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)
    return success_response(data={"waybill": waybill}, message="Digital Waybill items updated.")


@waybills_bp.patch("/<waybill_id>/transition/<target_status>")
@role_required("owner", "admin", "driver")
def transition_route(waybill_id, target_status):
    user_id, role = _identity()
    waybill = transition_waybill(waybill_id, target_status, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role, enforce_source_owner=True)
    return success_response(data={"waybill": waybill}, message="Digital Waybill updated.")


@waybills_bp.post("/<waybill_id>/confirm")
@role_required("driver")
def confirm_route(waybill_id):
    user_id, role = _identity()
    waybill = transition_waybill(waybill_id, "driver_confirmed", request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role, enforce_source_owner=True)
    return success_response(data={"waybill": waybill}, message="Digital Waybill confirmed.")


@waybills_bp.post("/<waybill_id>/custody")
@role_required("owner", "admin", "driver")
def custody_route(waybill_id):
    user_id, role = _identity()
    waybill = record_waybill_custody(waybill_id, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)
    return success_response(data={"waybill": waybill}, message="Custody handover recorded.", status_code=201)


@waybills_bp.patch("/<waybill_id>/variance-review")
@role_required("owner", "admin")
def variance_route(waybill_id):
    user_id, role = _identity()
    waybill = review_waybill_variance(waybill_id, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role, enforce_source_owner=True)
    return success_response(data={"waybill": waybill}, message="Waybill variance reviewed.")


@waybills_bp.post("/<waybill_id>/signatures/<party>")
@role_required("owner", "admin", "driver")
def signature_route(waybill_id, party):
    user_id, role = _identity()
    waybill = save_waybill_signature(waybill_id, party, request.get_json(silent=True) or {}, current_user_id=user_id, current_role=role)
    return success_response(data={"waybill": waybill}, message="Optional signature recorded.", status_code=201)
