from unittest.mock import patch
import sys
from pathlib import Path

import mongomock
import pytest
from bson import ObjectId

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import services.auth_service as auth_service
import services.stock_transfer_service as stock
from services.rbac_service import effective_data_scope, permissions_for_user
from utils.api_error import ApiError


def _transfer(destination, number):
    return {
        "_id": ObjectId(), "transfer_id": number, "operation_type": "stock_transfer",
        "sending_location": "Head Office", "receiving_location": f"Branch {number}",
        "receiving_location_id": destination, "destination_branch_id": destination,
        "transfer_items": [{"item_id": "SKU-1", "name": "Stock item", "quantity": 5, "unit": "box"}],
        "item_count": 1, "status": "awaiting_receipt", "receiving_status": "awaiting_confirmation",
        "recipient": {"full_name": "Destination team", "primary_phone": "+233200000000"},
        "audit_log": [], "version": 1,
    }


def _collections(db):
    return lambda name: db[name]


def test_branch_roles_have_separate_least_privilege_defaults():
    manager = set(permissions_for_user({"role": "branch_manager"}))
    warehouse = set(permissions_for_user({"role": "branch_warehouse_coordinator"}))
    receiving = {
        "stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify",
        "stock_transfers.report_variance", "stock_transfers.view_history",
    }
    assert receiving <= manager
    assert receiving <= warehouse
    assert {"branches.view_assigned", "delivery_operations.view_branch", "branch_operations.view"} <= manager
    assert not ({"branches.view_assigned", "delivery_operations.view_branch", "branch_operations.view", "finance.view", "roles.manage"} & warehouse)
    assert effective_data_scope({"role": "branch_manager"}) == "PRIMARY_BRANCH"
    assert effective_data_scope({"role": "branch_warehouse_coordinator"}) == "PRIMARY_BRANCH"


def test_branch_roles_require_a_primary_branch():
    with pytest.raises(ApiError) as raised:
        auth_service._require_primary_branch_for_roles(["driver", "branch_manager"], None)
    assert raised.value.status_code == 400
    auth_service._require_primary_branch_for_roles(["branch_warehouse_coordinator"], ObjectId())


@pytest.mark.parametrize("role", ["branch_manager", "branch_warehouse_coordinator"])
def test_existing_user_creation_reuses_multi_role_and_branch_fields(role):
    db = mongomock.MongoClient()[f"create_{role}"]
    primary, additional = ObjectId(), ObjectId()
    db.branches.insert_many([
        {"_id": primary, "name": "Primary", "status": "active"},
        {"_id": additional, "name": "Additional", "status": "active"},
    ])
    payload = {
        "full_name": "Branch User", "username": f"user_{role}", "phone": "+233200000001",
        "password": "temporary-password", "status": "active", "role_ids": [role, "driver"],
        "primary_branch_id": str(primary), "allowed_branch_ids": [str(additional)],
    }
    with (
        patch.object(auth_service, "users_collection", return_value=db.users),
        patch.object(auth_service, "users_read_collection", return_value=db.users),
        patch.object(auth_service, "get_collection", side_effect=_collections(db)),
    ):
        created = auth_service.create_user(payload, role=role)
    assert created["primary_branch_id"] == str(primary)
    assert created["allowed_branch_ids"] == [str(additional)]
    assert set(created["role_ids"]) == {role, "driver"}


def test_incoming_stock_is_limited_to_primary_and_explicit_allowed_branches():
    db = mongomock.MongoClient().branch_receiving
    primary, allowed, unauthorized = ObjectId(), ObjectId(), ObjectId()
    user_id = db.users.insert_one({
        "full_name": "Multi Role Manager", "role": "driver", "role_ids": ["driver", "branch_manager"],
        "primary_branch_id": primary, "allowed_branch_ids": [allowed], "status": "active",
    }).inserted_id
    db.stock_transfers.insert_many([_transfer(primary, "ST-PRIMARY"), _transfer(allowed, "ST-ALLOWED"), _transfer(unauthorized, "ST-HIDDEN")])

    with patch.object(stock, "get_collection", side_effect=_collections(db)):
        result = stock.list_stock_transfers(
            current_user_id=str(user_id), current_role="branch_manager", operation_type="stock_transfer",
        )

    assert {item["transfer_id"] for item in result["transfers"]} == {"ST-PRIMARY", "ST-ALLOWED"}


