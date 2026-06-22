from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.customer_service import (
    create_customer,
    get_customer_by_id,
    get_customer_summary,
    list_customer_options,
    list_customers,
    update_customer,
)
from utils.decorators import role_required
from utils.responses import success_response


customers_bp = Blueprint("customers", __name__)


def _summary_filters() -> dict:
    return {
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "creator_role": request.args.get("creator_role"),
        "driver_id": request.args.get("driver_id"),
        "customer_category_id": request.args.get("customer_category_id"),
        "source": request.args.get("source"),
    }


@customers_bp.get("")
@role_required("owner", "admin", "driver")
def get_customers_route():
    return success_response(
        data={
            "customers": list_customers(
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@customers_bp.get("/options")
@role_required("owner", "admin", "driver")
def get_customer_options_route():
    return success_response(
        data=list_customer_options(
            get_jwt_identity(),
            get_jwt().get("role"),
        )
    )


@customers_bp.get("/summary")
@role_required("owner", "admin", "driver")
def get_customer_summary_route():
    return success_response(
        data={
            "summary": get_customer_summary(
                get_jwt_identity(),
                get_jwt().get("role"),
                _summary_filters(),
            )
        }
    )


@customers_bp.post("")
@role_required("owner", "admin", "driver")
def create_customer_route():
    customer = create_customer(
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"customer": customer},
        message="Customer created successfully.",
        status_code=201,
    )


@customers_bp.get("/<customer_id>")
@role_required("owner", "admin", "driver")
def get_customer_route(customer_id: str):
    return success_response(
        data={
            "customer": get_customer_by_id(
                customer_id,
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@customers_bp.patch("/<customer_id>")
@role_required("owner", "admin", "driver")
def update_customer_route(customer_id: str):
    customer = update_customer(
        customer_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"customer": customer},
        message="Customer updated successfully.",
    )
