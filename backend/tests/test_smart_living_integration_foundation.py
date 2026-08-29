import sys
import time
import re
from pathlib import Path
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import services.branch_access_service as branch_access
import services.auth_service as auth
import services.rbac_service as rbac
import services.smart_living_delivery_service as delivery
import services.smart_living_integration_service as integration
import services.movement_source_service as movement_source
import services.operational_task_service as operational_tasks
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from routes.smart_living_integration import smart_living_integration_bp
from routes import register_blueprints
from routes.auth import auth_bp
import utils.decorators as decorators
from utils.api_error import ApiError
from utils.errors import register_error_handlers
from werkzeug.security import check_password_hash, generate_password_hash


@pytest.fixture
def domain():
    db = mongomock.MongoClient().flux_integration
    branch_a, branch_b = ObjectId(), ObjectId()
    admin, manager_a, manager_b, agent_a, agent_b = (ObjectId() for _ in range(5))
    db.branches.insert_many([
        {"_id": branch_a, "code": "A", "name": "Branch A", "status": "active"},
        {"_id": branch_b, "code": "B", "name": "Branch B", "status": "active"},
    ])
    db.users.insert_many([
        {"_id": admin, "role": "admin", "status": "active"},
        {"_id": manager_a, "role": "branch_manager", "status": "active", "primary_branch_id": branch_a, "allowed_branch_ids": [branch_a]},
        {"_id": manager_b, "role": "branch_manager", "status": "active", "primary_branch_id": branch_b, "allowed_branch_ids": [branch_b]},
        {"_id": agent_a, "role": "field_agent", "status": "active", "primary_branch_id": branch_a, "allowed_branch_ids": [branch_a]},
        {"_id": agent_b, "role": "field_agent", "status": "active", "primary_branch_id": branch_b, "allowed_branch_ids": [branch_b]},
    ])
    notification_calls = []
    patches = [
        patch.object(auth, "get_collection", side_effect=lambda name: db[name]),
        patch.object(integration, "get_collection", side_effect=lambda name: db[name]),
        patch.object(delivery, "get_collection", side_effect=lambda name: db[name]),
        patch.object(branch_access, "get_collection", side_effect=lambda name: db[name]),
        patch.object(rbac, "get_collection", side_effect=lambda name: db[name]),
        patch.object(decorators, "get_collection", side_effect=lambda name: db[name]),
        patch.object(movement_source, "get_collection", side_effect=lambda name: db[name]),
        patch.object(operational_tasks, "get_collection", side_effect=lambda name: db[name]),
        patch.object(delivery, "create_notification", side_effect=lambda *args, **kwargs: notification_calls.append((args, kwargs))),
    ]
    for item in patches:
        item.start()
    delivery.ensure_indexes(); integration.ensure_indexes()
    yield {"db": db, "a": branch_a, "b": branch_b, "admin": admin, "manager_a": manager_a, "manager_b": manager_b, "agent_a": agent_a, "agent_b": agent_b, "notifications": notification_calls}
    for item in reversed(patches):
        item.stop()


def provisioning_discovery(domain, agent_id="SL-NEW-1", name="Ama Boateng", relationship_status="resolved"):
    domain["db"].branches.update_one({"_id": domain["a"]}, {"$set": {"manager_id": domain["manager_a"]}})
    integration.create_mapping("branch", {
        "external_code": "Smart Branch A", "external_display_name": "Smart Branch A", "fleetops_id": str(domain["a"]),
    }, str(domain["admin"]))
    integration.create_mapping("manager", {
        "external_id": "SL-MANAGER-A", "external_display_name": "Smart Manager A", "fleetops_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    relationship = {
        "status": relationship_status, "reason": None if relationship_status == "resolved" else "conflicting_manager",
        "agent_id": agent_id, "agent_display_name": name,
        "manager_id": "SL-MANAGER-A", "manager_display_name": "Smart Manager A",
        "external_branch": "Smart Branch A", "fleetops_branch_id": None,
    }
    result = domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": agent_id.casefold(),
        "external_id": agent_id, "external_display_name": name, "display_name_status": "resolved" if name else "unavailable",
        "branch_name": "Smart Branch A", "currently_observed": True, "relationship": relationship,
    })
    return result.inserted_id


def manager_discovery(domain, manager_id="SL-MGR-1", name="Akosua Manager", branch="Smart Branch A", branch_keys=None, review_codes=None, **extra):
    result = domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "manager", "external_key": manager_id.casefold(),
        "external_id": manager_id, "external_display_name": name, "branch_name": branch,
        "branch_keys": branch_keys if branch_keys is not None else ([integration.normalize_branch_key(branch)] if branch else []),
        "review_codes": review_codes or [],
        "currently_observed": True, **extra,
    })
    return result.inserted_id


def assert_manager_contract(item):
    assert set(item) >= {
        "discovery_id", "source_id", "manager_name", "email", "phone", "source_branch",
        "source_branch_options", "branch_id", "branch_name", "fleetops_user_id", "fleetops_user_name",
        "match_method", "name_resolution_source", "account_status", "mapping_status", "status", "error_codes", "candidate_ids", "candidates",
    }
    assert isinstance(item["source_branch_options"], list)
    assert isinstance(item["error_codes"], list)
    assert isinstance(item["candidate_ids"], list)
    assert isinstance(item["candidates"], list)
    assert item["status"] in {"needs_review", "ready_to_link", "ready_to_create", "linked"}


def test_manager_existing_match_preserves_password_links_both_directions_and_reevaluates(domain):
    integration.create_mapping("branch", {"external_code": " Smart---Branch A ", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    password_hash = generate_password_hash("Existing@Password1")
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {
        "full_name": "Akosua Manager", "email": "akosua@example.com", "password_hash": password_hash,
    }})
    discovery_id = manager_discovery(domain, email="AKOSUA@example.com")
    agent_id = domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "sl-agent-waiting",
        "external_id": "SL-AGENT-WAITING", "external_display_name": "Waiting Agent", "branch_name": "Smart Branch A",
        "currently_observed": True, "relationship": {"status": "resolved", "agent_id": "SL-AGENT-WAITING",
            "agent_display_name": "Waiting Agent", "manager_id": "SL-MGR-1", "manager_display_name": "Akosua Manager",
            "external_branch": "smart branch a"},
    }).inserted_id
    preview = integration.preview_manager_provisioning(str(domain["admin"]))
    assert preview["counts"]["ready_to_link"] == 1
    assert_manager_contract(preview["managers"][0])
    result = integration.match_manager_provisioning(str(discovery_id), {}, str(domain["admin"]))
    assert result["agent_reevaluation"]["after"]["eligible"] == 1
    assert_manager_contract(result["manager"])
    branch = domain["db"].branches.find_one({"_id": domain["a"]}); user = domain["db"].users.find_one({"_id": domain["manager_a"]})
    assert branch["manager_id"] == domain["manager_a"] and user["primary_branch_id"] == domain["a"]
    assert user["smartliving_manager_id"] == "SL-MGR-1" and check_password_hash(user["password_hash"], "Existing@Password1")
    assert integration._provisioning_agent(domain["db"].integration_discoveries.find_one({"_id": agent_id}))["status"] == "eligible"


def test_missing_manager_creation_is_idempotent_and_requires_first_login_password_change(domain):
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    discovery_id = manager_discovery(domain, manager_id="SL-MGR-NEW", name="New Branch Manager")
    app = Flask(__name__); app.config.update(JWT_SECRET_KEY="manager-login-test-secret-at-least-32-bytes")
    JWTManager(app)
    with app.app_context():
        first = integration.create_manager_provisioning(str(discovery_id), {"approved": True}, str(domain["admin"]))
        second = integration.create_manager_provisioning(str(discovery_id), {"approved": True}, str(domain["admin"]))
        user = domain["db"].users.find_one({"smartliving_manager_id": "SL-MGR-NEW"})
        assert first["manager"]["status"] == "linked" and second["manager"]["status"] == "linked"
        assert first["manager"]["fleetops_username"] == "new.manager"
        assert first["manager"]["fleetops_roles"] == "Branch Manager"
        assert first["manager"]["fleetops_status"] == "active"
        assert domain["db"].users.count_documents({"smartliving_manager_id": "SL-MGR-NEW"}) == 1
        assert user["role"] == "branch_manager" and user["must_change_password"] is True and user["default_password_active"] is True
        assert user["username"] == "new.manager" and "fleet@12345" not in str(user)
        logged_in = auth.authenticate_user(user["username"], "fleet@12345")["user"]
        assert logged_in["must_change_password"] is True and logged_in["primary_branch_id"] == str(domain["a"])
        assert branch_access.branch_ids_for_user(user) == {domain["a"]}
        assert rbac.effective_data_scope(user) == "PRIMARY_BRANCH"
        assert rbac.user_has_permission(user, "branch_operations.view") is True
        auth.change_own_password(str(user["_id"]), "fleet@12345", "Changed@123")
        assert auth.authenticate_user(user["username"], "Changed@123")["user"]["must_change_password"] is False


def test_manager_create_uses_resolved_record_without_agent_rescan_or_global_matching(domain):
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    discovery_id = manager_discovery(domain, manager_id="SL-MGR-FAST", name="Fast Manager")
    domain["db"].integration_discoveries.insert_many([{
        "source_system": "smartliving", "discovery_type": "agent", "external_key": f"unrelated-{index}",
        "external_id": f"UNRELATED-{index}", "external_display_name": f"Unrelated Agent {index}",
        "branch_name": "Smart Branch A", "currently_observed": True,
    } for index in range(1000)])
    app = Flask(__name__); app.config.update(JWT_SECRET_KEY="manager-performance-test-secret-32"); JWTManager(app)
    with app.app_context(), \
         patch.object(integration, "_reevaluate_branch_agents") as reevaluate, \
         patch.object(integration, "_manager_item") as global_match, \
         patch.object(integration, "discover_source_values") as rescan, \
         patch.object(integration, "fetch_source_records") as external_fetch:
        started = time.perf_counter()
        first = integration.create_manager_provisioning(str(discovery_id), {"approved": True}, str(domain["admin"]))
        duration = time.perf_counter() - started
        second = integration.create_manager_provisioning(str(discovery_id), {"approved": True}, str(domain["admin"]))
    assert duration < 2.0
    assert first["manager"]["status"] == second["manager"]["status"] == "linked"
    assert domain["db"].users.count_documents({"smartliving_manager_id": "SL-MGR-FAST"}) == 1
    reevaluate.assert_not_called(); global_match.assert_not_called(); rescan.assert_not_called(); external_fetch.assert_not_called()


def test_manager_review_resolves_name_and_branch_then_recomputes_ready_to_create(domain):
    discovery_id = manager_discovery(
        domain, manager_id="SL-MGR-REVIEW", name=None, branch=None,
        branch_keys=[], review_codes=["MISSING_NAME", "UNRESOLVED_BRANCH"],
    )
    before = integration.preview_manager_provisioning(str(domain["admin"]))
    assert before["counts"] == {"linked": 0, "ready_to_link": 0, "ready_to_create": 0, "needs_review": 1}
    assert_manager_contract(before["managers"][0])
    resolved = integration.match_manager_provisioning(str(discovery_id), {
        "manager_name": "Confirmed Manager", "branch_id": str(domain["a"]), "resolve_only": True,
    }, str(domain["admin"]))
    assert resolved["manager"]["status"] == "ready_to_create"
    assert resolved["manager"]["manager_name"] == "Confirmed Manager"
    assert resolved["manager"]["branch_name"] == "Branch A"


def test_missing_name_uses_only_exact_source_linked_user_and_offers_link_existing(domain):
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {
        "full_name": "Authoritative Existing Manager", "username": "authoritative.manager",
        "smartliving_manager_id": "SL-MGR-NAMELESS",
    }})
    discovery_id = manager_discovery(
        domain, manager_id="SL-MGR-NAMELESS", name=None,
        review_codes=["MISSING_NAME"],
    )
    item = integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0]
    assert item["manager_name"] == "Authoritative Existing Manager"
    assert item["name_resolution_source"] == "fleetops_source_id"
    assert item["status"] == "ready_to_link" and item["error_codes"] == []
    linked = integration.match_manager_provisioning(str(discovery_id), {}, str(domain["admin"]))
    assert linked["manager"]["status"] == "linked"
    assert domain["db"].integration_mappings.find_one({"mapping_type": "manager", "external_key": "sl-mgr-nameless"})["fleetops_id"] == domain["manager_a"]
    resolution = domain["db"].integration_discoveries.find_one({"_id": discovery_id})["manager_provisioning_resolution"]
    assert resolution["manager_name"] == "Authoritative Existing Manager" and resolution["fleetops_user_id"] == domain["manager_a"]


