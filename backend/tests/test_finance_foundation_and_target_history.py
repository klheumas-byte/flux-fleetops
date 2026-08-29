from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import expense_service, finance_account_service, finance_foundation_service, master_data_service, user_service
from utils.api_error import ApiError


class FinanceFoundationAndTargetHistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().finance_foundation
        self.owner_id, self.admin_id, self.payer_id, self.driver_id = (ObjectId() for _ in range(4))
        self.vehicle_id, self.account_id, self.maintenance_id = ObjectId(), ObjectId(), ObjectId()
        self.db.users.insert_many([
            {"_id": self.owner_id, "role": "owner", "status": "active", "full_name": "Owner"},
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Requester"},
            {"_id": self.payer_id, "role": "admin", "status": "active", "full_name": "Payer"},
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "driver_profile": {"target_amount": 1000, "target_frequency": "weekly", "target_enabled": True, "settings_effective_date": "2026-01-01"}},
        ])
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "FLX-1", "status": "assigned"})
        self.db.finance_accounts.insert_one({"_id": self.account_id, "account_name": "Main", "account_type": "bank", "status": "active", "current_balance": 0, "opening_balance": 0})
        self.db.maintenance_jobs.insert_one({"_id": self.maintenance_id, "vehicle_id": self.vehicle_id, "title": "Battery replacement", "maintenance_type": "battery_replacement", "actual_cost": 1500, "status": "completed"})
        self.sources = {}
        for index, name in enumerate(["Fleet Sales / Driver Collection", "Smart Living", "Other"]):
            source_id = ObjectId(); self.sources[name] = source_id
            self.db.master_data.insert_one({"_id": source_id, "data_type": "funding_sources", "name": name, "normalized_name": name.lower(), "active": True, "archived": False, "sort_order": index})
        modules = [expense_service, finance_account_service, finance_foundation_service, master_data_service, user_service]
        self.patches = [patch.object(module, "get_collection", side_effect=lambda name, db=self.db: db[name]) for module in modules]
        for item in self.patches: item.start(); self.addCleanup(item.stop)

    def contribution(self):
        return finance_foundation_service.create_funding_contribution({
            "funding_source_id": str(self.sources["Smart Living"]), "finance_account_id": str(self.account_id),
            "amount": 10000, "contribution_date": "2026-08-25", "description": "Capital contribution",
        }, current_user_id=str(self.owner_id), current_role="owner", idempotency_key="smart-living-10k")

    def battery_expense(self, source="Smart Living", amount=1500, maintenance=True):
        return expense_service.create_expense({
            "expense_title": "Battery", "expense_category": "battery", "amount": amount,
            "expense_date": "2026-08-26", "vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id),
            "finance_account_id": str(self.account_id), "funding_source_id": str(self.sources[source]),
            "paid_by": str(self.payer_id), "payment_method": "bank_transfer",
            "maintenance_job_id": str(self.maintenance_id) if maintenance else None,
        }, current_user_id=str(self.admin_id), current_role="admin", idempotency_key=f"expense-{source}-{amount}")

    def test_funding_contribution_is_idempotent_and_not_sales(self):
        first = self.contribution(); second = self.contribution()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.db.funding_contributions.count_documents({}), 1)
        self.assertEqual(self.db.finance_accounts.find_one({"_id": self.account_id})["current_balance"], 10000)
        self.assertEqual(self.db.collections.count_documents({}), 0)

    def test_battery_expense_requires_source_links_maintenance_and_separates_payer(self):
        self.contribution(); expense = self.battery_expense()
        self.assertEqual(expense["funding_source_snapshot"]["name"], "Smart Living")
        self.assertEqual(expense["paid_by"], str(self.payer_id))
        self.assertEqual(self.db.maintenance_jobs.find_one({"_id": self.maintenance_id})["expense_id"], ObjectId(expense["id"]))
        with self.assertRaises(ApiError) as own_approval:
            expense_service.approve_expense(expense["id"], str(self.admin_id))
        self.assertEqual(own_approval.exception.status_code, 403)
        expense_service.approve_expense(expense["id"], str(self.owner_id))
        expense_service.mark_expense_paid(expense["id"], str(self.owner_id))
        position = finance_foundation_service.funding_position(start_date="2026-08-01", end_date="2026-08-31")
        self.assertEqual(position["money_in"], 10000)
        self.assertEqual(position["expenses_out"], 1500)
        self.assertEqual(position["net_funding_position"], 8500)
        self.assertEqual(self.db.collections.count_documents({}), 0)

    def test_other_source_needs_description_and_blank_source_is_rejected(self):
        base = {"expense_title": "Misc", "expense_category": "other", "amount": 10, "expense_date": "2026-08-26", "finance_account_id": str(self.account_id), "paid_by": str(self.payer_id), "payment_method": "cash"}
        with self.assertRaises(ApiError): expense_service.create_expense(base, str(self.admin_id), "admin")
        with self.assertRaises(ApiError): expense_service.create_expense({**base, "funding_source_id": str(self.sources["Other"])}, str(self.admin_id), "admin")

    def test_collection_reconciliation_only_offsets_driver_collection_funded_expense(self):
        self.db.collections.insert_one({"driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "amount": 5500, "submitted_amount": 4700, "status": "approved", "collection_date": "2026-08-27"})
        self.db.expenses.insert_many([
            {"driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "amount": 1200, "status": "paid", "expense_date": "2026-08-27", "funding_source_id": self.sources["Smart Living"], "funding_source_snapshot": {"name": "Smart Living"}},
            {"driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "amount": 800, "status": "approved", "expense_date": "2026-08-27", "funding_source_id": self.sources["Fleet Sales / Driver Collection"], "funding_source_snapshot": {"name": "Fleet Sales / Driver Collection"}},
        ])
        row = finance_foundation_service.reconciliation_report(current_user_id=str(self.owner_id), current_role="owner", driver_id=str(self.driver_id), start_date="2026-08-24", end_date="2026-08-29")["drivers"][0]
        self.assertEqual(row["gross_collections"], 5500)
        self.assertEqual(row["fleet_sales_funded_expenses"], 800)
        self.assertEqual(row["expected_cash_submission"], 4700)
        self.assertEqual(row["amount_submitted"], 4700)
        self.assertEqual(row["outstanding_unsubmitted_amount"], 0)
        self.assertEqual(row["target"], 1000)
        self.assertEqual(row["target_achievement_percentage"], 550)
        with self.assertRaises(ApiError):
            finance_foundation_service.reconciliation_report(current_user_id=str(ObjectId()), current_role="driver", driver_id=str(self.driver_id), start_date="2026-08-24", end_date="2026-08-29")

    def test_future_target_preserves_historical_target_and_is_owner_only(self):
        updated = user_service.schedule_driver_target(driver_id=str(self.driver_id), payload={"target_amount": 1400, "target_frequency": "weekly", "effective_from": "2026-09-07", "reason": "September target"}, current_user_id=str(self.owner_id), current_role="owner")
        history = updated["driver_profile"]["target_history"]
        self.assertEqual(len(history), 2)
        stored = self.db.users.find_one({"_id": self.driver_id})
        self.assertEqual(finance_foundation_service.target_for_date(stored, date(2026, 8, 29))["target_amount"], 1000)
        self.assertEqual(finance_foundation_service.target_for_date(stored, date(2026, 9, 7))["target_amount"], 1400)
        self.assertEqual(stored["driver_profile"]["target_amount"], 1000)
        with self.assertRaises(ApiError) as denied:
            user_service.schedule_driver_target(driver_id=str(self.driver_id), payload={"target_amount": 2000, "effective_from": "2026-10-01", "reason": "No"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(denied.exception.status_code, 403)

    def test_vehicle_history_does_not_double_count_linked_maintenance(self):
        expense_id = ObjectId()
        self.db.collections.insert_one({"driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "amount": 20000, "status": "approved", "collection_date": "2026-08-20"})
        self.db.expenses.insert_one({"_id": expense_id, "vehicle_id": self.vehicle_id, "amount": 3000, "status": "paid", "expense_date": "2026-08-21", "funding_source_snapshot": {"name": "Smart Living"}})
        self.db.maintenance_jobs.update_one({"_id": self.maintenance_id}, {"$set": {"expense_id": expense_id, "actual_cost": 3000}})
        history = finance_foundation_service.vehicle_finance_history(str(self.vehicle_id))
        self.assertEqual(history["revenue_sales"], 20000)
        self.assertEqual(history["lifetime_cost"], 3000)
        self.assertEqual(history["net_contribution"], 17000)


if __name__ == "__main__":
    unittest.main()
