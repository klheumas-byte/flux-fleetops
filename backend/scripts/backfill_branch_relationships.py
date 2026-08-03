"""Backfill branch references on legacy FleetOps records. Dry-run unless --apply is supplied."""
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path: sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from extensions import get_collection


COLLECTIONS = (
    "vehicles", "vehicle_operation_requests", "maintenance", "preventive_maintenance",
    "stock_transfers", "dispatch_jobs", "delivery_orders", "delivery_batches", "item_issues", "item_returns",
)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--branch-code",required=True); parser.add_argument("--apply",action="store_true"); args=parser.parse_args()
    app=create_app("development")
    with app.app_context():
        branch=get_collection("branches").find_one({"code":args.branch_code.strip().upper()})
        if not branch: raise SystemExit("Branch code was not found. Create the branch first.")
        proposed={}
        users=get_collection("users"); proposed["users"]=users.count_documents({"primary_branch_id":{"$exists":False}})
        if args.apply:
            users.update_many({"primary_branch_id":{"$exists":False}},{"$set":{"primary_branch_id":branch["_id"],"allowed_branch_ids":[branch["_id"]]}})
        for name in COLLECTIONS:
            collection=get_collection(name); query={"branch_id":{"$exists":False}}; proposed[name]=collection.count_documents(query)
            if args.apply: collection.update_many(query,{"$set":{"branch_id":branch["_id"]}})
        print(("Applied" if args.apply else "Dry run"),args.branch_code,proposed)


if __name__ == "__main__": main()
