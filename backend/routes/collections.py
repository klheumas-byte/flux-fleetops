from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from services.collection_service import (
    create_collection,
    get_collection_by_id,
    list_driver_weekly_statuses,
    list_collection_options,
    list_collections,
    list_pending_payment_submissions,
    update_collection_status,
)
from utils.decorators import role_required
from utils.responses import success_response


collections_bp = Blueprint("collections", __name__)


@collections_bp.get("")
@role_required("owner", "admin")
def get_collections():
    data = list_collections(
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=25, type=int),
        status=request.args.get("status"),
        driver_id=request.args.get("driver_id"),
        payment_method=request.args.get("payment_method"),
        collection_date=request.args.get("collection_date"),
        search=request.args.get("search"),
    )
    return success_response(data=data)


@collections_bp.get("/pending")
@role_required("owner", "admin")
def get_pending_collections():
    return success_response(data={"collections": list_pending_payment_submissions()})


@collections_bp.get("/pending-submissions")
@role_required("owner", "admin")
def get_pending_payment_submissions_route():
    submissions = list_pending_payment_submissions()
    return success_response(
        data={
            "pending_submissions": submissions,
            "collections": submissions,
        }
    )


@collections_bp.get("/weekly-status")
@role_required("owner", "admin")
def get_weekly_payment_status():
    return success_response(data={"cycles": list_driver_weekly_statuses()})


@collections_bp.get("/options")
@role_required("owner", "admin")
def get_collection_options():
    return success_response(data=list_collection_options())


@collections_bp.post("")
@role_required("owner", "admin")
def create_collection_route():
    payload = request.get_json(silent=True) or {}
    collection = create_collection(payload, get_jwt_identity())
    return success_response(
        data={"collection": collection},
        message="Collection recorded successfully.",
        status_code=201,
    )


@collections_bp.get("/<collection_id>")
@role_required("owner", "admin")
def get_collection_route(collection_id: str):
    return success_response(data={"collection": get_collection_by_id(collection_id)})


@collections_bp.patch("/<collection_id>/status")
@role_required("owner", "admin")
def update_collection_status_route(collection_id: str):
    payload = request.get_json(silent=True) or {}
    collection = update_collection_status(
        collection_id=collection_id,
        status=payload.get("status"),
        current_user_id=get_jwt_identity(),
        rejection_reason=payload.get("rejection_reason"),
        admin_received_amount=payload.get("admin_received_amount"),
        admin_approval_note=payload.get("admin_approval_note"),
    )
    return success_response(
        data={"collection": collection},
        message="Collection status updated successfully.",
    )


@collections_bp.patch("/pending-submissions/<collection_id>/confirm")
@role_required("owner", "admin")
def confirm_pending_submission_route(collection_id: str):
    payload = request.get_json(silent=True) or {}
    collection = update_collection_status(
        collection_id=collection_id,
        status="approved",
        current_user_id=get_jwt_identity(),
        admin_received_amount=payload.get("admin_received_amount"),
        admin_approval_note=payload.get("admin_approval_note"),
    )
    return success_response(
        data={"collection": collection},
        message="Payment submission confirmed successfully.",
    )


@collections_bp.patch("/pending-submissions/<collection_id>/reject")
@role_required("owner", "admin")
def reject_pending_submission_route(collection_id: str):
    payload = request.get_json(silent=True) or {}
    collection = update_collection_status(
        collection_id=collection_id,
        status="rejected",
        current_user_id=get_jwt_identity(),
        rejection_reason=payload.get("rejection_reason"),
    )
    return success_response(
        data={"collection": collection},
        message="Payment submission rejected successfully.",
    )
