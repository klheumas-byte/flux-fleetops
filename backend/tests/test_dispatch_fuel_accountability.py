from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import dispatch_fuel_service as fuel_service
from services import dispatch_financial_service as financial_service
from services import dispatch_return_service as return_service
from utils.api_error import ApiError


class DispatchFuelSummaryTests(unittest.TestCase):
    def test_tank_capacity_estimates_consumption_distance_and_efficiency(self):
        summary = fuel_service.build_dispatch_fuel_summary(
            {
                "opening_fuel_level": 6,
                "opening_odometer": 1000,
                "opening_fuel_recorded_at": datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc),
                "closing_fuel_level": 3,
                "closing_odometer": 1100,
                "closing_fuel_recorded_at": datetime(2026, 7, 18, 18, 0, tzinfo=timezone.utc),
            },
            vehicle={"tank_capacity_litres": 80},
            fuel_logs=[{"litres": 10, "amount": 150, "status": "approved"}],
        )
        self.assertEqual(summary["opening_fuel_details"]["estimated_litres"], 60)
        self.assertEqual(summary["closing_fuel_details"]["estimated_litres"], 30)
        self.assertEqual(summary["estimated_fuel_consumed"], 40)
        self.assertEqual(summary["distance_travelled"], 100)
        self.assertEqual(summary["estimated_fuel_efficiency"], 2.5)
        self.assertTrue(summary["litre_values_are_estimates"])

    def test_missing_tank_capacity_preserves_gauge_and_distance_without_estimates(self):
        summary = fuel_service.build_dispatch_fuel_summary(
            {
                "opening_fuel_level": 6,
                "opening_odometer": 1000,
                "closing_fuel_level": 3,
                "closing_odometer": 1100,
            },
            vehicle={},
            fuel_logs=[],
        )
        self.assertEqual(summary["opening_fuel_level"], 6)
        self.assertEqual(summary["closing_fuel_level"], 3)
        self.assertEqual(summary["distance_travelled"], 100)
        self.assertIsNone(summary["estimated_fuel_consumed"])
        self.assertIsNone(summary["estimated_fuel_efficiency"])

    def test_missing_odometer_keeps_distance_and_efficiency_unavailable(self):
        summary = fuel_service.build_dispatch_fuel_summary(
            {
                "opening_fuel_level": 6,
                "opening_odometer": None,
                "closing_fuel_level": 3,
                "closing_odometer": 1100,
            },
            vehicle={"tank_capacity_litres": 80},
            fuel_logs=[{"litres": 10, "amount": 150, "status": "approved"}],
        )
        self.assertIsNone(summary["distance_travelled"])
        self.assertIsNone(summary["estimated_fuel_efficiency"])
        self.assertEqual(summary["estimated_fuel_consumed"], 40)

    def test_fuel_purchases_are_included_in_totals(self):
        summary = fuel_service.build_dispatch_fuel_summary(
            {},
            fuel_logs=[
                {"_id": ObjectId(), "litres": 12.5, "amount": 200, "status": "submitted"},
                {"_id": ObjectId(), "litres": 7.5, "amount": 100, "status": "approved"},
            ],
        )
        self.assertEqual(summary["total_fuel_litres_added"], 7.5)
        self.assertEqual(summary["total_fuel_cost"], 100)
        self.assertEqual(summary["pending_fuel_litres"], 12.5)
        self.assertEqual(summary["pending_fuel_cost"], 200)
        self.assertEqual(len(summary["fuel_purchases"]), 2)


