from bson import ObjectId

from models.dispatch_job import serialize_dispatch_job
from models.incident import serialize_incident
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from models.vehicle_movement import serialize_vehicle_movement
from utils.dispatch_payment_classification import resolve_dispatch_financial_type


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _serialize_datetime(value):
    if value is None:
        return None
    return value.isoformat()


def serialize_dispatch_financial_expense(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "dispatch_financial_id": _serialize_reference_id(document.get("dispatch_financial_id")),
        "dispatch_job_id": _serialize_reference_id(document.get("dispatch_job_id")),
        "vehicle_movement_id": _serialize_reference_id(document.get("vehicle_movement_id")),
        "vehicle_id": _serialize_reference_id(document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(document.get("driver_id")),
        "expense_type": document.get("expense_type"),
        "amount": document.get("amount"),
        "note": document.get("note"),
        "receipt_reference": document.get("receipt_reference"),
        "status": document.get("status"),
        "rejection_reason": document.get("rejection_reason"),
        "submitted_by": _serialize_reference_id(document.get("submitted_by")),
        "submitted_at": _serialize_datetime(document.get("submitted_at")),
        "reviewed_by": _serialize_reference_id(document.get("reviewed_by")),
        "reviewed_at": _serialize_datetime(document.get("reviewed_at")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
    }


def serialize_dispatch_financial_incident(document: dict) -> dict:
    return {
        "id": str(document.get("_id")),
        "dispatch_financial_id": _serialize_reference_id(document.get("dispatch_financial_id")),
        "dispatch_job_id": _serialize_reference_id(document.get("dispatch_job_id")),
        "vehicle_movement_id": _serialize_reference_id(document.get("vehicle_movement_id")),
        "vehicle_id": _serialize_reference_id(document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(document.get("driver_id")),
        "linked_incident_id": _serialize_reference_id(document.get("linked_incident_id")),
        "incident_type": document.get("incident_type"),
        "incident_date": document.get("incident_date"),
        "incident_location": document.get("incident_location"),
        "amount": document.get("amount"),
        "responsibility_type": document.get("responsibility_type"),
        "company_share": document.get("company_share"),
        "driver_share": document.get("driver_share"),
        "final_responsible_party": document.get("final_responsible_party"),
        "description": document.get("description"),
        "evidence_reference": document.get("evidence_reference"),
        "admin_notes": document.get("admin_notes"),
        "status": document.get("status"),
        "rejection_reason": document.get("rejection_reason"),
        "submitted_by": _serialize_reference_id(document.get("submitted_by")),
        "submitted_at": _serialize_datetime(document.get("submitted_at")),
        "reviewed_by": _serialize_reference_id(document.get("reviewed_by")),
        "reviewed_at": _serialize_datetime(document.get("reviewed_at")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
    }


def serialize_dispatch_financial_record(document: dict) -> dict:
    financial_type, is_legacy = resolve_dispatch_financial_type(document)
    return {
        "id": str(document.get("_id")),
        "dispatch_financial_id": str(document.get("_id")) if document.get("_id") else None,
        "dispatch_job_id": _serialize_reference_id(document.get("dispatch_job_id")),
        "dispatch_request_id": _serialize_reference_id(document.get("dispatch_request_id")),
        "vehicle_movement_id": _serialize_reference_id(document.get("vehicle_movement_id")),
        "vehicle_id": _serialize_reference_id(document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(document.get("driver_id")),
        "approved_charge": document.get("approved_charge"),
        "amount_paid": document.get("amount_paid", 0),
        "dispatch_financial_type": financial_type,
        "dispatch_financial_type_is_legacy": bool(document.get("dispatch_financial_type_is_legacy", is_legacy)),
        "partner_organization_reference": document.get("partner_organization_reference"),
        "partner_billing_method": document.get("partner_billing_method"),
        "driver_compensation_type": document.get("driver_compensation_type") or "none",
        "driver_compensation_value": document.get("driver_compensation_value", 0),
        "driver_compensation_amount": document.get("driver_compensation_amount", 0),
        "driver_compensation_approved_by": _serialize_reference_id(document.get("driver_compensation_approved_by")),
        "driver_compensation_approved_at": _serialize_datetime(document.get("driver_compensation_approved_at")),
        "amount_collected_from_customer": document.get("amount_collected_from_customer"),
        "amount_submitted_by_driver": document.get("amount_submitted_by_driver"),
        "outstanding_balance": document.get("outstanding_balance"),
        "expected_fuel_cost": document.get("expected_fuel_cost"),
        "actual_fuel_cost": document.get("actual_fuel_cost"),
        "estimated_other_costs": document.get("estimated_other_costs"),
        "approved_expenses": document.get("approved_expenses"),
        "company_incident_costs": document.get("company_incident_costs"),
        "driver_liability_total": document.get("driver_liability_total"),
        "company_operational_cost": document.get("company_operational_cost"),
        "expected_net_revenue": document.get("expected_net_revenue"),
        "actual_net_revenue": document.get("actual_net_revenue"),
        "finance_notes": document.get("finance_notes"),
        "payment_method": document.get("payment_method"),
        "payment_reference": document.get("payment_reference"),
        "submitted_by": _serialize_reference_id(document.get("submitted_by")),
        "submitted_at": _serialize_datetime(document.get("submitted_at")),
        "verified_by": _serialize_reference_id(document.get("verified_by")),
        "verified_at": _serialize_datetime(document.get("verified_at")),
        "financial_status": document.get("financial_status"),
        "is_financially_closed": bool(document.get("is_financially_closed")),
        "financial_closed_at": _serialize_datetime(document.get("financial_closed_at")),
        "financial_closed_by": _serialize_reference_id(document.get("financial_closed_by")),
        "created_at": _serialize_datetime(document.get("created_at")),
        "updated_at": _serialize_datetime(document.get("updated_at")),
        "last_submission": document.get("last_submission") or {},
    }


def serialize_dispatch_financial_detail(
    document: dict,
    *,
    job_document: dict | None = None,
    movement_document: dict | None = None,
    vehicle_document: dict | None = None,
    driver_document: dict | None = None,
    linked_incident_documents: dict | None = None,
    expenses: list[dict] | None = None,
    incidents: list[dict] | None = None,
) -> dict:
    linked_incident_lookup = linked_incident_documents or {}
    serialized_expenses = [serialize_dispatch_financial_expense(item) for item in (expenses or [])]
    serialized_incidents = []
    for item in incidents or []:
        payload = serialize_dispatch_financial_incident(item)
        linked_document = linked_incident_lookup.get(item.get("linked_incident_id"))
        payload["linked_incident"] = serialize_incident(linked_document) if linked_document else None
        serialized_incidents.append(payload)
    return {
        "record": serialize_dispatch_financial_record(document),
        "job": serialize_dispatch_job(job_document) if job_document else None,
        "movement": serialize_vehicle_movement(movement_document) if movement_document else None,
        "vehicle": serialize_vehicle(vehicle_document, include_sensitive=False) if vehicle_document else None,
        "driver": serialize_user(driver_document) if driver_document else None,
        "expenses": serialized_expenses,
        "incidents": serialized_incidents,
    }
