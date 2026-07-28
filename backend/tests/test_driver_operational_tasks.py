from __future__ import annotations

import sys
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import operational_task_service as tasks
from routes import driver_portal as driver_routes


class DriverOperationalTaskTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_test
        self.driver_id = ObjectId()
        self.other_driver_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.now = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
        self.db.vehicles.insert_one({
            "_id": self.vehicle_id,
            "registration_number": "FLUX-01",
            "make": "Toyota",
            "model": "Hilux",
        })
        self.patch = patch.object(tasks, "get_collection", side_effect=lambda name: self.db[name])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _client_and_token(self, *, role="driver", identity=None):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="operational-task-test-secret-at-least-32-bytes",
        )
        JWTManager(app)
        app.register_blueprint(driver_routes.driver_portal_bp, url_prefix="/api/driver")
        with app.app_context():
            token = create_access_token(
                identity=str(identity or self.driver_id),
                additional_claims={"role": role},
            )
        return app.test_client(), token

    def insert_active_operations(self):
        pickup_id = self.db.stock_transfers.insert_one({
            "transfer_id": "SP-001",
            "operation_type": "supplier_pickup",
            "supplier": {"supplier_name": "Main Supplier", "pickup_address": "Supplier Yard"},
            "sending_location": "Supplier Yard",
            "receiving_location": "Central Store",
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "scheduled_at": self.now,
            "status": "scheduled",
            "transfer_items": [{"name": "Hidden detail"}],
            "audit_log": [{"event": "Hidden history"}],
        }).inserted_id
        transfer_id = self.db.stock_transfers.insert_one({
            "transfer_id": "ST-001",
            "operation_type": "stock_transfer",
            "sending_location": "Warehouse A",
            "receiving_location": "Warehouse B",
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "scheduled_at": self.now,
            "status": "released",
            "linked_waybill_id": ObjectId(),
        }).inserted_id
        request_id = self.db.vehicle_operation_requests.insert_one({
            "request_id": "OR-001",
            "operation_type": "administrative_errand",
            "title": "Collect permits",
            "origin": "Head Office",
            "destination": "Permit Office",
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "planned_departure_at": self.now,
            "status": "scheduled",
        }).inserted_id
        return pickup_id, transfer_id, request_id

    def test_empty_queue_returns_successful_empty_list(self):
        result = tasks.list_driver_operational_tasks(str(self.driver_id))

        self.assertEqual(result, {"tasks": [], "count": 0})

    def test_empty_queue_endpoint_returns_200_and_empty_tasks(self):
        client, token = self._client_and_token()
        with patch.object(
            driver_routes,
            "list_driver_operational_tasks",
            side_effect=tasks.list_driver_operational_tasks,
        ):
            response = client.get(
                "/api/driver/operational-tasks",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"], {"tasks": [], "count": 0})

    def test_operational_tasks_endpoint_is_driver_only(self):
        client, token = self._client_and_token(role="admin")
        response = client.get(
            "/api/driver/operational-tasks",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 403)

    def test_each_single_source_type_is_mapped(self):
        source_documents = (
            (
                "stock_transfers",
                {
                    "transfer_id": "SP-ONLY",
                    "operation_type": "supplier_pickup",
                    "supplier": {"supplier_name": "Supplier", "pickup_address": "Supplier Yard"},
                    "receiving_location": "Store",
                    "status": "scheduled",
                },
                "supplier_pickup",
            ),
            (
                "stock_transfers",
                {
                    "transfer_id": "ST-ONLY",
                    "operation_type": "stock_transfer",
                    "sending_location": "Store A",
                    "receiving_location": "Store B",
                    "status": "released",
                },
                "stock_transfer",
            ),
            (
                "vehicle_operation_requests",
                {
                    "request_id": "OR-ONLY",
                    "operation_type": "administrative_errand",
                    "title": "Collect papers",
                    "origin": "Office",
                    "destination": "Registry",
                    "status": "scheduled",
                },
                "operational_request",
            ),
        )
        for collection_name, document, expected_type in source_documents:
            with self.subTest(operation_type=expected_type):
                self.db.stock_transfers.delete_many({})
                self.db.vehicle_operation_requests.delete_many({})
                self.db[collection_name].insert_one({
                    **document,
                    "driver_id": self.driver_id,
                    "scheduled_at": self.now,
                    "planned_departure_at": self.now,
                })

                result = tasks.list_driver_operational_tasks(str(self.driver_id))

                self.assertEqual(result["count"], 1)
                self.assertEqual(result["tasks"][0]["operation_type"], expected_type)

    def test_malformed_optional_fields_and_legacy_ids_do_not_crash(self):
        self.db.stock_transfers.insert_one({
            "transfer_id": None,
            "operation_type": "supplier_pickup",
            "supplier": "legacy supplier text",
            "receiving_location": {"unexpected": ObjectId()},
            "vehicle_id": str(self.vehicle_id),
            "driver_id": str(self.driver_id),
            "scheduled_at": {"legacy": ObjectId()},
            "updated_at": b"legacy",
            "linked_waybill_id": {"id": ObjectId()},
            "status": "scheduled",
        })
        self.db.vehicle_operation_requests.insert_one({
            "request_id": None,
            "operation_type": {"invalid": True},
            "title": ["invalid"],
            "origin": ObjectId(),
            "destination": None,
            "vehicle_id": "not-an-object-id",
            "driver_id": str(self.driver_id),
            "planned_departure_at": None,
            "status": "scheduled",
        })

        result = tasks.list_driver_operational_tasks(str(self.driver_id))

        self.assertEqual(result["count"], 2)
        self.assertEqual(
            {item["operation_type"] for item in result["tasks"]},
            {"supplier_pickup", "operational_request"},
        )
        json.dumps(result)

    def test_all_operation_types_are_unique_summary_tasks(self):
        pickup_id, transfer_id, request_id = self.insert_active_operations()
        self.db.operation_assignments.insert_many([
            {"source_key": f"supplier_pickup:{pickup_id}", "driver_id": self.driver_id},
            {"source_key": f"supplier_pickup:{pickup_id}", "driver_id": self.driver_id},
        ])

        result = tasks.list_driver_operational_tasks(str(self.driver_id))

        self.assertEqual(result["count"], 3)
        self.assertEqual(
            {item["operation_type"] for item in result["tasks"]},
            {"supplier_pickup", "stock_transfer", "operational_request"},
        )
        self.assertEqual(
            {item["id"] for item in result["tasks"]},
            {str(pickup_id), str(transfer_id), str(request_id)},
        )
        pickup = next(item for item in result["tasks"] if item["operation_type"] == "supplier_pickup")
        self.assertEqual(pickup["current_action"]["label"], "Accept Pickup")
        self.assertEqual(pickup["vehicle"]["registration_number"], "FLUX-01")
        self.assertNotIn("transfer_items", pickup)
        self.assertNotIn("audit_log", pickup)

    def test_wrong_driver_and_terminal_operations_are_excluded(self):
        self.insert_active_operations()
        self.db.stock_transfers.insert_many([
            {"driver_id": self.driver_id, "status": "completed", "operation_type": "supplier_pickup"},
            {"driver_id": self.driver_id, "status": "cancelled", "operation_type": "stock_transfer"},
        ])
        self.db.vehicle_operation_requests.insert_one({
            "driver_id": self.driver_id,
            "status": "completed",
            "operation_type": "administrative_errand",
        })

        self.assertEqual(tasks.list_driver_operational_tasks(str(self.other_driver_id))["count"], 0)
        self.assertEqual(tasks.list_driver_operational_tasks(str(self.driver_id))["count"], 3)

    def test_reassignment_moves_the_same_source_task(self):
        pickup_id, _, _ = self.insert_active_operations()

        self.assertIn(
            str(pickup_id),
            {item["id"] for item in tasks.list_driver_operational_tasks(str(self.driver_id))["tasks"]},
        )
        self.db.stock_transfers.update_one(
            {"_id": pickup_id},
            {"$set": {"driver_id": self.other_driver_id}},
        )

        self.assertNotIn(
            str(pickup_id),
            {item["id"] for item in tasks.list_driver_operational_tasks(str(self.driver_id))["tasks"]},
        )
        self.assertIn(
            str(pickup_id),
            {item["id"] for item in tasks.list_driver_operational_tasks(str(self.other_driver_id))["tasks"]},
        )

    def test_acceptance_keeps_task_and_advances_current_action(self):
        pickup_id, _, _ = self.insert_active_operations()
        self.db.stock_transfers.update_one(
            {"_id": pickup_id},
            {"$set": {"acknowledged_at": self.now}},
        )

        pickup = next(
            item
            for item in tasks.list_driver_operational_tasks(str(self.driver_id))["tasks"]
            if item["id"] == str(pickup_id)
        )
        self.assertEqual(pickup["current_action"]["label"], "Arrive at Supplier")

    def test_operations_dashboard_counts_all_sources_without_target_data(self):
        self.insert_active_operations()
        self.db.dispatch_jobs.insert_one({
            "dispatch_job_id": "DJ-001",
            "driver_id": self.driver_id,
            "status": "assigned",
            "driver_response_status": "pending",
            "pickup": "Depot",
            "destination": "Customer",
            "scheduled_start_time": self.now,
            "approved_charge": 900,
            "internal_notes": "Must not be returned",
        })
        self.db.stock_transfers.insert_many([
            {
                "transfer_id": "ST-UPCOMING",
                "operation_type": "stock_transfer",
                "driver_id": self.driver_id,
                "status": "scheduled",
                "acknowledged_at": self.now,
                "scheduled_at": datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "transfer_id": "ST-DONE",
                "operation_type": "stock_transfer",
                "driver_id": self.driver_id,
                "status": "completed",
                "completed_at": self.now,
                "scheduled_at": self.now,
            },
        ])

        summary = tasks.get_driver_operations_dashboard_summary(
            str(self.driver_id),
            now_value=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(summary["counts"], {
            "current_task": 1,
            "today": 5,
            "upcoming": 1,
            "pending_acceptance": 3,
            "completed_today": 1,
        })
        self.assertEqual(summary["current_task"]["operation_type"], "stock_transfer")
        self.assertEqual(len(summary["upcoming_tasks"]), 1)
        self.assertNotIn("approved_charge", summary["current_task"])
        self.assertNotIn("internal_notes", summary["current_task"])
        self.assertNotIn("linked_waybill_id", summary["current_task"])
        self.assertNotIn("transfer_items", summary["current_task"])

    def test_operations_dashboard_limits_upcoming_and_updates_after_completion(self):
        for index in range(4):
            self.db.vehicle_operation_requests.insert_one({
                "request_id": f"OR-UP-{index}",
                "operation_type": "administrative_errand",
                "title": f"Upcoming {index}",
                "driver_id": self.driver_id,
                "status": "scheduled",
                "acknowledged_at": self.now,
                "opening_check_completed_at": self.now,
                "planned_departure_at": datetime(2026, 7, 24 + index, 8, 0, tzinfo=timezone.utc),
            })
        now_value = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

        before = tasks.get_driver_operations_dashboard_summary(
            str(self.driver_id), now_value=now_value,
        )
        self.assertEqual(before["counts"]["upcoming"], 4)
        self.assertEqual(len(before["upcoming_tasks"]), 3)
        self.assertEqual(
            [item["reference"] for item in before["upcoming_tasks"]],
            ["OR-UP-0", "OR-UP-1", "OR-UP-2"],
        )

        first_id = ObjectId(before["upcoming_tasks"][0]["id"])
        self.db.vehicle_operation_requests.update_one(
            {"_id": first_id},
            {"$set": {"status": "completed", "verified_at": now_value}},
        )
        after = tasks.get_driver_operations_dashboard_summary(
            str(self.driver_id), now_value=now_value,
        )
        self.assertEqual(after["counts"]["upcoming"], 3)
        self.assertEqual(after["counts"]["completed_today"], 1)
        self.assertEqual(after["current_task"]["reference"], "OR-UP-1")

    def test_operations_dashboard_does_not_read_target_or_booking_collections(self):
        touched = []

        def tracked_collection(name):
            touched.append(name)
            return self.db[name]

        with patch.object(tasks, "get_collection", side_effect=tracked_collection):
            tasks.get_driver_operations_dashboard_summary(
                str(self.driver_id),
                now_value=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(
            set(touched),
            {"stock_transfers", "vehicle_operation_requests", "dispatch_jobs"},
        )
        self.assertNotIn("assignments", touched)
        self.assertNotIn("collections", touched)
        self.assertNotIn("bookings", touched)


if __name__ == "__main__":
    unittest.main()
