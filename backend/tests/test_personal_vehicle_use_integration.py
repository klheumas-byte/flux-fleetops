from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.vehicle_operation_request import serialize_vehicle_operation_request
from services import movement_source_service
from services import vehicle_availability_service
from services import vehicle_movement_service
from services import vehicle_operation_request_service as service
from routes import operational_requests as operational_request_routes
from utils.api_error import ApiError


class PersonalVehicleUseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().personal_use
        self.driver_id = ObjectId()
        self.other_driver_id = ObjectId()
        self.admin_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.db.users.insert_many([
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver One", "driver_profile": {"approval_status": "approved"}},
            {"_id": self.other_driver_id, "role": "driver", "status": "active", "full_name": "Driver Two", "driver_profile": {"approval_status": "approved"}},
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Operations Admin"},
        ])
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "PVU-100", "status": "assigned"})
        self.patches = [
            patch.object(service, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(vehicle_availability_service, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(vehicle_movement_service, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(movement_source_service, "vehicle_movements_collection", return_value=self.db.vehicle_movements),
            patch.object(service, "user_has_permission", return_value=True),
            patch.object(service, "resolve_vehicle_availability", return_value={"is_available": True, "blocking_reasons": []}),
            patch.object(service, "notify_roles"),
            patch.object(service, "create_notification"),
            patch.object(service, "resolve_action_notifications"),
            patch("services.dispatch_planner_service.detect_dispatch_conflicts", return_value={"has_conflicts": False, "vehicle_conflicts": [], "driver_conflicts": []}),
            patch("services.movement_custody_service.transfer_movement_custody"),
            patch("services.movement_custody_service.accept_movement_custody"),
            patch("services.movement_custody_service.return_movement_custody"),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def payload(self, **overrides):
        planned_departure = datetime.now(timezone.utc) + timedelta(hours=1)
        expected_return = planned_departure + timedelta(hours=3)
        return {
            "operation_type": "personal_use",
            "purpose": "Family appointment",
            "origin": "Head Office",
            "destination": "Community Clinic",
            "vehicle_id": str(self.vehicle_id),
            "planned_departure_at": planned_departure.isoformat(),
            "expected_return_at": expected_return.isoformat(),
            "submit_for_approval": True,
            **overrides,
        }

    def create(self):
        return service.create_operational_request(self.payload(), current_user_id=str(self.driver_id), current_role="driver")

    def route_client(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, JWT_SECRET_KEY="personal-use-route-test-secret-at-least-32-bytes")
        JWTManager(app)
        app.register_blueprint(operational_request_routes.operational_requests_bp, url_prefix="/api/operational-requests")
        with app.app_context():
            token = create_access_token(identity=str(self.driver_id), additional_claims={"role": "driver"})
        return app.test_client(), {"Authorization": f"Bearer {token}"}

    def test_driver_identity_is_derived_and_records_are_owner_scoped(self):
        created = self.create()
        document = self.db.vehicle_operation_requests.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(document["requested_by"], self.driver_id)
        self.assertEqual(document["driver_id"], self.driver_id)
        own = service.list_operational_requests(current_user_id=str(self.driver_id), current_role="driver", operation_type="personal_use")
        other = service.list_operational_requests(current_user_id=str(self.other_driver_id), current_role="driver", operation_type="personal_use")
        self.assertEqual(own["pagination"]["total"], 1)
        self.assertEqual(other["pagination"]["total"], 0)

    def test_live_route_contract_accepts_canonical_and_legacy_types(self):
        client, headers = self.route_client()
        canonical = client.get("/api/operational-requests?operation_type=personal_use", headers=headers)
        legacy = client.get("/api/operational-requests?operation_type=PERSONAL_USE", headers=headers)
        created = client.post(
            "/api/operational-requests",
            headers=headers,
            json=self.payload(operation_type="PERSONAL_VEHICLE_USE"),
        )
        self.assertEqual(canonical.status_code, 200)
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["data"]["request"]["operation_type"], "personal_use")

    def test_type_aliases_normalize_for_create_list_and_existing_records(self):
        created = service.create_operational_request(
            self.payload(operation_type="PERSONAL_VEHICLE_USE"),
            current_user_id=str(self.driver_id),
            current_role="driver",
        )
        self.assertEqual(created["operation_type"], "personal_use")

        request_id = ObjectId(created["id"])
        self.db.vehicle_operation_requests.update_one(
            {"_id": request_id}, {"$set": {"operation_type": "PERSONAL_USE"}}
        )
        listed = service.list_operational_requests(
            current_user_id=str(self.driver_id),
            current_role="driver",
            operation_type="Personal Vehicle Use",
        )
        self.assertEqual(listed["pagination"]["total"], 1)
        self.assertEqual(listed["requests"][0]["operation_type"], "personal_use")

        loaded = service.get_operational_request(
            created["id"], current_user_id=str(self.driver_id), current_role="driver"
        )
        self.assertEqual(loaded["operation_type"], "personal_use")

    def test_vehicle_options_keep_target_assignment_selectable_and_apply_requested_window(self):
        self.db.vehicles.update_one(
            {"_id": self.vehicle_id},
            {"$set": {"personal_owner_user_id": None, "assigned_driver_id": self.other_driver_id}},
        )
        maintenance_id = ObjectId()
        reserved_id = ObjectId()
        later_id = ObjectId()
        self.db.vehicles.insert_many([
            {"_id": maintenance_id, "registration_number": "MAINT-1", "status": "maintenance"},
            {"_id": reserved_id, "registration_number": "BUSY-1", "status": "active"},
            {"_id": later_id, "registration_number": "LATER-1", "status": "active"},
        ])
        self.db.resource_reservations.insert_many([
            {"_id": ObjectId(), "resource_id": reserved_id, "reservation_type": "vehicle", "status": "reserved", "source_type": "customer_dispatch", "start_time": datetime(2026, 8, 10, 10, tzinfo=timezone.utc), "end_time": datetime(2026, 8, 10, 11, tzinfo=timezone.utc)},
            {"_id": ObjectId(), "resource_id": later_id, "reservation_type": "vehicle", "status": "reserved", "source_type": "customer_dispatch", "start_time": datetime(2026, 8, 11, 10, tzinfo=timezone.utc), "end_time": datetime(2026, 8, 11, 11, tzinfo=timezone.utc)},
        ])

        options = service.list_operational_request_options(
            current_role="driver",
            planned_departure_at="2026-08-10T09:00:00Z",
            expected_return_at="2026-08-10T12:00:00Z",
        )
        by_registration = {item["registration_number"]: item for item in options["vehicles"]}
        self.assertTrue(by_registration["PVU-100"]["is_available"])
        self.assertEqual(by_registration["PVU-100"]["availability_label"], "Assigned for Target · Approval Required")
        self.assertFalse(by_registration["MAINT-1"]["is_available"])
        self.assertEqual(by_registration["MAINT-1"]["availability_label"], "Maintenance")
        self.assertFalse(by_registration["BUSY-1"]["is_available"])
        self.assertEqual(by_registration["BUSY-1"]["availability_label"], "Reserved")
        self.assertTrue(by_registration["LATER-1"]["is_available"])

    def test_dispatch_opportunity_uses_centered_keyboard_safe_dialog_contract(self):
        source = (BACKEND_DIR.parent / "src/app/components/driver/DispatchOpportunities.tsx").read_text(encoding="utf-8")
        self.assertIn("<Dialog open=", source)
        self.assertIn("h-[92dvh]", source)
        self.assertIn("md:max-h-[90dvh]", source)
        self.assertIn("md:max-w-[800px]", source)
        self.assertIn("overflow-x-hidden overflow-y-auto", source)
        self.assertIn("md:grid-cols-2", source)
        self.assertIn("text-base", source)
        self.assertNotIn("sm:-translate-x-1/2", source)

    def test_personal_use_frontend_sequences_opening_check_before_start(self):
        source = (BACKEND_DIR.parent / "src/app/components/driver/PersonalVehicleUse.tsx").read_text(encoding="utf-8")
        self.assertIn("fetchVehicleMovementById", source)
        self.assertIn("{ fresh: true }", source)
        self.assertIn("mode: 'opening'", source)
        self.assertIn("returning ? 'return' : 'opening-check'", source)
        self.assertIn("needsOpeningCheck = movementStatus === 'approved'", source)
        self.assertIn("readyToStart = movementStatus === 'checked_out'", source)
        self.assertIn("movementStatus === 'in_progress'", source)
        self.assertIn("const returnOverdue = canReturn && isPast(record.expected_return_at)", source)
        self.assertIn("const departureOverdue = (needsOpeningCheck || readyToStart)", source)
        self.assertIn("{canReturn && <Button", source)
        self.assertNotIn("record.is_overdue", source)
        self.assertIn("Save Opening Check", source)

    def test_separate_account_and_requesting_for_another_driver_are_blocked(self):
        with self.assertRaises(ApiError) as raised:
            service.create_operational_request(self.payload(driver_id=str(self.other_driver_id)), current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 403)
        created = self.create()
        document = self.db.vehicle_operation_requests.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(document["driver_id"], self.driver_id)

    def test_requester_cannot_approve_own_request(self):
        created = self.create()
        with self.assertRaises(ApiError) as raised:
            service.approve_operational_request(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(raised.exception.status_code, 403)

    def test_admin_approval_reserves_vehicle_and_creates_one_personal_movement(self):
        created = self.create()
        approved = service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(approved["status"], "scheduled")
        request = self.db.vehicle_operation_requests.find_one({"_id": ObjectId(created["id"])})
        reservation = self.db.resource_reservations.find_one({"vehicle_operation_request_id": request["_id"]})
        movement = self.db.vehicle_movements.find_one({"source_key": f"vehicle_operation_request:{request['_id']}"})
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation["source_type"], "personal_use")
        self.assertEqual(movement["movement_type"], "personal_use")
        self.assertEqual(movement["movement_category"], "PERSONAL_USE")
        self.assertEqual(movement["reservation_id"], reservation["_id"])
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 1)

    def test_approved_request_keeps_vehicle_through_start_and_return(self):
        created = self.create()
        service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        request_id = ObjectId(created["id"])
        request = self.db.vehicle_operation_requests.find_one({"_id": request_id})
        movement_id = request["linked_vehicle_movement_id"]
        reservation = self.db.resource_reservations.find_one({"vehicle_operation_request_id": request_id})
        self.assertEqual(request["vehicle_id"], self.vehicle_id)
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": movement_id})["vehicle_id"], self.vehicle_id)
        self.assertEqual(reservation["resource_id"], self.vehicle_id)

        service.acknowledge_operational_request(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        service.open_operational_movement(
            created["id"],
            {"opening_odometer": 100, "opening_fuel_level": 6},
            current_user_id=str(self.driver_id),
            current_role="driver",
        )
        checked_movement = self.db.vehicle_movements.find_one({"_id": movement_id})
        self.assertEqual(checked_movement["status"], "checked_out")
        self.assertEqual(checked_movement["opening_fuel_level"], 6)
        started = service.start_operational_request(
            created["id"],
            {},
            current_user_id=str(self.driver_id),
            current_role="driver",
        )
        self.assertEqual(started["status"], "movement_in_progress")
        active_movement = self.db.vehicle_movements.find_one({"_id": movement_id})
        self.assertEqual(active_movement["status"], "in_progress")
        self.assertEqual(active_movement["opening_fuel_level"], 6)
        self.assertEqual(active_movement["_id"], movement_id)

        returned = service.return_operational_request(
            created["id"],
            {"closing_odometer": 110, "closing_fuel_level": 5},
            current_user_id=str(self.driver_id),
            current_role="driver",
        )
        self.assertEqual(returned["status"], "completed")
        self.assertEqual(returned["vehicle_id"], str(self.vehicle_id))
        completed_movement = self.db.vehicle_movements.find_one({"_id": movement_id})
        self.assertEqual(completed_movement["status"], "closed")
        self.assertEqual(completed_movement["closing_fuel_level"], 5)
        self.assertEqual(completed_movement["distance_travelled"], 10.0)
        self.assertEqual([event["status"] for event in completed_movement["status_history"]], ["checked_out", "in_progress", "returned", "closed"])
        self.assertEqual(self.db.resource_reservations.find_one({"_id": reservation["_id"]})["status"], "released")

    def test_stale_scheduled_source_is_advanced_from_in_progress_movement(self):
        created = self.create()
        service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        service.acknowledge_operational_request(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        service.open_operational_movement(
            created["id"],
            {"opening_fuel_level": 6},
            current_user_id=str(self.driver_id),
            current_role="driver",
        )
        service.start_operational_request(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        request_id = ObjectId(created["id"])
        self.db.vehicle_operation_requests.update_one(
            {"_id": request_id},
            {"$set": {"status": "scheduled", "opening_check_completed_at": None, "started_at": None}},
        )

        refreshed = service.get_operational_request(
            created["id"], current_user_id=str(self.driver_id), current_role="driver"
        )
        self.assertEqual(refreshed["status"], "movement_in_progress")
        self.assertEqual(refreshed["linked_vehicle_movement_status"], "in_progress")
        repaired = self.db.vehicle_operation_requests.find_one({"_id": request_id})
        self.assertEqual(repaired["status"], "movement_in_progress")
        self.assertIsNotNone(repaired["opening_check_completed_at"])

        # The mutation boundary also self-heals if an old writer leaves the
        # source behind again between refresh and Return.
        self.db.vehicle_operation_requests.update_one(
            {"_id": request_id}, {"$set": {"status": "scheduled"}}
        )
        returned = service.return_operational_request(
            created["id"],
            {"closing_fuel_level": 5},
            current_user_id=str(self.driver_id),
            current_role="driver",
        )
        self.assertEqual(returned["status"], "completed")

    def test_start_and_return_require_fuel_but_keep_odometer_optional(self):
        created = self.create()
        service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        service.acknowledge_operational_request(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        request = self.db.vehicle_operation_requests.find_one({"_id": ObjectId(created["id"])})

        with self.assertRaises(ApiError) as missing_opening_fuel:
            service.start_operational_request(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertIn("Opening fuel level is required", missing_opening_fuel.exception.message)
        service.start_operational_request(created["id"], {"opening_fuel_level": 6}, current_user_id=str(self.driver_id), current_role="driver")

        with self.assertRaises(ApiError) as missing_closing_fuel:
            service.return_operational_request(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertIn("Closing fuel level is required", missing_closing_fuel.exception.message)
        service.return_operational_request(created["id"], {"closing_fuel_level": 5}, current_user_id=str(self.driver_id), current_role="driver")
        movement = self.db.vehicle_movements.find_one({"_id": request["linked_vehicle_movement_id"]})
        self.assertIsNone(movement["distance_travelled"])

    def test_return_rejects_closing_odometer_below_opening(self):
        created = self.create()
        service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        service.acknowledge_operational_request(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        service.start_operational_request(created["id"], {"opening_fuel_level": 6, "opening_odometer": 100}, current_user_id=str(self.driver_id), current_role="driver")

        with self.assertRaises(ApiError) as invalid_odometer:
            service.return_operational_request(created["id"], {"closing_fuel_level": 5, "closing_odometer": 99}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertIn("closing_odometer cannot be lower", invalid_odometer.exception.message)
        request = self.db.vehicle_operation_requests.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": request["linked_vehicle_movement_id"]})["status"], "in_progress")

    def test_start_revalidates_driver_effective_availability(self):
        created = self.create()
        service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        service.acknowledge_operational_request(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.db.users.update_one({"_id": self.driver_id}, {"$set": {
            "driver_profile.manual_availability_status": "temporarily_unavailable",
            "driver_profile.manual_availability_reason": "off_duty",
        }})

        with self.assertRaises(ApiError) as unavailable:
            service.start_operational_request(created["id"], {"opening_fuel_level": 6}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(unavailable.exception.status_code, 409)
        self.assertIn("temporarily unavailable", unavailable.exception.message.lower())

    def test_overlapping_booking_returns_useful_reason_without_approval(self):
        created = self.create()
        with patch("services.dispatch_planner_service.detect_dispatch_conflicts", return_value={"has_conflicts": True, "vehicle_conflicts": ["Personal Use until 8:00 PM"], "driver_conflicts": []}):
            with self.assertRaises(ApiError) as raised:
                service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("Vehicle unavailable", str(raised.exception))
        self.assertIn("Personal Use until 8:00 PM", str(raised.exception))

    def test_overdue_flag_and_return_fault_linkage(self):
        created = self.create()
        service.approve_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        request_id = ObjectId(created["id"])
        document = self.db.vehicle_operation_requests.find_one({"_id": request_id})
        self.db.vehicle_operation_requests.update_one({"_id": request_id}, {"$set": {"status": "movement_in_progress", "expected_return_at": datetime.now(timezone.utc) - timedelta(hours=1), "started_at": datetime.now(timezone.utc) - timedelta(hours=2)}})
        document.update({"status": "movement_in_progress", "expected_return_at": datetime.now(timezone.utc) - timedelta(hours=1)})
        self.assertTrue(serialize_vehicle_operation_request(document)["is_overdue"])
        movement = self.db.vehicle_movements.find_one({"_id": document["linked_vehicle_movement_id"]})
        returned = {**movement, "status": "returned", "opening_odometer": 100, "closing_odometer": 125, "opening_fuel_level": 80, "closing_fuel_level": 60, "departure_time": datetime.now(timezone.utc) - timedelta(hours=2)}
        fault_id = ObjectId()
        with patch("services.vehicle_movement_service.return_vehicle_movement", return_value=returned), patch("services.vehicle_movement_service.close_vehicle_movement", return_value={**returned, "status": "closed"}), patch("services.fault_service.create_fault", return_value={"id": str(fault_id)}):
            result = service.return_operational_request(created["id"], {"closing_odometer": 125, "closing_fuel_level": 60, "damage_notes": "Mirror cracked"}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["distance_travelled"], 25.0)
        self.assertEqual(result["fuel_difference"], -20)
        self.assertEqual(result["return_fault_id"], str(fault_id))
        reservation = self.db.resource_reservations.find_one({"vehicle_operation_request_id": request_id})
        self.assertEqual(reservation["status"], "released")


if __name__ == "__main__":
    unittest.main()
