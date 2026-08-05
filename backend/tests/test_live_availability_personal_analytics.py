from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import dispatch_planner_service as planner
from services import vehicle_availability_service as availability
from services import vehicle_operation_request_service as operations


class SharedLiveAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().live_availability
        self.driver_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.now = datetime(2026, 8, 5, 10, tzinfo=timezone.utc)
        self.db.users.insert_one({"_id": self.driver_id, "role": "driver", "status": "active", "driver_profile": {"approval_status": "approved"}})
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "status": "assigned", "assigned_driver_id": self.driver_id})
        self.collection_patch = patch.object(availability, "get_collection", side_effect=lambda name: self.db[name])
        self.collection_patch.start()
        self.addCleanup(self.collection_patch.stop)

    def test_target_assignment_and_accepted_handover_are_not_live_usage(self):
        self.db.vehicle_movements.insert_one({
            "_id": ObjectId(), "vehicle_id": self.vehicle_id, "driver_id": self.driver_id,
            "movement_type": "assignment_handover", "custody_state": "accepted", "status": "approved",
        })
        result = availability.resolve_vehicle_availability(self.vehicle_id)
        self.assertTrue(result["is_available"])
        self.assertEqual(result["operational_state"], "assigned")

    def test_manual_available_never_overrides_reservation_and_release_reveals_manual_state(self):
        availability.update_vehicle_manual_availability(
            str(self.vehicle_id), {"status": "temporarily_unavailable", "reason": "cleaning"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        reservation_id = self.db.resource_reservations.insert_one({
            "resource_id": self.vehicle_id, "reservation_type": "vehicle", "status": "reserved",
            "start_time": self.now, "end_time": self.now + timedelta(hours=2),
        }).inserted_id
        reserved = availability.resolve_vehicle_availability(self.vehicle_id, {"start_time": self.now, "end_time": self.now + timedelta(hours=1)})
        self.assertFalse(reserved["is_available"])
        self.assertEqual(reserved["operational_state"], "reserved")
        availability.update_vehicle_manual_availability(
            str(self.vehicle_id), {"status": "available"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        still_reserved = availability.resolve_vehicle_availability(self.vehicle_id, {"start_time": self.now, "end_time": self.now + timedelta(hours=1)})
        self.assertEqual(still_reserved["operational_state"], "reserved")
        self.db.resource_reservations.update_one({"_id": reservation_id}, {"$set": {"status": "released"}})
        released = availability.resolve_vehicle_availability(self.vehicle_id)
        self.assertTrue(released["is_available"])
        self.assertEqual(released["operational_state"], "assigned")

    def test_driver_conflict_ignores_assignment_but_blocks_real_overlap(self):
        self.db.vehicle_movements.insert_one({
            "_id": ObjectId(), "vehicle_id": self.vehicle_id, "driver_id": self.driver_id,
            "movement_type": "assignment_handover", "status": "approved", "custody_state": "accepted",
        })
        patches = [
            patch.object(planner, "resource_reservations_collection", return_value=self.db.resource_reservations),
            patch.object(planner, "vehicle_movements_collection", return_value=self.db.vehicle_movements),
            patch.object(planner, "dispatch_jobs_collection", return_value=self.db.dispatch_jobs),
            patch.object(planner, "users_collection", return_value=self.db.users),
        ]
        for item in patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        self.assertEqual(planner._driver_conflicts(driver_id=self.driver_id, start_time=self.now, end_time=self.now + timedelta(hours=1)), [])
        self.db.vehicle_movements.insert_one({
            "_id": ObjectId(), "vehicle_id": ObjectId(), "driver_id": self.driver_id,
            "movement_type": "personal_use", "status": "approved",
            "requested_departure_time": self.now, "expected_return_time": self.now + timedelta(hours=2),
        })
        conflicts = planner._driver_conflicts(driver_id=self.driver_id, start_time=self.now, end_time=self.now + timedelta(hours=1))
        self.assertTrue(any("another vehicle movement" in item for item in conflicts))

    def test_vehicle_and_driver_use_separate_manual_reason_sets(self):
        vehicle = availability.update_vehicle_manual_availability(
            str(self.vehicle_id), {"status": "temporarily_unavailable", "reason": "fueling"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(vehicle["manual_availability_reason"], "fueling")
        with self.assertRaises(Exception) as vehicle_error:
            availability.update_vehicle_manual_availability(
                str(self.vehicle_id), {"status": "temporarily_unavailable", "reason": "off_duty"},
                current_user_id=str(self.driver_id), current_role="driver",
            )
        self.assertEqual(vehicle_error.exception.status_code, 400)

        driver = availability.update_driver_manual_availability(
            str(self.driver_id), {"status": "temporarily_unavailable", "reason": "off_duty"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(driver["manual_availability_reason"], "off_duty")
        with self.assertRaises(Exception) as driver_error:
            availability.update_driver_manual_availability(
                str(self.driver_id), {"status": "temporarily_unavailable", "reason": "fueling"},
                current_user_id=str(self.driver_id), current_role="driver",
            )
        self.assertEqual(driver_error.exception.status_code, 400)

    def test_other_note_and_update_metadata_persist_then_clear(self):
        unavailable = availability.update_vehicle_manual_availability(
            str(self.vehicle_id),
            {"status": "temporarily_unavailable", "reason": "other", "note": "Security inspection"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(unavailable["manual_availability_note"], "Security inspection")
        self.assertEqual(unavailable["manual_availability_updated_by"], str(self.driver_id))
        self.assertIsNotNone(unavailable["manual_availability_updated_at"])

        available = availability.update_vehicle_manual_availability(
            str(self.vehicle_id), {"status": "available"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(available["manual_availability_status"], "available")
        self.assertIsNone(available["manual_availability_reason"])
        self.assertIsNone(available["manual_availability_note"])

        driver_unavailable = availability.update_driver_manual_availability(
            str(self.driver_id),
            {"status": "temporarily_unavailable", "reason": "other", "note": "Family appointment"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(driver_unavailable["manual_availability_note"], "Family appointment")
        driver_available = availability.update_driver_manual_availability(
            str(self.driver_id), {"status": "available"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertIsNone(driver_available["manual_availability_reason"])
        self.assertIsNone(driver_available["manual_availability_note"])

    def test_driver_manual_available_does_not_override_active_movement(self):
        self.db.vehicle_movements.insert_one({
            "_id": ObjectId(), "vehicle_id": self.vehicle_id, "driver_id": self.driver_id,
            "movement_type": "dispatch", "status": "in_progress",
        })
        result = availability.update_driver_manual_availability(
            str(self.driver_id), {"status": "available"},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(result["manual_availability_status"], "available")
        self.assertEqual(result["operational_state"], "in_movement")
        self.assertFalse(result["is_available"])


class PersonalUseAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().personal_analytics
        self.driver_id = ObjectId()
        self.other_driver_id = ObjectId()
        self.admin_id = ObjectId()
        self.target_vehicle_id = ObjectId()
        self.other_vehicle_id = ObjectId()
        self.db.users.insert_many([
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver One"},
            {"_id": self.other_driver_id, "role": "driver", "status": "active", "full_name": "Driver Two"},
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Admin User"},
        ])
        self.db.vehicles.insert_many([
            {"_id": self.target_vehicle_id, "registration_number": "TARGET-1", "assigned_driver_id": self.driver_id},
            {"_id": self.other_vehicle_id, "registration_number": "OTHER-1"},
        ])
        self.patch = patch.object(operations, "get_collection", side_effect=lambda name: self.db[name])
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_lifetime_totals_filters_and_missing_legacy_metrics(self):
        first_id, second_id, movement_id = ObjectId(), ObjectId(), ObjectId()
        start = datetime(2026, 7, 1, 9, tzinfo=timezone.utc)
        self.db.vehicle_movements.insert_one({
            "_id": movement_id, "movement_type": "personal_use", "status": "closed",
            "opening_odometer": 100, "closing_odometer": 130,
            "departure_time": start, "returned_at": start + timedelta(hours=2),
            "permanent_driver_id": self.driver_id,
        })
        self.db.vehicle_operation_requests.insert_many([
            {"_id": first_id, "request_id": "PVU-1", "operation_type": "personal_use", "driver_id": self.driver_id, "vehicle_id": self.target_vehicle_id, "status": "completed", "purpose": "Appointment", "created_at": start, "planned_departure_at": start, "expected_return_at": start + timedelta(hours=1, minutes=30), "linked_vehicle_movement_id": movement_id, "approved_by": self.admin_id, "status_history": [{"status": "approved"}]},
            {"_id": second_id, "request_id": "PVU-2", "operation_type": "PERSONAL_USE", "driver_id": self.driver_id, "vehicle_id": self.other_vehicle_id, "status": "rejected", "purpose": "Errand", "created_at": start + timedelta(days=10)},
            {"_id": ObjectId(), "request_id": "PVU-3", "operation_type": "personal_use", "driver_id": self.other_driver_id, "vehicle_id": self.other_vehicle_id, "status": "pending_approval", "created_at": start + timedelta(days=20)},
        ])
        result = operations.get_personal_use_analytics(current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(result["totals"], {"requests": 3, "trips": 1, "hours": 2.0, "distance": 30.0})
        driver = next(item for item in result["drivers"] if item["driver_id"] == str(self.driver_id))
        self.assertEqual(driver["completed"], 1)
        self.assertEqual(driver["rejected"], 1)
        self.assertEqual(driver["target_assigned_vehicle_usage_count"], 1)
        legacy = next(item for item in result["history"] if item["request_id"] == "PVU-2")
        self.assertIsNone(legacy["distance"])
        self.assertIsNone(legacy["cost_impact"])
        filtered = operations.get_personal_use_analytics(current_user_id=str(self.driver_id), current_role="driver", date_from="2026-07-05T00:00:00Z")
        self.assertEqual(filtered["totals"]["requests"], 1)
        self.assertEqual(filtered["history"][0]["request_id"], "PVU-2")

    def test_driver_cannot_view_another_drivers_history(self):
        with self.assertRaises(Exception) as raised:
            operations.get_personal_use_analytics(current_user_id=str(self.driver_id), current_role="driver", driver_id=str(self.other_driver_id))
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
