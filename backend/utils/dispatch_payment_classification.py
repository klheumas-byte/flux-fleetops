from __future__ import annotations

from utils.api_error import ApiError


DISPATCH_FINANCIAL_TYPES = {
    "external_paid",
    "internal_company",
    "partner_contract",
    "complimentary",
    "cost_contribution",
}
PARTNER_BILLING_METHODS = {
    "no_individual_payment",
    "billed_later",
    "monthly_contract",
    "prepaid_contract",
    "manual_settlement",
}
DRIVER_COMPENSATION_TYPES = {
    "none",
    "fixed_tip",
    "fixed_allowance",
    "percentage_of_charge",
    "manual_amount",
}
NON_IMMEDIATE_PARTNER_BILLING_METHODS = {
    "no_individual_payment",
    "billed_later",
    "monthly_contract",
    "prepaid_contract",
}


def normalize_key(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("/", "_").replace(" ", "_")
    return normalized or None


def resolve_dispatch_financial_type(document: dict | None) -> tuple[str, bool]:
    document = document or {}
    explicit = normalize_key(document.get("dispatch_financial_type"))
    if explicit in DISPATCH_FINANCIAL_TYPES:
        return explicit, False
    # Legacy dispatches were created by a customer-payment-only workflow. A
    # positive charge/payment confirms that classification; zero-charge legacy
    # rows remain external rather than being guessed into an internal category.
    return "external_paid", True


def requires_immediate_customer_payment(financial_type: str, billing_method: str | None = None) -> bool:
    if financial_type == "external_paid":
        return True
    if financial_type == "partner_contract":
        return normalize_key(billing_method) == "manual_settlement"
    return False


def recognizes_individual_customer_revenue(financial_type: str, billing_method: str | None = None) -> bool:
    if financial_type == "external_paid":
        return True
    if financial_type == "partner_contract":
        return normalize_key(billing_method) in {"manual_settlement", "billed_later"}
    return False


def calculate_driver_compensation(compensation_type, compensation_value, customer_charge) -> float:
    normalized_type = normalize_key(compensation_type) or "none"
    if normalized_type not in DRIVER_COMPENSATION_TYPES:
        raise ApiError("Invalid driver_compensation_type.", status_code=400)
    try:
        value = float(compensation_value or 0)
        charge = float(customer_charge or 0)
    except (TypeError, ValueError) as error:
        raise ApiError("driver_compensation_value must be numeric.", status_code=400) from error
    if value < 0:
        raise ApiError("driver_compensation_value cannot be negative.", status_code=400)
    if normalized_type == "none":
        return 0.0
    if normalized_type == "percentage_of_charge":
        if charge <= 0:
            raise ApiError(
                "percentage_of_charge requires a customer charge greater than zero.",
                status_code=400,
            )
        if value > 100:
            raise ApiError("driver_compensation_value cannot exceed 100 percent.", status_code=400)
        return round(charge * value / 100, 2)
    return round(value, 2)


def payment_status_is_recorded(payment_status) -> bool:
    normalized = normalize_key(payment_status) or ""
    return normalized not in {"", "unpaid", "not_required", "not_applicable", "pending"}
