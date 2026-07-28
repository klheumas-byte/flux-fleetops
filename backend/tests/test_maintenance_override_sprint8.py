from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import maintenance_override_service as overrides
from services import vehicle_availability_service as availability
from utils.api_error import ApiError


class StrictCollection:
    """Match PyMongo's refusal to treat Collection objects as booleans."""

    def __init__(self, collection):
        self._collection = collection

    def __bool__(self):
        raise NotImplementedError("Collection objects do not implement truth value testing")

    def __getattr__(self, name):
        return getattr(self._collection, name)


class MaintenanceOverrideTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).maintenance_overrides
        self.owner_id = ObjectId(); self.admin_id = ObjectId(); self.driver_id = ObjectId()
        self.fleet_account_id = ObjectId(); self.fleet_owner_id = ObjectId(); self.vehicle_id = ObjectId()
        self.maintenance_id = ObjectId(); self.fault_id = ObjectId()
        self.db.users.insert_many([
            {"_id": self.owner_id, "role": "owner", "status": "active"},
            {"_id": self.admin_id, "role": "admin", "status": "active"},
            {"_id": self.driver_id, "role": "driver", "status": "active"},
            {"_id": self.fleet_account_id, "role": "fleet_owner", "status": "active"},
        ])
        self.db.fleet_owners.insert_one({"_id": self.fleet_owner_id, "account_id": self.fleet_account_id, "status": "active"})
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "REST-1", "status": "maintenance", "assigned_driver_id": self.driver_id, "fleet_owner_id": self.fleet_owner_id})
        self.db.maintenance_jobs.insert_one({"_id": self.maintenance_id, "vehicle_id": self.vehicle_id, "status": "in_progress", "priority": "high"})
        self.db.faults.insert_one({"_id": self.fault_id, "vehicle_id": self.vehicle_id, "status": "approved", "severity": "high", "vehicle_unsafe": False})
        self.db.assignments.insert_one({"_id": ObjectId(), "vehicle_id": self.vehicle_id, "driver_id": self.driver_id, "allocation_active": True})
        self.db.maintenance_availability_overrides.create_index(
            [("linked_record_type", 1), ("linked_record_id", 1)], unique=True,
            partialFilterExpression={"status": "active"},
        )
        patches = [
            patch.object(overrides, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(availability, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(overrides, "notify_linked_owner"), patch.object(overrides, "notify_roles"),
            patch.object(overrides, "create_notification"),
        ]
        for item in patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])

    def payload(self, **changes):
        now = overrides.now_utc()
        value = {
            "vehicle_id": str(self.vehicle_id), "linked_record_type": "maintenance",
            "linked_record_id": str(self.maintenance_id), "operational_restriction": "Daylight city trips only",
            "business_justification": "Temporary service continuity while parts arrive",
            "start_at": now.isoformat(), "repair_deadline": (now + timedelta(days=2)).isoformat(),
            "reminder_hours_before": 12, "maximum_mileage": 200, "notes": "Review daily",
        }
        value.update(changes); return value

    def test_eligible_issue_creates_conditional_availability(self):
        created = overrides.create_override(self.payload(), str(self.admin_id), "admin")
        result = availability.resolve_vehicle_availability(self.vehicle_id)
        self.assertEqual(created["status"], "active")
        self.assertTrue(result["is_available"])
        self.assertEqual(result["operational_state"], "available_with_restriction")
        self.assertEqual(result["active_restrictions"][0]["operational_restriction"], "Daylight city trips only")

    def test_critical_or_unsafe_issue_is_rejected(self):
        self.db.faults.update_one({"_id": self.fault_id}, {"$set": {"severity": "critical"}})
        with self.assertRaises(ApiError) as error:
            overrides.create_override(self.payload(linked_record_type="fault", linked_record_id=str(self.fault_id)), str(self.owner_id), "owner")
        self.assertEqual(error.exception.status_code, 409)

    def test_concurrent_approval_has_one_winner(self):
        def approve():
            try:
                overrides.create_override(self.payload(), str(self.admin_id), "admin"); return "created"
            except ApiError as error: return error.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _item: approve(), range(2)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count(409), 1)

    def test_driver_acknowledgement_and_repeated_action_are_idempotent(self):
        created = overrides.create_override(self.payload(), str(self.admin_id), "admin")
        first = overrides.acknowledge_override(created["id"], str(self.driver_id))
        second = overrides.acknowledge_override(created["id"], str(self.driver_id))
        self.assertEqual(len(first["acknowledgements"]), 1)
        self.assertEqual(len(second["acknowledgements"]), 1)
        revoked = overrides.transition_override(created["id"], "revoked", str(self.owner_id), "owner")
        repeated = overrides.transition_override(created["id"], "revoked", str(self.owner_id), "owner")
        self.assertEqual(revoked["status"], repeated["status"])
        self.assertFalse(availability.resolve_vehicle_availability(self.vehicle_id)["is_available"])

    def test_expiry_blocks_new_assignment_and_audits_once(self):
        created = overrides.create_override(self.payload(), str(self.admin_id), "admin")
        past = overrides.now_utc() - timedelta(minutes=1)
        self.db.maintenance_availability_overrides.update_one({"_id": ObjectId(created["id"])}, {"$set": {"repair_deadline": past}})
        self.assertFalse(availability.resolve_vehicle_availability(self.vehicle_id)["is_available"])
        self.assertEqual(self.db.maintenance_availability_overrides.find_one({"_id": ObjectId(created["id"])})["status"], "expired")
        overrides.reconcile_expired_overrides(self.vehicle_id)
        self.assertEqual(self.db.maintenance_availability_override_history.count_documents({"override_id": ObjectId(created["id"]), "action": "expired"}), 1)

    def test_linked_resolution_closes_override(self):
        created = overrides.create_override(self.payload(), str(self.admin_id), "admin")
        overrides.close_overrides_for_issue("maintenance", self.maintenance_id, self.admin_id)
        self.assertEqual(self.db.maintenance_availability_overrides.find_one({"_id": ObjectId(created["id"])})["status"], "resolved")

    def test_fleet_owner_visibility_is_vehicle_scoped(self):
        created = overrides.create_override(self.payload(), str(self.admin_id), "admin")
        rows = overrides.list_overrides(str(self.fleet_account_id), "fleet_owner")
        self.assertEqual([row["id"] for row in rows["records"]], [created["id"]])
        other_account = ObjectId(); self.db.users.insert_one({"_id": other_account, "role": "fleet_owner", "status": "active"})
        self.db.fleet_owners.insert_one({"_id": ObjectId(), "account_id": other_account, "status": "active"})
        self.assertEqual(overrides.list_overrides(str(other_account), "fleet_owner")["records"], [])

    def test_unauthorized_approval_is_denied(self):
        with self.assertRaises(ApiError) as error:
            overrides.create_override(self.payload(), str(self.driver_id), "driver")
        self.assertEqual(error.exception.status_code, 403)

    def test_injected_pymongo_collection_is_never_truth_value_tested(self):
        created = overrides.create_override(self.payload(), str(self.admin_id), "admin")
        strict_collection = StrictCollection(self.db.maintenance_availability_overrides)

        self.assertEqual(
            overrides.reconcile_expired_overrides(collection=strict_collection),
            0,
        )
        single = overrides.active_overrides_for_vehicle(
            self.vehicle_id,
            collection=strict_collection,
        )
        grouped = overrides.active_overrides_for_vehicles(
            [self.vehicle_id],
            collection=strict_collection,
        )

        self.assertEqual(str(single[0]["_id"]), created["id"])
        self.assertEqual(str(grouped[self.vehicle_id][0]["_id"]), created["id"])


if __name__ == "__main__": unittest.main()