@pytest.mark.parametrize("role,expected_name", [
    ("branch_manager", "Branch Manager"),
    ("branch_warehouse_coordinator", "Branch Warehouse Coordinator"),
])
def test_authorized_receiver_is_recorded_and_unauthorized_branch_returns_403(role, expected_name):
    db = mongomock.MongoClient()[f"receive_{role}"]
    authorized, unauthorized = ObjectId(), ObjectId()
    user_id = db.users.insert_one({
        "full_name": "Jane Receiver", "role": role, "role_ids": [role],
        "primary_branch_id": authorized, "allowed_branch_ids": [], "status": "active",
    }).inserted_id
    allowed_transfer, denied_transfer = _transfer(authorized, "ST-OK"), _transfer(unauthorized, "ST-NO")
    db.stock_transfers.insert_many([allowed_transfer, denied_transfer])

    with patch.object(stock, "get_collection", side_effect=_collections(db)):
        received = stock.receive_stock_transfer(
            str(allowed_transfer["_id"]),
            {"confirmed": True, "receiver_initials": "JR", "received_items": [{"item_id": "SKU-1", "name": "Stock item", "quantity": 5, "unit": "box"}]},
            current_user_id=str(user_id), current_role=role,
        )
        with pytest.raises(ApiError) as raised:
            stock.receive_stock_transfer(
                str(denied_transfer["_id"]),
                {"confirmed": True, "received_items": [{"item_id": "SKU-1", "name": "Stock item", "quantity": 5, "unit": "box"}]},
                current_user_id=str(user_id), current_role=role,
            )

    assert received["received_by_user_id"] == str(user_id)
    assert received["receiver_name"] == "Jane Receiver"
    assert received["receiver_role"] == expected_name
    assert received["receiving_branch_id"] == str(authorized)
    assert received["received_at"]
    assert received["actual_receiver"]["receiver_type"] == "fleetops_user"
    assert received["actual_receiver"]["user_id"] == str(user_id)
    assert received["actual_receiver"]["full_name"] == "Jane Receiver"
    assert received["actual_receiver"]["branch_id"] == str(authorized)
    assert raised.value.status_code == 403


def test_system_administrator_keeps_all_branch_visibility():
    db = mongomock.MongoClient().hq_visibility
    branch_a, branch_b = ObjectId(), ObjectId()
    user_id = db.users.insert_one({"full_name": "HQ Admin", "role": "system_administrator", "status": "active"}).inserted_id
    db.stock_transfers.insert_many([_transfer(branch_a, "ST-A"), _transfer(branch_b, "ST-B")])
    with patch.object(stock, "get_collection", side_effect=_collections(db)):
        result = stock.list_stock_transfers(current_user_id=str(user_id), current_role="system_administrator", operation_type="stock_transfer")
    assert {item["transfer_id"] for item in result["transfers"]} == {"ST-A", "ST-B"}


def test_full_receipt_is_verified_and_condition_variance_opens_exception():
    db = mongomock.MongoClient().receipt_outcomes
    branch = ObjectId()
    manager = db.users.insert_one({"full_name": "Branch Receiver", "role": "branch_manager", "role_ids": ["branch_manager"], "primary_branch_id": branch, "status": "active"}).inserted_id
    full, damaged, missing = _transfer(branch, "ST-FULL"), _transfer(branch, "ST-DAMAGED"), _transfer(branch, "ST-MISSING")
    db.stock_transfers.insert_many([full, damaged, missing])
    with patch.object(stock, "get_collection", side_effect=_collections(db)), patch.object(stock, "resolve_action_notifications"), patch.object(stock, "notify_roles"):
        verified = stock.receive_stock_transfer(str(full["_id"]), {"confirmed": True, "received_items": [{"item_id": "SKU-1", "received_quantity": 5, "good_quantity": 5, "damaged_quantity": 0, "wrong_item_quantity": 0}]}, current_user_id=str(manager), current_role="branch_manager")
        variance = stock.receive_stock_transfer(str(damaged["_id"]), {"confirmed": True, "received_items": [{"item_id": "SKU-1", "received_quantity": 5, "good_quantity": 4, "damaged_quantity": 1, "wrong_item_quantity": 0, "notes": "One crushed box"}]}, current_user_id=str(manager), current_role="branch_manager")
        partial = stock.receive_stock_transfer(str(missing["_id"]), {"confirmed": True, "received_items": [{"item_id": "SKU-1", "received_quantity": 3, "good_quantity": 3, "damaged_quantity": 0, "wrong_item_quantity": 0}]}, current_user_id=str(manager), current_role="branch_manager")
    assert verified["branch_receiving_status"] == "VERIFIED"
    assert verified["workflow_stage"] == "verified"
    assert variance["branch_receiving_status"] == "RECEIVED_WITH_VARIANCE"
    assert variance["workflow_stage"] == "received_with_variance"
    assert variance["linked_delivery_exception_id"]
    exception = db.delivery_exceptions.find_one({"_id": ObjectId(variance["linked_delivery_exception_id"])})
    assert exception["status"] == "open"
    assert exception["items"][0]["exception_type"] == "damaged"
    partial_exception = db.delivery_exceptions.find_one({"_id": ObjectId(partial["linked_delivery_exception_id"])})
    assert partial["received_items"][0]["missing_quantity"] == 2
    assert partial_exception["items"][0]["exception_type"] == "missing"
    history = db.stock_transfers.find_one({"_id": damaged["_id"]})["audit_log"]
    assert history[-1]["event"] == "branch_receipt_confirmed" and history[-1]["immutable"] is True


