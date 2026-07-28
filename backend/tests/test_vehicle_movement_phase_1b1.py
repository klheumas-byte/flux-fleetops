from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.vehicle_movement import serialize_vehicle_movement
from services import assignment_service
from services import dispatch_financial_service
from services import dispatch_planner_service
from services import maintenance_service
from services import movement_custody_service as custody_service
from services import movement_source_service
from services import vehicle_availability_service
from utils.api_error import ApiError


class MemoryCollection:
    def __init__(self, documents=None):
        self.documents = {
            document["_id"]: deepcopy(document)
            for document in (documents or [])
        }

    def find_one(self, query, projection=None, sort=None):
        del projection, sort
        for document in self.documents.values():
            if "_id" in query and document.get("_id") != query["_id"]:
                continue
            if "custody_events.event_key" in query:
                forbidden = query["custody_events.event_key"].get("$ne")
                if any(
                    event.get("event_key") == forbidden
                    for event in document.get("custody_events") or []
                ):
                    continue
            return deepcopy(document)
        return None

    def update_one(self, query, update):
        document = None
        for candidate in self.documents.values():
            if "_id" in query and candidate.get("_id") != query["_id"]:
                continue
            if "custody_events.event_key" in query:
                forbidden = query["custody_events.event_key"].get("$ne")
                if any(
                    event.get("event_key") == forbidden
                    for event in candidate.get("custody_events") or []
                ):
                    continue
            document = candidate
            break
        if not document:
            return SimpleNamespace(matched_count=0, modified_count=0)
        for key, value in update.get("$set", {}).items():
            document[key] = deepcopy(value)
        for key in update.get("$unset", {}):
            document.pop(key, None)
        for key, value in update.get("$inc", {}).items():
            document[key] = int(document.get(key) or 0) + value
        for key, value in update.get("$push", {}).items():
            document.setdefault(key, []).append(deepcopy(value))
        return SimpleNamespace(matched_count=1, modified_count=1)


