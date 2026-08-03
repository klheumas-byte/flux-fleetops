"""Backfill multi-role fields without removing the legacy `role` value.

Run from the backend directory:
    python scripts/migrate_user_role_ids.py          # dry run
    python scripts/migrate_user_role_ids.py --apply  # write changes
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from extensions import get_collection
from services.rbac_service import normalize_role


def migrate(apply=False):
    query = {"$or": [{"role_ids": {"$exists": False}}, {"role_ids": {"$size": 0}}]}
    users = get_collection("users")
    proposed = 0
    updated = 0
    for user in users.find(query, {"role": 1, "selected_workspace": 1}):
        role = normalize_role(user.get("role"))
        if not role:
            continue
        proposed += 1
        if apply:
            result = users.update_one(
                {"_id": user["_id"], "$or": [{"role_ids": {"$exists": False}}, {"role_ids": {"$size": 0}}]},
                {"$set": {"role_ids": [role], "selected_workspace": user.get("selected_workspace") or role}},
            )
            updated += result.modified_count
    return {"mode": "apply" if apply else "dry-run", "proposed": proposed, "updated": updated}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist the backward-compatible backfill.")
    args = parser.parse_args()
    application = create_app()
    with application.app_context():
        print(migrate(args.apply))
