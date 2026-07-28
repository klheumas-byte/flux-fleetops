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

from services import fleet_owner_service as owners
from services import user_service
from utils.api_error import ApiError


class FleetOwnerScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_sprint_5_6
        self.account_id = ObjectId()
        self.other_account_id = ObjectId()
        self.owner_id = ObjectId()
        self.other_owner_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.other_vehicle_id = ObjectId()
        self.driver_id = ObjectId()
        self.db.users.insert_many([
            {"_id": self.account_id, "role": "fleet_owner", "status": "active", "full_name": "Owner A"},
            {"_id": self.other_account_id, "role": "fleet_owner", "status": "active", "full_name": "Owner B"},
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver A"},
        ])
        self.db.fleet_owners.insert_many([
            {"_id": self.owner_id, "account_id": self.account_id, "name": "Owner A", "status": "active"},
            {"_id": self.other_owner_id, "account_id": self.other_account_id, "name": "Owner B", "status": "active"},
        ])
        self.db.vehicles.insert_many([
            {
                "_id": self.vehicle_id, "registration_number": "OWN-100",
                "ownership_type": "third_party_owned", "fleet_owner_id": self.owner_id,
                "status": "assigned", "make": "Ford", "model": "Transit",
            },
            {
                "_id": self.other_vehicle_id, "registration_number": "OTHER-200",
                "ownership_type": "third_party_owned", "fleet_owner_id": self.other_owner_id,
                "status": "available",
            },
        ])
        self.db.assignments.insert_one({
            "_id": ObjectId(), "vehicle_id": self.vehicle_id, "driver_id": self.driver_id,
            "allocation_active": True, "status": "active", "target_enabled": True,
            "target_amount": 1000, "operating_mode": "hybrid", "created_at": datetime.now(timezone.utc),
        })
        self.db.collections.insert_many([
            {"vehicle_id": self.vehicle_id, "amount": 800, "status": "approved", "collection_date": "2026-07-27"},
            {"vehicle_id": self.other_vehicle_id, "amount": 9000, "status": "approved", "collection_date": "2026-07-27"},
        ])
        self.db.fuel_logs.insert_one({
            "vehicle_id": self.vehicle_id, "amount": 100, "status": "approved", "fuel_date": "2026-07-27"
        })
        self.db.maintenance_jobs.insert_one({
            "_id": ObjectId(), "vehicle_id": self.vehicle_id, "title": "Service",
            "actual_cost": 150, "status": "completed", "completion_date": "2026-07-27",
        })
        self.db.expenses.insert_many([
            {"vehicle_id": self.vehicle_id, "amount": 50, "status": "paid", "expense_date": "2026-07-27"},
            # Driver-private item is unrelated to the vehicle and must not enter the formula.
            {"driver_id": self.driver_id, "amount": 500, "status": "paid", "expense_date": "2026-07-27"},
        ])
        self.collection_patch = patch.object(owners, "get_collection", side_effect=lambda name: self.db[name])
        self.collection_patch.start()
        self.addCleanup(self.collection_patch.stop)

    def test_dashboard_contains_only_linked_vehicles_and_safe_profitability(self):
        result = owners.owner_dashboard(str(self.account_id), "2026-07-27", "2026-07-27")
        self.assertEqual(result["summary"]["total_linked_vehicles"], 1)
        self.assertEqual([item["registration_number"] for item in result["vehicles"]], ["OWN-100"])
        totals = result["profitability"]["totals"]
        self.assertEqual(totals["gross_revenue"], 800)
        self.assertEqual(totals["total_recorded_operating_cost"], 300)
        self.assertEqual(totals["net_profitability"], 500)

    def test_id_substitution_for_other_owner_vehicle_is_hidden(self):
        with self.assertRaises(ApiError) as error:
            owners.owner_vehicle_detail(
                str(self.account_id), str(self.other_vehicle_id), "2026-07-27", "2026-07-27"
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_vehicle_detail_is_read_only_and_excludes_private_finance(self):
        result = owners.owner_vehicle_detail(
            str(self.account_id), str(self.vehicle_id), "2026-07-27", "2026-07-27"
        )
        self.assertTrue(result["read_only"])
        self.assertNotIn("driver_profile", result["current_driver"])
        self.assertNotIn("expenses", result)

    def test_inactive_account_is_denied(self):
        self.db.users.update_one({"_id": self.account_id}, {"$set": {"status": "inactive"}})
        with self.assertRaises(ApiError) as error:
            owners.owner_dashboard(str(self.account_id))
        self.assertEqual(error.exception.status_code, 403)

    def test_link_rejects_vehicle_owned_by_another_fleet_owner(self):
        with self.assertRaises(ApiError) as error:
            owners.link_owner_vehicles(
                str(self.owner_id), [str(self.other_vehicle_id)], str(ObjectId())
            )
        self.assertEqual(error.exception.status_code, 409)

    def test_create_and_deactivate_account(self):
        created_account_id = ObjectId()
        self.db.users.insert_one({
            "_id": created_account_id, "role": "fleet_owner", "status": "active",
            "full_name": "New Partner", "email": "partner@example.com", "phone": "+233200000001",
        })
        with patch.object(owners, "create_user", return_value={
            "id": str(created_account_id), "role": "fleet_owner", "status": "active",
            "full_name": "New Partner", "email": "partner@example.com", "phone": "+233200000001",
        }):
            created = owners.create_owner_account(
                {
                    "name": "New Partner Fleet", "contact_name": "New Partner",
                    "email": "partner@example.com", "phone": "+233200000001",
                    "password": "secret12",
                },
                str(ObjectId()),
            )
        self.assertEqual(created["status"], "active")
        updated = owners.update_owner_account(
            created["id"], {"status": "inactive"}, str(ObjectId())
        )
        self.assertEqual(updated["status"], "inactive")
        self.assertEqual(
            self.db.users.find_one({"_id": created_account_id})["status"], "inactive"
        )


class DriverSettingsSecurityTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_driver_settings
        self.admin_id = ObjectId()
        self.driver_id = ObjectId()
        self.owner_account_id = ObjectId()
        self.db.users.insert_many([
            {"_id": self.admin_id, "role": "admin", "status": "active"},
            {
                "_id": self.driver_id, "role": "driver", "status": "active",
                "driver_profile": {"operating_mode": "hybrid", "target_enabled": True, "target_amount": 700},
            },
            {"_id": self.owner_account_id, "role": "fleet_owner", "status": "active"},
        ])
        patches = [
            patch.object(user_service, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(user_service, "create_notification"),
        ]
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])

    def test_admin_change_is_audited_and_notified_once(self):
        result = user_service.update_driver_profile_as(
            str(self.admin_id), "admin", str(self.driver_id),
            {"operating_mode": "operations_only", "target_enabled": False, "target_amount": None},
        )
        self.assertEqual(result["driver_profile"]["operating_mode"], "operations_only")
        self.assertEqual(len(result["driver_profile"]["settings_history"]), 1)
        self.assertEqual(self.db.fleet_owner_audit.count_documents({"action": "driver_settings_changed"}), 1)
        user_service.create_notification.assert_called_once()

    def test_driver_cannot_change_own_mode(self):
        with self.assertRaises(ApiError) as error:
            user_service.update_driver_profile_as(
                str(self.driver_id), "driver", str(self.driver_id),
                {"operating_mode": "target_only"},
            )
        self.assertEqual(error.exception.status_code, 403)

    def test_fleet_owner_cannot_change_driver_mode(self):
        with self.assertRaises(ApiError) as error:
            user_service.update_driver_profile_as(
                str(self.owner_account_id), "fleet_owner", str(self.driver_id),
                {"operating_mode": "target_only"},
            )
        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