class CustodyEventTests(unittest.TestCase):
    def setUp(self):
        self.driver_a = ObjectId()
        self.driver_b = ObjectId()
        self.vehicle_id = ObjectId()
        self.movement_id = ObjectId()
        self.movement = {
            "_id": self.movement_id,
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_a,
            "movement_custodian_id": self.driver_a,
            "source_type": "assignment_handover",
            "source_id": "assignment:1",
            "status": "approved",
            "custody_events": [],
            "custody_version": 0,
        }
        self.movements = MemoryCollection([self.movement])
        self.vehicles = MemoryCollection([{"_id": self.vehicle_id}])
        self.users = MemoryCollection(
            [
                {"_id": self.driver_a, "status": "active"},
                {"_id": self.driver_b, "status": "active"},
            ]
        )
        self.patches = (
            patch.object(custody_service, "vehicle_movements_collection", return_value=self.movements),
            patch.object(custody_service, "vehicles_collection", return_value=self.vehicles),
            patch.object(custody_service, "users_collection", return_value=self.users),
        )

    def test_release_and_intended_driver_acceptance_are_recorded(self):
        with self.patches[0], self.patches[1], self.patches[2]:
            custody_service.transfer_movement_custody(
                self.movement_id,
                {
                    "to_user_id": str(self.driver_b),
                    "fuel_level": "1/2",
                    "odometer_available": False,
                    "odometer_unavailable_reason": "Dashboard unavailable",
                },
                current_user_id=str(self.driver_a),
                current_role="driver",
                source_event_key="handover:release",
            )
            accepted = custody_service.accept_movement_custody(
                self.movement_id,
                {"fuel_level": 4},
                current_user_id=str(self.driver_b),
                current_role="driver",
                source_event_key="handover:accept",
            )
        stored = self.movements.documents[self.movement_id]
        self.assertEqual([event["event_type"] for event in stored["custody_events"]], [
            "transferred_between_drivers",
            "accepted_by_driver",
        ])
        self.assertEqual(stored["movement_custodian_id"], self.driver_b)
        self.assertEqual(accepted["event"]["fuel_level"], 4)
        self.assertFalse(stored["custody_events"][0]["odometer_available"])

    def test_wrong_driver_cannot_accept_and_duplicate_accept_is_idempotent(self):
        with self.patches[0], self.patches[1], self.patches[2]:
            custody_service.transfer_movement_custody(
                self.movement_id,
                {"to_user_id": str(self.driver_b)},
                current_user_id=str(self.driver_a),
                current_role="driver",
                source_event_key="handover:release",
            )
            with self.assertRaises(ApiError) as raised:
                custody_service.accept_movement_custody(
                    self.movement_id,
                    {},
                    current_user_id=str(ObjectId()),
                    current_role="driver",
                    source_event_key="handover:accept",
                )
            first = custody_service.accept_movement_custody(
                self.movement_id,
                {},
                current_user_id=str(self.driver_b),
                current_role="driver",
                source_event_key="handover:accept",
            )
            repeated = custody_service.accept_movement_custody(
                self.movement_id,
                {},
                current_user_id=str(self.driver_b),
                current_role="driver",
                source_event_key="handover:accept",
            )
        self.assertEqual(raised.exception.status_code, 403)
        self.assertTrue(first["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(
            len(self.movements.documents[self.movement_id]["custody_events"]),
            2,
        )

    def test_admin_correction_requires_reason_and_embedded_evidence_is_rejected(self):
        with self.patches[0], self.patches[1], self.patches[2]:
            with self.assertRaises(ApiError):
                custody_service.transfer_movement_custody(
                    self.movement_id,
                    {"to_location": "Company yard"},
                    current_user_id=str(ObjectId()),
                    current_role="admin",
                )
            with self.assertRaises(ApiError):
                custody_service.append_custody_event(
                    self.movement_id,
                    event_type="other",
                    initiated_by=ObjectId(),
                    current_role="admin",
                    payload={"is_correction": True},
                )
            with self.assertRaises(ApiError):
                custody_service.append_custody_event(
                    self.movement_id,
                    event_type="other",
                    initiated_by=ObjectId(),
                    current_role="admin",
                    payload={
                        "is_correction": True,
                        "audit_reason": "Correct participant",
                        "evidence": "data:image/png;base64,AAAA",
                    },
                )

    def test_list_shape_excludes_evidence_and_legacy_movement_serializes(self):
        legacy = {
            "_id": ObjectId(),
            "vehicle_id": ObjectId(),
            "movement_id": "VM-LEGACY",
            "movement_type": "other",
            "status": "closed",
        }
        serialized = serialize_vehicle_movement(legacy)
        self.assertIsNone(serialized["custody_events"])
        self.assertEqual(serialized["custody_version"], 0)


class AssignmentHandoverTests(unittest.TestCase):
    def setUp(self):
        self.assignment = {
            "_id": ObjectId(),
            "vehicle_id": ObjectId(),
            "driver_id": ObjectId(),
            "assigned_by": ObjectId(),
            "handover_sequence": 1,
            "status": "pending_handover",
            "handover_status": "awaiting_driver_acceptance",
            "weekly_target": 1000,
        }

    def test_first_and_repeated_handover_use_one_source_key(self):
        movement = {
            "_id": ObjectId(),
            "vehicle_id": self.assignment["vehicle_id"],
            "status": "approved",
        }
        assignments = MagicMock()
        vehicles = MagicMock()
        vehicles.find_one.return_value = {
            "_id": self.assignment["vehicle_id"],
            "assigned_driver_id": None,
            "current_custodian_id": None,
        }
        central_result = {
            "movement": movement,
            "created": True,
            "source_key": f"assignment_handover:{self.assignment['_id']}:1:initial",
        }
        with patch.object(assignment_service, "assignments_collection", return_value=assignments), patch.object(
            assignment_service, "vehicles_collection", return_value=vehicles
        ), patch(
            "services.movement_source_service.ensure_movement_for_source",
            return_value=central_result,
        ) as ensure, patch(
            "services.movement_custody_service.transfer_movement_custody"
        ) as transfer:
            first = assignment_service._ensure_assignment_handover_movement(
                self.assignment,
                current_user_id=self.assignment["assigned_by"],
                handover_kind="initial",
            )
            second = assignment_service._ensure_assignment_handover_movement(
                self.assignment,
                current_user_id=self.assignment["assigned_by"],
                handover_kind="initial",
            )
        self.assertEqual(first["_id"], second["_id"])
        self.assertEqual(
            ensure.call_args.kwargs["source_record_id"],
            f"{self.assignment['_id']}:1:initial",
        )
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(transfer.call_count, 2)

    def test_wrong_driver_cannot_accept_assignment(self):
        with patch.object(
            assignment_service,
            "get_assignment_document_by_id",
            return_value=self.assignment,
        ):
            with self.assertRaises(ApiError) as raised:
                assignment_service.accept_assignment_handover(
                    str(self.assignment["_id"]),
                    {},
                    current_user_id=str(ObjectId()),
                    current_role="driver",
                )
        self.assertEqual(raised.exception.status_code, 403)

    def test_legacy_active_assignment_keeps_nonblocking_label(self):
        serialized = assignment_service.serialize_assignment(
            {
                "_id": self.assignment["_id"],
                "vehicle_id": self.assignment["vehicle_id"],
                "driver_id": self.assignment["driver_id"],
                "status": "active",
            }
        )
        self.assertEqual(serialized["handover_status"], "handover_not_recorded")

    def test_activation_preserves_targets_and_does_not_duplicate_wallet_entry(self):
        driver = {
            "_id": self.assignment["driver_id"],
            "driver_profile": {},
        }
        vehicle = {"_id": self.assignment["vehicle_id"]}
        assignments = MagicMock()
        users = MagicMock()
        users.find_one.return_value = driver
        vehicles = MagicMock()
        vehicles.find_one.return_value = vehicle
        wallet = MagicMock()
        wallet.find_one.return_value = {"_id": ObjectId()}
        with patch.object(assignment_service, "assignments_collection", return_value=assignments), patch.object(
            assignment_service, "users_collection", return_value=users
        ), patch.object(
            assignment_service, "vehicles_collection", return_value=vehicles
        ), patch.object(
            assignment_service, "get_collection", return_value=wallet
        ), patch.object(
            assignment_service, "create_wallet_entry"
        ) as create_wallet:
            result = assignment_service._activate_assignment_after_handover(
                dict(self.assignment),
                accepted_by=self.assignment["driver_id"],
            )
        self.assertEqual(result["weekly_target"], 1000)
        create_wallet.assert_not_called()


class MaintenanceTransportTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            "_id": ObjectId(),
            "vehicle_id": ObjectId(),
            "driver_id": ObjectId(),
            "title": "Workshop repair",
            "status": "approved",
            "transport_required": True,
            "transport_mode": "tow",
            "workshop_location": "North Workshop",
        }

    def test_in_house_maintenance_creates_no_transport_movement(self):
        in_house = {**self.job, "transport_required": False}
        with self.assertRaises(ApiError):
            maintenance_service._ensure_maintenance_transport_movement(
                in_house,
                direction="outbound",
                current_user_id=ObjectId(),
            )

    def test_outbound_uses_unique_directional_source_without_repair_data(self):
        movement = {"_id": ObjectId(), "vehicle_id": self.job["vehicle_id"]}
        vehicles = MagicMock()
        vehicles.find_one.return_value = {
            "_id": self.job["vehicle_id"],
            "assigned_driver_id": self.job["driver_id"],
        }
        maintenance_jobs = MagicMock()
        central = {
            "movement": movement,
            "created": True,
            "source_key": f"maintenance_job:{self.job['_id']}:outbound",
        }
        with patch.object(maintenance_service, "vehicles_collection", return_value=vehicles), patch.object(
            maintenance_service, "maintenance_jobs_collection", return_value=maintenance_jobs
        ), patch(
            "services.movement_source_service.ensure_movement_for_source",
            return_value=central,
        ) as ensure:
            result = maintenance_service._ensure_maintenance_transport_movement(
                self.job,
                direction="outbound",
                current_user_id=ObjectId(),
            )
        defaults = ensure.call_args.kwargs["movement_defaults"]
        self.assertEqual(result["_id"], movement["_id"])
        self.assertEqual(
            ensure.call_args.kwargs["source_record_id"],
            f"{self.job['_id']}:outbound",
        )
        self.assertNotIn("parts_changed", defaults)
        self.assertNotIn("actual_cost", defaults)

    def test_linked_movement_for_another_vehicle_is_rejected(self):
        self.job["linked_outbound_movement_id"] = ObjectId()
        vehicles = MagicMock()
        vehicles.find_one.return_value = {"_id": self.job["vehicle_id"]}
        movements = MagicMock()
        movements.find_one.return_value = {
            "_id": self.job["linked_outbound_movement_id"],
            "vehicle_id": ObjectId(),
        }
        with patch.object(maintenance_service, "vehicles_collection", return_value=vehicles), patch(
            "services.maintenance_service.get_collection",
            return_value=movements,
        ):
            with self.assertRaises(ApiError) as raised:
                maintenance_service._ensure_maintenance_transport_movement(
                    self.job,
                    direction="outbound",
                    current_user_id=ObjectId(),
                )
        self.assertEqual(raised.exception.status_code, 409)

    def test_completion_ensures_return_without_moving_repair_details(self):
        document = {
            **self.job,
            "status": "in_progress",
            "priority": "medium",
            "preventive_schedule_id": None,
            "notes": "Repair notes stay here",
        }
        movement = {"_id": ObjectId(), "vehicle_id": document["vehicle_id"]}
        jobs = MagicMock()
        with patch.object(
            maintenance_service,
            "_get_maintenance_document",
            return_value=document,
        ), patch.object(
            maintenance_service,
            "_get_vehicle_document",
            return_value={"_id": document["vehicle_id"]},
        ), patch.object(
            maintenance_service,
            "_ensure_maintenance_transport_movement",
            return_value=movement,
        ) as ensure, patch.object(
            maintenance_service,
            "_restore_vehicle_status_after_completion",
        ), patch.object(
            maintenance_service,
            "_append_vehicle_maintenance_history",
        ), patch.object(
            maintenance_service,
            "_process_maintenance_reminders",
        ), patch.object(
            maintenance_service,
            "_enrich_maintenance_job",
            side_effect=lambda item: item,
        ), patch.object(
            maintenance_service,
            "maintenance_jobs_collection",
            return_value=jobs,
        ):
            result = maintenance_service.update_maintenance_status(
                str(document["_id"]),
                "completed",
                {
                    "work_performed": "Replaced bearing",
                    "parts_changed": ["bearing"],
                },
                current_user_id=str(ObjectId()),
                current_role="admin",
            )
        ensure.assert_called_once()
        self.assertEqual(ensure.call_args.kwargs["direction"], "return")
        self.assertEqual(result["linked_return_movement_id"], movement["_id"])
        self.assertEqual(result["work_performed"], "Replaced bearing")


