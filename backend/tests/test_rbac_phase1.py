import sys
from pathlib import Path
from unittest.mock import patch

import mongomock
from flask import Flask
from flask_jwt_extended import JWTManager, decode_token

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import services.rbac_service as rbac_service
import routes.rbac as rbac_routes
import utils.decorators as decorators
from services.rbac_service import ROLE_DEFINITIONS, dashboard_for_role, effective_data_scope, permissions_for_user, user_has_permission, user_role_codes
import services.auth_service as auth_service
from models.user import serialize_driver_profile, serialize_user


def test_all_phase_one_roles_have_dashboards_and_permissions():
    roles = {
        "system_administrator", "operations_administrator", "operations_manager", "driver",
        "field_agent", "issuing_receiving_officer", "finance_officer",
    }
    assert roles.issubset(ROLE_DEFINITIONS)
    for role in roles:
        assert dashboard_for_role(role)
        assert permissions_for_user({"role": role})


def test_finance_and_operations_separation_is_enforced_by_policy():
    finance = {"role": "finance_officer"}
    operations = {"role": "operations_administrator"}
    assert user_has_permission(finance, "finance.view")
    assert not user_has_permission(finance, "driver.assign")
    assert user_has_permission(operations, "driver.assign")
    assert not user_has_permission(operations, "finance.view")


def test_system_administrator_has_no_implicit_profitability_access():
    system = {"role": "system_administrator"}
    assert user_has_permission(system, "users.manage")
    assert not user_has_permission(system, "finance.view")


def test_user_permission_grants_and_denials_override_role_defaults():
    user = {
        "role": "operations_manager",
        "permission_grants": ["finance.view"],
        "permission_denials": ["driver.assign"],
    }
    assert user_has_permission(user, "finance.view")
    assert not user_has_permission(user, "driver.assign")


def test_multi_role_permissions_are_a_union_and_legacy_role_is_retained():
    user = {"role": "driver", "role_ids": ["driver", "operations_manager"]}
    assert user_role_codes(user) == ["driver", "operations_manager"]
    assert user_has_permission(user, "delivery.execute")
    assert user_has_permission(user, "maintenance.manage")
    assert not user_has_permission(user, "profitability.view")


def test_driver_profile_survives_assignment_of_management_role():
    profile = {"license_number": "DRV-7", "approval_status": "approved"}
    user = {"role": "operations_manager", "role_ids": ["operations_manager", "driver"], "driver_profile": profile}
    serialized = serialize_driver_profile(user)
    assert serialized["license_number"] == "DRV-7"
    assert serialized["approval_status"] == "approved"


def test_effective_scope_uses_broadest_active_role_scope():
    assert effective_data_scope({"role": "driver"}) == "ASSIGNED_RECORDS"
    assert effective_data_scope({"role": "driver", "role_ids": ["driver", "operations_manager"]}) == "ALLOWED_BRANCHES"


def test_legacy_single_role_read_is_backward_compatible():
    assert user_role_codes({"role": "fleet_owner"}) == ["fleet_owner"]
    assert permissions_for_user({"role": "fleet_owner"}) == ["fleet_owner.portal"]


def test_scheduler_permissions_are_scoped_to_operational_workspaces():
    manager = {"role": "operations_manager"}
    driver = {"role": "driver"}
    agent = {"role": "field_agent"}
    issuing = {"role": "issuing_receiving_officer"}
    assert user_has_permission(manager, "delivery_scheduler.manage")
    assert user_has_permission(manager, "delivery_runs.publish")
    assert not user_has_permission(driver, "delivery_scheduler.manage")
    assert user_has_permission(driver, "delivery_schedule.view_assigned")
    assert user_has_permission(agent, "delivery_schedule.view_assigned")
    assert user_has_permission(issuing, "loading_schedule.view")


def test_delivery_accountability_permissions_separate_receiving_management_and_reopen():
    administrator = {"role": "operations_administrator"}
    manager = {"role": "operations_manager"}
    issuing = {"role": "issuing_receiving_officer"}
    driver = {"role": "driver"}
    assert user_has_permission(issuing, "returns.receive")
    assert not user_has_permission(issuing, "reconciliation.manage")
    assert user_has_permission(manager, "exceptions.manage")
    assert user_has_permission(manager, "investigations.manage")
    assert user_has_permission(manager, "reconciliation.manage")
    assert user_has_permission(manager, "delivery_batches.close")
    assert not user_has_permission(manager, "delivery_batches.reopen")
    assert user_has_permission(administrator, "delivery_batches.reopen")
    assert not user_has_permission(driver, "returns.receive")


