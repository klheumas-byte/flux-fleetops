"""Safe, repeatable Sprint 7-9 default backfill.

Dry-run is the default:
  python scripts/backfill_sprint_7_9.py
  python scripts/backfill_sprint_7_9.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from extensions import get_database


def run(db, *, apply=False):
    query = {
        "role": "driver",
        "$or": [
            {"driver_profile": {"$exists": False}},
            {"driver_profile.private_finance_enabled": {"$exists": False}},
        ],
    }
    documents = list(db.users.find(query, {"driver_profile": 1}))
    candidates = len(documents)
    modified = 0
    if apply and candidates:
        for document in documents:
            profile = dict(document.get("driver_profile") or {})
            profile["private_finance_enabled"] = False
            result = db.users.update_one({"_id": document["_id"]}, {"$set": {"driver_profile": profile}})
            modified += result.modified_count
    return {"candidates": candidates, "modified": modified, "mode": "apply" if apply else "dry-run"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist the idempotent default updates.")
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        result = run(get_database(), apply=args.apply)
    print(f"mode={result['mode']} candidates={result['candidates']} modified={result['modified']}")


if __name__ == "__main__":
    main()
