from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from unittest.mock import patch
import sys

import mongomock
import pytest
from bson import ObjectId
from flask import Flask

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import assignment_service, fault_service, maintenance_service, operations_control_service, vehicle_availability_service, vehicle_movement_service
from utils.api_error import ApiError


class CountingCollection:
    def __init__(self, collection, name, counts, lock):
        self._collection = collection
        self._name = name
        self._counts = counts
        self._lock = lock

    def find(self, *args, **kwargs):
        with self._lock:
            self._counts[self._name] += 1
        return self._collection.find(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._collection, name)


@pytest.fixture
def control_domain():
    db = mongomock.MongoClient(tz_aware=True).operations_control
    counts = Counter()
    lock = Lock()

    def collection(name):
        return CountingCollection(db[name], name, counts, lock)

    app = Flask(__name__)
    with (
        app.app_context(),
        patch.object(operations_control_service, "get_collection", side_effect=collection),
        patch.object(vehicle_availability_service, "get_collection", side_effect=collection),
        patch.object(vehicle_movement_service, "get_collection", side_effect=collection),
        patch.object(assignment_service, "get_collection", side_effect=collection),
    ):
        yield db, counts


def test_control_center_batches_queries_and_groups_multiple_blockers(control_domain):
    db, counts = control_domain
    vehicle_id = ObjectId()
    driver_ids = [ObjectId() for _ in range(20)]
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "TEST-01", "status": "available"})
    db.users.insert_many([
        {"_id": driver_id, "role": "driver", "full_name": f"Driver {index}", "status": "active", "driver_profile": {"approval_status": "approved"}}
        for index, driver_id in enumerate(driver_ids)
    ])
    db.vehicle_movements.insert_one({
        "_id": ObjectId(), "movement_id": "VM-ACTIVE", "vehicle_id": vehicle_id,
        "driver_id": driver_ids[0], "status": "in_progress", "movement_type": "dispatch",
    })
    db.resource_reservations.insert_many([
        {"_id": ObjectId(), "resource_id": vehicle_id, "reservation_type": "vehicle", "status": "consumed", "end_time": datetime.now(timezone.utc) - timedelta(hours=1)},
        {"_id": ObjectId(), "resource_id": driver_ids[0], "reservation_type": "driver", "status": "consumed", "end_time": datetime.now(timezone.utc) - timedelta(hours=1)},
    ])
    db.maintenance_jobs.insert_one({"_id": ObjectId(), "maintenance_id": "M-1", "vehicle_id": vehicle_id, "status": "in_progress"})

    result = operations_control_service.get_control_center(current_role="owner")

    vehicle_group = next(group for group in result["groups"] if group["asset_id"] == str(vehicle_id))
    assert {item["kind"] for item in vehicle_group["blockers"]} >= {"movement", "reservation", "maintenance"}
    assert counts["users"] == 1
    assert counts["resource_reservations"] == 2
    assert counts["dispatch_jobs"] == 2
    assert counts["vehicle_movements"] == 3


def test_stale_reservation_force_release_requires_confirmation_and_recalculates(control_domain):
    db, _counts = control_domain
    actor_id = ObjectId()
    vehicle_id = ObjectId()
    reservation_id = db.resource_reservations.insert_one({
        "resource_id": vehicle_id, "reservation_type": "vehicle", "status": "reserved",
        "end_time": datetime.now(timezone.utc) - timedelta(days=1),
    }).inserted_id
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "TEST-02", "status": "available"})

    with pytest.raises(ApiError, match="physical"):
        operations_control_service.execute_control_action(
            {"action": "release_reservation", "reservation_id": str(reservation_id), "reason": "Expired lock"},
            current_user_id=str(actor_id), current_role="admin",
        )

    operations_control_service.execute_control_action(
        {
            "action": "release_reservation", "reservation_id": str(reservation_id), "reason": "Expired lock",
            "physical_state_confirmed": True, "confirmation": "FORCE RELEASE",
        },
        current_user_id=str(actor_id), current_role="admin",
    )
    reservation = db.resource_reservations.find_one({"_id": reservation_id})
    refreshed = operations_control_service.get_control_center(current_role="admin")
    vehicle = next(item for item in refreshed["vehicles"] if item["id"] == str(vehicle_id))
    assert reservation["status"] == "released"
    assert reservation["audit_log"][-1]["actor_id"] == actor_id
    assert vehicle["is_available"] is True