class SourceRegistryTests(unittest.TestCase):
    def test_phase_1b_sources_reuse_generic_source_key_builder(self):
        assignment_id = f"{ObjectId()}:2:return"
        maintenance_id = f"{ObjectId()}:outbound"
        self.assertEqual(
            movement_source_service.build_source_key("assignment_handover", assignment_id),
            f"assignment_handover:{assignment_id}",
        )
        self.assertEqual(
            movement_source_service.build_source_key("maintenance_job", maintenance_id),
            f"maintenance_job:{maintenance_id}",
        )


class DispatchFinalizationTests(unittest.TestCase):
    def test_assignment_scheduling_ensures_authoritative_movement(self):
        actor = ObjectId()
        job = {
            "_id": ObjectId(),
            "dispatch_job_id": "DJ-SCHEDULED",
            "dispatch_request_id": ObjectId(),
            "vehicle_id": ObjectId(),
            "driver_id": ObjectId(),
            "vehicle_reservation_id": ObjectId(),
            "driver_reservation_id": ObjectId(),
            "status": "reserved",
            "timeline": [],
        }
        movement = {"_id": ObjectId(), "vehicle_id": job["vehicle_id"]}
        collection = MagicMock()
        request = {"_id": job["dispatch_request_id"]}
        with patch.object(
            dispatch_planner_service,
            "_get_dispatch_job_document",
            return_value=job,
        ), patch.object(
            dispatch_planner_service,
            "dispatch_jobs_collection",
            return_value=collection,
        ), patch.object(
            dispatch_planner_service,
            "_get_dispatch_request_document",
            return_value=request,
        ), patch.object(
            dispatch_planner_service,
            "_set_request_planning_state",
        ), patch.object(
            dispatch_planner_service,
            "_create_job_notification_once",
        ), patch.object(
            dispatch_planner_service,
            "_batch_enrich_dispatch_jobs",
            side_effect=lambda documents: documents,
        ), patch(
            "services.movement_source_service.ensure_dispatch_movement",
            return_value={
                "movement": movement,
                "created": True,
                "source_key": f"dispatch_job:{job['_id']}",
            },
        ) as ensure:
            result = dispatch_planner_service.assign_dispatch_job(
                str(job["_id"]),
                current_user_id=str(actor),
                current_role="admin",
            )
        self.assertEqual(result["linked_vehicle_movement_id"], movement["_id"])
        ensure.assert_called_once()
        self.assertEqual(
            collection.update_one.call_args.args[1]["$set"]["linked_vehicle_movement_id"],
            movement["_id"],
        )

    def test_financial_closure_does_not_ensure_or_create_movement(self):
        actor = ObjectId()
        job = {"_id": ObjectId()}
        record = {"_id": ObjectId(), "verified_at": object(), "is_financially_closed": False}
        financials = MagicMock()
        with patch.object(
            dispatch_financial_service, "_get_dispatch_job", return_value=job
        ), patch.object(
            dispatch_financial_service,
            "_get_financial_record_for_job",
            return_value=record,
        ), patch.object(
            dispatch_financial_service,
            "dispatch_financials_collection",
            return_value=financials,
        ), patch.object(
            dispatch_financial_service,
            "get_dispatch_financial_detail",
            return_value={"closed": True},
        ), patch(
            "services.movement_source_service.ensure_dispatch_movement"
        ) as ensure:
            result = dispatch_financial_service.close_dispatch_financial(
                str(job["_id"]),
                {},
                current_user_id=str(actor),
                current_role="admin",
            )
        self.assertEqual(result, {"closed": True})
        ensure.assert_not_called()


