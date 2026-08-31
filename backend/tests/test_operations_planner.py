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

    def test_shared_request_queue_serializes_mixed_operation_dates_as_iso(self):
        self.db.stock_transfers.insert_one({
            "transfer_id": "SP-DATE",
            "operation_type": "supplier_pickup",
            "status": "approved",
            "scheduled_at": self.now,
            "created_at": self.now,
        })
        self.db.vehicle_operation_requests.insert_one({
            "request_id": "OR-DATE",
            "status": "approved",
            "planned_departure_at": self.now,
            "expected_return_at": self.now + timedelta(hours=2),
        })

        result = planner.list_planner_requests(current_role="admin", operation_type="all")
        by_reference = {item["request_id"]: item for item in result["requests"]}

        stored_now = self.now.replace(tzinfo=None)
        self.assertEqual(by_reference["SP-DATE"]["scheduled_start_time"], stored_now.isoformat())
        self.assertEqual(by_reference["SP-DATE"]["created_at"], stored_now.isoformat())
        self.assertEqual(by_reference["SP-DATE"]["date_warnings"], [])
        self.assertEqual(by_reference["OR-DATE"]["scheduled_start_time"], stored_now.isoformat())
        self.assertEqual(
            by_reference["OR-DATE"]["expected_return_time"],
            (stored_now + timedelta(hours=2)).isoformat(),
        )

    def test_malformed_optional_schedule_is_null_with_record_warning(self):
        self.db.stock_transfers.insert_one({
            "transfer_id": "SP-BAD-DATE",
            "operation_type": "supplier_pickup",
            "status": "approved",
            "scheduled_at": "not-a-date",
            "created_at": None,
            "updated_at": "",
        })

        result = planner.list_planner_requests(current_role="admin", operation_type="all")
        record = next(item for item in result["requests"] if item["request_id"] == "SP-BAD-DATE")

        self.assertIsNone(record["scheduled_start_time"])
        self.assertIsNone(record["created_at"])
        self.assertIsNone(record["updated_at"])
        self.assertEqual(
            record["date_warnings"],
            ["scheduled_at is unavailable because the stored value is invalid."],
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

    def test_dispatch_schedule_validation_accepts_same_day_and_overnight_windows(self):
        same_day = planner.validate_dispatch_schedule({
            "scheduled_start_time": "2026-08-31T09:00:00+00:00",
            "expected_return_time": "2026-08-31T11:30:00+00:00",
        })
        overnight = planner.validate_dispatch_schedule({
            "scheduled_start_time": "2026-08-31T22:00:00+00:00",
            "expected_return_time": "2026-09-01T01:00:00+00:00",
        })

        self.assertLess(same_day["scheduled_start_time"], same_day["expected_return_time"])
        self.assertLess(overnight["scheduled_start_time"], overnight["expected_return_time"])

    def test_dispatch_schedule_validation_blocks_reverse_missing_and_malformed_windows(self):
        invalid_cases = (
            {
                "scheduled_start_time": "2026-08-31T12:00:00+00:00",
                "expected_return_time": "2026-08-31T11:00:00+00:00",
            },
            {"scheduled_start_time": None, "expected_return_time": "2026-08-31T11:00:00+00:00"},
            {"scheduled_start_time": "malformed", "expected_return_time": "also-malformed"},
            {"scheduled_start_time": "2026-08-31T09:00:00+00:00", "expected_return_time": None},
        )

        for schedule in invalid_cases:
            with self.subTest(schedule=schedule), self.assertRaisesRegex(
                planner.ApiError,
                "Schedule needs correction",
            ):
                planner.validate_dispatch_schedule(schedule)

    def test_existing_prestart_job_correction_reuses_reassignment_and_assignment_flow(self):
        job_id = str(ObjectId())
        payload = {
            "scheduled_start_time": "2026-08-31T22:00:00+00:00",
            "expected_return_time": "2026-09-01T01:00:00+00:00",
        }
        with (
            patch.object(planner, "_get_dispatch_job_document", return_value={"status": "accepted", "dispatch_request_id": ObjectId()}),
            patch.object(planner, "_get_dispatch_request_document", return_value={"status": "approved"}),
            patch.object(planner, "_normalize_planning_payload", return_value={
                **payload,
                "vehicle_id": self.vehicle_id,
                "driver_id": self.driver_id,
            }),
            patch.object(planner, "_validate_planning_payload"),
            patch.object(planner, "reassign_dispatch_job", return_value={"id": job_id, "status": "draft"}) as reassign,
            patch.object(planner, "assign_dispatch_job", return_value={"id": job_id, "status": "assigned"}) as assign,
        ):
            result = planner.correct_dispatch_job_schedule(
                job_id,
                payload,
                current_user_id=str(self.owner_id),
                current_role="admin",
            )

        self.assertEqual(result["id"], job_id)
        self.assertEqual(result["status"], "assigned")
        reassign.assert_called_once()
        assign.assert_called_once_with(job_id, current_user_id=str(self.owner_id), current_role="admin")

    def test_owner_save_on_accepted_job_returns_to_existing_replanning_flow(self):
        request_id = ObjectId()
        job_id = ObjectId()
        payload = {"job_id": str(job_id), "pickup": "Depot", "destination": "Customer"}
        with (
            patch.object(planner, "_get_dispatch_request_document", return_value={"_id": request_id, "status": "approved"}),
            patch.object(planner, "_normalize_planning_payload", return_value={"scheduled_start_time": self.now}),
            patch.object(planner, "_validate_planning_payload"),
            patch.object(planner, "_get_dispatch_job_document", return_value={"_id": job_id, "status": "accepted"}),
            patch.object(planner, "reassign_dispatch_job", return_value={"id": str(job_id), "status": "draft"}) as reassign,
        ):
            result = planner.save_dispatch_job_draft(
                str(request_id),
                payload,
                current_user_id=str(self.owner_id),
                current_role="admin",
            )

        self.assertEqual(result["status"], "draft")
        reassign.assert_called_once_with(
            str(job_id),
            payload,
            current_user_id=str(self.owner_id),
            current_role="admin",
        )

    def test_replanning_excludes_the_existing_linked_movement_from_conflicts(self):
        movement_id = ObjectId()
        request_id = ObjectId()
        job = {
            "_id": ObjectId(),
            "dispatch_job_id": "DJ-REPLAN",
            "dispatch_request_id": request_id,
            "status": "draft",
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "linked_vehicle_movement_id": movement_id,
            "scheduled_start_time": self.now,
            "expected_return_time": self.now + timedelta(hours=2),
            "timeline": [],
        }
        request = {"_id": request_id, "status": "approved"}
        with (
            patch.object(planner, "_get_dispatch_job_document", return_value=job),
            patch.object(planner, "detect_dispatch_conflicts", return_value={"has_conflicts": False}) as conflicts,
            patch.object(planner, "_release_reservations"),
            patch.object(planner, "_create_reservation", side_effect=[ObjectId(), ObjectId()]),
            patch.object(planner, "_get_dispatch_request_document", return_value=request),
            patch.object(planner, "_set_request_planning_state"),
            patch.object(planner, "_batch_enrich_dispatch_jobs", side_effect=lambda documents: documents),
            patch("services.movement_source_service.ensure_dispatch_movement", return_value={"movement": {"_id": movement_id}}) as ensure,
        ):
            planner.reserve_dispatch_resources(
                str(job["_id"]),
                current_user_id=str(self.owner_id),
                current_role="admin",
            )

        self.assertEqual(conflicts.call_args.kwargs["exclude_movement_id"], str(movement_id))
        ensure.assert_called_once()

    def test_driver_start_validates_canonical_window_and_starts_movement_only_once(self):
        request_id = self.db.dispatch_requests.insert_one({
            "request_id": "DR-START",
            "status": "approved",
            "planning_status": "accepted",
        }).inserted_id
        movement_id = ObjectId()
        job_id = self.db.dispatch_jobs.insert_one({
            "dispatch_job_id": "DJ-START",
            "dispatch_request_id": request_id,
            "status": "accepted",
            "driver_workflow_status": "accepted",
            "driver_id": self.driver_id,
            "vehicle_id": self.vehicle_id,
            "linked_vehicle_movement_id": movement_id,
            "scheduled_start_time": self.now - timedelta(hours=1),
            "expected_return_time": self.now + timedelta(hours=2),
            "timeline": [],
        }).inserted_id

        with (
            patch.object(planner, "now_utc", return_value=self.now),
            patch.object(planner, "_batch_enrich_dispatch_jobs", side_effect=lambda documents: documents),
            patch.object(planner, "_consume_reservations"),
            patch.object(planner, "_ensure_linked_vehicle_movement", return_value=movement_id),
            patch.object(planner, "_record_dispatch_start_custody"),
            patch("services.dispatch_fuel_service.assert_dispatch_opening_confirmed", return_value={"_id": movement_id}),
            patch("services.vehicle_movement_service.start_vehicle_movement", return_value={"id": str(movement_id)}) as start,
        ):
            result = planner.update_driver_dispatch_job_workflow(
                str(job_id),
                {"action": "start"},
                current_user_id=str(self.driver_id),
            )
            with self.assertRaisesRegex(planner.ApiError, "Only accepted dispatches"):
                planner.update_driver_dispatch_job_workflow(
                    str(job_id),
                    {"action": "start"},
                    current_user_id=str(self.driver_id),
                )

        self.assertEqual(result["status"], "in_progress")
        start.assert_called_once()
        self.assertEqual(start.call_args.args[1]["departure_time"], self.now)

    def test_driver_start_blocks_expired_return_before_movement_mutation(self):
        job_id = self.db.dispatch_jobs.insert_one({
            "dispatch_job_id": "DJ-EXPIRED",
            "dispatch_request_id": ObjectId(),
            "status": "accepted",
            "driver_workflow_status": "accepted",
            "driver_id": self.driver_id,
            "scheduled_start_time": self.now - timedelta(hours=2),
            "expected_return_time": self.now - timedelta(minutes=1),
            "timeline": [],
        }).inserted_id

        with (
            patch.object(planner, "now_utc", return_value=self.now),
            patch("services.dispatch_fuel_service.assert_dispatch_opening_confirmed") as opening,
            patch("services.vehicle_movement_service.start_vehicle_movement") as start,
            self.assertRaisesRegex(planner.ApiError, "expected return must be after actual departure"),
        ):
            planner.update_driver_dispatch_job_workflow(
                str(job_id),
                {"action": "start"},
                current_user_id=str(self.driver_id),
            )

        opening.assert_not_called()
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