@pytest.mark.parametrize(
    ("resolution", "expected_status", "expected_disposition", "needs_confirmation"),
    [
        ("physically_completed", "awaiting_receipt", "force_completed", True),
        ("cancelled", "cancelled", "cancelled", True),
        ("stale_incorrect_record", "cancelled", "voided", True),
    ],
)
def test_resolve_terminal_movement_reconciles_active_source(
    control_domain, resolution, expected_status, expected_disposition, needs_confirmation,
):
    db, _counts = control_domain
    actor_id, vehicle_id, driver_id, source_id, movement_id = (ObjectId() for _ in range(5))
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "RECOVER-01", "status": "available"})
    db.users.insert_one({"_id": driver_id, "role": "driver", "full_name": "Recovery Driver", "status": "active", "driver_profile": {"approval_status": "approved"}})
    db.stock_transfers.insert_one({
        "_id": source_id, "transfer_id": "ST-RECOVER", "status": "released",
        "vehicle_id": vehicle_id, "driver_id": driver_id,
        "linked_vehicle_movement_id": movement_id, "updated_at": datetime.now(timezone.utc),
    })
    db.vehicle_movements.insert_one({
        "_id": movement_id, "movement_id": "VM-TERMINAL", "status": "force_closed",
        "vehicle_id": vehicle_id, "driver_id": driver_id, "source_type": "stock_transfer",
        "source_id": source_id, "source_key": f"stock_transfer:{source_id}",
    })
    reservation_id = db.resource_reservations.insert_one({
        "resource_id": vehicle_id, "reservation_type": "vehicle", "status": "consumed",
        "source_id": source_id, "movement_id": movement_id,
    }).inserted_id
    issue = {
        "kind": "terminal_link", "blocker_type": "active_source_terminal_movement",
        "source_type": "stock_transfers", "source_id": str(source_id), "movement_id": str(movement_id),
    }
    payload = {"action": "resolve", "resolution": resolution, "reason": "Confirmed recovery outcome", "issue": issue}
    if needs_confirmation:
        payload.update({"physical_state_confirmed": True, "confirmation": "FORCE RELEASE"})

    result = operations_control_service.execute_control_action(
        payload, current_user_id=str(actor_id), current_role="owner",
    )

    source = db.stock_transfers.find_one({"_id": source_id})
    assert source["status"] == expected_status
    assert source["recovery_disposition"] == expected_disposition
    assert source["audit_log"][-1]["resolution"] == resolution
    assert db.vehicle_movements.find_one({"_id": movement_id})["status"] == "force_closed"
    assert db.resource_reservations.find_one({"_id": reservation_id})["status"] == "released"
    assert "control_center" not in result
    refreshed = operations_control_service.get_control_center(current_role="owner")
    assert not any(item["id"] == f"terminal_link:{movement_id}" for item in refreshed["issues"])


