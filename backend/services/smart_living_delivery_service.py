from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from uuid import uuid4

from bson import ObjectId
from flask import current_app
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.smart_living_delivery import serialize_batch, serialize_custody, serialize_delivery
from services.branch_access_service import assert_branch_access, assert_user_in_branch, branch_query, current_user, object_id
from services.notification_service import create_notification
from services.driver_scope_service import driver_ids_visible_to_branch_user
from services.rbac_service import user_has_permission, user_role_codes, write_audit
from utils.api_error import ApiError
from utils.file_validation import validate_attachment_list


ORDER_STATUSES = {"draft", "ready_for_planning", "scheduled", "issued", "in_progress", "partially_delivered", "delivered", "undelivered", "returned", "reconciled", "cancelled"}
BATCH_STATUSES = {"draft", "scheduled", "awaiting_issue", "issued", "accepted", "in_progress", "returning", "awaiting_reconciliation", "reconciled", "cancelled"}
FINAL_BATCH_STATUSES = {"reconciled", "cancelled"}
AGENT_ROLE_CODES = {"field_agent", "sales_agent", "responsible_agent", "agent"}
TRANSPORT_METHODS = {"VEHICLE", "KAYA", "OTHER_MANUAL"}


def now_utc(): return datetime.now(timezone.utc)
def orders(): return get_collection("delivery_orders")
def batches(): return get_collection("delivery_batches")
def issues(): return get_collection("item_issues")
def returns(): return get_collection("item_returns")
def exceptions(): return get_collection("delivery_exceptions")
def investigations(): return get_collection("delivery_exception_investigations")
def users(): return get_collection("users")


@contextmanager
def _transaction():
    """Use Mongo transactions when supported; mongomock/standalone dev remains usable."""
    session = None
    try:
        session = batches().database.client.start_session()
        session.start_transaction()
    except (AttributeError, NotImplementedError):
        if session:
            session.end_session()
        yield None
        return
    try:
        yield session
        session.commit_transaction()
    except Exception:
        session.abort_transaction()
        raise
    finally:
        session.end_session()


def _session(session):
    return {"session": session} if session is not None else {}


def ensure_indexes():
    get_collection("branches").create_index([("code", ASCENDING)], unique=True)
    get_collection("branches").create_index([("status", ASCENDING), ("name", ASCENDING)])
    orders().create_index([("external_source", ASCENDING), ("external_reference", ASCENDING)], unique=True)
    orders().create_index([("branch_id", ASCENDING), ("status", ASCENDING), ("requested_delivery_date", ASCENDING)])
    orders().create_index([("assigned_field_agent_id", ASCENDING), ("status", ASCENDING)])
    batches().create_index([("batch_number", ASCENDING)], unique=True)
    batches().create_index([("branch_id", ASCENDING), ("delivery_date", ASCENDING), ("status", ASCENDING)])
    batches().create_index([("driver_id", ASCENDING), ("delivery_date", ASCENDING), ("status", ASCENDING)])
    batches().create_index([("vehicle_id", ASCENDING), ("delivery_date", ASCENDING), ("status", ASCENDING)])
    batches().create_index([("assigned_agent_ids", ASCENDING), ("delivery_date", ASCENDING), ("status", ASCENDING)])
    issues().create_index([("batch_id", ASCENDING)], unique=True)
    returns().create_index([("batch_id", ASCENDING), ("created_at", DESCENDING)])
    returns().create_index([("source_key", ASCENDING)], unique=True, sparse=True)
    exceptions().create_index([("delivery_batch_id", ASCENDING), ("status", ASCENDING), ("severity", ASCENDING)])
    exceptions().create_index([("branch_id", ASCENDING), ("created_at", DESCENDING)])
    exceptions().create_index([("source_key", ASCENDING)], unique=True, sparse=True)
    investigations().create_index([("delivery_exception_id", ASCENDING)], unique=True)
    get_collection("audit_logs").create_index([("branch_id", ASCENDING), ("created_at", DESCENDING)])


def reconcile_tomorrow_delivery_notifications() -> dict:
    tomorrow = (now_utc().date() + timedelta(days=1)).isoformat(); sent = 0
    for run in batches().find({"delivery_date": tomorrow, "status": {"$nin": ["CANCELLED", "COMPLETED", "CLOSED"]}}):
        recipients = {item for item in [run.get("driver_id"), *(run.get("assigned_agent_ids") or [])] if item} | _branch_manager_ids(run["branch_id"])
        readiness = review_run(run)["readiness"]
        for recipient in recipients:
            create_notification(recipient, "Tomorrow delivery reminder", f"{run.get('run_number') or run.get('batch_number')} is planned for tomorrow. Readiness: {readiness.replace('_', ' ').title()}.", category="operations", module="smart-living-deliveries", priority="high" if readiness != "READY" else "medium", reference_type="delivery_run", reference_id=run["_id"], action_url="smart-living-deliveries", action_label="Review tomorrow plan", dedupe_key=f"tomorrow-delivery:{tomorrow}:{run['_id']}:{recipient}")
            sent += 1
    for order in orders().find({"requested_delivery_date": tomorrow, "status": {"$in": ["CERTIFIED", "WAITING_SCHEDULING", "ready_for_planning"]}, "$or": [{"batch_id": None}, {"batch_id": {"$exists": False}}]}):
        for recipient in _branch_manager_ids(order["branch_id"]):
            create_notification(recipient, "Tomorrow delivery needs planning", f"{order.get('customer_name') or 'A branch delivery'} is due tomorrow and has no daily run.", category="operations", module="smart-living-deliveries", priority="high", reference_type="delivery_order", reference_id=order["_id"], action_url="branch-operations", action_label="Plan delivery", dedupe_key=f"tomorrow-unplanned:{tomorrow}:{order['_id']}:{recipient}")
            sent += 1
    return {"date": tomorrow, "notifications_reconciled": sent}


def _line(payload: dict, index: int) -> dict:
    name = str(payload.get("product_name") or "").strip()
    quantity = int(payload.get("quantity_requested") or 0)
    if not name or quantity <= 0: raise ApiError(f"Product line {index + 1} requires a name and positive quantity.", status_code=400)
    return {"line_id": str(payload.get("line_id") or uuid4()), "product_id": payload.get("product_id"), "product_name": name, "description": payload.get("description"), "quantity_requested": quantity, "quantity_issued": 0, "quantity_delivered": 0, "quantity_returned": 0, "quantity_exception": 0, "exception_reason": None, "condition": payload.get("condition") or "good", "notes": payload.get("notes")}


def _audit(action, actor, entity, entity_id, branch_id, old=None, new=None, reason=None):
    write_audit(action, actor, entity, entity_id, {"old": old or {}, "new": new or {}, "reason": reason}, {"branch_id": str(branch_id)})


def _branch_manager_ids(branch_id):
    result = set()
    query = {"status": "active", "$or": [{"role": "branch_manager"}, {"role_ids": "branch_manager"}]}
    for user in users().find(query):
        try:
            assert_branch_access(user, branch_id)
        except ApiError:
            continue
        result.add(user["_id"])
    return result


def _notify_branch_managers(branch_id, title, message, event, reference_id, *, priority="medium"):
    for recipient in _branch_manager_ids(branch_id):
        create_notification(recipient, title, message, category="operations", module="smart-living-deliveries", priority=priority, reference_type="delivery_order", reference_id=reference_id, action_url="branch-operations", action_label="Open Branch Operations", dedupe_key=f"branch-delivery:{reference_id}:{event}:{recipient}")


def create_order(payload: dict, actor_id: str) -> dict:
    user = current_user(actor_id); branch_id = assert_branch_access(user, payload.get("branch_id"), require_active=True)
    reference = str(payload.get("external_reference") or "").strip()
    if not reference: raise ApiError("external_reference is required.", status_code=400)
    product_lines = [_line(item, index) for index, item in enumerate(payload.get("product_lines") or [])]
    if not product_lines: raise ApiError("At least one product line is required.", status_code=400)
    field_agent_id = object_id(payload["assigned_field_agent_id"], "assigned_field_agent_id") if payload.get("assigned_field_agent_id") else None
    if field_agent_id: assert_user_in_branch(field_agent_id, branch_id, AGENT_ROLE_CODES)
    timestamp = now_utc(); document = {"branch_id": branch_id, "external_source": "Smart Living", "external_reference": reference, "customer_name": str(payload.get("customer_name") or "").strip(), "customer_phone": str(payload.get("customer_phone") or "").strip(), "alternative_phone": payload.get("alternative_phone"), "delivery_address": str(payload.get("delivery_address") or "").strip(), "gps_location": payload.get("gps_location"), "assigned_field_agent_id": field_agent_id, "requested_delivery_date": payload.get("requested_delivery_date"), "notes": payload.get("notes"), "status": str(payload.get("status") or "draft").lower(), "product_lines": product_lines, "created_by": object_id(actor_id), "created_at": timestamp, "updated_at": timestamp, "locked": False}
    if not document["customer_name"] or not document["customer_phone"] or not document["delivery_address"]: raise ApiError("Customer name, phone, and delivery address are required.", status_code=400)
    if document["status"] not in {"draft", "ready_for_planning"}: raise ApiError("A new delivery must be Draft or Ready for Planning.", status_code=400)
    try: result = orders().insert_one(document)
    except DuplicateKeyError: raise ApiError("A Smart Living delivery already exists for this external reference.", status_code=409) from None
    document["_id"] = result.inserted_id; _audit("delivery_created", actor_id, "delivery_order", result.inserted_id, branch_id, new=document)
    _notify_branch_managers(branch_id, "New branch delivery", f"{document['customer_name']} is ready for branch planning.", "created", result.inserted_id)
    return serialize_delivery(document)