def test_missing_name_shows_branch_manager_candidate_but_requires_explicit_name_and_link(domain):
    integration.create_mapping("branch", {"external_code": "Madina", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {"full_name": "Rebecca Asante"}})
    discovery_id = manager_discovery(domain, manager_id="SL-MADINA-UNKNOWN", name=None, branch="Madina", review_codes=["MISSING_NAME"])

    item = integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0]
    assert item["status"] == "needs_review" and item["mapping_status"] == "unlinked"
    assert item["manager_name"] is None and item["fleetops_user_id"] is None
    assert item["candidates"] == [{
        "id": str(domain["manager_a"]), "name": "Rebecca Asante", "role": "Branch Manager",
        "match_reason": "branch_access", "username": None, "branch_id": str(domain["a"]), "branch_name": "Branch A",
    }]
    with pytest.raises(ApiError) as missing_name:
        integration.match_manager_provisioning(str(discovery_id), {"fleetops_user_id": str(domain["manager_a"])}, str(domain["admin"]))
    assert missing_name.value.errors[0]["code"] == "MISSING_NAME"

    linked = integration.match_manager_provisioning(str(discovery_id), {
        "manager_name": "Rebecca Asante", "fleetops_user_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    assert linked["manager"]["status"] == "linked"
    assert domain["db"].integration_mappings.count_documents({"mapping_type": "manager", "external_key": "sl-madina-unknown"}) == 1
    assert domain["db"].users.count_documents({"_id": domain["manager_a"]}) == 1


def test_role_conflicting_exact_name_also_shows_safe_branch_manager_link_candidate(domain):
    integration.create_mapping("branch", {"external_code": "Agormenya", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].users.update_one({"_id": domain["agent_a"]}, {"$set": {"full_name": "Doris A", "username": "doris.a"}})
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {"full_name": "Doris Mensah", "username": "dor12"}})
    discovery_id = manager_discovery(domain, manager_id="SL-DORIS", name="Doris A", branch="Agormenya")

    item = integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0]
    assert item["status"] == "needs_review" and item["error_codes"] == ["DUPLICATE_ACCOUNT"]
    assert {(row["name"], row["role"], row["match_reason"]) for row in item["candidates"]} == {
        ("Doris A", "Field Agent", "full_name"),
        ("Doris Mensah", "Branch Manager", "branch_access"),
    }
    linked = integration.match_manager_provisioning(str(discovery_id), {
        "fleetops_user_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    assert linked["manager"]["status"] == "linked" and linked["manager"]["fleetops_user_name"] == "Doris Mensah"
    assert domain["db"].users.count_documents({"full_name": {"$in": ["Doris A", "Doris Mensah"]}}) == 2


def test_same_stable_source_identity_links_manager_and_agent_to_one_multirole_account(domain):
    source_id = "SL-DORIS-SAME-ID"
    integration.create_mapping("branch", {"external_code": "Agormenya", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].users.update_one({"_id": domain["agent_a"]}, {"$set": {
        "full_name": "Doris A", "username": "doris.a", "password_hash": generate_password_hash("Existing@Password1"),
        "smartliving_agent_id": source_id, "role": "field_agent", "role_ids": ["field_agent"],
    }})
    integration.create_mapping("agent", {
        "external_id": source_id, "external_display_name": "Doris A", "fleetops_id": str(domain["agent_a"]),
    }, str(domain["admin"]))
    discovery_id = manager_discovery(domain, manager_id=source_id, name="Doris A", branch="Agormenya")
    before_users = domain["db"].users.count_documents({})

    preview = integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0]
    assert preview["status"] == "ready_to_link"
    assert preview["match_method"] == "cross_role_source_mapping"
    assert preview["fleetops_user_id"] == str(domain["agent_a"])
    assert preview["candidates"][0]["role"] == "Field Agent"

    first = integration.match_manager_provisioning(str(discovery_id), {}, str(domain["admin"]))
    repeated = integration.match_manager_provisioning(str(discovery_id), {}, str(domain["admin"]))
    user = domain["db"].users.find_one({"_id": domain["agent_a"]})
    assert first["manager"]["status"] == repeated["manager"]["status"] == "linked"
    assert first["manager"]["fleetops_username"] == "doris.a"
    assert first["manager"]["fleetops_roles"] == "Field Agent + Branch Manager"
    assert first["manager"]["fleetops_status"] == "active"
    assert rbac.user_role_codes(user) == ["field_agent", "branch_manager"]
    assert user["smartliving_agent_id"] == user["smartliving_manager_id"] == source_id
    assert domain["db"].integration_mappings.count_documents({"external_key": source_id.casefold()}) == 2
    assert {row["fleetops_id"] for row in domain["db"].integration_mappings.find({"external_key": source_id.casefold()})} == {domain["agent_a"]}
    assert domain["db"].users.count_documents({}) == before_users
    assert domain["db"].branches.find_one({"_id": domain["a"]})["manager_id"] == domain["agent_a"]
    assert branch_access.branch_ids_for_user(user) == {domain["a"]}
    assert rbac.effective_data_scope(user) == "PRIMARY_BRANCH"
    assert rbac.user_has_permission(user, "branch_operations.manage_team") is True
    assert rbac.user_has_permission(user, "delivery_routes.execute") is True
    assert domain["db"].audit_logs.count_documents({"action": "smartliving_identity_role_linked", "target_id": str(domain["agent_a"])}) == 1

    app = Flask(__name__); app.config.update(JWT_SECRET_KEY="multi-role-login-test-secret-32-bytes"); JWTManager(app)
    with app.app_context():
        logged_in = auth.authenticate_user("doris.a", "Existing@Password1")["user"]
    assert logged_in["role_ids"] == ["field_agent", "branch_manager"]


def test_same_stable_source_identity_cannot_map_across_two_fleetops_users(domain):
    source_id = "SL-ONE-PERSON"
    domain["db"].users.update_one(
        {"_id": domain["agent_a"]}, {"$set": {"role_ids": ["field_agent", "branch_manager"]}},
    )
    integration.create_mapping("agent", {
        "external_id": source_id, "fleetops_id": str(domain["agent_a"]),
    }, str(domain["admin"]))

    with pytest.raises(ApiError, match="other role"):
        integration.create_mapping("manager", {
            "external_id": source_id, "fleetops_id": str(domain["manager_a"]),
        }, str(domain["admin"]))

    created = integration.create_mapping("manager", {
        "external_id": source_id, "fleetops_id": str(domain["agent_a"]),
    }, str(domain["admin"]))
    assert created["fleetops_id"] == str(domain["agent_a"])


def test_manager_retry_replaces_only_an_inactive_legacy_branch_owner(domain):
    source_id = "SL-RETIRED-DUPLICATE"
    integration.create_mapping("branch", {"external_code": "Agormenya", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    retired = domain["db"].users.insert_one({
        "full_name": "Retired Duplicate", "role": "branch_manager", "role_ids": ["branch_manager"],
        "status": "inactive", "primary_branch_id": domain["a"], "allowed_branch_ids": [domain["a"]],
    }).inserted_id
    domain["db"].branches.update_one({"_id": domain["a"]}, {"$set": {
        "manager_id": retired, "manager_name": "Retired Duplicate", "manager_ids": [retired],
    }})
    domain["db"].users.update_one({"_id": domain["agent_a"]}, {"$set": {
        "full_name": "Canonical Multi Role", "smartliving_agent_id": source_id,
    }})
    integration.create_mapping("agent", {
        "external_id": source_id, "external_display_name": "Canonical Multi Role",
        "fleetops_id": str(domain["agent_a"]),
    }, str(domain["admin"]))
    discovery_id = manager_discovery(domain, manager_id=source_id, name="Canonical Multi Role", branch="Agormenya")

    first = integration.match_manager_provisioning(str(discovery_id), {}, str(domain["admin"]))
    repeated = integration.match_manager_provisioning(str(discovery_id), {}, str(domain["admin"]))

    branch = domain["db"].branches.find_one({"_id": domain["a"]})
    assert first["manager"]["status"] == repeated["manager"]["status"] == "linked"
    assert branch["manager_id"] == domain["agent_a"]
    assert branch["manager_name"] == "Canonical Multi Role"
    assert branch["manager_ids"] == [domain["agent_a"]]


def test_agent_provisioning_reuses_same_source_manager_account_and_adds_field_agent_role(domain):
    source_id = "SL-DUAL-ROLE"
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {
        "full_name": "Dual Role Person", "username": "dual.role", "smartliving_manager_id": source_id,
        "role": "branch_manager", "role_ids": ["branch_manager"],
    }})
    integration.create_mapping("manager", {
        "external_id": source_id, "external_display_name": "Dual Role Person", "fleetops_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    discovery_id = domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": source_id.casefold(),
        "external_id": source_id, "external_display_name": "Dual Role Person", "currently_observed": True,
        "relationship": {"status": "resolved", "reason": None, "agent_id": source_id,
            "agent_display_name": "Dual Role Person", "manager_id": source_id,
            "manager_display_name": "Dual Role Person", "direct_branch": "Smart Branch A",
            "direct_branch_options": ["Smart Branch A"], "manager_branch_options": ["Smart Branch A"]},
    }).inserted_id
    before_users = domain["db"].users.count_documents({})

    preview = integration.preview_agent_provisioning(str(domain["admin"]))["agents"][0]
    assert preview["status"] == "eligible" and preview["fleetops_user_name"] == "Dual Role Person"
    first = integration.provision_agents({"discovery_ids": [str(discovery_id)]}, str(domain["admin"]))
    repeated = integration.provision_agents({"discovery_ids": [str(discovery_id)]}, str(domain["admin"]))
    user = domain["db"].users.find_one({"_id": domain["manager_a"]})
    assert first["provisioned"] == 1 and first["results"][0]["status"] == "existing"
    assert first["results"][0]["username"] == "dual.role"
    assert first["results"][0]["role"] == "Branch Manager + Field Agent"
    assert repeated["duplicate"] == 1
    assert rbac.user_role_codes(user) == ["branch_manager", "field_agent"]
    assert user["smartliving_manager_id"] == user["smartliving_agent_id"] == source_id
    assert domain["db"].users.count_documents({}) == before_users
    assert domain["db"].integration_mappings.count_documents({"external_key": source_id.casefold()}) == 2


def test_hq_manager_aliases_use_confirmed_hq_mapping_without_guessing_name(domain):
    integration.create_mapping("branch", {"external_code": "HQ", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    discovery_id = manager_discovery(
        domain, manager_id="SL-HQ-NAMELESS", name=None, branch=None,
        branch_keys=["head quater", "head quaters", "headquarters", "hq"],
        review_codes=["BRANCH_CONFLICT", "MISSING_NAME"],
    )
    item = integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0]
    assert item["branch_id"] == str(domain["a"]) and item["branch_name"] == "Branch A"
    assert item["manager_name"] is None and item["error_codes"] == ["MISSING_NAME"]
    assert item["status"] == "needs_review"


def test_manager_name_extraction_reads_explicit_nested_name_fields_only():
    assert integration._source_manager_name({}, {}, {"manager": {"full_name": "Readable Manager"}}) == "Readable Manager"
    assert integration._source_manager_name({"manager_display_name": "Display Manager"}, {}, {}) == "Display Manager"
    assert integration._source_manager_name({"manager_id": "RAW-ID", "manager_branch": "HQ"}, {}, {}) == ""


def test_duplicate_manager_candidates_require_admin_selection_and_link_only_selected(domain):
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].users.update_many(
        {"_id": {"$in": [domain["manager_a"], domain["manager_b"]]}},
        {"$set": {"full_name": "Duplicate Manager"}},
    )
    discovery_id = manager_discovery(domain, manager_id="SL-MGR-DUP", name="Duplicate Manager")
    item = integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0]
    assert_manager_contract(item)
    assert item["status"] == "needs_review" and item["error_codes"] == ["AMBIGUOUS_MANAGER"]
    assert {candidate["id"] for candidate in item["candidates"]} == {str(domain["manager_a"]), str(domain["manager_b"])}
    linked = integration.match_manager_provisioning(str(discovery_id), {"fleetops_user_id": str(domain["manager_a"])}, str(domain["admin"]))
    assert linked["manager"]["status"] == "linked"
    assert domain["db"].users.find_one({"_id": domain["manager_b"]}).get("smartliving_manager_id") is None


def test_manager_branch_conflict_is_structured_and_does_not_change_existing_account(domain):
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    original_hash = generate_password_hash("KeepMe@123")
    domain["db"].users.update_one({"_id": domain["manager_b"]}, {"$set": {"full_name": "Wrong Branch Manager", "password_hash": original_hash}})
    discovery_id = manager_discovery(domain, manager_id="SL-MGR-CONFLICT", name="Wrong Branch Manager")
    assert_manager_contract(integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0])
    with pytest.raises(ApiError) as caught:
        integration.match_manager_provisioning(str(discovery_id), {"fleetops_user_id": str(domain["manager_b"])}, str(domain["admin"]))
    assert caught.value.errors[0]["code"] == "BRANCH_CONFLICT"
    unchanged = domain["db"].users.find_one({"_id": domain["manager_b"]})
    assert unchanged["primary_branch_id"] == domain["b"] and unchanged["password_hash"] == original_hash


