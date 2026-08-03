from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import sys

import mongomock
import pytest
from bson import ObjectId

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import dispatch_planner_service as planner
from services import driver_scope_service as scope
from services import user_service
from utils.api_error import ApiError


def collections(db):
    return lambda name: db[name]


def driver(branch=None, operational_scope="BRANCH"):
    return {"_id": ObjectId(), "full_name": f"{operational_scope} Driver", "role": "driver", "role_ids": ["driver"], "status": "active", "primary_branch_id": branch, "home_branch_id": branch, "allowed_branch_ids": [branch] if branch else [], "operational_scope": operational_scope, "driver_profile": {"approval_status": "approved"}}


def test_branch_driver_visibility_temporary_company_assignment_and_personal_exclusion():
    db = mongomock.MongoClient().driver_scope
    branch_a, branch_b = ObjectId(), ObjectId()
    manager = {"_id": ObjectId(), "full_name": "A Manager", "role": "branch_manager", "role_ids": ["branch_manager"], "status": "active", "primary_branch_id": branch_a, "allowed_branch_ids": []}
    home_a, home_b, company, personal = driver(branch_a), driver(branch_b), driver(None, "COMPANY_WIDE"), driver(None, "PERSONAL_ONLY")
    db.users.insert_many([manager, home_a, home_b, company, personal])
    now = datetime.now(timezone.utc)
    db.driver_branch_assignments.insert_one({"_id": ObjectId(), "driver_id": company["_id"], "branch_id": branch_a, "start_datetime": now - timedelta(hours=1), "end_datetime": now + timedelta(hours=2), "status": "active", "assigned_by": ObjectId(), "created_at": now})
    with patch.object(user_service, "get_collection", side_effect=collections(db)), patch.object(scope, "get_collection", side_effect=collections(db)):
        visible = user_service.list_drivers_for_role(str(manager["_id"]), "branch_manager")
    assert {row["id"] for row in visible} == {str(home_a["_id"]), str(company["_id"])}
    assert str(home_b["_id"]) not in {row["id"] for row in visible}
    assert str(personal["_id"]) not in {row["id"] for row in visible}


def test_temporary_assignment_conflict_and_expiry_reuse_existing_conflict_engine():
    db = mongomock.MongoClient().temporary_assignment
    branch = ObjectId(); db.branches.insert_one({"_id": branch, "name": "Madina", "status": "active"})
    admin = {"_id": ObjectId(), "role": "admin", "role_ids": ["admin"], "status": "active"}
    company = driver(None, "COMPANY_WIDE"); db.users.insert_many([admin, company])
    start = datetime.now(timezone.utc) + timedelta(days=1); end = start + timedelta(hours=8)
    payload = {"driver_id": str(company["_id"]), "branch_id": str(branch), "start_datetime": start.isoformat(), "end_datetime": end.isoformat(), "purpose": "Branch support"}
    with patch.object(scope, "get_collection", side_effect=collections(db)), patch.object(planner, "get_collection", side_effect=collections(db)):
        created = scope.create_temporary_branch_assignment(payload, current_user_id=str(admin["_id"]), current_role="admin")
        assert created["status"] == "scheduled"
        with pytest.raises(ApiError) as raised:
            scope.create_temporary_branch_assignment(payload, current_user_id=str(admin["_id"]), current_role="admin")
        assert raised.value.status_code == 409
        db.driver_branch_assignments.update_one({"_id": ObjectId(created["id"])}, {"$set": {"end_datetime": datetime.now(timezone.utc) - timedelta(minutes=1), "status": "active"}})
        assert scope.expire_temporary_assignments() == 1
        assert db.driver_branch_assignments.find_one({"_id": ObjectId(created["id"])})["status"] == "expired"


def test_personal_only_driver_is_excluded_from_planner_options():
    db = mongomock.MongoClient().planner_scope
    company, personal = driver(None, "COMPANY_WIDE"), driver(None, "PERSONAL_ONLY")
    db.users.insert_many([company, personal])
    with patch.object(planner, "get_collection", side_effect=collections(db)), patch.object(planner, "get_ttl_cached", return_value=None), patch.object(planner, "set_ttl_cached", side_effect=lambda _key, value, **_kwargs: value), patch.object(planner, "log_db_duration"):
        result = planner.list_planner_options(current_role="admin", current_user_id=str(ObjectId()))
    assert {row["id"] for row in result["drivers"]} == {str(company["_id"])}
