from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, jwt_required


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import assignment_service as allocations
from services import vehicle_service
from utils.api_error import ApiError
from utils.decorators import driver_mode_required


class VehicleAllocationTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_sprint4
        self.admin_id = ObjectId()
        self.driver_a = ObjectId()
        self.driver_b = ObjectId()
        self.vehicle_id = ObjectId()
        self.db.users.insert_many(
            [
                {"_id": self.admin_id, "role": "admin", "status": "active"},
                {
                    "_id": self.driver_a,
                    "role": "driver",
                    "status": "active",
                    "full_name": "Driver A",
                    "driver_profile": {"approval_status": "approved"},
                },
                {
                    "_id": self.driver_b,
                    "role": "driver",
                    "status": "active",
                    "full_name": "Driver B",
                    "driver_profile": {"approval_status": "approved"},
                },
            ]
        )
        self.db.vehicles.insert_one(
            {
                "_id": self.vehicle_id,
                "registration_number": "SPRINT-4",
                "vehicle_type": "van",
                "status": "available",
            }
        )
        self.db.assignments.create_index(
            [("vehicle_id", 1), ("allocation_active", 1)],
            unique=True,
            partialFilterExpression={"allocation_active": True},
        )
        self.db.assignments.create_index(
            [("driver_id", 1), ("allocation_active", 1)],
            unique=True,
            partialFilterExpression={"allocation_active": True},
        )
        self.patches = [
            patch.object(allocations, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(
                allocations,
                "_ensure_assignment_handover_movement",
                side_effect=lambda assignment, **_: {"_id": ObjectId()},
            ),
            patch.object(allocations, "create_wallet_entry"),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def payload(self, driver_id=None, **overrides):
        payload = {
            "driver_id": str(driver_id or self.driver_a),
            "vehicle_id": str(self.vehicle_id),
            "start_date": "2026-07-27",
            "reason": "Commercial shift allocation",
            "operating_mode": "hybrid",
            "target_enabled": True,
            "target_frequency": "weekly",
            "target_amount": 700,
            "weekly_target": 700,
            "daily_target": 100,
        }
        payload.update(overrides)
        return payload

    def create(self, driver_id=None, **overrides):
        return allocations.create_assignment(
            self.payload(driver_id, **overrides),
            str(self.admin_id),
        )

    def activate(self, assignment_id, driver_id=None):
        driver_id = driver_id or self.driver_a
        self.db.assignments.update_one(
            {"_id": ObjectId(assignment_id)},
            {"$set": {"status": "active", "handover_status": "accepted"}},
        )
        self.db.vehicles.update_one(
            {"_id": self.vehicle_id},
            {
                "$set": {
                    "assigned_driver_id": driver_id,
                    "current_custodian_id": driver_id,
                    "status": "assigned",
                },
                "$unset": {"pending_assignment_id": ""},
            },
        )
        self.db.users.update_one(
            {"_id": driver_id},
            {"$set": {"driver_profile.assigned_vehicle_id": self.vehicle_id}},
        )

    def test_assign_available_vehicle_and_store_audit_configuration(self):
        result = self.create(expected_end_at="2026-07-28T18:00:00Z")
        self.assertEqual(result["status"], "pending_handover")
        self.assertTrue(result["allocation_active"])
        self.assertEqual(result["assignment_reason"], "Commercial shift allocation")
        self.assertEqual(result["operating_mode"], "hybrid")
        self.assertTrue(result["target_enabled"])
        self.assertIsNotNone(result["expected_end_at"])

    def test_reject_second_active_allocation(self):
        self.create()
        with self.assertRaises(ApiError) as error:
            self.create(self.driver_b)
        self.assertEqual(error.exception.status_code, 409)

    def test_unassign_releases_vehicle_and_is_idempotent(self):
        created = self.create()
        first = allocations.end_assignment(
            created["id"],
            current_user_id=str(self.admin_id),
            end_reason="Shift complete",
        )
        second = allocations.end_assignment(
            created["id"],
            current_user_id=str(self.admin_id),
            end_reason="Repeated request",
        )
        self.assertEqual(first["status"], "ended")
        self.assertEqual(second["status"], "ended")
        self.assertFalse(self.db.assignments.find_one({"_id": ObjectId(created["id"])})["allocation_active"])
        self.assertEqual(self.db.vehicles.find_one({"_id": self.vehicle_id})["status"], "available")

    def test_transfer_driver_a_to_driver_b_preserves_history_links(self):
        created = self.create()
        self.activate(created["id"])
        transferred = allocations.transfer_assignment(
            created["id"],
            self.payload(self.driver_b, reason="Driver shift change"),
            current_user_id=str(self.admin_id),
        )
        previous = self.db.assignments.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(previous["status"], "ended")
        self.assertEqual(previous["transferred_to_allocation_id"], ObjectId(transferred["id"]))
        self.assertEqual(transferred["transferred_from_allocation_id"], created["id"])
        self.assertEqual(
            self.db.vehicles.find_one({"_id": self.vehicle_id})["assigned_driver_id"],
            self.driver_b,
        )

    def test_concurrent_assignment_has_one_winner(self):
        def attempt(driver_id):
            try:
                self.create(driver_id)
                return "created"
            except ApiError as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, (self.driver_a, self.driver_b)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count(409), 1)
        self.assertEqual(self.db.assignments.count_documents({"allocation_active": True}), 1)

    def test_target_disabled_does_not_create_wallet_obligation(self):
        created = self.create(
            operating_mode="operations_only",
            target_enabled=False,
            target_amount=None,
            weekly_target=None,
            daily_target=None,
        )
        document = self.db.assignments.find_one({"_id": ObjectId(created["id"])})
        allocations._activate_assignment_after_handover(document, accepted_by=self.driver_a)
        allocations.create_wallet_entry.assert_not_called()

    def test_all_operating_modes_and_invalid_combination(self):
        profile = {}
        for mode in ("operations_only", "target_only", "hybrid"):
            data = allocations._normalize_allocation_configuration(
                {
                    "operating_mode": mode,
                    "target_enabled": mode != "operations_only",
                    "target_frequency": "weekly",
                    "target_amount": None if mode == "operations_only" else 500,
                },
                profile,
            )
            self.assertEqual(data["operating_mode"], mode)
        with self.assertRaises(ApiError):
            allocations._normalize_allocation_configuration(
                {"operating_mode": "operations_only", "target_enabled": True, "target_amount": 1},
                profile,
            )

    def test_allocation_does_not_modify_booking_or_appointment_records(self):
        record_id = self.db.bookings.insert_one({"booking_id": "APPT-1", "status": "scheduled"}).inserted_id
        before = self.db.bookings.find_one({"_id": record_id})
        self.create()
        self.assertEqual(self.db.bookings.find_one({"_id": record_id}), before)


class VehicleOwnershipFoundationTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_sprint4_ownership
        self.patch = patch.object(vehicle_service, "get_collection", side_effect=lambda name: self.db[name])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def base_payload(self):
        return {
            "registration_number": "OWN-1",
            "vehicle_type": "van",
            "make": "Ford",
            "model": "Transit",
            "year": 2024,
            "transmission": "manual",
            "fuel_type": "diesel",
            "default_weekly_target": 700,
            "default_daily_target": 100,
        }

    def test_company_owned_vehicle(self):
        result = vehicle_service.normalize_vehicle_payload(
            {**self.base_payload(), "ownership_type": "company_owned"},
        )
        self.assertEqual(result["ownership_type"], "company_owned")
        self.assertIsNone(result["fleet_owner_id"])

    def test_third_party_vehicle_requires_and_links_fleet_owner(self):
        owner_id = self.db.fleet_owners.insert_one({"name": "Partner Fleet", "status": "active"}).inserted_id
        result = vehicle_service.normalize_vehicle_payload(
            {
                **self.base_payload(),
                "ownership_type": "third_party_owned",
                "fleet_owner_id": str(owner_id),
            },
        )
        self.assertEqual(result["ownership_type"], "third_party_owned")
        self.assertEqual(result["fleet_owner_id"], owner_id)
        with self.assertRaises(ApiError):
            vehicle_service.normalize_vehicle_payload(
                {**self.base_payload(), "ownership_type": "third_party_owned"},
            )


class DriverModePermissionTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_sprint4_modes
        self.app = Flask(__name__)
        self.app.config["JWT_SECRET_KEY"] = "sprint4-test-secret-key-at-least-32-bytes"
        self.app.config["MONGO_URI"] = "mongodb://sprint4-test"
        JWTManager(self.app)

        @self.app.get("/operations")
        @jwt_required()
        @driver_mode_required("operations")
        def operations_route():
            return {"ok": True}

        @self.app.get("/targets")
        @jwt_required()
        @driver_mode_required("targets")
        def targets_route():
            return {"ok": True}

        self.collection_patch = patch(
            "utils.decorators.get_collection",
            side_effect=lambda name: self.db[name],
        )
        self.collection_patch.start()
        self.addCleanup(self.collection_patch.stop)
        self.client = self.app.test_client()

    def request(self, mode, path):
        driver_id = ObjectId()
        self.db.users.insert_one(
            {
                "_id": driver_id,
                "role": "driver",
                "driver_profile": {"operating_mode": mode},
            }
        )
        with self.app.app_context():
            token = create_access_token(identity=str(driver_id), additional_claims={"role": "driver"})
        return self.client.get(path, headers={"Authorization": f"Bearer {token}"})

    def test_backend_permission_enforcement_for_all_modes(self):
        expectations = {
            "operations_only": (200, 403),
            "target_only": (403, 200),
            "hybrid": (200, 200),
        }
        for mode, expected in expectations.items():
            with self.subTest(mode=mode):
                self.assertEqual(self.request(mode, "/operations").status_code, expected[0])
                self.assertEqual(self.request(mode, "/targets").status_code, expected[1])


if __name__ == "__main__":
    unittest.main()
