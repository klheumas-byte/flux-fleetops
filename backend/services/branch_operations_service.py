from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from secrets import token_urlsafe

from bson import ObjectId

from extensions import get_collection
from models.user import serialize_user
from services.auth_service import create_user, reset_user_password_as
from services.branch_access_service import branch_ids_for_user, branch_query, current_user, object_id
from services.driver_scope_service import active_temporary_driver_ids
from services.rbac_service import user_role_codes
from utils.api_error import ApiError

TEAM_ROLES = {"field_agent", "driver", "branch_warehouse_coordinator"}
MANAGER_ROLES = {"branch_manager"}
GLOBAL_ROLES = {"owner", "admin", "system_administrator", "operations_administrator"}
OPEN_TRANSFER_STATUSES = {"approved", "assigned", "driver_confirmed", "loaded", "in_transit", "delivered", "awaiting_receipt"}
OPEN_EXCEPTION_STATUSES = {
    "OPEN",
    "REPORTED",
    "UNDER_REVIEW",
    "INVESTIGATING",
    "PENDING",
    "ACTION_REQUIRED",
    "open",
    "reported",
    "under_review",
    "investigating",
    "pending",
    "action_required",
}

def now_utc(): return datetime.now(timezone.utc)

def _actor(actor_id):
    actor = current_user(actor_id)
    if not set(user_role_codes(actor)) & (MANAGER_ROLES | GLOBAL_ROLES):
        raise ApiError("Branch Operations is restricted to Branch Managers and administrators.", status_code=403)
    return actor

def _manager(actor_id):
    actor = _actor(actor_id)
    if not set(user_role_codes(actor)) & MANAGER_ROLES:
        raise ApiError("Only a Branch Manager can manage a branch team.", status_code=403)
    if not actor.get("primary_branch_id"):
        raise ApiError("Your account has no primary branch.", status_code=409)
    return actor

def _match(branch_ids, field="branch_id"):
    return {} if branch_ids is None else {field: {"$in": list(branch_ids)}}

def list_branch_team(actor_id):
    actor = _actor(actor_id); branch_ids = branch_ids_for_user(actor)
    query = {"$or": [{"role": {"$in": list(TEAM_ROLES)}}, {"role_ids": {"$in": list(TEAM_ROLES)}}]}
    if branch_ids is not None:
        query["$and"] = [{"$or": [{"primary_branch_id": {"$in": list(branch_ids)}}, {"home_branch_id": {"$in": list(branch_ids)}}, {"allowed_branch_ids": {"$in": list(branch_ids)}}]}]
    rows = list(get_collection("users").find(query).sort("full_name", 1))
    temp_ids = active_temporary_driver_ids(branch_ids or []) if branch_ids is not None else set()
    active_ids = {row["driver_id"] for row in get_collection("delivery_batches").find({**_match(branch_ids), "status": {"$nin": ["COMPLETED", "CANCELLED", "CLOSED", "cancelled", "completed"]}, "driver_id": {"$ne": None}}, {"driver_id": 1}) if row.get("driver_id")}
    known = {row["_id"] for row in rows}; extra = (temp_ids | active_ids) - known
    if extra:
        rows.extend(get_collection("users").find({"_id": {"$in": list(extra)}, "$or": [{"role": "driver"}, {"role_ids": "driver"}]}))
    people = []
    for row in rows:
        item = serialize_user(row); item["temporary_assignment"] = row["_id"] in temp_ids; item["serving_active_delivery"] = row["_id"] in active_ids
        if "field_agent" in item.get("role_ids", []):
            delivery_query = {"assigned_field_agent_id": row["_id"], **_match(branch_ids)}
            item["delivery_summary"] = {
                "assigned": get_collection("delivery_orders").count_documents({**delivery_query, "status": {"$nin": ["COMPLETED", "DELIVERED", "completed", "delivered", "cancelled"]}}),
                "upcoming": get_collection("delivery_orders").count_documents({**delivery_query, "requested_delivery_date": {"$gte": date.today().isoformat()}, "status": {"$nin": ["COMPLETED", "DELIVERED", "completed", "delivered", "cancelled"]}}),
                "completed": get_collection("delivery_orders").count_documents({**delivery_query, "status": {"$in": ["COMPLETED", "DELIVERED", "completed", "delivered"]}}),
            }
        people.append(item)
    return {"staff": people, "field_agents": [x for x in people if "field_agent" in x.get("role_ids", [])], "drivers": [x for x in people if "driver" in x.get("role_ids", [])], "warehouse_coordinators": [x for x in people if "branch_warehouse_coordinator" in x.get("role_ids", [])]}