class DispatchOpeningFuelTests(unittest.TestCase):
    def setUp(self):
        self.job_id = ObjectId()
        self.driver_id = ObjectId()
        self.movement_id = ObjectId()
        self.job = {
            "_id": self.job_id,
            "dispatch_job_id": "DJ-FUEL-TEST",
            "status": "accepted",
            "driver_id": self.driver_id,
            "vehicle_id": ObjectId(),
        }
        self.movement = {
            "_id": self.movement_id,
            "dispatch_job_id": self.job_id,
            "status": "approved",
        }

    def test_dispatch_start_gate_rejects_missing_opening_reading(self):
        with patch.object(fuel_service, "_find_movement", return_value=self.movement):
            with self.assertRaises(ApiError) as raised:
                fuel_service.assert_dispatch_opening_confirmed(self.job)
        self.assertEqual(
            raised.exception.message,
            "Record opening fuel level before starting this dispatch.",
        )

    def test_dispatch_gauge_rejects_non_eighth_values(self):
        for invalid_value in (0.5, "half", "25%"):
            with self.subTest(value=invalid_value), self.assertRaises(ApiError):
                fuel_service._validate_required_fuel_level(invalid_value, "opening_fuel_level")

    def test_dispatch_start_gate_accepts_complete_opening_reading(self):
        self.movement.update(
            {
                "opening_fuel_level": 6,
                "opening_odometer": 1000,
                "opening_fuel_recorded_at": datetime.now(timezone.utc),
            }
        )
        with patch.object(fuel_service, "_find_movement", return_value=self.movement):
            self.assertIs(fuel_service.assert_dispatch_opening_confirmed(self.job), self.movement)

    def test_dispatch_start_gate_accepts_missing_odometer(self):
        self.movement.update(
            {
                "opening_fuel_level": 6,
                "opening_odometer": None,
                "opening_fuel_recorded_at": datetime.now(timezone.utc),
            }
        )
        with patch.object(fuel_service, "_find_movement", return_value=self.movement):
            self.assertIs(fuel_service.assert_dispatch_opening_confirmed(self.job), self.movement)

    def test_opening_confirmation_is_atomic_and_duplicate_safe(self):
        movement_collection = MagicMock()
        movement_collection.update_one.return_value = SimpleNamespace(matched_count=1)
        with patch.object(fuel_service, "_get_job", return_value=self.job), patch.object(
            fuel_service, "_ensure_predeparture_movement", return_value=self.movement
        ), patch.object(
            fuel_service, "vehicle_movements_collection", return_value=movement_collection
        ), patch.object(
            fuel_service, "get_dispatch_fuel_accountability", return_value={"summary": {"fuel_summary_status": "opening_confirmed"}}
        ):
            result = fuel_service.record_dispatch_opening_fuel(
                str(self.job_id),
                {"opening_fuel_level": "6/8", "opening_odometer": 1000},
                current_user_id=str(self.driver_id),
                current_role="driver",
            )
        self.assertEqual(result["summary"]["fuel_summary_status"], "opening_confirmed")
        update_fields = movement_collection.update_one.call_args.args[1]["$set"]
        self.assertEqual(update_fields["opening_fuel_level"], 6)
        self.assertEqual(update_fields["opening_odometer"], 1000)

        self.movement["opening_fuel_recorded_at"] = datetime.now(timezone.utc)
        with patch.object(fuel_service, "_get_job", return_value=self.job), patch.object(
            fuel_service, "_ensure_predeparture_movement", return_value=self.movement
        ):
            with self.assertRaises(ApiError) as raised:
                fuel_service.record_dispatch_opening_fuel(
                    str(self.job_id),
                    {"opening_fuel_level": 6, "opening_odometer": 1000},
                    current_user_id=str(self.driver_id),
                    current_role="driver",
                )
        self.assertEqual(raised.exception.status_code, 409)

    def test_opening_confirmation_allows_missing_odometer(self):
        movement_collection = MagicMock()
        movement_collection.update_one.return_value = SimpleNamespace(matched_count=1)
        with patch.object(fuel_service, "_get_job", return_value=self.job), patch.object(
            fuel_service, "_ensure_predeparture_movement", return_value=self.movement
        ), patch.object(
            fuel_service, "vehicle_movements_collection", return_value=movement_collection
        ), patch.object(
            fuel_service, "get_dispatch_fuel_accountability", return_value={"summary": {}}
        ):
            fuel_service.record_dispatch_opening_fuel(
                str(self.job_id),
                {"opening_fuel_level": 1},
                current_user_id=str(self.driver_id),
                current_role="driver",
            )
        update_fields = movement_collection.update_one.call_args.args[1]["$set"]
        self.assertEqual(update_fields["opening_fuel_level"], 1)
        self.assertIsNone(update_fields["opening_odometer"])


