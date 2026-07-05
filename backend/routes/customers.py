from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from services.customer_service import (
    create_customer,
    create_customer_contact,
    create_customer_note,
    create_customer_opportunity,
    get_customer_by_id,
    list_customer_contacts,
    list_customer_notes,
    list_customer_opportunities,
    get_customer_summary,
    list_customer_options,
    list_customers,
    update_customer_contact,
    update_customer_opportunity,
    update_customer_relationship,
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


def _options_filters() -> dict:
    raw_limit = request.args.get("limit", type=int)
    return {
        "q": request.args.get("q"),
        "limit": raw_limit if raw_limit is not None else 50,
        "include_customers": request.args.get("include_customers", "").strip().lower() in {"1", "true", "yes"},
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
    filters = _options_filters()
    return success_response(
        data=list_customer_options(
            get_jwt_identity(),
            get_jwt().get("role"),
            search_query=filters["q"],
            limit=filters["limit"],
            include_customers=filters["include_customers"],
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


@customers_bp.patch("/<customer_id>/relationship")
@role_required("owner", "admin", "driver")
def update_customer_relationship_route(customer_id: str):
    customer = update_customer_relationship(
        customer_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"customer": customer},
        message="Customer relationship details updated successfully.",
    )


@customers_bp.get("/<customer_id>/opportunities")
@role_required("owner", "admin", "driver")
def get_customer_opportunities_route(customer_id: str):
    return success_response(
        data={
            "opportunities": list_customer_opportunities(
                customer_id,
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@customers_bp.post("/<customer_id>/opportunities")
@role_required("owner", "admin", "driver")
def create_customer_opportunity_route(customer_id: str):
    opportunity = create_customer_opportunity(
        customer_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"opportunity": opportunity},
        message="Customer opportunity created successfully.",
        status_code=201,
    )


@customers_bp.patch("/<customer_id>/opportunities/<opportunity_id>")
@role_required("owner", "admin", "driver")
def update_customer_opportunity_route(customer_id: str, opportunity_id: str):
    opportunity = update_customer_opportunity(
        customer_id,
        opportunity_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"opportunity": opportunity},
        message="Customer opportunity updated successfully.",
    )


@customers_bp.get("/<customer_id>/contacts")
@role_required("owner", "admin", "driver")
def get_customer_contacts_route(customer_id: str):
    return success_response(
        data={
            "contacts": list_customer_contacts(
                customer_id,
                get_jwt_identity(),
                get_jwt().get("role"),
            )
        }
    )


@customers_bp.post("/<customer_id>/contacts")
@role_required("owner", "admin", "driver")
def create_customer_contact_route(customer_id: str):
    contact = create_customer_contact(
        customer_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"contact": contact},
        message="Customer contact created successfully.",
        status_code=201,
    )


@customers_bp.patch("/<customer_id>/contacts/<contact_id>")
@role_required("owner", "admin", "driver")
def update_customer_contact_route(customer_id: str, contact_id: str):
    contact = update_customer_contact(
        customer_id,
        contact_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"contact": contact},
        message="Customer contact updated successfully.",
    )


@customers_bp.get("/<customer_id>/notes")
@role_required("owner", "admin", "driver")
def get_customer_notes_route(customer_id: str):
    return success_response(
        data=list_customer_notes(
            customer_id,
            get_jwt_identity(),
            get_jwt().get("role"),
        )
    )


@customers_bp.post("/<customer_id>/notes")
@role_required("owner", "admin", "driver")
def create_customer_note_route(customer_id: str):
    note = create_customer_note(
        customer_id,
        request.get_json(silent=True) or {},
        get_jwt_identity(),
        get_jwt().get("role"),
    )
    return success_response(
        data={"note": note},
        message="Customer note added successfully.",
        status_code=201,
    )
