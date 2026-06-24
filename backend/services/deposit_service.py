from datetime import datetime, timezone
from math import ceil
from time import perf_counter

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.deposit import serialize_deposit
from models.finance_account import serialize_finance_account_snapshot
from models.user import serialize_user
from services.finance_account_service import get_finance_account_document, increment_finance_account_balance
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import log_db_duration


ALLOWED_DEPOSIT_METHODS = {"cash_deposit", "momo_transfer", "bank_transfer"}
ALLOWED_DEPOSIT_STATUSES = {"submitted", "verified", "rejected"}


def now_utc():
    return datetime.now(timezone.utc)


def deposits_collection():
    return get_collection("deposits")


def users_collection():
    return get_collection("users")


def collections_collection():
    return get_collection("collections")


def finance_accounts_collection():
    return get_collection("finance_accounts")


def ensure_deposit_indexes():
    ensure_indexes_for_collection(
        deposits_collection(),
        [
            {"keys": [("admin_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("deposit_date", DESCENDING)]},
            {"keys": [("submitted_by", ASCENDING)]},
            {"keys": [("verified_by", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("submitted_at", DESCENDING)]},
            {"keys": [("deposit_date", DESCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("deposit_date", DESCENDING)]},
            {"keys": [("admin_id", ASCENDING), ("status", ASCENDING), ("deposit_date", DESCENDING)]},
        ],
        collection_name="deposits",
    )


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


def _validate_positive_amount(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value <= 0:
        raise ApiError(f"{field_name} must be a positive number.", status_code=400)
    return round(float(value), 2)


def _get_admin_document(admin_id: str | ObjectId):
    admin_object_id = _to_object_id(admin_id, "admin_id")
    admin = users_collection().find_one({"_id": admin_object_id, "role": {"$in": ["owner", "admin"]}})
    if not admin:
        raise ApiError("Admin user not found.", status_code=404)
    return admin


def calculate_admin_holding_balance(admin_id: str | ObjectId) -> dict:
    admin_document = _get_admin_document(admin_id)
    total_collections = list(
        collections_collection().aggregate(
            [
                {
                    "$match": {
                        "received_by_admin_id": admin_document["_id"],
                        "status": "approved",
                    }
                },
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
            ]
        )
    )
    verified_deposits = list(
        deposits_collection().aggregate(
            [
                {
                    "$match": {
                        "admin_id": admin_document["_id"],
                        "status": "verified",
                    }
                },
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
            ]
        )
    )

    total_collected = round(float(total_collections[0]["total"]) if total_collections else 0.0, 2)
    total_deposited = round(float(verified_deposits[0]["total"]) if verified_deposits else 0.0, 2)
    holding_balance = round(total_collected - total_deposited, 2)

    return {
        "admin": serialize_user(admin_document),
        "total_collected": total_collected,
        "total_deposited": total_deposited,
        "holding_balance": holding_balance,
    }


def _enrich_deposit(deposit_document: dict) -> dict:
    deposit = serialize_deposit(deposit_document)
    admin_document = users_collection().find_one({"_id": deposit_document.get("admin_id")})
    submitted_by_document = users_collection().find_one({"_id": deposit_document.get("submitted_by")})
    verified_by_document = users_collection().find_one({"_id": deposit_document.get("verified_by")})
    rejected_by_document = users_collection().find_one({"_id": deposit_document.get("rejected_by")})

    deposit["admin"] = serialize_user(admin_document) if admin_document else None
    deposit["submitted_by_user"] = serialize_user(submitted_by_document) if submitted_by_document else None
    deposit["verified_by_user"] = serialize_user(verified_by_document) if verified_by_document else None
    deposit["rejected_by_user"] = serialize_user(rejected_by_document) if rejected_by_document else None
    finance_account_document = None
    finance_account_id = deposit_document.get("finance_account_id")
    if finance_account_id:
        finance_account_document = finance_accounts_collection().find_one({"_id": finance_account_id})
    deposit["finance_account"] = (
        serialize_finance_account_snapshot(finance_account_document) if finance_account_document else None
    )
    return deposit


def list_deposits(
    current_user_id: str,
    current_role: str,
    *,
    page: int = 1,
    page_size: int = 25,
    status: str | None = None,
) -> dict:
    query = {}
    if current_role == "admin":
        query["admin_id"] = _to_object_id(current_user_id, "current_user_id")
    if status and status != "all":
        query["status"] = status

    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 25), 1), 100)
    skip = (page - 1) * page_size

    count_started_at = perf_counter()
    total_records = deposits_collection().count_documents(query)
    log_db_duration("deposits.count_documents", count_started_at)

    summary_started_at = perf_counter()
    summary_result = list(
        deposits_collection().aggregate(
            [
                {"$match": query},
                {
                    "$group": {
                        "_id": None,
                        "total_amount": {"$sum": "$amount"},
                        "verified_total": {
                            "$sum": {"$cond": [{"$eq": ["$status", "verified"]}, {"$ifNull": ["$amount", 0]}, 0]}
                        },
                        "pending_total": {
                            "$sum": {"$cond": [{"$eq": ["$status", "submitted"]}, {"$ifNull": ["$amount", 0]}, 0]}
                        },
                        "rejected_total": {
                            "$sum": {"$cond": [{"$eq": ["$status", "rejected"]}, {"$ifNull": ["$amount", 0]}, 0]}
                        },
                        "verified_count": {"$sum": {"$cond": [{"$eq": ["$status", "verified"]}, 1, 0]}},
                        "pending_count": {"$sum": {"$cond": [{"$eq": ["$status", "submitted"]}, 1, 0]}},
                        "rejected_count": {"$sum": {"$cond": [{"$eq": ["$status", "rejected"]}, 1, 0]}},
                    }
                },
            ]
        )
    )
    log_db_duration("deposits.summary_aggregate", summary_started_at)
    summary = summary_result[0] if summary_result else {}

    find_started_at = perf_counter()
    documents = list(
        deposits_collection()
        .find(
            query,
            {
                "admin_id": 1,
                "finance_account_id": 1,
                "amount": 1,
                "deposit_date": 1,
                "deposit_method": 1,
                "destination_name": 1,
                "finance_account_snapshot": 1,
                "reference_number": 1,
                "receipt_image": 1,
                "notes": 1,
                "status": 1,
                "submitted_by": 1,
                "verified_by": 1,
                "rejected_by": 1,
                "rejection_reason": 1,
                "submitted_at": 1,
                "verified_at": 1,
                "rejected_at": 1,
                "created_at": 1,
            },
        )
        .sort([("deposit_date", DESCENDING), ("created_at", DESCENDING)])
        .skip(skip)
        .limit(page_size)
    )
    log_db_duration("deposits.find_page", find_started_at)
    return {
        "deposits": [_enrich_deposit(document) for document in documents],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_records": total_records,
            "total_pages": ceil(total_records / page_size) if total_records else 1,
        },
        "summary": {
            "total_records": total_records,
            "total_amount": round(float(summary.get("total_amount") or 0), 2),
            "verified_total": round(float(summary.get("verified_total") or 0), 2),
            "pending_total": round(float(summary.get("pending_total") or 0), 2),
            "rejected_total": round(float(summary.get("rejected_total") or 0), 2),
            "verified_count": int(summary.get("verified_count") or 0),
            "pending_count": int(summary.get("pending_count") or 0),
            "rejected_count": int(summary.get("rejected_count") or 0),
        },
    }


def get_deposit_by_id(deposit_id: str, current_user_id: str, current_role: str) -> dict:
    deposit_object_id = _to_object_id(deposit_id, "deposit_id")
    document = deposits_collection().find_one({"_id": deposit_object_id})
    if not document:
        raise ApiError("Deposit not found.", status_code=404)

    if current_role == "admin" and str(document.get("admin_id")) != current_user_id:
        raise ApiError("You do not have permission to view this deposit.", status_code=403)

    return _enrich_deposit(document)


def create_deposit(payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to submit deposits.", status_code=403)

    admin_id = payload.get("admin_id") or current_user_id
    if current_role == "admin" and admin_id != current_user_id:
        raise ApiError("Admins can only submit deposits from their own holding balance.", status_code=403)

    admin_document = _get_admin_document(admin_id)
    amount = _validate_positive_amount(payload.get("amount"), "amount")
    holding = calculate_admin_holding_balance(admin_document["_id"])
    if amount > holding["holding_balance"]:
        raise ApiError("Deposit amount cannot exceed the admin holding balance.", status_code=400)

    deposit_date = (payload.get("deposit_date") or "").strip()
    if not deposit_date:
        raise ApiError("deposit_date is required.", status_code=400)

    deposit_method = (payload.get("deposit_method") or "").strip().lower()
    if deposit_method not in ALLOWED_DEPOSIT_METHODS:
        raise ApiError(
            "deposit_method must be one of: cash_deposit, momo_transfer, bank_transfer.",
            status_code=400,
        )

    destination_name = (payload.get("destination_name") or "").strip()
    finance_account_document = get_finance_account_document(payload.get("finance_account_id"))
    if finance_account_document.get("status") != "active":
        raise ApiError("Selected finance account is inactive.", status_code=400)
    if not destination_name:
        destination_name = finance_account_document.get("account_name") or "Finance Account"

    receipt_image = payload.get("receipt_image")
    if receipt_image is not None and not isinstance(receipt_image, str):
        raise ApiError("receipt_image must be a string.", status_code=400)

    timestamp = now_utc()
    document = {
        "admin_id": admin_document["_id"],
        "finance_account_id": finance_account_document["_id"],
        "amount": amount,
        "deposit_date": deposit_date,
        "deposit_method": deposit_method,
        "destination_name": destination_name,
        "finance_account_snapshot": serialize_finance_account_snapshot(finance_account_document),
        "reference_number": (payload.get("reference_number") or "").strip() or None,
        "receipt_image": receipt_image or None,
        "notes": (payload.get("notes") or "").strip() or None,
        "status": "submitted",
        "submitted_by": _to_object_id(current_user_id, "submitted_by"),
        "verified_by": None,
        "rejected_by": None,
        "rejection_reason": None,
        "submitted_at": timestamp,
        "verified_at": None,
        "rejected_at": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = deposits_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return _enrich_deposit(document)


def verify_deposit(deposit_id: str, current_user_id: str, finance_account_id: str | None = None) -> dict:
    deposit_object_id = _to_object_id(deposit_id, "deposit_id")
    document = deposits_collection().find_one({"_id": deposit_object_id})
    if not document:
        raise ApiError("Deposit not found.", status_code=404)
    if document.get("status") == "verified":
        raise ApiError("Deposit has already been verified.", status_code=400)
    if document.get("status") == "rejected":
        raise ApiError("Rejected deposits cannot be verified.", status_code=400)

    selected_finance_account_id = finance_account_id or document.get("finance_account_id")
    if not selected_finance_account_id:
        raise ApiError("finance_account_id is required when verifying a deposit.", status_code=400)
    finance_account_document = get_finance_account_document(selected_finance_account_id)
    if finance_account_document.get("status") != "active":
        raise ApiError("Selected finance account is inactive.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "verified",
        "finance_account_id": finance_account_document["_id"],
        "destination_name": finance_account_document.get("account_name") or document.get("destination_name"),
        "finance_account_snapshot": serialize_finance_account_snapshot(finance_account_document),
        "verified_by": _to_object_id(current_user_id, "verified_by"),
        "verified_at": timestamp,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "updated_at": timestamp,
    }
    deposits_collection().update_one({"_id": deposit_object_id}, {"$set": update_fields})
    increment_finance_account_balance(finance_account_document["_id"], float(document.get("amount") or 0))
    document.update(update_fields)
    return _enrich_deposit(document)


def reject_deposit(deposit_id: str, current_user_id: str, rejection_reason: str | None) -> dict:
    deposit_object_id = _to_object_id(deposit_id, "deposit_id")
    document = deposits_collection().find_one({"_id": deposit_object_id})
    if not document:
        raise ApiError("Deposit not found.", status_code=404)
    if document.get("status") == "verified":
        raise ApiError("Verified deposits cannot be rejected.", status_code=400)
    if document.get("status") == "rejected":
        raise ApiError("Deposit has already been rejected.", status_code=400)

    reason = (rejection_reason or "").strip()
    if not reason:
        raise ApiError("rejection_reason is required when rejecting a deposit.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "rejected",
        "verified_by": None,
        "verified_at": None,
        "rejected_by": _to_object_id(current_user_id, "rejected_by"),
        "rejected_at": timestamp,
        "rejection_reason": reason,
        "updated_at": timestamp,
    }
    deposits_collection().update_one({"_id": deposit_object_id}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_deposit(document)


def list_holding_balances(current_user_id: str, current_role: str) -> list[dict]:
    if current_role == "admin":
        return [calculate_admin_holding_balance(current_user_id)]

    admins = users_collection().find({"role": {"$in": ["owner", "admin"]}}).sort("full_name", ASCENDING)
    return [calculate_admin_holding_balance(admin["_id"]) for admin in admins]


def get_company_funds_summary() -> dict:
    finance_summaries = list(
        finance_accounts_collection().aggregate(
            [
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": "$current_balance"},
                    }
                }
            ]
        )
    )
    summaries = list(
        deposits_collection().aggregate(
            [
                {
                    "$group": {
                        "_id": "$status",
                        "total": {"$sum": "$amount"},
                        "count": {"$sum": 1},
                    }
                }
            ]
        )
    )
    by_status = {
        summary["_id"]: {
            "total": round(float(summary.get("total") or 0), 2),
            "count": int(summary.get("count") or 0),
        }
        for summary in summaries
    }
    available_funds = round(float(finance_summaries[0]["total"]) if finance_summaries else 0.0, 2)

    return {
        "available_funds": available_funds,
        "verified_deposits_total": by_status.get("verified", {}).get("total", 0.0),
        "verified_deposits_count": by_status.get("verified", {}).get("count", 0),
        "pending_deposits_total": by_status.get("submitted", {}).get("total", 0.0),
        "pending_deposits_count": by_status.get("submitted", {}).get("count", 0),
        "rejected_deposits_total": by_status.get("rejected", {}).get("total", 0.0),
        "rejected_deposits_count": by_status.get("rejected", {}).get("count", 0),
    }