def test_screenshot_regression_physically_completed_active_supplier_pickup(control_domain):
    db, _counts = control_domain
    actor_id, vehicle_id, driver_id, source_id, movement_id = (ObjectId() for _ in range(5))
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "GW-9783-25", "status": "available"})
    db.users.insert_one({"_id": driver_id, "role": "driver", "full_name": "Jerry Sowah", "status": "active", "driver_profile": {"approval_status": "approved"}})
    db.stock_transfers.insert_one({
        "_id": source_id, "transfer_id": "SP-RECOVERY", "operation_type": "supplier_pickup",
        "status": "released", "vehicle_id": vehicle_id, "driver_id": driver_id,
        "linked_vehicle_movement_id": movement_id,
    })
    db.vehicle_movements.insert_one({
        "_id": movement_id, "movement_id": "VM-20260917110624-84D9EB", "status": "in_progress",
        "movement_type": "supplier_pickup", "source_type": "supplier_pickup", "source_id": source_id,
        "source_key": f"supplier_pickup:{source_id}", "vehicle_id": vehicle_id, "driver_id": driver_id,
        "started_at": datetime.now(timezone.utc) - timedelta(hours=2),
    })
    reservation_id = db.resource_reservations.insert_one({
        "resource_id": vehicle_id, "reservation_type": "vehicle", "status": "consumed",
        "movement_id": movement_id, "source_id": source_id,
    }).inserted_id

    result = operations_control_service.execute_control_action(
        {
            "action": "resolve", "resolution": "physically_completed", "reason": "Fully completed",
            "physical_state_confirmed": True, "confirmation": "FORCE RELEASE",
            "issue": {
                "kind": "movement", "source_type": "supplier_pickup", "source_id": str(source_id),
                "movement_id": str(movement_id), "vehicle_id": str(vehicle_id), "driver_id": str(driver_id),
            },
        },
        current_user_id=str(actor_id), current_role="admin",
    )

    assert result["action"] == "resolve" and "control_center" not in result
    assert db.vehicle_movements.find_one({"_id": movement_id})["status"] == "force_closed"
    assert db.stock_transfers.find_one({"_id": source_id})["status"] == "awaiting_receipt"
    assert db.resource_reservations.find_one({"_id": reservation_id})["status"] == "released"


def test_resolve_continue_and_reassignment_dispatch_to_contextual_actions(control_domain):
    db, _counts = control_domain
    actor_id, source_id, movement_id = ObjectId(), ObjectId(), ObjectId()
    db.stock_transfers.insert_one({"_id": source_id, "transfer_id": "ST-CONTINUE", "status": "released"})
    issue = {
        "kind": "terminal_link", "blocker_type": "active_source_terminal_movement",
        "source_type": "stock_transfers", "source_id": str(source_id), "movement_id": str(movement_id),
    }
    with patch.object(operations_control_service, "_restart_source_movement", return_value={"type": "vehicle_movement", "id": str(ObjectId()), "status": "approved"}) as restart:
        operations_control_service.execute_control_action(
            {"action": "resolve", "resolution": "continue_operation", "reason": "Continue required", "issue": issue},
            current_user_id=str(actor_id), current_role="admin",
        )
    restart.assert_called_once()

    operations_control_service.execute_control_action(
        {"action": "resolve", "resolution": "reassignment_required", "reason": "Driver unavailable", "issue": issue},
        current_user_id=str(actor_id), current_role="admin",
    )
    source = db.stock_transfers.find_one({"_id": source_id})
    assert source["status"] == "released"
    assert source["audit_log"][-1]["event"] == "reassignment_required"


def test_stale_reservation_resolution_does_not_close_its_linked_movement(control_domain):
    db, _counts = control_domain
    actor_id, vehicle_id, movement_id = ObjectId(), ObjectId(), ObjectId()
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "RES-01", "status": "available"})
    db.vehicle_movements.insert_one({"_id": movement_id, "vehicle_id": vehicle_id, "status": "closed"})
    reservation_id = db.resource_reservations.insert_one({
        "resource_id": vehicle_id, "reservation_type": "vehicle", "status": "consumed",
        "movement_id": movement_id, "end_time": datetime.now(timezone.utc) - timedelta(hours=1),
    }).inserted_id
    operations_control_service.execute_control_action(
        {
            "action": "resolve", "resolution": "stale_incorrect_record", "reason": "Stale lock",
            "physical_state_confirmed": True, "confirmation": "FORCE RELEASE",
            "issue": {"kind": "reservation", "reservation_id": str(reservation_id), "movement_id": str(movement_id)},
        },
        current_user_id=str(actor_id), current_role="owner",
    )
    assert db.resource_reservations.find_one({"_id": reservation_id})["status"] == "released"
    assert db.vehicle_movements.find_one({"_id": movement_id})["status"] == "closed"


