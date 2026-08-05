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

from services import incident_service as service


class IncidentResolutionRegressionTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().incident_resolution
        self.owner_id = ObjectId()
        self.driver_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.incident_id = ObjectId()
        self.db.users.insert_one({"_id": self.driver_id, "role": "driver", "full_name": "Driver One"})
        self.db.vehicles.insert_one(
            {
                "_id": self.vehicle_id,
                "registration_number": "ACC-100",
                "status": "accident",
                "assigned_driver_id": None,
            }
        )
        self.db.incidents.insert_one(
            {
                "_id": self.incident_id,
                "vehicle_id": self.vehicle_id,
                "driver_id": self.driver_id,
                "incident_type": "accident",
                "status": "under_review",
                "record_scope": "fleet",
                "can_vehicle_move": False,
                "vehicle_status_after_incident": "accident",
                "incident_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
                "audit_logs": [],
            }
        )
        self.collection_patch = patch.object(service, "get_collection", side_effect=lambda name: self.db[name])
        self.resolve_patch = patch.object(service, "resolve_action_notifications")
        self.collection_patch.start()
        self.resolve_notifications = self.resolve_patch.start()
        self.addCleanup(self.collection_patch.stop)
        self.addCleanup(self.resolve_patch.stop)

    def update(self, payload: dict):
        return service.update_incident(
            str(self.incident_id),
            payload,
            current_user_id=str(self.owner_id),
            current_role="owner",
        )

    def test_resolving_incident_releases_vehicle_and_resolves_notifications(self):
        response = self.update({"status": "resolved", "vehicle_status_after_incident": "accident"})

        incident = self.db.incidents.find_one({"_id": self.incident_id})
        vehicle = self.db.vehicles.find_one({"_id": self.vehicle_id})
        self.assertEqual(response["status"], "resolved")
        self.assertEqual(incident["vehicle_status_after_incident"], "available")
        self.assertEqual(vehicle["status"], "available")
        self.assertEqual(len(incident["audit_logs"]), 1)
        self.resolve_notifications.assert_called_once_with(
            "incident",
            self.incident_id,
            resolution="completed",
            completed_by=str(self.owner_id),
        )

    def test_another_open_incident_keeps_vehicle_blocked(self):
        self.db.incidents.insert_one(
            {
                "_id": ObjectId(),
                "vehicle_id": self.vehicle_id,
                "incident_type": "accident",
                "status": "under_review",
                "record_scope": "fleet",
                "can_vehicle_move": False,
                "vehicle_status_after_incident": "out_of_service",
            }
        )

        self.update({"status": "closed"})

        vehicle = self.db.vehicles.find_one({"_id": self.vehicle_id})
        self.assertEqual(vehicle["status"], "out_of_service")

    def test_claim_only_update_does_not_rewrite_vehicle_status(self):
        self.update({"claim_status": "under_review"})

        vehicle = self.db.vehicles.find_one({"_id": self.vehicle_id})
        self.assertEqual(vehicle["status"], "accident")
        self.resolve_notifications.assert_not_called()


if __name__ == "__main__":
    unittest.main()