def test_recipient_options_only_return_eligible_users_for_selected_branch():
    db = mongomock.MongoClient().recipient_options
    branch, other = ObjectId(), ObjectId()
    db.branches.insert_many([
        {"_id": branch, "name": "Accra", "code": "ACC", "status": "active"},
        {"_id": other, "name": "Kumasi", "code": "KSI", "status": "active"},
    ])
    manager = db.users.insert_one({"full_name": "Accra Manager", "role": "branch_manager", "primary_branch_id": branch, "phone": "+233200000001", "status": "active"}).inserted_id
    coordinator = db.users.insert_one({"full_name": "Accra Store", "role_ids": ["branch_warehouse_coordinator"], "allowed_branch_ids": [branch], "phone": "+233200000002", "status": "active"}).inserted_id
    db.users.insert_many([
        {"full_name": "Other Manager", "role": "branch_manager", "primary_branch_id": other, "phone": "+233200000003", "status": "active"},
        {"full_name": "Accra Driver", "role": "driver", "primary_branch_id": branch, "phone": "+233200000004", "status": "active"},
    ])
    with patch.object(stock, "get_collection", side_effect=_collections(db)):
        result = stock.list_stock_transfer_recipient_options(branch_id=str(branch), current_user_id=str(ObjectId()), current_role="admin")
    assert {item["id"] for item in result["receivers"]} == {str(manager), str(coordinator)}
    assert {item["role"] for item in result["receivers"]} == {"branch_manager", "branch_warehouse_coordinator"}


def test_internal_recipient_is_resolved_by_id_and_wrong_branch_is_rejected():
    db = mongomock.MongoClient().internal_recipient
    branch, other = ObjectId(), ObjectId()
    db.branches.insert_many([{"_id": branch, "name": "Accra", "status": "active"}, {"_id": other, "name": "Tema", "status": "active"}])
    creator = db.users.insert_one({"full_name": "Administrator", "role": "admin", "status": "active"}).inserted_id
    receiver = db.users.insert_one({"full_name": "Real Receiver", "role": "branch_manager", "primary_branch_id": branch, "phone": "+233200000005", "email": "receiver@example.com", "status": "active"}).inserted_id
    payload = {
        "sending_location": "HQ", "receiving_location": "Accra", "receiving_location_id": str(branch),
        "requested_date": "2026-08-03", "transfer_items": [{"item_id": "SKU-1", "name": "Stock", "quantity": 2, "unit": "box"}],
        "recipient": {"recipient_user_id": str(receiver), "full_name": "Spoofed Name", "primary_phone": "+233999999999", "delivery_instructions": "Call first"},
    }
    with patch.object(stock, "get_collection", side_effect=_collections(db)):
        created = stock.create_stock_transfer(payload, current_user_id=str(creator), current_role="admin")
        with pytest.raises(ApiError) as raised:
            stock.create_stock_transfer({**payload, "receiving_location": "Tema", "receiving_location_id": str(other)}, current_user_id=str(creator), current_role="admin")
    assert created["recipient"]["recipient_user_id"] == str(receiver)
    assert created["recipient"]["recipient_type"] == "fleetops_user"
    assert created["recipient"]["full_name"] == "Real Receiver"
    assert created["recipient"]["primary_phone"] == "+233200000005"
    assert created["recipient"]["branch_id"] == str(branch)
    assert raised.value.status_code == 403


def test_external_recipient_stays_manual_and_has_no_user_identity():
    db = mongomock.MongoClient().external_recipient
    branch = ObjectId()
    db.branches.insert_one({"_id": branch, "name": "Accra", "status": "active"})
    creator = db.users.insert_one({"full_name": "Administrator", "role": "admin", "status": "active"}).inserted_id
    payload = {
        "sending_location": "HQ", "receiving_location": "Accra", "receiving_location_id": str(branch),
        "requested_date": "2026-08-03", "transfer_items": [{"item_id": "SKU-1", "name": "Stock", "quantity": 2, "unit": "box"}],
        "recipient": {"recipient_type": "external", "recipient_user_id": None, "full_name": "External Contact", "role": "Storekeeper", "primary_phone": "+233200000006", "email": "external@example.com"},
    }
    with patch.object(stock, "get_collection", side_effect=_collections(db)):
        created = stock.create_stock_transfer(payload, current_user_id=str(creator), current_role="admin")
    assert created["recipient"]["recipient_type"] == "external"
    assert created["recipient"]["recipient_user_id"] is None
    assert created["recipient"]["full_name"] == "External Contact"
    assert db.users.count_documents({"full_name": "External Contact"}) == 0