class DispatchFuelClosureTests(unittest.TestCase):
    def test_final_closure_is_blocked_without_closing_fuel_confirmation(self):
        job = {
            "_id": ObjectId(),
            "return_status": "inspection_completed",
        }
        movement = {
            "_id": ObjectId(),
            "opening_fuel_level": 6,
            "opening_odometer": 1000,
            "opening_fuel_recorded_at": datetime.now(timezone.utc),
        }
        with patch.object(return_service, "_get_dispatch_job_document", return_value=job), patch.object(
            return_service, "_ensure_linked_vehicle_movement", return_value=movement
        ):
            with self.assertRaises(ApiError) as raised:
                return_service.close_dispatch_return(
                    str(job["_id"]),
                    {},
                    current_user_id=str(ObjectId()),
                    current_role="admin",
                )
        self.assertEqual(
            raised.exception.message,
            "Record closing fuel level before closing this dispatch.",
        )


class DispatchFuelFinancialTests(unittest.TestCase):
    def test_internal_dispatch_fuel_is_an_expense_without_customer_revenue(self):
        job_id = ObjectId()
        record = {
            "_id": ObjectId(),
            "dispatch_job_id": job_id,
            "dispatch_financial_type": "internal_company",
            "approved_charge": 0,
            "amount_paid": 0,
            "driver_compensation_type": "none",
        }
        job = {
            "_id": job_id,
            "dispatch_request_id": ObjectId(),
            "dispatch_financial_type": "internal_company",
            "amount_paid": 0,
            "driver_compensation_type": "none",
        }
        expense_collection = MagicMock()
        expense_collection.find.return_value = []
        incident_collection = MagicMock()
        incident_collection.find.return_value = []
        fuel_collection = MagicMock()
        fuel_collection.find.return_value = [{"amount": 100, "status": "approved"}]
        with patch.object(financial_service, "_get_dispatch_request", return_value={
            "dispatch_financial_type": "internal_company",
            "approved_charge": 0,
        }), patch.object(
            financial_service, "_get_vehicle_movement_for_job", return_value=None
        ), patch.object(
            financial_service, "dispatch_financial_expenses_collection", return_value=expense_collection
        ), patch.object(
            financial_service, "dispatch_financial_incidents_collection", return_value=incident_collection
        ), patch.object(
            financial_service, "fuel_logs_collection", return_value=fuel_collection
        ):
            synced = financial_service._sync_financial_record(record, job_document=job, persist=False)
        self.assertEqual(synced["amount_collected_from_customer"], 0)
        self.assertEqual(synced["actual_fuel_cost"], 100)
        self.assertEqual(synced["company_operational_cost"], 100)
        self.assertEqual(synced["actual_net_revenue"], -100)

    def test_dispatch_fuel_log_replaces_duplicate_legacy_fuel_expense(self):
        job_id = ObjectId()
        record = {
            "_id": ObjectId(),
            "dispatch_job_id": job_id,
            "dispatch_financial_type": "internal_company",
            "approved_charge": 0,
            "amount_paid": 0,
            "driver_compensation_type": "none",
        }
        job = {
            "_id": job_id,
            "dispatch_request_id": ObjectId(),
            "dispatch_financial_type": "internal_company",
            "amount_paid": 0,
            "driver_compensation_type": "none",
        }
        expense_collection = MagicMock()
        expense_collection.find.return_value = [
            {"expense_type": "fuel", "amount": 100, "status": "approved"},
            {"expense_type": "toll", "amount": 20, "status": "approved"},
        ]
        incident_collection = MagicMock()
        incident_collection.find.return_value = []
        fuel_collection = MagicMock()
        fuel_collection.find.return_value = [{"amount": 100, "status": "approved"}]
        with patch.object(financial_service, "_get_dispatch_request", return_value={
            "dispatch_financial_type": "internal_company",
            "approved_charge": 0,
        }), patch.object(
            financial_service, "_get_vehicle_movement_for_job", return_value=None
        ), patch.object(
            financial_service, "dispatch_financial_expenses_collection", return_value=expense_collection
        ), patch.object(
            financial_service, "dispatch_financial_incidents_collection", return_value=incident_collection
        ), patch.object(
            financial_service, "fuel_logs_collection", return_value=fuel_collection
        ):
            synced = financial_service._sync_financial_record(record, job_document=job, persist=False)
        self.assertEqual(synced["actual_fuel_cost"], 100)
        self.assertEqual(synced["approved_expenses"], 120)


if __name__ == "__main__":
    unittest.main()