def test_access_control_user_list_uses_live_multi_role_authority():
    db = mongomock.MongoClient().rbac_users
    db.users.insert_many([
        {"full_name": "System", "role": "driver", "role_ids": ["driver", "system_administrator"], "status": "active"},
        {"full_name": "Finance", "role": "finance_officer", "status": "active"},
        {"full_name": "Driver", "role": "Driver", "status": "active"},
    ])
    actor = db.users.find_one({"full_name": "System"})
    with patch.object(auth_service, "users_collection", return_value=db.users):
        users = auth_service.list_users_for_actor(actor)
    assert {user["full_name"] for user in users} == {"System", "Finance", "Driver"}


def test_operational_user_list_handles_legacy_role_casing():
    db = mongomock.MongoClient().rbac_operational_users
    db.users.insert_many([
        {"full_name": "Operations", "role": "operations_administrator", "status": "active"},
        {"full_name": "Legacy Driver", "role": "Driver", "status": "active"},
        {"full_name": "Finance", "role": "finance_officer", "status": "active"},
    ])
    actor = db.users.find_one({"full_name": "Operations"})
    with patch.object(auth_service, "users_collection", return_value=db.users):
        users = auth_service.list_users_for_actor(actor)
    assert [user["full_name"] for user in users] == ["Legacy Driver"]


def test_role_definitions_are_cached_within_one_request_context():
    app = Flask(__name__)
    roles = mongomock.MongoClient().rbac_cache.roles
    roles.insert_one({"code": "driver", "name": "Driver Override", "permissions": ["delivery.execute"], "status": "active"})
    with app.test_request_context("/api/users"), patch.object(rbac_service, "get_collection", return_value=roles), patch.object(roles, "find", wraps=roles.find) as find:
        assert rbac_service.role_definition("driver")["name"] == "Driver Override"
        assert rbac_service.role_definition("driver")["name"] == "Driver Override"
    assert find.call_count == 1


def test_role_normalization_accepts_legacy_fields_objects_and_codes():
    user = {
        "user_type": "Driver",
        "role_ids": ["operations_manager"],
        "roles": [{"code": "finance_officer"}, {"id": "field_agent"}],
    }
    assert user_role_codes(user) == ["operations_manager", "finance_officer", "field_agent", "driver"]


def test_user_response_has_canonical_active_role_objects_and_combined_permissions():
    user = serialize_user({
        "_id": "user-1",
        "full_name": "Multi Role User",
        "user_type": "driver",
        "role_ids": ["driver", "operations_manager"],
        "selected_workspace": "operations_manager",
        "status": "active",
    })
    assert user["role"] == "driver"
    assert user["selected_workspace"] == "operations_manager"
    assert {role["code"] for role in user["roles"]} == {"driver", "operations_manager"}
    assert all({"id", "code", "name", "active"}.issubset(role) for role in user["roles"])
    assert "delivery.execute" in user["permissions"]
    assert "maintenance.manage" in user["permissions"]


def test_session_token_carries_active_workspace_and_all_role_codes():
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-long-enough-for-workspace-token"
    JWTManager(app)
    from services.auth_service import create_session_token
    with app.app_context():
        token = create_session_token({
            "id": "user-1",
            "role": "driver",
            "role_ids": ["driver", "operations_manager", "finance_officer"],
            "selected_workspace": "operations_manager",
            "full_name": "Multi Role User",
        })
        claims = decode_token(token)
    assert claims["role"] == "operations_manager"
    assert claims["selected_workspace"] == "operations_manager"
    assert claims["roles"] == ["driver", "operations_manager", "finance_officer"]


def test_workspace_switch_persists_selection_returns_canonical_user_and_rotates_token():
    app = Flask(__name__)
    app.config.update(JWT_SECRET_KEY="test-secret-long-enough-for-workspace-route", MONGO_URI="mongodb://test")
    JWTManager(app)
    app.register_blueprint(rbac_routes.rbac_bp, url_prefix="/api/rbac")
    db = mongomock.MongoClient().workspace_switch
    user_id = db.users.insert_one({
        "full_name": "Multi Role Driver",
        "role": "driver",
        "role_ids": ["driver", "operations_manager"],
        "selected_workspace": "driver",
        "status": "active",
        "must_change_password": False,
    }).inserted_id
    with app.app_context():
        from flask_jwt_extended import create_access_token
        token = create_access_token(identity=str(user_id), additional_claims={"role": "driver"})
    collection = lambda name: db[name]
    with patch.object(rbac_routes, "get_collection", side_effect=collection), patch.object(decorators, "get_collection", side_effect=collection), patch.object(rbac_service, "get_collection", side_effect=collection), patch.object(rbac_routes, "write_audit"):
        response = app.test_client().post(
            "/api/rbac/workspace",
            json={"role": "operations_manager"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert db.users.find_one({"_id": user_id})["selected_workspace"] == "operations_manager"
    assert data["user"]["role"] == "driver"
    assert data["user"]["selected_workspace"] == "operations_manager"
    assert {role["code"] for role in data["user"]["roles"]} == {"driver", "operations_manager"}
    with app.app_context():
        claims = decode_token(data["access_token"])
    assert claims["role"] == "operations_manager"