def test_force_release_rejects_a_valid_future_reservation(control_domain):
    db, _counts = control_domain
    actor_id, vehicle_id = ObjectId(), ObjectId()
    reservation_id = db.resource_reservations.insert_one({
        "resource_id": vehicle_id, "reservation_type": "vehicle", "status": "reserved",
        "end_time": datetime.now(timezone.utc) + timedelta(hours=2),
    }).inserted_id
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "TEST-VALID", "status": "available"})
    with pytest.raises(ApiError, match="not stale"):
        operations_control_service.execute_control_action(
            {
                "action": "release_reservation", "reservation_id": str(reservation_id), "reason": "Should not release",
                "physical_state_confirmed": True, "confirmation": "FORCE RELEASE",
            },
            current_user_id=str(actor_id), current_role="owner",
        )
    assert db.resource_reservations.find_one({"_id": reservation_id})["status"] == "reserved"


def test_force_release_assignment_preserves_valid_maintenance_block(control_domain):
    db, _counts = control_domain
    actor_id, vehicle_id, driver_id = ObjectId(), ObjectId(), ObjectId()
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "TEST-03", "status": "assigned", "assigned_driver_id": driver_id})
    db.users.insert_one({"_id": driver_id, "role": "driver", "full_name": "Assigned Driver", "status": "active", "driver_profile": {"approval_status": "approved", "assigned_vehicle_id": vehicle_id}})
    assignment_id = db.assignments.insert_one({
        "vehicle_id": vehicle_id, "driver_id": driver_id, "status": "active", "allocation_active": True,
        "expected_end_at": datetime.now(timezone.utc) - timedelta(days=1), "handover_status": "accepted",
    }).inserted_id
    maintenance_id = db.maintenance_jobs.insert_one({"vehicle_id": vehicle_id, "status": "in_progress"}).inserted_id

    operations_control_service.execute_control_action(
        {
            "action": "release_assignment", "assignment_id": str(assignment_id), "reason": "Vehicle returned to depot",
            "physical_state_confirmed": True, "confirmation": "FORCE RELEASE",
        },
        current_user_id=str(actor_id), current_role="owner",
    )

    assert db.assignments.find_one({"_id": assignment_id})["status"] == "ended"
    assert db.vehicles.find_one({"_id": vehicle_id})["status"] == "maintenance"
    refreshed = operations_control_service.get_control_center(current_role="owner")
    vehicle = next(item for item in refreshed["vehicles"] if item["id"] == str(vehicle_id))
    assert vehicle["is_available"] is False
    assert any(item["entity_id"] == str(maintenance_id) for item in vehicle["blocking_reasons"])


def test_frontend_control_load_is_deduplicated_and_recheck_uses_get():
    root = Path(__file__).resolve().parents[2]
    api_source = (root / "src/app/lib/operations-control-api.ts").read_text(encoding="utf-8")
    component_source = (root / "src/app/components/admin/OperationsControlCenter.tsx").read_text(encoding="utf-8")
    assert "dedupeKey: 'GET:operations-control'" in api_source
    assert "useEffect(() => { void load(); }, [load])" in component_source
    assert "runOperationsControlAction({ action: 'recheck'" not in component_source
    assert "submitInFlight.current" in component_source
    assert "resolutionOptionsFor(selection.issue)" in component_source
    assert 'role="alert"' in component_source
    assert "setData(await fetchOperationsControl())" in component_source
    assert "control_center: unknown" not in api_source


def test_admin_fault_reporting_is_discoverable_and_does_not_submit_admin_as_driver():
    root = Path(__file__).resolve().parents[2]
    component_source = (root / "src/app/components/driver/ReportFault.tsx").read_text(encoding="utf-8")
    sidebar_source = (root / "src/app/components/admin/Sidebar.tsx").read_text(encoding="utf-8")
    access_source = (root / "src/app/lib/role-access.ts").read_text(encoding="utf-8")
    assert "{ id: 'report-fault', label: 'Report Vehicle Fault'" in sidebar_source
    assert "driver_id: isAdministrativeReporter ? undefined : currentUser?.id" in component_source
    assert "operations_administrator: OPERATIONS_ADMIN_ACCESS" in access_source
    assert "system_administrator: SYSTEM_ADMIN_ACCESS" in access_source
    assert "if (roleAccess) return true" in access_source
    assert "stored.permission_denials?.includes(permission)" in access_source


