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

from services import fuel_service, ride_service
from services.master_data_service import MASTER_DATA_DEFAULTS
from utils.api_error import ApiError


class TripEarningsTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().trip_earnings
        self.driver_id, self.other_driver_id, self.admin_id, self.vehicle_id = (ObjectId() for _ in range(4))
        self.db.users.insert_many([
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver One"},
            {"_id": self.other_driver_id, "role": "driver", "status": "active", "full_name": "Driver Two"},
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Admin"},
        ])
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "GT-1"})
        self.db.assignments.insert_one({"driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "status": "active"})
        self.source_ids = {name: ObjectId() for name in ["Uber", "Bolt", "Yango", "Flux Booking", "Other"]}
        self.purpose_id = ObjectId()
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        self.patches = [
            patch.object(ride_service, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(ride_service, "resolve_master_data_item", side_effect=self.resolve_master),
            patch.object(ride_service, "create_notification"),
            patch.object(ride_service, "notify_roles"),
            patch.object(ride_service, "get_ttl_cached", return_value=None),
            patch.object(ride_service, "set_ttl_cached", side_effect=lambda _key, value, **_kwargs: value),
            patch.object(ride_service, "now_utc", return_value=datetime(2026, 10, 1, 12, tzinfo=timezone.utc)),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.context.pop()

    def resolve_master(self, data_type, value, active_only=True):
        if data_type == "ride_sources":
            for name, item_id in self.source_ids.items():
                if value in {name, item_id, str(item_id)}:
                    return {"_id": item_id, "name": name, "active": True}
        if data_type == "ride_purposes" and value in {"Company Ride", self.purpose_id, str(self.purpose_id)}:
            return {"_id": self.purpose_id, "name": "Company Ride", "active": True}
        return None

    def payload(self):
        return {
            "vehicle_id": str(self.vehicle_id), "trip_source_id": "Uber", "trip_purpose_id": "Company Ride",
            "trip_date": "2026-10-01", "pickup_area": "Airport", "destination_area": "Osu",
            "status": "Completed", "actual_fare": 125, "platform_fee": 25, "payment_method": "MoMo",
        }

    def test_driver_earnings_are_validated_summarized_and_private(self):
        created = ride_service.create_ride(self.payload(), str(self.driver_id), "driver")
        self.assertEqual(created["net_earnings"], 100)
        self.assertEqual(created["payment_method"], "MoMo")

        summary = ride_service.get_ride_summary(str(self.driver_id), "driver")
        self.assertEqual(summary["earnings"]["today"]["gross_charged"], 125)
        self.assertEqual(summary["earnings"]["today"]["platform_fees"], 25)
        self.assertEqual(summary["earnings"]["today"]["net_earnings"], 100)
        self.assertEqual(summary["earnings"]["today"]["trip_count"], 1)
        self.assertEqual(summary["earnings"]["week"]["trip_count"], 1)
        self.assertEqual(summary["earnings"]["month"]["trip_count"], 1)
        self.assertEqual(summary["earnings"]["today"]["payment_method_breakdown"][0]["label"], "MoMo")
        self.assertEqual(summary["earnings"]["today"]["source_breakdown"][0]["label"], "Uber")

        admin_rows = ride_service.list_rides(str(self.admin_id), "admin")["rides"]
        self.assertNotIn("actual_fare", admin_rows[0])
        self.assertNotIn("net_earnings", admin_rows[0])
        self.assertNotIn("earnings", ride_service.get_ride_summary(str(self.admin_id), "admin"))
        self.assertEqual(ride_service.list_rides(str(self.other_driver_id), "driver")["rides"], [])
        self.assertEqual(self.db.collections.count_documents({}), 0)

        invalid = self.payload() | {"platform_fee": 126}
        with self.assertRaises(ApiError):
            ride_service.create_ride(invalid, str(self.driver_id), "driver")

    def test_supported_sources_and_payment_methods(self):
        self.assertTrue({"Uber", "Bolt", "Yango", "Flux Booking", "Other"}.issubset(MASTER_DATA_DEFAULTS["ride_sources"]))
        for index, (source, method) in enumerate(zip(["Uber", "Bolt"], ["Cash", "MoMo"])):
            created = ride_service.create_ride(
                self.payload() | {"trip_source_id": source, "payment_method": method, "trip_date": f"2026-09-{20 + index}"},
                str(self.driver_id), "driver",
            )
            self.assertEqual(created["trip_source"], source)
            self.assertEqual(created["payment_method"], method)
        with self.assertRaises(ApiError):
            ride_service.create_ride(self.payload() | {"actual_fare": -1}, str(self.driver_id), "driver")
        with self.assertRaises(ApiError):
            ride_service.create_ride(self.payload() | {"payment_method": "Platform/App"}, str(self.driver_id), "driver")

    def test_private_earnings_filters_use_trip_rows_once_and_only_for_authenticated_driver(self):
        ride_service.create_ride(self.payload(), str(self.driver_id), "driver")
        other_vehicle = ObjectId()
        self.db.vehicles.insert_one({"_id": other_vehicle, "registration_number": "GT-2"})
        self.db.assignments.insert_one({"driver_id": self.other_driver_id, "vehicle_id": other_vehicle, "status": "active"})
        ride_service.create_ride(
            self.payload() | {"vehicle_id": str(other_vehicle), "actual_fare": 500},
            str(self.other_driver_id), "driver",
        )
        result = ride_service.get_driver_earnings(
            str(self.driver_id), period="custom", start_date="2026-10-01", end_date="2026-10-01",
            source="Uber", payment_method="MoMo",
        )
        self.assertEqual(result["summary"], {
            "trip_count": 1, "gross_earnings": 125.0, "platform_fees": 25.0,
            "net_earnings": 100.0, "cash": 0.0, "momo": 125.0,
        })
        self.assertEqual(len(result["transactions"]), 1)
        self.assertEqual(result["transactions"][0]["id"], str(self.db.rides.find_one({"driver_id": self.driver_id})["_id"]))
        self.assertEqual(self.db.collections.count_documents({}), 0)

    def test_booking_amount_source_and_reference_are_authoritative_and_unique(self):
        booking_id = self.db.bookings.insert_one({
            "booking_id": "BKG-1", "driver_id": self.driver_id, "vehicle_id": self.vehicle_id,
            "pickup_date": "2026-10-01", "pickup_time": "09:00", "pickup_location": "A",
            "destination": "B", "expected_fare": 80, "status": "Scheduled", "is_recurring_template": False,
        }).inserted_id
        created = ride_service.convert_booking_to_ride(
            str(booking_id), {"trip_source_id": "Uber", "actual_fare": 999, "platform_fee": 10, "payment_method": "MoMo"},
            str(self.driver_id), "driver",
        )
        self.assertEqual(created["trip_source"], "Flux Booking")
        self.assertEqual(created["actual_fare"], 80)
        self.assertEqual(created["net_earnings"], 70)
        with self.assertRaises(ApiError) as caught:
            ride_service.convert_booking_to_ride(str(booking_id), {}, str(self.driver_id), "driver")
        self.assertEqual(caught.exception.status_code, 409)


class WeeklyRemittanceFuelTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().remittance_fuel
        self.driver_id, self.vehicle_id, self.assignment_id, self.station_id = (ObjectId() for _ in range(4))
        self.assignment = {
            "_id": self.assignment_id, "driver_id": self.driver_id, "vehicle_id": self.vehicle_id,
            "status": "active", "target_enabled": True, "weekly_target": 700, "start_date": "2026-09-01",
        }
        self.db.assignments.insert_one(self.assignment)
        self.db.users.insert_one({"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver"})
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "GT-2", "fuel_type": "petrol"})
        self.db.fuel_stations.insert_one({"_id": self.station_id, "station_name": "Shell", "status": "active"})
        self.app = Flask(__name__)
        self.context = self.app.app_context()
        self.context.push()
        self.notify_patch = patch.object(fuel_service, "notify_roles")
        self.notify = self.notify_patch.start()
        self.collection_patch = patch.object(fuel_service, "get_collection", side_effect=lambda name: self.db[name])
        self.collection_patch.start()
        self.context_patch = patch.object(fuel_service, "_resolve_driver_submission_context", return_value={
            "assignment_id": str(self.assignment_id), "driver_id": str(self.driver_id), "vehicle_id": str(self.vehicle_id),
        })
        self.context_patch.start()

    def tearDown(self):
        self.context_patch.stop()
        self.collection_patch.stop()
        self.notify_patch.stop()
        self.context.pop()

    def payload(self):
        return {"fuel_station_id": str(self.station_id), "fuel_type": "petrol", "litres": 10, "amount": 150, "fuel_date": "2026-10-01", "payment_method": "cash"}

    def test_weekly_remittance_fuel_is_recorded_without_fake_approval(self):
        created = fuel_service.create_fuel_log(self.payload(), str(self.driver_id), "driver")
        stored = self.db.fuel_logs.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(stored["status"], "recorded")
        self.assertEqual(stored["recorded_by"], self.driver_id)
        self.assertIsNotNone(stored["recorded_at"])
        self.assertIsNone(stored["approved_by"])
        self.assertEqual(len(self.db.vehicles.find_one({"_id": self.vehicle_id})["fuel_history"]), 1)
        result = fuel_service.list_fuel_logs(str(self.driver_id), "driver")
        self.assertEqual(result["logs"][0]["fuel_classification"], "weekly_remittance_fuel")
        self.assertEqual(result["analytics"]["total_fuel_spend"], 150)
        self.assertEqual(result["analytics"]["total_litres"], 10)
        self.notify.assert_not_called()
        with self.assertRaises(ApiError):
            fuel_service.approve_fuel_log(created["id"], str(ObjectId()), "admin")
        self.assertEqual(len(self.db.vehicles.find_one({"_id": self.vehicle_id})["fuel_history"]), 1)

    def test_non_remittance_fuel_keeps_review_flow(self):
        self.db.assignments.update_one({"_id": self.assignment_id}, {"$set": {"target_enabled": False}})
        created = fuel_service.create_fuel_log(self.payload(), str(self.driver_id), "driver")
        stored = self.db.fuel_logs.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(stored["status"], "submitted")
        self.assertEqual(created["fuel_classification"], "operational_fuel")
        self.assertNotIn("recorded_at", stored)
        self.assertIsNone(self.db.vehicles.find_one({"_id": self.vehicle_id}).get("fuel_history"))
        self.notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
