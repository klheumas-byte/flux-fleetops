import sys
from pathlib import Path
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import services.branch_access_service as branch_access
import services.smart_living_delivery_service as delivery
from routes.smart_living_deliveries import smart_living_deliveries_bp
from utils.api_error import ApiError
from utils.errors import register_error_handlers


@pytest.fixture
def scheduler():
    db = mongomock.MongoClient().scheduler_test
    branch = ObjectId(); other_branch = ObjectId(); manager = ObjectId(); driver = ObjectId(); other_driver = ObjectId(); agent_a = ObjectId(); agent_b = ObjectId(); vehicle = ObjectId(); other_vehicle = ObjectId()
    db.branches.insert_many([{"_id": branch, "code": "HQ", "name": "Head Office", "status": "active"}, {"_id": other_branch, "code": "N", "name": "North", "status": "active"}])
    db.users.insert_many([
        {"_id": manager, "full_name": "Planner", "role": "operations_manager", "status": "active", "primary_branch_id": branch, "allowed_branch_ids": [branch]},
        {"_id": driver, "full_name": "Driver One", "role": "driver", "status": "active", "primary_branch_id": branch, "allowed_branch_ids": [branch]},
        {"_id": other_driver, "full_name": "Driver Two", "role": "driver", "status": "active", "primary_branch_id": branch, "allowed_branch_ids": [branch]},
        {"_id": agent_a, "full_name": "Agent A", "role": "field_agent", "status": "active", "primary_branch_id": branch, "allowed_branch_ids": [branch]},
        {"_id": agent_b, "full_name": "Agent B", "role": "field_agent", "status": "active", "primary_branch_id": branch, "allowed_branch_ids": [branch]},
    ])
    db.vehicles.insert_many([{"_id": vehicle, "registration_number": "GT-1", "branch_id": branch, "status": "available"}, {"_id": other_vehicle, "registration_number": "GT-2", "branch_id": branch, "status": "available"}])
    patches = [patch.object(delivery, "get_collection", side_effect=lambda name: db[name]), patch.object(branch_access, "get_collection", side_effect=lambda name: db[name]), patch.object(delivery, "create_notification"), patch.object(delivery, "write_audit")]
    for item in patches: item.start()
    delivery.ensure_indexes()
    yield {"db": db, "branch": branch, "other_branch": other_branch, "manager": manager, "driver": driver, "other_driver": other_driver, "agent_a": agent_a, "agent_b": agent_b, "vehicle": vehicle, "other_vehicle": other_vehicle}
    for item in reversed(patches): item.stop()


def order_payload(domain, reference, agent=None, converted=False):
    line = {"product_name": "Approved Sofa", "quantity": 2, "delivery_type": "CLOSED_CONTRIBUTION_CONVERSION" if converted else "FULLY_COMPLETED_PRODUCT"}
    if converted: line.update({"original_product_name": "Original Table", "original_product_value": 900, "contributed_amount": 500, "approved_delivery_value": 750})
    return {"reference_number": reference, "customer_name": f"Customer {reference}", "phone": "0200000000", "branch_id": str(domain["branch"]), "sales_agent_id": str(agent or domain["agent_a"]), "delivery_address": "Accra Central", "landmark": "Market", "requested_delivery_date": "2099-08-10", "status": "CERTIFIED", "product_lines": [line]}


def make_run(domain, orders, *, driver=None, vehicle=None):
    return delivery.create_daily_run({"branch_id": str(domain["branch"]), "delivery_date": "2099-08-10", "planned_departure_time": "08:00", "driver_id": str(driver or domain["driver"]), "vehicle_id": str(vehicle or domain["vehicle"]), "delivery_order_ids": [item["id"] for item in orders]}, str(domain["manager"]))


def test_legacy_unassigned_lookups_are_normalized_and_can_create_run(scheduler):
    legacy_driver = ObjectId()
    legacy_agent = ObjectId()
    legacy_vehicle = ObjectId()
    scheduler["db"].users.insert_many([
        {
            "_id": legacy_driver,
            "full_name": "Legacy Driver",
            "user_type": "driver",
            "active": True,
        },
        {
            "_id": legacy_agent,
            "full_name": "Legacy Sales Agent",
            "role": "sales_agent",
            "active": True,
        },
    ])
    scheduler["db"].vehicles.insert_one({
        "_id": legacy_vehicle,
        "registration_number": "LEGACY-1",
        "status": "in_service",
    })
    app = Flask(__name__)
    app.config["ENV_NAME"] = "development"
    with app.app_context():
        metadata = delivery.scheduler_metadata(str(scheduler["manager"]))
    assert metadata["drivers"]["items"]
    assert metadata["agents"]["items"]
    assert metadata["vehicles"]["items"]
    assert next(item for item in metadata["drivers"]["items"] if item["id"] == str(legacy_driver))["branch"] == "Unassigned"
    assert next(item for item in metadata["agents"]["items"] if item["id"] == str(legacy_agent))["branch"] == "Unassigned"
    assert next(item for item in metadata["vehicles"]["items"] if item["id"] == str(legacy_vehicle))["disabled_reason"] is None
    assert metadata["diagnostics"]["drivers"]["returned"] >= 1

    order = delivery.create_certified_order(
        order_payload(scheduler, "LEGACY-RUN", legacy_agent),
        str(scheduler["manager"]),
    )
    run = delivery.create_daily_run({
        "branch_id": str(scheduler["branch"]),
        "delivery_date": "2099-08-10",
        "planned_departure_time": "08:00",
        "driver_id": str(legacy_driver),
        "vehicle_id": str(legacy_vehicle),
        "delivery_order_ids": [order["id"]],
    }, str(scheduler["manager"]))
    assert run["driver_id"] == str(legacy_driver)
    assert run["vehicle_id"] == str(legacy_vehicle)