def test_control_context_timing_labels_overdue_and_lazy_timeline(control_domain):
    db, _counts = control_domain
    now = datetime.now(timezone.utc)
    vehicle_id, driver_id, movement_id = ObjectId(), ObjectId(), ObjectId()
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "CTX-01", "status": "available", "assigned_driver_id": driver_id})
    db.users.insert_one({"_id": driver_id, "role": "driver", "full_name": "Context Driver", "status": "active", "driver_profile": {"approval_status": "approved"}})
    db.vehicle_movements.insert_one({
        "_id": movement_id, "movement_id": "VM-CTX", "vehicle_id": vehicle_id, "driver_id": driver_id,
        "status": "in_progress", "movement_type": "dispatch", "title": "Collect stock", "origin": "Depot", "destination": "Branch",
        "requested_departure_time": now - timedelta(hours=3), "expected_return_time": now - timedelta(hours=1),
        "started_at": now - timedelta(hours=2), "updated_at": now - timedelta(minutes=30),
        "status_history": [{"status": "in_progress", "timestamp": now - timedelta(hours=2), "actor_id": driver_id}],
    })

    result = operations_control_service.get_control_center(current_role="owner")
    group = next(item for item in result["groups"] if item["asset_id"] == str(vehicle_id))
    issue = next(item for item in group["blockers"] if item["kind"] == "movement")
    assert issue["driver_label"] == "Context Driver"
    assert issue["vehicle_label"] == "CTX-01"
    assert issue["task"] == "Collect stock" and issue["origin"] == "Depot" and issue["destination"] == "Branch"
    assert issue["overdue_seconds"] >= 3500 and issue["unresolved_seconds"] >= 1700
    assert group["recovery_state"] == "recovery_required"

    timeline = operations_control_service.get_control_timeline(
        current_role="owner", source_type="movement", source_id=str(movement_id), movement_id=str(movement_id),
    )
    assert len(timeline["records"]) == 1
    assert timeline["events"][0]["event"] == "in_progress"


@pytest.mark.parametrize("reporter_role", ["owner", "admin", "operations_administrator", "system_administrator"])
def test_admin_roles_fault_without_driver_uses_existing_workflow_and_blocks_unsafe_vehicle(control_domain, reporter_role):
    db, _counts = control_domain
    owner_id, vehicle_id, category_id, component_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "FAULT-01", "status": "available"})
    db.fault_categories.insert_one({"_id": category_id, "name": "Brakes", "code": "brakes", "status": "active"})
    db.fault_components.insert_one({"_id": component_id, "category_id": category_id, "name": "Pads", "code": "pads", "status": "active"})
    collection = lambda name: db[name]
    with (
        patch.object(fault_service, "get_collection", side_effect=collection),
        patch.object(fault_service, "create_notification"), patch.object(fault_service, "notify_roles"),
        patch.object(fault_service, "notify_linked_owner"), patch.object(fault_service, "log_db_duration"),
    ):
        created = fault_service.create_fault({
            "vehicle_id": str(vehicle_id), "category_id": str(category_id), "component_id": str(component_id),
            "severity": "critical", "description": "Brake pressure lost", "vehicle_unsafe": True,
            "detected_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        }, str(owner_id), reporter_role)
    document = db.faults.find_one({"_id": ObjectId(created["id"])})
    assert document["driver_id"] is None and document["reporter_role"] == reporter_role
    assert document["detected_at"] < document["reported_at"]
    assert db.vehicles.find_one({"_id": vehicle_id})["status"] == "maintenance"


def test_completed_maintenance_releases_only_after_last_safety_blocker(control_domain):
    db, _counts = control_domain
    vehicle_id, job_id = ObjectId(), ObjectId()
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "SAFE-01", "status": "maintenance"})
    db.maintenance_jobs.insert_one({"_id": job_id, "vehicle_id": vehicle_id, "status": "completed"})
    vehicle = db.vehicles.find_one({"_id": vehicle_id})
    collection = lambda name: db[name]
    with patch.object(maintenance_service, "get_collection", side_effect=collection):
        db.faults.insert_one({"vehicle_id": vehicle_id, "status": "approved", "severity": "critical", "vehicle_unsafe": True})
        maintenance_service._restore_vehicle_status_after_completion(vehicle, excluding_maintenance_job_id=job_id)
        assert db.vehicles.find_one({"_id": vehicle_id})["status"] == "maintenance"
        db.faults.update_many({}, {"$set": {"status": "resolved"}})
        maintenance_service._restore_vehicle_status_after_completion(vehicle, excluding_maintenance_job_id=job_id)
        assert db.vehicles.find_one({"_id": vehicle_id})["status"] == "available"