def test_persisted_source_mapping_is_reported_separately_from_branch_conflict(domain):
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].users.update_one({"_id": domain["manager_b"]}, {"$set": {"full_name": "Mapped Other Branch"}})
    integration.create_mapping("manager", {"external_id": "SL-MAPPED-CONFLICT", "fleetops_id": str(domain["manager_b"])}, str(domain["admin"]))
    manager_discovery(domain, manager_id="SL-MAPPED-CONFLICT", name="Mapped Other Branch")

    item = integration.preview_manager_provisioning(str(domain["admin"]))["managers"][0]
    assert item["mapping_status"] == "linked"
    assert item["status"] == "needs_review" and "BRANCH_CONFLICT" in item["error_codes"]
    assert {(row["name"], row["match_reason"]) for row in item["candidates"]} == {
        ("Mapped Other Branch", "source_mapping"),
        ("Name unavailable", "branch_access"),
    }


def test_hq_allows_multiple_individual_managers_without_overwriting_legacy_manager(domain):
    integration.create_mapping("branch", {"external_code": "HQ", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].branches.update_one({"_id": domain["a"]}, {"$set": {"name": "HQ"}})
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {"full_name": "HQ Manager One"}})
    domain["db"].users.update_one({"_id": domain["manager_b"]}, {"$set": {
        "full_name": "HQ Manager Two", "primary_branch_id": domain["a"], "allowed_branch_ids": [domain["a"]],
    }})
    first_id = manager_discovery(domain, manager_id="SL-HQ-MGR-1", name="HQ Manager One", branch="HQ")
    second_id = manager_discovery(domain, manager_id="SL-HQ-MGR-2", name="HQ Manager Two", branch="HQ")

    first = integration.match_manager_provisioning(str(first_id), {}, str(domain["admin"]))
    second = integration.match_manager_provisioning(str(second_id), {}, str(domain["admin"]))
    repeated = integration.match_manager_provisioning(str(second_id), {}, str(domain["admin"]))

    branch = domain["db"].branches.find_one({"_id": domain["a"]})
    assert first["manager"]["status"] == second["manager"]["status"] == repeated["manager"]["status"] == "linked"
    assert branch["manager_id"] == domain["manager_a"]
    assert set(branch["manager_ids"]) == {domain["manager_a"], domain["manager_b"]}
    assert domain["db"].integration_mappings.count_documents({"mapping_type": "manager"}) == 2
    assert domain["db"].users.count_documents({"_id": {"$in": [domain["manager_a"], domain["manager_b"]]}}) == 2
    audit = domain["db"].audit_logs.find_one({"action": "smartliving_manager_matched", "target_id": str(domain["manager_b"])})
    assert audit["actor_user_id"] == domain["admin"]


def test_agent_conflict_exposes_both_branches_and_confirmed_manager_resolution(domain):
    integration.create_mapping("branch", {"external_code": "Agent Branch", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    integration.create_mapping("branch", {"external_code": "Manager Branch", "fleetops_id": str(domain["b"])}, str(domain["admin"]))
    domain["db"].branches.update_one({"_id": domain["a"]}, {"$set": {"manager_ids": [domain["manager_a"]]}})
    integration.create_mapping("manager", {"external_id": "SL-MANAGER-A", "fleetops_id": str(domain["manager_b"])}, str(domain["admin"]))
    discovery_id = domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "sl-agent-conflict",
        "external_id": "SL-AGENT-CONFLICT", "external_display_name": "Conflict Agent", "currently_observed": True,
        "branch_name": "Agent Branch", "relationship": {
            "status": "conflicting", "reason": "conflicting_agent_manager_branch",
            "agent_id": "SL-AGENT-CONFLICT", "agent_display_name": "Conflict Agent",
            "manager_id": "SL-MANAGER-A", "manager_display_name": "HQ Manager One",
            "direct_branch": "Agent Branch", "manager_branch": "Manager Branch",
            "direct_branch_options": ["Agent Branch"], "manager_branch_options": ["Manager Branch"],
            "external_branch": "Agent Branch",
        },
    }).inserted_id

    before = integration.preview_agent_provisioning(str(domain["admin"]))["agents"][0]
    assert before["status"] == "needs_review" and "BRANCH_CONFLICT" in before["error_codes"]
    assert before["source_direct_branch"] == "Agent Branch"
    assert before["source_manager_branch"] == "Manager Branch"
    resolved = integration.resolve_agent_provisioning(str(discovery_id), {
        "agent_name": "Conflict Agent", "branch_id": str(domain["a"]), "manager_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    assert resolved["status"] == "eligible" and resolved["manager_name"] == domain["db"].users.find_one({"_id": domain["manager_a"]}).get("full_name")
    audit = domain["db"].audit_logs.find_one({"action": "smartliving_agent_resolved", "target_id": str(discovery_id)})
    assert audit["actor_user_id"] == domain["admin"]


def test_confirmed_hq_aliases_reconcile_branch_but_never_supply_a_person_name(domain):
    integration.create_mapping("branch", {"external_code": "HQ", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    integration.create_mapping("branch", {"external_code": "Head Office", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].branches.update_one({"_id": domain["a"]}, {"$set": {"manager_ids": [domain["manager_a"]]}})
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {"full_name": "Confirmed HQ Manager"}})
    integration.create_mapping("manager", {"external_id": "SL-HQ-MANAGER", "fleetops_id": str(domain["manager_a"])}, str(domain["admin"]))
    domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "sl-hq-agent",
        "external_id": "SL-HQ-AGENT", "external_display_name": "HQ Agent", "currently_observed": True,
        "relationship": {
            "status": "conflicting", "reason": "conflicting_agent_manager_branch",
            "agent_id": "SL-HQ-AGENT", "agent_display_name": "HQ Agent",
            "manager_id": "SL-HQ-MANAGER", "manager_display_name": None,
            "direct_branch": "HQ", "manager_branch": "Head Office", "external_branch": "HQ",
            "direct_branch_options": ["HQ"], "manager_branch_options": ["Head Office"],
        },
    })

    item = integration.preview_agent_provisioning(str(domain["admin"]))["agents"][0]
    assert item["status"] == "eligible" and item["branch_name"] == "Branch A", item
    assert item["manager_name"] == "Confirmed HQ Manager"
    assert item["source_manager_name"] is None


def test_empty_manager_preview_has_canonical_arrays_null_safe_counts_and_active_branches(domain):
    preview = integration.preview_manager_provisioning(str(domain["admin"]))
    assert preview == {
        "contract_version": 1,
        "counts": {"linked": 0, "ready_to_link": 0, "ready_to_create": 0, "needs_review": 0},
        "managers": [],
        "branches": [{"id": str(domain["a"]), "name": "Branch A"}, {"id": str(domain["b"]), "name": "Branch B"}],
        "contract_errors": [],
    }


def test_smartliving_valid_agent_provisions_and_can_login_change_password_and_relogin(domain):
    discovery_id = provisioning_discovery(domain)
    preview = integration.preview_agent_provisioning(str(domain["admin"]))
    assert preview["counts"]["eligible"] == 1
    provisioned = integration.provision_agents({"discovery_ids": [str(discovery_id)]}, str(domain["admin"]))
    assert provisioned["preview_eligible"] == 1
    assert provisioned["created"] == provisioned["provisioned"] == 1
    assert provisioned["linked"] == provisioned["skipped"] == provisioned["failed"] == 0
    result = provisioned["results"][0]
    assert result["username"] == "ama.boateng"
    temporary_password = result["temporary_password"]
    assert result["outcome"] == "created" and result["credential_available_once"] is True
    assert temporary_password == "fleet@12345"
    assert result["role"] == "Field Agent" and result["account_status"] == "active"
    user = domain["db"].users.find_one({"smartliving_agent_id": "SL-NEW-1"})
    assert user["role"] == "field_agent" and user["role_ids"] == ["field_agent"]
    assert user["primary_branch_id"] == domain["a"] and user["manager_id"] == domain["manager_a"]
    assert branch_access.branch_ids_for_user(user) == {domain["a"]}
    assert rbac.effective_data_scope(user) == "ASSIGNED_RECORDS"
    assert rbac.user_has_permission(user, "deliveries.view_assigned") is True
    assert rbac.user_has_permission(user, "users.manage") is False
    assert user["must_change_password"] is True and user["default_password_active"] is True
    assert temporary_password not in str(user)
    mapping = domain["db"].integration_mappings.find_one({"mapping_type": "agent", "external_key": "sl-new-1"})
    assert mapping["fleetops_id"] == user["_id"]

    app = Flask(__name__); app.config["JWT_SECRET_KEY"] = "smartliving-login-test-secret-32"; JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    register_error_handlers(app)
    with app.app_context():
        client = app.test_client()
        first_response = client.post("/api/auth/login", json={"identifier": "  AMA.BoAtEnG  ", "password": temporary_password})
        assert first_response.status_code == 200
        first_login = first_response.get_json()["data"]
        assert first_login["user"]["must_change_password"] is True
        assert first_login["user"]["default_password_active"] is True
        assert first_login["user"]["role"] == "field_agent"
        assert first_login["user"]["primary_branch_id"] == str(domain["a"])
        assert client.post("/api/auth/logout", headers={"Authorization": f"Bearer {first_login['access_token']}"}).status_code == 200
        relogin = client.post("/api/auth/login", json={"identifier": "ama.boateng", "password": temporary_password})
        assert relogin.status_code == 200
        changed = auth.change_own_password(str(user["_id"]), temporary_password, "NewSecure@123")
        assert changed["must_change_password"] is False and changed["default_password_active"] is False
        new_login = client.post("/api/auth/login", json={"identifier": "AMA.BOATENG", "password": "NewSecure@123"})
        assert new_login.status_code == 200 and new_login.get_json()["data"]["user"]["role"] == "field_agent"
        refreshed = auth.get_user_by_id(str(user["_id"]))
        assert refreshed["role"] == "field_agent" and refreshed["primary_branch_id"] == str(domain["a"])


def test_existing_mixed_case_username_login_is_case_insensitive_without_renaming(domain):
    user_id = ObjectId()
    domain["db"].users.insert_one({
        "_id": user_id,
        "full_name": "Legacy Field Agent",
        "username": "Legacy.Agent",
        "password_hash": generate_password_hash("LegacyPass@123"),
        "role": "field_agent",
        "role_ids": ["field_agent"],
        "status": "active",
    })
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "legacy-case-login-test-secret-32"
    JWTManager(app)
    with app.app_context():
        logged_in = auth.authenticate_user("  LEGACY.AGENT ", "LegacyPass@123")
    assert logged_in["user"]["id"] == str(user_id)
    assert domain["db"].users.find_one({"_id": user_id})["username"] == "Legacy.Agent"


def test_username_creation_rejects_case_only_duplicate(domain):
    domain["db"].users.insert_one({
        "_id": ObjectId(), "full_name": "Existing Agent", "username": "Case.Agent",
        "role": "field_agent", "role_ids": ["field_agent"], "status": "active",
    })
    with pytest.raises(ApiError) as error:
        auth.create_user({
            "full_name": "Other Agent", "username": "case.agent", "phone": "+233201234567",
            "password": "Temporary@123", "status": "active",
        }, "field_agent")
    assert error.value.status_code == 409


def test_legacy_case_only_username_collision_is_not_authenticated_ambiguously(domain):
    for username in ("Duplicate.Agent", "duplicate.agent"):
        domain["db"].users.insert_one({
            "_id": ObjectId(), "full_name": username, "username": username,
            "password_hash": generate_password_hash("SamePass@123"),
            "role": "field_agent", "role_ids": ["field_agent"], "status": "active",
        })
    with pytest.raises(ApiError) as error:
        auth.authenticate_user("DUPLICATE.AGENT", "SamePass@123")
    assert error.value.status_code == 401


def test_agent_temporary_password_uses_explicit_deployment_default():
    app = Flask(__name__)
    app.config["SMARTLIVING_TEMPORARY_PASSWORD"] = "fleet@12345"
    with app.app_context():
        assert integration._agent_temporary_password() == "fleet@12345"


def test_smartliving_existing_agent_retry_does_not_duplicate(domain):
    discovery_id = provisioning_discovery(domain, agent_id="SL-DUP-1", name="Kojo Mensah")
    first = integration.provision_agents({"discovery_ids": [str(discovery_id)]}, str(domain["admin"]))
    second = integration.provision_agents({"discovery_ids": [str(discovery_id)]}, str(domain["admin"]))
    assert first["provisioned"] == 1
    assert second["duplicate"] == second["skipped"] == 1 and second["provisioned"] == 0
    assert "temporary_password" not in second["results"][0]
    assert domain["db"].users.count_documents({"smartliving_agent_id": "SL-DUP-1"}) == 1
    assert domain["db"].integration_mappings.count_documents({"mapping_type": "agent", "external_key": "sl-dup-1"}) == 1


def test_pending_never_logged_in_agent_credentials_can_be_reissued_once(domain):
    discovery_id = provisioning_discovery(domain, agent_id="SL-LOST-CREDENTIAL", name="Lost Credential")
    created = integration.provision_agents({"discovery_ids": [str(discovery_id)]}, str(domain["admin"]))
    old_password = created["results"][0]["temporary_password"]
    user = domain["db"].users.find_one({"smartliving_agent_id": "SL-LOST-CREDENTIAL"})
    old_hash = user["password_hash"]
    domain["db"].users.update_one({"_id": user["_id"]}, {"$set": {"credential_recovery_required": True}})

    reissued = integration.reissue_pending_agent_credentials({"user_ids": [str(user["_id"])]}, str(domain["admin"]))
    new_password = reissued["credentials"][0]["temporary_password"]
    refreshed = domain["db"].users.find_one({"_id": user["_id"]})
    assert reissued["reissued"] == 1 and old_password == new_password == "fleet@12345"
    assert check_password_hash(refreshed["password_hash"], new_password)
    assert refreshed["password_hash"] != old_hash
    assert new_password not in str(refreshed)
    assert "credential_recovery_required" not in refreshed

    domain["db"].users.update_one({"_id": user["_id"]}, {"$set": {"last_login": integration.now_utc()}})
    protected = integration.reissue_pending_agent_credentials({"user_ids": [str(user["_id"])]}, str(domain["admin"]))
    assert protected["reissued"] == 0 and protected["skipped"] == 1


def test_agent_exact_contact_links_existing_account_but_name_only_requires_confirmation(domain):
    contact_id = provisioning_discovery(domain, agent_id="SL-CONTACT", name="Contact Match")
    domain["db"].users.update_one({"_id": domain["agent_a"]}, {"$set": {
        "full_name": "Existing Contact", "email": "contact@example.com",
    }})
    domain["db"].integration_discoveries.update_one({"_id": contact_id}, {"$set": {"email": "CONTACT@example.com"}})

    preview = integration.preview_agent_provisioning(str(domain["admin"]))["agents"][0]
    assert preview["status"] == "eligible" and preview["identity_match_method"] == "contact"
    linked = integration.provision_agents({"discovery_ids": [str(contact_id)]}, str(domain["admin"]))
    assert linked["linked"] == 1 and linked["created"] == 0
    assert domain["db"].users.count_documents({"smartliving_agent_id": "SL-CONTACT"}) == 1

    name_id = domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "sl-name-only",
        "external_id": "SL-NAME-ONLY", "external_display_name": "Existing Contact", "currently_observed": True,
        "relationship": {"status": "resolved", "agent_id": "SL-NAME-ONLY", "agent_display_name": "Existing Contact",
            "manager_id": "SL-MANAGER-A", "manager_display_name": "Smart Manager A", "external_branch": "Smart Branch A"},
    }).inserted_id
    name_item = next(item for item in integration.preview_agent_provisioning(str(domain["admin"]))["agents"] if item["discovery_id"] == str(name_id))
    assert name_item["status"] == "needs_review" and name_item["error_codes"] == ["AMBIGUOUS_IDENTITY"]
    skipped = integration.provision_agents({"discovery_ids": [str(name_id)]}, str(domain["admin"]))
    assert skipped["skipped"] == 1 and domain["db"].users.count_documents({"smartliving_agent_id": "SL-NAME-ONLY"}) == 0