def create_field_agent(actor_id, payload):
    actor = _manager(actor_id)
    forced = {**payload, "role": "field_agent", "role_ids": ["field_agent"], "primary_branch_id": str(actor["primary_branch_id"]), "allowed_branch_ids": [], "created_by": actor_id, "status": "active", "temporary_password": True}
    return create_user(forced, "field_agent")

def _scoped_agent(actor, user_id):
    target = get_collection("users").find_one({"_id": object_id(user_id, "user_id")})
    if not target or "field_agent" not in user_role_codes(target): raise ApiError("Field Agent not found.", status_code=404)
    allowed = branch_ids_for_user(actor); target_branches = {x for x in [target.get("primary_branch_id"), *(target.get("allowed_branch_ids") or [])] if x}
    if allowed is not None and not allowed & target_branches: raise ApiError("You do not have access to this Field Agent.", status_code=403)
    return target

def update_field_agent(actor_id, user_id, payload):
    actor = _manager(actor_id); target = _scoped_agent(actor, user_id)
    updates = {key: payload.get(key) for key in {"full_name", "email", "phone", "username", "notes"} if key in payload}
    if not updates: raise ApiError("No editable Field Agent details were provided.", status_code=400)
    if "full_name" in updates and not str(updates["full_name"] or "").strip(): raise ApiError("Full name is required.", status_code=400)
    updates["updated_at"] = now_utc(); get_collection("users").update_one({"_id": target["_id"]}, {"$set": updates}); target.update(updates)
    return serialize_user(target)

def set_field_agent_status(actor_id, user_id, status):
    actor = _manager(actor_id); target = _scoped_agent(actor, user_id); value = str(status or "").lower()
    if value not in {"active", "inactive"}: raise ApiError("Field Agent status must be active or inactive.", status_code=400)
    get_collection("users").update_one({"_id": target["_id"]}, {"$set": {"status": value, "updated_at": now_utc()}}); target["status"] = value
    return serialize_user(target)

def reset_field_agent_access(actor_id, user_id, temporary_password=None):
    actor = _manager(actor_id); _scoped_agent(actor, user_id); password = temporary_password or token_urlsafe(8)
    user = reset_user_password_as(actor_id, "owner", user_id, password)
    return {"user": user, "temporary_password": password}

def create_driver_request(actor_id, payload):
    actor = _manager(actor_id)
    forced = {**payload, "role": "driver", "role_ids": ["driver"], "status": "inactive", "primary_branch_id": str(actor["primary_branch_id"]), "home_branch_id": str(actor["primary_branch_id"]), "operational_scope": "BRANCH", "allowed_branch_ids": [], "created_by": actor_id, "temporary_password": True, "driver_profile": {**(payload.get("driver_profile") or {}), "approval_status": "pending"}}
    user = create_user(forced, "driver"); get_collection("users").update_one({"_id": ObjectId(user["id"])}, {"$set": {"driver_request_status": "PENDING_APPROVAL", "driver_request_notes": payload.get("notes")}}); user["driver_request_status"] = "PENDING_APPROVAL"
    return user

