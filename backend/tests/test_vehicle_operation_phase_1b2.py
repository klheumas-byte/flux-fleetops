from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.vehicle_operation_request import serialize_vehicle_operation_request
from services import movement_source_service
from services import fuel_service
from services import stock_transfer_service as stock
from services import vehicle_availability_service as availability
from services import vehicle_movement_service as movement_service
from services import vehicle_operation_request_service as operations
from services import waybill_service
from utils.api_error import ApiError


class Phase1B2Base(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().flux_test
        self.admin_id = ObjectId()
        self.owner_id = ObjectId()
        self.driver_id = ObjectId()
        self.other_driver_id = ObjectId()
        self.vehicle_id = ObjectId()
        self.db.users.insert_many([
            {"_id": self.admin_id, "role": "admin", "status": "active", "full_name": "Admin"},
            {"_id": self.owner_id, "role": "owner", "status": "active", "full_name": "Owner"},
            {"_id": self.driver_id, "role": "driver", "status": "active", "full_name": "Driver", "driver_profile": {"approval_status": "approved"}},
            {"_id": self.other_driver_id, "role": "driver", "status": "active", "full_name": "Other", "driver_profile": {"approval_status": "approved"}},
        ])
        self.db.vehicles.insert_one({"_id": self.vehicle_id, "registration_number": "FLUX-1", "status": "available"})
        self.patches = [
            patch.object(operations, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(stock, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(waybill_service, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(movement_service, "get_collection", side_effect=lambda name: self.db[name]),
            patch.object(movement_source_service, "vehicle_movements_collection", return_value=self.db.vehicle_movements),
            patch.object(operations, "notify_roles"), patch.object(operations, "create_notification"), patch.object(operations, "resolve_action_notifications"),
            patch.object(stock, "notify_roles"), patch.object(stock, "create_notification"), patch.object(stock, "resolve_action_notifications"),
            patch.object(operations, "resolve_vehicle_availability", return_value={"is_available": True, "blocking_reasons": []}),
            patch.object(stock, "resolve_vehicle_availability", return_value={"is_available": True, "blocking_reasons": []}),
            patch.object(movement_service, "resolve_vehicle_availability", return_value={"is_available": True, "blocking_reasons": []}),
            patch("services.movement_custody_service.transfer_movement_custody"),
            patch("services.movement_custody_service.accept_movement_custody"),
            patch("services.movement_custody_service.return_movement_custody"),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def create_request(self, operation_type="administrative_errand", **overrides):
        payload = {
            "operation_type": operation_type,
            "title": "Operational task",
            "purpose": "Company business",
            "origin": "Head Office",
            "destination": "Destination",
            "planned_departure_at": "2026-07-20T09:00:00Z",
            "expected_return_at": "2026-07-20T12:00:00Z",
            **overrides,
        }
        return operations.create_operational_request(payload, current_user_id=str(self.admin_id), current_role="admin")

    def approve_request(self, request_id):
        operations.submit_operational_request(request_id, current_user_id=str(self.admin_id), current_role="admin")
        return operations.approve_operational_request(request_id, current_user_id=str(self.admin_id), current_role="admin")

    def schedule_request(self, request_id, **overrides):
        return operations.schedule_operational_request(request_id, {
            "vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id),
            "planned_departure_at": "2026-07-20T09:00:00Z", "expected_return_at": "2026-07-20T12:00:00Z",
            **overrides,
        }, current_user_id=str(self.admin_id), current_role="admin")


class OperationalRequestTests(Phase1B2Base):
    def awaiting_verification_request(self):
        created = self.create_request("administrative_errand")
        self.approve_request(created["id"])
        self.schedule_request(created["id"])
        request_id = ObjectId(created["id"])
        document = self.db.vehicle_operation_requests.find_one({"_id": request_id})
        movement_id = document["linked_vehicle_movement_id"]
        request_history = [{"status": "awaiting_verification", "source": "operational_request"}]
        request_audit = [{"event": "driver_returned", "source": "operational_request"}]
        movement_history = [{"status": "returned", "source": "vehicle_movement"}]
        movement_audit = [{"event": "physical_return", "source": "vehicle_movement"}]
        self.db.vehicle_operation_requests.update_one(
            {"_id": request_id},
            {"$set": {
                "status": "awaiting_verification",
                "task_confirmation": {"task_completed": True},
                "status_history": request_history,
                "audit_log": request_audit,
            }},
        )
        self.db.vehicle_movements.update_one(
            {"_id": movement_id},
            {"$set": {
                "status": "returned",
                "status_history": movement_history,
                "audit_log": movement_audit,
            }},
        )
        return request_id, movement_id, request_history, request_audit, movement_history, movement_audit

    def test_draft_and_rejected_requests_do_not_create_movements(self):
        created = self.create_request()
        self.assertEqual(created["status"], "draft")
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 0)
        self.approve_request(created["id"])
        operations.reject_operational_request(created["id"], "Not required", current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 0)

    def test_approved_assigned_request_ensures_one_non_revenue_movement(self):
        created = self.create_request("internal_company_delivery")
        self.approve_request(created["id"])
        first = self.schedule_request(created["id"])
        second = self.schedule_request(created["id"])
        movements = list(self.db.vehicle_movements.find({}))
        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0]["source_key"], f"vehicle_operation_request:{created['id']}")
        self.assertEqual(movements[0]["movement_type"], "internal_company_delivery")
        self.assertEqual(movements[0]["financial_class"], "non_revenue")
        self.assertEqual(first["linked_vehicle_movement_id"], second["linked_vehicle_movement_id"])

    def test_wrong_driver_cannot_operate_assigned_request(self):
        created = self.create_request(); self.approve_request(created["id"]); self.schedule_request(created["id"])
        with self.assertRaises(ApiError) as raised:
            operations.acknowledge_operational_request(created["id"], current_user_id=str(self.other_driver_id), current_role="driver")
        self.assertEqual(raised.exception.status_code, 403)

    def test_driver_cannot_approve_request(self):
        created = self.create_request(); operations.submit_operational_request(created["id"], current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError) as raised:
            operations.approve_operational_request(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(raised.exception.status_code, 403)

    def test_administrative_errand_requires_destination_and_creates_no_revenue(self):
        with self.assertRaises(ApiError):
            self.create_request("administrative_errand", destination="")
        created = self.create_request("administrative_errand"); self.approve_request(created["id"]); self.schedule_request(created["id"])
        movement = self.db.vehicle_movements.find_one({})
        self.assertEqual(movement["financial_class"], "non_revenue")
        self.assertNotIn("revenue", movement)

    def test_fuel_visit_requires_fuel_log_or_no_purchase_reason(self):
        created = self.create_request("fuel_station_visit"); self.approve_request(created["id"]); self.schedule_request(created["id"])
        self.db.vehicle_operation_requests.update_one({"_id": ObjectId(created["id"])}, {"$set": {"status": "movement_in_progress"}})
        with self.assertRaises(ApiError):
            operations.confirm_operational_task(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        result = operations.confirm_operational_task(created["id"], {"no_purchase_reason": "Station unavailable"}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(result["no_purchase_reason"], "Station unavailable")

    def test_each_task_confirmation_response_is_json_serializable(self):
        vehicle_type_id = ObjectId()
        self.db.vehicles.update_one(
            {"_id": self.vehicle_id},
            {"$set": {"vehicle_type": vehicle_type_id}},
        )
        cases = (
            ("administrative_errand", {}),
            ("internal_company_delivery", {"receiver_name": "Receiving Officer"}),
            ("fuel_station_visit", {"no_purchase_reason": "Station unavailable"}),
            ("compliance_inspection_visit", {"outcome": "Passed"}),
            ("vehicle_repositioning", {"accepted_by_name": "Branch Officer"}),
        )
        for operation_type, confirmation_payload in cases:
            with self.subTest(operation_type=operation_type):
                related_source_id = ObjectId() if operation_type == "compliance_inspection_visit" else None
                document = {
                    "_id": ObjectId(),
                    "request_id": f"OR-{operation_type}",
                    "operation_type": operation_type,
                    "title": "Operational task",
                    "vehicle_id": self.vehicle_id,
                    "driver_id": self.driver_id,
                    "status": "movement_in_progress",
                }
                if related_source_id:
                    document["related_source_id"] = related_source_id
                self.db.vehicle_operation_requests.insert_one(document)

                result = operations.confirm_operational_task(
                    str(document["_id"]),
                    confirmation_payload,
                    current_user_id=str(self.driver_id),
                    current_role="driver",
                )

                json.dumps(result)
                confirmation = (
                    result.get("receiver_confirmation")
                    or result.get("task_confirmation")
                    or result.get("destination_acceptance")
                )
                self.assertEqual(confirmation["confirmed_by"], str(self.driver_id))
                self.assertEqual(result["vehicle"]["vehicle_type"], str(vehicle_type_id))
                if related_source_id:
                    self.assertEqual(
                        confirmation["compliance_record_id"],
                        str(related_source_id),
                    )

    def test_compliance_link_must_match_scheduled_vehicle(self):
        other_vehicle = ObjectId(); self.db.vehicles.insert_one({"_id": other_vehicle, "status": "available"})
        record_id = self.db.vehicle_compliance_records.insert_one({"vehicle_id": other_vehicle, "status": "expired"}).inserted_id
        created = self.create_request("compliance_inspection_visit", related_source_type="compliance_record", related_source_id=str(record_id))
        self.approve_request(created["id"])
        with self.assertRaises(ApiError) as raised:
            self.schedule_request(created["id"])
        self.assertEqual(raised.exception.status_code, 409)

    def test_reposition_same_location_requires_audited_override(self):
        created = self.create_request("vehicle_repositioning", origin="Head Office", destination="Head Office")
        self.approve_request(created["id"])
        with self.assertRaises(ApiError):
            self.schedule_request(created["id"])
        result = self.schedule_request(created["id"], override_reason="Move between parking zones")
        self.assertEqual(result["status"], "scheduled")

    def test_operations_planner_reassigns_scheduled_request_without_new_movement(self):
        other_vehicle_id = ObjectId()
        self.db.vehicles.insert_one(
            {"_id": other_vehicle_id, "registration_number": "FLUX-2", "status": "available"},
        )
        created = self.create_request()
        self.approve_request(created["id"])
        scheduled = self.schedule_request(created["id"])

        reassigned = operations.schedule_operational_request(
            created["id"],
            {
                "vehicle_id": str(other_vehicle_id),
                "driver_id": str(self.other_driver_id),
                "planned_departure_at": "2026-07-20T10:00:00Z",
                "expected_return_at": "2026-07-20T13:00:00Z",
                "reason": "Operations Planner reassignment",
            },
            current_user_id=str(self.admin_id),
            current_role="admin",
        )

        self.assertEqual(reassigned["vehicle_id"], str(other_vehicle_id))
        self.assertEqual(reassigned["driver_id"], str(self.other_driver_id))
        self.assertEqual(
            reassigned["linked_vehicle_movement_id"],
            scheduled["linked_vehicle_movement_id"],
        )
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 1)
        movement = self.db.vehicle_movements.find_one({})
        self.assertEqual(movement["vehicle_id"], other_vehicle_id)
        self.assertEqual(movement["driver_id"], self.other_driver_id)

    def test_verified_reposition_updates_location_only_after_acceptance(self):
        created = self.create_request("vehicle_repositioning", destination="Branch B"); self.approve_request(created["id"]); self.schedule_request(created["id"])
        request_oid = ObjectId(created["id"])
        self.assertIsNone(self.db.vehicles.find_one({"_id": self.vehicle_id}).get("current_operational_location"))
        self.db.vehicle_operation_requests.update_one({"_id": request_oid}, {"$set": {"status": "awaiting_verification", "destination_acceptance": {"accepted_by_name": "Branch Admin"}}})
        movement_id = self.db.vehicle_operation_requests.find_one({"_id": request_oid})["linked_vehicle_movement_id"]
        self.db.vehicle_movements.update_one({"_id": movement_id}, {"$set": {"status": "returned"}})
        with patch("services.vehicle_movement_service.close_vehicle_movement"):
            operations.verify_operational_request(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(self.db.vehicles.find_one({"_id": self.vehicle_id})["current_operational_location"], "Branch B")

    def test_verify_skips_movement_transition_when_return_closed_first(self):
        request_id, movement_id, request_history, request_audit, movement_history, movement_audit = self.awaiting_verification_request()
        closed_at = operations.now_utc()
        self.db.vehicle_movements.update_one(
            {"_id": movement_id},
            {"$set": {"status": "closed", "closed_at": closed_at}},
        )
        stored_closed_at = self.db.vehicle_movements.find_one(
            {"_id": movement_id},
            {"closed_at": 1},
        )["closed_at"]

        with patch("services.vehicle_movement_service.close_vehicle_movement") as close:
            result = operations.verify_operational_request(
                str(request_id),
                {"notes": "Physical return already reviewed"},
                current_user_id=str(self.admin_id),
                current_role="admin",
            )

        close.assert_not_called()
        self.assertEqual(result["status"], "completed")
        movement = self.db.vehicle_movements.find_one({"_id": movement_id})
        request = self.db.vehicle_operation_requests.find_one({"_id": request_id})
        self.assertEqual(movement["closed_at"], stored_closed_at)
        self.assertEqual(movement["status_history"], movement_history)
        self.assertEqual(movement["audit_log"], movement_audit)
        self.assertEqual(request["status_history"], request_history)
        self.assertEqual(request["audit_log"], request_audit)

    def test_verify_closes_returned_movement_then_completes_request(self):
        request_id, movement_id, *_ = self.awaiting_verification_request()

        result = operations.verify_operational_request(
            str(request_id),
            {},
            current_user_id=str(self.admin_id),
            current_role="admin",
        )

        self.assertEqual(result["status"], "completed")
        movement = self.db.vehicle_movements.find_one({"_id": movement_id})
        self.assertEqual(movement["status"], "closed")
        self.assertEqual(movement["closed_by"], self.admin_id)
        self.assertIsNotNone(movement.get("closed_at"))

    def test_repeated_verify_does_not_duplicate_completion_or_movement(self):
        request_id, movement_id, *_ = self.awaiting_verification_request()
        first = operations.verify_operational_request(
            str(request_id),
            {},
            current_user_id=str(self.admin_id),
            current_role="admin",
        )
        request_after_first = self.db.vehicle_operation_requests.find_one(
            {"_id": request_id},
        )
        movement_after_first = self.db.vehicle_movements.find_one({"_id": movement_id})
        second = operations.verify_operational_request(
            str(request_id),
            {},
            current_user_id=str(self.admin_id),
            current_role="admin",
        )
        request_after_second = self.db.vehicle_operation_requests.find_one(
            {"_id": request_id},
        )
        movement_after_second = self.db.vehicle_movements.find_one({"_id": movement_id})

        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        self.assertEqual(
            request_after_first["verified_at"],
            request_after_second["verified_at"],
        )
        self.assertEqual(first["version"], second["version"])
        self.assertEqual(
            movement_after_first["closed_at"],
            movement_after_second["closed_at"],
        )
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 1)
        self.assertEqual(self.db.vehicle_operation_requests.count_documents({}), 1)

    def test_verify_missing_linked_movement_does_not_create_replacement(self):
        request_id, movement_id, *_ = self.awaiting_verification_request()
        self.db.vehicle_movements.delete_one({"_id": movement_id})

        with self.assertRaises(ApiError) as raised:
            operations.verify_operational_request(
                str(request_id),
                {},
                current_user_id=str(self.admin_id),
                current_role="admin",
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 0)
        request = self.db.vehicle_operation_requests.find_one({"_id": request_id})
        self.assertEqual(request["status"], "awaiting_verification")

    def test_legacy_request_serializes_without_new_fields(self):
        payload = serialize_vehicle_operation_request({"_id": ObjectId(), "request_id": "LEGACY", "status": "completed"})
        self.assertEqual(payload["request_id"], "LEGACY")
        self.assertEqual(payload["planned_stops"], [])
        self.assertEqual(payload["version"], 1)


class StockTransferTests(Phase1B2Base):
    def recipient(self):
        return {"full_name": "Receiving Clerk", "role": "Stores", "primary_phone": "+233 20 123 4567"}

    def create_transfer(self, items=None):
        return stock.create_stock_transfer({"sending_location": "Warehouse A", "receiving_location": "Warehouse B", "recipient": self.recipient(), "transfer_items": items or [{"item_id": "OIL", "quantity": 10}]}, current_user_id=str(self.admin_id), current_role="admin")

    def supplier_pickup_payload(self, **overrides):
        payload = {
            "operation_type": "supplier_pickup",
            "supplier": {
                "supplier_name": "Parts Supplier",
                "contact_person": "Ama Supplier",
                "primary_phone": "+233 20 111 2222",
                "pickup_address": "Supplier Yard, Accra",
                "pickup_instructions": "Use gate 2",
            },
            "receiving_location": "Warehouse B",
            "recipient": {"full_name": "Receiving Clerk", "primary_phone": "+233 20 123 4567", "role": "Stores"},
            "supplier_reference": "PO-1001",
            "requested_date": "2026-07-20",
            "transfer_items": [{"item_id": "FILTER", "name": "Oil filter", "quantity": 4, "unit": "unit"}],
        }
        payload.update(overrides)
        return payload

    def test_operations_planner_reassigns_stock_transfer_without_new_records(self):
        other_vehicle_id = ObjectId()
        self.db.vehicles.insert_one(
            {"_id": other_vehicle_id, "registration_number": "FLUX-2", "status": "available"},
        )
        created = self.create_transfer()
        stock.submit_stock_transfer(
            created["id"],
            current_user_id=str(self.admin_id),
            current_role="admin",
        )
        stock.approve_stock_transfer(
            created["id"],
            current_user_id=str(self.admin_id),
            current_role="admin",
        )
        scheduled = stock.schedule_stock_transfer(
            created["id"],
            {
                "vehicle_id": str(self.vehicle_id),
                "driver_id": str(self.driver_id),
                "scheduled_at": "2026-07-20T09:00:00Z",
            },
            current_user_id=str(self.admin_id),
            current_role="admin",
        )

        reassigned = stock.schedule_stock_transfer(
            created["id"],
            {
                "vehicle_id": str(other_vehicle_id),
                "driver_id": str(self.other_driver_id),
                "scheduled_at": "2026-07-20T10:00:00Z",
                "reason": "Operations Planner reassignment",
            },
            current_user_id=str(self.admin_id),
            current_role="admin",
        )

        self.assertEqual(reassigned["vehicle_id"], str(other_vehicle_id))
        self.assertEqual(reassigned["driver_id"], str(self.other_driver_id))
        self.assertEqual(
            reassigned["linked_vehicle_movement_id"],
            scheduled["linked_vehicle_movement_id"],
        )
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 1)
        self.assertEqual(self.db.waybills.count_documents({}), 1)

    def create_supplier_pickup(self, **overrides):
        return stock.create_stock_transfer(self.supplier_pickup_payload(**overrides), current_user_id=str(self.admin_id), current_role="admin")

    def approve_transfer(self, transfer_id):
        stock.submit_stock_transfer(transfer_id, current_user_id=str(self.admin_id), current_role="admin")
        return stock.approve_stock_transfer(transfer_id, current_user_id=str(self.admin_id), current_role="admin")

    def deliver_transfer(self, items=None):
        created = self.create_transfer(items); self.approve_transfer(created["id"])
        scheduled = stock.schedule_stock_transfer(
            created["id"], {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        return created, scheduled

    def report_single_exception(self, exception_type):
        created, scheduled = self.deliver_transfer()
        received = 8 if exception_type == "missing" else 12 if exception_type == "excess" else 10
        condition = exception_type if exception_type in {"damaged", "wrong_item"} else "correct"
        payload = {
            "items": [{"item_id": "OIL", "received_quantity": received, "condition": condition, "notes": f"{exception_type} delivery", "photos": []}],
            "actual_receiver": {"full_name": "Receiver", "primary_contact": "+233 20 000 0000", "initials": "RX", "acknowledged": True},
        }
        stock.report_stock_transfer_delivery_exception(created["id"], payload, current_user_id=str(self.driver_id), current_role="driver")
        return created, scheduled

    def test_approval_reserves_but_does_not_create_movement_or_receipt(self):
        created = self.create_transfer(); approved = self.approve_transfer(created["id"])
        self.assertEqual(approved["reservation_status"], "reserved")
        self.assertEqual(approved["receiving_status"], "not_received")
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 0)

    def test_repeated_scheduling_uses_one_stock_transfer_movement(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        payload = {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"}
        first = stock.schedule_stock_transfer(created["id"], payload, current_user_id=str(self.admin_id), current_role="admin")
        second = stock.schedule_stock_transfer(created["id"], payload, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(first["linked_vehicle_movement_id"], second["linked_vehicle_movement_id"])
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 1)
        self.assertEqual(first["linked_waybill_id"], second["linked_waybill_id"])
        self.assertEqual(self.db.waybills.count_documents({}), 1)
        self.assertEqual(self.db.waybills.find_one({})["status"], "approved")
        notification = stock.create_notification.call_args
        self.assertEqual(notification.args[0], self.driver_id)
        self.assertEqual(notification.kwargs["reference_type"], "stock_transfer")
        self.assertEqual(notification.kwargs["reference_id"], ObjectId(first["id"]))
        self.assertEqual(notification.kwargs["action_url"], "my-operational-tasks")
        self.assertEqual(notification.kwargs["action_label"], "Accept Transfer")
        self.assertEqual(notification.kwargs["module"], "my-operational-tasks")

    def test_supplier_pickup_phase_one_shared_engine(self):
        created = self.create_supplier_pickup()
        self.assertEqual(created["operation_type"], "supplier_pickup")
        self.assertEqual(created["origin_type"], "external_supplier")
        self.assertEqual(created["supplier"]["supplier_name"], "Parts Supplier")
        self.assertEqual(created["sending_location"], "Supplier Yard, Accra")
        self.assertEqual(created["recipient"]["full_name"], "Receiving Clerk")
        self.assertEqual(created["transfer_items"][0]["name"], "Oil filter")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["audit_log"][0]["details"]["operation_type"], "supplier_pickup")

        approved = self.approve_transfer(created["id"])
        self.assertEqual(approved["status"], "approved")
        assigned = stock.schedule_stock_transfer(
            created["id"],
            {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        self.assertEqual(assigned["status"], "scheduled")
        self.assertEqual(self.db.vehicle_movements.count_documents({"source_type": "supplier_pickup"}), 1)
        self.assertEqual(self.db.waybills.count_documents({"source_type": "supplier_pickup"}), 0)
        movement = self.db.vehicle_movements.find_one({"source_type": "supplier_pickup"})
        self.assertEqual(movement["movement_type"], "supplier_pickup")
        task = self.db.operation_assignments.find_one({"source_type": "supplier_pickup"})
        self.assertEqual(task["supplier"]["supplier_name"], "Parts Supplier")
        self.assertEqual(task["pickup_location"], "Supplier Yard, Accra")
        self.assertEqual(task["destination"], "Warehouse B")
        self.assertEqual(task["requested_items"][0]["quantity"], 4)
        self.assertIsNone(task["waybill_id"])

        driver_list = stock.list_stock_transfers(current_user_id=str(self.driver_id), current_role="driver", operation_type="supplier_pickup")
        self.assertEqual(driver_list["transfers"][0]["id"], created["id"])
        accepted = stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(accepted["workflow_stage"], "driver_accepted")
        self.assertIsNone(accepted["linked_waybill_id"])
        arrived = stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(arrived["workflow_stage"], "arrived_at_supplier")
        self.assertIsNotNone(arrived["supplier_arrived_at"])
        refreshed_tasks = stock.list_stock_transfers(
            current_user_id=str(self.driver_id), current_role="driver", operation_type="supplier_pickup", active_tasks=True
        )["transfers"]
        self.assertEqual(len(refreshed_tasks), 1)
        self.assertEqual(refreshed_tasks[0]["workflow_stage"], "arrived_at_supplier")
        self.assertIsNotNone(refreshed_tasks[0]["supplier_arrived_at"])
        confirmed = stock.confirm_supplier_pickup(
            created["id"],
            {"items": [{"item_id": accepted["transfer_items"][0]["item_id"], "available_quantity": 4, "collected_quantity": 4}]},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(confirmed["workflow_stage"], "pickup_confirmed")
        self.assertEqual(confirmed["pickup_confirmation"]["items"][0]["shortfall_quantity"], 0)
        self.assertEqual(self.db.supplier_shortfalls.count_documents({}), 0)
        waybill = self.db.waybills.find_one({"source_type": "supplier_pickup"})
        self.assertEqual(self.db.waybills.count_documents({"source_type": "supplier_pickup"}), 1)
        self.assertEqual(waybill["status"], "driver_confirmed")
        self.assertEqual(waybill["items"][0]["expected_quantity"], 4)
        self.assertEqual(waybill["items"][0]["collected_quantity"], 4)
        self.assertEqual(waybill["recipient"]["full_name"], "Receiving Clerk")
        self.assertEqual(self.db.operation_assignments.find_one({"source_type": "supplier_pickup"})["waybill_id"], waybill["_id"])
        with self.assertRaises(ApiError) as read_only_waybill:
            waybill_service.transition_waybill(waybill["_id"], "loaded", {"quantities": []}, current_user_id=str(self.driver_id), current_role="driver", collection=self.db.waybills, enforce_source_owner=True)
        self.assertEqual(read_only_waybill.exception.status_code, 409)
        loaded = stock.release_stock_transfer(
            created["id"],
            {},
            current_user_id=str(self.driver_id), current_role="driver",
        )
        self.assertEqual(loaded["workflow_stage"], "loaded")
        self.assertEqual(loaded["loaded_quantities"][0]["quantity"], 4)
        self.assertEqual(self.db.waybills.find_one({"_id": ObjectId(loaded["linked_waybill_id"])})["status"], "loaded")
        custody = self.db.stock_transfers.find_one({"_id": ObjectId(created["id"])})["custody_history"]
        self.assertEqual(custody[0]["event"], "supplier_to_driver")
        started = stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(started["workflow_stage"], "in_transit")
        self.assertEqual(self.db.operation_assignments.find_one({"source_type": "supplier_pickup"})["status"], "in_transit")
        delivered = stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(delivered["workflow_stage"], "delivered")
        self.assertEqual(self.db.operation_assignments.find_one({"source_type": "supplier_pickup"})["status"], "delivered")
        repeated_supplier_arrival = stock.mark_supplier_pickup_arrived(
            created["id"], {}, current_user_id=str(self.driver_id), current_role="driver"
        )
        self.assertEqual(repeated_supplier_arrival["workflow_stage"], "delivered")
        active_after_delivery = stock.list_stock_transfers(
            current_user_id=str(self.driver_id), current_role="driver", operation_type="supplier_pickup", active_tasks=True
        )["transfers"]
        self.assertEqual([item["id"] for item in active_after_delivery], [created["id"]])
        completed = stock.verify_stock_transfer_delivery(created["id"], {
            "actual_receiver": {"full_name": "Receiving Clerk", "primary_contact": "+233 20 123 4567", "initials": "RC", "acknowledged": True},
            "items": [{"item_id": confirmed["pickup_confirmation"]["items"][0]["item_id"], "expected_quantity": 4, "received_quantity": 4, "condition": "correct"}],
        }, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["actual_receiver"]["full_name"], "Receiving Clerk")
        self.assertEqual(self.db.operation_assignments.find_one({"source_type": "supplier_pickup"})["status"], "completed")
        self.assertEqual(stock.list_stock_transfers(
            current_user_id=str(self.driver_id), current_role="driver", operation_type="supplier_pickup", active_tasks=True
        )["transfers"], [])

    def test_supplier_pickup_phase_two_approve_assign_and_confirm(self):
        created = self.create_supplier_pickup(recipient=None)
        stock.submit_stock_transfer(created["id"], current_user_id=str(self.admin_id), current_role="admin")
        approved = stock.approve_stock_transfer(created["id"], current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(approved["workflow_stage"], "approved")
        self.assertEqual(approved["approved_by"], str(self.admin_id))
        self.assertIsNotNone(approved["approved_at"])

        assigned = stock.schedule_stock_transfer(
            created["id"],
            {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id),
            current_role="admin",
        )
        self.assertEqual(assigned["workflow_stage"], "driver_assigned")
        self.assertIsNotNone(assigned["linked_assignment_id"])
        self.assertIsNotNone(assigned["linked_vehicle_movement_id"])
        self.assertIsNone(assigned["linked_waybill_id"])
        self.assertEqual(self.db.operation_assignments.count_documents({}), 1)
        self.assertEqual(self.db.vehicle_movements.count_documents({"source_type": "supplier_pickup"}), 1)
        self.assertEqual(self.db.waybills.count_documents({"source_type": "supplier_pickup"}), 0)
        assignment = self.db.operation_assignments.find_one({})
        self.assertEqual(assignment["driver_id"], self.driver_id)
        self.assertEqual(assignment["vehicle_id"], self.vehicle_id)
        self.assertEqual(assignment["audit_log"][0]["event"], "pickup_assignment_created")

        repeated = stock.schedule_stock_transfer(
            created["id"],
            {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id),
            current_role="admin",
        )
        self.assertEqual(repeated["linked_assignment_id"], assigned["linked_assignment_id"])
        self.assertEqual(self.db.operation_assignments.count_documents({}), 1)
        self.assertEqual(self.db.vehicle_movements.count_documents({"source_type": "supplier_pickup"}), 1)
        self.assertEqual(self.db.waybills.count_documents({"source_type": "supplier_pickup"}), 0)

        my_tasks = stock.list_stock_transfers(
            current_user_id=str(self.driver_id), current_role="driver", operation_type="supplier_pickup", active_tasks=True
        )["transfers"]
        other_tasks = stock.list_stock_transfers(
            current_user_id=str(self.other_driver_id), current_role="driver", operation_type="supplier_pickup", active_tasks=True
        )["transfers"]
        self.assertEqual([item["id"] for item in my_tasks], [created["id"]])
        self.assertEqual(other_tasks, [])
        self.assertEqual(my_tasks[0]["vehicle"]["registration_number"], "FLUX-1")
        self.assertEqual(my_tasks[0]["transfer_items"][0]["name"], "Oil filter")
        self.assertIsNone((self.db.users.find_one({"_id": self.driver_id}).get("driver_profile") or {}).get("assigned_vehicle_id"))
        notification = stock.create_notification.call_args
        self.assertEqual(notification.kwargs["reference_type"], "supplier_pickup")
        self.assertEqual(str(notification.kwargs["reference_id"]), my_tasks[0]["id"])

        with patch("services.movement_custody_service.accept_movement_custody") as accept_custody:
            confirmed = stock.acknowledge_stock_transfer(
                created["id"], current_user_id=str(self.driver_id), current_role="driver"
            )
        self.assertEqual(confirmed["workflow_stage"], "driver_accepted")
        accept_custody.assert_called_once()
        assignment = self.db.operation_assignments.find_one({"_id": ObjectId(assigned["linked_assignment_id"])})
        self.assertEqual(assignment["status"], "driver_accepted")
        self.assertEqual(assignment["confirmed_by"], self.driver_id)
        self.assertEqual(assignment["audit_log"][-1]["event"], "driver_accepted")
        accepted_tasks = stock.list_stock_transfers(
            current_user_id=str(self.driver_id), current_role="driver", operation_type="supplier_pickup", active_tasks=True
        )["transfers"]
        self.assertEqual(len(accepted_tasks), 1)
        self.assertEqual(accepted_tasks[0]["workflow_stage"], "driver_accepted")

    def test_active_driver_tasks_force_supplier_pickup_operation_type(self):
        pickup = self.create_supplier_pickup(); self.approve_transfer(pickup["id"])
        stock.schedule_stock_transfer(
            pickup["id"],
            {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        self.db.stock_transfers.insert_one({
            "transfer_id": "ST-REGRESSION", "operation_type": "stock_transfer",
            "driver_id": self.driver_id, "vehicle_id": self.vehicle_id, "status": "scheduled",
        })

        tasks = stock.list_stock_transfers(
            current_user_id=str(self.driver_id), current_role="driver", active_tasks=True
        )["transfers"]

        self.assertEqual([item["id"] for item in tasks], [pickup["id"]])
        self.assertEqual(tasks[0]["operation_type"], "supplier_pickup")

    def test_supplier_pickup_assignment_conflicts_and_authorized_reassignment(self):
        other_vehicle_id = self.db.vehicles.insert_one(
            {"registration_number": "FLUX-2", "status": "available"}
        ).inserted_id
        created = self.create_supplier_pickup()
        self.approve_transfer(created["id"])
        first = stock.schedule_stock_transfer(
            created["id"],
            {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id),
            current_role="admin",
        )

        conflicting = self.create_supplier_pickup(supplier_reference="PO-SECOND")
        self.approve_transfer(conflicting["id"])
        with self.assertRaises(ApiError) as driver_conflict:
            stock.schedule_stock_transfer(
                conflicting["id"],
                {"vehicle_id": str(other_vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T10:00:00Z"},
                current_user_id=str(self.admin_id),
                current_role="admin",
            )
        self.assertEqual(driver_conflict.exception.status_code, 409)

        reassigned = stock.schedule_stock_transfer(
            created["id"],
            {"vehicle_id": str(other_vehicle_id), "driver_id": str(self.other_driver_id), "scheduled_at": "2026-07-20T10:00:00Z"},
            current_user_id=str(self.admin_id),
            current_role="admin",
        )
        self.assertEqual(reassigned["linked_assignment_id"], first["linked_assignment_id"])
        self.assertEqual(reassigned["linked_vehicle_movement_id"], first["linked_vehicle_movement_id"])
        self.assertEqual(reassigned["linked_waybill_id"], first["linked_waybill_id"])
        self.assertEqual(self.db.operation_assignments.count_documents({}), 1)
        self.assertEqual(self.db.vehicle_movements.count_documents({"source_type": "supplier_pickup"}), 1)
        self.assertEqual(self.db.waybills.count_documents({"source_type": "supplier_pickup"}), 0)
        self.assertEqual(self.db.operation_assignments.find_one({})["audit_log"][-1]["event"], "pickup_assignment_reassigned")

        with self.assertRaises(ApiError) as unauthorized:
            stock.schedule_stock_transfer(
                created["id"],
                {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T11:00:00Z"},
                current_user_id=str(self.driver_id),
                current_role="driver",
            )
        self.assertEqual(unauthorized.exception.status_code, 403)

        stock.acknowledge_stock_transfer(
            created["id"], current_user_id=str(self.other_driver_id), current_role="driver"
        )
        with self.assertRaises(ApiError) as after_confirmation:
            stock.schedule_stock_transfer(
                created["id"],
                {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T11:00:00Z"},
                current_user_id=str(self.admin_id),
                current_role="admin",
            )
        self.assertEqual(after_confirmation.exception.status_code, 409)

    def test_supplier_pickup_quantity_permissions_shortfall_and_duplicate_prevention(self):
        created = self.create_supplier_pickup(); self.approve_transfer(created["id"])
        stock.schedule_stock_transfer(created["id"], {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"}, current_user_id=str(self.admin_id), current_role="admin")
        stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")

        item_id = created["transfer_items"][0]["item_id"]
        with self.assertRaises(ApiError) as admin_confirmation:
            stock.confirm_supplier_pickup(created["id"], {"items": [{"item_id": item_id, "collected_quantity": 2, "shortfall_reason": "Two unavailable"}]}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(admin_confirmation.exception.status_code, 403)
        with self.assertRaises(ApiError) as raised:
            stock.confirm_supplier_pickup(created["id"], {"items": [{"item_id": item_id, "collected_quantity": 5, "shortfall_reason": "Invalid"}]}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(raised.exception.status_code, 400)
        with self.assertRaises(ApiError) as missing_reason:
            stock.confirm_supplier_pickup(created["id"], {"items": [{"item_id": item_id, "collected_quantity": 2}]}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(missing_reason.exception.status_code, 400)

        confirmed = stock.confirm_supplier_pickup(created["id"], {"items": [{"item_id": item_id, "collected_quantity": 2, "shortfall_reason": "Two unavailable"}]}, current_user_id=str(self.driver_id), current_role="driver")
        repeated = stock.confirm_supplier_pickup(created["id"], {"items": [{"item_id": item_id, "collected_quantity": 2, "shortfall_reason": "Two unavailable"}]}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(confirmed["workflow_stage"], "pickup_confirmed")
        self.assertEqual(confirmed["pickup_confirmation"]["items"][0]["shortfall_quantity"], 2)
        self.assertEqual(confirmed["supplier_shortfall_ids"], repeated["supplier_shortfall_ids"])
        self.assertEqual(self.db.supplier_shortfalls.count_documents({}), 1)

        with self.assertRaises(ApiError) as admin_loaded:
            stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(admin_loaded.exception.status_code, 403)
        loaded = stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(loaded["loaded_quantities"][0]["quantity"], 2)
        started = stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(started["workflow_stage"], "in_transit")

    def test_supplier_pickup_validation_and_duplicate_prevention(self):
        with self.assertRaises(ApiError):
            self.create_supplier_pickup(supplier={**self.supplier_pickup_payload()["supplier"], "primary_phone": "bad"})
        payload = self.supplier_pickup_payload(idempotency_key="supplier-pickup-key")
        first = stock.create_stock_transfer(payload, current_user_id=str(self.admin_id), current_role="admin")
        second = stock.create_stock_transfer(payload, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(first["id"], second["id"])
        with self.assertRaises(ApiError) as raised:
            stock.create_stock_transfer({**payload, "receiving_location": "Warehouse C"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.db.stock_transfers.count_documents({"operation_type": "supplier_pickup"}), 1)

    def test_supplier_pickup_does_not_require_sending_location_or_recipient(self):
        payload = self.supplier_pickup_payload()
        payload.pop("recipient")

        created = stock.create_stock_transfer(
            payload,
            current_user_id=str(self.admin_id),
            current_role="admin",
        )

        self.assertEqual(created["sending_location"], payload["supplier"]["pickup_address"])
        self.assertIsNone(created["recipient"])

    def test_stock_transfer_still_requires_sending_location_and_recipient(self):
        with self.assertRaises(ApiError) as missing_origin:
            stock.create_stock_transfer(
                {"receiving_location": "Warehouse B", "recipient": self.recipient(), "transfer_items": [{"item_id": "OIL", "quantity": 10}]},
                current_user_id=str(self.admin_id),
                current_role="admin",
            )
        self.assertEqual(str(missing_origin.exception), "sending_location is required.")

        with self.assertRaises(ApiError) as missing_recipient:
            stock.create_stock_transfer(
                {"sending_location": "Warehouse A", "receiving_location": "Warehouse B", "transfer_items": [{"item_id": "OIL", "quantity": 10}]},
                current_user_id=str(self.admin_id),
                current_role="admin",
            )
        self.assertEqual(str(missing_recipient.exception), "recipient must be an object.")

    def test_scheduling_retry_recovers_after_waybill_creation_failure(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        payload = {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-22T21:00:00Z"}
        with patch("services.waybill_service.ensure_waybill_for_source", side_effect=RuntimeError("simulated Waybill failure")):
            with self.assertRaises(RuntimeError):
                stock.schedule_stock_transfer(created["id"], payload, current_user_id=str(self.admin_id), current_role="admin")
        partial = self.db.stock_transfers.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(partial["status"], "approved")
        self.assertIsNotNone(partial.get("linked_vehicle_movement_id"))
        recovered = stock.schedule_stock_transfer(created["id"], payload, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(recovered["status"], "scheduled")
        self.assertEqual(self.db.vehicle_movements.count_documents({}), 1)
        self.assertEqual(self.db.waybills.count_documents({}), 1)

    def test_driver_acknowledgement_is_required_before_stock_release(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        payload = {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"}
        stock.schedule_stock_transfer(created["id"], payload, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError):
            stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        acknowledged = stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.assertIsNotNone(acknowledged["acknowledged_at"])
        waybill = self.db.waybills.find_one({"_id": ObjectId(acknowledged["linked_waybill_id"])})
        self.assertEqual(waybill["status"], "driver_confirmed")
        self.assertEqual(waybill["confirmations"][0]["confirmed_by"], self.driver_id)
        self.assertEqual(waybill["confirmations"][0]["confirmed_by_name"], "Driver")
        self.assertEqual(waybill["custody_events"][0]["to"], str(self.driver_id))
        self.assertEqual(waybill["custody_events"][0]["to_name"], "Driver")

        repeated = stock.acknowledge_stock_transfer(
            created["id"], current_user_id=str(self.driver_id), current_role="driver"
        )
        repeated_waybill = self.db.waybills.find_one({"_id": ObjectId(repeated["linked_waybill_id"])})
        self.assertEqual(len(repeated_waybill["confirmations"]), 1)
        self.assertEqual(len(repeated_waybill["custody_events"]), 1)
        self.assertEqual(
            len([entry for entry in repeated_waybill["audit_log"] if entry["event"] == "status_driver_confirmed"]),
            1,
        )

    def test_movement_arrival_does_not_silently_receive_inventory(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        self.db.stock_transfers.update_one({"_id": ObjectId(created["id"])}, {"$set": {"status": "awaiting_receipt", "receiving_status": "awaiting_confirmation"}})
        document = self.db.stock_transfers.find_one({"_id": ObjectId(created["id"])})
        self.assertEqual(document["receiving_status"], "awaiting_confirmation")
        self.assertEqual(document["received_items"], [])

    def test_quantity_variance_requires_resolution_before_completion(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        transfer_oid = ObjectId(created["id"]); movement_id = ObjectId()
        self.db.vehicle_movements.insert_one({"_id": movement_id, "status": "returned", "vehicle_id": self.vehicle_id})
        self.db.stock_transfers.update_one({"_id": transfer_oid}, {"$set": {"status": "awaiting_receipt", "linked_vehicle_movement_id": movement_id, "recipient": None}})
        received = stock.receive_stock_transfer(created["id"], {"received_items": [{"item_id": "OIL", "quantity": 8}]}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(received["quantity_variance"][0]["difference"], -2)
        with self.assertRaises(ApiError):
            stock.complete_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        with patch("services.vehicle_movement_service.close_vehicle_movement"):
            completed = stock.complete_stock_transfer(created["id"], {"variance_resolution": "Shortage accepted and escalated"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.db.stock_transfers.find_one({"_id": transfer_oid})["inventory_posting_status"], "awaiting_external_inventory_posting")

    def test_stock_transfer_lifecycle_keeps_linked_waybill_in_sync(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        scheduled = stock.schedule_stock_transfer(
            created["id"],
            {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        with (
            patch("services.vehicle_movement_service.check_out_vehicle_movement"),
            patch("services.vehicle_movement_service.start_vehicle_movement"),
            patch("services.vehicle_movement_service.return_vehicle_movement"),
            patch("services.vehicle_movement_service.close_vehicle_movement"),
        ):
            stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
            stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
            stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
            self.db.stock_transfers.update_one({"_id": ObjectId(created["id"])}, {"$set": {"recipient": None}})
            stock.receive_stock_transfer(created["id"], {"received_items": [{"item_id": "OIL", "quantity": 8}], "receiver": "Warehouse Clerk"}, current_user_id=str(self.admin_id), current_role="admin")
            stock.complete_stock_transfer(created["id"], {"variance_resolution": "Shortage accepted"}, current_user_id=str(self.admin_id), current_role="admin")

        waybill = self.db.waybills.find_one({"_id": ObjectId(scheduled["linked_waybill_id"])})
        self.assertEqual(waybill["status"], "completed")
        self.assertEqual(waybill["items"][0]["variance"], -2)
        self.assertEqual(waybill["variance_review"]["resolution"], "Shortage accepted")

    def test_cancel_releases_reservation(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        cancelled = stock.cancel_stock_transfer(created["id"], {"reason": "No longer required"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(cancelled["reservation_status"], "released")

    def test_create_idempotency_prevents_duplicate_transfers(self):
        payload = {
            "sending_location": "Warehouse A", "receiving_location": "Warehouse B",
            "recipient": self.recipient(),
            "transfer_items": [{"item_id": "OIL", "quantity": 10}],
            "idempotency_key": "warehouse-a-oil-20260720",
        }
        first = stock.create_stock_transfer(payload, current_user_id=str(self.admin_id), current_role="admin")
        second = stock.create_stock_transfer(payload, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.db.stock_transfers.count_documents({}), 1)
        with self.assertRaises(ApiError) as raised:
            stock.create_stock_transfer({**payload, "receiving_location": "Warehouse C"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 409)

    def test_new_transfers_without_idempotency_keys_do_not_false_match(self):
        payload = {
            "sending_location": "Warehouse A", "receiving_location": "Warehouse B",
            "recipient": self.recipient(),
            "transfer_items": [{"item_id": "OIL", "quantity": 10}],
        }
        first = stock.create_stock_transfer(payload, current_user_id=str(self.admin_id), current_role="admin")
        second = stock.create_stock_transfer(payload, current_user_id=str(self.admin_id), current_role="admin")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.db.stock_transfers.count_documents({}), 2)
        self.assertEqual(self.db.stock_transfers.count_documents({"idempotency_key": {"$exists": False}}), 2)

    def test_phase4_stage_mapping_and_loaded_quantities(self):
        created = self.create_transfer()
        self.assertEqual(created["workflow_stage"], "draft")
        approved = self.approve_transfer(created["id"])
        self.assertEqual(approved["workflow_stage"], "approved")
        assigned = stock.schedule_stock_transfer(created["id"], {
            "vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id),
            "scheduled_at": "2026-07-20T09:00:00Z",
        }, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(assigned["workflow_stage"], "driver_assigned")
        confirmed = stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(confirmed["workflow_stage"], "waybill_confirmed")
        with patch("services.vehicle_movement_service.check_out_vehicle_movement"):
            loaded = stock.release_stock_transfer(created["id"], {
                "loaded_quantities": [{"item_id": "OIL", "quantity": 9}],
            }, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(loaded["workflow_stage"], "loaded")
        waybill = self.db.waybills.find_one({"_id": ObjectId(loaded["linked_waybill_id"])})
        self.assertEqual(waybill["items"][0]["loaded_quantity"], 9)

    def test_destination_receipt_is_authenticated_and_variance_is_explicit(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        stock.schedule_stock_transfer(created["id"], {
            "vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id),
            "scheduled_at": "2026-07-20T09:00:00Z",
        }, current_user_id=str(self.admin_id), current_role="admin")
        stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        with (
            patch("services.vehicle_movement_service.check_out_vehicle_movement"),
            patch("services.vehicle_movement_service.start_vehicle_movement"),
            patch("services.vehicle_movement_service.return_vehicle_movement"),
        ):
            stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
            stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
            stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.db.stock_transfers.update_one({"_id": ObjectId(created["id"])}, {"$set": {"recipient": None}})
        received = stock.receive_stock_transfer(created["id"], {
            "received_items": [{"item_id": "OIL", "quantity": 8}], "receiver": "Warehouse Clerk",
        }, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(received["workflow_stage"], "variance")
        waybill = self.db.waybills.find_one({"_id": ObjectId(received["linked_waybill_id"])})
        receipt = [item for item in waybill["confirmations"] if item.get("confirmation_type") == "destination_receipt"][0]
        self.assertEqual(receipt["confirmed_by"], self.admin_id)
        self.assertTrue(receipt["immutable"])
        reviewed = stock.review_stock_transfer_variance(created["id"], {"resolution": "Accepted shortage"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(reviewed["variance_review"]["resolution"], "Accepted shortage")

    def test_wrong_driver_cannot_access_or_acknowledge_transfer(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        stock.schedule_stock_transfer(created["id"], {
            "vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id),
            "scheduled_at": "2026-07-20T09:00:00Z",
        }, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError) as raised:
            stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.other_driver_id), current_role="driver")
        self.assertEqual(raised.exception.status_code, 403)

    def test_creation_supports_multiple_items_and_new_request_fields(self):
        created = stock.create_stock_transfer({
            "sending_location": "Warehouse A",
            "receiving_location": "Warehouse B",
            "requested_date": "2026-07-25",
            "purpose": "Replenish branch stock",
            "notes": "Keep cartons dry",
            "recipient": self.recipient(),
            "transfer_items": [
                {"item_id": "OIL", "name": "Engine oil", "quantity": 10},
                {"item_id": "FILTER", "name": "Oil filter", "quantity": 6},
            ],
        }, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["item_count"], 2)
        self.assertEqual(len(created["transfer_items"]), 2)
        self.assertEqual(created["requested_date"], "2026-07-25")
        self.assertEqual(created["purpose"], "Replenish branch stock")

    def test_creation_rejects_duplicate_items_case_insensitively(self):
        with self.assertRaises(ApiError) as raised:
            stock.create_stock_transfer({
                "sending_location": "Warehouse A",
                "receiving_location": "Warehouse B",
                "recipient": self.recipient(),
                "transfer_items": [
                    {"item_id": "OIL", "quantity": 10},
                    {"item_id": "oil", "quantity": 2},
                ],
            }, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 400)

    def test_creation_does_not_require_sku_or_item_id(self):
        created = stock.create_stock_transfer({
            "sending_location": "Warehouse A",
            "receiving_location": "Warehouse B",
            "recipient": self.recipient(),
            "transfer_items": [
                {"name": "Engine oil", "quantity": 10},
                {"name": "Oil filter", "quantity": 6},
            ],
        }, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual([item["name"] for item in created["transfer_items"]], ["Engine oil", "Oil filter"])
        self.assertEqual(created["transfer_items"][0]["item_id"], "Engine oil")

    def test_draft_can_be_saved_then_submitted_idempotently(self):
        created = self.create_transfer()
        self.assertEqual(created["status"], "draft")
        submitted = stock.submit_stock_transfer(created["id"], current_user_id=str(self.admin_id), current_role="admin")
        repeated = stock.submit_stock_transfer(created["id"], current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(submitted["status"], "pending_approval")
        self.assertEqual(repeated["status"], "pending_approval")
        self.assertEqual(submitted["id"], repeated["id"])

    def test_creation_rejects_invalid_requested_date(self):
        with self.assertRaises(ApiError) as raised:
            stock.create_stock_transfer({
                "sending_location": "Warehouse A",
                "receiving_location": "Warehouse B",
                "requested_date": "not-a-date",
                "recipient": self.recipient(),
                "transfer_items": [{"item_id": "OIL", "quantity": 10}],
            }, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 400)

    def test_recipient_validation_and_waybill_snapshot(self):
        base = {
            "sending_location": "Warehouse A", "receiving_location": "Warehouse B",
            "transfer_items": [{"item_id": "OIL", "quantity": 10}],
        }
        with self.assertRaises(ApiError):
            stock.create_stock_transfer(base, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError):
            stock.create_stock_transfer(
                {**base, "recipient": {"full_name": "Receiving Clerk", "primary_phone": "bad"}},
                current_user_id=str(self.admin_id), current_role="admin",
            )
        recipient = {
            "full_name": "Ama Mensah", "role": "Branch Manager",
            "primary_phone": "+233 20 111 2222", "secondary_phone": "+233 24 333 4444",
            "email": "ama@example.com", "delivery_instructions": "Call at the security gate.",
        }
        created = stock.create_stock_transfer(
            {**base, "recipient": recipient}, current_user_id=str(self.admin_id), current_role="admin"
        )
        self.approve_transfer(created["id"])
        scheduled = stock.schedule_stock_transfer(
            created["id"], {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        detail = stock.get_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(detail["recipient"], recipient)
        self.assertEqual(detail["waybill"]["recipient"], recipient)
        self.assertEqual(ObjectId(detail["linked_waybill_id"]), ObjectId(scheduled["linked_waybill_id"]))

    def test_recipient_edit_permissions_reason_and_audit(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        stock.schedule_stock_transfer(
            created["id"], {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        changed = {**self.recipient(), "full_name": "New Recipient"}
        with self.assertRaises(ApiError) as raised:
            stock.update_stock_transfer_recipient(
                created["id"], {"recipient": changed}, current_user_id=str(self.driver_id), current_role="driver"
            )
        self.assertEqual(raised.exception.status_code, 403)
        updated = stock.update_stock_transfer_recipient(
            created["id"], {"recipient": changed}, current_user_id=str(self.admin_id), current_role="admin"
        )
        self.assertEqual(updated["recipient"]["full_name"], "New Recipient")
        waybill = self.db.waybills.find_one({"_id": ObjectId(updated["linked_waybill_id"])})
        self.assertEqual(waybill["recipient"]["full_name"], "New Recipient")

        stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        with self.assertRaises(ApiError) as locked:
            stock.update_stock_transfer_recipient(
                created["id"], {"recipient": {**changed, "primary_phone": "+233 55 000 0000"}, "reason": "Recipient changed shift"},
                current_user_id=str(self.admin_id), current_role="admin",
            )
        self.assertEqual(locked.exception.status_code, 409)
        self.assertEqual(self.db.stock_transfers.find_one({"_id": ObjectId(created["id"])})["recipient"]["full_name"], "New Recipient")
        stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        after_departure = {**changed, "primary_phone": "+233 55 555 5555"}
        with self.assertRaises(ApiError):
            stock.update_stock_transfer_recipient(
                created["id"], {"recipient": after_departure}, current_user_id=str(self.admin_id), current_role="admin"
            )
        audited = stock.get_stock_transfer(created["id"], current_user_id=str(self.admin_id), current_role="admin")
        event = [item for item in audited["audit_log"] if item["event"] == "recipient_updated"][-1]
        self.assertEqual(event["actor_id"], str(self.admin_id))
        self.assertIsNone(event["details"]["reason"])
        self.assertTrue(event["timestamp"])
        waybill = self.db.waybills.find_one({"_id": ObjectId(audited["linked_waybill_id"])})
        self.assertEqual(waybill["recipient"]["full_name"], "New Recipient")
        self.assertIn("recipient_updated_from_source", [item["event"] for item in waybill["audit_log"]])

    def test_loaded_in_transit_delivered_are_synchronized_audited_and_idempotent(self):
        created = self.create_transfer(); self.approve_transfer(created["id"])
        assigned = stock.schedule_stock_transfer(
            created["id"], {"vehicle_id": str(self.vehicle_id), "driver_id": str(self.driver_id), "scheduled_at": "2026-07-20T09:00:00Z"},
            current_user_id=str(self.admin_id), current_role="admin",
        )
        with self.assertRaises(ApiError):
            stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        stock.acknowledge_stock_transfer(created["id"], current_user_id=str(self.driver_id), current_role="driver")
        loaded = stock.release_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(loaded["workflow_stage"], "loaded")
        self.assertEqual(self.db.waybills.find_one({"_id": ObjectId(assigned["linked_waybill_id"])})["status"], "loaded")
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": ObjectId(assigned["linked_vehicle_movement_id"])})["status"], "checked_out")

        started = stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        repeated_start = stock.start_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(started["status"], "in_transit")
        self.assertEqual(self.db.waybills.find_one({"_id": ObjectId(assigned["linked_waybill_id"])})["status"], "in_transit")
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": ObjectId(assigned["linked_vehicle_movement_id"])})["status"], "in_progress")
        self.assertEqual(len([item for item in repeated_start["audit_log"] if item["event"] == "journey_started"]), 1)

        delivered = stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        repeated_delivery = stock.arrive_stock_transfer(created["id"], {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(delivered["workflow_stage"], "delivered")
        self.assertEqual(delivered["dispatch_status"], "delivered")
        waybill = self.db.waybills.find_one({"_id": ObjectId(assigned["linked_waybill_id"])})
        movement = self.db.vehicle_movements.find_one({"_id": ObjectId(assigned["linked_vehicle_movement_id"])})
        self.assertEqual(waybill["status"], "delivered")
        self.assertTrue(waybill["receipt_pending"])
        self.assertFalse(any(item.get("confirmation_type") == "destination_receipt" for item in waybill["confirmations"]))
        self.assertEqual(waybill["signatures"], {})
        self.assertEqual(movement["status"], "returned")
        self.assertEqual(len([item for item in repeated_delivery["audit_log"] if item["event"] == "delivered"]), 1)
        events = {item["event"]: item for item in repeated_delivery["audit_log"]}
        for event_name in ("transfer_approved", "driver_confirmed", "loaded", "journey_started", "delivered"):
            self.assertIn(event_name, events)
            self.assertTrue(events[event_name]["actor_id"])
            self.assertTrue(events[event_name]["timestamp"])

    def test_receiver_verification_validates_items_signature_permissions_and_completes(self):
        created, scheduled = self.deliver_transfer()
        correct = {
            "items": [{"item_id": "OIL", "received_quantity": 10, "condition": "Correct"}],
            "actual_receiver": {
                "full_name": "Kojo Asante", "primary_contact": "+233 24 555 0101",
                "role": "Storekeeper", "initials": "KA", "notes": "Delivery checked.",
            },
        }
        with self.assertRaises(ApiError):
            stock.verify_stock_transfer_delivery(created["id"], {**correct, "items": []}, current_user_id=str(self.driver_id), current_role="driver")
        with self.assertRaises(ApiError):
            stock.verify_stock_transfer_delivery(
                created["id"], {**correct, "items": [{"item_id": "OIL", "received_quantity": 9, "condition": "Correct"}]},
                current_user_id=str(self.driver_id), current_role="driver",
            )
        with self.assertRaises(ApiError):
            stock.verify_stock_transfer_delivery(
                created["id"], {**correct, "actual_receiver": {**correct["actual_receiver"], "initials": ""}},
                current_user_id=str(self.driver_id), current_role="driver",
            )
        with self.assertRaises(ApiError) as wrong_driver:
            stock.verify_stock_transfer_delivery(created["id"], correct, current_user_id=str(self.other_driver_id), current_role="driver")
        self.assertEqual(wrong_driver.exception.status_code, 403)
        with self.assertRaises(ApiError) as admin:
            stock.verify_stock_transfer_delivery(created["id"], correct, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(admin.exception.status_code, 403)
        with self.assertRaises(ApiError) as legacy_admin_receipt:
            stock.receive_stock_transfer(
                created["id"], {"received_items": [{"item_id": "OIL", "quantity": 10}]},
                current_user_id=str(self.admin_id), current_role="admin",
            )
        self.assertEqual(legacy_admin_receipt.exception.status_code, 409)

        completed = stock.verify_stock_transfer_delivery(created["id"], correct, current_user_id=str(self.driver_id), current_role="driver")
        repeated = stock.verify_stock_transfer_delivery(created["id"], correct, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["workflow_stage"], "completed")
        self.assertEqual(completed["actual_receiver"]["full_name"], "Kojo Asante")
        self.assertEqual(completed["recipient"]["full_name"], "Receiving Clerk")
        self.assertEqual(completed["quantity_variance"], [])
        self.assertEqual(len([item for item in repeated["audit_log"] if item["event"] == "receiver_verified"]), 1)
        waybill = self.db.waybills.find_one({"_id": ObjectId(scheduled["linked_waybill_id"])})
        self.assertEqual(waybill["status"], "completed")
        self.assertEqual(waybill["items"][0]["received_quantity"], 10)
        self.assertEqual(waybill["items"][0]["variance"], 0)
        self.assertEqual(waybill["items"][0]["item_condition"], "correct")
        self.assertEqual(waybill["items"][0]["missing_quantity"], 0)
        self.assertEqual(waybill["items"][0]["excess_quantity"], 0)
        self.assertEqual(waybill["items"][0]["exception_status"], "clear")
        self.assertEqual(waybill["signatures"]["receiver"]["initials"], "KA")
        self.assertEqual(waybill["custody_events"][-1]["to"], "Kojo Asante")
        self.assertIsNotNone(waybill["locked_at"])
        self.assertEqual(len([item for item in waybill["confirmations"] if item.get("confirmation_type") == "receiver_verification"]), 1)
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": ObjectId(scheduled["linked_vehicle_movement_id"])})["status"], "closed")
        with self.assertRaises(ApiError):
            waybill_service.save_waybill_signature(
                waybill["_id"], "receiver", {"signature": "replacement", "signed_by_name": "Other"},
                current_user_id=str(self.driver_id), current_role="driver",
            )

    def test_receiver_exception_creates_one_link_and_keeps_transfer_open(self):
        created, scheduled = self.deliver_transfer()
        exception_payload = {
            "items": [{
                "item_id": "OIL", "expected_quantity": 10, "received_quantity": 8,
                "exception_type": "Correct",
                "notes": "Two units missing", "photos": ["data:image/png;base64,ITEM"],
            }],
            "actual_receiver": {
                "full_name": "Esi Boateng", "primary_contact": "+233 20 900 0000",
                "role": "Branch Lead", "signature": "data:image/png;base64,AAA",
                "notes": "Two units were missing from the sealed carton.",
                "acknowledged": True,
            },
        }
        reported = stock.report_stock_transfer_delivery_exception(
            created["id"], exception_payload, current_user_id=str(self.driver_id), current_role="driver"
        )
        repeated = stock.report_stock_transfer_delivery_exception(
            created["id"], exception_payload, current_user_id=str(self.driver_id), current_role="driver"
        )
        self.assertEqual(reported["status"], "awaiting_receipt")
        self.assertEqual(reported["workflow_stage"], "delivery_exception")
        self.assertEqual(reported["quantity_variance"][0]["difference"], -2)
        self.assertEqual(reported["quantity_variance"][0]["condition"], "missing")
        self.assertEqual(reported["recipient"]["full_name"], "Receiving Clerk")
        self.assertEqual(reported["actual_receiver"]["full_name"], "Esi Boateng")
        self.assertEqual(self.db.delivery_exceptions.count_documents({}), 1)
        self.assertEqual(repeated["linked_delivery_exception_id"], reported["linked_delivery_exception_id"])
        self.assertEqual(len([item for item in repeated["audit_log"] if item["event"] == "delivery_exception_reported"]), 1)
        exception = self.db.delivery_exceptions.find_one({})
        self.assertEqual(exception["status"], "open")
        self.assertEqual(exception["items"][0]["variance"], -2)
        self.assertEqual(exception["items"][0]["exception_quantity"], 2)
        self.assertEqual(exception["items"][0]["exception_type"], "missing")
        self.assertEqual(exception["items"][0]["photos"], ["data:image/png;base64,ITEM"])
        self.assertEqual(exception["driver_id"], self.driver_id)
        self.assertTrue(exception["receiver_acknowledgement"]["acknowledged"])
        self.assertEqual(exception["stock_transfer_id"], ObjectId(created["id"]))
        self.assertEqual(exception["waybill_id"], ObjectId(scheduled["linked_waybill_id"]))
        self.assertEqual(exception["movement_id"], ObjectId(scheduled["linked_vehicle_movement_id"]))
        self.assertEqual(reported["delivery_exception_summary"]["affected_item_count"], 1)
        waybill = self.db.waybills.find_one({"_id": ObjectId(scheduled["linked_waybill_id"])})
        self.assertEqual(waybill["status"], "delivered")
        self.assertEqual(waybill["linked_delivery_exception_id"], exception["_id"])
        self.assertEqual(waybill["delivery_exception_summary"]["exception_number"], exception["exception_number"])
        self.assertEqual(waybill["signatures"]["receiver"]["signed_by_name"], "Esi Boateng")
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": ObjectId(scheduled["linked_vehicle_movement_id"])})["status"], "returned")
        with self.assertRaises(ApiError):
            stock.verify_stock_transfer_delivery(created["id"], exception_payload, current_user_id=str(self.driver_id), current_role="driver")
        with self.assertRaises(ApiError) as blocked_completion:
            stock.complete_stock_transfer(created["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(blocked_completion.exception.status_code, 409)
        changed = {**exception_payload, "items": [{
            "item_id": "OIL", "expected_quantity": 10, "received_quantity": 10,
            "exception_type": "Damaged", "notes": "Units damaged", "photos": [],
        }]}
        with self.assertRaises(ApiError) as duplicate:
            stock.report_stock_transfer_delivery_exception(created["id"], changed, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertEqual(self.db.delivery_exceptions.count_documents({}), 1)

    def test_delivery_exception_supports_all_types_multiple_items_and_validation(self):
        items = [
            {"item_id": "MISSING", "name": "Missing item", "quantity": 10},
            {"item_id": "DAMAGED", "name": "Damaged item", "quantity": 10},
            {"item_id": "WRONG", "name": "Wrong item", "quantity": 10},
            {"item_id": "EXCESS", "name": "Excess item", "quantity": 10},
        ]
        created, scheduled = self.deliver_transfer(items)
        reviewed_items = [
            {"item_id": "MISSING", "expected_quantity": 10, "received_quantity": 8, "exception_type": "Correct", "notes": "Short by two", "photos": []},
            {"item_id": "DAMAGED", "expected_quantity": 10, "received_quantity": 10, "exception_type": "Damaged", "notes": "Received units were crushed", "photos": ["data:image/jpeg;base64,DAMAGE"]},
            {"item_id": "WRONG", "expected_quantity": 10, "received_quantity": 10, "exception_type": "Wrong Item", "notes": "Wrong products received", "photos": []},
            {"item_id": "EXCESS", "expected_quantity": 10, "received_quantity": 12, "exception_type": "Correct", "notes": "Two extra", "photos": []},
        ]
        receiver = {
            "full_name": "Akosua Owusu", "primary_contact": "+233 24 000 1111",
            "role": "Receiver", "initials": "AO", "acknowledged": True,
        }
        payload = {"items": reviewed_items, "actual_receiver": receiver}
        with self.assertRaises(ApiError):
            stock.report_stock_transfer_delivery_exception(
                created["id"], {**payload, "actual_receiver": {**receiver, "acknowledged": False}},
                current_user_id=str(self.driver_id), current_role="driver",
            )
        invalid_quantity = [dict(item) for item in reviewed_items]
        invalid_quantity[0]["exception_quantity"] = 1
        with self.assertRaises(ApiError):
            stock.report_stock_transfer_delivery_exception(
                created["id"], {**payload, "items": invalid_quantity},
                current_user_id=str(self.driver_id), current_role="driver",
            )
        missing_damage_notes = [dict(item) for item in reviewed_items]
        missing_damage_notes[1]["notes"] = ""
        with self.assertRaises(ApiError):
            stock.report_stock_transfer_delivery_exception(
                created["id"], {**payload, "items": missing_damage_notes},
                current_user_id=str(self.driver_id), current_role="driver",
            )
        with self.assertRaises(ApiError) as wrong_driver:
            stock.report_stock_transfer_delivery_exception(
                created["id"], payload, current_user_id=str(self.other_driver_id), current_role="driver",
            )
        self.assertEqual(wrong_driver.exception.status_code, 403)
        with self.assertRaises(ApiError) as admin:
            stock.report_stock_transfer_delivery_exception(
                created["id"], payload, current_user_id=str(self.admin_id), current_role="admin",
            )
        self.assertEqual(admin.exception.status_code, 403)

        reported = stock.report_stock_transfer_delivery_exception(
            created["id"], payload, current_user_id=str(self.driver_id), current_role="driver",
        )
        exception = self.db.delivery_exceptions.find_one({"_id": ObjectId(reported["linked_delivery_exception_id"])})
        self.assertEqual({item["exception_type"] for item in exception["items"]}, {"missing", "damaged", "wrong_item", "excess"})
        self.assertEqual(len(exception["items"]), 4)
        exception_by_item = {item["item_id"]: item for item in exception["items"]}
        self.assertEqual(exception_by_item["MISSING"]["exception_quantity"], 2)
        self.assertEqual(exception_by_item["EXCESS"]["exception_quantity"], 2)
        self.assertEqual(exception_by_item["DAMAGED"]["exception_quantity"], 10)
        self.assertEqual(exception_by_item["WRONG"]["exception_quantity"], 10)
        self.assertNotIn("exception_quantity", reviewed_items[0])
        self.assertEqual(exception["actual_receiver"]["full_name"], "Akosua Owusu")
        self.assertTrue(exception["reported_at"])
        self.assertTrue(exception["created_at"])
        self.assertEqual(reported["status"], "awaiting_receipt")
        self.assertEqual(reported["receiving_status"], "exception_reported")
        self.assertEqual(reported["delivery_exception_summary"]["affected_item_count"], 4)
        self.assertEqual(len([event for event in reported["audit_log"] if event["event"] == "delivery_exception_reported"]), 1)
        waybill = self.db.waybills.find_one({"_id": ObjectId(scheduled["linked_waybill_id"])})
        self.assertEqual(waybill["status"], "delivered")
        self.assertEqual(waybill["delivery_exception_status"], "open")
        waybill_items = {item["item_id"]: item for item in waybill["items"]}
        self.assertEqual(waybill_items["MISSING"]["missing_quantity"], 2)
        self.assertEqual(waybill_items["MISSING"]["excess_quantity"], 0)
        self.assertEqual(waybill_items["EXCESS"]["missing_quantity"], 0)
        self.assertEqual(waybill_items["EXCESS"]["excess_quantity"], 2)
        self.assertTrue(all(item["exception_status"] == "exception" for item in waybill["items"]))
        self.assertEqual(len([event for event in waybill["audit_log"] if event["event"] == "delivery_exception_reported"]), 1)

    def test_missing_exception_dispatches_one_traced_replacement(self):
        created, _scheduled = self.report_single_exception("missing")
        actioned = stock.take_delivery_exception_action(created["id"], {"action": "dispatch_replacement"}, current_user_id=str(self.admin_id), current_role="admin")
        repeated = stock.take_delivery_exception_action(created["id"], {"action": "dispatch_replacement"}, current_user_id=str(self.admin_id), current_role="admin")
        exception = self.db.delivery_exceptions.find_one({"_id": ObjectId(actioned["linked_delivery_exception_id"])})
        replacement = self.db.delivery_replacement_requests.find_one({"delivery_exception_id": exception["_id"]})
        replacement_transfer = self.db.stock_transfers.find_one({"_id": replacement["linked_stock_transfer_id"]})
        self.assertEqual(self.db.delivery_replacement_requests.count_documents({}), 1)
        self.assertEqual(repeated["delivery_exception"]["current_action"]["action"], "dispatch_replacement")
        self.assertEqual(replacement_transfer["original_stock_transfer_id"], ObjectId(created["id"]))
        self.assertEqual(replacement_transfer["source_delivery_exception_id"], exception["_id"])
        self.assertEqual(replacement_transfer["transfer_items"][0]["quantity"], 2)
        self.assertIsNotNone(replacement["linked_waybill_id"])
        self.assertIsNotNone(replacement["linked_vehicle_movement_id"])

    def test_replacement_completion_automatically_resolves_original_exception(self):
        created, original_scheduled = self.report_single_exception("missing")
        actioned = stock.take_delivery_exception_action(created["id"], {"action": "dispatch_replacement"}, current_user_id=str(self.admin_id), current_role="admin")
        replacement = self.db.delivery_replacement_requests.find_one({"delivery_exception_id": ObjectId(actioned["linked_delivery_exception_id"])})
        replacement_id = str(replacement["linked_stock_transfer_id"])
        stock.acknowledge_stock_transfer(replacement_id, current_user_id=str(self.driver_id), current_role="driver")
        stock.release_stock_transfer(replacement_id, {}, current_user_id=str(self.admin_id), current_role="admin")
        stock.start_stock_transfer(replacement_id, {}, current_user_id=str(self.driver_id), current_role="driver")
        stock.arrive_stock_transfer(replacement_id, {}, current_user_id=str(self.driver_id), current_role="driver")
        verification = {
            "items": [{"item_id": "OIL", "received_quantity": 2, "condition": "correct"}],
            "actual_receiver": {"full_name": "Replacement Receiver", "primary_contact": "+233 24 222 1111", "initials": "RR"},
        }
        completed = stock.verify_stock_transfer_delivery(replacement_id, verification, current_user_id=str(self.driver_id), current_role="driver")
        repeated = stock.verify_stock_transfer_delivery(replacement_id, verification, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(repeated["status"], "completed")
        exception = self.db.delivery_exceptions.find_one({"_id": ObjectId(actioned["linked_delivery_exception_id"])})
        original = self.db.stock_transfers.find_one({"_id": ObjectId(created["id"])})
        replacement_document = self.db.stock_transfers.find_one({"_id": ObjectId(replacement_id)})
        replacement_waybill = self.db.waybills.find_one({"_id": replacement_document["linked_waybill_id"]})
        replacement_movement = self.db.vehicle_movements.find_one({"_id": replacement_document["linked_vehicle_movement_id"]})
        original_waybill = self.db.waybills.find_one({"_id": ObjectId(original_scheduled["linked_waybill_id"])})
        self.assertEqual(exception["status"], "resolved")
        self.assertEqual(exception["operational_status"], "resolved")
        self.assertEqual(exception["linked_replacement_status"], "completed")
        self.assertTrue(exception["resolved_at"])
        self.assertEqual(original["status"], "awaiting_receipt")
        self.assertEqual(original["delivery_exception_status"], "resolved")
        self.assertEqual(original["linked_replacement_status"], "completed")
        self.assertEqual(original_waybill["status"], "delivered")
        self.assertEqual(original_waybill["delivery_exception_status"], "resolved")
        self.assertEqual(replacement_waybill["status"], "completed")
        self.assertEqual(replacement_movement["status"], "closed")
        self.assertEqual(self.db.delivery_replacement_requests.find_one({"_id": replacement["_id"]})["status"], "completed")
        self.assertEqual(len([event for event in exception["audit_log"] if event["event"] == "exception_resolved"]), 1)
        refreshed = stock.get_stock_transfer(created["id"], current_user_id=str(self.admin_id), current_role="admin")
        timeline = refreshed["delivery_exception"]["operations_timeline"]
        self.assertEqual([stage["key"] for stage in timeline], ["exception_reported", "action_selected", "replacement_created", "driver_assigned", "loaded", "in_transit", "delivered", "receiver_verified", "exception_resolved"])
        self.assertTrue(all(stage["completed"] for stage in timeline))
        with self.assertRaises(ApiError):
            stock.take_delivery_exception_action(created["id"], {"action": "resolved"}, current_user_id=str(self.admin_id), current_role="admin")

    def test_damaged_exception_return_lifecycle_synchronizes_documents(self):
        created, _scheduled = self.report_single_exception("damaged")
        selected = stock.take_delivery_exception_action(created["id"], {"action": "return_item"}, current_user_id=str(self.admin_id), current_role="admin")
        request = self.db.delivery_return_requests.find_one({})
        self.assertEqual(request["status"], "assigned")
        self.assertEqual(request["driver_id"], self.driver_id)
        self.assertEqual(self.db.waybills.find_one({"_id": request["linked_waybill_id"]})["status"], "approved")
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": request["linked_vehicle_movement_id"]})["status"], "approved")
        stock.transition_delivery_exception_return(created["id"], "in_transit", {}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(self.db.waybills.find_one({"_id": request["linked_waybill_id"]})["status"], "in_transit")
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": request["linked_vehicle_movement_id"]})["status"], "in_progress")
        stock.transition_delivery_exception_return(created["id"], "returned", {}, current_user_id=str(self.driver_id), current_role="driver")
        completed = stock.transition_delivery_exception_return(created["id"], "received_at_origin", {}, current_user_id=str(self.admin_id), current_role="admin")
        request = self.db.delivery_return_requests.find_one({})
        self.assertEqual(request["status"], "received_at_origin")
        self.assertEqual(self.db.waybills.find_one({"_id": request["linked_waybill_id"]})["status"], "completed")
        self.assertEqual(self.db.vehicle_movements.find_one({"_id": request["linked_vehicle_movement_id"]})["status"], "closed")
        self.assertEqual(completed["delivery_exception"]["current_action"]["status"], "completed")
        self.assertEqual(selected["delivery_exception"]["return_request"]["status"], "assigned")

    def test_wrong_item_requires_return_before_replacement(self):
        created, _scheduled = self.report_single_exception("wrong_item")
        with self.assertRaises(ApiError):
            stock.take_delivery_exception_action(created["id"], {"action": "dispatch_replacement"}, current_user_id=str(self.admin_id), current_role="admin")
        stock.take_delivery_exception_action(created["id"], {"action": "return_item"}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_return(created["id"], "in_transit", {}, current_user_id=str(self.driver_id), current_role="driver")
        stock.transition_delivery_exception_return(created["id"], "returned", {}, current_user_id=str(self.driver_id), current_role="driver")
        stock.transition_delivery_exception_return(created["id"], "received_at_origin", {}, current_user_id=str(self.admin_id), current_role="admin")
        result = stock.take_delivery_exception_action(created["id"], {"action": "dispatch_replacement"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(result["delivery_exception"]["current_action"]["action"], "dispatch_replacement")
        self.assertEqual(self.db.delivery_return_requests.count_documents({}), 1)
        self.assertEqual(self.db.delivery_replacement_requests.count_documents({}), 1)

    def test_excess_return_is_idempotent_and_invalid_actions_are_rejected(self):
        created, _scheduled = self.report_single_exception("excess")
        first = stock.take_delivery_exception_action(created["id"], {"action": "return_item"}, current_user_id=str(self.admin_id), current_role="admin")
        second = stock.take_delivery_exception_action(created["id"], {"action": "return_item"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(first["delivery_exception"]["current_action"]["action_id"], second["delivery_exception"]["current_action"]["action_id"])
        self.assertEqual(self.db.delivery_return_requests.count_documents({}), 1)
        self.assertEqual(self.db.vehicle_movements.count_documents({"movement_type": "stock_return"}), 1)
        self.assertEqual(self.db.waybills.count_documents({"source_type": "delivery_return_request"}), 1)
        with self.assertRaises(ApiError):
            stock.take_delivery_exception_action(created["id"], {"action": "dispatch_replacement"}, current_user_id=str(self.admin_id), current_role="admin")

    def resolved_exception(self, exception_type="missing"):
        created, _scheduled = self.report_single_exception(exception_type)
        exception = self.db.delivery_exceptions.find_one({"stock_transfer_id": ObjectId(created["id"])})
        timestamp = stock.now_utc()
        self.db.delivery_exceptions.update_one({"_id": exception["_id"]}, {"$set": {"status": "resolved", "operational_status": "resolved", "resolved_at": timestamp}})
        self.db.stock_transfers.update_one({"_id": ObjectId(created["id"])}, {"$set": {"delivery_exception_status": "resolved"}})
        return created, exception

    def test_investigation_requires_resolved_exception_and_is_unique(self):
        created, _scheduled = self.report_single_exception("missing")
        with self.assertRaises(ApiError) as raised:
            stock.start_delivery_exception_investigation(created["id"], {"investigator_id": str(self.admin_id), "priority": "high"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 409)
        self.db.delivery_exceptions.update_one({"stock_transfer_id": ObjectId(created["id"])}, {"$set": {"status": "resolved"}})
        first = stock.start_delivery_exception_investigation(created["id"], {"investigator_id": str(self.admin_id), "priority": "high", "note": "Initial review", "evidence": ["/uploads/investigation.pdf"]}, current_user_id=str(self.admin_id), current_role="admin")
        second = stock.start_delivery_exception_investigation(created["id"], {"investigator_id": str(self.admin_id), "priority": "high"}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(self.db.delivery_exception_investigations.count_documents({}), 1)
        self.assertEqual(first["delivery_exception"]["investigation"]["id"], second["delivery_exception"]["investigation"]["id"])
        self.assertEqual(first["delivery_exception"]["investigation"]["evidence"][0]["file_kind"], "document")

    def test_investigation_requires_findings_generates_action_and_blocks_close(self):
        created, _exception = self.resolved_exception()
        stock.start_delivery_exception_investigation(created["id"], {"investigator_id": str(self.admin_id), "priority": "critical"}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_investigation(created["id"], "under_investigation", {}, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError):
            stock.transition_delivery_exception_investigation(created["id"], "awaiting_approval", {}, current_user_id=str(self.admin_id), current_role="admin")
        stock.update_delivery_exception_investigation(created["id"], {"root_cause": "warehouse_picking_error", "responsibility": "warehouse", "decision": "retraining", "note": "Picker selected the adjacent bin.", "cost_impact": {"estimated_loss": 120, "replacement_cost": 80, "recovered_amount": 50, "recovery_status": "in_progress"}}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_investigation(created["id"], "awaiting_approval", {}, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError) as raised:
            stock.transition_delivery_exception_investigation(created["id"], "approved", {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 403)
        approved = stock.transition_delivery_exception_investigation(created["id"], "approved", {"approval_comments": "Approved for corrective action."}, current_user_id=str(self.owner_id), current_role="owner")
        action = approved["delivery_exception"]["investigation"]["linked_actions"][0]
        self.assertEqual(action["action_type"], "warehouse_action")
        self.assertEqual(approved["delivery_exception"]["investigation"]["approval"]["approved_by"], str(self.owner_id))
        self.assertTrue(approved["delivery_exception"]["investigation"]["approval"]["approved_on"])
        self.assertEqual(approved["delivery_exception"]["investigation"]["approval"]["approval_comments"], "Approved for corrective action.")
        self.assertEqual(approved["delivery_exception"]["investigation"]["cost_impact"]["outstanding_amount"], 150)
        stock.transition_delivery_exception_investigation(created["id"], "actions_in_progress", {}, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError) as raised:
            stock.transition_delivery_exception_investigation(created["id"], "closed", {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(raised.exception.status_code, 409)
        stock.complete_delivery_investigation_action(created["id"], action["id"], {"notes": "Retraining record issued."}, current_user_id=str(self.admin_id), current_role="admin")
        repeated = stock.complete_delivery_investigation_action(created["id"], action["id"], {}, current_user_id=str(self.admin_id), current_role="admin")
        closed = stock.transition_delivery_exception_investigation(created["id"], "closed", {}, current_user_id=str(self.admin_id), current_role="admin")
        investigation = closed["delivery_exception"]["investigation"]
        self.assertEqual(investigation["status"], "closed")
        self.assertEqual(investigation["closure_summary"]["status"], "awaiting_receipt")
        self.assertEqual(investigation["closure_summary"]["exception_status"], "resolved")
        self.assertEqual(investigation["closure_summary"]["investigation_status"], "closed")
        self.assertEqual(investigation["closure_summary"]["root_cause"], "warehouse_picking_error")
        self.assertEqual(investigation["closure_summary"]["responsibility"], "warehouse")
        self.assertEqual(investigation["closure_summary"]["decision"], "retraining")
        self.assertEqual(investigation["closure_summary"]["approved_by"], str(self.owner_id))
        self.assertEqual(investigation["closure_summary"]["closed_by"], str(self.admin_id))
        self.assertEqual(investigation["closure_summary"]["cost_impact"]["outstanding_amount"], 150)
        self.assertEqual(closed["delivery_exception_summary"]["closure_summary"]["cost_impact"]["outstanding_amount"], 150)
        self.assertEqual(repeated["delivery_exception"]["investigation"]["linked_actions"][0]["status"], "completed")
        self.assertEqual(len([item for item in investigation["audit_log"] if item["event"] == "investigation_action_completed"]), 1)
        self.assertEqual(len([item for item in investigation["audit_log"] if item["event"] == "investigation_closed"]), 1)
        self.assertEqual([item["status"] for item in investigation["status_history"]], ["open", "under_investigation", "awaiting_approval", "approved", "actions_in_progress", "closed"])

    def test_suspected_theft_requires_explicit_owner_confirmation(self):
        created, _exception = self.resolved_exception("damaged")
        stock.start_delivery_exception_investigation(created["id"], {"investigator_id": str(self.admin_id)}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_investigation(created["id"], "under_investigation", {}, current_user_id=str(self.admin_id), current_role="admin")
        stock.update_delivery_exception_investigation(created["id"], {"root_cause": "suspected_theft", "responsibility": "third_party", "decision": "escalate"}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_investigation(created["id"], "awaiting_approval", {}, current_user_id=str(self.admin_id), current_role="admin")
        with self.assertRaises(ApiError):
            stock.transition_delivery_exception_investigation(created["id"], "approved", {}, current_user_id=str(self.owner_id), current_role="owner")
        result = stock.transition_delivery_exception_investigation(created["id"], "approved", {"confirm_suspected_theft": True}, current_user_id=str(self.owner_id), current_role="owner")
        self.assertTrue(result["delivery_exception"]["investigation"]["suspected_theft_confirmed"])
        self.assertEqual(result["delivery_exception"]["investigation"]["linked_actions"][0]["action_type"], "operations_action")

    def test_investigation_permissions_and_no_action_closure(self):
        created, _exception = self.resolved_exception()
        with self.assertRaises(ApiError) as raised:
            stock.start_delivery_exception_investigation(created["id"], {"investigator_id": str(self.admin_id)}, current_user_id=str(self.driver_id), current_role="driver")
        self.assertEqual(raised.exception.status_code, 403)
        stock.start_delivery_exception_investigation(created["id"], {"investigator_id": str(self.admin_id)}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_investigation(created["id"], "under_investigation", {}, current_user_id=str(self.admin_id), current_role="admin")
        stock.update_delivery_exception_investigation(created["id"], {"root_cause": "documentation_error", "responsibility": "shared", "decision": "no_action"}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_investigation(created["id"], "awaiting_approval", {}, current_user_id=str(self.admin_id), current_role="admin")
        stock.transition_delivery_exception_investigation(created["id"], "approved", {}, current_user_id=str(self.owner_id), current_role="owner")
        stock.transition_delivery_exception_investigation(created["id"], "actions_in_progress", {}, current_user_id=str(self.admin_id), current_role="admin")
        closed = stock.transition_delivery_exception_investigation(created["id"], "closed", {}, current_user_id=str(self.admin_id), current_role="admin")
        self.assertEqual(closed["delivery_exception"]["investigation"]["linked_actions"], [])

    def test_investigation_decisions_map_to_non_executing_action_records(self):
        cases = [
            ({"decision": "warning", "responsibility": "driver"}, "hr_action"),
            ({"decision": "finance_case", "responsibility": "shared"}, "finance_recovery"),
            ({"decision": "supplier_claim", "responsibility": "supplier"}, "supplier_claim"),
            ({"decision": "retraining", "responsibility": "warehouse"}, "warehouse_action"),
            ({"decision": "escalate", "responsibility": "third_party"}, "operations_action"),
            ({"decision": "no_action", "responsibility": "shared"}, None),
        ]
        for investigation, expected in cases:
            with self.subTest(decision=investigation["decision"]):
                self.assertEqual(stock._decision_action_type(investigation), expected)


class AvailabilityExceptionTests(unittest.TestCase):
    def test_matching_compliance_visit_bypasses_only_matching_compliance_blocker(self):
        db = mongomock.MongoClient().availability_test
        vehicle_id, compliance_id = ObjectId(), ObjectId()
        db.vehicles.insert_one({"_id": vehicle_id, "status": "available"})
        db.vehicle_compliance_records.insert_one({"_id": compliance_id, "vehicle_id": vehicle_id, "status": "expired"})
        with patch.object(availability, "get_collection", side_effect=lambda name: db[name]):
            normal = availability.resolve_vehicle_availability(vehicle_id)
            exception = availability.resolve_vehicle_availability(vehicle_id, context={"movement_type": "compliance_inspection_visit", "related_source_type": "compliance_record", "related_source_id": compliance_id})
        self.assertFalse(normal["is_available"])
        self.assertTrue(exception["is_available"])

    def test_safety_blocker_remains_during_compliance_visit(self):
        db = mongomock.MongoClient().availability_safety
        vehicle_id, compliance_id = ObjectId(), ObjectId()
        db.vehicles.insert_one({"_id": vehicle_id, "status": "available"})
        db.vehicle_compliance_records.insert_one({"_id": compliance_id, "vehicle_id": vehicle_id, "status": "expired"})
        db.faults.insert_one({"vehicle_id": vehicle_id, "status": "reported", "severity": "critical"})
        with patch.object(availability, "get_collection", side_effect=lambda name: db[name]):
            result = availability.resolve_vehicle_availability(vehicle_id, context={"movement_type": "compliance_inspection_visit", "related_source_type": "compliance_record", "related_source_id": compliance_id})
        self.assertFalse(result["is_available"])
        self.assertEqual(result["blocking_reasons"][0]["type"], "fault")

    def test_movement_transition_excludes_itself_from_conflict_check(self):
        db = mongomock.MongoClient().movement_transition
        vehicle_id, movement_id = ObjectId(), ObjectId()
        db.vehicles.insert_one({"_id": vehicle_id, "status": "available"})
        db.vehicle_movements.insert_one({"_id": movement_id, "vehicle_id": vehicle_id, "status": "approved", "movement_type": "administrative_errand"})
        with (
            patch.object(availability, "get_collection", side_effect=lambda name: db[name]),
            patch.object(movement_service, "vehicle_movements_collection", return_value=db.vehicle_movements),
            patch.object(movement_service, "resolve_vehicle_availability", side_effect=lambda vehicle, context=None: availability.resolve_vehicle_availability(vehicle, context=context)),
        ):
            movement_service._assert_vehicle_is_not_blocked(vehicle_id, exclude_movement_id=movement_id, source_type="administrative_errand")


class FuelMovementLinkTests(unittest.TestCase):
    def test_fuel_during_active_operational_movement_attaches_to_it(self):
        db = mongomock.MongoClient().fuel_operation
        driver_id, vehicle_id, assignment_id, station_id, movement_id = ObjectId(), ObjectId(), ObjectId(), ObjectId(), ObjectId()
        db.vehicle_movements.insert_one({"_id": movement_id, "vehicle_id": vehicle_id, "driver_id": driver_id, "movement_custodian_id": driver_id, "status": "in_progress", "updated_at": operations.now_utc()})
        with (
            patch.object(fuel_service, "dispatch_jobs_collection", return_value=db.dispatch_jobs),
            patch.object(fuel_service, "vehicle_movements_collection", return_value=db.vehicle_movements),
            patch.object(fuel_service, "_resolve_driver_submission_context", return_value={"vehicle_id": vehicle_id, "driver_id": driver_id, "assignment_id": assignment_id}),
            patch.object(fuel_service, "_get_vehicle_document", return_value={"_id": vehicle_id, "fuel_type": "petrol"}),
            patch.object(fuel_service, "_get_driver_document", return_value={"_id": driver_id}),
            patch.object(fuel_service, "_get_assignment_document", return_value={"_id": assignment_id, "vehicle_id": vehicle_id, "driver_id": driver_id}),
            patch.object(fuel_service, "_get_station_document", return_value={"_id": station_id, "status": "active"}),
            patch.object(fuel_service, "_calculate_log_metrics", return_value=(None, None, None)),
            patch.object(fuel_service, "_calculate_abnormal_spending", return_value=False),
        ):
            payload = fuel_service._build_fuel_log_payload({"fuel_station_id": str(station_id), "fuel_type": "petrol", "litres": 10, "amount": 100, "fuel_date": "2026-07-20", "payment_method": "cash"}, str(driver_id), "driver")
        self.assertEqual(payload["movement_id"], movement_id)
        self.assertEqual(payload["payment_responsibility"], "driver_paid_reimbursable")


class SourceRegistryTests(unittest.TestCase):
    def test_phase_1b2_sources_use_existing_source_key_builder(self):
        source_id = ObjectId()
        self.assertEqual(movement_source_service.build_source_key("vehicle_operation_request", source_id), f"vehicle_operation_request:{source_id}")
        self.assertEqual(movement_source_service.build_source_key("stock_transfer", source_id), f"stock_transfer:{source_id}")


if __name__ == "__main__":
    unittest.main()
