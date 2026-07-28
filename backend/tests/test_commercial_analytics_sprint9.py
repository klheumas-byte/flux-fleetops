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

from services import commercial_analytics_service as analytics
from services import fleet_owner_service
from utils.api_error import ApiError


class CommercialAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_sprint_9
        self.admin_id, self.account_id = ObjectId(), ObjectId()
        self.profile_id, self.other_profile_id = ObjectId(), ObjectId()
        self.driver_id, self.other_driver_id = ObjectId(), ObjectId()
        self.vehicle_id, self.other_vehicle_id = ObjectId(), ObjectId()
        self.db.users.insert_many([
            {"_id": self.admin_id, "role": "admin", "status": "active"},
            {"_id": self.account_id, "role": "fleet_owner", "status": "active"},
            {"_id": self.driver_id, "role": "driver", "status": "active"},
            {"_id": self.other_driver_id, "role": "driver", "status": "active"},
        ])
        self.db.fleet_owners.insert_one({
            "_id": self.profile_id, "account_id": self.account_id, "status": "active",
        })
        self.db.vehicles.insert_many([
            {"_id": self.vehicle_id, "registration_number": "SAFE-1", "ownership_type": "third_party_owned", "fleet_owner_id": self.profile_id},
            {"_id": self.other_vehicle_id, "registration_number": "HIDDEN-2", "ownership_type": "third_party_owned", "fleet_owner_id": self.other_profile_id},
        ])
        self.db.assignments.insert_many([
            {"vehicle_id": self.vehicle_id, "driver_id": self.driver_id, "start_date": "2026-07-01", "end_date": "2026-07-15"},
            {"vehicle_id": self.vehicle_id, "driver_id": self.other_driver_id, "start_date": "2026-07-16", "allocation_active": True},
        ])
        self.db.rides.insert_many([
            {"vehicle_id": self.vehicle_id, "trip_date": "2026-07-10", "status": "completed", "distance_km": 20},
            {"vehicle_id": self.vehicle_id, "trip_date": "2026-07-20", "status": "completed", "distance_km": 90},
            {"vehicle_id": self.other_vehicle_id, "driver_id": self.driver_id, "trip_date": "2026-07-10", "status": "completed", "distance_km": 999},
        ])
        self.db.collections.insert_many([
            {"vehicle_id": self.vehicle_id, "driver_id": self.driver_id, "collection_date": "2026-07-10", "status": "approved", "amount": 1000},
            {"vehicle_id": self.vehicle_id, "driver_id": self.other_driver_id, "collection_date": "2026-07-20", "status": "approved", "amount": 400},
            {"vehicle_id": self.other_vehicle_id, "collection_date": "2026-07-10", "status": "approved", "amount": 9999},
        ])
        self.db.fuel_logs.insert_one({"vehicle_id": self.vehicle_id, "fuel_date": "2026-07-10", "status": "approved", "amount": 100})
        self.db.maintenance_jobs.insert_one({
            "vehicle_id": self.vehicle_id, "completion_date": "2026-07-12", "status": "completed", "estimated_cost": 200, "actual_cost": None,
        })
        self.db.expenses.insert_one({"vehicle_id": self.vehicle_id, "expense_date": "2026-07-11", "status": "paid", "amount": 50})
        self.db.driver_private_finance.insert_one({
            "driver_id": self.driver_id, "date": "2026-07-10", "net_earnings": 777777,
        })
        patches = [
            patch.object(analytics, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(fleet_owner_service, "get_collection", side_effect=lambda name: self.db[name]),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_fleet_owner_scope_and_profitability_formula(self):
        result = analytics.get_commercial_analytics(
            role="fleet_owner", user_id=str(self.account_id), start_date="2026-07-01", end_date="2026-07-31",
        )
        self.assertEqual(result["scope"]["vehicle_count"], 1)
        self.assertEqual(result["summary"]["gross_revenue"], 1400)
        self.assertEqual(result["summary"]["total_recorded_operating_cost"], 350)
        self.assertEqual(result["summary"]["net_profitability"], 1050)
        self.assertFalse(result["data_quality"]["complete"])
        self.assertNotIn("777777", str(result))

    def test_fleet_owner_cannot_substitute_vehicle(self):
        with self.assertRaises(ApiError) as error:
            analytics.get_commercial_analytics(
                role="fleet_owner", user_id=str(self.account_id), vehicle_id=str(self.other_vehicle_id),
                start_date="2026-07-01", end_date="2026-07-31",
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_driver_uses_historical_assignment_and_hides_fleet_costs(self):
        result = analytics.get_commercial_analytics(
            role="driver", user_id=str(self.driver_id), start_date="2026-07-01", end_date="2026-07-31",
        )
        self.assertEqual(result["summary"]["completed_trips"], 1)
        self.assertEqual(result["summary"]["distance_km"], 20)
        self.assertEqual(result["summary"]["recognized_company_revenue"], 1000)
        self.assertIsNone(result["summary"]["fuel_cost"])
        self.assertNotIn("777777", str(result))

    def test_driver_cannot_substitute_driver(self):
        with self.assertRaises(ApiError) as error:
            analytics.get_commercial_analytics(
                role="driver", user_id=str(self.driver_id), driver_id=str(self.other_driver_id),
                start_date="2026-07-01", end_date="2026-07-31",
            )
        self.assertEqual(error.exception.status_code, 403)

    def test_filters_pagination_and_export_are_bounded(self):
        result = analytics.get_commercial_analytics(
            role="admin", user_id=str(self.admin_id), start_date="2026-07-01", end_date="2026-07-31",
            status="completed", page=1, page_size=1,
        )
        self.assertEqual(result["pagination"]["page_size"], 1)
        self.assertEqual(len(result["vehicles"]), 1)
        csv_text = analytics.export_commercial_analytics_csv(
            role="fleet_owner", user_id=str(self.account_id), start_date="2026-07-01", end_date="2026-07-31",
            period="daily", vehicle_id=None, driver_id=None, fleet_owner_id=None, operation_type=None, status=None,
        )
        self.assertIn("SAFE-1", csv_text)
        self.assertNotIn("HIDDEN-2", csv_text)


if __name__ == "__main__":
    unittest.main()