def test_certified_delivery_supports_multiple_products_and_conversion_reference(scheduler):
    payload = order_payload(scheduler, "CERT-1", converted=True)
    payload["product_lines"].append({"product_name": "Wardrobe", "quantity": 1, "delivery_type": "OTHER_APPROVED_PRODUCT"})
    order = delivery.create_certified_order(payload, str(scheduler["manager"]))
    assert order["status"] == "CERTIFIED"
    assert len(order["product_lines"]) == 2
    assert order["product_lines"][0]["original_product_name"] == "Original Table"
    assert order["product_lines"][0]["product_name"] == "Approved Sofa"


def test_daily_run_manual_order_publish_lock_and_assigned_visibility(scheduler):
    first = delivery.create_certified_order(order_payload(scheduler, "CERT-1", scheduler["agent_a"]), str(scheduler["manager"]))
    second = delivery.create_certified_order(order_payload(scheduler, "CERT-2", scheduler["agent_b"]), str(scheduler["manager"]))
    run = make_run(scheduler, [first, second])
    reversed_stops = [run["stops"][1], run["stops"][0]]
    updated = delivery.update_daily_run(run["id"], {"stops": reversed_stops}, str(scheduler["manager"]))
    assert [item["customer_name"] for item in updated["stops"]] == ["Customer CERT-2", "Customer CERT-1"]
    assert [item["sequence_number"] for item in updated["stops"]] == [1, 2]
    published = delivery.publish_daily_run(run["id"], str(scheduler["manager"]))
    assert published["status"] == "PUBLISHED"
    assert published["review"]["valid"] is True
    locked = delivery.lock_daily_run(run["id"], str(scheduler["manager"]))
    assert locked["status"] == "LOCKED" and locked["locked_at"]
    driver_runs = delivery.list_daily_runs(str(scheduler["driver"]), {}, assigned_only=True)
    agent_runs = delivery.list_daily_runs(str(scheduler["agent_b"]), {}, assigned_only=True)
    assert driver_runs["count"] == 1 and agent_runs["count"] == 1
    assert [stop["customer_name"] for stop in agent_runs["runs"][0]["stops"] if stop["agent_id"] == str(scheduler["agent_b"])] == ["Customer CERT-2"]
    assert delivery.list_daily_runs(str(scheduler["manager"]), {}, loading_only=True)["count"] == 1


def test_draft_is_private_and_publish_is_idempotent_for_assigned_driver(scheduler):
    order = delivery.create_certified_order(
        order_payload(scheduler, "PUBLISH-BOUNDARY", scheduler["agent_a"]),
        str(scheduler["manager"]),
    )
    run = make_run(scheduler, [order])

    assert delivery.list_daily_runs(
        str(scheduler["driver"]), {}, assigned_only=True,
    )["count"] == 0
    assert delivery.list_daily_runs(
        str(scheduler["other_driver"]), {}, assigned_only=True,
    )["count"] == 0
    before_publish = delivery.list_field_agent_deliveries(
        str(scheduler["agent_a"]), {},
    )["deliveries"][0]
    assert before_publish["planning_status"] == "AWAITING_PLANNING"
    assert before_publish["driver"] is None
    assert before_publish["vehicle"] is None
    assert before_publish["delivery_date"] is None

    published = delivery.publish_daily_run(run["id"], str(scheduler["manager"]))
    repeated = delivery.publish_daily_run(run["id"], str(scheduler["manager"]))

    assert published["status"] == repeated["status"] == "PUBLISHED"
    stored = scheduler["db"].delivery_batches.find_one({"_id": ObjectId(run["id"])})
    assert len(stored["route_versions"]) == 1
    assert delivery.list_daily_runs(
        str(scheduler["driver"]), {}, assigned_only=True,
    )["count"] == 1
    assert delivery.list_daily_runs(
        str(scheduler["other_driver"]), {}, assigned_only=True,
    )["count"] == 0
    after_publish = delivery.list_field_agent_deliveries(
        str(scheduler["agent_a"]), {},
    )["deliveries"][0]
    assert after_publish["planning_status"] == "PUBLISHED"
    assert after_publish["driver"]["name"] == "Driver One"
    assert after_publish["vehicle"]["name"] == "GT-1"
    assert after_publish["stop_sequence"] == 1


def test_driver_cannot_open_planning_queue_or_unscoped_runs(scheduler):
    with pytest.raises(ApiError) as queue_error:
        delivery.list_scheduler_queue(str(scheduler["driver"]), {})
    assert queue_error.value.status_code == 403
    with pytest.raises(ApiError) as run_error:
        delivery.list_daily_runs(str(scheduler["driver"]), {})
    assert run_error.value.status_code == 403


