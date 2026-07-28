from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask_jwt_extended import create_access_token


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app
from services import driver_private_finance_service as finance
from utils.api_error import ApiError


class DriverPrivateFinanceTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().private_finance
        self.driver_id = ObjectId()
        self.other_driver_id = ObjectId()
        for driver_id in (self.driver_id, self.other_driver_id):
            self.db.users.insert_one({
                "_id": driver_id, "role": "driver", "status": "active",
                "driver_profile": {
                    "operating_mode": "hybrid", "target_enabled": True,
                    "private_finance_enabled": True,
                },
            })
        self.db.driver_private_finance.create_index(
            [("driver_id", 1), ("entry_date", 1), ("platform", 1)],
            unique=True, partialFilterExpression={"status": "active"},
        )
        self.collection_patch = patch.object(finance, "get_collection", side_effect=lambda name: self.db[name])
        self.collection_patch.start()
        self.addCleanup(self.collection_patch.stop)

    def payload(self, **updates):
        value = {
            "date": "2026-07-28", "platform": "Bolt", "cash_sales": 100,
            "digital_sales": 50, "other_sales": 10, "platform_fees": 20,
            "fuel_paid_personally": 15, "parking": 5, "tolls": 2,
            "washing": 3, "repairs_paid_personally": 4, "other_expenses": 1,
            "notes": "Private note",
        }
        value.update(updates)
        return value

    def test_eligible_driver_calculations_and_summary(self):
        entry = finance.create_private_entry(str(self.driver_id), self.payload())
        self.assertEqual(entry["gross_sales"], 160)
        self.assertEqual(entry["total_platform_deductions"], 20)
        self.assertEqual(entry["total_personal_expenses"], 30)
        self.assertEqual(entry["driver_net_earnings"], 110)
        summary = finance.private_finance_summary(
            str(self.driver_id), "2026-07-01", "2026-07-31", period="weekly"
        )
        self.assertEqual(summary["entry_count"], 1)
        self.assertEqual(summary["driver_net_earnings"], 110)
        self.assertEqual(summary["platform_breakdown"][0]["platform"], "bolt")

    def test_edit_delete_and_private_history(self):
        entry = finance.create_private_entry(str(self.driver_id), self.payload())
        updated = finance.update_private_entry(str(self.driver_id), entry["id"], {"cash_sales": 125})
        self.assertEqual(updated["gross_sales"], 185)
        history = finance.private_entry_history(str(self.driver_id), entry["id"])
        self.assertEqual([row["action"] for row in history], ["updated", "created"])
        finance.delete_private_entry(str(self.driver_id), entry["id"])
        self.assertEqual(finance.list_private_entries(
            str(self.driver_id), "2026-07-01", "2026-07-31"
        )["pagination"]["total"], 0)

    def test_duplicate_and_concurrent_submission_are_protected(self):
        def submit():
            try:
                finance.create_private_entry(str(self.driver_id), self.payload())
                return "created"
            except ApiError as error:
                return error.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _item: submit(), range(2)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count(409), 1)

    def test_driver_cannot_substitute_another_drivers_entry_id(self):
        entry = finance.create_private_entry(str(self.other_driver_id), self.payload())
        with self.assertRaises(ApiError) as error:
            finance.update_private_entry(str(self.driver_id), entry["id"], {"cash_sales": 999})
        self.assertEqual(error.exception.status_code, 404)

    def test_disabled_or_ineligible_driver_is_denied(self):
        self.db.users.update_one(
            {"_id": self.driver_id}, {"$set": {"driver_profile.private_finance_enabled": False}}
        )
        with self.assertRaises(ApiError) as error:
            finance.create_private_entry(str(self.driver_id), self.payload())
        self.assertEqual(error.exception.status_code, 403)

    def test_csv_contains_only_requesting_driver(self):
        finance.create_private_entry(str(self.driver_id), self.payload())
        finance.create_private_entry(str(self.other_driver_id), self.payload(cash_sales=999))
        content = finance.export_private_entries_csv(str(self.driver_id), "2026-07-01", "2026-07-31")
        self.assertIn("110.0", content)
        self.assertNotIn("999", content)


class DriverPrivateFinanceRoutePrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app("development")
        cls.app.config.update(TESTING=True, JWT_SECRET_KEY="private-finance-test-secret")
        cls.client = cls.app.test_client()

    def token(self, role):
        with self.app.app_context():
            return create_access_token(identity=str(ObjectId()), additional_claims={"role": role, "operating_mode": "hybrid"})

    def test_privileged_business_roles_have_no_bypass(self):
        for role in ("admin", "owner", "fleet_owner"):
            with self.subTest(role=role):
                response = self.client.get(
                    "/api/driver/private-finance",
                    headers={"Authorization": f"Bearer {self.token(role)}"},
                )
                self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
