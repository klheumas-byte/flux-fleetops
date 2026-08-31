from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import dispatch_finance_engine_service as engine
from services import collection_service
from utils.api_error import ApiError


class DispatchFinanceEngineTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).dispatch_finance_engine
        self.owner_id, self.admin_id, self.driver_id = ObjectId(), ObjectId(), ObjectId()
        self.vehicle_id, self.job_id, self.request_id, self.source_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        self.db.users.insert_many([
            {"_id": self.owner_id, "role": "owner", "full_name": "Fleet Owner"},
            {"_id": self.admin_id, "role": "admin", "full_name": "Finance Admin"},
            {"_id": self.driver_id, "role": "driver", "full_name": "Driver One"},
        ])
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "TEST-1", "km_per_litre": 10})
        self.db.dispatch_requests.insert_one({"_id": self.request_id, "approved_charge": 400, "distance_estimate_km": 20})
        self.db.dispatch_jobs.insert_one({
            "_id": self.job_id, "dispatch_job_id": "DSP-TEST-1", "dispatch_request_id": self.request_id,
            "vehicle_id": self.vehicle_id, "driver_id": self.driver_id, "dispatch_date": "2026-08-20",
            "status": "completed", "return_status": "dispatch_closed",
        })
        self.record_id = self.db.dispatch_financial_records.insert_one({
            "dispatch_job_id": self.job_id, "vehicle_id": self.vehicle_id, "driver_id": self.driver_id,
            "approved_charge": 400, "financial_status": "pending_collection",
        }).inserted_id
        self.db.dispatch_finance_settings.insert_many([
            {"setting_type": "fuel_price_per_litre", "value": 10, "effective_from": "2026-01-01"},
            {"setting_type": "maintenance_reserve_rate", "value": 25, "effective_from": "2026-01-01"},
        ])
        self.db.vehicle_maintenance_reserve_entries.create_index("source_key", unique=True)
        self.patches = [
            patch.object(engine, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(engine, "resolve_master_data_item", side_effect=self.resolve_source),
        ]
        for item in self.patches: item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def resolve_source(self, group, identifier, active_only=True):
        if group == "funding_sources" and str(identifier) == str(self.source_id):
            return {"_id": self.source_id, "name": "Smart Living", "active": True}
        return None

    def payload(self, pricing_type="standard", customer_charge=400, **updates):
        value = {
            "commercial_value": 400, "customer_charge": customer_charge, "pricing_type": pricing_type,
            "billable_distance_km": 18, "operational_distance_km": 20,
            "driver_compensation_mode": "amount", "driver_compensation_value": 50,
            "driver_adjustments": [{"category": "loading", "reason": "Heavy items", "mode": "amount", "value": 10}],
            "other_direct_costs": 5,
        }
        if pricing_type != "standard": value["funding_source_id"] = str(self.source_id)
        value.update(updates); return value

    def test_standard_400_flow_and_idempotent_reserve_posting(self):
        snapshot = engine.approve_finance_snapshot(str(self.job_id), self.payload(), current_user_id=str(self.admin_id), current_role="admin")
        repeated = engine.approve_finance_snapshot(str(self.job_id), self.payload(), current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(snapshot, repeated)
        self.assertEqual(snapshot["fuel"]["cost"], 20)
        self.assertEqual(snapshot["maintenance_reserve"]["amount"], 100)
        self.assertEqual(snapshot["driver_compensation"]["approved_amount"], 60)
        self.assertEqual(snapshot["expected_company_contribution"], 215)
        self.assertEqual(self.db.vehicle_maintenance_reserve_entries.count_documents({}), 1)
        self.db.vehicle_maintenance_reserve_entries.delete_many({})
        engine.approve_finance_snapshot(str(self.job_id), self.payload(), current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(self.db.vehicle_maintenance_reserve_entries.count_documents({}), 1)

    def test_subsidized_and_complimentary_preserve_full_values(self):
        subsidized = engine.build_finance_preview(str(self.job_id), self.payload("subsidized", 150), current_user_id=str(self.admin_id), current_role="admin")
        complimentary = engine.build_finance_preview(str(self.job_id), self.payload("complimentary", 0), current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual((subsidized["commercial_value"], subsidized["customer_charge"], subsidized["concession_value"]), (400, 150, 250))
        self.assertEqual((complimentary["commercial_value"], complimentary["customer_charge"], complimentary["concession_value"]), (400, 0, 400))
        self.assertEqual(subsidized["driver_compensation"]["approved_amount"], complimentary["driver_compensation"]["approved_amount"])
        self.assertEqual(subsidized["funding_source"]["name"], "Smart Living")

    def test_percentage_compensation_uses_commercial_value_not_discounted_charge(self):
        preview = engine.build_finance_preview(str(self.job_id), self.payload("subsidized", 150, driver_compensation_mode="percentage", driver_compensation_value=20, driver_adjustments=[]), current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(preview["driver_compensation"]["approved_amount"], 80)
        self.assertEqual(preview["driver_compensation"]["effective_percentage"], 20)

    def test_approved_and_final_snapshots_are_immutable_and_actuals_compare(self):
        estimate = engine.approve_finance_snapshot(str(self.job_id), self.payload(), current_user_id=str(self.admin_id), current_role="admin")
        self.db.dispatch_finance_settings.update_one({"setting_type": "maintenance_reserve_rate"}, {"$set": {"value": 30}})
        final = engine.finalize_finance_snapshot(str(self.job_id), {"actual_operational_distance_km": 30, "driver_compensation_mode": "amount", "driver_compensation_value": 70, "driver_adjustments": [], "actual_other_direct_costs": 8}, current_user_id=str(self.admin_id), current_role="admin")
        stored = self.db.dispatch_financial_records.find_one({"_id": self.record_id})
        self.assertEqual(stored["finance_snapshot"], estimate)
        self.assertEqual(final["basis"], "actual")
        self.assertEqual(final["maintenance_reserve"]["rate_percent"], 25)
        self.assertEqual(final["estimated_vs_actual"]["fuel_cost"], {"estimated": 20.0, "actual": 30.0})
        self.assertEqual(engine.finalize_finance_snapshot(str(self.job_id), {}, current_user_id=str(self.admin_id), current_role="admin"), final)

    def test_reserve_spend_requires_balance_and_is_idempotent(self):
        engine.approve_finance_snapshot(str(self.job_id), self.payload(), current_user_id=str(self.admin_id), current_role="admin")
        maintenance_id, expense_id = ObjectId(), ObjectId()
        expense = {"_id": expense_id, "vehicle_id": self.vehicle_id, "maintenance_job_id": maintenance_id, "amount": 40, "maintenance_reserve_amount": 40}
        first = engine.post_reserve_spend_for_expense(expense, actor_id=str(self.admin_id))
        second = engine.post_reserve_spend_for_expense(expense, actor_id=str(self.admin_id))
        self.assertEqual(first["balance"], 60)
        self.assertEqual(second["balance"], 60)
        self.assertEqual(self.db.vehicle_maintenance_reserve_entries.count_documents({}), 2)

    def test_analytics_derive_from_snapshots_and_dispatch_linked_collections(self):
        engine.approve_finance_snapshot(str(self.job_id), self.payload("subsidized", 150), current_user_id=str(self.admin_id), current_role="admin")
        self.db.collections.insert_one({"dispatch_job_id": self.job_id, "driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "amount": 150, "submitted_amount": 100, "status": "approved"})
        result = engine.dispatch_finance_analytics(current_user_id=str(self.admin_id), current_role="admin", preset="this_month")
        # Fixture date may be outside the runtime month, so use an explicit period.
        result = engine.dispatch_finance_analytics(current_user_id=str(self.admin_id), current_role="admin", start_date="2026-08-01", end_date="2026-08-31")
        self.assertEqual(result["summary"]["pricing"]["subsidized"]["count"], 1)
        self.assertEqual(result["summary"]["collections"], 150)
        self.assertEqual(result["summary"]["submissions"], 100)
        self.assertEqual(result["summary"]["outstanding_reconciliation"], 50)
        self.assertEqual(result["drivers"][0]["driver_name"], "Driver One")
        self.assertEqual(result["vehicles"][0]["vehicle_name"], "TEST-1")

    def test_dispatch_collection_submission_reuses_canonical_collection_idempotently(self):
        assignment_id = self.db.assignments.insert_one({"driver_id":self.driver_id,"vehicle_id":self.vehicle_id,"status":"active"}).inserted_id
        job = self.db.dispatch_jobs.find_one({"_id":self.job_id}); job["assignment_id"] = assignment_id
        record = self.db.dispatch_financial_records.find_one({"_id":self.record_id})
        with patch.object(collection_service, "get_collection", side_effect=lambda name:self.db[name]):
            first = collection_service.create_dispatch_collection_submission(job, record, amount_collected=400, amount_submitted=350, payment_method="cash", payment_reference="REF-1", finance_notes=None, current_user_id=str(self.driver_id))
            second = collection_service.create_dispatch_collection_submission(job, record, amount_collected=400, amount_submitted=350, payment_method="cash", payment_reference="REF-1", finance_notes=None, current_user_id=str(self.driver_id))
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(self.db.collections.count_documents({"dispatch_job_id":self.job_id}), 1)
            with self.assertRaises(ApiError):
                collection_service.create_dispatch_collection_submission(job, record, amount_collected=400, amount_submitted=300, payment_method="cash", payment_reference="REF-1", finance_notes=None, current_user_id=str(self.driver_id))

    def test_rbac_hides_company_profit_and_owner_controls_settings(self):
        with self.assertRaises(ApiError):
            engine.schedule_finance_setting("maintenance_reserve_rate", {"value": 30, "effective_from": "2026-09-01", "reason": "Review"}, current_user_id=str(self.admin_id), current_role="admin")
        engine.approve_finance_snapshot(str(self.job_id), self.payload(), current_user_id=str(self.admin_id), current_role="admin")
        driver = engine.dispatch_finance_analytics(current_user_id=str(self.driver_id), current_role="driver", start_date="2026-08-01", end_date="2026-08-31")
        self.assertNotIn("company_contribution", driver["summary"])
        with self.assertRaises(ApiError):
            engine.dispatch_finance_analytics(current_user_id=str(self.driver_id), current_role="driver", driver_id=str(self.admin_id), start_date="2026-08-01", end_date="2026-08-31")


if __name__ == "__main__":
    unittest.main()