def test_driver_workspace_overrides_inherited_planner_permissions(scheduler):
    scheduler["db"].users.update_one(
        {"_id": scheduler["driver"]},
        {"$set": {
            "role_ids": ["driver", "operations_manager"],
            "selected_workspace": "driver",
        }},
    )
    order = delivery.create_certified_order(
        order_payload(scheduler, "DRIVER-WORKSPACE"), str(scheduler["manager"])
    )
    run = make_run(scheduler, [order])

    with pytest.raises(ApiError) as queue_error:
        delivery.list_scheduler_queue(str(scheduler["driver"]), {})
    assert queue_error.value.status_code == 403
    with pytest.raises(ApiError) as runs_error:
        delivery.list_daily_runs(str(scheduler["driver"]), {})
    assert runs_error.value.status_code == 403
    with pytest.raises(ApiError) as publish_error:
        delivery.publish_daily_run(run["id"], str(scheduler["driver"]))
    assert publish_error.value.status_code == 403
    assert delivery.list_daily_runs(
        str(scheduler["driver"]), {}, assigned_only=True
    )["count"] == 0

    delivery.publish_daily_run(run["id"], str(scheduler["manager"]))
    assert delivery.list_daily_runs(
        str(scheduler["driver"]), {}, assigned_only=True
    )["count"] == 1
    assert delivery.list_daily_runs(
        str(scheduler["driver"]), {}, loading_only=True
    )["count"] == 1


def test_planner_workspace_keeps_multi_role_admin_access(scheduler):
    scheduler["db"].users.update_one(
        {"_id": scheduler["manager"]},
        {"$set": {
            "role_ids": ["operations_manager", "driver"],
            "selected_workspace": "operations_manager",
        }},
    )
    delivery.create_certified_order(
        order_payload(scheduler, "PLANNER-WORKSPACE"), str(scheduler["manager"])
    )
    assert delivery.list_scheduler_queue(
        str(scheduler["manager"]), {}
    )["pagination"]["total"] == 1


def test_driver_direct_http_calls_cannot_bypass_assignment_scope(scheduler):
    scheduler["db"].users.update_one(
        {"_id": scheduler["driver"]},
        {"$set": {
            "role_ids": ["driver", "operations_manager"],
            "selected_workspace": "driver",
        }},
    )
    order = delivery.create_certified_order(
        order_payload(scheduler, "HTTP-SCOPE"), str(scheduler["manager"])
    )
    make_run(scheduler, [order])
    app = Flask(__name__)
    app.config.update(
        JWT_SECRET_KEY="delivery-scheduler-scope-test-secret-32",
        TESTING=True,
    )
    JWTManager(app)
    register_error_handlers(app)
    app.register_blueprint(
        smart_living_deliveries_bp, url_prefix="/api/smart-living-deliveries"
    )
    with app.app_context():
        token = create_access_token(
            identity=str(scheduler["driver"]),
            additional_claims={"role": "driver"},
        )
    headers = {"Authorization": f"Bearer {token}"}
    with patch("utils.decorators.get_collection", side_effect=lambda name: scheduler["db"][name]):
        client = app.test_client()
        assert client.get(
            "/api/smart-living-deliveries/scheduler/queue", headers=headers
        ).status_code == 403
        assert client.get(
            "/api/smart-living-deliveries/scheduler/runs", headers=headers
        ).status_code == 403
        assigned = client.get(
            "/api/smart-living-deliveries/scheduler/assigned", headers=headers
        )
    assert assigned.status_code == 200
    assert assigned.get_json()["data"]["count"] == 0


def test_driver_and_vehicle_conflicts_prevent_publish(scheduler):
    first = delivery.create_certified_order(order_payload(scheduler, "CERT-1"), str(scheduler["manager"]))
    delivery.publish_daily_run(make_run(scheduler, [first])["id"], str(scheduler["manager"]))
    second = delivery.create_certified_order(order_payload(scheduler, "CERT-2"), str(scheduler["manager"]))
    conflicting = make_run(scheduler, [second], vehicle=scheduler["other_vehicle"])
    with pytest.raises(ApiError) as error:
        delivery.publish_daily_run(conflicting["id"], str(scheduler["manager"]))
    assert error.value.status_code == 409
    assert "driver" in " ".join(error.value.errors).lower()
    third = delivery.create_certified_order(order_payload(scheduler, "CERT-3"), str(scheduler["manager"]))
    vehicle_conflict = make_run(scheduler, [third], driver=scheduler["other_driver"])
    with pytest.raises(ApiError) as vehicle_error:
        delivery.publish_daily_run(vehicle_conflict["id"], str(scheduler["manager"]))
    assert "vehicle" in " ".join(vehicle_error.value.errors).lower()


def test_open_vehicle_movement_returns_actionable_publish_error_without_partial_publish(scheduler):
    order = delivery.create_certified_order(
        order_payload(scheduler, "OPEN-MOVEMENT"), str(scheduler["manager"])
    )
    run = make_run(scheduler, [order])
    scheduler["db"].vehicle_movements.insert_one(
        {
            "_id": ObjectId(),
            "movement_id": "VM-OPEN-1",
            "vehicle_id": scheduler["vehicle"],
            "status": "approved",
            "source_key": "dispatch_job:existing",
        }
    )

    with pytest.raises(ApiError) as error:
        delivery.publish_daily_run(run["id"], str(scheduler["manager"]))

    assert error.value.status_code == 409
    assert "VM-OPEN-1" in error.value.message
    assert "close or return" in error.value.message.lower()
    stored_run = scheduler["db"].delivery_batches.find_one(
        {"_id": ObjectId(run["id"])}
    )
    stored_order = scheduler["db"].delivery_orders.find_one(
        {"_id": ObjectId(order["id"])}
    )
    assert stored_run["status"] == "DRAFT"
    assert stored_order["status"] == "CERTIFIED"


