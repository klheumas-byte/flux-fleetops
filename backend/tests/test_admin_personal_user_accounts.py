from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from werkzeug.security import generate_password_hash


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from routes.auth import auth_bp
from services import auth_service
from utils import decorators
from utils.api_error import ApiError
from utils.decorators import role_required


class AdminPersonalUserAccountTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).admin_personal_users
        self.admin_id, self.owner_id = ObjectId(), ObjectId()
        self.db.users.insert_many([
            {"_id": self.admin_id, "full_name": "Admin", "email": "admin@example.com", "phone": "0200000001", "password_hash": generate_password_hash("AdminPass1"), "role": "admin", "status": "active", "must_change_password": False},
            {"_id": self.owner_id, "full_name": "Owner", "email": "owner@example.com", "phone": "0200000002", "password_hash": generate_password_hash("OwnerPass1"), "role": "owner", "status": "active", "must_change_password": False},
        ])

    def _patch(self, module=auth_service):
        return patch.object(module, "get_collection", side_effect=lambda name: self.db[name])

    def _create_personal(self, email="personal@example.com", phone="0200000003"):
        with self._patch():
            return auth_service.create_user_as("admin", {
                "full_name": "Personal User", "email": email, "phone": phone,
                "password": "TempPass1", "role": "personal_vehicle_owner", "status": "active",
            }, str(self.admin_id))

    def test_admin_creates_personal_user_with_temporary_password_and_audit(self):
        user = self._create_personal()
        self.assertEqual(user["role"], "personal_vehicle_owner")
        self.assertTrue(user["must_change_password"])
        self.assertNotIn("password_hash", user)
        audit = self.db.user_management_audit.find_one({"action": "user_created"})
        self.assertEqual(audit["actor_user_id"], self.admin_id)
        self.assertEqual(audit["target_user_id"], ObjectId(user["id"]))

    def test_duplicate_email_and_phone_are_rejected(self):
        self._create_personal()
        with self.assertRaises(ApiError) as email_error:
            self._create_personal(email="PERSONAL@example.com", phone="0200000004")
        with self.assertRaises(ApiError) as phone_error:
            self._create_personal(email="other@example.com", phone="0200000003")
        self.assertEqual(email_error.exception.status_code, 409)
        self.assertEqual(phone_error.exception.status_code, 409)

    def test_temporary_login_password_change_and_reset_cycle(self):
        user = self._create_personal()
        with self._patch(), patch.object(auth_service, "create_access_token", return_value="token"):
            login = auth_service.authenticate_user("personal@example.com", "TempPass1")
            self.assertTrue(login["user"]["must_change_password"])
            changed = auth_service.change_own_password(user["id"], "TempPass1", "PrivatePass2")
            self.assertFalse(changed["must_change_password"])
            auth_service.authenticate_user("personal@example.com", "PrivatePass2")
            reset = auth_service.reset_user_password_as(str(self.admin_id), "admin", user["id"], "ResetPass3")
            self.assertTrue(reset["must_change_password"])
            auth_service.authenticate_user("personal@example.com", "ResetPass3")
        actions = {item["action"] for item in self.db.user_management_audit.find({})}
        self.assertTrue({"first_login_password_changed", "temporary_password_reset"}.issubset(actions))

    def test_inactive_account_is_denied(self):
        user = self._create_personal()
        with self._patch():
            auth_service.update_user_status_as("admin", user["id"], "inactive", str(self.admin_id))
            with self.assertRaises(ApiError) as error:
                auth_service.authenticate_user("personal@example.com", "TempPass1")
        self.assertEqual(error.exception.status_code, 403)

    def test_admin_edits_contact_fields_and_uniqueness_is_preserved(self):
        user = self._create_personal()
        with self._patch():
            updated = auth_service.update_user_account_as(str(self.admin_id), "admin", user["id"], {"full_name": "Updated Name", "email": "updated@example.com", "phone": "0200000005"})
            with self.assertRaises(ApiError) as duplicate:
                auth_service.update_user_account_as(str(self.admin_id), "admin", user["id"], {"email": "admin@example.com"})
        self.assertEqual(updated["full_name"], "Updated Name")
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertIsNotNone(self.db.user_management_audit.find_one({"action": "user_profile_changed"}))

    def test_first_login_gate_allows_password_change_then_personal_route(self):
        user = self._create_personal()
        app = Flask(__name__)
        app.config.update(TESTING=True, JWT_SECRET_KEY="test-secret-key-that-is-at-least-32-bytes", MONGO_URI="mongomock://test")
        JWTManager(app)
        app.register_blueprint(auth_bp, url_prefix="/api/auth")

        @app.get("/api/personal-test")
        @role_required("personal_vehicle_owner")
        def personal_test():
            return {"ok": True}

        with app.app_context():
            token = create_access_token(identity=user["id"], additional_claims={"role": "personal_vehicle_owner"})
        headers = {"Authorization": f"Bearer {token}"}
        with self._patch(), patch.object(decorators, "get_collection", side_effect=lambda name: self.db[name]):
            client = app.test_client()
            blocked = client.get("/api/personal-test", headers=headers)
            changed = client.post("/api/auth/change-password", headers=headers, json={"current_password": "TempPass1", "new_password": "PrivatePass2", "confirm_password": "PrivatePass2"})
            allowed = client.get("/api/personal-test", headers=headers)
        self.assertEqual(blocked.status_code, 428)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(allowed.status_code, 200)

    def test_personal_role_is_denied_from_admin_commercial_route(self):
        user = self._create_personal()
        self.db.users.update_one({"_id": ObjectId(user["id"])}, {"$set": {"must_change_password": False}})
        app = Flask(__name__)
        app.config.update(TESTING=True, JWT_SECRET_KEY="test-secret-key-that-is-at-least-32-bytes", MONGO_URI="mongomock://test")
        JWTManager(app)

        @app.get("/api/admin-test")
        @role_required("owner", "admin")
        def admin_test():
            return {"ok": True}

        with app.app_context():
            token = create_access_token(identity=user["id"], additional_claims={"role": "personal_vehicle_owner"})
        with patch.object(decorators, "get_collection", side_effect=lambda name: self.db[name]):
            response = app.test_client().get("/api/admin-test", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 403)

    def test_frontend_redirect_and_account_controls_are_present(self):
        app_source = (BACKEND_DIR.parent / "src/app/App.tsx").read_text(encoding="utf-8")
        portal_source = (BACKEND_DIR.parent / "src/app/components/personal/PersonalVehiclePortal.tsx").read_text(encoding="utf-8")
        accounts_source = (BACKEND_DIR.parent / "src/app/components/admin/PersonalUserAccounts.tsx").read_text(encoding="utf-8")
        self.assertIn("currentUser?.must_change_password", app_source)
        self.assertIn("/my-vehicles/${section}", portal_source)
        for marker in ("Personal Vehicle Owner", "reset-password", "last_login", "created_at"):
            self.assertIn(marker, accounts_source)


if __name__ == "__main__":
    unittest.main()
