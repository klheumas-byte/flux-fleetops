"""Backfill password-state fields for legacy users without changing credentials.

Repeatable:
    python scripts/backfill_user_password_state.py
"""

from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import flask_app
from extensions import get_collection


def run() -> dict:
    with flask_app.app_context():
        users = get_collection("users")
        password_state = users.update_many(
            {"must_change_password": {"$exists": False}},
            {"$set": {"must_change_password": False}},
        )
        versions = users.update_many(
            {"password_version": {"$exists": False}},
            {"$set": {"password_version": 1}},
        )
        return {
            "password_state_matched": password_state.matched_count,
            "password_state_updated": password_state.modified_count,
            "password_version_matched": versions.matched_count,
            "password_version_updated": versions.modified_count,
        }


if __name__ == "__main__":
    print(run())
