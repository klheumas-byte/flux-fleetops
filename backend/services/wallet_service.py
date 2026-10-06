from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.user import serialize_user
from models.wallet_entry import serialize_wallet_entry
from services.payment_cycle_service import build_weekly_ledger, get_current_cycle_for_assignment, get_weekly_cycle_window, list_non_working_requests
from utils.api_error import ApiError
from utils.performance import build_cache_key, get_ttl_cached, set_ttl_cached


ALLOWED_WALLET_ENTRY_TYPES = {"weekly_target", "collection", "adjustment", "reversal"}


def now_utc():
    return datetime.now(timezone.utc)


def users_collection():
    return get_collection("users")


def wallet_entries_collection():
    return get_collection("wallet_entries")


def assignments_collection():
    return get_collection("assignments")


def ensure_wallet_indexes():
    wallet_entries_collection().create_index([("driver_id", ASCENDING)])
    wallet_entries_collection().create_index([("vehicle_id", ASCENDING)])
    wallet_entries_collection().create_index([("assignment_id", ASCENDING)])
    wallet_entries_collection().create_index([("type", ASCENDING)])
    wallet_entries_collection().create_index([("created_at", DESCENDING)])
    wallet_entries_collection().create_index([("event_key", ASCENDING)], unique=True, sparse=True)


def to_object_id(value, field_name: str, required: bool = True):
    if value is None:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _get_driver_document(driver_id):
    driver_object_id = to_object_id(driver_id, "driver_id")
    driver = users_collection().find_one({"_id": driver_object_id, "role": "driver"})
    if not driver:
        raise ApiError("Driver not found.", status_code=404)
    return driver


def create_wallet_entry(
    *,
    driver_id,
    vehicle_id=None,
    assignment_id=None,
    entry_type: str,
    description: str,
    debit: float = 0,
    credit: float = 0,
    reference_id=None,
    created_by=None,
    event_key: str | None = None,
):
    if entry_type not in ALLOWED_WALLET_ENTRY_TYPES:
        raise ApiError(
            "type must be one of: weekly_target, collection, adjustment, reversal.",
            status_code=400,
        )
    if isinstance(debit, bool) or isinstance(credit, bool):
        raise ApiError("debit and credit must be numeric.", status_code=400)
    if not isinstance(debit, (int, float)) or not isinstance(credit, (int, float)):
        raise ApiError("debit and credit must be numeric.", status_code=400)
    if debit < 0 or credit < 0:
        raise ApiError("debit and credit cannot be negative.", status_code=400)
    if debit == 0 and credit == 0:
        raise ApiError("A wallet entry must include a debit or credit amount.", status_code=400)

    driver_object_id = to_object_id(driver_id, "driver_id")
    vehicle_object_id = to_object_id(vehicle_id, "vehicle_id", required=False)
    assignment_object_id = to_object_id(assignment_id, "assignment_id", required=False)
    reference_object_id = to_object_id(reference_id, "reference_id", required=False)
    created_by_object_id = to_object_id(created_by, "created_by", required=False)

    if event_key:
        existing = wallet_entries_collection().find_one({"event_key": str(event_key)})
        if existing:
            return serialize_wallet_entry(existing)

    latest_entry = wallet_entries_collection().find_one(
        {"driver_id": driver_object_id},
        sort=[("created_at", DESCENDING), ("_id", DESCENDING)],
    )
    previous_balance = latest_entry.get("balance_after", 0) if latest_entry else 0
    balance_after = previous_balance + debit - credit

    wallet_entry_document = {
        "driver_id": driver_object_id,
        "vehicle_id": vehicle_object_id,
        "assignment_id": assignment_object_id,
        "type": entry_type,
        "description": description,
        "debit": float(debit),
        "credit": float(credit),
        "balance_after": float(balance_after),
        "reference_id": reference_object_id,
        "created_by": created_by_object_id,
        "created_at": now_utc(),
    }
    if event_key:
        wallet_entry_document["event_key"] = str(event_key)
    try:
        result = wallet_entries_collection().insert_one(wallet_entry_document)
    except DuplicateKeyError:
        existing = wallet_entries_collection().find_one({"event_key": str(event_key)}) if event_key else None
        if existing:
            return serialize_wallet_entry(existing)
        raise
    wallet_entry_document["_id"] = result.inserted_id
    return serialize_wallet_entry(wallet_entry_document)


def _can_view_driver_wallet(current_user_id: str, current_role: str, driver_id: str):
    if current_role in {"owner", "admin"}:
        return
    if current_role != "driver":
        raise ApiError("You do not have permission to access this wallet.", status_code=403)
    if current_user_id != driver_id:
        raise ApiError("You can only view your own wallet.", status_code=403)


def _wallet_summary_from_entries(driver: dict, entries: list[dict]) -> dict:
    total_debit = sum(float(entry.get("debit") or 0) for entry in entries)
    total_credit = sum(float(entry.get("credit") or 0) for entry in entries)
    outstanding_balance = total_debit - total_credit

    weekly_target = 0.0
    active_assignment = get_collection("assignments").find_one(
        {"driver_id": driver["_id"], "status": {"$in": ["active", "suspended"]}}
    )
    if active_assignment:
        current_cycle = get_current_cycle_for_assignment(active_assignment)
        weekly_target = float(current_cycle.get("final_due") if current_cycle.get("final_due") is not None else current_cycle.get("weekly_target") or 0)

    total_collected = sum(
        float(entry.get("credit") or 0) for entry in entries if entry.get("type") == "collection"
    )
    achievement_percentage = (total_collected / weekly_target * 100) if weekly_target > 0 else 0

    return {
        "outstanding_balance": float(outstanding_balance),
        "weekly_target": float(weekly_target),
        "total_collected": float(total_collected),
        "achievement_percentage": round(float(achievement_percentage), 2),
        "current_balance": float(entries[-1].get("balance_after")) if entries else 0.0,
        "total_debit": float(total_debit),
        "total_credit": float(total_credit),
    }