def test_scheduler_dtos_resolve_readable_names(scheduler):
    order = delivery.create_certified_order(
        order_payload(scheduler, "READABLE", scheduler["agent_a"]),
        str(scheduler["manager"]),
    )
    queue_order = delivery.list_scheduler_queue(
        str(scheduler["manager"]), {}
    )["orders"][0]
    assert queue_order["branch"]["name"] == "Head Office"
    assert queue_order["agent"]["name"] == "Agent A"
    assert queue_order["source_reference"] == "READABLE"
    run = make_run(scheduler, [order])
    assert run["branch"]["name"] == "Head Office"
    assert run["driver"]["name"] == "Driver One"
    assert run["vehicle"]["name"] == "GT-1"


def test_post_publish_update_increments_version_and_locked_override_is_guarded(scheduler):
    order = delivery.create_certified_order(order_payload(scheduler, "CERT-1"), str(scheduler["manager"]))
    run = delivery.publish_daily_run(make_run(scheduler, [order])["id"], str(scheduler["manager"]))
    changed = delivery.update_daily_run(run["id"], {"planned_departure_time": "09:00"}, str(scheduler["manager"]))
    assert changed["version"] == 2
    assert len(changed["route_versions"]) == 2
    delivery.lock_daily_run(run["id"], str(scheduler["manager"]))
    with pytest.raises(ApiError) as denied:
        delivery.update_daily_run(run["id"], {"planned_departure_time": "10:00", "reason": "Road closure"}, str(scheduler["manager"]))
    assert denied.value.status_code == 403
    scheduler["db"].users.update_one({"_id": scheduler["manager"]}, {"$set": {"permission_grants": ["delivery_runs.override_lock"]}})
    corrected = delivery.update_daily_run(run["id"], {"planned_departure_time": "10:00", "reason": "Road closure"}, str(scheduler["manager"]))
    assert corrected["version"] == 3
    assert corrected["route_versions"][-1]["change_summary"] == ["planned_departure_time"]


def test_queue_and_runs_enforce_branch_scope(scheduler):
    delivery.create_certified_order(order_payload(scheduler, "CERT-1"), str(scheduler["manager"]))
    scheduler["db"].delivery_orders.insert_one({"reference_number": "OTHER", "external_reference": "OTHER", "external_source": "FleetOps Manual", "customer_name": "Other", "branch_id": scheduler["other_branch"], "status": "CERTIFIED", "product_lines": [{"product_name": "Desk", "quantity": 1}], "created_at": delivery.now_utc()})
    queue = delivery.list_scheduler_queue(str(scheduler["manager"]), {})
    assert [item["reference_number"] for item in queue["orders"]] == ["CERT-1"]


def test_completed_stop_cannot_be_removed_from_run(scheduler):
    first = delivery.create_certified_order(order_payload(scheduler, "CERT-1"), str(scheduler["manager"]))
    second = delivery.create_certified_order(order_payload(scheduler, "CERT-2"), str(scheduler["manager"]))
    run = make_run(scheduler, [first, second])
    completed_id = run["stops"][0]["stop_id"]
    scheduler["db"].delivery_batches.update_one(
        {"_id": ObjectId(run["id"]), "stops.stop_id": completed_id},
        {"$set": {"stops.0.status": "COMPLETED"}},
    )
    with pytest.raises(ApiError) as error:
        delivery.update_daily_run(run["id"], {"stops": [run["stops"][1]]}, str(scheduler["manager"]))
    assert error.value.status_code == 409
    assert "completed stops" in error.value.message.lower()


def _published_and_accepted(scheduler, reference="EXEC-1", extra_lines=None):
    payload = order_payload(scheduler, reference)
    payload["product_lines"].extend(extra_lines or [])
    order = delivery.create_certified_order(payload, str(scheduler["manager"]))
    run = delivery.publish_daily_run(make_run(scheduler, [order])["id"], str(scheduler["manager"]))
    accepted = delivery.accept_run_assignment(run["id"], str(scheduler["driver"]))
    return order, accepted


def test_issue_excludes_closed_products_and_rejects_over_issue(scheduler):
    order, run = _published_and_accepted(scheduler, extra_lines=[{
        "product_name": "Closed chair", "quantity": 1,
        "delivery_type": "FULLY_COMPLETED_PRODUCT", "status": "CLOSED_PRODUCT",
    }])
    ready = order["product_lines"][0]
    with pytest.raises(ApiError) as excessive:
        delivery.issue_scheduler_run(run["id"], {"items": [{
            "delivery_order_id": order["id"], "line_id": ready["line_id"], "issued_quantity": 3,
        }]}, str(scheduler["manager"]))
    assert excessive.value.status_code == 409
    issue = delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    assert [item["product_name"] for item in issue["items"]] == ["Approved Sofa"]
    assert issue["closed_lines"][0]["instruction"] == "DO NOT LOAD OR DELIVER"
    assert delivery.get_daily_run(run["id"], str(scheduler["manager"]))["status"] == "ITEMS_ISSUED"


