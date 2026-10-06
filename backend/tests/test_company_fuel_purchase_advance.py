from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import expense_service, finance_account_service, fuel_advance_service, fuel_service
from services import vehicle_movement_service as movement_service
from utils.api_error import ApiError


class CompanyFuelPurchaseAdvanceTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().fuel_advance
        self.app = Flask(__name__)
        self.app.config["CLOUDFLARE_IMAGES_ENABLED"] = False
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.admin_id, self.driver_id, self.other_driver_id = ObjectId(), ObjectId(), ObjectId()
        self.vehicle_id, self.assignment_id, self.station_id, self.account_id = (ObjectId() for _ in range(4))
        self.db.users.insert_many([
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Admin"},
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver", "driver_profile": {"approval_status": "approved"}},
            {"_id": self.other_driver_id, "role": "driver", "status": "active", "full_name": "Other", "driver_profile": {"approval_status": "approved"}},
        ])
        self.db.vehicles.insert_one({
            "_id": self.vehicle_id, "registration_number": "GX-100", "status": "available",
            "fuel_type": "petrol", "assigned_driver_id": self.driver_id,
        })
        self.db.assignments.insert_one({
            "_id": self.assignment_id, "vehicle_id": self.vehicle_id, "driver_id": self.driver_id,
            "status": "active", "target_enabled": False, "weekly_target": 0,
        })
        self.db.fuel_stations.insert_one({"_id": self.station_id, "station_name": "Station", "status": "active"})
        self.db.finance_accounts.insert_one({
            "_id": self.account_id, "account_name": "Operations Cash", "account_type": "cash",
            "status": "active", "opening_balance": 1000.0, "current_balance": 1000.0,
        })
        modules = [movement_service, fuel_service, expense_service, finance_account_service, fuel_advance_service]
        self.patches = [patch.object(module, "get_collection", side_effect=lambda name, db=self.db: db[name]) for module in modules]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.notify_patch = patch.object(movement_service, "_notify_movement_participants")
        self.notify_patch.start(); self.addCleanup(self.notify_patch.stop)
        self.availability_patch = patch.object(
            movement_service, "resolve_vehicle_availability",
            return_value={"is_available": True, "blocking_reasons": []},
        )
        self.availability_patch.start(); self.addCleanup(self.availability_patch.stop)
        self.fuel_notify_patch = patch.object(fuel_service, "notify_roles")
        self.fuel_notify_patch.start(); self.addCleanup(self.fuel_notify_patch.stop)
        self.single_notify_patch = patch.object(fuel_service, "create_notification")
        self.single_notify_patch.start(); self.addCleanup(self.single_notify_patch.stop)
        self.resolve_notify_patch = patch.object(fuel_service, "resolve_action_notifications")
        self.resolve_notify_patch.start(); self.addCleanup(self.resolve_notify_patch.stop)
        finance_account_service.ensure_finance_account_indexes()
        fuel_service.ensure_fuel_indexes()
        expense_service.ensure_expense_indexes()

    def create_movement(self):
        return movement_service.create_vehicle_movement({
            "vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id),
            "movement_type": "fuel_purchase", "status": "pending_approval",
            "requested_departure_time": "2026-10-05T09:00:00Z",
            "origin": "Office", "destination": "Fuel station", "purpose": "Company fuel purchase",
            "finance_account_id": str(self.account_id), "issued_amount": 300,
        }, current_user_id=str(self.admin_id), current_role="admin")

    def test_issue_purchase_expense_return_and_settlement_reconcile_once(self):
        movement = self.create_movement()
        self.assertEqual(movement["fuel_advance"]["status"], "pending_approval")
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 1000)

        movement = movement_service.approve_vehicle_movement(
            movement["id"], current_user_id=str(self.admin_id), current_role="admin",
        )
        self.assertEqual(movement["fuel_advance"]["status"], "issued")
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 700)
        issue = self.db.finance_ledger_entries.find_one({"source_type": "fuel_advance_issue"})
        self.assertEqual((issue["direction"], issue["amount"]), ("debit", 300))

        log = fuel_service.create_fuel_log({
            "movement_id": movement["id"], "fuel_station_id": str(self.station_id),
            "fuel_type": "petrol", "litres": 10, "amount": 250,
            "fuel_date": "2026-10-05", "payment_method": "cash", "odometer_reading": 12345,
        }, str(self.driver_id), "driver")
        approved = fuel_service.approve_fuel_log(log["id"], str(self.admin_id), "admin")
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(self.db.expenses.count_documents({"fuel_log_id": ObjectId(log["id"])}), 1)
        expense = self.db.expenses.find_one({"fuel_log_id": ObjectId(log["id"])})
        self.assertEqual((expense["amount"], expense["status"], expense["payment_source"]), (250, "paid", "fuel_advance"))
        self.assertEqual(expense["treasury_posting_status"], "debited_on_advance_issue")
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 700)

        returned = fuel_advance_service.return_fuel_advance_balance(
            movement["id"], {"amount": 50}, actor_id=str(self.admin_id), actor_role="admin", idempotency_key="return-1",
        )
        repeated = fuel_advance_service.return_fuel_advance_balance(
            movement["id"], {"amount": 50}, actor_id=str(self.admin_id), actor_role="admin", idempotency_key="return-1",
        )
        self.assertEqual(returned["fuel_advance"]["status"], "settled")
        self.assertEqual(repeated["fuel_advance"]["returned_amount"], 50)
        self.assertEqual(returned["fuel_advance"]["outstanding_amount"], 0)
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 750)
        self.assertEqual(self.db.finance_ledger_entries.count_documents({"source_type": "fuel_advance_return"}), 1)
        self.assertEqual(self.db.expenses.count_documents({}), 1)
        self.assertEqual(300 - 250 - 50, 0)

    def test_wrong_driver_over_spend_and_duplicate_log_are_rejected(self):
        movement = self.create_movement()
        movement = movement_service.approve_vehicle_movement(movement["id"], current_user_id=str(self.admin_id), current_role="admin")
        payload = {"movement_id": movement["id"], "fuel_station_id": str(self.station_id), "fuel_type": "petrol",
                   "litres": 10, "amount": 301, "fuel_date": "2026-10-05", "payment_method": "cash"}
        with self.assertRaises(ApiError) as denied:
            fuel_service.create_fuel_log(payload, str(self.other_driver_id), "driver")
        self.assertEqual(denied.exception.status_code, 403)
        log = fuel_service.create_fuel_log({**payload, "amount": 300}, str(self.driver_id), "driver")
        with self.assertRaises(ApiError):
            fuel_service.create_fuel_log({**payload, "amount": 299}, str(self.driver_id), "driver")
        self.db.fuel_logs.update_one({"_id": ObjectId(log["id"])}, {"$set": {"amount": 301}})
        with self.assertRaises(ApiError):
            fuel_service.approve_fuel_log(log["id"], str(self.admin_id), "admin")
        self.assertEqual(self.db.expenses.count_documents({}), 0)

    def test_weekly_remittance_assignment_cannot_receive_company_advance(self):
        self.db.assignments.update_one({"_id": self.assignment_id}, {"$set": {"target_enabled": True, "weekly_target": 700}})
        with self.assertRaises(ApiError) as caught:
            self.create_movement()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 0)
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 1000)

    def test_all_treasury_account_types_are_supported_without_provider_hardcoding(self):
        for account_type in ("cash", "momo", "bank"):
            account = {"_id": ObjectId(), "account_name": f"{account_type} source", "account_type": account_type,
                       "status": "active", "current_balance": 500}
            self.db.finance_accounts.insert_one(account)
            advance = fuel_advance_service.build_pending_fuel_advance(
                {"finance_account_id": str(account["_id"]), "issued_amount": 25},
                driver={"_id": self.driver_id}, assignment=None,
            )
            self.assertEqual(advance["finance_account_id"], account["_id"])


if __name__ == "__main__":
    unittest.main()