def list_orders(actor_id: str, filters: dict) -> dict:
    user = current_user(actor_id); query = branch_query(user)
    if filters.get("branch_id"):
        branch_id = assert_branch_access(user, filters["branch_id"]); query["branch_id"] = branch_id
    if filters.get("status"): query["status"] = filters["status"]
    if filters.get("assigned_field_agent_id"): query["assigned_field_agent_id"] = object_id(filters["assigned_field_agent_id"])
    page=max(int(filters.get("page") or 1),1); size=min(max(int(filters.get("page_size") or 25),1),100)
    total=orders().count_documents(query); rows=orders().find(query).sort("created_at", DESCENDING).skip((page-1)*size).limit(size)
    return {"orders": [serialize_delivery(row) for row in rows], "pagination": {"page":page,"page_size":size,"total":total,"total_pages":max(1,(total+size-1)//size)}}


def get_order(order_id: str, actor_id: str) -> dict:
    user=current_user(actor_id); query={"_id":object_id(order_id), **branch_query(user)}; document=orders().find_one(query)
    if not document: raise ApiError("Delivery order not found.", status_code=404)
    return serialize_delivery(document)


def create_batch(payload: dict, actor_id: str) -> dict:
    user=current_user(actor_id); branch_id=assert_branch_access(user,payload.get("branch_id"),require_active=True)
    delivery_date=str(payload.get("delivery_date") or "").strip()
    if not delivery_date: raise ApiError("delivery_date is required.", status_code=400)
    driver_id=object_id(payload.get("driver_id"),"driver_id"); vehicle_id=object_id(payload.get("vehicle_id"),"vehicle_id"); agent_id=object_id(payload.get("field_agent_id"),"field_agent_id")
    assert_user_in_branch(driver_id,branch_id,{"driver"}); assert_user_in_branch(agent_id,branch_id,AGENT_ROLE_CODES)
    vehicle=get_collection("vehicles").find_one({"_id":vehicle_id})
    if not vehicle or str(vehicle.get("status") or "").lower() not in {"active","available"}: raise ApiError("Vehicle is unavailable.",status_code=409)
    if vehicle.get("branch_id") and object_id(vehicle["branch_id"]) != branch_id: raise ApiError("Vehicle does not belong to the selected branch.",status_code=409)
    overlap={"delivery_date":delivery_date,"status":{"$nin":list(FINAL_BATCH_STATUSES)},"$or":[{"driver_id":driver_id},{"vehicle_id":vehicle_id}]}
    if batches().find_one(overlap): raise ApiError("Driver or vehicle already has an overlapping delivery batch.",status_code=409)
    ids=[object_id(value,"delivery_order_id") for value in payload.get("delivery_order_ids") or []]
    found=list(orders().find({"_id":{"$in":ids},"branch_id":branch_id,"status":"ready_for_planning","locked":False}))
    if not ids or len(found)!=len(set(ids)): raise ApiError("All deliveries must be Ready for Planning in the selected branch.",status_code=409)
    timestamp=now_utc(); number=f"SL-{timestamp:%Y%m%d}-{str(uuid4())[:6].upper()}"; document={"batch_number":number,"branch_id":branch_id,"delivery_date":delivery_date,"driver_id":driver_id,"vehicle_id":vehicle_id,"field_agent_id":agent_id,"delivery_order_ids":ids,"route_sequence":ids,"status":"scheduled","created_by":object_id(actor_id),"created_at":timestamp,"updated_at":timestamp,"assignment_history":[{"driver_id":driver_id,"vehicle_id":vehicle_id,"field_agent_id":agent_id,"changed_by":object_id(actor_id),"changed_at":timestamp,"reason":"Initial assignment"}],"reconciled":False}
    result=batches().insert_one(document); document["_id"]=result.inserted_id
    orders().update_many({"_id":{"$in":ids}},{"$set":{"status":"scheduled","batch_id":result.inserted_id,"assigned_field_agent_id":agent_id,"updated_at":timestamp}})
    _audit("batch_created",actor_id,"delivery_batch",result.inserted_id,branch_id,new=document)
    for recipient in (driver_id,agent_id):
        create_notification(recipient,"Smart Living delivery batch assigned",f"{number} is scheduled for {delivery_date}.",category="operations",module="my-operational-tasks",priority="high",reference_type="delivery_batch",reference_id=result.inserted_id,action_url="my-operational-tasks",action_label="View Batch",dedupe_key=f"delivery-batch:{result.inserted_id}:{recipient}")
    return serialize_batch(document)


def reassign_batch(batch_id: str, payload: dict, actor_id: str) -> dict:
    user=current_user(actor_id); batch=batches().find_one({"_id":object_id(batch_id),**branch_query(user)})
    if not batch: raise ApiError("Delivery batch not found.",status_code=404)
    if batch["status"] not in {"scheduled","awaiting_issue","issued","accepted"}: raise ApiError("A batch cannot be reassigned after the trip starts.",status_code=409)
    driver_id=object_id(payload.get("driver_id") or batch["driver_id"],"driver_id"); vehicle_id=object_id(payload.get("vehicle_id") or batch["vehicle_id"],"vehicle_id"); agent_id=object_id(payload.get("field_agent_id") or batch["field_agent_id"],"field_agent_id")
    assert_user_in_branch(driver_id,batch["branch_id"],{"driver"}); assert_user_in_branch(agent_id,batch["branch_id"],AGENT_ROLE_CODES)
    vehicle=get_collection("vehicles").find_one({"_id":vehicle_id})
    if not vehicle or str(vehicle.get("status") or "").lower() not in {"active","available"}: raise ApiError("Vehicle is unavailable.",status_code=409)
    overlap={"_id":{"$ne":batch["_id"]},"delivery_date":batch["delivery_date"],"status":{"$nin":list(FINAL_BATCH_STATUSES)},"$or":[{"driver_id":driver_id},{"vehicle_id":vehicle_id}]}
    if batches().find_one(overlap): raise ApiError("Driver or vehicle already has an overlapping delivery batch.",status_code=409)
    reason=str(payload.get("reason") or "").strip()
    if not reason: raise ApiError("A reassignment reason is required.",status_code=400)
    timestamp=now_utc(); old={key:batch.get(key) for key in ("driver_id","vehicle_id","field_agent_id")}; new={"driver_id":driver_id,"vehicle_id":vehicle_id,"field_agent_id":agent_id}; history={**new,"changed_by":object_id(actor_id),"changed_at":timestamp,"reason":reason}
    batches().update_one({"_id":batch["_id"]},{"$set":{**new,"updated_at":timestamp},"$push":{"assignment_history":history}}); batch.update(new)
    _audit("delivery_batch_reassigned",actor_id,"delivery_batch",batch["_id"],batch["branch_id"],old=old,new=new,reason=reason)
    for recipient in {driver_id,agent_id,*[value for value in (old["driver_id"],old["field_agent_id"]) if value]}:
        create_notification(recipient,"Smart Living schedule changed",f"{batch['batch_number']} assignment changed: {reason}",category="operations",module="my-operational-tasks",priority="high",reference_type="delivery_batch",reference_id=batch["_id"],action_url="my-operational-tasks",action_label="Review Schedule",dedupe_key=f"delivery-reassigned:{batch['_id']}:{recipient}:{timestamp.timestamp()}")
    return serialize_batch(batch)


def cancel_batch(batch_id: str, reason: str, actor_id: str) -> dict:
    user=current_user(actor_id); batch=batches().find_one({"_id":object_id(batch_id),**branch_query(user)})
    if not batch: raise ApiError("Delivery batch not found.",status_code=404)
    if batch["status"] in {"in_progress","returning","awaiting_reconciliation","reconciled","cancelled"}: raise ApiError("This batch can no longer be cancelled.",status_code=409)
    reason=str(reason or "").strip()
    if not reason: raise ApiError("A cancellation reason is required.",status_code=400)
    timestamp=now_utc(); batches().update_one({"_id":batch["_id"]},{"$set":{"status":"cancelled","cancelled_at":timestamp,"cancelled_by":object_id(actor_id),"cancellation_reason":reason,"updated_at":timestamp}}); orders().update_many({"_id":{"$in":batch["delivery_order_ids"]}},{"$set":{"status":"ready_for_planning","batch_id":None,"updated_at":timestamp}}); batch["status"]="cancelled"
    _audit("delivery_batch_cancelled",actor_id,"delivery_batch",batch["_id"],batch["branch_id"],reason=reason)
    for recipient in (batch["driver_id"],batch["field_agent_id"]): create_notification(recipient,"Delivery batch cancelled",f"{batch['batch_number']} was cancelled: {reason}",category="operations",module="notifications",priority="high",reference_type="delivery_batch",reference_id=batch["_id"],action_url="notifications",action_label="View Notice",dedupe_key=f"delivery-cancelled:{batch['_id']}:{recipient}")
    return serialize_batch(batch)


def list_batches(actor_id: str, filters: dict, *, own_role=None) -> dict:
    user=current_user(actor_id); query=branch_query(user)
    role=str(user.get("role") or "").lower()
    if role=="driver": query["driver_id"]=object_id(actor_id)
    if role=="field_agent": query["field_agent_id"]=object_id(actor_id)
    if filters.get("branch_id"): query["branch_id"]=assert_branch_access(user,filters["branch_id"])
    if filters.get("status"): query["status"]=filters["status"]
    rows=[]
    for batch in batches().find(query).sort([("delivery_date",ASCENDING),("created_at",DESCENDING)]).limit(100):
        batch["delivery_orders"]=[serialize_delivery(item) for item in orders().find({"_id":{"$in":batch.get("delivery_order_ids",[])}})]
        rows.append(serialize_batch(batch))
    return {"batches":rows,"count":len(rows)}


def issue_batch(batch_id: str, payload: dict, actor_id: str) -> dict:
    user=current_user(actor_id); batch=batches().find_one({"_id":object_id(batch_id),**branch_query(user)})
    if not batch: raise ApiError("Delivery batch not found.",status_code=404)
    if batch["status"] not in {"scheduled","awaiting_issue"}: raise ApiError("This batch cannot be issued in its current state.",status_code=409)
    lines=[]; updates={}
    for item in payload.get("items") or []:
        order_id=object_id(item.get("delivery_order_id")); line_id=str(item.get("line_id") or ""); qty=int(item.get("issued_quantity") or 0)
        order=orders().find_one({"_id":order_id,"batch_id":batch["_id"]}); line=next((line for line in (order or {}).get("product_lines",[]) if line["line_id"]==line_id),None)
        if not line or qty<0 or qty>line["quantity_requested"]: raise ApiError("Issued quantity is invalid.",status_code=400)
        lines.append({"delivery_order_id":order_id,"line_id":line_id,"product_name":line["product_name"],"issued_quantity":qty,"condition":item.get("condition") or "good","notes":item.get("notes")})
        updates.setdefault(order_id,{})[line_id]=qty
    if not lines: raise ApiError("At least one issued item is required.",status_code=400)
    timestamp=now_utc(); document={"branch_id":batch["branch_id"],"batch_id":batch["_id"],"driver_id":batch["driver_id"],"vehicle_id":batch["vehicle_id"],"field_agent_id":batch["field_agent_id"],"issuing_officer_id":object_id(actor_id),"issue_timestamp":timestamp,"items":lines,"status":"awaiting_driver_acknowledgement","created_at":timestamp,"corrections":[]}
    try: result=issues().insert_one(document)
    except DuplicateKeyError: raise ApiError("This batch has already been issued.",status_code=409) from None
    for order_id,line_values in updates.items():
        order=orders().find_one({"_id":order_id}); product_lines=order["product_lines"]
        for line in product_lines: line["quantity_issued"]=line_values.get(line["line_id"],line["quantity_issued"])
        orders().update_one({"_id":order_id},{"$set":{"product_lines":product_lines,"status":"issued","updated_at":timestamp}})
    batches().update_one({"_id":batch["_id"]},{"$set":{"status":"awaiting_issue","item_issue_id":result.inserted_id,"updated_at":timestamp}})
    document["_id"]=result.inserted_id; _audit("items_issued",actor_id,"item_issue",result.inserted_id,batch["branch_id"],new=document)
    return serialize_custody(document)


def acknowledge_issue(batch_id: str, actor_id: str) -> dict:
    batch=batches().find_one({"_id":object_id(batch_id),"driver_id":object_id(actor_id)})
    if not batch: raise ApiError("Assigned delivery batch not found.",status_code=404)
    issue=issues().find_one({"batch_id":batch["_id"]})
    if not issue: raise ApiError("No item issue is awaiting acknowledgement.",status_code=409)
    if issue.get("acknowledged_at"): return serialize_custody(issue)
    timestamp=now_utc(); issues().update_one({"_id":issue["_id"]},{"$set":{"status":"acknowledged","acknowledged_by":object_id(actor_id),"acknowledged_at":timestamp}}); batches().update_one({"_id":batch["_id"]},{"$set":{"status":"issued","updated_at":timestamp}})
    issue.update({"status":"acknowledged","acknowledged_by":object_id(actor_id),"acknowledged_at":timestamp}); _audit("driver_acknowledged_items",actor_id,"item_issue",issue["_id"],batch["branch_id"])
    return serialize_custody(issue)


def correct_issue(batch_id: str, payload: dict, actor_id: str) -> dict:
    user=current_user(actor_id); batch=batches().find_one({"_id":object_id(batch_id),**branch_query(user)}); reason=str(payload.get("reason") or "").strip()
    if not batch: raise ApiError("Delivery batch not found.",status_code=404)
    if not reason: raise ApiError("A correction reason is required.",status_code=400)
    issue=issues().find_one({"batch_id":batch["_id"]})
    if not issue: raise ApiError("Item issue not found.",status_code=404)
    timestamp=now_utc(); old=[]; new=[]
    for correction in payload.get("items") or []:
        order_id=object_id(correction.get("delivery_order_id")); line_id=str(correction.get("line_id")); quantity=int(correction.get("issued_quantity") or 0); order=orders().find_one({"_id":order_id,"batch_id":batch["_id"],"locked":False}); line=next((item for item in (order or {}).get("product_lines",[]) if item["line_id"]==line_id),None)
        if not line or quantity<line["quantity_delivered"]+line["quantity_returned"]+line["quantity_exception"] or quantity>line["quantity_requested"]: raise ApiError("Corrected quantity is invalid.",status_code=409)
        old.append({"delivery_order_id":order_id,"line_id":line_id,"issued_quantity":line["quantity_issued"]}); new.append({"delivery_order_id":order_id,"line_id":line_id,"issued_quantity":quantity}); orders().update_one({"_id":order_id,"product_lines.line_id":line_id},{"$set":{"product_lines.$.quantity_issued":quantity,"updated_at":timestamp}})
        issues().update_one({"_id":issue["_id"],"items.delivery_order_id":order_id,"items.line_id":line_id},{"$set":{"items.$.issued_quantity":quantity}})
    if not new: raise ApiError("At least one correction is required.",status_code=400)
    correction_record={"old":old,"new":new,"reason":reason,"corrected_by":object_id(actor_id),"corrected_at":timestamp}; issues().update_one({"_id":issue["_id"]},{"$push":{"corrections":correction_record}}); _audit("item_issue_corrected",actor_id,"item_issue",issue["_id"],batch["branch_id"],old=old,new=new,reason=reason)
    return serialize_custody(issues().find_one({"_id":issue["_id"]}))


def driver_batch_action(batch_id: str, action: str, actor_id: str) -> dict:
    batch=batches().find_one({"_id":object_id(batch_id),"driver_id":object_id(actor_id)})
    if not batch: raise ApiError("Assigned delivery batch not found.",status_code=404)
    transitions={"accept":({"issued"},"accepted"),"start":({"accepted"},"in_progress"),"complete":({"in_progress"},"returning")}
    allowed,target=transitions.get(action,(set(),None))
    if batch["status"] not in allowed: raise ApiError("Batch action is not allowed in its current state.",status_code=409)
    timestamp=now_utc(); batches().update_one({"_id":batch["_id"]},{"$set":{"status":target,f"{action}ed_at":timestamp,"updated_at":timestamp}}); batch["status"]=target
    orders().update_many({"_id":{"$in":batch["delivery_order_ids"]}},{"$set":{"status":"in_progress" if target=="in_progress" else "issued","updated_at":timestamp}})
    _audit(f"delivery_batch_{action}",actor_id,"delivery_batch",batch["_id"],batch["branch_id"],new={"status":target}); return serialize_batch(batch)


def record_delivery(order_id: str, payload: dict, actor_id: str) -> dict:
    order=orders().find_one({"_id":object_id(order_id)}); actor=object_id(actor_id)
    if not order: raise ApiError("Delivery order not found.",status_code=404)
    batch=batches().find_one({"_id":order.get("batch_id"),"driver_id":actor,"status":"in_progress"})
    if not batch: raise ApiError("You may update only your active assigned deliveries.",status_code=403)
    quantities={str(item.get("line_id")):item for item in payload.get("items") or []}; product_lines=order["product_lines"]
    for line in product_lines:
        if line["line_id"] not in quantities: continue
        item=quantities[line["line_id"]]; delivered=int(item.get("quantity_delivered") or 0); exception=int(item.get("quantity_exception") or 0)
        if delivered<0 or exception<0 or delivered+exception>line["quantity_issued"]: raise ApiError("Delivery quantities exceed the issued quantity.",status_code=409)
        line.update({"quantity_delivered":delivered,"quantity_exception":exception,"exception_reason":item.get("exception_reason"),"notes":item.get("notes")})
    issued=sum(line["quantity_issued"] for line in product_lines); delivered=sum(line["quantity_delivered"] for line in product_lines)
    status="delivered" if delivered==issued and issued>0 else "partially_delivered" if delivered>0 else "undelivered"
    timestamp=now_utc(); updates={"product_lines":product_lines,"status":status,"delivered_at":timestamp,"delivery_note":payload.get("note"),"delivery_exception_type":payload.get("exception_type"),"updated_at":timestamp}
    orders().update_one({"_id":order["_id"]},{"$set":updates}); order.update(updates); _audit("delivery_quantities_recorded",actor_id,"delivery_order",order["_id"],order["branch_id"],new=updates,reason=payload.get("exception_type"))
    if status in {"partially_delivered", "undelivered"}:
        _notify_branch_managers(order["branch_id"], "Delivery requires attention", f"{order.get('customer_name') or 'A branch delivery'} was {status.replace('_', ' ')}.", status, order["_id"], priority="high")
    return serialize_delivery(order)


def confirm_delivery(order_id: str, payload: dict, actor_id: str) -> dict:
    order=orders().find_one({"_id":object_id(order_id),"assigned_field_agent_id":object_id(actor_id)})
    if not order: raise ApiError("Assigned delivery order not found.",status_code=404)
    if order["status"] not in {"delivered","partially_delivered","undelivered"}: raise ApiError("Delivery quantities must be recorded before confirmation.",status_code=409)
    timestamp=now_utc(); confirmation={"confirmed_by":object_id(actor_id),"confirmed_at":timestamp,"note":payload.get("note"),"customer_confirmed":bool(payload.get("customer_confirmed"))}; orders().update_one({"_id":order["_id"]},{"$set":{"field_agent_confirmation":confirmation,"updated_at":timestamp}}); order["field_agent_confirmation"]=confirmation; _audit("delivery_confirmed",actor_id,"delivery_order",order["_id"],order["branch_id"],new=confirmation)
    return serialize_delivery(order)


def record_return(batch_id: str, payload: dict, actor_id: str) -> dict:
    user=current_user(actor_id); batch=batches().find_one({"_id":object_id(batch_id),**branch_query(user)})
    if not batch: raise ApiError("Delivery batch not found.",status_code=404)
    if batch["status"] not in {"returning","in_progress","awaiting_reconciliation"}: raise ApiError("This batch is not ready for returns.",status_code=409)
    timestamp=now_utc(); recorded=[]
    for item in payload.get("items") or []:
        order_id=object_id(item.get("delivery_order_id")); line_id=str(item.get("line_id")); qty=int(item.get("returned_quantity") or 0); condition=str(item.get("condition") or "good").lower()
        order=orders().find_one({"_id":order_id,"batch_id":batch["_id"]}); line=next((line for line in (order or {}).get("product_lines",[]) if line["line_id"]==line_id),None)
        if not line or qty<0 or line["quantity_delivered"]+qty+line["quantity_exception"]>line["quantity_issued"]: raise ApiError("Returned quantity is invalid.",status_code=409)
        line["quantity_returned"]=qty; orders().update_one({"_id":order_id,"product_lines.line_id":line_id},{"$set":{"product_lines.$.quantity_returned":qty,"status":"returned","updated_at":timestamp}})
        record={"delivery_order_id":order_id,"line_id":line_id,"product_name":line["product_name"],"returned_quantity":qty,"condition":condition,"notes":item.get("notes"),"variance_reason":item.get("variance_reason")}; recorded.append(record)
        if condition in {"damaged","missing","wrong_item","other_exception"}:
            get_collection("delivery_exceptions").insert_one({"exception_number":f"DEX-{timestamp:%Y%m%d}-{str(uuid4())[:6].upper()}","delivery_order_id":order_id,"delivery_batch_id":batch["_id"],"driver_id":batch["driver_id"],"branch_id":batch["branch_id"],"status":"open","items":[record],"notes":item.get("variance_reason"),"reported_by":object_id(actor_id),"reported_at":timestamp,"created_at":timestamp,"updated_at":timestamp})
    document={"branch_id":batch["branch_id"],"batch_id":batch["_id"],"driver_id":batch["driver_id"],"receiving_officer_id":object_id(actor_id),"return_timestamp":timestamp,"items":recorded,"created_at":timestamp}; result=returns().insert_one(document); document["_id"]=result.inserted_id
    batches().update_one({"_id":batch["_id"]},{"$set":{"status":"awaiting_reconciliation","updated_at":timestamp}}); _audit("items_returned",actor_id,"item_return",result.inserted_id,batch["branch_id"],new=document)
    return serialize_custody(document)


def reconciliation_totals(product_lines: list[dict]) -> dict:
    totals={key:sum(int(line.get(key) or 0) for line in product_lines) for key in ("quantity_issued","quantity_delivered","quantity_returned","quantity_exception")}
    totals["variance"]=totals["quantity_issued"]-totals["quantity_delivered"]-totals["quantity_returned"]-totals["quantity_exception"]
    return totals


def reconcile_batch(batch_id: str, payload: dict, actor_id: str) -> dict:
    user=current_user(actor_id); batch=batches().find_one({"_id":object_id(batch_id),**branch_query(user)})
    if not batch: raise ApiError("Delivery batch not found.",status_code=404)
    if batch.get("reconciled"): return serialize_batch(batch)
    if batch["status"]!="awaiting_reconciliation": raise ApiError("Batch is not awaiting reconciliation.",status_code=409)
    order_rows=list(orders().find({"_id":{"$in":batch["delivery_order_ids"]}})); summaries=[]
    for order in order_rows:
        totals=reconciliation_totals(order["product_lines"]); summaries.append({"delivery_order_id":order["_id"],**totals})
        if totals["variance"]!=0: raise ApiError("Reconciliation failed because issued quantities do not balance.",status_code=409,errors=[{"delivery_order_id":str(order["_id"]),"totals":totals}])
    timestamp=now_utc(); updates={"status":"reconciled","reconciled":True,"reconciled_at":timestamp,"reconciled_by":object_id(actor_id),"reconciliation_summary":summaries,"reconciliation_note":payload.get("note"),"updated_at":timestamp}
    batches().update_one({"_id":batch["_id"],"reconciled":{"$ne":True}},{"$set":updates}); orders().update_many({"_id":{"$in":batch["delivery_order_ids"]}},{"$set":{"status":"reconciled","locked":True,"updated_at":timestamp}}); batch.update(updates); _audit("delivery_reconciled",actor_id,"delivery_batch",batch["_id"],batch["branch_id"],new=updates)
    return serialize_batch(batch)


# Central Delivery Scheduler -------------------------------------------------
# These functions deliberately use the existing delivery_orders and
# delivery_batches collections. Legacy Smart Living fields are written as
# aliases so the custody/execution workflow can consume a published run later.

CERTIFIED_ORDER_STATUSES = {
    "DRAFT", "CERTIFIED", "WAITING_SCHEDULING", "SCHEDULED", "IN_DELIVERY",
    "PARTIALLY_DELIVERED", "DELIVERED", "RETURN_PENDING", "EXCEPTION",
    "CLOSED", "CANCELLED",
}
DELIVERY_TYPES = {"FULLY_COMPLETED_PRODUCT", "CLOSED_CONTRIBUTION_CONVERSION", "OTHER_APPROVED_PRODUCT"}
RUN_STATUSES = {
    "DRAFT", "READY_FOR_REVIEW", "PUBLISHED", "LOCKED", "ACCEPTED", "ITEMS_ISSUED", "ISSUING",
    "IN_PROGRESS", "EXECUTION_COMPLETED", "AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION", "RETURN_PENDING", "RECONCILIATION", "COMPLETED",
    "EXCEPTION", "CANCELLED",
}
VISIBLE_RUN_STATUSES = {"PUBLISHED", "LOCKED", "ACCEPTED", "ITEMS_ISSUED", "ISSUING", "IN_PROGRESS", "EXECUTION_COMPLETED", "AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION", "RETURN_PENDING", "RECONCILIATION", "COMPLETED", "EXCEPTION"}
CONFLICTING_RUN_STATUSES = VISIBLE_RUN_STATUSES | {"scheduled", "awaiting_issue", "issued", "accepted", "in_progress", "returning", "awaiting_reconciliation"}
STARTED_RUN_STATUSES = {"ITEMS_ISSUED", "ISSUING", "IN_PROGRESS", "EXECUTION_COMPLETED", "AWAITING_RETURN_RECONCILIATION", "RETURN_PENDING", "RECONCILIATION", "COMPLETED", "EXCEPTION"}
PRODUCT_LINE_STATUSES = {"READY_FOR_DELIVERY", "CLOSED_PRODUCT", "ON_HOLD", "DELIVERED", "CANCELLED", "SUBSTITUTED"}
STOP_TYPES = {"CUSTOMER_DELIVERY", "AGENT_PICKUP", "AGENT_MEETING", "SUPPLIER_PICKUP", "STOCK_TRANSFER", "OPERATIONAL_TASK", "FUEL_STOP", "RETURN_TO_BRANCH"}


def _scheduler_line(payload: dict, index: int) -> dict:
    product_name = str(payload.get("product_name") or "").strip()
    try:
        quantity = int(payload.get("quantity", payload.get("quantity_requested", 0)))
    except (TypeError, ValueError):
        quantity = 0
    delivery_type = str(payload.get("delivery_type") or "FULLY_COMPLETED_PRODUCT").strip().upper()
    if not product_name or quantity <= 0:
        raise ApiError(f"Product line {index + 1} requires a product name and positive quantity.", status_code=400)
    if delivery_type not in DELIVERY_TYPES:
        raise ApiError(f"Product line {index + 1} has an invalid delivery type.", status_code=400)
    if delivery_type == "CLOSED_CONTRIBUTION_CONVERSION" and not str(payload.get("original_product_name") or "").strip():
        raise ApiError(f"Product line {index + 1} requires the original product for conversion reference.", status_code=400)
    line_status = str(payload.get("status") or payload.get("delivery_status") or "READY_FOR_DELIVERY").strip().upper()
    if line_status not in PRODUCT_LINE_STATUSES:
        raise ApiError(f"Product line {index + 1} has an invalid status.", status_code=400)
    return {
        "line_id": str(payload.get("line_id") or uuid4()), "product_name": product_name,
        "product_code": str(payload.get("product_code") or "").strip() or None,
        "quantity": quantity, "quantity_requested": quantity, "delivery_type": delivery_type,
        "original_product_name": str(payload.get("original_product_name") or "").strip() or None,
        "original_product_value": payload.get("original_product_value"), "contributed_amount": payload.get("contributed_amount"),
        "deduction_amount": payload.get("deduction_amount"), "approved_delivery_value": payload.get("approved_delivery_value"),
        "notes": str(payload.get("notes") or "").strip() or None,
        "status": line_status, "delivery_status": line_status,
        "operational_instruction": "DO NOT LOAD OR DELIVER" if line_status == "CLOSED_PRODUCT" else None,
        "quantity_issued": 0, "quantity_delivered": 0, "quantity_returned": 0, "quantity_exception": 0,
    }


def create_certified_order(payload: dict, actor_id: str) -> dict:
    actor = current_user(actor_id)
    branch_id = assert_branch_access(actor, payload.get("branch_id"), require_active=True)
    reference = str(payload.get("reference_number") or payload.get("external_reference") or "").strip()
    if not reference:
        raise ApiError("reference_number is required.", status_code=400)
    lines = [_scheduler_line(item, index) for index, item in enumerate(payload.get("product_lines") or [])]
    if not lines:
        raise ApiError("At least one certified product line is required.", status_code=400)
    status = str(payload.get("status") or "DRAFT").strip().upper()
    if status not in {"DRAFT", "CERTIFIED", "WAITING_SCHEDULING"}:
        raise ApiError("A new delivery must be Draft, Certified, or Waiting Scheduling.", status_code=400)
    sales_agent_id = object_id(payload.get("sales_agent_id"), "sales_agent_id") if payload.get("sales_agent_id") else None
    if sales_agent_id:
        assert_user_in_branch(sales_agent_id, branch_id, AGENT_ROLE_CODES)
    required = {"customer_name": str(payload.get("customer_name") or "").strip(), "phone": str(payload.get("phone") or payload.get("customer_phone") or "").strip(), "delivery_address": str(payload.get("delivery_address") or "").strip()}
    if not all(required.values()):
        raise ApiError("Customer name, phone, and delivery address are required.", status_code=400)
    latitude = payload.get("latitude"); longitude = payload.get("longitude")
    timestamp = now_utc()
    document = {
        "reference_number": reference, "external_reference": reference, "external_source": "FleetOps Manual",
        **required, "customer_phone": required["phone"], "alternative_phone": str(payload.get("alternative_phone") or "").strip() or None,
        "branch_id": branch_id, "sales_agent_id": sales_agent_id, "assigned_field_agent_id": sales_agent_id,
        "landmark": str(payload.get("landmark") or "").strip() or None, "latitude": latitude, "longitude": longitude,
        "gps_location": {"latitude": latitude, "longitude": longitude} if latitude is not None and longitude is not None else None,
        "requested_delivery_date": str(payload.get("requested_delivery_date") or "").strip() or None,
        "notes": str(payload.get("notes") or "").strip() or None, "status": status, "certified_at": timestamp if status in {"CERTIFIED", "WAITING_SCHEDULING"} else None,
        "certified_by": object_id(actor_id) if status in {"CERTIFIED", "WAITING_SCHEDULING"} else None,
        "product_lines": lines, "created_by": object_id(actor_id), "created_at": timestamp, "updated_at": timestamp, "locked": False,
    }
    try:
        result = orders().insert_one(document)
    except DuplicateKeyError:
        raise ApiError("A delivery order already exists for this reference number.", status_code=409) from None
    document["_id"] = result.inserted_id
    _audit("certified_delivery_created", actor_id, "delivery_order", result.inserted_id, branch_id, new=document)
    _notify_branch_managers(branch_id, "New branch delivery", f"{document['customer_name']} was added to the branch delivery queue.", "certified-created", result.inserted_id)
    return serialize_delivery(document)


def certify_order(order_id: str, actor_id: str) -> dict:
    actor = current_user(actor_id); oid = object_id(order_id, "order_id")
    document = orders().find_one({"_id": oid, **branch_query(actor)})
    if not document:
        raise ApiError("Delivery order not found.", status_code=404)
    if str(document.get("status")).upper() != "DRAFT":
        raise ApiError("Only draft deliveries can be certified.", status_code=409)
    if not document.get("product_lines"):
        raise ApiError("A certified delivery requires product lines.", status_code=409)
    timestamp = now_utc(); updates = {"status": "CERTIFIED", "certified_at": timestamp, "certified_by": object_id(actor_id), "updated_at": timestamp}
    orders().update_one({"_id": oid}, {"$set": updates}); document.update(updates)
    _audit("delivery_certified", actor_id, "delivery_order", oid, document["branch_id"], new=updates)
    return serialize_delivery(document)


def list_scheduler_queue(actor_id: str, filters: dict) -> dict:
    actor = current_user(actor_id); query = {**branch_query(actor), "status": {"$in": ["CERTIFIED", "WAITING_SCHEDULING", "ready_for_planning"]}, "$or": [{"batch_id": None}, {"batch_id": {"$exists": False}}]}
    if filters.get("branch_id"): query["branch_id"] = assert_branch_access(actor, filters["branch_id"])
    if filters.get("agent_id"): query["$and"] = [{"$or": [{"sales_agent_id": object_id(filters["agent_id"])}, {"assigned_field_agent_id": object_id(filters["agent_id"])}]}]
    if filters.get("delivery_date"): query["requested_delivery_date"] = filters["delivery_date"]
    if filters.get("status"): query["status"] = filters["status"]
    if filters.get("product"): query["product_lines.product_name"] = {"$regex": str(filters["product"]), "$options": "i"}
    search = str(filters.get("search") or filters.get("customer") or "").strip()
    if search:
        search_query = {"$or": [{"customer_name": {"$regex": search, "$options": "i"}}, {"reference_number": {"$regex": search, "$options": "i"}}, {"delivery_address": {"$regex": search, "$options": "i"}}, {"landmark": {"$regex": search, "$options": "i"}}, {"product_lines.product_name": {"$regex": search, "$options": "i"}}]}
        query.setdefault("$and", []).append(search_query)
    try: page = max(int(filters.get("page") or 1), 1); size = min(max(int(filters.get("page_size") or 50), 1), 100)
    except ValueError: page, size = 1, 50
    total = orders().count_documents(query); rows = orders().find(query).sort([("requested_delivery_date", ASCENDING), ("created_at", ASCENDING)]).skip((page - 1) * size).limit(size)
    return {"orders": [serialize_delivery(row) for row in rows], "pagination": {"page": page, "page_size": size, "total": total}}


def scheduler_metadata(actor_id: str, branch_id=None) -> dict:
    actor = current_user(actor_id); branch_filter = branch_query(actor, "_id")
    if branch_id:
        selected = assert_branch_access(actor, branch_id); branch_filter = {"_id": selected}
    branch_rows = list(get_collection("branches").find({**branch_filter, "status": "active"}).sort("name", ASCENDING))
    allowed_ids = [item["_id"] for item in branch_rows]
    selected_branch = object_id(branch_id) if branch_id else None
    branch_names = {item["_id"]: item.get("name") for item in branch_rows}
    user_collection = get_collection("users"); all_users = list(user_collection.find({}).sort("full_name", ASCENDING))
    active_users = [item for item in all_users if str(item.get("status") or ("active" if item.get("active", True) else "inactive")).lower() == "active"]
    def user_branch_match(item):
        values = {value for value in [item.get("primary_branch_id"), *(item.get("allowed_branch_ids") or [])] if value}
        return not values or bool(values & set(([selected_branch] if selected_branch else allowed_ids)))
    scoped_users = [item for item in active_users if user_branch_match(item)]
    def branch_label(item):
        value = item.get("primary_branch_id") or next(iter(item.get("allowed_branch_ids") or []), None)
        return branch_names.get(value) or "Unassigned"
    all_driver_rows = [item for item in all_users if "driver" in user_role_codes(item) or bool(item.get("driver_profile"))]
    active_driver_rows = [item for item in active_users if item in all_driver_rows]
    try:
        visible_driver_ids = driver_ids_visible_to_branch_user(actor)
    except (KeyError, RuntimeError):
        # Lightweight service tests and migration utilities may not initialize
        # the application-level driver-scope database connection.
        visible_driver_ids = None
    driver_rows = [item for item in scoped_users if item in all_driver_rows]
    if visible_driver_ids is not None:
        driver_rows = [item for item in active_driver_rows if item.get("_id") in visible_driver_ids]
    all_agent_rows = [item for item in all_users if set(user_role_codes(item)) & AGENT_ROLE_CODES or any(item.get(key) for key in ("agent_profile", "sales_agent_profile", "field_agent_profile"))]
    active_agent_rows = [item for item in active_users if item in all_agent_rows]
    agent_rows = [item for item in scoped_users if item in all_agent_rows]
    def user_item(item):
        label = item.get("full_name") or item.get("username") or "Unnamed user"
        return {"id": str(item["_id"]), "label": label, "name": label, "status": "active", "branch": branch_label(item), "branch_id": str(item.get("primary_branch_id")) if item.get("primary_branch_id") else None, "primary_branch_id": str(item.get("primary_branch_id")) if item.get("primary_branch_id") else None, "disabled_reason": None}
    vehicles_all = list(get_collection("vehicles").find({}).sort("registration_number", ASCENDING))
    vehicle_active_statuses = {"available", "active", "assigned", "in_service"}
    vehicles_active = [item for item in vehicles_all if str(item.get("status") or ("active" if item.get("active", True) else "inactive")).lower() in vehicle_active_statuses]
    vehicles_scoped = [item for item in vehicles_active if not item.get("branch_id") or item.get("branch_id") in set(([selected_branch] if selected_branch else allowed_ids))]
    vehicles = []
    for item in vehicles_scoped:
        label = item.get("registration_number") or item.get("vehicle_number") or item.get("make") or "Vehicle"
        status = str(item.get("status") or "available").lower(); disabled = None
        if status not in {"available", "active", "in_service"}:
            disabled = "Assigned to another driver" if item.get("assigned_driver_id") else f"Vehicle status is {status.replace('_', ' ')}"
        vehicles.append({"id": str(item["_id"]), "label": label, "name": label, "status": status, "branch": branch_names.get(item.get("branch_id")) or "Unassigned", "branch_id": str(item.get("branch_id")) if item.get("branch_id") else None, "assigned_driver_id": str(item.get("assigned_driver_id")) if item.get("assigned_driver_id") else None, "disabled_reason": disabled})
    drivers = [user_item(item) for item in driver_rows]; agents = [user_item(item) for item in agent_rows]
    diagnostics = {
        "drivers": {"total": len(all_driver_rows), "active": len(active_driver_rows), "branch_match": len(driver_rows), "available": len(driver_rows), "returned": len(drivers)},
        "agents": {"total": len(all_agent_rows), "active": len(active_agent_rows), "branch_match": len(agent_rows), "available": len(agent_rows), "returned": len(agents)},
        "vehicles": {"total": len(vehicles_all), "active": len(vehicles_active), "branch_match": len(vehicles_scoped), "available": sum(not item.get("disabled_reason") for item in vehicles), "returned": len(vehicles)},
    }
    development_mode = current_app.config.get("ENV_NAME") == "development"
    if development_mode:
        for resource, counts in diagnostics.items(): current_app.logger.info("[Delivery Lookup] %s: total %s -> active %s -> branch %s -> available %s -> returned %s", resource.title(), counts["total"], counts["active"], counts["branch_match"], counts["available"], counts["returned"])
    branches_result = [{"id": str(item["_id"]), "code": item.get("code"), "name": item.get("name")} for item in branch_rows]
    return {"branches": branches_result, "drivers": {"items": drivers}, "agents": {"items": agents}, "vehicles": {"items": vehicles}, "diagnostics": diagnostics if development_mode else None}


def _make_stops(delivery_rows: list[dict], payload_stops=None) -> list[dict]:
    provided = {str(item.get("delivery_order_id")): item for item in (payload_stops or [])}
    stops = []
    for sequence, order in enumerate(delivery_rows, 1):
        configured = provided.get(str(order["_id"]), {})
        agent_id = configured.get("agent_id") or order.get("sales_agent_id") or order.get("assigned_field_agent_id")
        stops.append({
            "stop_id": str(configured.get("stop_id") or uuid4()), "delivery_order_id": order["_id"], "sequence_number": sequence,
            "stop_type": "CUSTOMER_DELIVERY", "customer_name": order.get("customer_name"), "agent_id": object_id(agent_id, "agent_id") if agent_id else None,
            "linked_source_type": "DELIVERY_ORDER", "linked_source_id": order["_id"],
            "customer_phone": order.get("phone") or order.get("customer_phone"), "alternative_phone": order.get("alternative_phone"),
            "address": order.get("delivery_address"), "landmark": order.get("landmark"), "latitude": order.get("latitude"), "longitude": order.get("longitude"),
            "expected_arrival_time": configured.get("expected_arrival_time"), "estimated_service_minutes": configured.get("estimated_service_minutes"),
            "priority": configured.get("priority") or "NORMAL", "notes": configured.get("notes") or order.get("notes"), "status": "PENDING",
        })
    delivery_ids = {str(item["_id"]) for item in delivery_rows}
    for configured in payload_stops or []:
        if str(configured.get("delivery_order_id") or "") in delivery_ids:
            continue
        stop_type = str(configured.get("stop_type") or "").strip().upper()
        if stop_type not in STOP_TYPES - {"CUSTOMER_DELIVERY"}:
            raise ApiError("A non-customer stop requires a supported stop type.", status_code=400)
        stops.append({
            "stop_id": str(configured.get("stop_id") or uuid4()), "delivery_order_id": None,
            "sequence_number": len(stops) + 1, "stop_type": stop_type,
            "linked_source_type": configured.get("linked_source_type"),
            "linked_source_id": object_id(configured.get("linked_source_id"), "linked_source_id") if configured.get("linked_source_id") and ObjectId.is_valid(str(configured.get("linked_source_id"))) else configured.get("linked_source_id"),
            "customer_name": str(configured.get("name") or configured.get("customer_name") or stop_type.replace("_", " ").title()).strip(),
            "agent_id": object_id(configured.get("agent_id"), "agent_id") if configured.get("agent_id") else None,
            "address": str(configured.get("address") or "").strip(), "landmark": configured.get("landmark"),
            "latitude": configured.get("latitude"), "longitude": configured.get("longitude"),
            "expected_arrival_time": configured.get("expected_arrival_time"),
            "estimated_service_minutes": configured.get("estimated_service_minutes"),
            "priority": configured.get("priority") or "NORMAL", "notes": configured.get("notes"), "status": "PENDING",
        })
    return stops


def _validate_vehicle(vehicle_id, branch_id, driver_id=None):
    vehicle = get_collection("vehicles").find_one({"_id": vehicle_id})
    if not vehicle or str(vehicle.get("status") or "").lower() not in {"available", "active", "assigned", "in_service"}:
        raise ApiError("The selected vehicle is unavailable.", status_code=409)
    if vehicle.get("branch_id") and vehicle.get("branch_id") != branch_id:
        raise ApiError("The selected vehicle does not belong to this branch.", status_code=409)
    if vehicle.get("assigned_driver_id") and driver_id and vehicle.get("assigned_driver_id") != driver_id:
        raise ApiError("The selected vehicle is allocated to another driver.", status_code=409)
    return vehicle


def _transport_method(document: dict) -> str:
    value = str(document.get("transport_method") or "VEHICLE").strip().upper()
    return value if value in TRANSPORT_METHODS else "VEHICLE"


def _manual_transport(payload: dict, actor_id=None, existing=None) -> dict | None:
    method = _transport_method(payload)
    if method == "VEHICLE":
        return None
    source = payload.get("manual_transport") or existing or {}
    name = str(source.get("provider_name") or source.get("handler_name") or "").strip()
    phone = str(source.get("phone") or source.get("handler_phone") or "").strip()
    raw_cost = source.get("agreed_cost")
    try: cost = float(raw_cost) if raw_cost not in (None, "") else None
    except (TypeError, ValueError): raise ApiError("Agreed cost must be numeric.", status_code=400) from None
    if cost is not None and cost < 0: raise ApiError("Agreed cost cannot be negative.", status_code=400)
    assigned_by = source.get("assigned_by")
    return {
        "provider_name": name or None, "handler_name": name or None,
        "phone": phone or None, "handler_phone": phone or None,
        "agreed_cost": cost,
        "assigned_by": object_id(assigned_by, "assigned_by") if assigned_by else (object_id(actor_id) if actor_id else None),
        "notes": str(source.get("notes") or "").strip() or None,
    }


def _assert_driver_for_branch(actor: dict, driver_id, branch_id):
    try:
        return assert_user_in_branch(driver_id, branch_id, {"driver"})
    except ApiError as error:
        visible = driver_ids_visible_to_branch_user(actor)
        if error.status_code == 409 and visible is not None and driver_id in visible:
            driver = users().find_one({"_id": driver_id})
            if driver and "driver" in user_role_codes(driver) and str(driver.get("status") or "").lower() == "active":
                return driver
        raise


def create_daily_run(payload: dict, actor_id: str) -> dict:
    actor = current_user(actor_id); branch_id = assert_branch_access(actor, payload.get("branch_id"), require_active=True)
    delivery_ids = list(dict.fromkeys(object_id(value, "delivery_order_id") for value in payload.get("delivery_order_ids") or []))
    if not delivery_ids:
        raise ApiError("Select at least one certified delivery.", status_code=400)
    delivery_rows = list(orders().find({"_id": {"$in": delivery_ids}, "branch_id": branch_id, "status": {"$in": ["CERTIFIED", "WAITING_SCHEDULING", "ready_for_planning"]}, "$or": [{"batch_id": None}, {"batch_id": {"$exists": False}}]}))
    if len(delivery_rows) != len(delivery_ids):
        raise ApiError("Every selected delivery must be certified, unscheduled, and in the selected branch.", status_code=409)
    order_by_id = {item["_id"]: item for item in delivery_rows}; delivery_rows = [order_by_id[item] for item in delivery_ids]
    transport_method = _transport_method(payload)
    if str(payload.get("transport_method") or "VEHICLE").strip().upper() not in TRANSPORT_METHODS:
        raise ApiError("Invalid transport_method.", status_code=400)
    driver_id = object_id(payload.get("driver_id"), "driver_id") if transport_method == "VEHICLE" and payload.get("driver_id") else None
    vehicle_id = object_id(payload.get("vehicle_id"), "vehicle_id") if transport_method == "VEHICLE" and payload.get("vehicle_id") else None
    if driver_id: _assert_driver_for_branch(actor, driver_id, branch_id)
    if vehicle_id: _validate_vehicle(vehicle_id, branch_id, driver_id)
    manual_transport = _manual_transport({**payload, "transport_method": transport_method}, actor_id)
    stops = _make_stops(delivery_rows, payload.get("stops"))
    agent_ids = list(dict.fromkeys(stop["agent_id"] for stop in stops if stop.get("agent_id")))
    for agent_id in agent_ids:
        assert_user_in_branch(
            agent_id,
            branch_id,
            AGENT_ROLE_CODES,
        )
    timestamp = now_utc(); number = f"RUN-{timestamp:%Y%m%d}-{str(uuid4())[:6].upper()}"
    document = {
        "run_number": number, "batch_number": number, "branch_id": branch_id,
        "delivery_date": str(payload.get("delivery_date") or "").strip() or None,
        "planned_departure_time": str(payload.get("planned_departure_time") or "").strip() or None,
        "transport_method": transport_method, "manual_transport": manual_transport,
        "driver_id": driver_id, "vehicle_id": vehicle_id, "assigned_agent_ids": agent_ids, "field_agent_id": agent_ids[0] if agent_ids else None,
        "delivery_order_ids": delivery_ids, "route_sequence": delivery_ids, "stops": stops,
        "notes": str(payload.get("notes") or "").strip() or None, "status": "DRAFT", "version": 1,
        "published_at": None, "locked_at": None, "created_by": object_id(actor_id), "created_at": timestamp, "updated_at": timestamp,
        "route_status": "DRAFT", "assignment_status": "PENDING", "custody_status": "NOT_ISSUED",
        "status_history": [{"from": None, "to": "DRAFT", "actor_id": object_id(actor_id), "timestamp": timestamp}],
        "route_versions": [], "change_history": [], "reconciled": False,
    }
    result = batches().insert_one(document); document["_id"] = result.inserted_id
    orders().update_many({"_id": {"$in": delivery_ids}}, {"$set": {"batch_id": result.inserted_id, "updated_at": timestamp}})
    _audit("delivery_run_created", actor_id, "delivery_run", result.inserted_id, branch_id, new=document)
    return _enrich_run(document)


def _conflicts(run: dict) -> list[dict]:
    conflicts = []
    if not run.get("delivery_date"): return conflicts
    query = {"_id": {"$ne": run.get("_id")}, "delivery_date": run["delivery_date"], "status": {"$in": list(CONFLICTING_RUN_STATUSES)}}
    if run.get("driver_id"):
        match = batches().find_one({**query, "driver_id": run["driver_id"]})
        if match: conflicts.append({"type": "driver", "run_number": match.get("run_number") or match.get("batch_number")})
    if run.get("vehicle_id"):
        match = batches().find_one({**query, "vehicle_id": run["vehicle_id"]})
        if match: conflicts.append({"type": "vehicle", "run_number": match.get("run_number") or match.get("batch_number")})
    return conflicts


def review_run(run: dict) -> dict:
    errors = []; warnings = []
    method = _transport_method(run)
    if method == "VEHICLE":
        if not run.get("driver_id"): errors.append("Assign a driver.")
        if not run.get("vehicle_id"): errors.append("Assign a vehicle.")
    else:
        manual = run.get("manual_transport") or {}
        if not manual.get("provider_name") and not manual.get("handler_name"): errors.append("Add a handler or provider name.")
        if not manual.get("phone") and not manual.get("handler_phone"): errors.append("Add a handler or provider phone.")
    if not run.get("delivery_date"): errors.append("Set a delivery date.")
    if not run.get("planned_departure_time"): errors.append("Set a departure time.")
    if not run.get("delivery_order_ids"): errors.append("Add at least one certified delivery.")
    order_rows = list(orders().find({"_id": {"$in": run.get("delivery_order_ids", [])}}))
    if len(order_rows) != len(run.get("delivery_order_ids", [])): errors.append("One or more deliveries are unavailable.")
    for order in order_rows:
        if not order.get("product_lines"): errors.append(f"{order.get('customer_name') or 'A delivery'} has no product lines.")
        for line in order.get("product_lines", []):
            if not line.get("product_name") or int(line.get("quantity", line.get("quantity_requested", 0)) or 0) <= 0: errors.append(f"{order.get('customer_name') or 'A delivery'} has an invalid product instruction.")
        if order.get("latitude") is None or order.get("longitude") is None: warnings.append(f"{order.get('customer_name') or 'A delivery'} has no GPS coordinates.")
    for stop in run.get("stops", []):
        if stop.get("stop_type") == "CUSTOMER_DELIVERY" and not stop.get("agent_id"): errors.append(f"Stop {stop.get('sequence_number')} has no responsible agent.")
        if not stop.get("expected_arrival_time"): warnings.append(f"Stop {stop.get('sequence_number')} has no expected arrival time.")
    for conflict in _conflicts(run): errors.append(f"The selected {conflict['type']} conflicts with {conflict['run_number']}.")
    errors = list(dict.fromkeys(errors)); warnings = list(dict.fromkeys(warnings))
    requirement_count = 5 if method == "VEHICLE" else 5
    readiness = "READY" if not errors else "PLANNING_REQUIRED" if len(errors) >= requirement_count else "PARTIALLY_PLANNED"
    return {"valid": not errors, "readiness": readiness, "errors": errors, "missing_requirements": errors, "warnings": warnings}


def _person(person_id):
    if not person_id: return None
    item = get_collection("users").find_one({"_id": person_id}, {"full_name": 1, "phone": 1, "email": 1})
    return {"id": str(person_id), "name": item.get("full_name"), "phone": item.get("phone"), "email": item.get("email")} if item else {"id": str(person_id), "name": "Unavailable user"}


def _enrich_run(document: dict) -> dict:
    result = dict(document)
    order_rows = list(orders().find({"_id": {"$in": document.get("delivery_order_ids", [])}})); order_map = {item["_id"]: item for item in order_rows}
    result["delivery_orders"] = [serialize_delivery(order_map[item]) for item in document.get("delivery_order_ids", []) if item in order_map]
    result["driver"] = _person(document.get("driver_id")); result["agents"] = [_person(item) for item in document.get("assigned_agent_ids", [])]
    vehicle = get_collection("vehicles").find_one({"_id": document.get("vehicle_id")}) if document.get("vehicle_id") else None
    result["vehicle"] = {"id": str(vehicle["_id"]), "name": vehicle.get("registration_number") or vehicle.get("vehicle_number") or vehicle.get("make") or "Vehicle"} if vehicle else None
    enriched_stops = []
    for stop in sorted(document.get("stops", []), key=lambda item: item.get("sequence_number", 0)):
        order = order_map.get(stop.get("delivery_order_id")); enriched_stops.append({**stop, "agent": _person(stop.get("agent_id")), "phone": order.get("phone") or order.get("customer_phone") if order else None, "products": order.get("product_lines", []) if order else []})
    result["transport_method"] = _transport_method(document)
    result["stops"] = enriched_stops; result["review"] = review_run(document); result["readiness"] = result["review"]["readiness"]
    return serialize_batch(result)


def get_daily_run(run_id: str, actor_id: str, assigned_only=False) -> dict:
    actor = current_user(actor_id); query = {"_id": object_id(run_id, "run_id"), **branch_query(actor)}
    if assigned_only: query["$or"] = [{"driver_id": object_id(actor_id)}, {"assigned_agent_ids": object_id(actor_id)}]
    run = batches().find_one(query)
    if not run: raise ApiError("Delivery run not found.", status_code=404)
    if assigned_only and set(user_role_codes(actor)) & AGENT_ROLE_CODES and run.get("driver_id") != object_id(actor_id):
        scoped_stops = [item for item in run.get("stops", []) if item.get("agent_id") == object_id(actor_id)]
        run = {**run, "stops": scoped_stops, "delivery_order_ids": [item["delivery_order_id"] for item in scoped_stops]}
    return _enrich_run(run)


def list_daily_runs(actor_id: str, filters: dict, assigned_only=False, loading_only=False) -> dict:
    actor = current_user(actor_id); query = branch_query(actor)
    if filters.get("branch_id"): query["branch_id"] = assert_branch_access(actor, filters["branch_id"])
    if filters.get("status"): query["status"] = filters["status"]
    if filters.get("date_from") or filters.get("date_to"):
        query["delivery_date"] = {}
        if filters.get("date_from"): query["delivery_date"]["$gte"] = filters["date_from"]
        if filters.get("date_to"): query["delivery_date"]["$lte"] = filters["date_to"]
    if assigned_only:
        identity = object_id(actor_id); query["status"] = {"$in": list(VISIBLE_RUN_STATUSES)}; query["$or"] = [{"driver_id": identity}, {"assigned_agent_ids": identity}]
    if loading_only: query["status"] = {"$in": list(VISIBLE_RUN_STATUSES - {"COMPLETED"})}
    try: page = max(int(filters.get("page") or 1), 1); size = min(max(int(filters.get("page_size") or 50), 1), 100)
    except (TypeError, ValueError): page, size = 1, 50
    total = batches().count_documents(query); rows = []
    cursor = batches().find(query).sort([("delivery_date", ASCENDING), ("planned_departure_time", ASCENDING)]).skip((page - 1) * size).limit(size)
    for item in cursor:
        if assigned_only and set(user_role_codes(actor)) & AGENT_ROLE_CODES and item.get("driver_id") != object_id(actor_id):
            scoped_stops = [stop for stop in item.get("stops", []) if stop.get("agent_id") == object_id(actor_id)]
            item = {**item, "stops": scoped_stops, "delivery_order_ids": [stop["delivery_order_id"] for stop in scoped_stops]}
        rows.append(_enrich_run(item))
    return {"runs": rows, "count": len(rows), "pagination": {"page": page, "page_size": size, "total": total, "total_pages": max(1, (total + size - 1) // size)}}


def _notify_run(run: dict, title: str, message: str, event: str, previous_recipients=None):
    recipients = {item for item in [run.get("driver_id"), *(run.get("assigned_agent_ids") or []), *(previous_recipients or [])] if item} | _branch_manager_ids(run["branch_id"])
    for recipient in recipients:
        create_notification(recipient, title, f"{message} Current version: v{run.get('version', 1)}.", category="operations", module="smart-living-deliveries", priority="high", reference_type="delivery_run", reference_id=run["_id"], action_url="smart-living-deliveries", action_label="View Schedule", dedupe_key=f"delivery-run:{run['_id']}:{event}:v{run.get('version', 1)}:{recipient}")


def _notify_phase5(run: dict, title: str, message: str, event: str, permission: str, *, priority="high", extra_recipients=None):
    recipients = {item for item in (extra_recipients or []) if item}
    for user in users().find({"status": "active"}):
        if not user_has_permission(user, permission):
            continue
        try:
            assert_branch_access(user, run["branch_id"])
        except ApiError:
            continue
        recipients.add(user["_id"])
    for recipient in recipients:
        create_notification(recipient, title, message, category="operations", module="smart-living-deliveries", priority=priority, reference_type="delivery_batch", reference_id=run["_id"], action_url="smart-living-deliveries", action_label="Open accountability", dedupe_key=f"delivery-phase5:{run['_id']}:{event}:{recipient}")


def update_daily_run(run_id: str, payload: dict, actor_id: str) -> dict:
    actor = current_user(actor_id); run = batches().find_one({"_id": object_id(run_id, "run_id"), **branch_query(actor)})
    if not run: raise ApiError("Delivery run not found.", status_code=404)
    if run.get("status") in {"EXECUTION_COMPLETED", "AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION", "COMPLETED", "CANCELLED"}: raise ApiError("This delivery run can no longer be edited.", status_code=409)
    allowed = {"delivery_date", "planned_departure_time", "transport_method", "manual_transport", "driver_id", "vehicle_id", "notes", "stops", "stop_order", "status"}
    material = {key for key in payload if key in allowed}
    reason = str(payload.get("reason") or "").strip()
    if run.get("status") == "LOCKED" and material and (not reason or not user_has_permission(actor, "delivery_runs.override_lock")):
        raise ApiError("Locked run changes require override permission and a reason.", status_code=403)
    if run.get("status") in {"ACCEPTED", "ITEMS_ISSUED", "IN_PROGRESS"} and material and not reason:
        raise ApiError("Changes after driver acceptance require an operational reason.", status_code=400)
    if run.get("status") == "IN_PROGRESS" and material & {"stops", "stop_order"} and not (user_has_permission(actor, "delivery_execution.override") or user_has_permission(actor, "delivery_runs.override_lock")):
        raise ApiError("Changing an active route requires delivery execution override permission.", status_code=403)
    if run.get("status") in STARTED_RUN_STATUSES and material & {"driver_id", "vehicle_id"}:
        raise ApiError("Started runs cannot change driver or vehicle.", status_code=409)
    updates = {}; old = {key: run.get(key) for key in material}; previous_recipients = [run.get("driver_id"), *(run.get("assigned_agent_ids") or [])]
    if "delivery_date" in payload: updates["delivery_date"] = str(payload.get("delivery_date") or "").strip() or None
    if "planned_departure_time" in payload: updates["planned_departure_time"] = str(payload.get("planned_departure_time") or "").strip() or None
    if "notes" in payload: updates["notes"] = str(payload.get("notes") or "").strip() or None
    method = _transport_method({"transport_method": payload.get("transport_method", run.get("transport_method"))})
    if "transport_method" in payload:
        raw_method = str(payload.get("transport_method") or "").strip().upper()
        if raw_method not in TRANSPORT_METHODS: raise ApiError("Invalid transport_method.", status_code=400)
        updates["transport_method"] = method
        if method != "VEHICLE": updates.update({"driver_id": None, "vehicle_id": None})
    if "manual_transport" in payload or "transport_method" in payload:
        updates["manual_transport"] = _manual_transport({"transport_method": method, "manual_transport": payload.get("manual_transport")}, actor_id, run.get("manual_transport"))
    driver_id = object_id(payload.get("driver_id"), "driver_id") if payload.get("driver_id") else (None if "driver_id" in payload else run.get("driver_id"))
    vehicle_id = object_id(payload.get("vehicle_id"), "vehicle_id") if payload.get("vehicle_id") else (None if "vehicle_id" in payload else run.get("vehicle_id"))
    if "driver_id" in payload:
        if method != "VEHICLE" and driver_id: raise ApiError("Manual transport does not use a company driver.", status_code=400)
        if driver_id: _assert_driver_for_branch(actor, driver_id, run["branch_id"])
        updates["driver_id"] = driver_id
    if "vehicle_id" in payload:
        if method != "VEHICLE" and vehicle_id: raise ApiError("Manual transport does not use a company vehicle.", status_code=400)
        if vehicle_id: _validate_vehicle(vehicle_id, run["branch_id"], driver_id)
        updates["vehicle_id"] = vehicle_id
    stops = [dict(item) for item in run.get("stops", [])]
    if payload.get("stops"):
        existing = {item["stop_id"]: item for item in stops}; next_stops = []
        incoming_ids = {str(item.get("stop_id")) for item in payload["stops"]}
        protected_ids = {
            str(item.get("stop_id"))
            for item in stops
            if item.get("status") in {"COMPLETED", "PARTIAL", "PARTIALLY_COMPLETED", "FAILED", "SKIPPED"}
        }
        if not protected_ids.issubset(incoming_ids):
            raise ApiError("Completed stops cannot be removed.", status_code=409)
        incoming_positions = {str(item.get("stop_id")): index + 1 for index, item in enumerate(payload["stops"])}
        if any(incoming_positions.get(str(item.get("stop_id"))) != item.get("sequence_number") for item in stops if str(item.get("stop_id")) in protected_ids):
            raise ApiError("Completed stops cannot be reordered.", status_code=409)
        for sequence, item in enumerate(payload["stops"], 1):
            current = dict(existing.get(str(item.get("stop_id"))) or item)
            if item.get("agent_id") is not None: current["agent_id"] = object_id(item["agent_id"], "agent_id") if item["agent_id"] else None
            for key in ("expected_arrival_time", "estimated_service_minutes", "priority", "notes"):
                if key in item: current[key] = item[key]
            current["sequence_number"] = sequence; next_stops.append(current)
        stops = next_stops; updates["stops"] = stops; updates["route_sequence"] = [item["delivery_order_id"] for item in stops if item.get("delivery_order_id")]
    elif payload.get("stop_order"):
        order_values = [str(item) for item in payload["stop_order"]]; by_id = {str(item["stop_id"]): item for item in stops}
        if set(order_values) != set(by_id): raise ApiError("Stop order must include every stop exactly once.", status_code=400)
        protected = {str(item["stop_id"]): item.get("sequence_number") for item in stops if item.get("status") in {"COMPLETED", "PARTIAL", "PARTIALLY_COMPLETED", "FAILED", "SKIPPED"}}
        if any(order_values.index(stop_id) + 1 != position for stop_id, position in protected.items()): raise ApiError("Completed stops cannot be reordered.", status_code=409)
        stops = [{**by_id[value], "sequence_number": index + 1} for index, value in enumerate(order_values)]; updates["stops"] = stops; updates["route_sequence"] = [item["delivery_order_id"] for item in stops if item.get("delivery_order_id")]
    if "stops" in updates:
        agent_ids = list(dict.fromkeys(item.get("agent_id") for item in stops if item.get("agent_id")))
        for agent_id in agent_ids: assert_user_in_branch(agent_id, run["branch_id"], AGENT_ROLE_CODES)
        updates["assigned_agent_ids"] = agent_ids; updates["field_agent_id"] = agent_ids[0] if agent_ids else None
    if payload.get("status") == "READY_FOR_REVIEW" and run.get("status") == "DRAFT": updates["status"] = "READY_FOR_REVIEW"
    if not updates: raise ApiError("No editable run fields were provided.", status_code=400)
    timestamp = now_utc(); published_change = run.get("status") in {"PUBLISHED", "LOCKED", "ACCEPTED", "ITEMS_ISSUED", "IN_PROGRESS"}; next_version = int(run.get("version") or 1) + (1 if published_change else 0)
    updates.update({"updated_at": timestamp, "version": next_version})
    history = {"previous_version": run.get("version", 1), "updated_version": next_version, "changed_fields": sorted(updates.keys() - {"updated_at", "version"}), "old": old, "new": {key: value for key, value in updates.items() if key not in {"updated_at"}}, "actor_id": object_id(actor_id), "reason": reason or None, "timestamp": timestamp}
    push_values = {"change_history": history}
    if published_change:
        push_values["route_versions"] = {"version": next_version, "stops": updates.get("stops", run.get("stops", [])), "driver_id": updates.get("driver_id", run.get("driver_id")), "vehicle_id": updates.get("vehicle_id", run.get("vehicle_id")), "changed_by": object_id(actor_id), "changed_at": timestamp, "change_summary": history["changed_fields"], "affected_users": list(dict.fromkeys(item for item in [updates.get("driver_id", run.get("driver_id")), *(updates.get("assigned_agent_ids", run.get("assigned_agent_ids", [])) or [])] if item))}
    batches().update_one({"_id": run["_id"]}, {"$set": updates, "$push": push_values}); run.update(updates)
    _audit("delivery_run_updated", actor_id, "delivery_run", run["_id"], run["branch_id"], old=old, new=updates, reason=reason)
    if published_change:
        run = batches().find_one({"_id": run["_id"]})
        _notify_run(run, "Delivery schedule updated", f"{run.get('run_number')} was updated.", "updated", previous_recipients)
    return _enrich_run(run)


def publish_daily_run(run_id: str, actor_id: str) -> dict:
    actor = current_user(actor_id); run = batches().find_one({"_id": object_id(run_id, "run_id"), **branch_query(actor)})
    if not run: raise ApiError("Delivery run not found.", status_code=404)
    if run.get("status") not in {"DRAFT", "READY_FOR_REVIEW"}: raise ApiError("Only a draft or reviewed run can be published.", status_code=409)
    validation = review_run(run)
    if not validation["valid"]: raise ApiError("Resolve publishing errors before publishing this run.", status_code=409, errors=validation["errors"])
    timestamp = now_utc(); updates = {"status": "PUBLISHED", "route_status": "PUBLISHED", "published_at": timestamp, "published_by": object_id(actor_id), "updated_at": timestamp}
    status_event = {"from": run.get("status"), "to": "PUBLISHED", "actor_id": object_id(actor_id), "timestamp": timestamp}
    route_version = {"version": int(run.get("version") or 1), "stops": run.get("stops", []), "driver_id": run.get("driver_id"), "vehicle_id": run.get("vehicle_id"), "published_by": object_id(actor_id), "published_at": timestamp}
    batches().update_one({"_id": run["_id"]}, {"$set": updates, "$push": {"status_history": status_event, "route_versions": route_version}}); orders().update_many({"_id": {"$in": run["delivery_order_ids"]}}, {"$set": {"status": "SCHEDULED", "updated_at": timestamp}}); run.update(updates)
    _audit("delivery_run_published", actor_id, "delivery_run", run["_id"], run["branch_id"], new=updates); _notify_run(run, "Delivery run published", f"{run['run_number']} is scheduled for {run['delivery_date']}.", "published")
    return _enrich_run(run)


def lock_daily_run(run_id: str, actor_id: str) -> dict:
    actor = current_user(actor_id); run = batches().find_one({"_id": object_id(run_id, "run_id"), **branch_query(actor)})
    if not run: raise ApiError("Delivery run not found.", status_code=404)
    if run.get("status") != "PUBLISHED": raise ApiError("Only a published run can be locked.", status_code=409)
    timestamp = now_utc(); updates = {"status": "LOCKED", "locked_at": timestamp, "locked_by": object_id(actor_id), "updated_at": timestamp}
    batches().update_one({"_id": run["_id"]}, {"$set": updates}); run.update(updates)
    _audit("delivery_run_locked", actor_id, "delivery_run", run["_id"], run["branch_id"], new=updates); _notify_run(run, "Delivery run locked", f"{run['run_number']} is now the confirmed operational plan.", "locked")
    return _enrich_run(run)


def cancel_daily_run(run_id: str, reason: str, actor_id: str) -> dict:
    actor = current_user(actor_id); run = batches().find_one({"_id": object_id(run_id, "run_id"), **branch_query(actor)})
    if not run: raise ApiError("Delivery run not found.", status_code=404)
    if run.get("status") in STARTED_RUN_STATUSES | {"COMPLETED", "CANCELLED"}: raise ApiError("This run can no longer be cancelled.", status_code=409)
    reason = str(reason or "").strip()
    if not reason: raise ApiError("A cancellation reason is required.", status_code=400)
    timestamp = now_utc(); updates = {"status": "CANCELLED", "cancelled_at": timestamp, "cancelled_by": object_id(actor_id), "cancellation_reason": reason, "updated_at": timestamp}
    batches().update_one({"_id": run["_id"]}, {"$set": updates}); orders().update_many({"_id": {"$in": run.get("delivery_order_ids", [])}}, {"$set": {"status": "WAITING_SCHEDULING", "batch_id": None, "updated_at": timestamp}}); run.update(updates)
    _audit("delivery_run_cancelled", actor_id, "delivery_run", run["_id"], run["branch_id"], new=updates, reason=reason); _notify_run(run, "Delivery run cancelled", f"{run['run_number']} was cancelled: {reason}", "cancelled")
    return _enrich_run(run)


# Phases 2-4 execution API. These operations extend scheduler runs in the
# canonical delivery_batches collection; no separate trip or custody model is
# introduced.

def _scheduler_run(run_id: str, actor_id: str, driver_only=False) -> tuple[dict, dict]:
    actor = current_user(actor_id)
    run = batches().find_one({"_id": object_id(run_id, "run_id"), **branch_query(actor)})
    if not run or not run.get("run_number"):
        raise ApiError("Delivery run not found.", status_code=404)
    if driver_only and run.get("driver_id") != object_id(actor_id):
        manual_agent = _transport_method(run) != "VEHICLE" and object_id(actor_id) in (run.get("assigned_agent_ids") or [])
        if not manual_agent:
            raise ApiError("Only the assigned driver or manual-transport Field Agent can perform this action.", status_code=403)
    return actor, run


def _run_transition(run: dict, target: str, actor_id: str, action: str, extra=None, reason=None, session=None, enrich=True) -> dict:
    timestamp = now_utc(); old_status = run.get("status")
    updates = {"status": target, "updated_at": timestamp, **(extra or {})}
    event = {"from": old_status, "to": target, "action": action, "actor_id": object_id(actor_id), "reason": reason, "timestamp": timestamp}
    batches().update_one({"_id": run["_id"]}, {"$set": updates, "$push": {"status_history": event}}, **_session(session))
    run.update(updates)
    _audit(action, actor_id, "delivery_run", run["_id"], run["branch_id"], old={"status": old_status}, new=updates, reason=reason)
    return _enrich_run(run) if enrich else run


def accept_run_assignment(run_id: str, actor_id: str) -> dict:
    _, run = _scheduler_run(run_id, actor_id, driver_only=True)
    if run.get("status") in {"ACCEPTED", "ITEMS_ISSUED", "IN_PROGRESS", "EXECUTION_COMPLETED", "AWAITING_RETURN_RECONCILIATION"}:
        return _enrich_run(run)
    if run.get("status") not in {"PUBLISHED", "LOCKED"}:
        raise ApiError("Only a published assignment can be accepted.", status_code=409)
    timestamp = now_utc()
    return _run_transition(run, "ACCEPTED", actor_id, "delivery_run_accepted", {"assignment_status": "ACCEPTED", "accepted_at": timestamp, "accepted_by": object_id(actor_id)})


def issue_scheduler_run(run_id: str, payload: dict, actor_id: str) -> dict:
    actor, run = _scheduler_run(run_id, actor_id)
    if run.get("status") != "ACCEPTED":
        if run.get("status") == "ITEMS_ISSUED":
            existing = issues().find_one({"batch_id": run["_id"]})
            return serialize_custody(existing) if existing else _enrich_run(run)
        raise ApiError("The driver must accept the published run before items are issued.", status_code=409)
    order_rows = list(orders().find({"_id": {"$in": run.get("delivery_order_ids", [])}}))
    requested = {(str(item.get("delivery_order_id")), str(item.get("line_id"))): item for item in payload.get("items") or []}
    lines = []; closed_lines = []; changed_orders = []; timestamp = now_utc()
    for order in order_rows:
        changed = False
        for line in order.get("product_lines", []):
            line_status = str(line.get("status") or line.get("delivery_status") or "READY_FOR_DELIVERY").upper()
            identity = (str(order["_id"]), str(line.get("line_id")))
            if line_status == "CLOSED_PRODUCT":
                closed_lines.append({"delivery_order_id": order["_id"], "line_id": line.get("line_id"), "product_name": line.get("product_name"), "instruction": "DO NOT LOAD OR DELIVER"})
                continue
            if line_status != "READY_FOR_DELIVERY":
                continue
            instruction = requested.get(identity, {})
            quantity = int(instruction.get("issued_quantity", line.get("quantity", line.get("quantity_requested", 0))) or 0)
            available = int(line.get("quantity", line.get("quantity_requested", 0)) or 0)
            if identity in requested and quantity <= 0:
                raise ApiError(f"Issued quantity for {line.get('product_name')} must be greater than zero.", status_code=400)
            if quantity < 0 or quantity > available:
                raise ApiError(f"Issued quantity for {line.get('product_name')} exceeds the ready quantity.", status_code=409)
            if quantity:
                line["quantity_issued"] = quantity; changed = True
                lines.append({"delivery_order_id": order["_id"], "delivery_product_line_id": line.get("line_id"), "line_id": line.get("line_id"), "product_name": line.get("product_name"), "expected_quantity": available, "issued_quantity": quantity, "serial_numbers": instruction.get("serial_numbers") or [], "condition": instruction.get("condition") or "good", "notes": instruction.get("notes")})
        if changed:
            changed_orders.append(order)
    if not lines:
        raise ApiError("No Ready for Delivery product lines are available to issue.", status_code=409)
    total_expected = sum(item["expected_quantity"] for item in lines); total_issued = sum(item["issued_quantity"] for item in lines)
    declared_total = payload.get("total_issued_quantity")
    if (declared_total is not None and int(declared_total) != total_issued) or total_issued != sum(int(item.get("issued_quantity") or 0) for item in lines):
        raise ApiError("Batch issue totals do not equal the issue-line sum.", status_code=409)
    document = {"branch_id": run["branch_id"], "batch_id": run["_id"], "driver_id": run["driver_id"], "vehicle_id": run.get("vehicle_id"), "issuing_officer_id": object_id(actor_id), "issued_by": object_id(actor_id), "issue_timestamp": timestamp, "issued_at": timestamp, "items": lines, "closed_lines": closed_lines, "total_expected_quantity": total_expected, "total_issued_quantity": total_issued, "status": "AWAITING_CUSTODY", "custody_status": "PENDING", "created_at": timestamp, "corrections": []}
    with _transaction() as session:
        try:
            result = issues().insert_one(document, **_session(session))
        except DuplicateKeyError:
            raise ApiError("This run has already been issued. Use authorized reissue for a correction.", status_code=409) from None
        for order in changed_orders:
            orders().update_one({"_id": order["_id"]}, {"$set": {"product_lines": order["product_lines"], "status": "ISSUED", "updated_at": timestamp}}, **_session(session))
        document["_id"] = result.inserted_id
        _run_transition(run, "ITEMS_ISSUED", actor_id, "delivery_items_issued", {"item_issue_id": result.inserted_id, "custody_status": "PENDING", "items_issued_at": timestamp}, session=session)
    _audit("delivery_items_issued", actor_id, "item_issue", result.inserted_id, run["branch_id"], new=document)
    return serialize_custody(document)


def reissue_scheduler_run(run_id: str, payload: dict, actor_id: str) -> dict:
    actor, run = _scheduler_run(run_id, actor_id)
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ApiError("A reissue reason is required.", status_code=400)
    if not user_has_permission(actor, "delivery_items.issue") and not user_has_permission(actor, "items.reissue") and not user_has_permission(actor, "items.correct"):
        raise ApiError("You do not have permission to reissue items.", status_code=403)
    issue = issues().find_one({"batch_id": run["_id"]})
    if not issue or run.get("status") not in {"ITEMS_ISSUED", "ACCEPTED"}:
        raise ApiError("Only an unstarted issued run can be reissued.", status_code=409)
    if issue.get("custody_status") == "ACCEPTED":
        raise ApiError("Accepted custody cannot be reissued without first recording a discrepancy.", status_code=409)
    requested = {(str(item.get("delivery_order_id")), str(item.get("line_id"))): int(item.get("issued_quantity") or 0) for item in payload.get("items") or []}
    next_items = []
    for item in issue.get("items", []):
        key = (str(item.get("delivery_order_id")), str(item.get("line_id")))
        quantity = requested.get(key, int(item.get("issued_quantity") or 0))
        order = orders().find_one({"_id": item["delivery_order_id"]})
        line = next((row for row in (order or {}).get("product_lines", []) if str(row.get("line_id")) == key[1]), None)
        maximum = int((line or {}).get("quantity", (line or {}).get("quantity_requested", 0)) or 0)
        if quantity < 0 or quantity > maximum:
            raise ApiError("Reissued quantity exceeds the ready quantity.", status_code=409)
        next_items.append({**item, "issued_quantity": quantity})
        orders().update_one({"_id": item["delivery_order_id"], "product_lines.line_id": item["line_id"]}, {"$set": {"product_lines.$.quantity_issued": quantity, "updated_at": now_utc()}})
    correction = {"reason": reason, "old_items": issue.get("items", []), "new_items": next_items, "actor_id": object_id(actor_id), "timestamp": now_utc()}
    issues().update_one({"_id": issue["_id"]}, {"$set": {"items": next_items, "custody_status": "PENDING", "status": "AWAITING_CUSTODY"}, "$push": {"corrections": correction}})
    _audit("delivery_items_reissued", actor_id, "item_issue", issue["_id"], run["branch_id"], old=issue.get("items", []), new=next_items, reason=reason)
    return serialize_custody(issues().find_one({"_id": issue["_id"]}))


def respond_to_custody(run_id: str, payload: dict, actor_id: str) -> dict:
    _, run = _scheduler_run(run_id, actor_id, driver_only=True)
    issue = issues().find_one({"batch_id": run["_id"]})
    if not issue:
        raise ApiError("No issued items are awaiting custody confirmation.", status_code=409)
    decision = str(payload.get("decision") or "ACCEPT").strip().upper()
    if decision not in {"ACCEPT", "DISPUTE"}:
        raise ApiError("Custody decision must be ACCEPT or DISPUTE.", status_code=400)
    if decision == "ACCEPT" and issue.get("custody_status") == "ACCEPTED":
        return serialize_custody(issue)
    reason = str(payload.get("reason") or "").strip()
    discrepancies = payload.get("discrepancies") or []
    if decision == "DISPUTE" and not (reason or discrepancies):
        raise ApiError("Describe the custody discrepancy.", status_code=400)
    timestamp = now_utc(); status = "ACCEPTED" if decision == "ACCEPT" else "DISPUTED"
    updates = {"custody_status": status, "acknowledgement_status": status, "status": status, "custody_responded_at": timestamp, "acknowledged_at": timestamp if status == "ACCEPTED" else None, "custody_responded_by": object_id(actor_id), "custody_holder_id": object_id(actor_id), "driver_note": str(payload.get("note") or "").strip() or None, "discrepancy_reason": reason or None, "discrepancy": discrepancies or reason or None, "discrepancies": discrepancies}
    if _transport_method(run) == "VEHICLE": updates["driver_id"] = object_id(actor_id)
    with _transaction() as session:
        issues().update_one({"_id": issue["_id"]}, {"$set": updates}, **_session(session))
        batches().update_one({"_id": run["_id"]}, {"$set": {"custody_status": status, "updated_at": timestamp}}, **_session(session))
    issue.update(updates)
    _audit(f"delivery_custody_{status.lower()}", actor_id, "item_issue", issue["_id"], run["branch_id"], new=updates, reason=reason)
    return serialize_custody(issue)


def start_scheduler_run(run_id: str, payload: dict, actor_id: str) -> dict:
    actor, run = _scheduler_run(run_id, actor_id, driver_only=True)
    if run.get("status") == "IN_PROGRESS":
        return _enrich_run(run)
    if run.get("status") != "ITEMS_ISSUED":
        raise ApiError("Only an issued run can be started.", status_code=409)
    issue = issues().find_one({"batch_id": run["_id"]})
    reason = str(payload.get("override_reason") or "").strip()
    accepted = issue and issue.get("custody_status") == "ACCEPTED"
    if not accepted and not (reason and (user_has_permission(actor, "delivery_execution.override") or user_has_permission(actor, "delivery_execution.override_custody"))):
        raise ApiError("Accept issued-item custody before starting this run.", status_code=409)
    _run_transition(run, "IN_PROGRESS", actor_id, "delivery_run_started", {"route_status": "IN_PROGRESS", "started_at": now_utc(), "custody_override_reason": reason or None}, reason=reason or None, enrich=False)
    _notify_run(run, "Delivery route started", f"{run.get('run_number')} has started its route.", "started")
    return _enrich_run(run)


def update_scheduler_stop(run_id: str, stop_id: str, payload: dict, actor_id: str) -> dict:
    _, run = _scheduler_run(run_id, actor_id, driver_only=True)
    if run.get("status") != "IN_PROGRESS":
        raise ApiError("Stops can only be updated while the run is in progress.", status_code=409)
    stops = sorted([dict(item) for item in run.get("stops", [])], key=lambda item: item.get("sequence_number", 0))
    index = next((i for i, item in enumerate(stops) if str(item.get("stop_id")) == str(stop_id)), -1)
    if index < 0:
        raise ApiError("Route stop not found.", status_code=404)
    action = str(payload.get("action") or "").strip().upper(); stop = stops[index]
    terminal = {"COMPLETED", "PARTIAL", "PARTIALLY_COMPLETED", "FAILED", "SKIPPED"}
    if stop.get("status") in terminal:
        return _enrich_run(run)
    if action == "ARRIVE":
        if any(item.get("status") not in terminal for item in stops[:index]):
            raise ApiError("Complete the previous stop before arriving here.", status_code=409)
        stop.update({"status": "ARRIVED", "arrived_at": now_utc()})
    elif action == "START_SERVICE":
        if stop.get("status") != "ARRIVED":
            raise ApiError("Mark the stop arrived before starting service.", status_code=409)
        stop.update({"status": "IN_SERVICE", "service_started_at": now_utc()})
    elif action == "OUTCOME":
        if stop.get("status") not in {"ARRIVED", "IN_SERVICE"}:
            raise ApiError("Arrive at the stop before recording its outcome.", status_code=409)
        outcome = str(payload.get("outcome") or "COMPLETED").strip().upper()
        if outcome == "PARTIALLY_COMPLETED": outcome = "PARTIAL"
        if outcome not in terminal:
            raise ApiError("Invalid stop outcome.", status_code=400)
        line_reason = next((str(item.get("reason") or "").strip() for item in payload.get("items") or [] if str(item.get("reason") or "").strip()), "")
        reason = str(payload.get("reason") or payload.get("exception") or payload.get("notes") or line_reason or "").strip()
        if outcome in {"PARTIAL", "FAILED", "SKIPPED"} and not reason:
            raise ApiError("Partial, failed, and skipped stops require a reason.", status_code=400)
        order = orders().find_one({"_id": stop.get("delivery_order_id")}) if stop.get("delivery_order_id") else None
        submitted = {str(item.get("line_id")): item for item in payload.get("items") or []}
        if order:
            for line in order.get("product_lines", []):
                line_status = str(line.get("status") or line.get("delivery_status") or "READY_FOR_DELIVERY").upper()
                if line_status == "CLOSED_PRODUCT":
                    continue
                issued = int(line.get("quantity_issued") or 0); values = submitted.get(str(line.get("line_id")), {})
                delivered = int(values.get("quantity_delivered") or 0); undelivered = int(values.get("quantity_undelivered") or 0)
                if delivered < 0 or undelivered < 0 or delivered + undelivered != issued:
                    raise ApiError(f"Delivered and undelivered quantities for {line.get('product_name')} must equal the issued quantity.", status_code=409)
                line_outcome = "FULLY_DELIVERED" if delivered == issued else "NOT_DELIVERED" if delivered == 0 else "PARTIALLY_DELIVERED"
                line.update({"quantity_delivered": delivered, "delivered_quantity": delivered, "quantity_exception": undelivered, "undelivered_quantity": undelivered, "delivery_outcome": line_outcome, "outcome_reason": values.get("reason") or reason or None, "exception_reason": values.get("reason") or reason or None, "delivered_at": now_utc(), "recipient_name": payload.get("recipient_name"), "status": "DELIVERED" if delivered == issued else line_status, "delivery_status": "DELIVERED" if delivered == issued else line_status})
            order_status = "DELIVERED" if all(str(item.get("status") or "").upper() in {"DELIVERED", "CLOSED_PRODUCT"} for item in order.get("product_lines", [])) else "PARTIALLY_DELIVERED"
        stop.update({"status": outcome, "outcome": outcome, "outcome_reason": reason or None, "outcome_notes": payload.get("notes"), "exception": payload.get("exception"), "recipient_name": payload.get("recipient_name"), "proof": payload.get("proof"), "completed_at": now_utc()})
    else:
        raise ApiError("Stop action must be ARRIVE, START_SERVICE, or OUTCOME.", status_code=400)
    timestamp = now_utc()
    became_awaiting = False
    with _transaction() as session:
        if action == "OUTCOME" and order:
            orders().update_one({"_id": order["_id"]}, {"$set": {"product_lines": order["product_lines"], "status": order_status, "delivery_exception": payload.get("exception"), "updated_at": timestamp}}, **_session(session))
        batches().update_one({"_id": run["_id"]}, {"$set": {"stops": stops, "updated_at": timestamp}}, **_session(session)); run["stops"] = stops
        if all(item.get("status") in terminal for item in stops):
            _run_transition(run, "EXECUTION_COMPLETED", actor_id, "delivery_execution_completed", {"route_status": "COMPLETED", "execution_completed_at": timestamp}, session=session, enrich=False)
            _run_transition(run, "AWAITING_RECONCILIATION", actor_id, "delivery_awaiting_reconciliation", {"awaiting_reconciliation_at": timestamp}, session=session, enrich=False)
            became_awaiting = True
    _audit("delivery_stop_updated", actor_id, "delivery_run", run["_id"], run["branch_id"], new={"stop_id": stop_id, "action": action, "status": stop.get("status")})
    if action == "OUTCOME":
        _notify_run(run, "Delivery stop updated", f"Stop {stop.get('sequence_number')} is {stop.get('status')}.", f"stop-{stop_id}-{stop.get('status')}")
    if became_awaiting and sum(item["expected_return_quantity"] for item in _phase5_lines(run)) > 0:
        _notify_phase5(run, "Outstanding delivery returns", f"{run.get('run_number') or run.get('batch_number')} has items awaiting return receiving.", "outstanding-returns", "returns.receive")
    return _enrich_run(run)


def complete_scheduler_run(run_id: str, actor_id: str) -> dict:
    _, run = _scheduler_run(run_id, actor_id, driver_only=True)
    if run.get("status") in {"EXECUTION_COMPLETED", "AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION"}:
        return _enrich_run(run)
    if run.get("status") != "IN_PROGRESS":
        raise ApiError("Only an in-progress run can be completed.", status_code=409)
    terminal = {"COMPLETED", "PARTIAL", "PARTIALLY_COMPLETED", "FAILED", "SKIPPED"}
    if any(item.get("status") not in terminal for item in run.get("stops", [])):
        raise ApiError("Record an outcome for every route stop before completing the run.", status_code=409)
    _run_transition(run, "EXECUTION_COMPLETED", actor_id, "delivery_execution_completed", {"route_status": "COMPLETED", "execution_completed_at": now_utc()}, enrich=False)
    result = _run_transition(run, "AWAITING_RECONCILIATION", actor_id, "delivery_awaiting_reconciliation", {"awaiting_reconciliation_at": now_utc()})
    if sum(item["expected_return_quantity"] for item in _phase5_lines(run)) > 0:
        _notify_phase5(run, "Outstanding delivery returns", f"{run.get('run_number') or run.get('batch_number')} has items awaiting return receiving.", "outstanding-returns", "returns.receive")
    return result


def handoff_scheduler_returns(run_id: str, actor_id: str) -> dict:
    _, run = _scheduler_run(run_id, actor_id)
    if run.get("status") in {"AWAITING_RECONCILIATION", "AWAITING_RETURN_RECONCILIATION"}:
        return _enrich_run(run)
    if run.get("status") != "EXECUTION_COMPLETED":
        raise ApiError("Execution must be completed before return reconciliation handoff.", status_code=409)
    result = _run_transition(run, "AWAITING_RECONCILIATION", actor_id, "delivery_return_handoff", {"return_handoff_at": now_utc()})
    if sum(item["expected_return_quantity"] for item in _phase5_lines(run)) > 0:
        _notify_phase5(run, "Outstanding delivery returns", f"{run.get('run_number') or run.get('batch_number')} has items awaiting return receiving.", "outstanding-returns", "returns.receive")
    return result


# Phase 5: Returns, Exceptions and Reconciliation ---------------------------

RETURN_CONDITIONS = {"GOOD", "DAMAGED", "PACKAGING_DAMAGED", "WRONG_ITEM", "MISSING_PARTS", "DESTROYED"}
EXCEPTION_CATEGORIES = {"CUSTOMER_UNAVAILABLE", "CUSTOMER_REFUSED", "WRONG_ADDRESS", "WRONG_PHONE", "PRODUCT_DAMAGED", "VEHICLE_BREAKDOWN", "SAFETY", "THEFT", "MISSING_ITEM", "OTHER"}
EXCEPTION_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
EXCEPTION_STATUSES = {"OPEN", "UNDER_REVIEW", "RESOLVED", "CLOSED"}
TERMINAL_STOP_STATUSES = {"COMPLETED", "PARTIAL", "PARTIALLY_COMPLETED", "FAILED", "SKIPPED"}
PHASE5_BATCH_STATUSES = {"AWAITING_RECONCILIATION", "RECONCILED", "CLOSED", "REOPENED", "awaiting_reconciliation", "reconciled"}


def _phase5_run(run_id: str, actor_id: str) -> tuple[dict, dict]:
    actor = current_user(actor_id)
    run = batches().find_one({"_id": object_id(run_id, "run_id"), **branch_query(actor)})
    if not run:
        raise ApiError("Delivery batch not found.", status_code=404)
    if run.get("status") not in PHASE5_BATCH_STATUSES:
        raise ApiError("This batch has not completed delivery execution.", status_code=409)
    return actor, run


def _phase5_lines(run: dict) -> list[dict]:
    order_map = {item["_id"]: item for item in orders().find({"_id": {"$in": run.get("delivery_order_ids", [])}})}
    issue = issues().find_one({"batch_id": run["_id"]}) or {}
    rows = []
    for issued in issue.get("items", []):
        order = order_map.get(issued.get("delivery_order_id")); line = next((item for item in (order or {}).get("product_lines", []) if str(item.get("line_id")) == str(issued.get("line_id"))), {})
        issued_quantity = int(issued.get("issued_quantity") or line.get("quantity_issued") or 0)
        delivered = int(line.get("delivered_quantity", line.get("quantity_delivered", 0)) or 0)
        rows.append({"delivery_order_id": issued.get("delivery_order_id"), "line_id": issued.get("line_id"), "customer_name": (order or {}).get("customer_name"), "product_name": issued.get("product_name") or line.get("product_name"), "issued_quantity": issued_quantity, "delivered_quantity": delivered, "expected_return_quantity": max(issued_quantity - delivered, 0), "line": line})
    return rows


def list_accountability_batches(actor_id: str, filters: dict) -> dict:
    actor = current_user(actor_id); query = {**branch_query(actor), "status": {"$in": list(PHASE5_BATCH_STATUSES)}}
    if filters.get("branch_id"): query["branch_id"] = assert_branch_access(actor, filters["branch_id"])
    if filters.get("status"): query["status"] = filters["status"]
    if filters.get("driver_id"): query["driver_id"] = object_id(filters["driver_id"], "driver_id")
    if filters.get("vehicle_id"): query["vehicle_id"] = object_id(filters["vehicle_id"], "vehicle_id")
    try: page = max(int(filters.get("page") or 1), 1); size = min(max(int(filters.get("page_size") or 25), 1), 100)
    except (TypeError, ValueError): page, size = 1, 25
    total = batches().count_documents(query); cursor = batches().find(query).sort("updated_at", DESCENDING).skip((page - 1) * size).limit(size)
    rows = []
    for run in cursor:
        payload = _enrich_run(run); payload["return"] = serialize_custody(returns().find_one({"batch_id": run["_id"]})) if returns().find_one({"batch_id": run["_id"]}) else None
        payload["exception_summary"] = {status: exceptions().count_documents({"delivery_batch_id": run["_id"], "status": status}) for status in EXCEPTION_STATUSES}
        payload["reconciliation"] = reconciliation_summary(run)
        rows.append(payload)
    return {"batches": rows, "pagination": {"page": page, "page_size": size, "total": total, "total_pages": max(1, (total + size - 1) // size)}}


def receive_scheduler_returns(run_id: str, payload: dict, actor_id: str) -> dict:
    _, run = _phase5_run(run_id, actor_id)
    if run.get("locked") or run.get("status") == "CLOSED": raise ApiError("Closed batches cannot receive returns.", status_code=409)
    existing = returns().find_one({"batch_id": run["_id"]})
    idempotency_key = str(payload.get("_idempotency_key") or payload.get("idempotency_key") or "").strip() or None
    if existing and (not payload.get("items") or (idempotency_key and any(event.get("idempotency_key") == idempotency_key for event in existing.get("receiving_events", [])))):
        return serialize_custody(existing)
    supplied = {(str(item.get("delivery_order_id")), str(item.get("line_id"))): item for item in payload.get("items") or []}
    phase_lines = _phase5_lines(run)
    if not phase_lines: raise ApiError("No issued product lines exist for this batch.", status_code=409)
    previous_items = {(str(item.get("delivery_order_id")), str(item.get("line_id"))): item for item in (existing or {}).get("items", [])}
    records = []; receipt_items = []; changed_orders = {}; timestamp = now_utc()
    for row in phase_lines:
        key = (str(row["delivery_order_id"]), str(row["line_id"])); item = supplied.get(key, {})
        previous = previous_items.get(key, {}); previously_received = int(previous.get("returned_quantity") or 0)
        quantity = int(item.get("returned_quantity") or 0); expected = row["expected_return_quantity"]; outstanding = max(expected - previously_received, 0)
        condition = str(item.get("condition") or "GOOD").strip().upper()
        if quantity < 0 or quantity > outstanding: raise ApiError(f"Returned quantity for {row['product_name']} must be between 0 and {outstanding}.", status_code=409)
        if condition not in RETURN_CONDITIONS: raise ApiError("Invalid return condition.", status_code=400)
        reason = str(item.get("return_reason") or "").strip()
        if key in supplied and outstanding > 0 and quantity < outstanding and not reason: raise ApiError("A return reason is required for a partial return receipt.", status_code=400)
        cumulative = previously_received + quantity
        prior_conditions = list(previous.get("conditions") or ([previous.get("condition")] if previous.get("condition") else []))
        if quantity: prior_conditions.append(condition)
        record = {"delivery_order_id": row["delivery_order_id"], "delivery_product_line_id": row["line_id"], "line_id": row["line_id"], "customer_name": row["customer_name"], "product_name": row["product_name"], "issued_quantity": row["issued_quantity"], "delivered_quantity": row["delivered_quantity"], "expected_return_quantity": expected, "previously_received_quantity": previously_received, "returned_quantity": cumulative, "outstanding_quantity": max(expected - cumulative, 0), "condition": condition if quantity else previous.get("condition", condition), "conditions": list(dict.fromkeys(filter(None, prior_conditions))), "return_reason": reason or previous.get("return_reason"), "notes": item.get("notes") or previous.get("notes")}
        records.append(record)
        if quantity:
            receipt_items.append({"delivery_order_id": row["delivery_order_id"], "line_id": row["line_id"], "product_name": row["product_name"], "received_quantity": quantity, "condition": condition, "return_reason": reason or None, "notes": item.get("notes")})
        order = changed_orders.get(row["delivery_order_id"]) or orders().find_one({"_id": row["delivery_order_id"]})
        line = next(entry for entry in order.get("product_lines", []) if str(entry.get("line_id")) == str(row["line_id"])); line["quantity_returned"] = cumulative; line["return_condition"] = record["condition"]; changed_orders[row["delivery_order_id"]] = order
    if not receipt_items: raise ApiError("Enter at least one returned quantity that is still outstanding.", status_code=400)
    total_expected = sum(item["expected_return_quantity"] for item in records); total_returned = sum(item["returned_quantity"] for item in records)
    event = {"receipt_id": str(uuid4()), "idempotency_key": idempotency_key, "items": receipt_items, "received_by": object_id(actor_id), "received_at": timestamp}
    source_key = f"delivery_batch:{run['_id']}"; document = {"source_key": source_key, "branch_id": run["branch_id"], "batch_id": run["_id"], "driver_id": run.get("driver_id"), "vehicle_id": run.get("vehicle_id"), "receiving_officer_id": object_id(actor_id), "received_by": object_id(actor_id), "return_timestamp": timestamp, "received_at": timestamp, "items": records, "receiving_events": [event], "total_expected_return_quantity": total_expected, "total_returned_quantity": total_returned, "total_outstanding_quantity": max(total_expected - total_returned, 0), "status": "RECEIVED" if total_returned == total_expected else "PARTIALLY_RECEIVED", "locked": False, "created_at": timestamp, "updated_at": timestamp}
    with _transaction() as session:
        if existing:
            returns().update_one({"_id": existing["_id"], "locked": {"$ne": True}}, {"$set": {key: document[key] for key in ("items", "total_expected_return_quantity", "total_returned_quantity", "total_outstanding_quantity", "status", "received_by", "received_at", "updated_at")}, "$push": {"receiving_events": event}}, **_session(session)); document = returns().find_one({"_id": existing["_id"]})
        else:
            try: document["_id"] = returns().insert_one(document, **_session(session)).inserted_id
            except DuplicateKeyError:
                winner = returns().find_one({"source_key": source_key}); return serialize_custody(winner)
        for order in changed_orders.values(): orders().update_one({"_id": order["_id"]}, {"$set": {"product_lines": order["product_lines"], "updated_at": timestamp}}, **_session(session))
        batches().update_one({"_id": run["_id"]}, {"$set": {"returns_received_at": timestamp, "returns_received_by": object_id(actor_id), "updated_at": timestamp}}, **_session(session))
    _audit("delivery_returns_received", actor_id, "item_return", document["_id"], run["branch_id"], new=event)
    damaged = sum(item["received_quantity"] for item in receipt_items if item["condition"] != "GOOD")
    if damaged:
        _notify_phase5(run, "Damaged or incomplete return received", f"{damaged} returned item(s) require exception review.", f"damaged-return:{event['receipt_id']}", "exceptions.manage", priority="critical" if any(item["condition"] == "DESTROYED" for item in receipt_items) else "high")
    if document.get("total_outstanding_quantity", 0) > 0:
        _notify_phase5(run, "Returns still outstanding", f"{document['total_outstanding_quantity']} item(s) remain outstanding after a partial receipt.", f"partial-return:{event['receipt_id']}", "returns.manage")
    return serialize_custody(document)


def create_delivery_exception(run_id: str, payload: dict, actor_id: str) -> dict:
    _, run = _phase5_run(run_id, actor_id)
    if run.get("locked"): raise ApiError("Closed batches cannot be changed.", status_code=409)
    category = str(payload.get("category") or "").strip().upper(); severity = str(payload.get("severity") or "MEDIUM").strip().upper(); description = str(payload.get("description") or "").strip()
    if category not in EXCEPTION_CATEGORIES: raise ApiError("Invalid exception category.", status_code=400)
    if severity not in EXCEPTION_SEVERITIES: raise ApiError("Invalid exception severity.", status_code=400)
    if not description: raise ApiError("Exception description is required.", status_code=400)
    stop_id = str(payload.get("stop_id") or "").strip() or None
    if stop_id and not any(str(item.get("stop_id")) == stop_id for item in run.get("stops", [])): raise ApiError("The selected stop does not belong to this batch.", status_code=409)
    delivery_order_id = object_id(payload.get("delivery_order_id"), "delivery_order_id") if payload.get("delivery_order_id") else None
    line_id = str(payload.get("line_id") or "").strip() or None
    phase_line = next((item for item in _phase5_lines(run) if item["delivery_order_id"] == delivery_order_id and str(item["line_id"]) == str(line_id)), None) if delivery_order_id and line_id else None
    if (delivery_order_id or line_id) and not phase_line: raise ApiError("The selected product line does not belong to this batch.", status_code=409)
    exception_quantity = int(payload.get("quantity") or 0)
    if exception_quantity < 0 or (phase_line and exception_quantity > phase_line["issued_quantity"]): raise ApiError("Exception quantity is outside the issued product quantity.", status_code=400)
    responsible_person_id = object_id(payload.get("responsible_person_id"), "responsible_person_id") if payload.get("responsible_person_id") else None
    if responsible_person_id: assert_user_in_branch(responsible_person_id, run["branch_id"])
    evidence = validate_attachment_list(payload.get("evidence") or [], field_name="evidence", max_files=10)
    idempotency_key = str(payload.get("_idempotency_key") or payload.get("idempotency_key") or "").strip() or None
    source_key = f"delivery_exception:{run['_id']}:{idempotency_key}" if idempotency_key else None
    if source_key:
        existing = exceptions().find_one({"source_key": source_key})
        if existing: return serialize_custody(existing)
    requires_investigation = bool(payload.get("requires_investigation")) or severity == "CRITICAL" or category in {"THEFT", "SAFETY"}
    initial_note = str(payload.get("notes") or "").strip()
    timestamp = now_utc(); document = {"exception_number": f"DEX-{timestamp:%Y%m%d}-{str(uuid4())[:6].upper()}", "source_key": source_key, "delivery_batch_id": run["_id"], "batch_id": run["_id"], "stop_id": stop_id, "delivery_order_id": delivery_order_id, "delivery_product_line_id": line_id, "customer_name": phase_line.get("customer_name") if phase_line else None, "product_name": phase_line.get("product_name") if phase_line else None, "category": category, "quantity": exception_quantity, "severity": severity, "description": description, "responsible_department": str(payload.get("responsible_department") or "OPERATIONS").strip().upper(), "responsible_person_id": responsible_person_id, "status": "OPEN", "requires_investigation": requires_investigation, "approved_exception_quantity": 0, "evidence": evidence, "notes": ([{"note_id": str(uuid4()), "text": initial_note, "created_by": object_id(actor_id), "created_at": timestamp}] if initial_note else []), "branch_id": run["branch_id"], "driver_id": run.get("driver_id"), "created_by": object_id(actor_id), "created_at": timestamp, "reported_by": object_id(actor_id), "reported_at": timestamp, "updated_at": timestamp}
    try: document["_id"] = exceptions().insert_one(document).inserted_id
    except DuplicateKeyError:
        winner = exceptions().find_one({"source_key": source_key})
        if winner: return serialize_custody(winner)
        raise
    _audit("delivery_exception_created", actor_id, "delivery_exception", document["_id"], run["branch_id"], new=document)
    _notify_phase5(run, "Delivery exception opened", f"{document['exception_number']}: {category.replace('_', ' ').title()} requires review.", f"exception-opened:{document['_id']}", "exceptions.manage", priority="critical" if severity == "CRITICAL" else "high")
    return serialize_custody(document)


def list_delivery_exceptions(actor_id: str, filters: dict) -> dict:
    actor = current_user(actor_id); query = branch_query(actor)
    if filters.get("batch_id"): query["delivery_batch_id"] = object_id(filters["batch_id"], "batch_id")
    if filters.get("status"): query["status"] = str(filters["status"]).upper()
    if filters.get("severity"): query["severity"] = str(filters["severity"]).upper()
    if filters.get("category"): query["category"] = str(filters["category"]).upper()
    try: page = max(int(filters.get("page") or 1), 1); size = min(max(int(filters.get("page_size") or 25), 1), 100)
    except (TypeError, ValueError): page, size = 1, 25
    total = exceptions().count_documents(query); rows = exceptions().find(query).sort("created_at", DESCENDING).skip((page - 1) * size).limit(size)
    return {"exceptions": [serialize_custody(item) for item in rows], "pagination": {"page": page, "page_size": size, "total": total, "total_pages": max(1, (total + size - 1) // size)}}


def update_delivery_exception(exception_id: str, payload: dict, actor_id: str) -> dict:
    actor = current_user(actor_id); document = exceptions().find_one({"_id": object_id(exception_id, "exception_id"), **branch_query(actor)})
    if not document: raise ApiError("Delivery exception not found.", status_code=404)
    if document.get("locked"): raise ApiError("Closed exception records cannot be changed without reopening the batch.", status_code=409)
    target = str(payload.get("status") or document.get("status") or "OPEN").upper()
    transitions = {"OPEN": {"OPEN", "UNDER_REVIEW"}, "UNDER_REVIEW": {"UNDER_REVIEW", "RESOLVED"}, "RESOLVED": {"RESOLVED", "CLOSED"}, "CLOSED": {"CLOSED"}}
    if target not in transitions.get(document.get("status"), set()): raise ApiError("Invalid exception status transition.", status_code=409)
    note = str(payload.get("note") or "").strip(); timestamp = now_utc(); updates = {"status": target, "updated_at": timestamp}
    if "approved_exception_quantity" in payload:
        quantity = int(payload.get("approved_exception_quantity") or 0)
        if target not in {"RESOLVED", "CLOSED"} or quantity < 0: raise ApiError("Approved exception quantity requires a resolved exception.", status_code=400)
        phase_line = next((item for item in _phase5_lines(batches().find_one({"_id": document["delivery_batch_id"]})) if item["delivery_order_id"] == document.get("delivery_order_id") and str(item["line_id"]) == str(document.get("delivery_product_line_id"))), None)
        if quantity and not phase_line: raise ApiError("Approved exception quantity requires a product-line exception.", status_code=400)
        if phase_line and quantity > phase_line["issued_quantity"]: raise ApiError("Approved exception quantity cannot exceed the issued quantity.", status_code=400)
        updates["approved_exception_quantity"] = quantity
    if payload.get("resolution") is not None: updates["resolution"] = str(payload.get("resolution") or "").strip() or None
    if target in {"RESOLVED", "CLOSED"}:
        if document.get("requires_investigation") and document.get("investigation_status") != "CLOSED": raise ApiError("Complete the required investigation before resolving this exception.", status_code=409)
        updates["resolved_by"] = object_id(actor_id); updates["resolved_at"] = timestamp
    operation = {"$set": updates}
    if note: operation["$push"] = {"notes": {"note_id": str(uuid4()), "text": note, "created_by": object_id(actor_id), "created_at": timestamp}}
    exceptions().update_one({"_id": document["_id"]}, operation); document = exceptions().find_one({"_id": document["_id"]})
    _audit("delivery_exception_updated", actor_id, "delivery_exception", document["_id"], document["branch_id"], new=updates, reason=note or None)
    if target in {"RESOLVED", "CLOSED"}:
        run = batches().find_one({"_id": document["delivery_batch_id"]})
        _notify_phase5(run, "Delivery exception resolved", f"{document.get('exception_number')} was {target.lower()}.", f"exception-{target.lower()}:{document['_id']}", "reconciliation.manage", extra_recipients=[document.get("created_by")])
    return serialize_custody(document)


def investigate_delivery_exception(exception_id: str, payload: dict, actor_id: str) -> dict:
    actor = current_user(actor_id); exception = exceptions().find_one({"_id": object_id(exception_id, "exception_id"), **branch_query(actor)})
    if not exception: raise ApiError("Delivery exception not found.", status_code=404)
    if exception.get("locked"): raise ApiError("Closed exception records cannot be investigated without reopening the batch.", status_code=409)
    if not exception.get("requires_investigation"): raise ApiError("This exception does not require an investigation.", status_code=409)
    existing = investigations().find_one({"delivery_exception_id": exception["_id"]}); timestamp = now_utc()
    investigator_id = object_id(payload.get("assigned_investigator_id"), "assigned_investigator_id") if payload.get("assigned_investigator_id") else (existing or {}).get("assigned_investigator_id")
    if not investigator_id: raise ApiError("Assign an investigator.", status_code=400)
    assert_user_in_branch(investigator_id, exception["branch_id"])
    evidence = validate_attachment_list(payload.get("evidence") or [], field_name="evidence", max_files=10)
    status = str(payload.get("status") or (existing or {}).get("status") or "UNDER_REVIEW").upper()
    if status not in {"UNDER_REVIEW", "RESOLVED", "CLOSED"}: raise ApiError("Invalid investigation status.", status_code=400)
    responsible_party_id = object_id(payload.get("responsible_party_id"), "responsible_party_id") if payload.get("responsible_party_id") else (existing or {}).get("responsible_party_id")
    if responsible_party_id: assert_user_in_branch(responsible_party_id, exception["branch_id"])
    approved_quantity = int(payload.get("approved_exception_quantity") if payload.get("approved_exception_quantity") is not None else (existing or {}).get("approved_exception_quantity") or 0)
    if approved_quantity < 0: raise ApiError("Approved exception quantity cannot be negative.", status_code=400)
    phase_line = next((item for item in _phase5_lines(batches().find_one({"_id": exception["delivery_batch_id"]})) if item["delivery_order_id"] == exception.get("delivery_order_id") and str(item["line_id"]) == str(exception.get("delivery_product_line_id"))), None)
    if approved_quantity and (not phase_line or approved_quantity > phase_line["issued_quantity"]): raise ApiError("Approved exception quantity is outside the issued product quantity.", status_code=400)
    updates = {"delivery_exception_id": exception["_id"], "delivery_batch_id": exception["delivery_batch_id"], "branch_id": exception["branch_id"], "assigned_investigator_id": investigator_id, "findings": str(payload.get("findings") or (existing or {}).get("findings") or "").strip() or None, "responsible_party_id": responsible_party_id, "approved_exception_quantity": approved_quantity, "resolution": str(payload.get("resolution") or (existing or {}).get("resolution") or "").strip() or None, "corrective_action": str(payload.get("corrective_action") or (existing or {}).get("corrective_action") or "").strip() or None, "status": status, "updated_at": timestamp}
    if status in {"RESOLVED", "CLOSED"} and not updates["findings"]: raise ApiError("Findings are required to resolve an investigation.", status_code=400)
    if status == "CLOSED" and (not updates["resolution"] or not updates["corrective_action"]): raise ApiError("Resolution and corrective action are required to close an investigation.", status_code=400)
    if existing:
        operation = {"$set": updates}
        if evidence: operation["$push"] = {"evidence": {"$each": [{**item, "evidence_id": item.get("id") or str(uuid4()), "uploaded_by": object_id(actor_id), "uploaded_at": timestamp} for item in evidence]}}
        investigations().update_one({"_id": existing["_id"]}, operation); investigation_id = existing["_id"]
    else:
        updates.update({"evidence": [{**item, "evidence_id": item.get("id") or str(uuid4()), "uploaded_by": object_id(actor_id), "uploaded_at": timestamp} for item in evidence], "notes": [], "created_by": object_id(actor_id), "created_at": timestamp}); investigation_id = investigations().insert_one(updates).inserted_id
    note = str(payload.get("notes") or "").strip()
    if note: investigations().update_one({"_id": investigation_id}, {"$push": {"notes": {"note_id": str(uuid4()), "text": note, "created_by": object_id(actor_id), "created_at": timestamp}}})
    if status == "CLOSED": updates["closed_at"] = timestamp; updates["closed_by"] = object_id(actor_id); updates["resolved_at"] = timestamp; updates["resolved_by"] = object_id(actor_id); investigations().update_one({"_id": investigation_id}, {"$set": {"closed_at": timestamp, "closed_by": object_id(actor_id), "resolved_at": timestamp, "resolved_by": object_id(actor_id)}})
    exception_updates = {"investigation_id": investigation_id, "investigation_status": status, "status": "UNDER_REVIEW" if status == "UNDER_REVIEW" else exception.get("status"), "updated_at": timestamp}
    if status == "CLOSED": exception_updates["approved_exception_quantity"] = approved_quantity
    exceptions().update_one({"_id": exception["_id"]}, {"$set": exception_updates})
    _audit("delivery_exception_investigated", actor_id, "delivery_exception_investigation", investigation_id, exception["branch_id"], new=updates)
    run = batches().find_one({"_id": exception["delivery_batch_id"]})
    if not existing:
        create_notification(investigator_id, "Investigation assigned", f"Investigation for {exception.get('exception_number')} was assigned to you.", category="operations", module="smart-living-deliveries", priority="critical" if exception.get("severity") == "CRITICAL" else "high", reference_type="delivery_exception", reference_id=exception["_id"], action_url="smart-living-deliveries", action_label="Open investigation", dedupe_key=f"delivery-phase5:{run['_id']}:investigation-assigned:{investigation_id}:{investigator_id}")
    return serialize_custody(investigations().find_one({"_id": investigation_id}))


def reconciliation_summary(run: dict) -> dict:
    return_doc = returns().find_one({"batch_id": run["_id"]}) or {}; returned = {(str(item.get("delivery_order_id")), str(item.get("line_id"))): int(item.get("returned_quantity") or 0) for item in return_doc.get("items", [])}
    approved = {}
    for item in exceptions().find({"delivery_batch_id": run["_id"], "status": {"$in": ["RESOLVED", "CLOSED"]}}):
        key = (str(item.get("delivery_order_id")), str(item.get("delivery_product_line_id")))
        approved[key] = approved.get(key, 0) + int(item.get("approved_exception_quantity") or 0)
    pending_exception_keys = {(str(item.get("delivery_order_id")), str(item.get("delivery_product_line_id"))) for item in exceptions().find({"delivery_batch_id": run["_id"], "status": {"$in": ["OPEN", "UNDER_REVIEW"]}})}
    lines = []
    for row in _phase5_lines(run):
        key = (str(row["delivery_order_id"]), str(row["line_id"])); quantity_returned = returned.get(key, 0); approved_loss = approved.get(key, 0); outstanding = row["issued_quantity"] - row["delivered_quantity"] - quantity_returned - approved_loss
        status = "RECONCILED" if outstanding == 0 and run.get("status") in {"RECONCILED", "CLOSED"} else "BALANCED" if outstanding == 0 else "MISMATCH" if outstanding < 0 else "EXCEPTION_PENDING" if key in pending_exception_keys else "OUTSTANDING_RETURN" if quantity_returned < row["expected_return_quantity"] else "MISMATCH"
        lines.append({**{field: row[field] for field in ("delivery_order_id", "line_id", "customer_name", "product_name", "issued_quantity", "delivered_quantity", "expected_return_quantity")}, "returned_quantity": quantity_returned, "approved_exception_quantity": approved_loss, "outstanding_difference": outstanding, "reconciliation_status": status})
    balanced = bool(lines) and all(item["outstanding_difference"] == 0 for item in lines)
    overall_status = "RECONCILED" if balanced and run.get("status") in {"RECONCILED", "CLOSED"} else "BALANCED" if balanced else "MISMATCH" if any(item["reconciliation_status"] == "MISMATCH" for item in lines) else "EXCEPTION_PENDING" if any(item["reconciliation_status"] == "EXCEPTION_PENDING" for item in lines) else "OUTSTANDING_RETURN"
    return {"issued": sum(item["issued_quantity"] for item in lines), "delivered": sum(item["delivered_quantity"] for item in lines), "returned": sum(item["returned_quantity"] for item in lines), "approved_loss": sum(item["approved_exception_quantity"] for item in lines), "outstanding_difference": sum(item["outstanding_difference"] for item in lines), "balanced": balanced, "status": overall_status, "lines": serialize_custody({"lines": lines})["lines"]}


def reconcile_scheduler_batch(run_id: str, payload: dict, actor_id: str) -> dict:
    _, run = _phase5_run(run_id, actor_id)
    if run.get("status") in {"RECONCILED", "CLOSED"} or run.get("reconciled"): return _enrich_run(run)
    critical = exceptions().find_one({"delivery_batch_id": run["_id"], "severity": "CRITICAL", "status": {"$nin": ["RESOLVED", "CLOSED"]}})
    if critical: raise ApiError("Resolve critical exceptions before reconciliation.", status_code=409)
    summary = reconciliation_summary(run)
    if not summary["balanced"]:
        _notify_phase5(run, "Delivery reconciliation mismatch", f"{run.get('run_number') or run.get('batch_number')} has a difference of {summary['outstanding_difference']} item(s).", f"reconciliation-mismatch:{summary['outstanding_difference']}", "reconciliation.manage", priority="critical")
        raise ApiError("Reconciliation failed because issued quantities do not balance.", status_code=409, errors=summary["lines"])
    timestamp = now_utc(); updates = {"status": "RECONCILED", "reconciled": True, "reconciled_at": timestamp, "reconciled_by": object_id(actor_id), "reconciliation_summary": summary, "reconciliation_note": payload.get("note"), "updated_at": timestamp}
    with _transaction() as session:
        batches().update_one({"_id": run["_id"], "reconciled": {"$ne": True}}, {"$set": updates, "$push": {"status_history": {"from": run.get("status"), "to": "RECONCILED", "actor_id": object_id(actor_id), "timestamp": timestamp}}}, **_session(session))
    run.update(updates); _audit("delivery_batch_reconciled", actor_id, "delivery_batch", run["_id"], run["branch_id"], new=updates)
    _notify_phase5(run, "Batch ready for closure", f"{run.get('run_number') or run.get('batch_number')} is reconciled and ready to close.", "ready-for-closure", "delivery_batches.close")
    return _enrich_run(run)


def close_scheduler_batch(run_id: str, payload: dict, actor_id: str) -> dict:
    _, run = _phase5_run(run_id, actor_id)
    if run.get("status") == "CLOSED": return _enrich_run(run)
    if run.get("status") != "RECONCILED" or not run.get("reconciled"): raise ApiError("Reconcile the batch before closure.", status_code=409)
    if any(item.get("status") not in TERMINAL_STOP_STATUSES for item in run.get("stops", [])): raise ApiError("Every route stop requires an outcome before closure.", status_code=409)
    if sum(item["expected_return_quantity"] for item in _phase5_lines(run)) > 0 and not returns().find_one({"batch_id": run["_id"]}): raise ApiError("Receive expected returns before closure.", status_code=409)
    unresolved = exceptions().find_one({"delivery_batch_id": run["_id"], "status": {"$nin": ["RESOLVED", "CLOSED"]}})
    if unresolved: raise ApiError("Resolve all delivery exceptions before closure.", status_code=409)
    required_without_closed_investigation = exceptions().find_one({"delivery_batch_id": run["_id"], "requires_investigation": True, "investigation_status": {"$ne": "CLOSED"}})
    if required_without_closed_investigation: raise ApiError("Complete every required investigation before closure.", status_code=409)
    incomplete_investigation = investigations().find_one({"delivery_batch_id": run["_id"], "status": {"$ne": "CLOSED"}})
    if incomplete_investigation: raise ApiError("Complete required investigations before closure.", status_code=409)
    timestamp = now_utc(); closure = {"status": "CLOSED", "locked": True, "closed_at": timestamp, "closed_by": object_id(actor_id), "closure_note": payload.get("note"), "updated_at": timestamp}
    with _transaction() as session:
        batches().update_one({"_id": run["_id"]}, {"$set": closure, "$push": {"status_history": {"from": run.get("status"), "to": "CLOSED", "actor_id": object_id(actor_id), "timestamp": timestamp}}}, **_session(session))
        issues().update_many({"batch_id": run["_id"]}, {"$set": {"locked": True, "locked_at": timestamp}}, **_session(session)); orders().update_many({"_id": {"$in": run.get("delivery_order_ids", [])}}, {"$set": {"locked": True, "status": "CLOSED", "updated_at": timestamp}}, **_session(session)); returns().update_many({"batch_id": run["_id"]}, {"$set": {"locked": True, "locked_at": timestamp}}, **_session(session)); exceptions().update_many({"delivery_batch_id": run["_id"]}, {"$set": {"locked": True, "updated_at": timestamp}}, **_session(session)); investigations().update_many({"delivery_batch_id": run["_id"]}, {"$set": {"locked": True, "updated_at": timestamp}}, **_session(session))
    run.update(closure); _audit("delivery_batch_closed", actor_id, "delivery_batch", run["_id"], run["branch_id"], new=closure)
    _notify_phase5(run, "Delivery batch closed", f"{run.get('run_number') or run.get('batch_number')} was closed and its accountability records were locked.", f"closed:{timestamp.isoformat()}", "returns.manage", extra_recipients=[run.get("driver_id"), *(run.get("assigned_agent_ids") or [])])
    return _enrich_run(run)


def reopen_scheduler_batch(run_id: str, payload: dict, actor_id: str) -> dict:
    _, run = _phase5_run(run_id, actor_id); reason = str(payload.get("reason") or "").strip()
    if run.get("status") != "CLOSED": raise ApiError("Only a closed batch can be reopened.", status_code=409)
    if not reason: raise ApiError("A reopening reason is required.", status_code=400)
    timestamp = now_utc(); updates = {"status": "REOPENED", "locked": False, "reconciled": False, "reopened_at": timestamp, "reopened_by": object_id(actor_id), "reopening_reason": reason, "updated_at": timestamp}
    with _transaction() as session:
        batches().update_one({"_id": run["_id"]}, {"$set": updates, "$push": {"status_history": {"from": "CLOSED", "to": "REOPENED", "actor_id": object_id(actor_id), "reason": reason, "timestamp": timestamp}}}, **_session(session)); issues().update_many({"batch_id": run["_id"]}, {"$set": {"locked": False}}, **_session(session)); orders().update_many({"_id": {"$in": run.get("delivery_order_ids", [])}}, {"$set": {"locked": False, "updated_at": timestamp}}, **_session(session)); returns().update_many({"batch_id": run["_id"]}, {"$set": {"locked": False}}, **_session(session)); exceptions().update_many({"delivery_batch_id": run["_id"]}, {"$set": {"locked": False}}, **_session(session)); investigations().update_many({"delivery_batch_id": run["_id"]}, {"$set": {"locked": False}}, **_session(session))
    run.update(updates); _audit("delivery_batch_reopened", actor_id, "delivery_batch", run["_id"], run["branch_id"], new=updates, reason=reason)
    _notify_phase5(run, "Delivery batch reopened", f"{run.get('run_number') or run.get('batch_number')} was reopened: {reason}", f"reopened:{timestamp.isoformat()}", "returns.manage", extra_recipients=[run.get("driver_id"), *(run.get("assigned_agent_ids") or [])])
    return _enrich_run(run)


def delivery_accountability_report(actor_id: str, filters: dict) -> dict:
    data = list_accountability_batches(actor_id, {**filters, "page": 1, "page_size": min(int(filters.get("page_size") or 100), 100)})
    rows = data["batches"]
    def grouped(field):
        result = {}
        for row in rows:
            key = str(row.get(field) or "unassigned"); result[key] = result.get(key, 0) + 1
        return result
    return {"totals": {"batches": data["pagination"]["total"], "returns": sum(1 for row in rows if row.get("return")), "exceptions": sum(sum(row.get("exception_summary", {}).values()) for row in rows), "closed": sum(1 for row in rows if row.get("status") == "CLOSED")}, "by_driver": grouped("driver_id"), "by_vehicle": grouped("vehicle_id"), "batches": [{"id": row["id"], "batch_number": row.get("batch_number"), "status": row.get("status"), "reconciliation": row.get("reconciliation")} for row in rows]}
