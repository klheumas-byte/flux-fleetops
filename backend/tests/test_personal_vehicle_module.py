from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import auth_service, expense_service, incident_service, personal_vehicle_service
from utils.api_error import ApiError


class PersonalVehicleModuleTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).personal_vehicles
        self.owner_a, self.owner_b, self.admin = ObjectId(), ObjectId(), ObjectId()
        self.db.users.insert_many([
            {"_id": self.owner_a, "role": "personal_vehicle_owner", "status": "active", "full_name": "Owner A", "email": "a@example.com"},
            {"_id": self.owner_b, "role": "personal_vehicle_owner", "status": "active", "full_name": "Owner B", "email": "b@example.com"},
            {"_id": self.admin, "role": "admin", "status": "active", "full_name": "Admin"},
        ])

    def _patch(self, module=personal_vehicle_service):
        return patch.object(module, "get_collection", side_effect=lambda name: self.db[name])

    def _vehicle(self, owner=None, registration="PV-001", vehicle_type="saloon_car", mileage=0):
        with self._patch(), patch.object(personal_vehicle_service, "create_notification"):
            return personal_vehicle_service.create_vehicle(str(owner or self.owner_a), {
                "registration_number": registration, "vehicle_type": vehicle_type,
                "make": "Flux", "model": "Test", "year": 2025,
                "fuel_type": "petrol", "current_mileage": mileage,
            })

    def test_all_supported_vehicle_types_and_commercial_default_are_separate(self):
        for index, vehicle_type in enumerate(sorted(personal_vehicle_service.VEHICLE_TYPES)):
            result = self._vehicle(registration=f"PV-{index:03d}", vehicle_type=vehicle_type)
            self.assertEqual(result["usage_type"], "personal")
            self.assertEqual(result["vehicle_type"], vehicle_type)
        self.db.vehicles.insert_one({"registration_number": "LEGACY-1", "usage_type": "commercial"})
        with self._patch():
            rows = personal_vehicle_service.list_vehicles(str(self.owner_a))
        self.assertEqual(len(rows), len(personal_vehicle_service.VEHICLE_TYPES))
        self.assertNotIn("LEGACY-1", {row["registration_number"] for row in rows})

    def test_cross_owner_vehicle_and_record_access_return_not_found(self):
        vehicle = self._vehicle()
        with self._patch(), patch.object(personal_vehicle_service, "create_notification"):
            record = personal_vehicle_service.create_record(str(self.owner_a), "expenses", {
                "vehicle_id": vehicle["id"], "record_date": date.today().isoformat(),
                "category": "parking", "title": "Parking", "amount": 10,
            })
            with self.assertRaises(ApiError) as vehicle_error:
                personal_vehicle_service.get_vehicle(str(self.owner_b), vehicle["id"])
            with self.assertRaises(ApiError) as record_error:
                personal_vehicle_service.update_record(str(self.owner_b), "expenses", record["id"], {"notes": "guess"})
        self.assertEqual(vehicle_error.exception.status_code, 404)
        self.assertEqual(record_error.exception.status_code, 404)

    def test_mileage_regression_requires_reason_and_is_audited(self):
        vehicle = self._vehicle(mileage=500)
        with self._patch():
            with self.assertRaises(ApiError) as error:
                personal_vehicle_service.update_vehicle(str(self.owner_a), vehicle["id"], {"current_mileage": 450})
            corrected = personal_vehicle_service.update_vehicle(str(self.owner_a), vehicle["id"], {"current_mileage": 450, "correction_reason": "Odometer entry typo"})
        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(corrected["current_mileage"], 450)
        audit = self.db.personal_vehicle_audit.find_one({"action": "mileage_updated"})
        self.assertEqual(audit["reason"], "Odometer entry typo")

    def test_service_reminder_dedup_status_health_and_dashboard_service_summary(self):
        vehicle = self._vehicle(mileage=1000)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        payload = {
            "vehicle_id": vehicle["id"], "record_date": yesterday, "mileage": 1100,
            "service_type": "Oil service", "work_performed": "Changed oil and filter",
            "labour_cost": 20, "parts_cost": 30, "next_service_date": yesterday,
        }
        with self._patch(), patch.object(personal_vehicle_service, "create_notification"):
            service = personal_vehicle_service.create_record(str(self.owner_a), "services", payload)
            personal_vehicle_service._upsert_service_reminder(self.owner_a, self.db.vehicles.find_one({"_id": ObjectId(vehicle["id"])}), self.db.maintenance_jobs.find_one({"_id": ObjectId(service["id"])}))
            reminders = personal_vehicle_service.list_records(str(self.owner_a), "reminders")
            dashboard = personal_vehicle_service.dashboard(str(self.owner_a))
        self.assertEqual(self.db.personal_vehicle_reminders.count_documents({}), 1)
        self.assertEqual(reminders["records"][0]["status"], "overdue")
        self.assertLess(dashboard["vehicles"][0]["health"]["score"], 100)
        self.assertEqual(dashboard["vehicles"][0]["last_service"]["id"], service["id"])
        self.assertEqual(dashboard["vehicles"][0]["next_service"]["status"], "overdue")

    def test_fuel_calculations_and_expense_summary_avoid_double_counting(self):
        vehicle = self._vehicle()
        today = date.today().isoformat()
        with self._patch(), patch.object(personal_vehicle_service, "create_notification"):
            personal_vehicle_service.create_record(str(self.owner_a), "fuel", {"vehicle_id": vehicle["id"], "record_date": today, "mileage": 100, "quantity": 10, "total_cost": 50})
            second = personal_vehicle_service.create_record(str(self.owner_a), "fuel", {"vehicle_id": vehicle["id"], "record_date": today, "mileage": 300, "quantity": 20, "total_cost": 80})
            personal_vehicle_service.create_record(str(self.owner_a), "services", {"vehicle_id": vehicle["id"], "record_date": today, "mileage": 300, "service_type": "Check", "work_performed": "Inspection", "labour_cost": 40})
            personal_vehicle_service.create_record(str(self.owner_a), "expenses", {"vehicle_id": vehicle["id"], "record_date": today, "category": "parking", "title": "Parking", "amount": 15})
            self.db.expenses.insert_one({"record_scope": "personal", "personal_owner_user_id": self.owner_a, "vehicle_id": ObjectId(vehicle["id"]), "record_date": today, "expense_category": "service", "amount": 40, "linked_source_id": ObjectId(), "linked_source_type": "services"})
            summary = personal_vehicle_service.expense_summary(str(self.owner_a))
        self.assertEqual(second["distance_since_previous"], 200)
        self.assertEqual(second["consumption_per_100_km"], 10)
        self.assertEqual(second["cost_per_km"], 0.4)
        self.assertEqual(summary["total"], 185)
        self.assertEqual(summary["by_category"]["service"], 40)

    def test_document_renewal_preserves_previous_and_timeline_has_unique_events(self):
        vehicle = self._vehicle()
        today = date.today().isoformat()
        with self._patch(), patch.object(personal_vehicle_service, "create_notification"):
            original = personal_vehicle_service.create_record(str(self.owner_a), "documents", {"vehicle_id": vehicle["id"], "record_date": today, "document_type": "insurance", "issue_date": today, "expiry_date": (date.today() + timedelta(days=30)).isoformat()})
            renewed = personal_vehicle_service.renew_document(str(self.owner_a), original["id"], {"issue_date": today, "expiry_date": (date.today() + timedelta(days=365)).isoformat()})
            timeline = personal_vehicle_service.vehicle_timeline(str(self.owner_a), vehicle_id=vehicle["id"], page_size=100)
        self.assertEqual(self.db.vehicle_compliance_records.count_documents({}), 2)
        self.assertEqual(self.db.vehicle_compliance_records.find_one({"_id": ObjectId(original["id"])} )["status"], "renewed")
        self.assertEqual(renewed["renewal_of_id"], original["id"])
        keys = [event["key"] for event in timeline["events"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_inactive_owner_and_legacy_admin_mutations_cannot_reach_private_records(self):
        vehicle = self._vehicle()
        expense_id = self.db.expenses.insert_one({"record_scope": "personal", "personal_owner_user_id": self.owner_a, "vehicle_id": ObjectId(vehicle["id"]), "status": "recorded", "amount": 10}).inserted_id
        incident_id = self.db.incidents.insert_one({"record_scope": "personal", "personal_owner_user_id": self.owner_a, "vehicle_id": ObjectId(vehicle["id"])}).inserted_id
        with self._patch(expense_service):
            with self.assertRaises(ApiError) as expense_error:
                expense_service.approve_expense(str(expense_id), str(self.admin))
        with self._patch(incident_service):
            with self.assertRaises(ApiError) as incident_error:
                incident_service.get_incident_by_id(str(incident_id), current_user_id=str(self.admin), current_role="admin")
        self.db.users.update_one({"_id": self.owner_a}, {"$set": {"status": "inactive"}})
        with self._patch():
            with self.assertRaises(ApiError) as inactive_error:
                personal_vehicle_service.list_vehicles(str(self.owner_a))
        self.assertEqual(expense_error.exception.status_code, 404)
        self.assertEqual(incident_error.exception.status_code, 404)
        self.assertEqual(inactive_error.exception.status_code, 403)

    def test_role_is_available_to_owner_and_admin_account_creation(self):
        self.assertIn("personal_vehicle_owner", auth_service.ALLOWED_ROLES)
        with self._patch(auth_service), patch.object(auth_service, "generate_password_hash", return_value="hash"):
            account = auth_service.create_user_as("admin", {"full_name": "Personal User", "email": "p@example.com", "phone": "0200000000", "password": "strong-password", "role": "personal_vehicle_owner"})
        self.assertEqual(account["role"], "personal_vehicle_owner")
        self.assertEqual(account["status"], "active")


if __name__ == "__main__":
    unittest.main()
