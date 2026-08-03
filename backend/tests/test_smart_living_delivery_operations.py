import sys
from pathlib import Path
from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId

BACKEND_DIR=Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path: sys.path.insert(0,str(BACKEND_DIR))

import services.branch_access_service as branch_access
import services.smart_living_delivery_service as delivery
from utils.api_error import ApiError


@pytest.fixture
def domain():
    db=mongomock.MongoClient().flux_test
    branch_a=ObjectId(); branch_b=ObjectId(); manager=ObjectId(); driver=ObjectId(); agent=ObjectId(); officer=ObjectId(); vehicle=ObjectId()
    db.branches.insert_many([{"_id":branch_a,"code":"A","name":"A","status":"active"},{"_id":branch_b,"code":"B","name":"B","status":"active"}])
    db.users.insert_many([
        {"_id":manager,"role":"operations_manager","status":"active","primary_branch_id":branch_a,"allowed_branch_ids":[branch_a]},
        {"_id":driver,"role":"driver","status":"active","primary_branch_id":branch_a,"allowed_branch_ids":[branch_a]},
        {"_id":agent,"role":"field_agent","status":"active","primary_branch_id":branch_a,"allowed_branch_ids":[branch_a]},
        {"_id":officer,"role":"issuing_receiving_officer","status":"active","primary_branch_id":branch_a,"allowed_branch_ids":[branch_a]},
    ])
    db.vehicles.insert_one({"_id":vehicle,"branch_id":branch_a,"status":"available"})
    patches=[patch.object(delivery,"get_collection",side_effect=lambda name:db[name]),patch.object(branch_access,"get_collection",side_effect=lambda name:db[name]),patch.object(delivery,"create_notification"),patch.object(delivery,"write_audit")]
    for item in patches:item.start()
    delivery.ensure_indexes()
    yield {"db":db,"a":branch_a,"b":branch_b,"manager":manager,"driver":driver,"agent":agent,"officer":officer,"vehicle":vehicle}
    for item in reversed(patches):item.stop()


def order_payload(branch, reference="SL-1", quantity=5):
    return {"branch_id":str(branch),"external_reference":reference,"customer_name":"Ada Mensah","customer_phone":"0200000000","delivery_address":"Accra","requested_delivery_date":"2099-08-01","status":"ready_for_planning","product_lines":[{"product_name":"Sofa","quantity_requested":quantity}]}


def test_branch_filter_and_duplicate_reference(domain):
    first=delivery.create_order(order_payload(domain["a"]),str(domain["manager"]))
    assert first["branch_id"]==str(domain["a"])
    with pytest.raises(ApiError) as duplicate:
        delivery.create_order(order_payload(domain["a"]),str(domain["manager"]))
    assert duplicate.value.status_code==409
    domain["db"].delivery_orders.insert_one({"branch_id":domain["b"],"external_source":"Smart Living","external_reference":"SL-B","status":"ready_for_planning","created_at":delivery.now_utc()})
    result=delivery.list_orders(str(domain["manager"]),{})
    assert [item["external_reference"] for item in result["orders"]]==["SL-1"]


def test_inactive_branch_and_cross_branch_assignment_are_rejected(domain):
    domain["db"].branches.update_one({"_id":domain["a"]},{"$set":{"status":"inactive"}})
    with pytest.raises(ApiError) as inactive: delivery.create_order(order_payload(domain["a"]),str(domain["manager"]))
    assert inactive.value.status_code==409
    domain["db"].branches.update_one({"_id":domain["a"]},{"$set":{"status":"active"}})
    domain["db"].users.update_one({"_id":domain["agent"]},{"$set":{"primary_branch_id":domain["b"],"allowed_branch_ids":[domain["b"]]}})
    order=delivery.create_order(order_payload(domain["a"]),str(domain["manager"]))
    with pytest.raises(ApiError) as mismatch:
        delivery.create_batch({"branch_id":str(domain["a"]),"delivery_date":"2099-08-01","driver_id":str(domain["driver"]),"vehicle_id":str(domain["vehicle"]),"field_agent_id":str(domain["agent"]),"delivery_order_ids":[order["id"]]},str(domain["manager"]))
    assert mismatch.value.status_code==409


def _scheduled(domain, reference="SL-1"):
    order=delivery.create_order(order_payload(domain["a"],reference),str(domain["manager"]))
    batch=delivery.create_batch({"branch_id":str(domain["a"]),"delivery_date":"2099-08-01","driver_id":str(domain["driver"]),"vehicle_id":str(domain["vehicle"]),"field_agent_id":str(domain["agent"]),"delivery_order_ids":[order["id"]]},str(domain["manager"]))
    return order,batch


