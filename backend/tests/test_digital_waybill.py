from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import waybill_service as service
from services import movement_source_service
from utils.api_error import ApiError


class RealCollectionBehaviorProxy:
    """Mirror PyMongo's explicit rejection of Collection truth-value checks."""

    def __init__(self, collection):
        self.collection = collection

    def __bool__(self):
        raise NotImplementedError("Collection objects do not implement truth value testing")

    def __getattr__(self, name):
        return getattr(self.collection, name)


class DigitalWaybillTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().waybill_test
        self.collection = self.db.waybills
        self.admin_id = ObjectId()
        self.driver_id = ObjectId()
        self.other_driver_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.source_id = ObjectId()
        self.movement_id = ObjectId()
        self.db.users.insert_many([
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Assigned Driver"},
            {"_id": self.other_driver_id, "role": "driver", "status": "active", "full_name": "Other Driver"},
        ])
        self.patches = [
            patch.object(service, "waybills_collection", return_value=self.collection),
            patch.object(service, "get_collection", side_effect=lambda name: self.db[name]),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def defaults(self):
        return {
            "source_type": "stock_transfer",
            "source_document": {
                "_id": self.source_id,
                "transfer_id": "ST-1",
                "sending_location": "Warehouse A",
                "receiving_location": "Warehouse B",
                "recipient": {
                    "full_name": "Receiving Clerk",
                    "role": "Stores",
                    "primary_phone": "+233 20 123 4567",
                    "delivery_instructions": "Call at the gate.",
                },
                "vehicle_id": self.vehicle_id,
                "driver_id": self.driver_id,
                "transfer_items": [
                    {"item_id": "SKU-1", "name": "Widget", "quantity": 5, "unit": "box"}
                ],
            },
            "movement_document": {
                "_id": self.movement_id,
                "source_key": f"stock_transfer:{self.source_id}",
                "vehicle_id": self.vehicle_id,
                "driver_id": self.driver_id,
                "origin": "Warehouse A",
                "destination": "Warehouse B",
            },
            "current_user_id": self.admin_id,
            "collection": self.collection,
        }

    def create_waybill(self):
        return service.ensure_waybill_for_source(**self.defaults())["waybill"]

    def test_one_waybill_per_source_and_retry_is_idempotent(self):
        with Flask(__name__).app_context():
            service.ensure_waybill_indexes()
        first = service.ensure_waybill_for_source(**self.defaults())
        second = service.ensure_waybill_for_source(**self.defaults())

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["waybill"]["_id"], second["waybill"]["_id"])
        self.assertEqual(self.collection.count_documents({}), 1)
        self.assertEqual(first["waybill"]["movement_id"], self.movement_id)
        self.assertEqual(first["waybill"]["items"][0]["expected_quantity"], 5)
        printed = service.get_waybill(
            first["waybill"]["_id"], current_user_id=str(self.admin_id), current_role="admin"
        )
        self.assertEqual(printed["recipient"]["full_name"], "Receiving Clerk")
        self.assertEqual(printed["recipient"]["delivery_instructions"], "Call at the gate.")

    def test_explicit_collection_does_not_use_truth_value_testing(self):
        collection = RealCollectionBehaviorProxy(self.collection)
        defaults = {**self.defaults(), "collection": collection}
        created = service.ensure_waybill_for_source(**defaults)["waybill"]
        service.transition_waybill(
            created["_id"], "approved", {},
            current_user_id=str(self.admin_id), current_role="admin",
            collection=collection,
        )
        self.assertEqual(self.collection.find_one({"_id": created["_id"]})["status"], "approved")

    def test_item_validation_rejects_duplicates_and_invalid_quantities(self):
        duplicate = [
            {"item_id": "SKU-1", "name": "One", "expected_quantity": 1},
            {"item_id": "sku-1", "name": "Duplicate", "expected_quantity": 2},
        ]
        with self.assertRaises(ApiError):
            service.normalize_waybill_items(duplicate)
        with self.assertRaises(ApiError):
            service.normalize_waybill_items(
                [{"item_id": "SKU-2", "name": "Invalid", "expected_quantity": -1}]
            )

    def test_driver_confirmation_is_authenticated_scoped_and_immutable(self):
        document = self.create_waybill()
        self.collection.update_one({"_id": document["_id"]}, {"$set": {"status": "approved"}})

        with self.assertRaises(ApiError) as raised:
            service.transition_waybill(
                document["_id"], "driver_confirmed", {},
                current_user_id=str(self.other_driver_id), current_role="driver",
            )
        self.assertEqual(raised.exception.status_code, 403)

        confirmed = service.transition_waybill(
            document["_id"], "driver_confirmed",
            {"gps": {"latitude": -1.2921, "longitude": 36.8219}, "device": {"platform": "mobile"}},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        confirmation = confirmed["confirmations"][0]
        self.assertEqual(confirmation["confirmed_by"], str(self.driver_id))
        self.assertEqual(confirmation["confirmed_by_name"], "Assigned Driver")
        self.assertTrue(confirmation["immutable"])
        self.assertTrue(confirmation["confirmed_at"])
        self.assertEqual(len(confirmed["custody_events"]), 1)
        self.assertEqual(confirmed["custody_events"][0]["to"], str(self.driver_id))
        self.assertEqual(confirmed["custody_events"][0]["to_name"], "Assigned Driver")
        self.assertEqual(confirmed["audit_log"][-1]["event"], "status_driver_confirmed")
        self.assertEqual(confirmed["audit_log"][-1]["actor_id"], str(self.driver_id))

        repeated = service.transition_waybill(
            document["_id"], "driver_confirmed", {},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(len(repeated["confirmations"]), 1)
        self.assertEqual(len(repeated["custody_events"]), 1)
        self.assertEqual(
            len([entry for entry in repeated["audit_log"] if entry["event"] == "status_driver_confirmed"]),
            1,
        )

    def test_driver_can_only_list_assigned_waybills(self):
        assigned = self.create_waybill()
        other = dict(self.defaults())
        other["source_document"] = {**other["source_document"], "_id": ObjectId(), "transfer_id": "ST-2", "driver_id": self.other_driver_id}
        other["movement_document"] = {**other["movement_document"], "_id": ObjectId(), "source_key": f"stock_transfer:{other['source_document']['_id']}", "driver_id": self.other_driver_id}
        service.ensure_waybill_for_source(**other)

        result = service.list_waybills(
            current_user_id=str(self.driver_id), current_role="driver"
        )
        self.assertEqual([item["id"] for item in result["waybills"]], [str(assigned["_id"])])

    def test_lifecycle_calculates_variance_and_requires_review(self):
        document = self.create_waybill()
        waybill_id = document["_id"]
        service.transition_waybill(waybill_id, "approved", {}, current_user_id=str(self.admin_id), current_role="admin")
        service.transition_waybill(waybill_id, "driver_confirmed", {}, current_user_id=str(self.driver_id), current_role="driver")
        service.transition_waybill(waybill_id, "loaded", {"quantities": [{"item_id": "SKU-1", "quantity": 5}]}, current_user_id=str(self.admin_id), current_role="admin")
        service.transition_waybill(waybill_id, "in_transit", {}, current_user_id=str(self.driver_id), current_role="driver")
        delivered = service.transition_waybill(waybill_id, "delivered", {"receiver": "Receiving Clerk", "quantities": [{"item_id": "SKU-1", "quantity": 4}]}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertTrue(delivered["has_variance"])
        self.assertEqual(delivered["items"][0]["variance"], -1)
        service.transition_waybill(waybill_id, "verified", {}, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError) as raised:
            service.transition_waybill(waybill_id, "completed", {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 409)
        service.review_waybill_variance(waybill_id, {"resolution": "Accepted shortage"}, current_user_id=str(self.admin_id), current_role="admin")
        completed = service.transition_waybill(waybill_id, "completed", {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(completed["status"], "completed")

    def test_lifecycle_rejects_skipped_steps(self):
        document = self.create_waybill()
        with self.assertRaises(ApiError) as raised:
            service.transition_waybill(document["_id"], "loaded", {"quantities": []}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(self.collection.find_one({"_id": document["_id"]})["status"], "draft")

    def test_stock_transfer_waybill_workflow_is_source_owned(self):
        document = self.create_waybill()
        with self.assertRaises(ApiError) as raised:
            service.transition_waybill(
                document["_id"], "approved", {},
                current_user_id=str(self.admin_id), current_role="admin",
                enforce_source_owner=True,
            )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.collection.find_one({"_id": document["_id"]})["status"], "draft")

    def test_optional_signature_is_immutable(self):
        document = self.create_waybill()
        first = service.save_waybill_signature(
            document["_id"], "sender", {"signature": "data:image/png;base64,AAA", "signed_by_name": "Sender"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        self.assertTrue(first["signatures"]["sender"]["immutable"])
        with self.assertRaises(ApiError) as raised:
            service.save_waybill_signature(
                document["_id"], "sender", {"signature": "replacement", "signed_by_name": "Other"},
                current_user_id=str(self.admin_id), current_role="admin",
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_supplier_pickup_adapter_is_registered_for_future_reuse(self):
        self.assertEqual(
            service.WAYBILL_SOURCE_DEFINITIONS["supplier_pickup"]["collection"],
            "supplier_pickups",
        )

    def test_dispatch_movement_creates_and_links_one_waybill(self):
        job = {
            "_id": ObjectId(),
            "dispatch_job_id": "DJ-WAYBILL",
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "pickup": "Customer A",
            "destination": "Customer B",
            "status": "assigned",
        }
        self.db.dispatch_jobs.insert_one(dict(job))
        with patch.object(
            movement_source_service,
            "vehicle_movements_collection",
            return_value=self.db.vehicle_movements,
        ), patch.object(
            movement_source_service,
            "dispatch_jobs_collection",
            return_value=self.db.dispatch_jobs,
        ), patch.object(
            movement_source_service,
            "get_collection",
            side_effect=lambda name: self.db[name],
        ):
            first = movement_source_service.ensure_dispatch_movement(
                job, current_user_id=self.admin_id
            )
            second = movement_source_service.ensure_dispatch_movement(
                job, current_user_id=self.admin_id
            )

        self.assertEqual(first["waybill"]["_id"], second["waybill"]["_id"])
        self.assertEqual(self.db.waybills.count_documents({}), 1)
        stored_job = self.db.dispatch_jobs.find_one({"_id": job["_id"]})
        self.assertEqual(stored_job["linked_waybill_id"], first["waybill"]["_id"])
        self.assertEqual(first["waybill"]["source_key"], f"dispatch_job:{job['_id']}")


if __name__ == "__main__":
    unittest.main()
