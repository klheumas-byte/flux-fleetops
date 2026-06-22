from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.finance_account import serialize_finance_account
from models.user import serialize_user
from utils.api_error import ApiError


ALLOWED_ACCOUNT_TYPES = {"bank", "momo", "cash", "reserve"}
ALLOWED_ACCOUNT_STATUSES = {"active", "inactive"}


def now_utc():
    return datetime.now(timezone.utc)


def finance_accounts_collection():
    return get_collection("finance_accounts")


def deposits_collection():
    return get_collection("deposits")


def users_collection():
    return get_collection("users")


def ensure_finance_account_indexes():
    finance_accounts_collection().create_index([("account_name", ASCENDING)], unique=True)
    finance_accounts_collection().create_index([("account_type", ASCENDING)])
    finance_accounts_collection().create_index([("status", ASCENDING)])
    finance_accounts_collection().create_index([("created_at", DESCENDING)])


def _to_object_id(value, field_name: str, required: bool = True):
    if value is None:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _validate_non_negative_amount(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _get_owner_document(owner_id: str | ObjectId):
    owner_object_id = _to_object_id(owner_id, "owner_id")
    owner = users_collection().find_one({"_id": owner_object_id, "role": "owner"})
    if not owner:
        raise ApiError("Owner user not found.", status_code=404)
    return owner


def get_finance_account_document(account_id: str | ObjectId):
    account_object_id = _to_object_id(account_id, "finance_account_id")
    document = finance_accounts_collection().find_one({"_id": account_object_id})
    if not document:
        raise ApiError("Finance account not found.", status_code=404)
    return document


def _enrich_finance_account(account_document: dict) -> dict:
    account = serialize_finance_account(account_document)
    created_by_document = users_collection().find_one({"_id": account_document.get("created_by")})
    account["created_by_user"] = serialize_user(created_by_document) if created_by_document else None
    return account


def list_finance_accounts(current_role: str) -> list[dict]:
    query = {}
    if current_role == "admin":
        query["status"] = "active"
    documents = finance_accounts_collection().find(query).sort(
        [("account_type", ASCENDING), ("account_name", ASCENDING)]
    )
    return [_enrich_finance_account(document) for document in documents]


def get_finance_account_by_id(account_id: str, current_role: str) -> dict:
    document = get_finance_account_document(account_id)
    if current_role == "admin" and document.get("status") != "active":
        raise ApiError("You do not have permission to view this finance account.", status_code=403)
    return _enrich_finance_account(document)


def create_finance_account(payload: dict, current_user_id: str) -> dict:
    _get_owner_document(current_user_id)
    account_name = (payload.get("account_name") or "").strip()
    if not account_name:
        raise ApiError("account_name is required.", status_code=400)
    if finance_accounts_collection().find_one({"account_name": account_name}):
        raise ApiError("Account name must be unique.", status_code=400)

    account_type = (payload.get("account_type") or "").strip().lower()
    if account_type not in ALLOWED_ACCOUNT_TYPES:
        raise ApiError("account_type must be one of: bank, momo, cash, reserve.", status_code=400)

    opening_balance = _validate_non_negative_amount(payload.get("opening_balance") or 0, "opening_balance")
    status = (payload.get("status") or "active").strip().lower()
    if status not in ALLOWED_ACCOUNT_STATUSES:
        raise ApiError("status must be one of: active, inactive.", status_code=400)

    timestamp = now_utc()
    document = {
        "account_name": account_name,
        "account_type": account_type,
        "provider_name": (payload.get("provider_name") or "").strip() or None,
        "account_number": (payload.get("account_number") or "").strip() or None,
        "branch": (payload.get("branch") or "").strip() or None,
        "opening_balance": opening_balance,
        "current_balance": opening_balance,
        "status": status,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = finance_accounts_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _enrich_finance_account(document)


def update_finance_account(account_id: str, payload: dict, current_user_id: str) -> dict:
    _get_owner_document(current_user_id)
    document = get_finance_account_document(account_id)

    update_fields = {}
    if "account_name" in payload:
        account_name = (payload.get("account_name") or "").strip()
        if not account_name:
            raise ApiError("account_name cannot be empty.", status_code=400)
        existing = finance_accounts_collection().find_one({"account_name": account_name})
        if existing and existing.get("_id") != document.get("_id"):
            raise ApiError("Account name must be unique.", status_code=400)
        update_fields["account_name"] = account_name

    if "account_type" in payload:
        account_type = (payload.get("account_type") or "").strip().lower()
        if account_type not in ALLOWED_ACCOUNT_TYPES:
            raise ApiError("account_type must be one of: bank, momo, cash, reserve.", status_code=400)
        update_fields["account_type"] = account_type

    if "provider_name" in payload:
        update_fields["provider_name"] = (payload.get("provider_name") or "").strip() or None
    if "account_number" in payload:
        update_fields["account_number"] = (payload.get("account_number") or "").strip() or None
    if "branch" in payload:
        update_fields["branch"] = (payload.get("branch") or "").strip() or None

    update_fields["updated_at"] = now_utc()
    finance_accounts_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_finance_account(document)


def update_finance_account_status(account_id: str, status: str, current_user_id: str) -> dict:
    _get_owner_document(current_user_id)
    document = get_finance_account_document(account_id)
    next_status = (status or "").strip().lower()
    if next_status not in ALLOWED_ACCOUNT_STATUSES:
        raise ApiError("status must be one of: active, inactive.", status_code=400)
    if document.get("status") == next_status:
        raise ApiError("Finance account already has that status.", status_code=400)

    update_fields = {
        "status": next_status,
        "updated_at": now_utc(),
    }
    finance_accounts_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_finance_account(document)


def increment_finance_account_balance(account_id: str | ObjectId, amount: float):
    account_object_id = _to_object_id(account_id, "finance_account_id")
    amount_value = _validate_non_negative_amount(amount, "amount")
    finance_accounts_collection().update_one(
        {"_id": account_object_id},
        {
            "$inc": {"current_balance": amount_value},
            "$set": {"updated_at": now_utc()},
        },
    )


def decrement_finance_account_balance(account_id: str | ObjectId, amount: float):
    account_object_id = _to_object_id(account_id, "finance_account_id")
    amount_value = _validate_non_negative_amount(amount, "amount")
    account_document = get_finance_account_document(account_object_id)
    current_balance = round(float(account_document.get("current_balance") or 0), 2)
    if amount_value > current_balance:
        raise ApiError("Finance account balance is insufficient.", status_code=400)

    finance_accounts_collection().update_one(
        {"_id": account_object_id},
        {
            "$inc": {"current_balance": -amount_value},
            "$set": {"updated_at": now_utc()},
        },
    )


def finance_account_has_transactions(account_id: str | ObjectId) -> bool:
    account_object_id = _to_object_id(account_id, "finance_account_id")
    return deposits_collection().find_one({"finance_account_id": account_object_id}) is not None


def get_finance_accounts_summary(current_role: str) -> dict:
    accounts = list_finance_accounts(current_role)
    type_totals = {account_type: 0.0 for account_type in ALLOWED_ACCOUNT_TYPES}
    active_count = 0

    for account in accounts:
        type_totals[account["account_type"]] += float(account.get("current_balance") or 0)
        if account.get("status") == "active":
            active_count += 1

    total_company_funds = round(sum(type_totals.values()), 2)
    return {
        "total_company_funds": total_company_funds,
        "active_accounts_count": active_count,
        "bank_accounts_total": round(type_totals["bank"], 2),
        "momo_accounts_total": round(type_totals["momo"], 2),
        "cash_accounts_total": round(type_totals["cash"], 2),
        "reserve_accounts_total": round(type_totals["reserve"], 2),
        "accounts": accounts,
    }
