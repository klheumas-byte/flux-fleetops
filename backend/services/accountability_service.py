from pymongo import ASCENDING
from time import perf_counter

from extensions import get_collection
from models.user import serialize_user
from services.payment_cycle_service import get_current_cycle_for_assignment
from utils.performance import log_db_duration


def users_collection():
    return get_collection("users")


def collections_collection():
    return get_collection("collections")


def deposits_collection():
    return get_collection("deposits")


def assignments_collection():
    return get_collection("assignments")


def _sum_amounts(filter_query: dict, *, source_collection=None) -> float:
    collection = source_collection if source_collection is not None else collections_collection()
    pipeline = [
        {"$match": filter_query},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]
    result = list(collection.aggregate(pipeline))
    return float(result[0]["total"]) if result else 0.0


def list_admin_accountability() -> list[dict]:
    admins_started_at = perf_counter()
    admins = list(
        users_collection()
        .find({"role": {"$in": ["owner", "admin"]}})
        .sort("full_name", ASCENDING)
    )
    log_db_duration("admins.accountability.admins_find", admins_started_at)

    collections_started_at = perf_counter()
    collected_rows = list(
        collections_collection().aggregate(
            [
                {"$match": {"status": "approved", "received_by_admin_id": {"$ne": None}}},
                {"$group": {"_id": "$received_by_admin_id", "total": {"$sum": "$amount"}}},
            ]
        )
    )
    approved_rows = list(
        collections_collection().aggregate(
            [
                {"$match": {"status": "approved", "approved_by_admin_id": {"$ne": None}}},
                {"$group": {"_id": "$approved_by_admin_id", "total": {"$sum": "$amount"}}},
            ]
        )
    )
    log_db_duration("admins.accountability.collections_aggregates", collections_started_at)

    deposits_started_at = perf_counter()
    deposited_rows = list(
        deposits_collection().aggregate(
            [
                {"$match": {"status": "verified", "admin_id": {"$ne": None}}},
                {"$group": {"_id": "$admin_id", "total": {"$sum": "$amount"}}},
            ]
        )
    )
    log_db_duration("admins.accountability.deposits_aggregate", deposits_started_at)

    collected_by_admin = {
        row["_id"]: float(row.get("total") or 0) for row in collected_rows if row.get("_id") is not None
    }
    approved_by_admin = {
        row["_id"]: float(row.get("total") or 0) for row in approved_rows if row.get("_id") is not None
    }
    deposited_by_admin = {
        row["_id"]: float(row.get("total") or 0) for row in deposited_rows if row.get("_id") is not None
    }

    accountability_records = []
    for admin in admins:
        total_collected = round(collected_by_admin.get(admin["_id"], 0.0), 2)
        total_approved = round(approved_by_admin.get(admin["_id"], 0.0), 2)
        total_deposited = round(deposited_by_admin.get(admin["_id"], 0.0), 2)
        accountability_records.append(
            {
                "admin": serialize_user(admin),
                "total_collected": total_collected,
                "total_approved": total_approved,
                "total_deposited": total_deposited,
                "current_holding_balance": round(total_collected - total_deposited, 2),
            }
        )

    return accountability_records


def get_owner_weekly_payment_overview() -> dict:
    assignments = list(assignments_collection().find({"status": {"$in": ["active", "suspended"]}}))

    total_expected = 0.0
    total_approved = 0.0
    total_outstanding = 0.0
    arrears = 0.0
    drivers_below_target = []

    for assignment in assignments:
        cycle = get_current_cycle_for_assignment(assignment)
        total_expected += float(cycle.get("weekly_target") or 0)
        total_approved += float(cycle.get("approved_total") or 0)
        total_outstanding += float(cycle.get("outstanding_balance") or 0)
        if cycle.get("status") == "overdue":
            arrears += float(cycle.get("outstanding_balance") or 0)
        if float(cycle.get("approved_total") or 0) < float(cycle.get("weekly_target") or 0):
            driver = users_collection().find_one({"_id": assignment.get("driver_id")})
            drivers_below_target.append(
                {
                    "driver": serialize_user(driver) if driver else None,
                    "assignment_id": str(assignment["_id"]),
                    "cycle": cycle,
                }
            )

    return {
        "total_expected": round(total_expected, 2),
        "total_approved": round(total_approved, 2),
        "total_outstanding": round(total_outstanding, 2),
        "arrears": round(arrears, 2),
        "drivers_below_target": drivers_below_target,
    }
