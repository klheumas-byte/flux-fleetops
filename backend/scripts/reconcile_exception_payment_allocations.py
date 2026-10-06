"""Restore payment-period allocations incorrectly detached by historical work exceptions.

Dry-run by default. The correction is idempotent and appends allocation/audit history;
it never changes payment amounts, payment dates, submission/confirmation timestamps, or actors.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from pymongo import MongoClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import BaseConfig


def _allocation_map(rows):
    result = {}
    for row in rows or []:
        key = str(row.get("cycle_key") or "")
        amount = round(float(row.get("amount") or 0), 2)
        if key and amount > 0:
            result[key] = {**row, "amount": amount}
    return result


def reconcile(database, assignment_id: ObjectId, actor_id: ObjectId, *, apply: bool = False):
    exceptions = list(database.weekly_non_working_requests.find({
        "assignment_id": assignment_id,
        "financial_status": "approved",
        "financial_treatment": {"$in": ["waive", "reduce"]},
    }))
    exception_cycles = {
        f"{datetime.strptime(date_value[:10], '%Y-%m-%d').date().isocalendar().year}-W{datetime.strptime(date_value[:10], '%Y-%m-%d').date().isocalendar().week:02d}"
        for row in exceptions
        for date_value in (row.get("week_starts") or [row.get("week_start")])
        if date_value
    }
    now = datetime.now(timezone.utc)
    changed = []
    for payment in database.collections.find({"assignment_id": assignment_id}):
        release_events = [
            event for event in payment.get("remittance_allocation_history") or []
            if event.get("reason") == "work_exception_decision"
        ]
        if not release_events:
            continue
        current = _allocation_map(payment.get("remittance_allocations"))
        restored = dict(current)
        for event in release_events:
            for cycle_key, allocation in _allocation_map(event.get("before")).items():
                if cycle_key in exception_cycles and cycle_key not in restored:
                    restored[cycle_key] = allocation
        before = sorted(current.values(), key=lambda row: (row.get("week_start") or "", row["cycle_key"]))
        after = sorted(restored.values(), key=lambda row: (row.get("week_start") or "", row["cycle_key"]))
        if before == after:
            continue
        amount = round(float(payment.get("amount") or 0), 2)
        event = {
            "changed_at": now,
            "changed_by": actor_id,
            "before": before,
            "after": after,
            "reason": "historical_exception_allocation_correction",
            "decision_reason": "Preserve each historical payment in its original effective remittance week.",
        }
        changed.append({
            "payment_id": str(payment["_id"]),
            "restored_cycles": sorted(set(restored) - set(current)),
            "unallocated_credit_before": round(max(amount - sum(row["amount"] for row in before), 0), 2),
            "unallocated_credit_after": round(max(amount - sum(row["amount"] for row in after), 0), 2),
        })
        if apply:
            database.collections.update_one({"_id": payment["_id"]}, {
                "$set": {
                    "remittance_allocations": after,
                    "remittance_unallocated_credit": changed[-1]["unallocated_credit_after"],
                    "remittance_allocated_at": now,
                    "remittance_allocated_by": actor_id,
                },
                "$push": {"remittance_allocation_history": event},
            })
    if apply and changed:
        correction_audit = {
            "action": "historical_payment_allocations_restored",
            "at": now,
            "by": actor_id,
            "reason": "Original effective payment periods preserved after exception correction.",
        }
        database.weekly_non_working_requests.update_many(
            {"_id": {"$in": [row["_id"] for row in exceptions]}},
            {"$set": {"released_confirmed_credit": 0.0, "released_pending_unallocated": 0.0},
             "$push": {"audit_history": correction_audit}},
        )
    return {"mode": "apply" if apply else "dry-run", "exception_cycles": sorted(exception_cycles), "payments": changed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assignment-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not ObjectId.is_valid(args.assignment_id) or not ObjectId.is_valid(args.actor_id):
        parser.error("assignment-id and actor-id must be valid ObjectIds")
    database = MongoClient(BaseConfig.MONGO_URI)[BaseConfig.MONGO_DB_NAME]
    print(reconcile(database, ObjectId(args.assignment_id), ObjectId(args.actor_id), apply=args.apply))


if __name__ == "__main__":
    main()