def test_driver_ownership_and_disputed_custody_block_execution(scheduler):
    _, run = _published_and_accepted(scheduler)
    delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    with pytest.raises(ApiError) as stranger:
        delivery.respond_to_custody(run["id"], {"decision": "ACCEPT"}, str(scheduler["other_driver"]))
    assert stranger.value.status_code == 403
    disputed = delivery.respond_to_custody(run["id"], {"decision": "DISPUTE", "reason": "One carton damaged"}, str(scheduler["driver"]))
    assert disputed["custody_status"] == "DISPUTED"
    with pytest.raises(ApiError) as blocked:
        delivery.start_scheduler_run(run["id"], {}, str(scheduler["driver"]))
    assert blocked.value.status_code == 409


def test_sequential_driver_execution_balances_each_line_and_hands_off(scheduler):
    order, run = _published_and_accepted(scheduler)
    delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    delivery.respond_to_custody(run["id"], {"decision": "ACCEPT"}, str(scheduler["driver"]))
    started = delivery.start_scheduler_run(run["id"], {}, str(scheduler["driver"]))
    stop = started["stops"][0]; line = order["product_lines"][0]
    delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "ARRIVE"}, str(scheduler["driver"]))
    with pytest.raises(ApiError) as unbalanced:
        delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "OUTCOME", "outcome": "PARTIALLY_COMPLETED", "reason": "Customer requested partial", "items": [{"line_id": line["line_id"], "quantity_delivered": 1, "quantity_undelivered": 0}]}, str(scheduler["driver"]))
    assert unbalanced.value.status_code == 409
    finished_stop = delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "OUTCOME", "outcome": "PARTIALLY_COMPLETED", "items": [{"line_id": line["line_id"], "quantity_delivered": 1, "quantity_undelivered": 1, "reason": "Customer requested partial"}]}, str(scheduler["driver"]))
    assert finished_stop["stops"][0]["status"] == "PARTIAL"
    completed = delivery.complete_scheduler_run(run["id"], str(scheduler["driver"]))
    assert completed["status"] == "AWAITING_RECONCILIATION"
    handoff = delivery.handoff_scheduler_returns(run["id"], str(scheduler["manager"]))
    assert handoff["status"] == "AWAITING_RECONCILIATION"


def test_twenty_customer_batch_is_ordered_and_paginated(scheduler):
    customer_orders = [
        delivery.create_certified_order(order_payload(scheduler, f"BULK-{index:02d}"), str(scheduler["manager"]))
        for index in range(20)
    ]
    run = make_run(scheduler, customer_orders)
    assert len(run["stops"]) == 20
    assert [item["sequence_number"] for item in run["stops"]] == list(range(1, 21))
    page = delivery.list_daily_runs(str(scheduler["manager"]), {"page": "1", "page_size": "1"})
    assert page["pagination"] == {"page": 1, "page_size": 1, "total": 1, "total_pages": 1}


def test_issue_manifest_totals_serials_and_duplicate_prevention(scheduler):
    order, run = _published_and_accepted(scheduler)
    line = order["product_lines"][0]
    issue = delivery.issue_scheduler_run(run["id"], {"total_issued_quantity": 2, "items": [{"delivery_order_id": order["id"], "line_id": line["line_id"], "issued_quantity": 2, "serial_numbers": ["SOFA-1", "SOFA-2"]}]}, str(scheduler["manager"]))
    assert issue["total_expected_quantity"] == issue["total_issued_quantity"] == 2
    assert issue["items"][0]["serial_numbers"] == ["SOFA-1", "SOFA-2"]
    repeated = delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    assert repeated["id"] == issue["id"]
    assert scheduler["db"].item_issues.count_documents({"batch_id": ObjectId(run["id"])}) == 1


def test_full_and_failed_stops_automatically_await_reconciliation(scheduler):
    first = delivery.create_certified_order(order_payload(scheduler, "OUTCOME-1"), str(scheduler["manager"]))
    second = delivery.create_certified_order(order_payload(scheduler, "OUTCOME-2"), str(scheduler["manager"]))
    run = delivery.publish_daily_run(make_run(scheduler, [first, second])["id"], str(scheduler["manager"]))
    delivery.accept_run_assignment(run["id"], str(scheduler["driver"]))
    delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    delivery.respond_to_custody(run["id"], {"decision": "ACCEPT", "note": "Manifest verified"}, str(scheduler["driver"]))
    started = delivery.start_scheduler_run(run["id"], {}, str(scheduler["driver"]))
    for index, stop in enumerate(started["stops"]):
        delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "ARRIVE"}, str(scheduler["driver"]))
        line = stop["products"][0]; issued = int(line["quantity_issued"])
        outcome = {"action": "OUTCOME", "outcome": "COMPLETED" if index == 0 else "FAILED", "recipient_name": "Customer One" if index == 0 else None, "items": [{"line_id": line["line_id"], "quantity_delivered": issued if index == 0 else 0, "quantity_undelivered": 0 if index == 0 else issued}]}
        if index: outcome["reason"] = "Customer unavailable"
        result = delivery.update_scheduler_stop(run["id"], stop["stop_id"], outcome, str(scheduler["driver"]))
    assert result["status"] == "AWAITING_RECONCILIATION"
    stored = scheduler["db"].delivery_orders.find_one({"_id": ObjectId(first["id"])})
    assert stored["product_lines"][0]["delivery_outcome"] == "FULLY_DELIVERED"