class AvailabilityCustodyTests(unittest.TestCase):
    def _collections(self, *, vehicle_id: ObjectId, movement: dict | None, maintenance: dict | None = None):
        def collection(name):
            mock = MagicMock()
            if name == "vehicles":
                mock.find_one.return_value = {
                    "_id": vehicle_id,
                    "status": "assigned",
                    "assigned_driver_id": None,
                }
            elif name == "vehicle_movements":
                mock.find_one.return_value = movement
            elif name == "maintenance_jobs":
                mock.find_one.return_value = maintenance
            else:
                mock.find_one.return_value = None
            return mock
        return collection

    def test_pending_handover_is_unavailable_and_explicitly_labeled(self):
        vehicle_id = ObjectId()
        movement = {
            "_id": ObjectId(),
            "vehicle_id": vehicle_id,
            "movement_type": "assignment_handover",
            "custody_state": "pending_acceptance",
        }
        with patch.object(
            vehicle_availability_service,
            "get_collection",
            side_effect=self._collections(vehicle_id=vehicle_id, movement=movement),
        ):
            result = vehicle_availability_service.resolve_vehicle_availability(vehicle_id)
        self.assertFalse(result["is_available"])
        self.assertEqual(result["operational_state"], "pending_handover")

    def test_completed_repair_with_open_return_movement_stays_unavailable(self):
        vehicle_id = ObjectId()
        movement = {
            "_id": ObjectId(),
            "vehicle_id": vehicle_id,
            "movement_type": "maintenance_transport",
            "custody_state": "workshop_custody",
            "current_custody_location": "North Workshop",
        }
        with patch.object(
            vehicle_availability_service,
            "get_collection",
            side_effect=self._collections(vehicle_id=vehicle_id, movement=movement),
        ):
            result = vehicle_availability_service.resolve_vehicle_availability(vehicle_id)
        self.assertFalse(result["is_available"])
        self.assertEqual(result["operational_state"], "external_custody")


if __name__ == "__main__":
    unittest.main()