def test_driver_fault_reporting_regression_keeps_driver_scope(control_domain):
    db, _counts = control_domain
    driver_id, vehicle_id, category_id, component_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "DRV-FAULT", "status": "available", "assigned_driver_id": driver_id})
    db.users.insert_one({"_id": driver_id, "role": "driver", "full_name": "Reporting Driver", "status": "active"})
    db.fault_categories.insert_one({"_id": category_id, "name": "Engine", "code": "engine", "status": "active"})
    db.fault_components.insert_one({"_id": component_id, "category_id": category_id, "name": "Oil", "code": "oil", "status": "active"})
    with (
        patch.object(fault_service, "get_collection", side_effect=lambda name: db[name]),
        patch.object(fault_service, "_validate_driver_fault_scope", return_value=(driver_id, vehicle_id)) as scope,
        patch.object(fault_service, "create_notification"), patch.object(fault_service, "notify_roles"),
        patch.object(fault_service, "notify_linked_owner"), patch.object(fault_service, "log_db_duration"),
    ):
        created = fault_service.create_fault({
            "vehicle_id": str(vehicle_id), "driver_id": str(driver_id), "category_id": str(category_id),
            "component_id": str(component_id), "severity": "medium", "description": "Oil warning", "vehicle_unsafe": False,
        }, str(driver_id), "driver")
    scope.assert_called_once()
    document = db.faults.find_one({"_id": ObjectId(created["id"])})
    assert document["driver_id"] == driver_id and document["reporter_role"] == "driver"
    assert db.vehicles.find_one({"_id": vehicle_id})["status"] == "available"


def test_unsafe_fault_maintenance_requires_roadworthy_confirmation(control_domain):
    db, _counts = control_domain
    actor_id, vehicle_id, fault_id, job_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
    db.vehicles.insert_one({"_id": vehicle_id, "registration_number": "ROAD-01", "status": "maintenance"})
    db.faults.insert_one({"_id": fault_id, "vehicle_id": vehicle_id, "status": "converted_to_maintenance", "severity": "critical", "vehicle_unsafe": True})
    db.maintenance_jobs.insert_one({
        "_id": job_id, "maintenance_id": "M-ROAD", "vehicle_id": vehicle_id, "fault_report_id": fault_id,
        "status": "in_progress", "priority": "critical", "title": "Brake repair", "maintenance_type": "repair",
        "transport_required": False, "created_at": datetime.now(timezone.utc),
    })
    patches = (
        patch.object(maintenance_service, "get_collection", side_effect=lambda name: db[name]),
        patch.object(maintenance_service, "_append_vehicle_maintenance_history"),
        patch.object(maintenance_service, "_process_maintenance_reminders"),
        patch.object(maintenance_service, "_enrich_maintenance_job", side_effect=lambda document: document),
        patch("services.maintenance_override_service.close_overrides_for_issue"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        with pytest.raises(ApiError, match="Roadworthy confirmation"):
            maintenance_service.update_maintenance_status(str(job_id), "completed", {"work_performed": "Repaired"}, str(actor_id), "owner")
        maintenance_service.update_maintenance_status(
            str(job_id), "completed", {"work_performed": "Repaired and inspected", "roadworthy_confirmed": True}, str(actor_id), "owner",
        )
    assert db.maintenance_jobs.find_one({"_id": job_id})["roadworthy_confirmed"] is True
    assert db.faults.find_one({"_id": fault_id})["status"] == "resolved"
    assert db.vehicles.find_one({"_id": vehicle_id})["status"] == "available"
