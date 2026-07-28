"""Non-destructive Sprint 4 allocation and ownership backfill.

Run from the backend directory:
  python scripts/backfill_commercial_operations.py
  python scripts/backfill_commercial_operations.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from extensions import get_database


LIVE_STATUSES = {"pending_handover", "active", "pending_return", "suspended"}
COMPANY_OWNER_TYPES = {"Axelera Owned", "Existing Company Asset"}


def build_updates(db) -> dict:
    conflicts = []
    for field in ("vehicle_id", "driver_id"):
        pipeline = [
            {"$match": {"status": {"$in": list(LIVE_STATUSES)}}},
            {"$group": {"_id": f"${field}", "ids": {"$push": "$_id"}, "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
        ]
        conflicts.extend({"field": field, **item} for item in db.assignments.aggregate(pipeline))

    assignment_updates = []
    for item in db.assignments.find({}):
        updates = {}
        if "allocation_active" not in item:
            updates["allocation_active"] = item.get("status") in LIVE_STATUSES
        if "start_time" not in item:
            updates["start_time"] = item.get("created_at")
        if "assignment_reason" not in item:
            updates["assignment_reason"] = "Legacy assignment backfill"
        if "target_enabled" not in item:
            updates["target_enabled"] = True
        if "target_frequency" not in item:
            updates["target_frequency"] = "weekly"
        if "target_amount" not in item:
            updates["target_amount"] = item.get("weekly_target")
        if "operating_mode" not in item:
            updates["operating_mode"] = "hybrid"
        if updates:
            assignment_updates.append((item["_id"], updates))

    driver_updates = []
    for driver in db.users.find({"role": "driver"}):
        profile = dict(driver.get("driver_profile") or {})
        changed = False
        defaults = {
            "operating_mode": "hybrid",
            "target_enabled": True,
            "target_frequency": "weekly",
        }
        active = db.assignments.find_one(
            {"driver_id": driver["_id"], "status": {"$in": list(LIVE_STATUSES)}}
        )
        if active:
            defaults["target_amount"] = active.get("weekly_target")
        for key, value in defaults.items():
            if key not in profile:
                profile[key] = value
                changed = True
        if changed:
            driver_updates.append((driver["_id"], profile))

    fleet_owners = {}
    vehicle_updates = []
    for vehicle in db.vehicles.find({}):
        existing_type = vehicle.get("ownership_type")
        ownership_type = existing_type or (
            "company_owned"
            if (vehicle.get("asset_owner_type") or "Axelera Owned") in COMPANY_OWNER_TYPES
            else "third_party_owned"
        )
        updates = {"ownership_type": ownership_type}
        if ownership_type == "third_party_owned" and not vehicle.get("fleet_owner_id"):
            owner_name = vehicle.get("asset_owner_name") or "Legacy third-party owner"
            owner = db.fleet_owners.find_one({"name": owner_name})
            owner_id = owner["_id"] if owner else fleet_owners.setdefault(owner_name, ObjectId())
            updates["fleet_owner_id"] = owner_id
        elif ownership_type == "company_owned":
            updates["fleet_owner_id"] = None
        vehicle_updates.append((vehicle["_id"], updates))

    return {
        "conflicts": conflicts,
        "assignment_updates": assignment_updates,
        "driver_updates": driver_updates,
        "fleet_owners": fleet_owners,
        "vehicle_updates": vehicle_updates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        db = get_database()
        plan = build_updates(db)
        if plan["conflicts"]:
            print(f"Blocked: {len(plan['conflicts'])} live allocation conflicts require review.")
            for conflict in plan["conflicts"]:
                print(conflict)
            return 2
        print(
            "Backfill plan:",
            {
                "assignments": len(plan["assignment_updates"]),
                "drivers": len(plan["driver_updates"]),
                "fleet_owners": len(plan["fleet_owners"]),
                "vehicles": len(plan["vehicle_updates"]),
            },
        )
        if not args.apply:
            print("Dry run only. Re-run with --apply to persist.")
            return 0
        for name, owner_id in plan["fleet_owners"].items():
            db.fleet_owners.update_one(
                {"name": name},
                {
                    "$setOnInsert": {
                        "_id": owner_id,
                        "name": name,
                        "status": "active",
                        "source": "sprint4_backfill",
                    }
                },
                upsert=True,
            )
        for assignment_id, updates in plan["assignment_updates"]:
            db.assignments.update_one({"_id": assignment_id}, {"$set": updates})
        for driver_id, profile in plan["driver_updates"]:
            db.users.update_one({"_id": driver_id}, {"$set": {"driver_profile": profile}})
        for vehicle_id, updates in plan["vehicle_updates"]:
            db.vehicles.update_one({"_id": vehicle_id}, {"$set": updates})
        print("Backfill applied successfully.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
