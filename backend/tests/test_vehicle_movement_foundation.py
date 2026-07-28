from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bson import ObjectId
from pymongo.errors import DuplicateKeyError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import movement_source_service as source_service
from services import dispatch_fuel_service
from services import dispatch_planner_service
from services import dispatch_return_service
from services import vehicle_movement_service as movement_service
from utils.api_error import ApiError
from utils.fuel_levels import normalize_fuel_level_eighths


class FuelLevelNormalizationTests(unittest.TestCase):
    def test_canonical_eighth_inputs(self):
        cases = (
            (0, 0),
            (1, 1),
            ("1/8", 1),
            (8, 8),
            ("F", 8),
            ("E", 0),
            (0.5, 4),
            ("1/2", 4),
            ("25%", 2),
            ("12.5%", 1),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(normalize_fuel_level_eighths(value), (expected, None))

    def test_ambiguous_or_invalid_values_are_rejected(self):
        for value in (0.4, 9, 25, "13%", "9/8", True, "unknown"):
            with self.subTest(value=value):
                normalized, warning = normalize_fuel_level_eighths(value)
                self.assertIsNone(normalized)
                self.assertTrue(warning)


class MovementSourceServiceTests(unittest.TestCase):
    def setUp(self):
        self.source_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.actor_id = ObjectId()
        self.defaults = {
            "vehicle_id": self.vehicle_id,
            "movement_type": "customer_dispatch",
            "status": "approved",
            "created_by": self.actor_id,
        }

    def test_first_source_call_creates_one_movement(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        movement_id = ObjectId()
        collection.insert_one.return_value = SimpleNamespace(inserted_id=movement_id)
        with patch.object(source_service, "vehicle_movements_collection", return_value=collection):
            result = source_service.ensure_movement_for_source(
                source_type="dispatch_job",
                source_record_id=self.source_id,
                source_reference="DJ-1",
                movement_defaults=self.defaults,
                legacy_query={"dispatch_job_id": self.source_id},
            )
        self.assertTrue(result["created"])
        self.assertEqual(result["movement"]["_id"], movement_id)
        self.assertEqual(result["source_key"], f"dispatch_job:{self.source_id}")
        collection.insert_one.assert_called_once()

    def test_repeated_source_call_returns_existing_movement(self):
        existing = {
            "_id": ObjectId(),
            "source_key": f"dispatch_job:{self.source_id}",
            "source_type": "dispatch_job",
        }
        collection = MagicMock()
        collection.find_one.return_value = existing
        with patch.object(source_service, "vehicle_movements_collection", return_value=collection):
            result = source_service.ensure_movement_for_source(
                source_type="dispatch_job",
                source_record_id=self.source_id,
                movement_defaults=self.defaults,
            )
        self.assertFalse(result["created"])
        self.assertIs(result["movement"], existing)
        collection.insert_one.assert_not_called()

    def test_concurrent_duplicate_attempt_returns_winning_movement(self):
        winner = {
            "_id": ObjectId(),
            "source_key": f"dispatch_job:{self.source_id}",
            "source_type": "dispatch_job",
        }
        collection = MagicMock()
        collection.find_one.side_effect = [None, None, winner]
        collection.insert_one.side_effect = DuplicateKeyError("duplicate source")
        with patch.object(source_service, "vehicle_movements_collection", return_value=collection):
            result = source_service.ensure_movement_for_source(
                source_type="dispatch_job",
                source_record_id=self.source_id,
                movement_defaults=self.defaults,
                legacy_query={"dispatch_job_id": self.source_id},
            )
        self.assertFalse(result["created"])
        self.assertEqual(result["movement"]["_id"], winner["_id"])

    def test_legacy_dispatch_movement_is_backfilled_without_replacement(self):
        legacy = {
            "_id": ObjectId(),
            "dispatch_job_id": self.source_id,
            "source_key": None,
        }
        collection = MagicMock()
        collection.find_one.side_effect = [None, legacy]
        with patch.object(source_service, "vehicle_movements_collection", return_value=collection):
            result = source_service.ensure_movement_for_source(
                source_type="dispatch_job",
                source_record_id=self.source_id,
                source_reference="DJ-LEGACY",
                movement_defaults=self.defaults,
                legacy_query={"dispatch_job_id": self.source_id},
            )
        self.assertFalse(result["created"])
        self.assertEqual(result["movement"]["_id"], legacy["_id"])
        self.assertEqual(result["movement"]["source_key"], f"dispatch_job:{self.source_id}")
        collection.insert_one.assert_not_called()


class DispatchMovementIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.actor_id = ObjectId()
        self.job = {
            "_id": ObjectId(),
            "dispatch_job_id": "DJ-CENTRAL",
            "vehicle_id": ObjectId(),
            "driver_id": self.actor_id,
            "dispatch_request_id": ObjectId(),
            "status": "accepted",
        }
        self.movement = {
            "_id": ObjectId(),
            "dispatch_job_id": self.job["_id"],
            "vehicle_id": self.job["vehicle_id"],
            "driver_id": self.actor_id,
            "status": "approved",
        }
        self.central_result = {
            "movement": self.movement,
            "created": False,
            "source_key": f"dispatch_job:{self.job['_id']}",
        }

    def test_opening_fuel_reuses_central_movement(self):
        with patch(
            "services.movement_source_service.ensure_dispatch_movement",
            return_value=self.central_result,
        ) as ensure:
            movement = dispatch_fuel_service._ensure_predeparture_movement(
                self.job,
                current_user_id=str(self.actor_id),
            )
        self.assertIs(movement, self.movement)
        ensure.assert_called_once()

    def test_return_fallback_reuses_central_movement(self):
        with patch(
            "services.movement_source_service.ensure_dispatch_movement",
            return_value=self.central_result,
        ) as ensure:
            movement = dispatch_return_service._ensure_linked_vehicle_movement(
                self.job,
                current_user_id=str(self.actor_id),
            )
        self.assertIs(movement, self.movement)
        ensure.assert_called_once()

    def test_dispatch_start_reuses_and_transitions_central_movement(self):
        movement_collection = MagicMock()
        with patch(
            "services.movement_source_service.ensure_dispatch_movement",
            return_value=self.central_result,
        ) as ensure, patch.object(
            dispatch_planner_service,
            "vehicle_movements_collection",
            return_value=movement_collection,
        ):
            movement_id = dispatch_planner_service._ensure_linked_vehicle_movement(
                self.job,
                current_user_id=str(self.actor_id),
            )
        self.assertEqual(movement_id, self.movement["_id"])
        self.assertEqual(self.movement["status"], "in_progress")
        movement_collection.update_one.assert_called_once()
        ensure.assert_called_once()


class MovementPermissionAndLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.active_driver = ObjectId()
        self.permanent_driver = ObjectId()
        self.movement = {
            "_id": ObjectId(),
            "movement_id": "VM-TEST",
            "vehicle_id": ObjectId(),
            "driver_id": self.active_driver,
            "movement_custodian_id": self.active_driver,
            "permanent_driver_id": self.permanent_driver,
            "movement_type": "other",
            "status": "approved",
            "requested_departure_time": movement_service.now_utc(),
        }

    def test_active_driver_can_mutate_movement(self):
        movement_service._assert_vehicle_movement_mutation_access(
            self.movement,
            current_user_id=str(self.active_driver),
            current_role="driver",
        )

    def test_permanent_driver_cannot_mutate_temporary_custodian_movement(self):
        with self.assertRaises(ApiError) as raised:
            movement_service._assert_vehicle_movement_mutation_access(
                self.movement,
                current_user_id=str(self.permanent_driver),
                current_role="driver",
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_driver_cannot_patch_source_owned_route_fields(self):
        with patch.object(
            movement_service,
            "_get_vehicle_movement_document",
            return_value=dict(self.movement),
        ):
            with self.assertRaises(ApiError) as raised:
                movement_service.update_vehicle_movement(
                    str(self.movement["_id"]),
                    {"origin": "Other yard", "destination": "Other branch"},
                    current_user_id=str(self.active_driver),
                    current_role="driver",
                )
        self.assertEqual(raised.exception.message, "No valid vehicle movement fields provided for update.")

    def test_unsafe_creation_status_is_rejected(self):
        for status in ("in_progress", "returned", "closed", "cancelled"):
            with self.subTest(status=status), self.assertRaises(ApiError):
                movement_service.create_vehicle_movement(
                    {
                        "vehicle_id": str(self.movement["vehicle_id"]),
                        "movement_type": "other",
                        "status": status,
                    },
                    current_user_id=str(ObjectId()),
                    current_role="admin",
                )

    def test_update_no_longer_references_undefined_next_status(self):
        collection = MagicMock()
        document = dict(self.movement)
        with patch.object(
            movement_service,
            "_get_vehicle_movement_document",
            return_value=document,
        ), patch.object(
            movement_service,
            "_validate_relationships",
            return_value=({"_id": document["vehicle_id"]}, None, None),
        ), patch.object(
            movement_service,
            "_assert_vehicle_is_not_blocked",
        ), patch.object(
            movement_service,
            "vehicle_movements_collection",
            return_value=collection,
        ), patch.object(
            movement_service,
            "_batch_enrich_vehicle_movements",
            side_effect=lambda documents: documents,
        ):
            result = movement_service.update_vehicle_movement(
                str(document["_id"]),
                {"notes": "Safe update"},
                current_user_id=str(ObjectId()),
                current_role="admin",
            )
        self.assertEqual(result["notes"], "Safe update")
        collection.update_one.assert_called_once()


if __name__ == "__main__":
    unittest.main()