def _group(status):
    value = str(status or "").upper()
    if value in {"DRAFT", "CERTIFIED", "WAITING_SCHEDULING", "READY_FOR_PLANNING"}: return "awaiting_planning"
    if value in {"SCHEDULED", "PUBLISHED", "LOCKED", "ASSIGNED", "ACCEPTED", "AWAITING_ISSUE", "AWAITING_DRIVER_ACKNOWLEDGEMENT"}: return "scheduled"
    if value in {"IN_PROGRESS", "STARTED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "ISSUED", "LOADED"}: return "in_progress"
    if value in {"COMPLETED", "DELIVERED", "RECONCILED", "CLOSED"}: return "completed"
    if value in {"FAILED", "PARTIALLY_DELIVERED", "PARTIAL", "CANCELLED"}: return "exceptions"
    return "scheduled"

def get_branch_operations_overview(actor_id):
    actor = _actor(actor_id); branch_ids = branch_ids_for_user(actor); today = date.today(); tomorrow = today + timedelta(days=1); week_end = today + timedelta(days=7)
    runs = list(get_collection("delivery_batches").find(_match(branch_ids)).sort([("delivery_date", 1), ("planned_departure_time", 1)]))
    unplanned_query = {**_match(branch_ids), "status": {"$in": ["CERTIFIED", "WAITING_SCHEDULING", "ready_for_planning"]}, "$or": [{"batch_id": None}, {"batch_id": {"$exists": False}}]}
    unplanned = list(get_collection("delivery_orders").find(unplanned_query).sort("requested_delivery_date", 1))
    user_ids = {x for run in runs for x in [run.get("driver_id"), run.get("field_agent_id"), *(run.get("assigned_agent_ids") or [])] if x}
    user_ids.update(row.get("assigned_field_agent_id") for row in unplanned if row.get("assigned_field_agent_id"))
    people = {x["_id"]: x.get("full_name") for x in get_collection("users").find({"_id": {"$in": list(user_ids)}})} if user_ids else {}
    vehicle_ids = {x.get("vehicle_id") for x in runs if x.get("vehicle_id")}; vehicles = {x["_id"]: x.get("registration_number") or x.get("vehicle_number") or x.get("make") for x in get_collection("vehicles").find({"_id": {"$in": list(vehicle_ids)}})} if vehicle_ids else {}
    board = {key: [] for key in ["awaiting_planning", "scheduled", "in_progress", "completed", "exceptions"]}
    for order in unplanned:
        board["awaiting_planning"].append({
            "id": str(order["_id"]), "record_type": "delivery_order", "run_number": None,
            "delivery_date": order.get("requested_delivery_date"), "expected_time": None,
            "status": order.get("status"), "readiness": "PLANNING_REQUIRED",
            "customer": order.get("customer_name"), "area": order.get("landmark") or order.get("delivery_address"),
            "products": [item.get("product_name") for item in order.get("product_lines", []) if item.get("product_name")],
            "field_agent": people.get(order.get("assigned_field_agent_id")), "field_agents": [people.get(order.get("assigned_field_agent_id"))] if people.get(order.get("assigned_field_agent_id")) else [], "transport_method": str(order.get("transport_method") or "VEHICLE").upper(),
            "driver": None, "handler": None, "vehicle": None, "delivery_count": 1,
        })
    for run in runs:
        order_rows = list(get_collection("delivery_orders").find({"_id": {"$in": run.get("delivery_order_ids", [])}})); first = order_rows[0] if order_rows else {}; stops = run.get("stops") or []
        method = str(run.get("transport_method") or "VEHICLE").upper(); manual = run.get("manual_transport") or {}
        missing = []
        if not run.get("delivery_date"): missing.append("date")
        if not run.get("planned_departure_time"): missing.append("time")
        if not (run.get("assigned_agent_ids") or run.get("field_agent_id")): missing.append("agent")
        if not stops: missing.append("route")
        if method == "VEHICLE":
            if not run.get("driver_id"): missing.append("driver")
            if not run.get("vehicle_id"): missing.append("vehicle")
        else:
            if not (manual.get("provider_name") or manual.get("handler_name")): missing.append("handler")
            if not (manual.get("phone") or manual.get("handler_phone")): missing.append("handler phone")
        readiness = "READY" if not missing else "PLANNING_REQUIRED" if len(missing) >= 4 else "PARTIALLY_PLANNED"
        products = list(dict.fromkeys(item.get("product_name") for order in order_rows for item in order.get("product_lines", []) if item.get("product_name")))
        run_agent_names = list(dict.fromkeys(people.get(value) for value in (run.get("assigned_agent_ids") or [run.get("field_agent_id")]) if people.get(value)))
        row = {"id": str(run["_id"]), "record_type": "delivery_run", "run_number": run.get("run_number") or run.get("batch_number"), "delivery_date": run.get("delivery_date"), "expected_time": run.get("planned_departure_time") or (stops[0].get("expected_arrival_time") if stops else None), "status": run.get("status"), "readiness": readiness, "missing_requirements": missing, "customer": first.get("customer_name") or (stops[0].get("customer_name") if stops else None), "area": first.get("landmark") or first.get("delivery_address") or (stops[0].get("landmark") if stops else None), "products": products, "field_agent": run_agent_names[0] if run_agent_names else None, "field_agents": run_agent_names, "transport_method": method, "driver": people.get(run.get("driver_id")), "handler": manual.get("provider_name") or manual.get("handler_name"), "vehicle": vehicles.get(run.get("vehicle_id")), "delivery_count": len(run.get("delivery_order_ids") or [])}
        board[_group(run.get("status"))].append(row)
    awaiting = len(unplanned)
    incoming = get_collection("stock_transfers").count_documents({**_match(branch_ids, "destination_branch_id"), "status": {"$in": list(OPEN_TRANSFER_STATUSES)}, "receiving_status": {"$ne": "received"}})
    open_exceptions = get_collection("delivery_exceptions").count_documents({**_match(branch_ids), "status": {"$in": list(OPEN_EXCEPTION_STATUSES)}})
    team = list_branch_team(actor_id); available = sum(1 for x in team["drivers"] if x.get("status") == "active" and str((x.get("driver_profile") or {}).get("approval_status") or "approved") == "approved")
    upcoming = {"today": [], "tomorrow": [], "this_week": []}; today_text = today.isoformat(); tomorrow_text = tomorrow.isoformat(); week_text = week_end.isoformat()
    for rows in board.values():
        for row in rows:
            value = row.get("delivery_date")
            if value == today_text: upcoming["today"].append(row)
            if value == tomorrow_text: upcoming["tomorrow"].append(row)
            if value and today_text <= value <= week_text: upcoming["this_week"].append(row)
    count = lambda key: sum(x["delivery_count"] for x in board[key])
    tomorrow_rows = upcoming["tomorrow"]
    tomorrow_summary = {"total": sum(x["delivery_count"] for x in tomorrow_rows), "ready": sum(x["delivery_count"] for x in tomorrow_rows if x.get("readiness") == "READY"), "planning_required": sum(x["delivery_count"] for x in tomorrow_rows if x.get("readiness") != "READY")}
    kpis = {"deliveries_today": sum(x["delivery_count"] for x in upcoming["today"]), "tomorrow": tomorrow_summary["total"], "upcoming": sum(x["delivery_count"] for x in upcoming["this_week"]), "awaiting_planning": awaiting, "scheduled": count("scheduled"), "in_progress": count("in_progress"), "completed": count("completed"), "failed_partial": count("exceptions"), "incoming_stock": incoming, "open_exceptions": open_exceptions, "available_branch_drivers": available}
    return {"kpis": kpis, "board": board, "upcoming": upcoming, "tomorrow_summary": tomorrow_summary}
