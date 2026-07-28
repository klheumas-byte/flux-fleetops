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

from flask import Flask
from routes.faults import faults_bp
from services import assignment_service, fault_service, fleet_owner_service, maintenance_service, preventive_maintenance_service, user_service
from utils.api_error import ApiError
from utils.decorators import request_driver_capability


class Sprint10Tests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().sprint10
        self.admin_id, self.driver_id = ObjectId(), ObjectId()
        self.account_id, self.profile_id = ObjectId(), ObjectId()
        self.vehicle_id, self.other_vehicle_id = ObjectId(), ObjectId()
        self.db.users.insert_many([
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Admin User"},
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver A", "driver_profile": {"operating_mode": "target_only", "target_enabled": True, "target_amount": 500}},
            {"_id": self.account_id, "role": "fleet_owner", "status": "active", "full_name": "Fleet Owner"},
        ])
        self.db.fleet_owners.insert_one({"_id": self.profile_id, "account_id": self.account_id, "status": "active"})
        self.db.vehicles.insert_many([
            {"_id": self.vehicle_id, "registration_number": "OWN-10", "ownership_type": "third_party_owned", "fleet_owner_id": self.profile_id, "assigned_driver_id": self.driver_id},
            {"_id": self.other_vehicle_id, "registration_number": "OTHER-10", "ownership_type": "company_owned"},
        ])
        self.assignment_id = self.db.assignments.insert_one({
            "driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "operating_mode": "target_only",
            "target_enabled": True, "target_amount": 500, "target_frequency": "weekly", "weekly_target": 500,
            "daily_target": 0, "start_date": "2026-07-01", "start_time": datetime(2026, 7, 1, tzinfo=timezone.utc),
            "status": "active", "assigned_by": self.admin_id, "created_by": self.admin_id,
            "created_at": datetime.now(timezone.utc), "allocation_active": True,
        }).inserted_id

    def _patch(self, module):
        return patch.object(module, "get_collection", side_effect=lambda name: self.db[name])

    def test_mode_change_is_immediate_without_rewriting_assignment_snapshot_and_is_audited(self):
        with self._patch(user_service), patch.object(user_service, "create_notification"):
            result = user_service.update_driver_profile_as(
                str(self.admin_id), "admin", str(self.driver_id),
                {"driver_profile": {"operating_mode": "hybrid", "target_enabled": True, "target_amount": 500}, "change_reason": "Driver now supports dispatch"},
            )
        self.assertEqual(result["driver_profile"]["operating_mode"], "hybrid")
        self.assertEqual(self.db.assignments.find_one({"_id": self.assignment_id})["operating_mode"], "target_only")
        audit = self.db.fleet_owner_audit.find_one({"action": "driver_settings_changed"})
        self.assertEqual(audit["reason"], "Driver now supports dispatch")
        self.assertEqual(audit["actor_role"], "admin")

    def test_same_mode_submission_is_idempotent(self):
        before = self.db.users.find_one({"_id": self.driver_id})
        with self._patch(user_service), patch.object(user_service, "create_notification"):
            user_service.update_driver_profile_as(str(self.admin_id), "admin", str(self.driver_id), {
                "driver_profile": {"operating_mode": "target_only", "target_enabled": True, "target_amount": 500}
            })
        self.assertEqual(self.db.fleet_owner_audit.count_documents({}), 0)
        self.assertEqual(self.db.users.find_one({"_id": self.driver_id})["updated_at"] if "updated_at" in before else None, before.get("updated_at"))

    def test_driver_cannot_change_operating_mode(self):
        with self._patch(user_service):
            with self.assertRaises(ApiError) as error:
                user_service.update_driver_profile_as(str(self.driver_id), "driver", str(self.driver_id), {"operating_mode": "hybrid"})
        self.assertEqual(error.exception.status_code, 403)

    def test_universal_safety_paths_are_not_mode_gated(self):
        for path in ("/api/faults", "/api/incidents", "/api/maintenance-overrides", "/api/assignments/my-handovers", "/api/driver/maintenance"):
            self.assertIsNone(request_driver_capability(path))
        self.assertEqual(request_driver_capability("/api/driver/operational-tasks"), "operations")
        self.assertEqual(request_driver_capability("/api/driver/wallet"), "targets")
        self.assertEqual(request_driver_capability("/api/calendar"), "targets")

    def test_fleet_owner_requests_are_scoped_and_reviewed_without_direct_mutation(self):
        with self._patch(fleet_owner_service), patch.object(fleet_owner_service, "notify_roles"), patch.object(fleet_owner_service, "create_notification"):
            request = fleet_owner_service.create_participation_request(str(self.account_id), {
                "vehicle_id": str(self.vehicle_id), "request_type": "driver_reassignment", "reason": "Driver unavailable",
            })
            reviewed = fleet_owner_service.review_participation_request(request["id"], {"status": "approved"}, str(self.admin_id), "admin")
        self.assertEqual(reviewed["status"], "approved")
        self.assertEqual(self.db.assignments.find_one({"_id": self.assignment_id})["status"], "active")
        with self._patch(fleet_owner_service):
            with self.assertRaises(ApiError) as error:
                fleet_owner_service.create_participation_request(str(self.account_id), {
                    "vehicle_id": str(self.other_vehicle_id), "request_type": "vehicle_withdrawal", "reason": "No",
                })
        self.assertEqual(error.exception.status_code, 404)

    def test_fleet_owner_comment_is_owned_vehicle_scoped(self):
        fault_id = self.db.faults.insert_one({"vehicle_id": self.vehicle_id, "status": "reported"}).inserted_id
        other_fault = self.db.faults.insert_one({"vehicle_id": self.other_vehicle_id, "status": "reported"}).inserted_id
        with self._patch(fleet_owner_service):
            result = fleet_owner_service.add_owned_case_comment(str(self.account_id), "fault", str(fault_id), "Please inspect the brakes")
            self.assertEqual(result["created_by_role"], "fleet_owner")
            with self.assertRaises(ApiError):
                fleet_owner_service.add_owned_case_comment(str(self.account_id), "fault", str(other_fault), "Not mine")

    def test_fleet_owner_reports_fault_and_cannot_report_for_other_vehicle(self):
        category_id = self.db.fault_categories.insert_one({"name": "Brakes", "status": "active"}).inserted_id
        component_id = self.db.fault_components.insert_one({"name": "Pads", "category_id": category_id, "status": "active"}).inserted_id
        payload = {"vehicle_id": str(self.vehicle_id), "category_id": str(category_id), "component_id": str(component_id), "severity": "high", "description": "Grinding noise", "vehicle_unsafe": False}
        with self._patch(fault_service), self._patch(fleet_owner_service), patch.object(fault_service, "create_notification"), patch.object(fault_service, "notify_roles"), patch.object(fault_service, "notify_linked_owner"), patch.object(fault_service, "log_db_duration"):
            result = fault_service.create_fault(payload, str(self.account_id), "fleet_owner")
            self.assertEqual(result["reporter_role"], "fleet_owner")
            with self.assertRaises(ApiError):
                fault_service.create_fault({**payload, "vehicle_id": str(self.other_vehicle_id)}, str(self.account_id), "fleet_owner")

    def test_fleet_owner_document_action_obeys_vehicle_scope(self):
        payload = {"vehicle_id": str(self.vehicle_id), "compliance_item_name": "Insurance", "issue_date": "2026-01-01", "expiry_date": "2027-01-01", "renewal_frequency": "yearly", "warning_days_before": 30}
        with self._patch(preventive_maintenance_service), self._patch(fleet_owner_service), patch.object(preventive_maintenance_service, "_notify_compliance_status"):
            record = preventive_maintenance_service.create_compliance_record(payload, str(self.account_id), "fleet_owner")
            self.assertEqual(record["vehicle_id"], str(self.vehicle_id))
            with self.assertRaises(ApiError):
                preventive_maintenance_service.create_compliance_record({**payload, "vehicle_id": str(self.other_vehicle_id)}, str(self.account_id), "fleet_owner")

    def test_conversion_route_exists_with_correct_method(self):
        app = Flask(__name__)
        app.register_blueprint(faults_bp, url_prefix="/api/faults")
        rules = {(rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"}))) for rule in app.url_map.iter_rules()}
        self.assertIn(("/api/faults/<fault_id>/convert-to-maintenance", ("POST",)), rules)

    def test_repeated_conversion_returns_existing_canonical_job(self):
        fault_id, job_id = ObjectId(), ObjectId()
        fault = {"_id": fault_id, "status": "converted_to_maintenance", "maintenance_job_id": job_id}
        job = {"_id": job_id, "vehicle_id": self.vehicle_id, "status": "pending"}
        with patch.object(maintenance_service, "_get_fault_document", return_value=fault), patch.object(maintenance_service, "maintenance_jobs_collection", return_value=self.db.maintenance_jobs), patch.object(maintenance_service, "_enrich_maintenance_job", side_effect=lambda item: {"id": str(item["_id"]) }):
            self.db.maintenance_jobs.insert_one(job)
            first = maintenance_service.convert_fault_to_maintenance_job(str(fault_id), str(self.admin_id), "admin")
            second = maintenance_service.convert_fault_to_maintenance_job(str(fault_id), str(self.admin_id), "admin")
        self.assertEqual(first, second)
        self.assertEqual(self.db.maintenance_jobs.count_documents({"_id": job_id}), 1)

    def test_eligible_conversion_and_invalid_status_validation(self):
        approved = {"_id": ObjectId(), "status": "approved", "vehicle_id": self.vehicle_id, "driver_id": self.driver_id, "description": "Repair", "severity": "medium"}
        with patch.object(maintenance_service, "_get_fault_document", return_value=approved), patch.object(maintenance_service, "maintenance_jobs_collection", return_value=self.db.maintenance_jobs), patch.object(maintenance_service, "fault_categories_collection", return_value=self.db.fault_categories), patch.object(maintenance_service, "fault_components_collection", return_value=self.db.fault_components), patch.object(maintenance_service, "create_maintenance_job", return_value={"id": "job-1"}) as create:
            result = maintenance_service.convert_fault_to_maintenance_job(str(approved["_id"]), str(self.admin_id), "admin")
        self.assertEqual(result["id"], "job-1")
        create.assert_called_once()
        invalid = {**approved, "status": "reported"}
        with patch.object(maintenance_service, "_get_fault_document", return_value=invalid), patch.object(maintenance_service, "maintenance_jobs_collection", return_value=self.db.maintenance_jobs):
            with self.assertRaises(ApiError) as error:
                maintenance_service.convert_fault_to_maintenance_job(str(invalid["_id"]), str(self.admin_id), "admin")
        self.assertIn("Only approved faults", str(error.exception))

    def test_allocation_history_resolves_actor_names_in_batch(self):
        with self._patch(assignment_service):
            records = assignment_service.list_assignments()
        self.assertEqual(records[0]["assigned_by_user"]["full_name"], "Admin User")
        self.assertIsNone(records[0]["ended_by_user"])


if __name__ == "__main__":
    unittest.main()
