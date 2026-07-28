"""Safely mark legacy vehicles as commercial without converting any records.

Repeatable:
    python scripts/backfill_personal_vehicle_defaults.py
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
        result = get_collection("vehicles").update_many(
            {"usage_type": {"$exists": False}},
            {"$set": {"usage_type": "commercial"}},
        )
        return {"matched": result.matched_count, "updated": result.modified_count}


if __name__ == "__main__":
    print(run())
