from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import dispatch_return_service as service
from utils.api_error import ApiError


class DispatchReturnDatetimeTests(unittest.TestCase):
    def _parse_return(self, return_date: str, return_time: str) -> datetime:
        local_value = datetime.fromisoformat(f"{return_date}T{return_time}").replace(tzinfo=timezone.utc)
        parsed, _, _ = service._parse_return_datetime(
            {
                "return_date": return_date,
                "return_time": return_time,
                "actual_return_at": local_value.isoformat(),
                "timezone_offset_minutes": 0,
            }
        )
        return parsed

    def test_same_day_valid_return_is_accepted(self):
        service._validate_return_after_departure(
            actual_departure_at=datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
            actual_return_at=self._parse_return("2026-07-16", "20:02"),
        )

    def test_multi_day_valid_return_is_accepted(self):
        service._validate_return_after_departure(
            actual_departure_at=datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc),
            actual_return_at=self._parse_return("2026-07-16", "08:00"),
        )

    def test_earlier_return_is_rejected_with_safe_values(self):
        with self.assertRaises(ApiError) as raised:
            service._validate_return_after_departure(
                actual_departure_at=datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
                actual_return_at=self._parse_return("2026-07-16", "08:00"),
            )
        self.assertIn("Recorded departure: 16-Jul-2026 09:00 AM UTC", raised.exception.message)
        self.assertIn("Entered return: 16-Jul-2026 08:00 AM UTC", raised.exception.message)

    def test_equal_return_is_rejected(self):
        with self.assertRaises(ApiError):
            service._validate_return_after_departure(
                actual_departure_at=datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
                actual_return_at=self._parse_return("2026-07-16", "09:00"),
            )

    def test_missing_actual_departure_has_clear_error(self):
        with self.assertRaises(ApiError) as raised:
            service._resolve_actual_departure_at({}, {})
        self.assertIn("recorded departure time is unavailable", raised.exception.message.lower())

    def test_scheduled_departure_is_not_used_as_return_validation_fallback(self):
        with self.assertRaises(ApiError):
            service._resolve_actual_departure_at(
                {"scheduled_start_time": datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)},
                {"requested_departure_time": datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc)},
            )

    def test_timezone_offset_is_normalized_to_utc(self):
        parsed, _, _ = service._parse_return_datetime(
            {
                "return_date": "2026-07-16",
                "return_time": "20:02",
                "actual_return_at": "2026-07-16T18:02:00Z",
                "timezone_offset_minutes": -120,
            }
        )
        self.assertEqual(parsed, datetime(2026, 7, 16, 18, 2, tzinfo=timezone.utc))


class DispatchReturnConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.job_id = ObjectId()
        self.movement_id = ObjectId()
        self.user_id = ObjectId()
        self.job = {
            "_id": self.job_id,
            "dispatch_job_id": "DJ-RETURN-TEST",
            "status": "completed",
            "return_status": "awaiting_return",
            "actual_departure_at": datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
            "timeline": [],
        }
        self.movement = {
            "_id": self.movement_id,
            "dispatch_job_id": self.job_id,
            "status": "in_progress",
            "actual_departure_at": datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
            "departure_time": datetime(2026, 7, 16, 9, 0, tzinfo=timezone.utc),
            "opening_odometer": 1000,
            "opening_fuel_level": 6,
            "return_checklist": None,
        }
        self.payload = {
            "return_date": "2026-07-16",
            "return_time": "20:02",
            "actual_return_at": "2026-07-16T20:02:00Z",
            "timezone_offset_minutes": 0,
            "closing_odometer": 1100,
            "closing_fuel_level": 4,
        }

    def _run_confirm(self):
        movement_collection = MagicMock()

        def update_movement(query, update):
            if self.movement["status"] not in query["status"]["$in"]:
                return SimpleNamespace(matched_count=0)
            self.movement.update(update["$set"])
            return SimpleNamespace(matched_count=1)

        movement_collection.update_one.side_effect = update_movement
        job_collection = MagicMock()

        def update_job(_query, update):
            self.job.update(update["$set"])
            return SimpleNamespace(matched_count=1)

        job_collection.update_one.side_effect = update_job

        patches = [
            patch.object(service, "_get_dispatch_job_document", return_value=self.job),
            patch.object(service, "_ensure_linked_vehicle_movement", return_value=self.movement),
            patch.object(service, "vehicle_movements_collection", return_value=movement_collection),
            patch.object(service, "dispatch_jobs_collection", return_value=job_collection),
            patch.object(service, "_build_return_detail", return_value={"ok": True}),
            patch.object(service, "resolve_action_notifications"),
            patch("services.dispatch_financial_service.ensure_dispatch_financial_record"),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            result = service.confirm_dispatch_return(
                str(self.job_id),
                self.payload,
                current_user_id=str(self.user_id),
                current_role="admin",
            )
            with self.assertRaises(ApiError) as repeated:
                service.confirm_dispatch_return(
                    str(self.job_id),
                    self.payload,
                    current_user_id=str(self.user_id),
                    current_role="admin",
                )

        return result, repeated.exception, movement_collection

    def test_repeated_confirmation_does_not_create_competing_timestamp(self):
        result, repeated_error, movement_collection = self._run_confirm()
        self.assertEqual(result["detail"], {"ok": True})
        self.assertEqual(repeated_error.message, "This dispatch return has already been confirmed.")
        self.assertEqual(movement_collection.update_one.call_count, 1)
        self.assertEqual(self.movement["actual_return_at"], datetime(2026, 7, 16, 20, 2, tzinfo=timezone.utc))

    def test_closing_fuel_is_saved_on_movement_and_return_record(self):
        self._run_confirm()
        self.assertEqual(self.movement["closing_fuel_level"], 4)
        self.assertEqual(self.movement["return_checklist"]["closing_fuel_level"], 4)
        self.assertEqual(self.job["return_checklist"]["closing_fuel_level"], 4)

    def test_closing_odometer_is_optional(self):
        self.payload.pop("closing_odometer")
        self._run_confirm()
        self.assertIsNone(self.movement["closing_odometer"])
        self.assertIsNone(self.job["return_checklist"]["closing_odometer"])

    def test_closing_odometer_cannot_be_lower_than_opening(self):
        self.payload["closing_odometer"] = 999
        with patch.object(service, "_get_dispatch_job_document", return_value=self.job), patch.object(
            service, "_ensure_linked_vehicle_movement", return_value=self.movement
        ):
            with self.assertRaises(ApiError) as raised:
                service.confirm_dispatch_return(
                    str(self.job_id),
                    self.payload,
                    current_user_id=str(self.user_id),
                    current_role="admin",
                )
        self.assertIn("greater than or equal to opening_odometer", raised.exception.message)


if __name__ == "__main__":
    unittest.main()
