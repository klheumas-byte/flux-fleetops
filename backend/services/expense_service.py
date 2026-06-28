from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.expense import serialize_expense
from models.finance_account import serialize_finance_account_snapshot
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.assignment_service import get_active_assignment_for_driver
from services.finance_account_service import (
    decrement_finance_account_balance,
    get_finance_account_document,
)
from utils.api_error import ApiError
from utils.file_validation import validate_file_reference
from utils.mongo_indexes import ensure_indexes_for_collection


ALLOWED_EXPENSE_CATEGORIES = {
    "fuel",
    "repairs",
    "servicing",
    "insurance",
    "roadworthy",
    "tyres",
    "battery",
    "car_wash",
    "driver_advance",
    "office",
    "other",
}
ALLOWED_EXPENSE_STATUSES = {"pending", "approved", "rejected", "paid"}
ALLOWED_PAYMENT_METHODS = {"cash", "momo_transfer", "bank_transfer", "card", "other"}


def now_utc():
    return datetime.now(timezone.utc)


def expenses_collection():
    return get_collection("expenses")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def finance_accounts_collection():
    return get_collection("finance_accounts")


def ensure_expense_indexes():
    ensure_indexes_for_collection(
        expenses_collection(),
        [
            {"keys": [("status", ASCENDING)]},
            {"keys": [("expense_category", ASCENDING)]},
            {"keys": [("expense_date", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("finance_account_id", ASCENDING)]},
            {"keys": [("requested_by", ASCENDING)]},
            {"keys": [("approved_by", ASCENDING)]},
            {"keys": [("paid_by", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING), ("expense_date", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("status", ASCENDING), ("expense_date", DESCENDING)]},
        ],
        collection_name="expenses",
    )


def _to_object_id(value, field_name: str, required: bool = True):
    if value is None or value == "":
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _validate_positive_amount(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value <= 0:
        raise ApiError(f"{field_name} must be a positive number.", status_code=400)
    return round(float(value), 2)


def _get_user_document(user_id: str | ObjectId, expected_roles: set[str] | None = None):
    user_object_id = _to_object_id(user_id, "user_id")
    query = {"_id": user_object_id}
    if expected_roles:
        query["role"] = {"$in": list(expected_roles)}
    user = users_collection().find_one(query)
    if not user:
        raise ApiError("User not found.", status_code=404)
    return user


def _get_vehicle_document(vehicle_id: str | ObjectId):
    vehicle_object_id = _to_object_id(vehicle_id, "vehicle_id")
    vehicle = vehicles_collection().find_one({"_id": vehicle_object_id})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _validate_payment_method(payment_method: str | None):
    normalized = (payment_method or "").strip().lower()
    if normalized not in ALLOWED_PAYMENT_METHODS:
        raise ApiError(
            "payment_method must be one of: cash, momo_transfer, bank_transfer, card, other.",
            status_code=400,
        )
    return normalized


def _validate_expense_category(category: str | None):
    normalized = (category or "").strip().lower()
    if normalized not in ALLOWED_EXPENSE_CATEGORIES:
        raise ApiError(
            "expense_category must be one of: fuel, repairs, servicing, insurance, roadworthy, tyres, battery, car_wash, driver_advance, office, other.",
            status_code=400,
        )
    return normalized


def _validate_driver_submission(
    current_user_id: str,
    driver_object_id: ObjectId | None,
    vehicle_object_id: ObjectId | None,
):
    if driver_object_id is None:
        driver_object_id = _to_object_id(current_user_id, "driver_id")
    if str(driver_object_id) != current_user_id:
        raise ApiError("Drivers can only submit expense requests for themselves.", status_code=403)

    active_assignment = get_active_assignment_for_driver(current_user_id)
    if not active_assignment:
        raise ApiError("You must have an active vehicle assignment to submit an expense request.", status_code=403)

    if vehicle_object_id is None:
        vehicle_object_id = _to_object_id(active_assignment.get("vehicle_id"), "vehicle_id")
    if str(vehicle_object_id) != active_assignment.get("vehicle_id"):
        raise ApiError("Drivers can only submit expense requests for their assigned vehicle.", status_code=403)

    return driver_object_id, vehicle_object_id


def _enrich_expense(expense_document: dict) -> dict:
    expense = serialize_expense(expense_document)
    requested_by_document = users_collection().find_one({"_id": expense_document.get("requested_by")})
    approved_by_document = users_collection().find_one({"_id": expense_document.get("approved_by")})
    paid_by_document = users_collection().find_one({"_id": expense_document.get("paid_by")})
    rejected_by_document = users_collection().find_one({"_id": expense_document.get("rejected_by")})
    driver_document = users_collection().find_one({"_id": expense_document.get("driver_id")})
    vehicle_document = vehicles_collection().find_one({"_id": expense_document.get("vehicle_id")})

    expense["requested_by_user"] = serialize_user(requested_by_document) if requested_by_document else None
    expense["approved_by_user"] = serialize_user(approved_by_document) if approved_by_document else None
    expense["paid_by_user"] = serialize_user(paid_by_document) if paid_by_document else None
    expense["rejected_by_user"] = serialize_user(rejected_by_document) if rejected_by_document else None
    expense["driver"] = serialize_user(driver_document) if driver_document else None
    expense["vehicle"] = serialize_vehicle(vehicle_document) if vehicle_document else None

    finance_account_document = None
    finance_account_id = expense_document.get("finance_account_id")
    if finance_account_id:
        finance_account_document = finance_accounts_collection().find_one({"_id": finance_account_id})
    expense["finance_account"] = (
        serialize_finance_account_snapshot(finance_account_document) if finance_account_document else None
    )

    return expense


def list_expenses(current_user_id: str, current_role: str) -> list[dict]:
    query = {}
    if current_role == "driver":
        query["requested_by"] = _to_object_id(current_user_id, "current_user_id")

    documents = expenses_collection().find(query).sort([("expense_date", DESCENDING), ("created_at", DESCENDING)])
    return [_enrich_expense(document) for document in documents]


def get_expense_by_id(expense_id: str, current_user_id: str, current_role: str) -> dict:
    expense_object_id = _to_object_id(expense_id, "expense_id")
    document = expenses_collection().find_one({"_id": expense_object_id})
    if not document:
        raise ApiError("Expense not found.", status_code=404)

    if current_role == "driver" and str(document.get("requested_by")) != current_user_id:
        raise ApiError("You do not have permission to view this expense.", status_code=403)

    return _enrich_expense(document)


def create_expense(payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to create expenses.", status_code=403)

    expense_title = (payload.get("expense_title") or "").strip()
    if not expense_title:
        raise ApiError("expense_title is required.", status_code=400)

    amount = _validate_positive_amount(payload.get("amount"), "amount")
    expense_date = (payload.get("expense_date") or "").strip()
    if not expense_date:
        raise ApiError("expense_date is required.", status_code=400)

    expense_category = _validate_expense_category(payload.get("expense_category"))
    payment_method = _validate_payment_method(payload.get("payment_method"))
    finance_account_document = get_finance_account_document(payload.get("finance_account_id"))
    if finance_account_document.get("status") != "active":
        raise ApiError("Selected finance account is inactive.", status_code=400)

    driver_object_id = _to_object_id(payload.get("driver_id"), "driver_id", required=False)
    vehicle_object_id = _to_object_id(payload.get("vehicle_id"), "vehicle_id", required=False)

    if current_role == "driver":
        driver_object_id, vehicle_object_id = _validate_driver_submission(
            current_user_id=current_user_id,
            driver_object_id=driver_object_id,
            vehicle_object_id=vehicle_object_id,
        )
    else:
        if vehicle_object_id is not None:
            _get_vehicle_document(vehicle_object_id)
        if driver_object_id is not None:
            driver_document = _get_user_document(driver_object_id, expected_roles={"driver"})
            if vehicle_object_id is None:
                assigned_vehicle_id = (driver_document.get("driver_profile") or {}).get("assigned_vehicle_id")
                if assigned_vehicle_id:
                    vehicle_object_id = assigned_vehicle_id

    if driver_object_id is not None:
        _get_user_document(driver_object_id, expected_roles={"driver"})
    if vehicle_object_id is not None:
        _get_vehicle_document(vehicle_object_id)

    receipt_image = validate_file_reference(
        payload.get("receipt_image"),
        field_name="receipt_image",
        file_name="expense-receipt",
    )

    timestamp = now_utc()
    document = {
        "expense_title": expense_title,
        "expense_category": expense_category,
        "amount": amount,
        "expense_date": expense_date,
        "vehicle_id": vehicle_object_id,
        "driver_id": driver_object_id,
        "finance_account_id": finance_account_document["_id"],
        "finance_account_snapshot": serialize_finance_account_snapshot(finance_account_document),
        "payment_method": payment_method,
        "reference_number": (payload.get("reference_number") or "").strip() or None,
        "receipt_image": receipt_image,
        "notes": (payload.get("notes") or "").strip() or None,
        "status": "pending",
        "requested_by": _to_object_id(current_user_id, "requested_by"),
        "approved_by": None,
        "paid_by": None,
        "rejected_by": None,
        "approved_at": None,
        "rejected_at": None,
        "paid_at": None,
        "rejection_reason": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = expenses_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _enrich_expense(document)


def approve_expense(expense_id: str, current_user_id: str) -> dict:
    expense_object_id = _to_object_id(expense_id, "expense_id")
    document = expenses_collection().find_one({"_id": expense_object_id})
    if not document:
        raise ApiError("Expense not found.", status_code=404)
    if document.get("status") == "approved":
        raise ApiError("Expense has already been approved.", status_code=400)
    if document.get("status") == "paid":
        raise ApiError("Paid expenses cannot be approved again.", status_code=400)
    if document.get("status") == "rejected":
        raise ApiError("Rejected expenses cannot be approved.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "approved",
        "approved_by": _to_object_id(current_user_id, "approved_by"),
        "approved_at": timestamp,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "updated_at": timestamp,
    }
    expenses_collection().update_one({"_id": expense_object_id}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_expense(document)


def reject_expense(expense_id: str, current_user_id: str, rejection_reason: str | None) -> dict:
    expense_object_id = _to_object_id(expense_id, "expense_id")
    document = expenses_collection().find_one({"_id": expense_object_id})
    if not document:
        raise ApiError("Expense not found.", status_code=404)
    if document.get("status") == "paid":
        raise ApiError("Paid expenses cannot be rejected.", status_code=400)
    if document.get("status") == "rejected":
        raise ApiError("Expense has already been rejected.", status_code=400)

    reason = (rejection_reason or "").strip()
    if not reason:
        raise ApiError("rejection_reason is required when rejecting an expense.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "rejected",
        "approved_by": None,
        "approved_at": None,
        "rejected_by": _to_object_id(current_user_id, "rejected_by"),
        "rejected_at": timestamp,
        "rejection_reason": reason,
        "updated_at": timestamp,
    }
    expenses_collection().update_one({"_id": expense_object_id}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_expense(document)


def mark_expense_paid(expense_id: str, current_user_id: str) -> dict:
    expense_object_id = _to_object_id(expense_id, "expense_id")
    document = expenses_collection().find_one({"_id": expense_object_id})
    if not document:
        raise ApiError("Expense not found.", status_code=404)
    if document.get("status") == "paid":
        raise ApiError("Expense has already been marked as paid.", status_code=400)
    if document.get("status") != "approved":
        raise ApiError("Only approved expenses can be marked as paid.", status_code=400)

    finance_account_document = get_finance_account_document(document.get("finance_account_id"))
    if finance_account_document.get("status") != "active":
        raise ApiError("Selected finance account is inactive.", status_code=400)

    amount = round(float(document.get("amount") or 0), 2)
    current_balance = round(float(finance_account_document.get("current_balance") or 0), 2)
    if amount > current_balance:
        raise ApiError("Finance account balance is insufficient to pay this expense.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "paid",
        "paid_by": _to_object_id(current_user_id, "paid_by"),
        "paid_at": timestamp,
        "finance_account_snapshot": serialize_finance_account_snapshot(finance_account_document),
        "updated_at": timestamp,
    }
    expenses_collection().update_one({"_id": expense_object_id}, {"$set": update_fields})
    decrement_finance_account_balance(finance_account_document["_id"], amount)
    document.update(update_fields)
    return _enrich_expense(document)
