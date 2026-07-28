from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import dispatch_planner_service as planner


class OperationsPlannerTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_test
        self.owner_id = ObjectId()
        self.driver_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.now = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
        self.patches = [
            patch.object(planner, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(
                planner,
                "resolve_vehicle_availability",
                return_value={"is_available": True, "blocking_reasons": []},
            ),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def test_shared_request_queue_contains_all_approved_operation_types(self):
        self.db.dispatch_requests.insert_one({
            "request_id": "DR-1",
            "status": "approved",
            "planning_status": "unplanned",
            "customer_name": "Customer",
            "pickup_location": "Depot",
            "destination": "Customer site",
            "created_at": self.now,
        })
        self.db.stock_transfers.insert_many([
            {
                "transfer_id": "SP-1",
                "operation_type": "supplier_pickup",
                "status": "approved",
                "supplier": {"supplier_name": "Supplier", "pickup_address": "Supplier yard"},
                "receiving_location": "Warehouse",
                "created_at": self.now,
            },
            {
                "transfer_id": "ST-1",
                "operation_type": "stock_transfer",
                "status": "approved",
                "sending_location": "Warehouse A",
                "receiving_location": "Warehouse B",
                "created_at": self.now,
            },
        ])
        self.db.vehicle_operation_requests.insert_one({
            "request_id": "OR-1",
            "operation_type": "administrative_errand",
            "status": "approved",
            "title": "Collect permit",
            "origin": "Office",
            "destination": "Registry",
            "created_at": self.now,
        })

        result = planner.list_planner_requests(
            current_role="admin",
            operation_type="all",
        )

        self.assertEqual(result["pagination"]["total"], 4)
        self.assertEqual(
            {item["planner_operation_type"] for item in result["requests"]},
            {"dispatch", "supplier_pickup", "stock_transfer", "operational_request"},
        )

    def test_non_dispatch_planning_reuses_source_workflows(self):
        cases = (
            ("supplier_pickup", "services.stock_transfer_service.schedule_stock_transfer"),
            ("stock_transfer", "services.stock_transfer_service.schedule_stock_transfer"),
            ("operational_request", "services.vehicle_operation_request_service.schedule_operational_request"),
        )
        for operation_type, target in cases:
            with self.subTest(operation_type=operation_type), patch(target, return_value={"id": "record", "status": "scheduled"}) as schedule:
                result = planner.plan_operation(
                    operation_type,
                    str(ObjectId()),
                    {
                        "vehicle_id": str(self.vehicle_id),
                        "driver_id": str(self.driver_id),
                        "scheduled_start_time": self.now.isoformat(),
                        "expected_return_time": (self.now + timedelta(hours=2)).isoformat(),
                    },
                    current_user_id=str(self.owner_id),
                    current_role="admin",
                )

                self.assertEqual(result["operation_type"], operation_type)
                self.assertEqual(result["record"]["status"], "scheduled")
                called_payload = schedule.call_args.args[1]
                if operation_type == "operational_request":
                    self.assertEqual(called_payload["planned_departure_at"], self.now.isoformat())
                else:
                    self.assertEqual(called_payload["scheduled_at"], self.now.isoformat())

    def test_dispatch_planning_still_uses_existing_draft_and_assignment(self):
        with (
            patch.object(planner, "save_dispatch_job_draft", return_value={"id": "job-1", "status": "draft"}) as save,
            patch.object(planner, "assign_dispatch_job", return_value={"id": "job-1", "status": "assigned"}) as assign,
        ):
            result = planner.plan_operation(
                "dispatch",
                str(ObjectId()),
                {"pickup": "Depot"},
                current_user_id=str(self.owner_id),
                current_role="admin",
            )

        save.assert_called_once()
        assign.assert_called_once_with(
            "job-1",
            current_user_id=str(self.owner_id),
            current_role="admin",
        )
        self.assertEqual(result["record"]["status"], "assigned")

    def test_conflicts_are_shared_across_operation_windows(self):
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "status": "available"})
        self.db.users.insert_one({
            "_id": self.driver_id,
            "role": "driver",
            "status": "active",
            "driver_profile": {"approval_status": "approved"},
        })
        self.db.resource_reservations.insert_many([
            {
                "reservation_type": "vehicle",
                "resource_id": self.vehicle_id,
                "status": "reserved",
                "start_time": self.now,
                "end_time": self.now + timedelta(hours=3),
            },
            {
                "reservation_type": "driver",
                "resource_id": self.driver_id,
                "status": "reserved",
                "start_time": self.now,
                "end_time": self.now + timedelta(hours=3),
            },
        ])

        result = planner.detect_dispatch_conflicts(
            vehicle_id=str(self.vehicle_id),
            driver_id=str(self.driver_id),
            scheduled_start_time=self.now + timedelta(hours=1),
            expected_return_time=self.now + timedelta(hours=2),
        )

        self.assertTrue(result["has_conflicts"])
        self.assertTrue(result["vehicle_conflicts"])
        self.assertTrue(result["driver_conflicts"])

    def test_reassignment_and_cancellation_delegate_without_parallel_records(self):
        source_id = str(ObjectId())
        with patch(
            "services.stock_transfer_service.schedule_stock_transfer",
            return_value={"id": source_id, "status": "scheduled"},
        ) as reassign:
            reassigned = planner.reassign_planned_operation(
                "stock_transfer",
                source_id,
                {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id)},
                current_user_id=str(self.owner_id),
                current_role="admin",
            )
        with patch(
            "services.stock_transfer_service.cancel_stock_transfer",
            return_value={"id": source_id, "status": "cancelled"},
        ) as cancel:
            cancelled = planner.cancel_planned_operation(
                "stock_transfer",
                source_id,
                {"reason": "Plan withdrawn"},
                current_user_id=str(self.owner_id),
                current_role="admin",
            )

        reassign.assert_called_once()
        cancel.assert_called_once()
        self.assertEqual(reassigned["record"]["id"], source_id)
        self.assertEqual(cancelled["record"]["status"], "cancelled")
        self.assertEqual(self.db.dispatch_jobs.count_documents({}), 0)

    def test_dispatch_plan_cancellation_preserves_approved_source_request(self):
        request_id = self.db.dispatch_requests.insert_one({
            "request_id": "DR-CANCEL",
            "status": "approved",
            "planning_status": "assigned",
        }).inserted_id
        vehicle_reservation_id = self.db.resource_reservations.insert_one({
            "reservation_type": "vehicle",
            "resource_id": self.vehicle_id,
            "status": "reserved",
        }).inserted_id
        driver_reservation_id = self.db.resource_reservations.insert_one({
            "reservation_type": "driver",
            "resource_id": self.driver_id,
            "status": "reserved",
        }).inserted_id
        job_id = self.db.dispatch_jobs.insert_one({
            "dispatch_job_id": "DJ-CANCEL",
            "dispatch_request_id": request_id,
            "status": "assigned",
            "vehicle_reservation_id": vehicle_reservation_id,
            "driver_reservation_id": driver_reservation_id,
            "timeline": [],
        }).inserted_id

        with (
            patch.object(planner, "_batch_enrich_dispatch_jobs", side_effect=lambda documents: documents),
            patch.object(planner, "resolve_action_notifications"),
        ):
            result = planner.cancel_dispatch_job(
                str(job_id),
                {"reason": "Customer rescheduled"},
                current_user_id=str(self.owner_id),
                current_role="admin",
            )

        self.assertEqual(result["status"], "cancelled")
        request = self.db.dispatch_requests.find_one({"_id": request_id})
        self.assertEqual(request["status"], "approved")
        self.assertEqual(request["planning_status"], "cancelled")
        self.assertIsNone(request["active_dispatch_job_id"])
        self.assertEqual(
            self.db.resource_reservations.count_documents({"status": "released"}),
            2,
        )


if __name__ == "__main__":
    unittest.main()