def _awaiting_reconciliation(scheduler, reference="RETURN-1", delivered=0):
    order, run = _published_and_accepted(scheduler, reference)
    delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    delivery.respond_to_custody(run["id"], {"decision": "ACCEPT"}, str(scheduler["driver"]))
    started = delivery.start_scheduler_run(run["id"], {}, str(scheduler["driver"]))
    stop = started["stops"][0]; line = stop["products"][0]; issued = int(line["quantity_issued"])
    delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "ARRIVE"}, str(scheduler["driver"]))
    result = delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "OUTCOME", "outcome": "COMPLETED" if delivered == issued else "FAILED", "reason": None if delivered == issued else "Customer unavailable", "items": [{"line_id": line["line_id"], "quantity_delivered": delivered, "quantity_undelivered": issued - delivered}]}, str(scheduler["driver"]))
    return order, result, line


def test_phase5_full_damaged_return_reconciliation_and_closure(scheduler):
    order, run, line = _awaiting_reconciliation(scheduler)
    returned = delivery.receive_scheduler_returns(run["id"], {"items": [{"delivery_order_id": order["id"], "line_id": line["line_id"], "returned_quantity": 2, "condition": "DAMAGED", "return_reason": "Customer unavailable"}]}, str(scheduler["manager"]))
    assert returned["total_returned_quantity"] == 2 and returned["items"][0]["condition"] == "DAMAGED"
    repeated = delivery.receive_scheduler_returns(run["id"], {}, str(scheduler["manager"]))
    assert repeated["id"] == returned["id"]
    reconciled = delivery.reconcile_scheduler_batch(run["id"], {"note": "All goods accounted for"}, str(scheduler["manager"]))
    assert reconciled["status"] == "RECONCILED" and reconciled["reconciliation_summary"]["balanced"] is True
    closed = delivery.close_scheduler_batch(run["id"], {"note": "Close accountability cycle"}, str(scheduler["manager"]))
    assert closed["status"] == "CLOSED" and closed["locked"] is True
    assert scheduler["db"].item_issues.find_one({"batch_id": ObjectId(run["id"])})["locked"] is True
    assert scheduler["db"].item_returns.find_one({"batch_id": ObjectId(run["id"])})["locked"] is True
    report = delivery.delivery_accountability_report(str(scheduler["manager"]), {})
    assert report["totals"]["batches"] == 1 and report["totals"]["closed"] == 1


def test_phase5_partial_and_missing_return_needs_approved_exception(scheduler):
    order, run, line = _awaiting_reconciliation(scheduler, "RETURN-2")
    returned = delivery.receive_scheduler_returns(run["id"], {"items": [{"delivery_order_id": order["id"], "line_id": line["line_id"], "returned_quantity": 1, "condition": "GOOD", "return_reason": "One unit missing"}]}, str(scheduler["manager"]))
    assert returned["total_returned_quantity"] == 1
    with pytest.raises(ApiError) as mismatch:
        delivery.reconcile_scheduler_batch(run["id"], {}, str(scheduler["manager"]))
    assert mismatch.value.status_code == 409
    exception = delivery.create_delivery_exception(run["id"], {"delivery_order_id": order["id"], "line_id": line["line_id"], "category": "MISSING_ITEM", "severity": "HIGH", "description": "One issued unit was not returned", "responsible_department": "OPERATIONS"}, str(scheduler["manager"]))
    delivery.update_delivery_exception(exception["id"], {"status": "UNDER_REVIEW", "note": "Count verified"}, str(scheduler["manager"]))
    resolved = delivery.update_delivery_exception(exception["id"], {"status": "RESOLVED", "resolution": "Approved operational loss", "approved_exception_quantity": 1}, str(scheduler["manager"]))
    assert resolved["approved_exception_quantity"] == 1
    assert delivery.reconcile_scheduler_batch(run["id"], {}, str(scheduler["manager"]))["status"] == "RECONCILED"


def test_phase5_multiple_partial_receipts_accumulate_and_dedupe(scheduler):
    order, run, line = _awaiting_reconciliation(scheduler, "RETURN-PARTIAL-TWICE")
    first_payload = {"_idempotency_key": "receipt-1", "items": [{"delivery_order_id": order["id"], "line_id": line["line_id"], "returned_quantity": 1, "condition": "GOOD", "return_reason": "Second unit is on another vehicle"}]}
    first = delivery.receive_scheduler_returns(run["id"], first_payload, str(scheduler["manager"]))
    repeated = delivery.receive_scheduler_returns(run["id"], first_payload, str(scheduler["manager"]))
    assert first["total_returned_quantity"] == repeated["total_returned_quantity"] == 1
    assert first["total_outstanding_quantity"] == 1

    second = delivery.receive_scheduler_returns(run["id"], {"_idempotency_key": "receipt-2", "items": [{"delivery_order_id": order["id"], "line_id": line["line_id"], "returned_quantity": 1, "condition": "PACKAGING_DAMAGED", "return_reason": "Final unit received"}]}, str(scheduler["manager"]))
    assert second["total_returned_quantity"] == 2
    assert second["total_outstanding_quantity"] == 0
    assert len(second["receiving_events"]) == 2
    summary = delivery.reconciliation_summary(scheduler["db"].delivery_batches.find_one({"_id": ObjectId(run["id"])}))
    assert summary["balanced"] is True
    assert summary["lines"][0]["reconciliation_status"] == "BALANCED"