def get_driver_wallet_summary(current_user_id: str, current_role: str, driver_id: str) -> dict:
    _can_view_driver_wallet(current_user_id, current_role, driver_id)
    driver = _get_driver_document(driver_id)
    entries = list(
        wallet_entries_collection()
        .find({"driver_id": driver["_id"]})
        .sort([("created_at", ASCENDING), ("_id", ASCENDING)])
    )
    return {
        "driver": serialize_user(driver),
        "summary": _wallet_summary_from_entries(driver, entries),
    }


def list_driver_wallet_ledger(current_user_id: str, current_role: str, driver_id: str) -> dict:
    _can_view_driver_wallet(current_user_id, current_role, driver_id)
    driver = _get_driver_document(driver_id)
    entries = list(
        wallet_entries_collection()
        .find({"driver_id": driver["_id"]})
        .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
    )
    serialized_entries = [serialize_wallet_entry(entry) for entry in entries]
    return {
        "driver": serialize_user(driver),
        "summary": _wallet_summary_from_entries(driver, list(reversed(entries))),
        "ledger": serialized_entries,
    }


def list_wallet_driver_options() -> list[dict]:
    drivers = users_collection().find({"role": "driver"}).sort("full_name", ASCENDING)
    return [serialize_user(driver) for driver in drivers]


def get_logged_in_driver_wallet(driver_user_id: str) -> dict:
    cache_key = build_cache_key("driver_wallet", driver_user_id=driver_user_id)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached
    driver = _get_driver_document(driver_user_id)
    active_assignment = assignments_collection().find_one(
        {"driver_id": driver["_id"], "status": "active", "target_enabled": {"$ne": False}}
    )
    if not active_assignment:
        return set_ttl_cached(
            cache_key,
            {
            "driver_id": str(driver["_id"]),
            "active_assignment_id": None,
            "weekly_target": 0,
            "daily_target": 0,
            "total_debits": 0,
            "total_credits": 0,
            "outstanding_balance": 0,
            "achievement_percentage": 0,
            "weekly_cycle": None,
            "weekly_history": [],
            "ledger_entries": [],
        },
            ttl_seconds=15,
        )

    ledger_documents = list(
        wallet_entries_collection()
        .find({"driver_id": driver["_id"], "assignment_id": active_assignment["_id"]})
        .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
    )
    serialized_ledger = []
    total_debits = 0.0
    total_credits = 0.0
    for entry in ledger_documents:
        serialized = serialize_wallet_entry(entry)
        total_debits += float(serialized.get("debit") or 0)
        total_credits += float(serialized.get("credit") or 0)
        serialized_ledger.append(
            {
                "date": serialized.get("created_at"),
                "type": serialized.get("type"),
                "description": serialized.get("description"),
                "debit": float(serialized.get("debit") or 0),
                "credit": float(serialized.get("credit") or 0),
                "balance_after": float(serialized.get("balance_after") or 0),
                "reference_id": serialized.get("reference_id"),
            }
        )

    daily_target = float(active_assignment.get("daily_target") or 0)
    remittance = build_weekly_ledger(active_assignment)
    current_cycle_key = get_weekly_cycle_window()["cycle_key"]
    weekly_cycle = next((row for row in remittance["weeks"] if row["cycle_key"] == current_cycle_key), None)
    weekly_target = float(weekly_cycle.get("final_due") if weekly_cycle and weekly_cycle.get("final_due") is not None else remittance["agreement"].get("weekly_amount") or 0)
    weekly_history = remittance["weeks"]
    outstanding_balance = remittance["position"]["outstanding"]
    achievement_percentage = round(
        ((remittance["position"]["adjusted_expected"] - outstanding_balance)
         / remittance["position"]["adjusted_expected"] * 100)
        if remittance["position"]["adjusted_expected"] > 0 else 100,
        2,
    )

    return set_ttl_cached(
        cache_key,
        {
        "driver_id": str(driver["_id"]),
        "active_assignment_id": str(active_assignment["_id"]),
        "weekly_target": weekly_target,
        "daily_target": daily_target,
        "total_debits": round(total_debits, 2),
        "total_credits": round(total_credits, 2),
        "outstanding_balance": outstanding_balance,
        "achievement_percentage": achievement_percentage,
        "weekly_cycle": weekly_cycle,
        "weekly_history": weekly_history,
        "work_exception_requests": list_non_working_requests(driver_id=str(driver["_id"])),
        "remittance_agreement": remittance["agreement"],
        "financial_position": remittance["position"],
        "credit_payments": remittance.get("credit_payments", []),
        "credit": remittance["position"]["applicable_credit"],
        "arrears": remittance["position"]["arrears"],
        "ledger_entries": serialized_ledger,
    },
        ttl_seconds=15,
    )
