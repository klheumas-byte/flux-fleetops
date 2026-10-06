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

from services import collection_service, payment_cycle_service, wallet_service


class WeeklyRemittanceTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().weekly_remittance
        self.driver_id, self.admin_id, self.vehicle_id, self.assignment_id = (ObjectId() for _ in range(4))
        self.db.users.insert_many([
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Abraham Aeyee"},
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Admin"},
        ])
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "GS454126", "make": "Kia", "model": "Picanto"})
        self.db.assignments.insert_one({
            "_id": self.assignment_id, "driver_id": self.driver_id, "vehicle_id": self.vehicle_id,
            "start_date": "2026-07-20", "status": "active", "target_enabled": True,
            "weekly_target": 800.0, "daily_target": 133.0,
        })
        modules = (payment_cycle_service, collection_service, wallet_service)
        self.patches = [patch.object(module, "get_collection", side_effect=lambda name, db=self.db: db[name]) for module in modules]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)

    def payment(self, amount, payment_date, status="approved", allocations=None):
        window = payment_cycle_service.get_weekly_cycle_window(payment_date)
        document = {"_id": ObjectId(), "driver_id": self.driver_id, "vehicle_id": self.vehicle_id,
                    "assignment_id": self.assignment_id, "amount": float(amount), "submitted_amount": float(amount),
                    "collection_date": payment_date, "status": status, "cycle_key": window["cycle_key"],
                    "week_start": window["week_start"], "week_end": window["week_end"],
                    "payment_deadline": window["payment_deadline"],
                    "submitted_at": datetime.fromisoformat(payment_date).replace(tzinfo=timezone.utc),
                    "approved_at": datetime.fromisoformat(payment_date).replace(tzinfo=timezone.utc) if status == "approved" else None,
                    "created_at": datetime.fromisoformat(payment_date).replace(tzinfo=timezone.utc)}
        if allocations is not None: document["remittance_allocations"] = allocations
        self.db.collections.insert_one(document)
        return document

    def test_abraham_picanto_reuses_assignment_and_partial_payment(self):
        self.payment(400, "2026-07-25")
        assignment = self.db.assignments.find_one({"_id": self.assignment_id})
        ledger = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-07-25")
        self.assertEqual(ledger["agreement"]["assignment_id"], str(self.assignment_id))
        self.assertEqual(ledger["agreement"]["effective_start"], "2026-07-20")
        self.assertEqual(ledger["agreement"]["weekly_amount"], 800)
        self.assertEqual(ledger["weeks"][0]["outstanding"], 400)
        self.assertEqual(ledger["weeks"][0]["status"], "partial")

    def test_effective_rate_change_keeps_historical_weeks(self):
        payment_cycle_service.update_remittance_agreement(str(self.assignment_id), {
            "weekly_amount": 1000, "effective_from": "2026-08-03", "reason": "New owner amount",
        }, current_user_id=str(self.admin_id))
        assignment = self.db.assignments.find_one({"_id": self.assignment_id})
        ledger = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-08-08")
        by_start = {row["week_start"]: row for row in ledger["weeks"]}
        self.assertEqual(by_start["2026-07-20"]["original_amount"], 800)
        self.assertEqual(by_start["2026-07-27"]["original_amount"], 800)
        self.assertEqual(by_start["2026-08-03"]["original_amount"], 1000)
        self.assertEqual(ledger["position"]["gross_expected"], 2600)

    def test_dashboard_and_wallet_use_current_authoritative_obligation(self):
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 8, 8, 12, tzinfo=timezone.utc)), \
             patch.object(collection_service, "now_utc", return_value=datetime(2026, 8, 8, 12, tzinfo=timezone.utc)), \
             patch.object(wallet_service, "now_utc", return_value=datetime(2026, 8, 8, 12, tzinfo=timezone.utc)), \
             patch.object(collection_service, "log_db_duration"), \
             patch.object(collection_service, "_log_slow_collection_section"):
            payment_cycle_service.update_remittance_agreement(str(self.assignment_id), {
                "weekly_amount": 1000, "effective_from": "2026-08-03", "reason": "Current agreement rate",
            }, current_user_id=str(self.admin_id))
            request = payment_cycle_service.submit_non_working_request({
                "selection_type": "whole_week", "start_date": "2026-08-03",
                "reason_code": "vehicle_issue", "explanation": "Approved repair days",
                "requested_action": "reduction",
            }, current_user_id=str(self.driver_id), request_key="current-dashboard")
            payment_cycle_service.decide_non_working_request(request["id"], {
                "decision_type": "reduce", "revised_amount_due": 600,
                "decision_reason": "Approved current-week reduction",
            }, current_user_id=str(self.admin_id))
            dashboard = collection_service.get_driver_dashboard_summary(str(self.driver_id))
            wallet = wallet_service.get_logged_in_driver_wallet(str(self.driver_id))
        self.assertEqual(dashboard["weekly_target"], 600)
        self.assertEqual(dashboard["weekly_cycle"]["original_amount"], 1000)
        self.assertEqual(dashboard["outstanding_balance"], 600)
        self.assertEqual(wallet["weekly_target"], 600)
        self.assertEqual(wallet["remittance_agreement"]["weekly_amount"], 1000)

    def test_non_working_pending_does_not_reduce_and_approved_waiver_does(self):
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 7, 24, tzinfo=timezone.utc)):
            request = payment_cycle_service.submit_non_working_request({
                "start_date": "2026-07-20", "end_date": "2026-07-25", "reason": "Vehicle repair",
            }, current_user_id=str(self.driver_id), request_key="one")
        assignment = self.db.assignments.find_one({"_id": self.assignment_id})
        pending = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-07-25")
        self.assertEqual(pending["position"]["adjusted_expected"], 800)
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 7, 25, tzinfo=timezone.utc)):
            payment_cycle_service.decide_non_working_request(request["id"], {
                "attendance_status": "confirmed", "financial_treatment": "waive", "decision_reason": "Workshop evidence confirmed",
            }, current_user_id=str(self.admin_id))
        waived = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-07-25")
        self.assertEqual(waived["position"]["adjusted_expected"], 0)
        self.assertEqual(waived["weeks"][0]["status"], "waived")
        self.assertEqual(waived["position"]["arrears"], 0)

    def test_multi_week_allocation_and_excess_credit(self):
        payment = self.payment(1800, "2026-08-08", allocations=[])
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 8, 8, 12, tzinfo=timezone.utc)):
            result = payment_cycle_service.replace_payment_allocations(str(payment["_id"]), [
                {"cycle_key": "2026-W30", "amount": 800},
                {"cycle_key": "2026-W31", "amount": 800},
            ], current_user_id=str(self.admin_id))
        self.assertEqual(result["credit"], 200)
        ledger = payment_cycle_service.build_weekly_ledger(self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-08-08")
        self.assertEqual(ledger["position"]["confirmed_receipts"], 1600)
        self.assertEqual(ledger["position"]["total_confirmed_receipts"], 1800)
        self.assertEqual(ledger["position"]["applicable_credit"], 200)
        self.assertEqual(ledger["position"]["outstanding"], 800)

    def test_unallocated_credit_does_not_clear_debt_until_applied(self):
        self.payment(1000, "2026-08-08", allocations=[])
        assignment = self.db.assignments.find_one({"_id": self.assignment_id})
        before = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-08-10")
        self.assertEqual(before["position"]["available_credit"], 1000)
        self.assertEqual(before["position"]["arrears"], 2400)
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 8, 10, 12, tzinfo=timezone.utc)):
            result = payment_cycle_service.apply_confirmed_credit(
                str(self.assignment_id),
                [{"cycle_key": "2026-W30", "amount": 800}, {"cycle_key": "2026-W31", "amount": 200}],
                current_user_id=str(self.admin_id),
            )
        self.assertEqual(result["applied"], 1000)
        self.assertEqual(result["position"]["available_credit"], 0)
        self.assertEqual(result["position"]["arrears"], 1400)

    def test_bulk_credit_oldest_first_leaves_only_genuine_excess(self):
        payment = self.payment(4430, "2026-09-20", allocations=[])
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 9, 20, 12, tzinfo=timezone.utc)):
            result = payment_cycle_service.apply_confirmed_credit(
                str(self.assignment_id), None, current_user_id=str(self.admin_id)
            )
        stored = self.db.collections.find_one({"_id": payment["_id"]})
        self.assertEqual([row["cycle_key"] for row in stored["remittance_allocations"][:2]], ["2026-W30", "2026-W31"])
        self.assertEqual(result["position"]["available_credit"], 0)
        self.assertEqual(result["position"]["total_unpaid"], 2770)

    def test_driver_submission_is_idempotent_and_unconfirmed_payment_does_not_reduce_debt(self):
        payload = {"amount": 400, "collection_date": "2026-07-25", "payment_method": "cash", "notes": "Part payment"}
        submitted_at = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
        with patch.object(collection_service, "now_utc", return_value=submitted_at):
            first = collection_service.submit_driver_payment(payload, str(self.driver_id), idempotency_key="mobile-1")
            second = collection_service.submit_driver_payment(payload, str(self.driver_id), idempotency_key="mobile-1")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.db.collections.count_documents({}), 1)
        ledger = payment_cycle_service.build_weekly_ledger(self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-07-25")
        self.assertEqual(ledger["position"]["confirmed_receipts"], 0)
        self.assertEqual(ledger["position"]["outstanding"], 800)
        self.assertEqual(ledger["position"]["pending_confirmation"], 400)

    def test_driver_manual_week_allocation_is_preserved_on_confirmation(self):
        payload = {
            "amount": 600, "collection_date": "2026-08-08", "payment_method": "momo",
            "remittance_allocations": [
                {"cycle_key": "2026-W30", "amount": 400},
                {"cycle_key": "2026-W31", "amount": 200},
            ],
        }
        with patch.object(collection_service, "now_utc", return_value=datetime(2026, 8, 8, 9, tzinfo=timezone.utc)):
            submitted = collection_service.submit_driver_payment(payload, str(self.driver_id), idempotency_key="manual-weeks")
        pending = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-08-08"
        )
        self.assertEqual(pending["position"]["confirmed_receipts"], 0)
        with patch.object(collection_service, "now_utc", return_value=datetime(2026, 8, 8, 12, tzinfo=timezone.utc)):
            collection_service.update_collection_status(
                submitted["id"], "approved", str(self.admin_id), admin_received_amount=600
            )
        stored = self.db.collections.find_one({"_id": ObjectId(submitted["id"])})
        self.assertEqual([row["amount"] for row in stored["remittance_allocations"]], [400.0, 200.0])
        confirmed = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-08-08"
        )
        by_key = {row["cycle_key"]: row for row in confirmed["weeks"]}
        self.assertEqual(by_key["2026-W30"]["outstanding"], 400)
        self.assertEqual(by_key["2026-W31"]["outstanding"], 600)

    def test_confirmed_payment_auto_allocates_oldest_outstanding_once(self):
        pending = self.payment(1000, "2026-08-08", status="pending")
        collection_service.update_collection_status(str(pending["_id"]), "approved", str(self.admin_id), admin_received_amount=1000)
        stored = self.db.collections.find_one({"_id": pending["_id"]})
        self.assertEqual(stored["remittance_allocations"], [
            {"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 800.0},
            {"cycle_key": "2026-W31", "week_start": "2026-07-27", "amount": 200.0},
        ])
        self.assertEqual(self.db.wallet_entries.count_documents({"reference_id": pending["_id"]}), 1)

    def test_confirmation_uses_authenticated_actor_and_is_not_counted_twice(self):
        pending = self.payment(800, "2026-07-25", status="pending")
        self.db.collections.update_one({"_id": pending["_id"]}, {"$set": {
            "submitted_by_driver_id": self.driver_id,
            "submitted_at": datetime(2026, 7, 25, 9, tzinfo=timezone.utc),
        }})
        confirmed_at = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
        with patch.object(collection_service, "now_utc", return_value=confirmed_at), \
             patch.object(payment_cycle_service, "now_utc", return_value=confirmed_at):
            collection_service.update_collection_status(
                str(pending["_id"]), "approved", str(self.admin_id), admin_received_amount=800
            )
            with self.assertRaisesRegex(Exception, "already has that status"):
                collection_service.update_collection_status(
                    str(pending["_id"]), "approved", str(self.admin_id), admin_received_amount=800
                )
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-07-25"
        )
        payment_detail = ledger["weeks"][0]["payments"][0]
        self.assertEqual(payment_detail["actual_payment_date"], "2026-07-25")
        self.assertTrue(payment_detail["submitted_at"].startswith("2026-07-25T09:00:00"))
        self.assertTrue(payment_detail["approved_at"].startswith("2026-07-25T12:00:00"))
        self.assertEqual(payment_detail["confirmed_by_user"]["full_name"], "Admin")
        self.assertEqual(payment_detail["confirmed_by_user"]["role"], "admin")
        self.assertEqual(ledger["position"]["confirmed_receipts"], 800)
        self.assertEqual(self.db.wallet_entries.count_documents({"reference_id": pending["_id"]}), 1)

    def test_manual_confirmation_ignores_frontend_supplied_confirmer(self):
        spoofed_owner = ObjectId()
        self.db.users.insert_one({"_id": spoofed_owner, "role": "owner", "status": "active", "full_name": "Spoofed Owner"})
        with patch.object(collection_service, "now_utc", return_value=datetime(2026, 7, 25, 12, tzinfo=timezone.utc)), \
             patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 7, 25, 12, tzinfo=timezone.utc)):
            created = collection_service.create_collection({
                "driver_id": str(self.driver_id), "vehicle_id": str(self.vehicle_id),
                "assignment_id": str(self.assignment_id), "amount": 800,
                "collection_date": "2026-07-25", "payment_method": "cash", "status": "approved",
                "approved_by_admin_id": str(spoofed_owner),
            }, str(self.admin_id))
        stored = self.db.collections.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(stored["approved_by_admin_id"], self.admin_id)
        self.assertNotEqual(stored["approved_by_admin_id"], spoofed_owner)

    def test_reversal_preserves_payment_audit_but_no_longer_reduces_balance(self):
        pending = self.payment(800, "2026-07-25", status="pending")
        with patch.object(collection_service, "now_utc", return_value=datetime(2026, 7, 25, 10, tzinfo=timezone.utc)), \
             patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 7, 25, 10, tzinfo=timezone.utc)):
            collection_service.update_collection_status(
                str(pending["_id"]), "approved", str(self.admin_id), admin_received_amount=800
            )
        with patch.object(collection_service, "now_utc", return_value=datetime(2026, 7, 26, 10, tzinfo=timezone.utc)):
            with self.assertRaisesRegex(Exception, "reversal_reason is required"):
                collection_service.update_collection_status(
                    str(pending["_id"]), "reversed", str(self.admin_id)
                )
            collection_service.update_collection_status(
                str(pending["_id"]), "reversed", str(self.admin_id), rejection_reason="Correction"
            )
            collection_service.update_collection_status(
                str(pending["_id"]), "reversed", str(self.admin_id), rejection_reason="Correction"
            )
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-07-26"
        )
        self.assertEqual(ledger["position"]["confirmed_receipts"], 0)
        self.assertEqual(ledger["weeks"][0]["outstanding"], 800)
        self.assertEqual(ledger["weeks"][0]["payments"][0]["status"], "reversed")
        stored = self.db.collections.find_one({"_id": pending["_id"]})
        self.assertEqual([event["status"] for event in stored["status_history"]][-2:], ["approved", "reversed"])
        self.assertEqual(stored["reversal_reason"], "Correction")
        self.assertEqual(stored["reversed_by_admin_id"], self.admin_id)
        self.assertEqual(stored["reversal_actor"]["full_name"], "Admin")
        self.assertEqual(stored["original_payment_snapshot"]["payment_amount"], 800)
        self.assertEqual(stored["correction_history"][0]["affected_weeks"], ["2026-W30"])
        self.assertEqual(self.db.wallet_entries.count_documents({"event_key": f"collection-reversal:{pending['_id']}"}), 1)

    def test_multi_week_reversal_removes_allocations_and_credit_without_touching_valid_payment(self):
        mistaken = self.payment(1800, "2026-08-08", allocations=[
            {"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 800},
            {"cycle_key": "2026-W31", "week_start": "2026-07-27", "amount": 800},
        ])
        valid = self.payment(400, "2026-08-08", allocations=[
            {"cycle_key": "2026-W32", "week_start": "2026-08-03", "amount": 400},
        ])
        before = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-08-08"
        )
        self.assertEqual(before["position"]["available_credit"], 200)
        with patch.object(collection_service, "now_utc", return_value=datetime(2026, 8, 9, 12, tzinfo=timezone.utc)):
            collection_service.update_collection_status(
                str(mistaken["_id"]), "reversed", str(self.admin_id), rejection_reason="Duplicate bulk payment"
            )
        after = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-08-09"
        )
        by_key = {week["cycle_key"]: week for week in after["weeks"]}
        self.assertEqual(after["position"]["available_credit"], 0)
        self.assertEqual(by_key["2026-W30"]["outstanding"], 800)
        self.assertEqual(by_key["2026-W31"]["outstanding"], 800)
        self.assertEqual(by_key["2026-W32"]["confirmed_allocated_payments"], 400)
        self.assertEqual(self.db.collections.find_one({"_id": valid["_id"]})["status"], "approved")

    def test_oldest_first_suggestion_handles_partial_oldest_balance(self):
        self.payment(400, "2026-07-25", allocations=[
            {"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 400}
        ])
        pending = self.payment(1000, "2026-08-08", status="pending")
        with patch.object(collection_service, "now_utc", return_value=datetime(2026, 8, 8, 12, tzinfo=timezone.utc)), \
             patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 8, 8, 12, tzinfo=timezone.utc)):
            collection_service.update_collection_status(
                str(pending["_id"]), "approved", str(self.admin_id), admin_received_amount=1000
            )
        stored = self.db.collections.find_one({"_id": pending["_id"]})
        self.assertEqual(stored["remittance_allocations"], [
            {"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 400.0},
            {"cycle_key": "2026-W31", "week_start": "2026-07-27", "amount": 600.0},
        ])

    def test_selected_date_excludes_future_receipts_and_period_uses_actual_weeks(self):
        self.payment(800, "2026-07-25")
        self.payment(800, "2026-08-08")
        assignment = self.db.assignments.find_one({"_id": self.assignment_id})
        snapshot = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-07-31")
        self.assertEqual(snapshot["position"]["gross_expected"], 1600)
        self.assertEqual(snapshot["position"]["confirmed_receipts"], 800)
        period = payment_cycle_service.build_weekly_ledger(assignment, start_date="2026-07-27", as_of="2026-08-08")
        self.assertEqual(period["position"]["gross_expected"], 1600)
        self.assertEqual([row["week_start"] for row in period["weeks"]], ["2026-08-03", "2026-07-27"])

    def test_selected_date_uses_confirmation_date_not_claimed_payment_date(self):
        payment = self.payment(800, "2026-07-25")
        self.db.collections.update_one(
            {"_id": payment["_id"]},
            {"$set": {"approved_at": datetime(2026, 8, 2, tzinfo=timezone.utc)}},
        )
        assignment = self.db.assignments.find_one({"_id": self.assignment_id})
        before_confirmation = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-07-31")
        after_confirmation = payment_cycle_service.build_weekly_ledger(assignment, as_of="2026-08-02")
        self.assertEqual(before_confirmation["position"]["confirmed_receipts"], 0)
        self.assertEqual(after_confirmation["position"]["confirmed_receipts"], 800)

    def test_dispatch_receipt_never_reduces_weekly_remittance(self):
        payment = self.payment(800, "2026-07-25")
        self.db.collections.update_one(
            {"_id": payment["_id"]},
            {"$set": {"dispatch_job_id": ObjectId(), "payment_purpose": "dispatch"}},
        )
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-07-25"
        )
        self.assertEqual(ledger["position"]["confirmed_receipts"], 0)
        self.assertEqual(ledger["position"]["outstanding"], 800)

    def test_late_partial_and_pending_weeks_still_count_as_arrears(self):
        self.payment(400, "2026-07-25")
        self.payment(100, "2026-08-01", status="pending")
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-08-10"
        )
        by_start = {row["week_start"]: row for row in ledger["weeks"]}
        self.assertTrue(by_start["2026-07-20"]["is_partial"])
        self.assertTrue(by_start["2026-07-20"]["is_overdue"])
        self.assertTrue(by_start["2026-07-27"]["is_overdue"])
        self.assertEqual(ledger["position"]["arrears"], 2000)

    def test_current_week_before_effective_deadline_is_not_overdue_or_defaulted(self):
        self.db.assignments.update_one({"_id": self.assignment_id}, {"$set": {"start_date": "2026-09-14"}})
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-09-18"
        )
        week = ledger["weeks"][0]
        self.assertEqual(week["week_start"], "2026-09-14")
        self.assertEqual(week["effective_deadline"], "2026-09-19")
        self.assertEqual(week["payment_status"], "not_yet_due")
        self.assertFalse(week["defaulted"])
        self.assertEqual(ledger["position"]["overdue_balance"], 0)

    def test_late_payment_clears_debt_but_preserves_default_history(self):
        payment = self.payment(800, "2026-07-27", allocations=[{"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 800}])
        self.db.collections.update_one({"_id": payment["_id"]}, {"$set": {"approved_at": datetime(2026, 7, 27, tzinfo=timezone.utc)}})
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-07-27"
        )
        week = next(row for row in ledger["weeks"] if row["cycle_key"] == "2026-W30")
        self.assertEqual(week["outstanding"], 0)
        self.assertTrue(week["defaulted"])
        self.assertEqual(week["payment_status"], "paid_late")
        self.assertEqual(ledger["position"]["defaulted_week_count"], 1)

    def test_september_historical_payment_uses_actual_date_and_is_paid_late(self):
        self.db.assignments.update_one({"_id": self.assignment_id}, {"$set": {"start_date": "2026-09-07"}})
        payment = self.payment(800, "2026-09-15", allocations=[
            {"cycle_key": "2026-W37", "week_start": "2026-09-07", "amount": 800}
        ])
        self.db.collections.update_one({"_id": payment["_id"]}, {"$set": {
            "submitted_at": datetime(2026, 9, 16, 9, tzinfo=timezone.utc),
            "created_at": datetime(2026, 9, 16, 9, tzinfo=timezone.utc),
            "approved_at": datetime(2026, 9, 18, 14, tzinfo=timezone.utc),
        }})
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-09-18"
        )
        week = next(row for row in ledger["weeks"] if row["cycle_key"] == "2026-W37")
        self.assertEqual(week["week_start"], "2026-09-07")
        self.assertEqual(week["week_end"], "2026-09-12")
        self.assertEqual(week["effective_deadline"], "2026-09-12")
        self.assertEqual(week["outstanding"], 0)
        self.assertEqual(week["status"], "paid_late")
        self.assertEqual(week["payment_status"], "paid_late")
        self.assertEqual(week["payments"][0]["actual_payment_date"], "2026-09-15")
        self.assertTrue(week["payments"][0]["submitted_at"].startswith("2026-09-16"))
        self.assertTrue(week["payments"][0]["approved_at"].startswith("2026-09-18"))

    def test_actual_payment_before_deadline_is_on_time_even_if_confirmed_later(self):
        self.db.assignments.update_one({"_id": self.assignment_id}, {"$set": {"start_date": "2026-09-07"}})
        payment = self.payment(800, "2026-09-12", allocations=[
            {"cycle_key": "2026-W37", "week_start": "2026-09-07", "amount": 800}
        ])
        self.db.collections.update_one({"_id": payment["_id"]}, {"$set": {
            "submitted_at": datetime(2026, 9, 16, 9, tzinfo=timezone.utc),
            "created_at": datetime(2026, 9, 16, 9, tzinfo=timezone.utc),
            "approved_at": datetime(2026, 9, 18, 14, tzinfo=timezone.utc),
        }})
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-09-18"
        )
        week = next(row for row in ledger["weeks"] if row["cycle_key"] == "2026-W37")
        self.assertEqual(week["payment_status"], "paid")
        self.assertFalse(week["defaulted"])

    def test_partial_approval_changes_amount_but_never_extends_deadline(self):
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 7, 24, tzinfo=timezone.utc)):
            request = payment_cycle_service.submit_non_working_request({
                "start_date": "2026-07-20", "end_date": "2026-07-25", "reason_code": "low_earnings",
                "explanation": "Low demand", "requested_action": "reduction",
            }, current_user_id=str(self.driver_id), request_key="partial")
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 7, 25, tzinfo=timezone.utc)):
            payment_cycle_service.decide_non_working_request(request["id"], {
                "decision_type": "partial_approval", "approved_amount": 400,
                "revised_deadline": "2026-07-31", "decision_reason": "Half reduction and more time",
            }, current_user_id=str(self.admin_id), decision_key="decision-1")
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-07-27"
        )
        first = next(row for row in ledger["weeks"] if row["cycle_key"] == "2026-W30")
        second = next(row for row in ledger["weeks"] if row["cycle_key"] == "2026-W31")
        self.assertEqual(first["final_due"], 400)
        self.assertEqual(first["effective_deadline"], "2026-07-25")
        self.assertTrue(first["is_overdue"])
        self.assertEqual(first["request_status"], "partially_approved")
        self.assertEqual(second["final_due"], 800)

    def test_historical_admin_exception_keeps_real_record_and_approval_times(self):
        recorded_at = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
        approved_at = datetime(2026, 9, 21, 14, tzinfo=timezone.utc)
        with patch.object(payment_cycle_service, "now_utc", return_value=recorded_at):
            request = payment_cycle_service.submit_non_working_request({
                "selection_type": "whole_week", "start_date": "2026-07-20",
                "reason_code": "vehicle_issue", "explanation": "Historical workshop record verified",
                "requested_action": "full_exemption",
            }, current_user_id=str(self.admin_id), driver_id=str(self.driver_id), entered_by_role="admin", request_key="historical-admin")
        self.assertTrue(request["created_at"].startswith("2026-09-20"))
        self.assertEqual(request["affected_dates"][0], "2026-07-20")
        with patch.object(payment_cycle_service, "now_utc", return_value=approved_at):
            decided = payment_cycle_service.decide_non_working_request(request["id"], {
                "decision_type": "full_exemption", "decision_reason": "Confirmed vehicle unavailable",
            }, current_user_id=str(self.admin_id))
        self.assertTrue(decided["approval_timestamp"].startswith("2026-09-21"))
        self.assertEqual(decided["approver_snapshot"]["full_name"], "Admin")
        self.assertEqual(decided["approver_snapshot"]["role"], "admin")
        self.assertEqual(decided["affected_week_decisions"]["2026-07-20"]["original_amount"], 800)
        self.assertEqual(decided["affected_week_decisions"]["2026-07-20"]["revised_amount_due"], 0)
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-09-21"
        )
        by_start = {week["week_start"]: week for week in ledger["weeks"]}
        self.assertEqual(by_start["2026-07-20"]["payment_status"], "excused_no_payment_due")
        self.assertEqual(by_start["2026-07-20"]["outstanding"], 0)
        self.assertNotIn("2026-W30", ledger["position"]["defaulted_weeks"])
        self.assertEqual(by_start["2026-07-27"]["final_due"], 800)

    def test_overlapping_problem_request_is_rejected_and_idempotent_retry_is_safe(self):
        payload = {"start_date": "2026-07-20", "end_date": "2026-07-25", "reason_code": "illness",
                   "explanation": "Unable to work", "requested_action": "reduction"}
        first = payment_cycle_service.submit_non_working_request(payload, current_user_id=str(self.driver_id), request_key="problem-1")
        retry = payment_cycle_service.submit_non_working_request(payload, current_user_id=str(self.driver_id), request_key="problem-1")
        self.assertEqual(first["id"], retry["id"])
        with self.assertRaisesRegex(Exception, "overlapping request"):
            payment_cycle_service.submit_non_working_request(payload, current_user_id=str(self.driver_id), request_key="problem-2")

    def test_single_multiple_and_whole_week_date_selections_are_structured(self):
        single = payment_cycle_service.submit_non_working_request({
            "selection_type": "single_day", "start_date": "2026-07-20",
            "reason_code": "sick_health", "explanation": "Medical rest", "requested_action": "reduction",
        }, current_user_id=str(self.driver_id), request_key="single")
        multiple = payment_cycle_service.submit_non_working_request({
            "selection_type": "multiple_days", "affected_dates": ["2026-07-27", "2026-07-29"],
            "reason_code": "company_assignment", "explanation": "Assigned to company duty", "requested_action": "full_exemption",
        }, current_user_id=str(self.driver_id), request_key="multiple")
        whole = payment_cycle_service.submit_non_working_request({
            "selection_type": "whole_week", "start_date": "2026-08-03",
            "reason_code": "vehicle_issue", "explanation": "Vehicle in workshop", "requested_action": "full_exemption",
        }, current_user_id=str(self.driver_id), request_key="whole")
        self.assertEqual(single["affected_dates"], ["2026-07-20"])
        self.assertEqual(multiple["affected_dates"], ["2026-07-27", "2026-07-29"])
        self.assertEqual(whole["affected_dates"], [
            "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-08",
        ])

    def test_reduction_preserves_historical_payment_allocation(self):
        payment = self.payment(800, "2026-07-25", allocations=[
            {"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 800},
        ])
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 7, 25, 12, tzinfo=timezone.utc)):
            request = payment_cycle_service.submit_non_working_request({
                "selection_type": "whole_week", "start_date": "2026-07-20",
                "reason_code": "vehicle_issue", "explanation": "Workshop repair",
                "requested_action": "reduction",
            }, current_user_id=str(self.driver_id), request_key="release-credit")
            payment_cycle_service.decide_non_working_request(request["id"], {
                "decision_type": "reduce", "revised_amount_due": 500,
                "decision_reason": "Three affected work days approved",
            }, current_user_id=str(self.admin_id))
        stored = self.db.collections.find_one({"_id": payment["_id"]})
        self.assertEqual(stored["remittance_allocations"][0]["amount"], 800)
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-07-25"
        )
        self.assertEqual(ledger["weeks"][0]["final_due"], 500)
        self.assertEqual(ledger["weeks"][0]["outstanding"], 0)
        self.assertEqual(ledger["position"]["available_credit"], 0)

    def test_exception_preserves_pending_payment_period(self):
        pending = self.payment(800, "2026-07-25", status="pending", allocations=[
            {"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 800},
        ])
        with patch.object(payment_cycle_service, "now_utc", return_value=datetime(2026, 9, 20, 14, tzinfo=timezone.utc)):
            request = payment_cycle_service.submit_non_working_request({
                "selection_type": "whole_week", "start_date": "2026-07-20",
                "reason_code": "company_assignment", "explanation": "Historical company assignment",
                "requested_action": "full_exemption",
            }, current_user_id=str(self.admin_id), driver_id=str(self.driver_id), entered_by_role="admin", request_key="pending-release")
            payment_cycle_service.decide_non_working_request(request["id"], {
                "decision_type": "full_exemption", "decision_reason": "Company duty verified",
                "effective_date": "2026-07-20",
            }, current_user_id=str(self.admin_id))
        stored = self.db.collections.find_one({"_id": pending["_id"]})
        self.assertEqual(stored["remittance_allocations"], [
            {"cycle_key": "2026-W30", "week_start": "2026-07-20", "amount": 800},
        ])
        ledger = payment_cycle_service.build_weekly_ledger(
            self.db.assignments.find_one({"_id": self.assignment_id}), as_of="2026-09-20"
        )
        week = next(row for row in ledger["weeks"] if row["cycle_key"] == "2026-W30")
        self.assertEqual(week["final_due"], 0)
        self.assertEqual(week["pending_total"], 800)
        self.assertEqual(ledger["position"]["pending_confirmation"], 800)

    def test_driver_cannot_open_another_drivers_assignment(self):
        other_driver = ObjectId()
        self.db.users.insert_one({"_id": other_driver, "role": "driver", "status": "active", "full_name": "Other Driver"})
        with self.assertRaisesRegex(Exception, "not found"):
            payment_cycle_service.get_remittance_position(
                current_user_id=str(other_driver), current_role="driver", assignment_id=str(self.assignment_id), as_of="2026-07-25"
            )

    def test_driver_agreement_list_preserves_previous_vehicle_assignment(self):
        old_vehicle = ObjectId(); old_assignment = ObjectId()
        self.db.vehicles.insert_one({"_id": old_vehicle, "registration_number": "OLD-1", "make": "Kia", "model": "Morning"})
        self.db.assignments.insert_one({"_id": old_assignment, "driver_id": self.driver_id, "vehicle_id": old_vehicle,
                                        "start_date": "2026-06-01", "end_date": "2026-07-19", "status": "ended",
                                        "target_enabled": True, "weekly_target": 700.0, "created_at": datetime(2026, 6, 1, tzinfo=timezone.utc)})
        agreements = payment_cycle_service.list_remittance_agreements(driver_id=str(self.driver_id), as_of="2026-07-25")
        self.assertEqual({row["agreement"]["assignment_id"] for row in agreements}, {str(self.assignment_id), str(old_assignment)})


if __name__ == "__main__":
    unittest.main()