def test_phase5_only_flagged_exceptions_can_be_investigated(scheduler):
    order, run, line = _awaiting_reconciliation(scheduler, "RETURN-NO-INVESTIGATION")
    exception = delivery.create_delivery_exception(run["id"], {"delivery_order_id": order["id"], "line_id": line["line_id"], "category": "OTHER", "severity": "LOW", "description": "Routine clarification"}, str(scheduler["manager"]))
    assert exception["requires_investigation"] is False
    with pytest.raises(ApiError) as blocked:
        delivery.investigate_delivery_exception(exception["id"], {"assigned_investigator_id": str(scheduler["manager"]), "status": "UNDER_REVIEW"}, str(scheduler["manager"]))
    assert blocked.value.status_code == 409


def test_phase5_exception_idempotency_key_prevents_duplicate_submission(scheduler):
    order, run, line = _awaiting_reconciliation(scheduler, "RETURN-IDEMPOTENT")
    payload = {"_idempotency_key": "mobile-submit-1", "delivery_order_id": order["id"], "line_id": line["line_id"], "category": "OTHER", "severity": "LOW", "description": "Customer note requires review"}
    first = delivery.create_delivery_exception(run["id"], payload, str(scheduler["manager"]))
    second = delivery.create_delivery_exception(run["id"], payload, str(scheduler["manager"]))
    assert first["id"] == second["id"]
    assert scheduler["db"].delivery_exceptions.count_documents({"delivery_batch_id": ObjectId(run["id"])}) == 1


def test_phase5_critical_exception_investigation_blocks_until_completed(scheduler):
    order, run, line = _awaiting_reconciliation(scheduler, "RETURN-3")
    delivery.receive_scheduler_returns(run["id"], {"items": [{"delivery_order_id": order["id"], "line_id": line["line_id"], "returned_quantity": 1, "condition": "GOOD", "return_reason": "Theft suspected"}]}, str(scheduler["manager"]))
    exception = delivery.create_delivery_exception(run["id"], {"delivery_order_id": order["id"], "line_id": line["line_id"], "category": "THEFT", "severity": "CRITICAL", "description": "One unit missing after route"}, str(scheduler["manager"]))
    with pytest.raises(ApiError) as critical:
        delivery.reconcile_scheduler_batch(run["id"], {}, str(scheduler["manager"]))
    assert "critical" in critical.value.message.lower()
    delivery.update_delivery_exception(exception["id"], {"status": "UNDER_REVIEW"}, str(scheduler["manager"]))
    with pytest.raises(ApiError) as required:
        delivery.update_delivery_exception(exception["id"], {"status": "RESOLVED", "approved_exception_quantity": 1}, str(scheduler["manager"]))
    assert "investigation" in required.value.message.lower()
    investigation = delivery.investigate_delivery_exception(exception["id"], {"assigned_investigator_id": str(scheduler["manager"]), "status": "CLOSED", "findings": "Custody loss confirmed", "resolution": "Approved loss", "corrective_action": "Dual-count at vehicle"}, str(scheduler["manager"]))
    assert investigation["closed_at"]
    delivery.update_delivery_exception(exception["id"], {"status": "RESOLVED", "approved_exception_quantity": 1, "resolution": "Investigation complete"}, str(scheduler["manager"]))
    assert delivery.reconcile_scheduler_batch(run["id"], {}, str(scheduler["manager"]))["status"] == "RECONCILED"


def test_phase5_reconciles_multiple_products_for_one_customer(scheduler):
    payload = order_payload(scheduler, "RETURN-MULTI")
    payload["product_lines"].append({"product_name": "Wardrobe", "quantity": 1, "delivery_type": "FULLY_COMPLETED_PRODUCT"})
    order = delivery.create_certified_order(payload, str(scheduler["manager"]))
    run = delivery.publish_daily_run(make_run(scheduler, [order])["id"], str(scheduler["manager"]))
    delivery.accept_run_assignment(run["id"], str(scheduler["driver"]))
    delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    delivery.respond_to_custody(run["id"], {"decision": "ACCEPT"}, str(scheduler["driver"]))
    started = delivery.start_scheduler_run(run["id"], {}, str(scheduler["driver"]))
    stop = started["stops"][0]
    delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "ARRIVE"}, str(scheduler["driver"]))
    outcomes = []
    receipts = []
    for product in stop["products"]:
        issued = int(product["quantity_issued"])
        delivered = max(issued - 1, 0)
        outcomes.append({"line_id": product["line_id"], "quantity_delivered": delivered, "quantity_undelivered": issued - delivered})
        receipts.append({"delivery_order_id": order["id"], "line_id": product["line_id"], "returned_quantity": issued - delivered, "condition": "GOOD"})
    delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "OUTCOME", "outcome": "PARTIAL", "reason": "Customer accepted part of the order", "items": outcomes}, str(scheduler["driver"]))
    delivery.receive_scheduler_returns(run["id"], {"items": receipts}, str(scheduler["manager"]))
    summary = delivery.reconciliation_summary(scheduler["db"].delivery_batches.find_one({"_id": ObjectId(run["id"])}))
    assert len(summary["lines"]) == 2
    assert summary["balanced"] is True
    assert {line["product_name"] for line in summary["lines"]} == {"Approved Sofa", "Wardrobe"}


