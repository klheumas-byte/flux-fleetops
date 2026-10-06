from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import expense_service, finance_account_service, fuel_service
from services import movement_source_service
from services import vehicle_movement_service as movement_service
from services import vehicle_operation_request_service as operations
from utils.api_error import ApiError


class FuelInstructionOperationalTaskTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().fuel_instruction
        self.app = Flask(__name__)
        self.app.config["MAX_UPLOAD_SIZE_MB"] = 5
        self.context = self.app.app_context(); self.context.push(); self.addCleanup(self.context.pop)
        self.admin_id, self.owner_id, self.driver_id, self.other_driver_id = (ObjectId() for _ in range(4))
        self.vehicle_id, self.account_id, self.station_id = (ObjectId() for _ in range(3))
        self.db.users.insert_many([
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Admin"},
            {"_id": self.owner_id, "role": "owner", "status": "active", "full_name": "Owner"},
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver", "driver_profile": {"approval_status": "approved"}},
            {"_id": self.other_driver_id, "role": "driver", "status": "active", "full_name": "Other", "driver_profile": {"approval_status": "approved"}},
        ])
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "AX-100", "status": "available", "fuel_type": "petrol"})
        self.db.finance_accounts.insert_one({"_id": self.account_id, "account_name": "Axelera Cash", "account_type": "cash", "status": "active", "current_balance": 1000.0, "ledger_initialized": True})
        self.db.fuel_stations.insert_one({"_id": self.station_id, "station_name": "Test Station", "status": "active"})
        modules = [operations, movement_service, fuel_service, expense_service, finance_account_service]
        self.patches = [patch.object(module, "get_collection", side_effect=lambda name, db=self.db: db[name]) for module in modules]
        self.patches += [
            patch.object(movement_source_service, "vehicle_movements_collection", return_value=self.db.vehicle_movements),
            patch.object(operations, "notify_roles"), patch.object(operations, "create_notification"), patch.object(operations, "resolve_action_notifications"),
            patch.object(operations, "resolve_vehicle_availability", return_value={"is_available": True, "blocking_reasons": []}),
            patch.object(movement_service, "resolve_vehicle_availability", return_value={"is_available": True, "blocking_reasons": []}),
            patch.object(movement_service, "resolve_driver_availability", return_value={"is_available": True, "blocking_reasons": []}),
            patch("services.movement_custody_service.transfer_movement_custody"),
            patch("services.movement_custody_service.accept_movement_custody"),
            patch("services.movement_custody_service.return_movement_custody"),
        ]
        for item in self.patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])
        finance_account_service.ensure_finance_account_indexes()
        expense_service.ensure_expense_indexes()
        fuel_service.ensure_fuel_indexes()

    def create_instruction(self, **overrides):
        payload = {
            "vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id),
            "authorized_amount": 300, "authorized_litres": 12,
            "finance_account_id": str(self.account_id), "fuel_station_id": str(self.station_id),
            "planned_departure_at": "2026-10-05T10:00:00Z", "expected_return_at": "2026-10-05T12:00:00Z",
            "idempotency_key": str(ObjectId()),
            **overrides,
        }
        return operations.create_fuel_instruction(payload, current_user_id=str(self.admin_id), current_role="admin")

    def submit_proof(self, instruction, **overrides):
        request_id = ObjectId(instruction["id"])
        self.db.vehicle_operation_requests.update_one({"_id": request_id}, {"$set": {"status": "movement_in_progress"}})
        proof = operations.confirm_operational_task(instruction["id"], {
            "actual_amount": 250, "actual_litres": 10, "odometer_reading": 12345,
            "fuel_date": "2026-10-05", "fuel_type": "petrol", "receipt_image": "/uploads/fuel.png",
            "actual_fuel_station_id": str(self.station_id), "station_branch": "Airport Branch",
            "discrepancy_notes": "Bought less than authorized", **overrides,
        }, current_user_id=str(self.driver_id), current_role="driver")
        movement_id = ObjectId(proof["linked_vehicle_movement_id"])
        self.db.vehicle_operation_requests.update_one({"_id": request_id}, {"$set": {"status": "awaiting_verification"}})
        self.db.vehicle_movements.update_one({"_id": movement_id}, {"$set": {"status": "closed"}})
        return operations.get_operational_request(instruction["id"], current_user_id=str(self.admin_id), current_role="admin")

    def test_instruction_task_proof_verify_posts_once_and_keeps_authorized_actual_separate(self):
        instruction = self.create_instruction()
        self.assertEqual(instruction["status"], "scheduled")
        self.assertIn("Fuel Vehicle", instruction["title"])
        self.assertEqual(instruction["fuel_instruction"]["finance_account_id"], str(self.account_id))
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 1000)
        operations.acknowledge_operational_request(instruction["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.db.vehicle_operation_requests.update_one({"_id": ObjectId(instruction["id"])}, {"$set": {"status": "movement_in_progress"}})
        arrived = operations.arrive_operational_request(instruction["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.assertIsNotNone(arrived["arrived_at"])
        awaiting = self.submit_proof(instruction)
        fuel_log = self.db.fuel_logs.find_one({"fuel_instruction_id": ObjectId(instruction["id"])})
        self.assertEqual((fuel_log["fuel_station_id"], fuel_log["station_name"], fuel_log["station_branch"]), (self.station_id, "Test Station", "Airport Branch"))
        listed = fuel_service.list_fuel_logs(str(self.admin_id), "admin")
        self.assertEqual(listed["logs"][0]["fuel_classification"], "operational_fuel")
        with self.assertRaises(ApiError) as bypass:
            fuel_service.approve_fuel_log(str(fuel_log["_id"]), str(self.admin_id), "admin")
        self.assertEqual(bypass.exception.status_code, 409)
        result = operations.verify_operational_request(awaiting["id"], {"decision": "verified"}, current_user_id=str(self.owner_id), current_role="owner")
        repeated = operations.verify_operational_request(awaiting["id"], {"decision": "verified"}, current_user_id=str(self.owner_id), current_role="owner")
        self.assertEqual((result["status"], repeated["status"]), ("completed", "completed"))
        stored = self.db.vehicle_operation_requests.find_one({"_id": ObjectId(instruction["id"])})
        self.assertEqual((stored["fuel_instruction"]["authorized_amount"], stored["fuel_instruction"]["actual_amount"]), (300, 250))
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 750)
        self.assertEqual(self.db.finance_ledger_entries.count_documents({"source_type": "fuel_instruction_expense"}), 1)
        self.assertEqual(self.db.finance_ledger_entries.find_one({"source_type": "fuel_instruction_expense"})["account_id"], self.account_id)
        self.assertEqual(self.db.expenses.count_documents({"fuel_instruction_id": ObjectId(instruction["id"])}), 1)
        self.assertEqual(self.db.expenses.find_one({"fuel_instruction_id": ObjectId(instruction["id"])})["finance_account_id"], self.account_id)
        self.assertEqual(self.db.fuel_logs.count_documents({"fuel_instruction_id": ObjectId(instruction["id"]), "status": "approved"}), 1)
        history = self.db.vehicles.find_one({"_id": self.vehicle_id})["fuel_history"]
        self.assertEqual((history[0]["station_name"], history[0]["station_branch"]), ("Test Station", "Airport Branch"))

    def test_create_retry_returns_same_purchase_task(self):
        key = "fuel-ui-retry-1"
        first = self.create_instruction(idempotency_key=key)
        second = self.create_instruction(idempotency_key=key)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.db.vehicle_operation_requests.count_documents({"fuel_instruction.idempotency_key": key}), 1)
        self.assertEqual(self.db.vehicle_movements.count_documents({"source_id": ObjectId(first["id"])}), 1)

    def test_flag_allows_driver_correction_without_posting(self):
        instruction = self.create_instruction()
        awaiting = self.submit_proof(instruction)
        flagged = operations.verify_operational_request(awaiting["id"], {"decision": "flagged", "reason": "Receipt unclear"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(flagged["verification_status"], "flagged")
        self.assertEqual(self.db.expenses.count_documents({}), 0)
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 1000)
        with self.assertRaises(ApiError) as premature:
            operations.verify_operational_request(instruction["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(premature.exception.status_code, 409)
        operations.confirm_operational_task(instruction["id"], {"actual_amount": 240, "actual_litres": 10, "odometer_reading": 12346, "receipt_image": "/uploads/replacement.png", "discrepancy_notes": "Corrected receipt and amount", "actual_station_name": "Manual Fuel Vendor", "station_branch": "North Branch"}, current_user_id=str(self.driver_id), current_role="driver")
        completed = operations.verify_operational_request(instruction["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(completed["verification_status"], "verified")
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 760)

    def test_driver_manual_station_and_branch_are_persisted_when_admin_station_is_blank(self):
        instruction = self.create_instruction(fuel_station_id=None, station_name=None)
        self.submit_proof(instruction, actual_fuel_station_id=None, actual_station_name="Independent Fuel", station_branch="Spintex Road")
        log = self.db.fuel_logs.find_one({"fuel_instruction_id": ObjectId(instruction["id"])})
        self.assertIsNone(log["fuel_station_id"])
        self.assertEqual((log["station_name"], log["station_branch"]), ("Independent Fuel", "Spintex Road"))

    def test_driver_completes_proof_and_vehicle_return_in_one_retry_safe_action(self):
        instruction = self.create_instruction()
        request_id = ObjectId(instruction["id"])
        movement_id = ObjectId(instruction["linked_vehicle_movement_id"])
        self.db.vehicle_operation_requests.update_one(
            {"_id": request_id},
            {"$set": {"status": "movement_in_progress", "acknowledged_at": operations.now_utc()}},
        )
        self.db.vehicle_movements.update_one(
            {"_id": movement_id},
            {"$set": {"status": "in_progress", "opening_fuel_level": 2, "opening_odometer": 12300,
                      "departure_time": datetime(2026, 10, 5, 10, tzinfo=timezone.utc)}},
        )
        payload = {
            "actual_amount": 250, "actual_litres": 10, "odometer_reading": 12345,
            "fuel_date": "2026-10-05", "fuel_type": "petrol", "receipt_image": "/uploads/fuel.png",
            "actual_fuel_station_id": str(self.station_id), "station_branch": "Airport Branch",
            "discrepancy_notes": "Bought less than authorized", "closing_fuel_level": 6,
        }
        completed = operations.complete_fuel_instruction_task(
            instruction["id"], payload, current_user_id=str(self.driver_id), current_role="driver"
        )
        repeated = operations.complete_fuel_instruction_task(
            instruction["id"], payload, current_user_id=str(self.driver_id), current_role="driver"
        )
        self.assertEqual((completed["status"], repeated["status"]), ("awaiting_verification", "awaiting_verification"))
        self.assertEqual(self.db.fuel_logs.count_documents({"fuel_instruction_id": request_id}), 1)
        movement = self.db.vehicle_movements.find_one({"_id": movement_id})
        self.assertEqual((movement["status"], movement["closing_fuel_level"], movement["closing_odometer"]), ("returned", 6, 12345.0))
        verified = operations.verify_operational_request(
            instruction["id"], {"decision": "verified"}, current_user_id=str(self.admin_id), current_role="admin"
        )
        self.assertEqual(verified["status"], "completed")
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": movement_id})["status"], "closed")
        self.assertEqual(self.db.expenses.count_documents({"fuel_instruction_id": request_id}), 1)
        self.assertEqual(self.db.finance_ledger_entries.count_documents({"source_type": "fuel_instruction_expense"}), 1)

    def test_permissions_weekly_remittance_and_cancelled_instruction_do_not_post(self):
        with self.assertRaises(ApiError) as denied:
            operations.create_fuel_instruction({"vehicle_id": str(self.vehicle_id)}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(denied.exception.status_code, 403)
        assignment_id = self.db.assignments.insert_one({"vehicle_id": self.vehicle_id, "driver_id": self.driver_id, "status": "active", "weekly_target": 700}).inserted_id
        with self.assertRaises(ApiError) as weekly:
            self.create_instruction()
        self.assertEqual(weekly.exception.status_code, 409)
        self.db.assignments.delete_one({"_id": assignment_id})
        instruction = self.create_instruction()
        operations.cancel_operational_request(instruction["id"], {"reason": "No longer required"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(self.db.expenses.count_documents({}), 0)
        self.assertEqual(self.db.finance_ledger_entries.count_documents({}), 0)
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 1000)

    def test_cash_momo_and_bank_are_generic_account_types(self):
        for account_type in ("cash", "momo", "bank"):
            self.db.vehicle_operation_requests.delete_many({}); self.db.vehicle_movements.delete_many({})
            account_id = ObjectId()
            self.db.finance_accounts.insert_one({"_id": account_id, "account_name": f"{account_type} account", "account_type": account_type, "status": "active", "current_balance": 500})
            instruction = self.create_instruction(finance_account_id=str(account_id))
            self.assertEqual(instruction["fuel_instruction"]["finance_account_snapshot"]["account_type"], account_type)
            self.assertEqual(self.db.finance_accounts.find_one({"_id": account_id})["current_balance"], 500)


if __name__ == "__main__":
    unittest.main()
