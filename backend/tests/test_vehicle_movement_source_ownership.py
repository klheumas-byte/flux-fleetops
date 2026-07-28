from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from mongomock import MongoClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import movement_source_service as source_service
from services import vehicle_movement_service as movement_service
from routes.vehicle_movements import vehicle_movements_bp
from utils.api_error import ApiError
from utils.errors import register_error_handlers


class VehicleMovementSourceOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.actor_id = ObjectId()
        self.vehicle_id = ObjectId()

    def test_generic_create_rejects_every_source_managed_type(self):
        for movement_type, ownership in source_service.SOURCE_MOVEMENT_OWNERSHIP.items():
            with self.subTest(movement_type=movement_type), self.assertRaises(ApiError) as raised:
                movement_service.create_vehicle_movement(
                    {
                        "vehicle_id": str(self.vehicle_id),
                        "movement_type": movement_type,
                        "status": "approved",
                    },
                    current_user_id=str(self.actor_id),
                    current_role="admin",
                )

            error = raised.exception
            self.assertEqual(error.status_code, 400)
            self.assertEqual(error.errors[0]["code"], "source_managed_movement_required")
            self.assertEqual(error.errors[0]["movement_type"], movement_type)
            self.assertEqual(error.errors[0]["owning_module"], ownership["owning_module"])

    def test_source_service_creates_once_and_retry_is_idempotent(self):
        collection = MongoClient().db.vehicle_movements
        source_id = ObjectId()
        defaults = {
            "vehicle_id": self.vehicle_id,
            "movement_type": "customer_dispatch",
            "status": "approved",
            "created_by": self.actor_id,
        }

        with patch.object(source_service, "vehicle_movements_collection", return_value=collection):
            first = source_service.ensure_movement_for_source(
                source_type="dispatch_job",
                source_record_id=source_id,
                movement_defaults=defaults,
            )
            second = source_service.ensure_movement_for_source(
                source_type="dispatch_job",
                source_record_id=source_id,
                movement_defaults=defaults,
            )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["movement"]["_id"], second["movement"]["_id"])
        self.assertEqual(collection.count_documents({}), 1)

    def test_source_service_rejects_type_owned_by_another_module(self):
        with self.assertRaises(ApiError) as raised:
            source_service.ensure_movement_for_source(
                source_type="dispatch_job",
                source_record_id=ObjectId(),
                movement_defaults={
                    "vehicle_id": self.vehicle_id,
                    "movement_type": "stock_transfer",
                    "status": "approved",
                },
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.errors[0]["code"], "invalid_movement_source_owner")
        self.assertEqual(raised.exception.errors[0]["owning_module"], "stock_transfers")

    def test_generic_update_rejects_all_source_ownership_fields(self):
        document = {
            "_id": ObjectId(),
            "vehicle_id": self.vehicle_id,
            "movement_type": "customer_dispatch",
            "status": "approved",
            "source_type": "dispatch_job",
            "source_module": "dispatch",
        }
        payload = {field: "replacement" for field in source_service.SOURCE_OWNERSHIP_FIELDS}

        with patch.object(
            movement_service,
            "_get_vehicle_movement_document",
            return_value=document,
        ), self.assertRaises(ApiError) as raised:
            movement_service.update_vehicle_movement(
                str(document["_id"]),
                payload,
                current_user_id=str(self.actor_id),
                current_role="admin",
            )

        error = raised.exception
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.errors[0]["code"], "source_ownership_fields_immutable")
        self.assertEqual(set(error.errors[0]["fields"]), set(source_service.SOURCE_OWNERSHIP_FIELDS))
        self.assertEqual(error.errors[0]["movement_type"], "customer_dispatch")
        self.assertEqual(error.errors[0]["owning_module"], "dispatch")

    def test_generic_update_cannot_change_a_source_managed_type(self):
        document = {
            "_id": ObjectId(),
            "vehicle_id": self.vehicle_id,
            "movement_type": "stock_transfer",
            "status": "approved",
        }

        with patch.object(
            movement_service,
            "_get_vehicle_movement_document",
            return_value=document,
        ), self.assertRaises(ApiError) as raised:
            movement_service.update_vehicle_movement(
                str(document["_id"]),
                {"movement_type": "other"},
                current_user_id=str(self.actor_id),
                current_role="admin",
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.errors[0]["code"], "source_managed_movement_type_immutable")
        self.assertEqual(raised.exception.errors[0]["owning_module"], "stock_transfers")

    def test_legacy_movement_without_source_key_remains_readable(self):
        legacy = {
            "_id": ObjectId(),
            "movement_id": "VM-LEGACY",
            "vehicle_id": self.vehicle_id,
            "movement_type": "customer_dispatch",
            "status": "closed",
        }

        with patch.object(
            movement_service,
            "_get_vehicle_movement_document",
            return_value=legacy,
        ), patch.object(
            movement_service,
            "_batch_enrich_vehicle_movements",
            side_effect=lambda documents: documents,
        ):
            result = movement_service.get_vehicle_movement_by_id(
                str(legacy["_id"]),
                current_user_id=str(self.actor_id),
                current_role="admin",
            )

        self.assertEqual(result["movement_id"], "VM-LEGACY")
        self.assertNotIn("source_key", result)

    def test_source_managed_error_is_returned_as_json(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="source-ownership-test-secret-at-least-32-bytes",
        )
        JWTManager(app)
        register_error_handlers(app)
        app.register_blueprint(vehicle_movements_bp, url_prefix="/api/vehicle-movements")
        with app.app_context():
            token = create_access_token(
                identity=str(self.actor_id),
                additional_claims={"role": "admin"},
            )

        response = app.test_client().post(
            "/api/vehicle-movements",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "vehicle_id": str(self.vehicle_id),
                "movement_type": "customer_dispatch",
                "status": "approved",
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content_type, "application/json")
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], payload["errors"][0]["message"])
        self.assertEqual(payload["errors"][0]["code"], "source_managed_movement_required")
        self.assertEqual(payload["errors"][0]["movement_type"], "customer_dispatch")
        self.assertEqual(payload["errors"][0]["owning_module"], "dispatch")


if __name__ == "__main__":
    unittest.main()