def test_phase5_authorized_reopen_requires_reason(scheduler):
    order, run, line = _awaiting_reconciliation(scheduler, "RETURN-4")
    delivery.receive_scheduler_returns(run["id"], {"items": [{"delivery_order_id": order["id"], "line_id": line["line_id"], "returned_quantity": 2, "condition": "GOOD"}]}, str(scheduler["manager"]))
    delivery.reconcile_scheduler_batch(run["id"], {}, str(scheduler["manager"])); delivery.close_scheduler_batch(run["id"], {}, str(scheduler["manager"]))
    with pytest.raises(ApiError) as reason:
        delivery.reopen_scheduler_batch(run["id"], {}, str(scheduler["manager"]))
    assert reason.value.status_code == 400
    reopened = delivery.reopen_scheduler_batch(run["id"], {"reason": "Audit recount required"}, str(scheduler["manager"]))
    assert reopened["status"] == "REOPENED" and reopened["locked"] is False


def test_kaya_run_is_ready_without_driver_or_vehicle_and_reuses_execution(scheduler):
    order = delivery.create_certified_order(order_payload(scheduler, "KAYA-1"), str(scheduler["manager"]))
    run = delivery.create_daily_run({
        "branch_id": str(scheduler["branch"]), "delivery_date": "2099-08-10", "planned_departure_time": "08:00",
        "transport_method": "KAYA", "manual_transport": {"provider_name": "Kojo Kaya", "phone": "0201234567", "agreed_cost": 45, "notes": "Call before loading"},
        "delivery_order_ids": [order["id"]],
    }, str(scheduler["manager"]))
    assert run["transport_method"] == "KAYA" and run["driver_id"] is None and run["vehicle_id"] is None
    assert run["readiness"] == "READY" and not any("driver" in item.lower() or "vehicle" in item.lower() for item in run["review"]["errors"])
    published = delivery.publish_daily_run(run["id"], str(scheduler["manager"]))
    delivery.accept_run_assignment(published["id"], str(scheduler["agent_a"]))
    delivery.issue_scheduler_run(run["id"], {}, str(scheduler["manager"]))
    custody = delivery.respond_to_custody(run["id"], {"decision": "ACCEPT"}, str(scheduler["agent_a"]))
    assert custody["custody_holder_id"] == str(scheduler["agent_a"]) and custody.get("driver_id") is None
    started = delivery.start_scheduler_run(run["id"], {}, str(scheduler["agent_a"]))
    stop = started["stops"][0]; line = stop["products"][0]
    delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "ARRIVE"}, str(scheduler["agent_a"]))
    completed = delivery.update_scheduler_stop(run["id"], stop["stop_id"], {"action": "OUTCOME", "outcome": "COMPLETED", "recipient_name": "Customer", "items": [{"line_id": line["line_id"], "quantity_delivered": line["quantity_issued"], "quantity_undelivered": 0}]}, str(scheduler["agent_a"]))
    assert completed["status"] == "AWAITING_RECONCILIATION"
    assert delivery.reconcile_scheduler_batch(run["id"], {}, str(scheduler["manager"]))["status"] == "RECONCILED"


def test_manual_transport_requires_handler_but_legacy_run_remains_vehicle(scheduler):
    first = delivery.create_certified_order(order_payload(scheduler, "KAYA-MISSING"), str(scheduler["manager"]))
    manual = delivery.create_daily_run({"branch_id": str(scheduler["branch"]), "delivery_date": "2099-08-10", "planned_departure_time": "08:00", "transport_method": "OTHER_MANUAL", "delivery_order_ids": [first["id"]]}, str(scheduler["manager"]))
    assert manual["readiness"] != "READY"
    assert any("handler" in item.lower() for item in manual["review"]["errors"])
    second = delivery.create_certified_order(order_payload(scheduler, "LEGACY-VEHICLE"), str(scheduler["manager"]))
    legacy = make_run(scheduler, [second])
    assert legacy["transport_method"] == "VEHICLE" and legacy["readiness"] == "READY"


def test_temporary_company_driver_is_available_to_branch_planner(scheduler):
    company_driver = ObjectId()
    scheduler["db"].users.insert_one({"_id": company_driver, "full_name": "HQ Relief Driver", "role": "driver", "status": "active", "operational_scope": "COMPANY_WIDE"})
    app = Flask(__name__); app.config["ENV_NAME"] = "development"
    with patch.object(delivery, "driver_ids_visible_to_branch_user", return_value={scheduler["driver"], company_driver}), app.app_context():
        metadata = delivery.scheduler_metadata(str(scheduler["manager"]))
    assert str(company_driver) in {item["id"] for item in metadata["drivers"]["items"]}