def test_smartliving_needs_review_resolution_fixes_data_and_becomes_eligible(domain):
    discovery_id = provisioning_discovery(domain, agent_id="SL-REVIEW-1", name="", relationship_status="conflicting")
    before = integration.preview_agent_provisioning(str(domain["admin"]))
    assert before["counts"]["needs_review"] == 1
    resolved = integration.resolve_agent_provisioning(str(discovery_id), {
        "agent_name": "Efua Owusu", "branch_id": str(domain["a"]), "manager_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    assert resolved["status"] == "eligible" and resolved["reasons"] == []
    stored = domain["db"].integration_discoveries.find_one({"_id": discovery_id})
    assert stored["provisioning_resolution"]["resolved_by"] == domain["admin"]
    assert stored["relationship"]["status"] == "resolved"
    provisioned = integration.provision_agents({"discovery_ids": [str(discovery_id)]}, str(domain["admin"]))
    assert provisioned["provisioned"] == 1


def test_agent_bulk_returns_created_linked_skipped_failed_and_continues(domain):
    created_id = provisioning_discovery(domain, agent_id="SL-BULK-CREATE", name="Create Agent")
    def add_discovery(agent_id, name, relationship_status="resolved"):
        return domain["db"].integration_discoveries.insert_one({
            "source_system": "smartliving", "discovery_type": "agent", "external_key": agent_id.casefold(),
            "external_id": agent_id, "external_display_name": name, "currently_observed": True,
            "relationship": {"status": relationship_status, "agent_id": agent_id, "agent_display_name": name,
                "manager_id": "SL-MANAGER-A", "manager_display_name": "Smart Manager A",
                "direct_branch": "Smart Branch A", "direct_branch_options": ["Smart Branch A"],
                "manager_branch_options": ["Smart Branch A"]},
        }).inserted_id
    linked_id = add_discovery("SL-BULK-LINK", "Existing Agent")
    skipped_id = add_discovery("SL-BULK-SKIP", "", "conflicting")
    existing_id = domain["db"].users.insert_one({
        "full_name": "Existing Agent", "username": "existing.agent", "role": "branch_manager",
        "role_ids": ["branch_manager"], "status": "active", "primary_branch_id": domain["a"],
        "allowed_branch_ids": [domain["a"]], "smartliving_manager_id": "SL-BULK-LINK",
    }).inserted_id
    integration.create_mapping("manager", {
        "external_id": "SL-BULK-LINK", "fleetops_id": str(existing_id),
    }, str(domain["admin"]))

    original = integration._provision_one
    def provision_or_fail(row, actor_id, context=None, username_override=None):
        if row.get("external_id") == "SL-BULK-FAIL":
            raise ApiError("simulated safe failure", status_code=409)
        return original(row, actor_id, context, username_override)

    failed_id = add_discovery("SL-BULK-FAIL", "Failed Agent")
    with patch.object(integration, "_provision_one", side_effect=provision_or_fail):
        result = integration.provision_agents({"discovery_ids": [
            str(created_id), str(linked_id), str(skipped_id), str(failed_id),
        ]}, str(domain["admin"]))

    assert {key: result[key] for key in ("created", "linked", "skipped", "failed")} == {
        "created": 1, "linked": 1, "skipped": 1, "failed": 1,
    }
    linked = domain["db"].users.find_one({"_id": existing_id})
    assert set(linked["role_ids"]) == {"branch_manager", "field_agent"}
    assert linked["manager_id"] == domain["manager_a"] and linked["smartliving_agent_id"] == "SL-BULK-LINK"
    assert "temporary_password" not in next(item for item in result["results"] if item["outcome"] == "linked")


def test_smartliving_agent_preview_batches_mapping_branch_and_user_lookups(domain):
    provisioning_discovery(domain, agent_id="SL-BATCH-1", name="Batch Agent One")
    for index in range(2, 12):
        agent_id = f"SL-BATCH-{index}"
        domain["db"].integration_discoveries.insert_one({
            "source_system": "smartliving", "discovery_type": "agent", "external_key": agent_id.casefold(),
            "external_id": agent_id, "external_display_name": f"Batch Agent {index}", "currently_observed": True,
            "relationship": {"status": "resolved", "agent_id": agent_id, "agent_display_name": f"Batch Agent {index}",
                             "manager_id": "SL-MANAGER-A", "manager_display_name": "Smart Manager A",
                             "external_branch": "Smart Branch A"},
        })
    branches = domain["db"].branches; mappings = domain["db"].integration_mappings; users = domain["db"].users
    with patch.object(branches, "find_one", wraps=branches.find_one) as branch_find_one, \
         patch.object(mappings, "find_one", wraps=mappings.find_one) as mapping_find_one, \
         patch.object(users, "find_one", wraps=users.find_one) as user_find_one:
        preview = integration.preview_agent_provisioning(str(domain["admin"]))
    assert preview["counts"]["eligible"] == 11
    assert branch_find_one.call_count == 0 and mapping_find_one.call_count == 0
    assert user_find_one.call_count == 1  # Canonical RBAC actor lookup only.


def test_smartliving_provisioning_routes_are_json_and_owner_admin_only(domain):
    discovery_id = provisioning_discovery(domain, agent_id="SL-ROUTE-1", name="Route Agent")
    manager_discovery_id = manager_discovery(domain, manager_id="SL-MGR-ROUTE", name="Route Manager")
    app = Flask(__name__)
    app.config.update(JWT_SECRET_KEY="smartliving-provisioning-test-secret-32", TESTING=True, MONGO_URI="mongodb://test")
    JWTManager(app); register_error_handlers(app)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(smart_living_integration_bp, url_prefix="/api/integrations/smartliving")
    client = app.test_client()
    for role in ("owner", "admin"):
        user_id = ObjectId(); domain["db"].users.insert_one({"_id": user_id, "role": role, "status": "active"})
        with app.app_context(): token = create_access_token(identity=str(user_id), additional_claims={"role": role})
        headers = {"Authorization": f"Bearer {token}"}
        preview_response = client.get("/api/integrations/smartliving/managers/preview", headers=headers)
        assert preview_response.status_code == 200 and preview_response.is_json
        assert client.get("/api/integrations/smartliving/managers/preview", headers=headers).status_code == 200
        with app.app_context(): relogin_token = create_access_token(identity=str(user_id), additional_claims={"role": role})
        assert client.get("/api/integrations/smartliving/managers/preview", headers={"Authorization": f"Bearer {relogin_token}"}).status_code == 200
        matched = client.post(f"/api/integrations/smartliving/managers/{manager_discovery_id}/match", headers=headers, json={"fleetops_user_id": str(domain["manager_a"])})
        assert matched.status_code == 200 and matched.is_json
        assert client.post(f"/api/integrations/smartliving/managers/{manager_discovery_id}/re-evaluate", headers=headers).is_json
        assert client.post("/api/integrations/smartliving/managers/backfill", headers=headers, json={"apply": False}).is_json
        assert client.get("/api/integrations/smartliving/agents/preview", headers=headers).is_json
        resolved = client.post(f"/api/integrations/smartliving/agents/{discovery_id}/resolve", headers=headers, json={
            "agent_name": "Route Agent", "branch_id": str(domain["a"]), "manager_id": str(domain["manager_a"]),
        })
        assert resolved.status_code == 200 and resolved.is_json
        response = client.post("/api/integrations/smartliving/agents/provision", headers=headers, json={"discovery_ids": [str(discovery_id)]})
        assert response.status_code == 200 and response.is_json
        assert response.headers["Cache-Control"] == "no-store"
    denied_id = ObjectId(); domain["db"].users.insert_one({"_id": denied_id, "role": "operations_manager", "status": "active", "permission_grants": ["integrations.manage"]})
    with app.app_context(): denied_token = create_access_token(identity=str(denied_id), additional_claims={"role": "operations_manager"})
    denied = client.get("/api/integrations/smartliving/agents/preview", headers={"Authorization": f"Bearer {denied_token}"})
    assert denied.status_code == 403 and denied.is_json
    denied_manager = client.get("/api/integrations/smartliving/managers/preview", headers={"Authorization": f"Bearer {denied_token}"})
    assert denied_manager.status_code == 403 and denied_manager.is_json


def test_application_blueprint_registry_contains_every_manager_provisioning_route():
    app = Flask(__name__)
    register_blueprints(app)
    registered = {(rule.rule, method) for rule in app.url_map.iter_rules() for method in rule.methods}
    expected = {
        ("/api/integrations/smartliving/managers/preview", "GET"),
        ("/api/integrations/smartliving/managers/<discovery_id>/match", "POST"),
        ("/api/integrations/smartliving/managers/<discovery_id>/create", "POST"),
        ("/api/integrations/smartliving/managers/<discovery_id>/re-evaluate", "POST"),
        ("/api/integrations/smartliving/managers/backfill", "POST"),
    }
    assert expected <= registered
    assert ("/api/integrations/smartliving/agents/reissue-credentials", "POST") in registered
    assert {
        ("/api/smart-living-deliveries/field-schedule", "GET"),
        ("/api/smart-living-deliveries/scheduler/queue", "GET"),
        ("/api/smart-living-deliveries/scheduler/runs", "POST"),
        ("/api/smart-living-deliveries/scheduler/assigned", "GET"),
        ("/api/smart-living-deliveries/scheduler/runs/<run_id>/stops/<stop_id>", "POST"),
    } <= registered


def canonical(record_id="D-100"):
    return {
        "source_system": "SmartLiving", "source_type": "delivery", "source_record_id": record_id,
        "source_synced_at": "2026-08-06T12:00:00Z",
        "branch_reference": {"external_id": "SL-BR-A", "external_display_name": "Smart Branch A"},
        "agent_reference": {"external_id": "SL-AG-A", "external_display_name": "Smart Agent A"},
        "reference_number": record_id, "customer_name": "Ada Mensah", "phone": "0200000000",
        "delivery_address": "Accra", "requested_delivery_date": "2026-08-10",
        "product_lines": [{"product_name": "Sofa", "quantity": 1}],
    }


def add_mappings(domain):
    integration.create_mapping("branch", {"external_id": "SL-BR-A", "external_display_name": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    integration.create_mapping("agent", {"external_id": "SL-AG-A", "external_display_name": "Smart Agent A", "fleetops_id": str(domain["agent_a"])}, str(domain["admin"]))


def test_manual_delivery_remains_compatible_and_has_no_external_identity(domain):
    manual = delivery.create_certified_order({
        "branch_id": str(domain["a"]), "reference_number": "MANUAL-1", "customer_name": "Manual Customer",
        "phone": "0240000000", "delivery_address": "Tema", "status": "WAITING_SCHEDULING",
        "product_lines": [{"product_name": "Chair", "quantity": 1}],
    }, str(domain["admin"]))
    stored = domain["db"].delivery_orders.find_one({"_id": ObjectId(manual["id"])})
    assert stored["external_source"] == "FleetOps Manual"
    assert "source_system" not in stored


def test_mapping_intake_persists_identity_and_lands_in_existing_queue(domain):
    add_mappings(domain)
    result = integration.intake_delivery(canonical(), str(domain["admin"]))
    assert result["outcome"] == "imported"
    stored = domain["db"].delivery_orders.find_one({"_id": ObjectId(result["delivery"]["id"])})
    assert stored["source_system"] == "smartliving"
    assert stored["source_type"] == "delivery"
    assert stored["source_record_id"] == "D-100"
    assert stored["source_synced_at"].isoformat().startswith("2026-08-06T12:00:00")
    assert stored["branch_id"] == domain["a"]
    assert stored["assigned_field_agent_id"] == domain["agent_a"]
    assert stored["status"] == "WAITING_SCHEDULING"
    queue = delivery.list_scheduler_queue(str(domain["manager_a"]), {})
    assert [row["id"] for row in queue["orders"]] == [str(stored["_id"])]


def test_duplicate_is_idempotent_and_conflicting_payload_creates_exception(domain):
    add_mappings(domain)
    first = integration.intake_delivery(canonical(), str(domain["admin"]))
    repeated = integration.intake_delivery(canonical(), str(domain["admin"]))
    assert repeated["outcome"] == "duplicate_skipped"
    assert repeated["delivery"]["id"] == first["delivery"]["id"]
    assert domain["db"].delivery_orders.count_documents({"source_record_id": "D-100"}) == 1
    changed = canonical(); changed["customer_name"] = "Different Customer"
    conflict = integration.intake_delivery(changed, str(domain["admin"]))
    assert conflict["outcome"] == "conflict"
    assert conflict["exception"]["exception_type"] == "conflicting_source_record"
    assert domain["db"].delivery_orders.count_documents({"source_record_id": "D-100"}) == 1


def test_database_unique_external_identity_is_authoritative(domain):
    identity = {"source_system": "smartliving", "source_type": "delivery", "source_record_id": "D-UNIQUE"}
    domain["db"].delivery_orders.insert_one({**identity, "external_source": "one", "external_reference": "one"})
    with pytest.raises(Exception):
        domain["db"].delivery_orders.insert_one({**identity, "external_source": "two", "external_reference": "two"})


def test_unmapped_record_creates_exception_not_delivery(domain):
    result = integration.intake_delivery(canonical("D-NOMAP"), str(domain["admin"]))
    assert result["outcome"] == "mapping_failed"
    assert result["exception"]["exception_type"] == "unmapped_branch"
    assert domain["db"].delivery_orders.count_documents({"source_record_id": "D-NOMAP"}) == 0
    assert domain["db"].integration_exceptions.count_documents({"source_record_id": "D-NOMAP", "status": "open"}) == 1


def test_invalid_sync_timestamp_creates_deduplicated_exception(domain):
    payload = canonical("D-BAD-TIME"); payload["source_synced_at"] = "not-a-timestamp"
    first = integration.intake_delivery(payload, str(domain["admin"]))
    second = integration.intake_delivery(payload, str(domain["admin"]))
    assert first["outcome"] == second["outcome"] == "validation_failed"
    assert first["exception"]["exception_type"] == "invalid_source_data"
    assert domain["db"].integration_exceptions.count_documents({"source_record_id": "D-BAD-TIME", "status": "open"}) == 1
    assert domain["db"].delivery_orders.count_documents({"source_record_id": "D-BAD-TIME"}) == 0


def test_validation_failure_creates_exception_and_branch_visibility_is_scoped(domain):
    add_mappings(domain)
    invalid = canonical("D-INVALID"); invalid["product_lines"] = []
    failed = integration.intake_delivery(invalid, str(domain["admin"]))
    assert failed["outcome"] == "validation_failed"
    assert domain["db"].delivery_orders.count_documents({"source_record_id": "D-INVALID"}) == 0
    imported = integration.intake_delivery(canonical("D-SCOPED"), str(domain["admin"]))
    assert imported["outcome"] == "imported"
    assert delivery.list_scheduler_queue(str(domain["manager_a"]), {})["pagination"]["total"] == 1
    assert delivery.list_scheduler_queue(str(domain["manager_b"]), {})["pagination"]["total"] == 0


def test_branch_manager_cannot_manage_global_integration(domain):
    with pytest.raises(ApiError) as denied:
        integration.list_mappings("branch", str(domain["manager_a"]))
    assert denied.value.status_code == 403


def test_only_owner_and_admin_roles_can_manage_smartliving_integration(domain):
    owner, legacy_admin, operations_manager = ObjectId(), ObjectId(), ObjectId()
    domain["db"].users.insert_many([
        {"_id": owner, "role": "owner", "status": "active"},
        {"_id": legacy_admin, "role": "admin", "status": "active"},
        {"_id": operations_manager, "role": "operations_manager", "status": "active", "permission_grants": ["integrations.manage"]},
    ])
    assert integration.list_mappings("branch", str(owner)) == {"mappings": []}
    assert integration.list_mappings("branch", str(legacy_admin)) == {"mappings": []}
    assert integration.list_mappings("branch", str(domain["admin"])) == {"mappings": []}
    with pytest.raises(ApiError) as error:
        integration.list_mappings("branch", str(operations_manager))
    assert error.value.status_code == 403
    assert "integrations.manage" not in rbac.role_definition("operations_manager")["permissions"]


def test_smartliving_access_follows_the_active_workspace_on_refresh(domain):
    user_id = ObjectId()
    domain["db"].users.insert_one({
        "_id": user_id,
        "role": "system_administrator",
        "role_ids": ["system_administrator", "admin"],
        "selected_workspace": "system_administrator",
        "status": "active",
    })
    with pytest.raises(ApiError) as denied:
        integration.list_mappings("branch", str(user_id))
    assert denied.value.status_code == 403

    domain["db"].users.update_one({"_id": user_id}, {"$set": {"selected_workspace": "admin"}})
    assert integration.list_mappings("branch", str(user_id)) == {"mappings": []}


def test_owner_and_admin_can_reach_authenticated_smartliving_routes(domain):
    app = Flask(__name__)
    app.config.update(JWT_SECRET_KEY="smartliving-rbac-test-secret-at-least-32-bytes", TESTING=True)
    JWTManager(app)
    register_error_handlers(app)
    app.register_blueprint(smart_living_integration_bp, url_prefix="/api/integrations/smartliving")
    client = app.test_client()

    for role in ("owner", "admin"):
        user_id = ObjectId()
        domain["db"].users.insert_one({"_id": user_id, "role": role, "status": "active"})
        with app.app_context():
            token = create_access_token(identity=str(user_id), additional_claims={"role": role})
        headers = {"Authorization": f"Bearer {token}"}
        for path in (
            "/status", "/discoveries", "/dry-run/latest", "/mapping-options",
            "/mappings/branch", "/mappings/agent", "/exceptions", "/history",
        ):
            response = client.get(f"/api/integrations/smartliving{path}", headers=headers)
            assert response.status_code == 200, (role, path, response.get_json())


@pytest.mark.parametrize("role", ["system_administrator", "operations_administrator", "operations_manager"])
def test_non_admin_role_cannot_reach_smartliving_routes_even_with_permission_grant(domain, role):
    app = Flask(__name__)
    app.config.update(JWT_SECRET_KEY="smartliving-rbac-test-secret-at-least-32-bytes", TESTING=True)
    JWTManager(app)
    register_error_handlers(app)
    app.register_blueprint(smart_living_integration_bp, url_prefix="/api/integrations/smartliving")
    user_id = ObjectId()
    domain["db"].users.insert_one({
        "_id": user_id, "role": role, "status": "active",
        "permission_grants": ["integrations.manage"],
    })
    with app.app_context():
        token = create_access_token(identity=str(user_id), additional_claims={"role": role})
    response = app.test_client().get(
        "/api/integrations/smartliving/mappings/branch",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_read_only_connection_probe_persists_only_sanitized_structure(domain):
    class Response:
        status = 200

        def read(self):
            return b'{"ok":true,"pagination":{"page":1,"limit":5,"total":2,"total_pages":1},"rows":[{"_id":"secret-id","customer_name":"Private Name","qty":2}]}'

    app = Flask(__name__)
    app.config.update(SMARTLIVING_API_BASE_URL="https://smartliving.invalid/api", SMARTLIVING_API_KEY="super-secret-key")
    seen_requests = []

    def fake_urlopen(request, timeout):
        seen_requests.append(request)
        assert request.get_header("X-api-key") == "super-secret-key"
        assert request.get_header("Accept") == "application/json"
        assert timeout == 30
        return Response()

    with app.app_context(), patch.object(integration, "urlopen", side_effect=fake_urlopen):
        result = integration.test_connection(str(domain["admin"]))
        status = integration.integration_status(str(domain["admin"]))

    assert result["connection_status"] == "connected"
    assert status["connection_status"] == "connected"
    assert [item["endpoint"] for item in result["endpoints"]] == ["/completed-cards", "/closed-cards"]
    assert all(item["http_status"] == 200 and item["record_count"] == 2 for item in result["endpoints"])
    assert result["endpoints"][0]["sample_structure"][0] == {"_id": "<string>", "customer_name": "<string>", "qty": "<number>"}
    stored = domain["db"].integration_connections.find_one({"source_system": "smartliving"})
    assert "super-secret-key" not in repr(stored)
    assert domain["db"].delivery_orders.count_documents({}) == 0
    assert len(seen_requests) == 2


def test_discovery_and_dry_run_group_records_without_creating_deliveries(domain):
    add_mappings(domain)
    completed_base = {
        "_id": "CARD-1", "customer_id": "CUSTOMER-1", "customer_name": "Preview Customer",
        "customer_phone": "0200000000", "customer": {"location": "Preview Location"},
        "agent_id": "SL-AG-A", "agent_name": "External Agent", "agent_branch": "SL-BR-A",
        "status": "pending", "stock_deduction_status": "confirmed", "created_at": "2026-08-07T00:00:00Z",
        "product_index": 0, "product": {"_id": "PRODUCT-1", "name": "Sofa", "quantity": 1},
    }
    source_rows = {
        "completed-cards": [
            completed_base,
            {**completed_base, "product_index": 1, "product": {"_id": "PRODUCT-2", "name": "Chair", "quantity": 2}},
            {**completed_base, "_id": "CARD-DONE", "status": "delivered"},
        ],
        "closed-cards": [
            {
                "_id": "CLOSED-1", "action": "close_card", "customer_id": "CUSTOMER-2",
                "customer": {"name": "Closed Preview", "phone_number": "0200000001", "location": "Preview Location", "agent_id": "SL-AG-A", "purchases": [{"agent_id": "SL-AG-A"}]},
                "payload": {"selected_product_index": 0, "selected_product_name": "Original", "target_products": [{"id": "PRODUCT-3", "qty": 1}]},
            },
            {
                "_id": "CLOSED-NO-TARGET", "action": "close_card", "customer_id": "CUSTOMER-3",
                "customer": {"name": "No Target", "phone_number": "0200000002", "location": "Preview Location"},
                "payload": {"selected_product_index": 0, "selected_product_name": "Original", "target_products": []},
            },
        ],
    }
    app = Flask(__name__)
    with app.app_context():
        discovered = integration.discover_source_values(str(domain["admin"]), source_rows=source_rows)
        result = integration.dry_run_import(str(domain["admin"]), source_rows=source_rows)

    assert discovered["unique_branches"] == 1
    assert discovered["unique_agents"] == 1
    assert result["total_scanned"] == 5
    assert result["source_counts"] == {"completed_rows": 3, "completed_records": 2, "closed_rows": 2, "closed_records": 2}
    assert result["eligible"] == 3
    assert result["ready"] == 2
    assert result["unmapped_branches"] == 0
    assert result["deduplication"]["completed_rows_collapsed_by_card_id"] == 1
    assert result["deliveries_created"] == 0
    assert domain["db"].delivery_orders.count_documents({}) == 0
    assert domain["db"].integration_exceptions.find_one({"source_record_id": "CLOSED-1"}) is None


def test_controlled_period_preview_and_selected_import_are_safe_and_idempotent(domain):
    add_mappings(domain)
    base = {
        "customer_id": "CUSTOMER-1", "customer_name": "Period Customer", "customer_phone": "0200000000",
        "customer": {"location": "Accra", "coordinates": {"latitude": 5.5, "longitude": -0.2}},
        "agent_id": "SL-AG-A", "agent_name": "External Agent", "agent_branch": "SL-BR-A",
        "status": "pending", "stock_deduction_status": "confirmed", "product_index": 0,
        "product": {"_id": "PRODUCT-1", "name": "Sofa", "quantity": 1},
    }
    rows = {
        "completed-cards": [
            {**base, "_id": "IN-RANGE", "created_at": "2026-08-06T10:00:00Z"},
            {**base, "_id": "OUTSIDE", "created_at": "2026-07-30T10:00:00Z"},
            {**base, "_id": "DELIVERED", "created_at": "2026-08-05T10:00:00Z", "status": "delivered"},
        ],
        "closed-cards": [{"_id": "CLOSED", "at": "2026-08-06T12:00:00Z", "action": "close_card", "payload": {"target_products": []}}],
    }
    controls = {"source": "completed-cards", "from_date": "2026-08-03", "to_date": "2026-08-09", "quick_option": "this_week"}
    preview = integration.dry_run_import(str(domain["admin"]), controls, source_rows=rows)

    assert preview["found"] == 2
    assert preview["ready"] == 2
    assert preview["range_counts"]["outside_period"] == 1
    assert preview["performance"]["records_fetched"] == 3
    assert preview["performance"]["records_matched"] == 2
    assert preview["performance"]["api_calls"] == 0
    assert {item["source_record_id"] for item in preview["records"]} == {"IN-RANGE", "DELIVERED"}
    ready = next(item for item in preview["records"] if item["source_record_id"] == "IN-RANGE")
    delivered = next(item for item in preview["records"] if item["source_record_id"] == "DELIVERED")
    assert ready["source_date_field"] == "created_at" and ready["import_eligible"] is True
    assert ready["customer_name"] == "Period Customer" and ready["products"] == [{"name": "Sofa", "reference": "PRODUCT-1", "quantity": 1}]
    assert delivered["physically_delivered"] is False and delivered["import_eligible"] is True

    delivered_request = {**controls, "selected_records": [{"source_endpoint": "completed-cards", "source_record_id": "DELIVERED"}]}
    delivered_import = integration.import_selected_records(delivered_request, str(domain["admin"]), source_rows=rows)
    assert delivered_import["imported"] == 1 and delivered_import["rejected"] == 0
    assert domain["db"].delivery_orders.find_one({"source_record_id": "DELIVERED"})["status"] == "WAITING_SCHEDULING"

    request = {**controls, "selected_records": [{"source_endpoint": "completed-cards", "source_record_id": "IN-RANGE"}]}
    first = integration.import_selected_records(request, str(domain["admin"]), source_rows=rows)
    assert first["imported"] == 1 and first["rejected"] == 0
    stored = domain["db"].delivery_orders.find_one({"source_record_id": "IN-RANGE"})
    assert stored["status"] == "WAITING_SCHEDULING"
    assert stored["source_date_field"] == "created_at" and stored["source_date"].isoformat().startswith("2026-08-06")
    assert stored["imported_at"] and stored["imported_by"] == domain["admin"]
    assert stored["import_batch_id"] == first["batch_id"]
    assert stored["import_from_date"] == "2026-08-03" and stored["import_to_date"] == "2026-08-09"

    repeated = integration.import_selected_records(request, str(domain["admin"]), source_rows=rows)
    assert repeated["imported"] == 0 and repeated["duplicate_already_imported"] == 1
    assert domain["db"].delivery_orders.count_documents({"source_record_id": "IN-RANGE"}) == 1
    rerun = integration.dry_run_import(str(domain["admin"]), controls, source_rows=rows)
    imported_record = next(item for item in rerun["records"] if item["source_record_id"] == "IN-RANGE")
    assert imported_record["outcome"] == "already_imported"
    assert imported_record["import_eligible"] is False
    assert rerun["already_imported"] == 2 and rerun["blocked"] == 0
    assert rerun["eligible"] == rerun["ready"] + rerun["blocked_eligible"]


def test_three_ready_deliveries_complete_existing_operations_flow(domain):
    add_mappings(domain)
    integration.create_mapping("manager", {
        "external_id": "SL-MGR-A", "external_display_name": "Smart Manager A",
        "fleetops_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    second_manager_id = ObjectId()
    domain["db"].users.insert_one({
        "_id": second_manager_id, "full_name": "Second Branch Manager", "role": "branch_manager", "status": "active",
        "primary_branch_id": domain["a"], "allowed_branch_ids": [domain["a"]],
    })
    domain["db"].branches.update_one({"_id": domain["a"]}, {"$set": {"manager_ids": [domain["manager_a"], second_manager_id]}})
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {"full_name": "Branch Manager A"}})
    domain["db"].users.update_one({"_id": domain["agent_a"]}, {"$set": {"full_name": "Field Agent A", "manager_id": domain["manager_a"]}})
    driver_id, vehicle_id = ObjectId(), ObjectId()
    domain["db"].users.insert_one({
        "_id": driver_id, "full_name": "Delivery Driver", "role": "driver", "status": "active",
        "primary_branch_id": domain["a"], "allowed_branch_ids": [domain["a"]],
    })
    domain["db"].vehicles.insert_one({
        "_id": vehicle_id, "registration_number": "SL-1001", "branch_id": domain["a"], "status": "available",
    })
    base = {
        "customer_id": "SMART-CUSTOMER", "customer_phone": "0200000000",
        "customer": {"location": "Accra Central", "coordinates": {"latitude": 5.56, "longitude": -0.2}},
        "agent_id": "SL-AG-A", "agent_name": "Smart Agent A", "agent_branch": "SL-BR-A",
        "manager_id": "SL-MGR-A", "manager_name": "Smart Manager A", "manager_branch": "SL-BR-A",
        "status": "pending", "stock_deduction_status": "confirmed", "product_index": 0,
        "created_at": "2026-08-25T10:00:00Z",
    }
    rows = {"completed-cards": [
        {**base, "_id": f"FLOW-{index}", "customer_name": f"Flow Customer {index}",
         "product": {"_id": f"PRODUCT-{index}", "name": f"Product {index}", "quantity": index}}
        for index in range(1, 4)
    ]}
    controls = {"source": "completed-cards", "from_date": "2026-08-25", "to_date": "2026-08-25"}
    preview = integration.dry_run_import(str(domain["admin"]), controls, source_rows=rows)
    assert preview["ready"] == 3
    selected = [{"source_endpoint": item["source_endpoint"], "source_record_id": item["source_record_id"]} for item in preview["records"] if item["import_eligible"]]
    imported = integration.import_selected_records({**controls, "selected_records": selected}, str(domain["admin"]), source_rows=rows)
    assert imported["imported"] == 3 and imported["rejected"] == 0
    order_rows = list(domain["db"].delivery_orders.find({"source_record_id": {"$in": ["FLOW-1", "FLOW-2", "FLOW-3"]}}).sort("source_record_id", 1))
    assert len(order_rows) == 3
    assert all(row["status"] == "WAITING_SCHEDULING" and row["branch_id"] == domain["a"] for row in order_rows)
    assert all(row["assigned_field_agent_id"] == domain["agent_a"] and row["manager_id"] == domain["manager_a"] for row in order_rows)
    assert all(row["source_agent_id"] == "SL-AG-A" and row["source_manager_id"] == "SL-MGR-A" for row in order_rows)
    repeated = integration.import_selected_records({**controls, "selected_records": selected}, str(domain["admin"]), source_rows=rows)
    assert repeated["imported"] == 0 and repeated["duplicate_already_imported"] == 3
    assert domain["db"].delivery_orders.count_documents({"source_record_id": {"$in": ["FLOW-1", "FLOW-2", "FLOW-3"]}}) == 3

    run = delivery.create_daily_run({
        "branch_id": str(domain["a"]), "delivery_date": "2099-08-25", "planned_departure_time": "08:00",
        "driver_id": str(driver_id), "vehicle_id": str(vehicle_id),
        "delivery_order_ids": [str(row["_id"]) for row in order_rows],
        "stops": [{"delivery_order_id": str(row["_id"]), "expected_arrival_time": f"0{8 + index}:00"} for index, row in enumerate(order_rows)],
    }, str(domain["admin"]))
    published = delivery.publish_daily_run(run["id"], str(domain["admin"]))
    assert published["status"] == "PUBLISHED" and [stop["sequence_number"] for stop in published["stops"]] == [1, 2, 3]
    assert domain["db"].vehicle_movements.count_documents({"source_key": f"delivery_run:{run['id']}"}) == 1

    agent_view = delivery.list_field_agent_deliveries(str(domain["agent_a"]), {})
    manager_view = delivery.list_daily_runs(str(domain["manager_a"]), {})
    assert agent_view["count"] == 3 and agent_view["counts"]["upcoming"] == 3
    assert all(item["driver"]["name"] == "Delivery Driver" and item["vehicle"]["name"] == "SL-1001" for item in agent_view["deliveries"])
    assert manager_view["count"] == 1 and len(manager_view["runs"][0]["stops"]) == 3
    assert delivery.list_daily_runs(str(second_manager_id), {})["count"] == 1
    assert delivery.list_field_agent_deliveries(str(domain["agent_b"]), {})["count"] == 0
    assert delivery.list_daily_runs(str(domain["manager_b"]), {})["count"] == 0
    tasks = operational_tasks.list_driver_operational_tasks(str(driver_id))
    assert tasks["count"] == 1 and len(tasks["tasks"][0]["stops"]) == 3
    assert tasks["tasks"][0]["stops"][0]["field_agent"] == "Field Agent A"
    assert tasks["tasks"][0]["stops"][0]["products"] == [{"name": "Product 1", "quantity": 1}]

    delivery.accept_run_assignment(run["id"], str(driver_id))
    issue_items = [
        {"delivery_order_id": str(order["_id"]), "line_id": str(line["line_id"]), "issued_quantity": line["quantity"]}
        for order in order_rows for line in order["product_lines"]
    ]
    delivery.issue_scheduler_run(run["id"], {"items": issue_items, "total_issued_quantity": 6}, str(domain["admin"]))
    delivery.respond_to_custody(run["id"], {"decision": "ACCEPT"}, str(driver_id))
    delivery.start_scheduler_run(run["id"], {}, str(driver_id))
    first_stop = published["stops"][0]
    delivery.update_scheduler_stop(run["id"], first_stop["stop_id"], {"action": "ARRIVE"}, str(driver_id))
    delivery.update_scheduler_stop(run["id"], first_stop["stop_id"], {
        "action": "OUTCOME", "outcome": "COMPLETED", "recipient_name": "Test Recipient",
        "items": [{"line_id": str(order_rows[0]["product_lines"][0]["line_id"]), "quantity_delivered": 1, "quantity_undelivered": 0}],
    }, str(driver_id))
    completed = domain["db"].delivery_orders.find_one({"_id": order_rows[0]["_id"]})
    assert completed["status"] == "DELIVERED" and completed["product_lines"][0]["quantity_delivered"] == 1
    refreshed = delivery.list_field_agent_deliveries(str(domain["agent_a"]), {})
    assert refreshed["counts"] == {"upcoming": 2, "delivered": 1}
    assert next(item for item in refreshed["deliveries"] if item["id"] == str(completed["_id"]))["stop_status"] == "COMPLETED"
    movement = domain["db"].vehicle_movements.find_one({"source_key": f"delivery_run:{run['id']}"})
    assert movement["status"] == "in_progress"
    notified_users = {call[0][0] for call in domain["notifications"]}
    assert {domain["agent_a"], domain["manager_a"], second_manager_id, driver_id} <= notified_users


def test_closed_cards_use_at_for_period_filtering(domain):
    rows = {"closed-cards": [{"_id": "CLOSED-1", "at": "2026-08-01T23:59:59Z", "action": "ignore", "payload": {"target_products": []}}]}
    preview = integration.dry_run_import(str(domain["admin"]), {"source": "closed-cards", "from_date": "2026-08-01", "to_date": "2026-08-01"}, source_rows=rows)
    assert preview["found"] == 1
    assert preview["records"][0]["source_date_field"] == "at"


def test_preview_uses_canonical_blockers_and_keeps_invalid_dates_visible(domain):
    rows = {"completed-cards": [{
        "_id": "INVALID-DATE", "created_at": "not-a-date", "status": "pending",
        "agent_branch": "UNKNOWN", "agent_id": "UNKNOWN", "stock_deduction_status": "confirmed",
        "customer_name": "", "customer_phone": "", "customer": {"location": ""},
        "product": {"_id": "P-1", "name": "Chair", "quantity": 0}, "product_index": 0,
    }]}
    controls = {"source": "completed-cards", "from_date": "2026-08-03", "to_date": "2026-08-09"}
    before = domain["db"].delivery_orders.count_documents({})
    preview = integration.dry_run_import(str(domain["admin"]), controls, source_rows=rows)
    record = preview["records"][0]

    assert set(record["blockers"]) == {
        "invalid_source_date", "missing_customer_name", "missing_customer_phone", "missing_customer_location",
        "missing_quantity", "unmapped_agent", "unmapped_branch",
    }
    assert "other" not in record["blockers"]
    assert record["outcome"] == "blocked" and record["import_eligible"] is False
    assert preview["eligible"] == preview["ready"] + preview["blocked_eligible"] == 1
    assert preview["invalid_ignored"] == 0
    assert preview["range_counts"]["missing_or_invalid_date"] == 1
    assert domain["db"].delivery_orders.count_documents({}) == before


def test_closed_card_resolves_only_exact_product_identity_and_preserves_unknowns(domain):
    add_mappings(domain)
    rows = {"closed-cards": [
        {
            "_id": "KNOWN", "at": "2026-08-06T12:00:00Z", "action": "close_card", "agent_branch": "SL-BR-A",
            "customer": {"name": "Known", "phone_number": "020", "location": "Accra", "agent_id": "SL-AG-A",
                         "purchases": [{"product": {"_id": "P-1", "name": "Exact Sofa"}}]},
            "payload": {"target_products": [{"id": "P-1", "qty": 2}]},
        },
        {
            "_id": "UNKNOWN", "at": "2026-08-06T12:00:00Z", "action": "close_card", "agent_branch": "SL-BR-A",
            "customer": {"name": "Unknown", "phone_number": "021", "location": "Accra", "agent_id": "SL-AG-A"},
            "payload": {"selected_product_name": "Must Not Be Guessed", "target_products": [{"id": "P-X", "qty": 1}]},
        },
    ]}
    preview = integration.dry_run_import(str(domain["admin"]), {"source": "closed-cards", "from_date": "2026-08-03", "to_date": "2026-08-09"}, source_rows=rows)
    by_id = {item["source_record_id"]: item for item in preview["records"]}
    assert by_id["KNOWN"]["products"][0]["name"] == "Exact Sofa"
    assert "stock_status_unavailable" in by_id["KNOWN"]["other_detail"]
    assert by_id["UNKNOWN"]["products"][0]["name"] is None
    assert "missing_target_product_name" in by_id["UNKNOWN"]["other_detail"]
    assert by_id["KNOWN"]["import_eligible"] is True
    assert by_id["UNKNOWN"]["blockers"] == ["missing_product_name"]


def test_preview_and_import_reuse_confirmed_user_source_link_without_duplicate_mapping(domain):
    domain["db"].users.update_one({"_id": domain["agent_a"]}, {"$set": {
        "smartliving_agent_id": "CONFIRMED-AGENT", "full_name": "Confirmed Agent",
    }})
    rows = {"completed-cards": [{
        "_id": "CONFIRMED-LINK-DELIVERY", "created_at": "2026-08-20T10:00:00Z", "status": "pending",
        "stock_deduction_status": "confirmed", "agent_id": "CONFIRMED-AGENT", "agent_name": "Confirmed Agent",
        "agent_branch": "Current Confirmed Branch", "customer_name": "Confirmed Customer", "customer_phone": "0200000000",
        "customer": {"location": "Confirmed Location"}, "product_index": 0,
        "product": {"_id": "CONFIRMED-PRODUCT", "name": "Confirmed Product", "quantity": 1},
    }]}
    controls = {"source": "completed-cards", "from_date": "2026-08-19", "to_date": "2026-08-24"}
    preview = integration.dry_run_import(str(domain["admin"]), controls, source_rows=rows)
    assert preview["ready"] == 1
    record = preview["records"][0]
    assert record["mapping_status"] == "mapped" and record["blockers"] == []
    selected = [{"source_endpoint": record["source_endpoint"], "source_record_id": record["source_record_id"]}]
    result = integration.import_selected_records({**controls, "selected_records": selected}, str(domain["admin"]), source_rows=rows)
    assert result["imported"] == 1
    stored = domain["db"].delivery_orders.find_one({"source_record_id": "CONFIRMED-LINK-DELIVERY"})
    assert stored["branch_id"] == domain["a"] and stored["assigned_field_agent_id"] == domain["agent_a"]
    repeated = integration.import_selected_records({**controls, "selected_records": selected}, str(domain["admin"]), source_rows=rows)
    assert repeated["duplicate_already_imported"] == 1
    assert domain["db"].delivery_orders.count_documents({"source_record_id": "CONFIRMED-LINK-DELIVERY"}) == 1


def test_closed_card_uses_exact_completed_card_names_for_readable_preview(domain):
    rows = {
        "completed-cards": [{
            "_id": "COMPLETED", "created_at": "2026-08-06T10:00:00Z", "status": "delivered",
            "agent_id": "AGENT-1", "agent_name": "Readable Agent", "agent_branch": "Readable Branch",
            "manager_id": "MANAGER-1", "manager_branch": "Readable Branch",
            "customer_name": "Completed Customer", "customer_phone": "020", "customer": {"location": "Accra"},
            "product": {"_id": "P-1", "name": "Main Product", "quantity": 1}, "product_index": 0,
            "inventory_recipe_snapshot": {"components": [{"inventory_product_id": "STOCK-1", "component_name": "Readable Component"}]},
        }],
        "closed-cards": [{
            "_id": "CLOSED", "at": "2026-08-06T12:00:00Z", "action": "close_card",
            "customer": {"name": "Closed Customer", "phone_number": "021", "location": "Tema", "occupation": "Trader", "agent_id": "AGENT-1", "manager_id": "MANAGER-1", "purchases": []},
            "payload": {"target_products": [{"id": "STOCK-1", "qty": 2}]},
        }],
    }
    preview = integration.dry_run_import(str(domain["admin"]), {"source": "both", "from_date": "2026-08-03", "to_date": "2026-08-09"}, source_rows=rows)
    closed = next(item for item in preview["records"] if item["source_endpoint"] == "closed-cards")
    assert closed["customer_name"] == "Closed Customer"
    assert closed["customer_phone"] == "021" and closed["customer_location"] == "Tema"
    assert closed["customer_occupation"] == "Trader"
    assert closed["external_agent_name"] == "Readable Agent"
    assert closed["branch_name"] == "Readable Branch"
    assert closed["products"] == [{"name": "Readable Component", "reference": "STOCK-1", "quantity": 2}]
    assert closed["source_status_label"] == "Closed card"
    assert closed["entities"]["customer"] == {"id": None, "display_name": "Closed Customer", "phone": "021", "location": "Tema", "occupation": "Trader"}
    assert closed["entities"]["agent"] == {"id": "AGENT-1", "display_name": "Readable Agent"}
    assert closed["entities"]["branch"]["display_name"] == "Readable Branch"
    assert closed["entities"]["products"] == [{"id": "STOCK-1", "display_name": "Readable Component", "quantity": 2}]


def test_discovery_rebuilds_stale_id_label_from_current_api_without_touching_mapping(domain):
    add_mappings(domain)
    domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "sl-ag-a",
        "external_id": "SL-AG-A", "external_display_name": "SL-AG-A", "currently_observed": True,
    })
    domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "other-agent",
        "external_id": "OTHER-AGENT", "external_display_name": "Other Agent", "currently_observed": True,
    })
    mapping_before = domain["db"].integration_mappings.find_one({"mapping_type": "agent"})
    rows = {"completed-cards": [{
        "_id": "CURRENT", "agent_id": "SL-AG-A", "agent_name": "Current Agent Name", "agent_branch": "Current Branch",
        "customer_id": "C-1", "customer_name": "Customer", "customer_phone": "020", "customer": {"location": "Accra"},
        "product": {"_id": "P-1", "name": "Chair", "quantity": 1}, "created_at": "2026-08-06T00:00:00Z", "status": "pending",
    }], "closed-cards": []}
    integration.discover_source_values(str(domain["admin"]), source_rows=rows)
    discovery = domain["db"].integration_discoveries.find_one({"external_key": "sl-ag-a"})
    mapping_after = domain["db"].integration_mappings.find_one({"mapping_type": "agent"})
    assert discovery["external_display_name"] == "Current Agent Name"
    assert discovery["display_name_status"] == "resolved" and discovery["branch_name"] == "Current Branch"
    assert domain["db"].integration_discoveries.find_one({"external_key": "other-agent"})["currently_observed"] is True
    assert mapping_after == mapping_before


def test_agent_relationship_resolver_uses_stable_manager_and_confirmed_branch_ids_without_provisioning(domain):
    add_mappings(domain)
    before_users = domain["db"].users.count_documents({})
    rows = {
        "completed-cards": [
            {
                "_id": "REL-1", "agent_id": "AGENT-REL", "agent_name": "Readable Agent",
                "manager_id": "MANAGER-REL", "manager_name": "Readable Manager", "manager_branch": "SL-BR-A",
            },
            {
                "_id": "DIRECT-1", "agent_id": "AGENT-DIRECT", "agent_name": "Direct Agent",
                "agent_branch": "SL-BR-A",
            },
            {
                "_id": "CONFLICT-1", "agent_id": "AGENT-CONFLICT", "manager_id": "MANAGER-A",
                "manager_branch": "SL-BR-A",
            },
            {
                "_id": "CONFLICT-2", "agent_id": "AGENT-CONFLICT", "manager_id": "MANAGER-B",
                "manager_branch": "SL-BR-A",
            },
            {"_id": "BRANCH-CONFLICT-1", "agent_id": "AGENT-BRANCH-CONFLICT", "agent_branch": "SL-BR-A"},
            {"_id": "BRANCH-CONFLICT-2", "agent_id": "AGENT-BRANCH-CONFLICT", "agent_branch": "SL-BR-B"},
        ],
        "closed-cards": [{
            "_id": "REVIEW-1", "customer": {
                "agent_id": "AGENT-REVIEW", "manager_id": "MANAGER-REVIEW", "purchases": [],
            }, "payload": {},
        }],
    }

    result = integration.discover_source_values(str(domain["admin"]), source_rows=rows)
    found = {
        row["external_id"]: row["relationship"]
        for row in domain["db"].integration_discoveries.find({"discovery_type": "agent"})
    }

    assert result["relationship_counts"] == {"resolved": 1, "unresolved": 2, "conflicting": 2}
    assert found["AGENT-REL"]["resolution_source"] == "manager_branch"
    assert found["AGENT-REL"]["manager_id"] == "MANAGER-REL"
    assert found["AGENT-REL"]["manager_display_name"] == "Readable Manager"
    assert found["AGENT-REL"]["external_branch"] == "SL-BR-A"
    assert found["AGENT-DIRECT"]["status"] == "needs_review"
    assert found["AGENT-DIRECT"]["reason"] == "missing_manager_id"
    assert found["AGENT-REVIEW"]["status"] == "needs_review"
    assert found["AGENT-REVIEW"]["reason"] == "missing_agent_name"
    assert found["AGENT-CONFLICT"]["status"] == "conflicting"
    assert found["AGENT-CONFLICT"]["reason"] == "conflicting_manager"
    assert found["AGENT-BRANCH-CONFLICT"]["reason"] == "conflicting_direct_branch"
    assert domain["db"].users.count_documents({}) == before_users


def test_agent_relationship_resolver_uses_latest_dated_evidence_not_historical_values():
    rows = {"completed-cards": [
        {"_id": "OLD", "created_at": "2026-01-01T00:00:00Z", "agent_id": "AGENT-1", "agent_name": "Old Name", "agent_branch": "Kasoa", "manager_id": "MANAGER-OLD", "manager_name": "Old Manager", "manager_branch": "Kasoa"},
        {"_id": "CURRENT", "created_at": "2026-08-24T00:00:00Z", "agent_id": "AGENT-1", "agent_name": "Current Name", "agent_branch": "Tema Newtown", "manager_id": "MANAGER-CURRENT", "manager_name": "Current Manager", "manager_branch": "Tema Newtown"},
    ], "closed-cards": []}
    relationship = integration.resolve_agent_manager_branches(rows)["agent-1"]
    assert relationship["status"] == "resolved" and relationship["reason"] is None
    assert relationship["agent_display_name"] == "Current Name"
    assert relationship["direct_branch"] == "Tema Newtown" and relationship["direct_branch_options"] == ["Tema Newtown"]
    assert relationship["manager_id"] == "MANAGER-CURRENT" and relationship["manager_display_name"] == "Current Manager"


def test_same_timestamp_direct_branch_disagreement_remains_a_real_conflict():
    rows = {"completed-cards": [
        {"_id": "ONE", "created_at": "2026-08-24T00:00:00Z", "agent_id": "AGENT-1", "agent_name": "Current Name", "agent_branch": "Tema Newtown", "manager_id": "MANAGER-1"},
        {"_id": "TWO", "created_at": "2026-08-24T00:00:00Z", "agent_id": "AGENT-1", "agent_name": "Current Name", "agent_branch": "Kasoa", "manager_id": "MANAGER-1"},
    ], "closed-cards": []}
    relationship = integration.resolve_agent_manager_branches(rows)["agent-1"]
    assert relationship["status"] == "conflicting" and relationship["reason"] == "conflicting_direct_branch"
    assert set(relationship["direct_branch_options"]) == {"Tema Newtown", "Kasoa"}


def test_confirmed_manager_mapping_resolves_tema_and_flags_cross_branch_assignment(domain):
    integration.create_mapping("branch", {"external_code": "Tema Newtown", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    integration.create_mapping("branch", {"external_code": "Kasoa", "fleetops_id": str(domain["b"])}, str(domain["admin"]))
    domain["db"].users.update_one({"_id": domain["manager_a"]}, {"$set": {"full_name": "Edem Kwak"}})
    integration.create_mapping("manager", {"external_id": "SL-EDEM", "fleetops_id": str(domain["manager_a"])}, str(domain["admin"]))
    for agent_id, branch in (("RIGHT-TEMA", "Tema Newtown"), ("WRONG-KASOA", "Kasoa")):
        domain["db"].integration_discoveries.insert_one({
            "source_system": "smartliving", "discovery_type": "agent", "external_key": agent_id.casefold(),
            "external_id": agent_id, "external_display_name": agent_id.replace("-", " ").title(), "currently_observed": True,
            "relationship": {"status": "resolved", "reason": None, "agent_id": agent_id,
                "agent_display_name": agent_id.replace("-", " ").title(), "manager_id": "SL-EDEM",
                "direct_branch": branch, "direct_branch_options": [branch], "manager_branch_options": []},
        })
    preview = {item["agent_id"]: item for item in integration.preview_agent_provisioning(str(domain["admin"]))["agents"]}
    assert preview["RIGHT-TEMA"]["status"] == "eligible" and preview["RIGHT-TEMA"]["manager_name"] == "Edem Kwak"
    assert preview["WRONG-KASOA"]["status"] == "needs_review"
    assert preview["WRONG-KASOA"]["branch_name"] == "Branch B" and preview["WRONG-KASOA"]["manager_branch_name"] == "Branch A"
    assert "BRANCH_CONFLICT" in preview["WRONG-KASOA"]["error_codes"]


def test_manual_agent_resolution_remains_authoritative_after_discovery_refresh(domain):
    integration.create_mapping("branch", {"external_code": "Smart Branch A", "fleetops_id": str(domain["a"])}, str(domain["admin"]))
    domain["db"].branches.update_one({"_id": domain["a"]}, {"$set": {"manager_ids": [domain["manager_a"]]}})
    integration.create_mapping("manager", {"external_id": "SOURCE-MANAGER", "fleetops_id": str(domain["manager_b"])}, str(domain["admin"]))
    discovery_id = domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "manual-agent",
        "external_id": "MANUAL-AGENT", "external_display_name": None, "currently_observed": True,
        "relationship": {"status": "conflicting", "reason": "conflicting_agent_manager_branch", "manager_id": "SOURCE-MANAGER"},
    }).inserted_id
    resolved = integration.resolve_agent_provisioning(str(discovery_id), {
        "agent_name": "Confirmed Agent", "branch_id": str(domain["a"]), "manager_id": str(domain["manager_a"]),
    }, str(domain["admin"]))
    assert resolved["status"] == "eligible"

    rows = {"completed-cards": [{
        "_id": "NEW", "created_at": "2026-08-24T00:00:00Z", "agent_id": "MANUAL-AGENT",
        "agent_name": "Source Changed Name", "agent_branch": "Unknown Branch", "manager_id": "SOURCE-MANAGER",
    }], "closed-cards": []}
    integration.discover_source_values(str(domain["admin"]), source_rows=rows)
    refreshed = integration.preview_agent_provisioning(str(domain["admin"]))["agents"][0]
    assert refreshed["status"] == "eligible" and refreshed["name"] == "Confirmed Agent"
    assert refreshed["branch_id"] == str(domain["a"]) and refreshed["manager_id"] == str(domain["manager_a"])


def test_backfill_persists_only_confirmed_manager_branch_aliases_and_is_idempotent(domain):
    integration.create_mapping("branch", {
        "external_code": "Tema Newtown", "fleetops_id": str(domain["a"]),
    }, str(domain["admin"]))
    discovery_id = manager_discovery(
        domain, manager_id="SL-EDEM", name="Edem Kwak", branch="Tema Newtown",
        branch_keys=["tema", "tema newtown"],
    )
    domain["db"].integration_discoveries.update_one({"_id": discovery_id}, {"$set": {
        "manager_provisioning_resolution": {
            "branch_id": domain["a"], "resolved_by": domain["admin"],
        },
    }})

    dry_run = integration.backfill_provisioning_mappings({"apply": False}, str(domain["admin"]))
    assert dry_run["confirmed_branch_aliases_created"] == 1
    assert domain["db"].integration_mappings.count_documents({"mapping_type": "branch"}) == 1

    applied = integration.backfill_provisioning_mappings({"apply": True}, str(domain["admin"]))
    repeated = integration.backfill_provisioning_mappings({"apply": True}, str(domain["admin"]))
    alias = domain["db"].integration_mappings.find_one({"mapping_type": "branch", "external_key": "tema"})
    assert applied["confirmed_branch_aliases_created"] == 1
    assert repeated["confirmed_branch_aliases_created"] == 0
    assert alias["fleetops_id"] == domain["a"]
    assert domain["db"].integration_mappings.count_documents({"mapping_type": "branch"}) == 2


def test_unique_index_preflight_refuses_duplicates_without_deleting_data():
    db = mongomock.MongoClient().index_safety
    duplicate_mapping = {"source_system": "smartliving", "mapping_type": "branch", "external_key": "hq"}
    db.integration_mappings.insert_many([{**duplicate_mapping, "marker": 1}, {**duplicate_mapping, "marker": 2}])
    duplicate_order = {"source_system": "smartliving", "source_type": "delivery_card", "source_record_id": "DUP"}
    db.delivery_orders.insert_many([{**duplicate_order, "marker": 1}, {**duplicate_order, "marker": 2}])
    with patch.object(integration, "get_collection", side_effect=lambda name: db[name]), pytest.raises(RuntimeError, match="duplicate mapping keys"):
        integration.ensure_mapping_unique_index()
    with patch.object(delivery, "get_collection", side_effect=lambda name: db[name]), pytest.raises(RuntimeError, match="duplicate source identities"):
        delivery.ensure_source_identity_unique_index()
    assert db.integration_mappings.count_documents({}) == 2
    assert db.delivery_orders.count_documents({}) == 2


def test_preview_period_rejects_reversed_date_range_without_side_effects(domain):
    with pytest.raises(ApiError) as error:
        integration.dry_run_import(
            str(domain["admin"]),
            {"source": "both", "from_date": "2026-08-10", "to_date": "2026-08-01"},
            source_rows={"completed-cards": [], "closed-cards": []},
        )
    assert error.value.status_code == 400
    assert "cannot be after" in str(error.value)
    assert domain["db"].delivery_orders.count_documents({}) == 0
    assert domain["db"].integration_dry_runs.count_documents({}) == 0


def test_period_preview_does_not_rebuild_or_stale_discovery_cache(domain):
    domain["db"].integration_discoveries.insert_one({
        "source_system": "smartliving", "discovery_type": "agent", "external_key": "cached-agent",
        "external_id": "CACHED-AGENT", "external_display_name": "Cached Name", "currently_observed": True,
    })
    with patch.object(integration, "discover_source_values") as discover:
        integration.dry_run_import(
            str(domain["admin"]), {"source": "completed-cards", "from_date": "2026-08-03", "to_date": "2026-08-09"},
            source_rows={"completed-cards": []},
        )
    discover.assert_not_called()
    cached = domain["db"].integration_discoveries.find_one({"external_key": "cached-agent"})
    assert cached["external_display_name"] == "Cached Name" and cached["currently_observed"] is True


def test_period_fetch_stops_after_first_ordered_page_and_fetches_sources_concurrently(domain):
    calls = []

    def fake_page(base_url, api_key, endpoint, page, limit=100, stats=None):
        calls.append((endpoint, page, limit))
        if stats is not None:
            with stats["lock"]:
                stats["api_calls"] += 1
        field = "created_at" if endpoint == "completed-cards" else "at"
        return {
            "rows": [{"_id": f"{endpoint}-new", field: "2026-08-07T12:00:00Z"}, {"_id": f"{endpoint}-old", field: "2026-07-20T12:00:00Z"}],
            "pagination": {"page": page, "limit": 100, "total_pages": 13 if endpoint == "completed-cards" else 16},
        }

    app = Flask(__name__)
    with app.app_context(), patch.object(integration, "_source_configuration", return_value=("https://smartliving.invalid", "secret")), patch.object(integration, "_fetch_source_page", side_effect=fake_page):
        rows, metrics = integration.fetch_source_records(
            ["completed-cards", "closed-cards"], from_date=integration.date.fromisoformat("2026-08-01"), with_metrics=True,
        )

    assert sorted(calls) == [("closed-cards", 1, 100), ("completed-cards", 1, 100)]
    assert metrics["api_calls"] == metrics["pages_fetched"] == 2
    assert metrics["records_fetched"] == 4
    assert all(item["cutoff_reached"] for item in metrics["endpoints"].values())
    assert set(rows) == {"completed-cards", "closed-cards"}


def test_period_fetch_falls_back_to_all_pages_when_order_is_not_safe(domain):
    calls = []

    def fake_page(base_url, api_key, endpoint, page, limit=100, stats=None):
        calls.append(page)
        if stats is not None:
            with stats["lock"]:
                stats["api_calls"] += 1
        dates = {
            1: ["2026-07-01T00:00:00Z", "2026-08-07T00:00:00Z"],
            2: ["2026-06-01T00:00:00Z"],
            3: ["2026-08-05T00:00:00Z"],
        }[page]
        return {"rows": [{"_id": f"row-{page}-{index}", "created_at": value} for index, value in enumerate(dates)], "pagination": {"total_pages": 3}}

    app = Flask(__name__)
    with app.app_context(), patch.object(integration, "_source_configuration", return_value=("https://smartliving.invalid", "secret")), patch.object(integration, "_fetch_source_page", side_effect=fake_page):
        rows, metrics = integration.fetch_source_records(["completed-cards"], from_date=integration.date.fromisoformat("2026-08-01"), with_metrics=True)

    assert calls == [1, 2, 3]
    assert len(set(calls)) == len(calls)
    assert len(rows["completed-cards"]) == 4
    assert metrics["pages_fetched"] == 3