def test_planned_recipient_does_not_limit_incoming_visibility_or_replace_actual_receiver():
    db = mongomock.MongoClient().planned_actual_receiver
    branch = ObjectId()
    planned = db.users.insert_one({"full_name": "Planned Manager", "role": "branch_manager", "primary_branch_id": branch, "phone": "+233200000007", "status": "active"}).inserted_id
    actual = db.users.insert_one({"full_name": "Actual Coordinator", "role": "branch_warehouse_coordinator", "primary_branch_id": branch, "phone": "+233200000008", "status": "active"}).inserted_id
    transfer = _transfer(branch, "ST-PLANNED")
    transfer["recipient"] = {"recipient_user_id": planned, "recipient_type": "fleetops_user", "full_name": "Planned Manager", "primary_phone": "+233200000007"}
    db.stock_transfers.insert_one(transfer)
    with patch.object(stock, "get_collection", side_effect=_collections(db)), patch.object(stock, "resolve_action_notifications"), patch.object(stock, "notify_roles"):
        listed = stock.list_stock_transfers(current_user_id=str(actual), current_role="branch_warehouse_coordinator", operation_type="stock_transfer")
        received = stock.receive_stock_transfer(str(transfer["_id"]), {"confirmed": True, "received_items": [{"item_id": "SKU-1", "received_quantity": 5, "good_quantity": 5, "damaged_quantity": 0, "wrong_item_quantity": 0}]}, current_user_id=str(actual), current_role="branch_warehouse_coordinator")
    assert [item["transfer_id"] for item in listed["transfers"]] == ["ST-PLANNED"]
    assert received["recipient"]["recipient_user_id"] == str(planned)
    assert received["received_by_user_id"] == str(actual)
    assert received["receiver_name"] == "Actual Coordinator"


def test_destination_receiver_notifications_are_branch_scoped_and_deduplicated():
    db = mongomock.MongoClient().recipient_notifications
    branch, other = ObjectId(), ObjectId()
    manager = db.users.insert_one({"full_name": "Manager", "role": "branch_manager", "primary_branch_id": branch, "status": "active"}).inserted_id
    coordinator = db.users.insert_one({"full_name": "Coordinator", "role": "branch_warehouse_coordinator", "allowed_branch_ids": [branch], "status": "active"}).inserted_id
    db.users.insert_one({"full_name": "Other Manager", "role": "branch_manager", "primary_branch_id": other, "status": "active"})
    document = _transfer(branch, "ST-NOTIFY")
    calls = []
    with patch.object(stock, "get_collection", side_effect=_collections(db)), patch.object(stock, "create_notification", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))):
        stock._notify_destination_receivers(document, "Stock transfer assigned", "Assigned to branch", event="assigned")
    assert {call[0][0] for call in calls} == {manager, coordinator}
    assert len({call[1]["dedupe_key"] for call in calls}) == 2
    assert all(":destination:assigned:" in call[1]["dedupe_key"] for call in calls)


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_can_record_external_actual_receiver(role):
    db = mongomock.MongoClient()[f"external_actual_{role}"]
    branch = ObjectId()
    db.branches.insert_one({"_id": branch, "name": "Accra", "status": "active"})
    actor = db.users.insert_one({"full_name": "Operations Admin", "role": role, "phone": "+233200000020", "status": "active"}).inserted_id
    transfer = _transfer(branch, f"ST-{role.upper()}")
    transfer["recipient"] = {"recipient_type": "external", "recipient_user_id": None, "full_name": "Planned Contact", "primary_phone": "+233200000021"}
    db.stock_transfers.insert_one(transfer)
    payload = {
        "received_items": [{"item_id": "SKU-1", "received_quantity": 5, "good_quantity": 5, "damaged_quantity": 0, "wrong_item_quantity": 0}],
        "actual_receiver": {"receiver_type": "external", "full_name": "External Receiver", "role": "Storekeeper", "primary_contact": "+233200000022", "notes": "Handed over at gate"},
    }
    with patch.object(stock, "get_collection", side_effect=_collections(db)), patch.object(stock, "resolve_action_notifications"):
        received = stock.receive_stock_transfer(str(transfer["_id"]), payload, current_user_id=str(actor), current_role=role)
    assert received["received_by_user_id"] == str(actor)
    assert received["recipient"]["full_name"] == "Planned Contact"
    assert received["actual_receiver"]["receiver_type"] == "external"
    assert received["actual_receiver"]["user_id"] is None
    assert received["actual_receiver"]["full_name"] == "External Receiver"
    assert received["actual_receiver"]["primary_contact"] == "+233200000022"