def test_assignment_conflict_and_vehicle_unavailability(domain):
    _scheduled(domain)
    other=delivery.create_order(order_payload(domain["a"],"SL-2"),str(domain["manager"]))
    with pytest.raises(ApiError) as conflict:
        delivery.create_batch({"branch_id":str(domain["a"]),"delivery_date":"2099-08-01","driver_id":str(domain["driver"]),"vehicle_id":str(domain["vehicle"]),"field_agent_id":str(domain["agent"]),"delivery_order_ids":[other["id"]]},str(domain["manager"]))
    assert conflict.value.status_code==409
    domain["db"].vehicles.update_one({"_id":domain["vehicle"]},{"$set":{"status":"maintenance"}})
    with pytest.raises(ApiError) as unavailable:
        delivery.create_batch({"branch_id":str(domain["a"]),"delivery_date":"2099-08-02","driver_id":str(domain["driver"]),"vehicle_id":str(domain["vehicle"]),"field_agent_id":str(domain["agent"]),"delivery_order_ids":[other["id"]]},str(domain["manager"]))
    assert unavailable.value.status_code==409


def test_partial_delivery_return_and_idempotent_reconciliation(domain):
    order,batch=_scheduled(domain); line=order["product_lines"][0]
    issue=delivery.issue_batch(batch["id"],{"items":[{"delivery_order_id":order["id"],"line_id":line["line_id"],"issued_quantity":5,"condition":"good"}]},str(domain["officer"]))
    assert issue["status"]=="awaiting_driver_acknowledgement"
    first_ack=delivery.acknowledge_issue(batch["id"],str(domain["driver"])); second_ack=delivery.acknowledge_issue(batch["id"],str(domain["driver"]))
    assert first_ack["acknowledged_at"] and second_ack["acknowledged_at"]
    assert domain["db"].item_issues.count_documents({"batch_id":ObjectId(batch["id"]),"status":"acknowledged"})==1
    delivery.driver_batch_action(batch["id"],"accept",str(domain["driver"])); delivery.driver_batch_action(batch["id"],"start",str(domain["driver"]))
    updated=delivery.record_delivery(order["id"],{"items":[{"line_id":line["line_id"],"quantity_delivered":3}],"exception_type":"customer_unavailable"},str(domain["driver"]))
    assert updated["status"]=="partially_delivered"
    delivery.driver_batch_action(batch["id"],"complete",str(domain["driver"]))
    delivery.record_return(batch["id"],{"items":[{"delivery_order_id":order["id"],"line_id":line["line_id"],"returned_quantity":2,"condition":"good"}]},str(domain["officer"]))
    reconciled=delivery.reconcile_batch(batch["id"],{},str(domain["manager"])); repeated=delivery.reconcile_batch(batch["id"],{},str(domain["manager"]))
    assert reconciled["status"]=="reconciled" and repeated["reconciled"] is True
    assert domain["db"].delivery_orders.find_one({"_id":ObjectId(order["id"])})["locked"] is True


def test_reconciliation_rejects_variance_and_driver_ownership_is_scoped(domain):
    order,batch=_scheduled(domain); line=order["product_lines"][0]
    delivery.issue_batch(batch["id"],{"items":[{"delivery_order_id":order["id"],"line_id":line["line_id"],"issued_quantity":5}]},str(domain["officer"]))
    delivery.acknowledge_issue(batch["id"],str(domain["driver"])); delivery.driver_batch_action(batch["id"],"accept",str(domain["driver"])); delivery.driver_batch_action(batch["id"],"start",str(domain["driver"])); delivery.driver_batch_action(batch["id"],"complete",str(domain["driver"]))
    delivery.record_return(batch["id"],{"items":[{"delivery_order_id":order["id"],"line_id":line["line_id"],"returned_quantity":4,"condition":"good"}]},str(domain["officer"]))
    with pytest.raises(ApiError) as variance: delivery.reconcile_batch(batch["id"],{},str(domain["manager"]))
    assert variance.value.status_code==409
    stranger=ObjectId(); domain["db"].users.insert_one({"_id":stranger,"role":"driver","status":"active","primary_branch_id":domain["a"]})
    assert delivery.list_batches(str(stranger),{})["count"]==0


def test_reassignment_cancellation_and_issue_correction_are_auditable_transitions(domain):
    order,batch=_scheduled(domain); line=order["product_lines"][0]
    other_driver=ObjectId(); domain["db"].users.insert_one({"_id":other_driver,"role":"driver","status":"active","primary_branch_id":domain["a"],"allowed_branch_ids":[domain["a"]]})
    reassigned=delivery.reassign_batch(batch["id"],{"driver_id":str(other_driver),"reason":"Primary driver unavailable"},str(domain["manager"]))
    assert reassigned["driver_id"]==str(other_driver)
    delivery.issue_batch(batch["id"],{"items":[{"delivery_order_id":order["id"],"line_id":line["line_id"],"issued_quantity":5}]},str(domain["officer"]))
    corrected=delivery.correct_issue(batch["id"],{"reason":"Count verified at loading bay","items":[{"delivery_order_id":order["id"],"line_id":line["line_id"],"issued_quantity":4}]},str(domain["manager"]))
    assert corrected["corrections"][0]["reason"]=="Count verified at loading bay"
    cancelled=delivery.cancel_batch(batch["id"],"Customer requested reschedule",str(domain["manager"]))
    assert cancelled["status"]=="cancelled"
    assert domain["db"].delivery_orders.find_one({"_id":ObjectId(order["id"])})["status"]=="ready_for_planning"
