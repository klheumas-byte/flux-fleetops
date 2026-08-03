from __future__ import annotations

from datetime import datetime, timezone
import re

from bson import ObjectId
from flask import g, has_app_context, request
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection


DATA_SCOPES = (
    "OWN_RECORDS", "ASSIGNED_RECORDS", "PRIMARY_BRANCH",
    "ALLOWED_BRANCHES", "ALL_BRANCHES", "ALL_RECORDS",
)
SCOPE_RANK = {scope: index for index, scope in enumerate(DATA_SCOPES)}

# These definitions are compatibility seeds, not a second role system. Persisted
# records in `roles` override them, while legacy installations work immediately.
ROLE_DEFINITIONS = {
    "system_administrator": {
        "name": "System Administrator", "dashboard": "system-dashboard",
        "description": "Manages system configuration and access control.",
        "default_data_scope": "ALL_RECORDS", "system": True,
        "permissions": [
            "users.manage", "users.manage_operational", "roles.manage", "permissions.manage",
            "branches.view", "branches.manage", "vehicle.view", "vehicle.manage",
            "system.configure", "audit.view", "security.manage", "notifications.view",
        ],
    },
    "operations_administrator": {
        "name": "Operations Administrator", "dashboard": "dashboard",
        "description": "Administers fleet and delivery operations across branches.",
        "default_data_scope": "ALL_BRANCHES", "system": True,
        "permissions": [
            "users.manage_operational", "branches.view", "operations.view_all", "deliveries.view",
            "deliveries.create", "deliveries.update", "deliveries.manage", "deliveries.assign", "delivery_scheduler.view", "delivery_scheduler.manage", "delivery_runs.publish", "delivery_runs.lock", "delivery_runs.override_lock", "loading_schedule.view",
            "batches.create", "batches.manage", "delivery.create", "delivery.update", "delivery.batch",
            "driver.assign", "driver.view", "driver.update", "drivers.assign", "vehicle.assign",
            "vehicles.assign", "vehicle.view", "vehicle.manage", "maintenance.view", "maintenance.manage",
            "fault.view", "fault.manage", "items.issue", "items.receive", "items.correct", "items.reissue", "custody.view", "custody.accept", "custody.dispute",
            "delivery_execution.accept", "delivery_execution.start", "delivery_execution.stop_update", "delivery_execution.complete", "delivery_execution.override_custody", "returns.manage",
            "operations.reports", "operations.view", "notifications.view",
        ],
    },
    "operations_manager": {
        "name": "Operations Manager", "dashboard": "operations-dashboard",
        "description": "Coordinates day-to-day operations for allowed branches.",
        "default_data_scope": "ALLOWED_BRANCHES", "system": True,
        "permissions": [
            "branches.view", "deliveries.view", "deliveries.create", "deliveries.update", "delivery_scheduler.view", "delivery_scheduler.manage", "delivery_runs.publish", "delivery_runs.lock", "loading_schedule.view",
            "deliveries.manage", "deliveries.assign", "batches.create", "batches.manage",
            "delivery.create", "delivery.update", "delivery.batch", "driver.assign", "drivers.assign",
            "driver.view", "vehicle.assign", "vehicles.assign", "vehicle.view", "maintenance.view",
            "maintenance.manage", "fault.view", "items.correct", "items.reissue", "returns.manage", "operations.view", "notifications.view",
        ],
    },
    "driver": {
        "name": "Driver", "dashboard": "dashboard", "system": True,
        "description": "Completes assigned trips, deliveries and vehicle tasks.",
        "default_data_scope": "ASSIGNED_RECORDS",
        "permissions": [
            "deliveries.view_own", "delivery.view_own", "delivery.accept", "delivery.execute",
            "trips.execute", "vehicle.view_assigned", "fault.report", "returns.record_own", "delivery_schedule.view_assigned", "custody.view", "custody.accept", "custody.dispute",
            "delivery_execution.accept", "delivery_execution.start", "delivery_execution.stop_update", "delivery_execution.complete",
            "notifications.view", "trip.view_own",
        ],
    },
    "field_agent": {
        "name": "Field Agent", "dashboard": "field-dashboard", "system": True,
        "description": "Works assigned customer and delivery records.",
        "default_data_scope": "ASSIGNED_RECORDS",
        "permissions": ["deliveries.view_assigned", "delivery.view_assigned", "delivery.confirm", "delivery_schedule.view_assigned", "customer.view_assigned", "customer.issue_report", "notifications.view"],
    },
    "issuing_receiving_officer": {
        "name": "Issuing / Receiving Officer", "dashboard": "items-dashboard", "system": True,
        "description": "Controls branch item issue and return workflows.",
        "default_data_scope": "PRIMARY_BRANCH",
        "permissions": ["branches.view", "deliveries.view", "loading_schedule.view", "items.issue", "items.reissue", "items.receive", "items.history", "driver.view_waiting", "custody.view", "returns.manage"],
    },
    "branch_manager": {
        "name": "Branch Manager", "dashboard": "dashboard", "system": True,
        "description": "Provides operational oversight for explicitly assigned branches.",
        "default_data_scope": "PRIMARY_BRANCH",
        "permissions": [
            "branches.view_assigned", "delivery_operations.view_branch", "branch_operations.view",
            "stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify",
            "stock_transfers.report_variance", "stock_transfers.view_history", "notifications.view",
            "driver.view", "vehicle.view", "operations.view",
        ],
    },
    "branch_warehouse_coordinator": {
        "name": "Branch Warehouse Coordinator", "dashboard": "items-dashboard", "system": True,
        "description": "Receives, verifies and safeguards stock for explicitly assigned branches.",
        "default_data_scope": "PRIMARY_BRANCH",
        "permissions": [
            "stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify",
            "stock_transfers.report_variance", "stock_transfers.view_history", "notifications.view",
        ],
    },
    "finance_officer": {
        "name": "Finance Officer", "dashboard": "finance-dashboard", "system": True,
        "description": "Works with approved operational finance records.",
        "default_data_scope": "ALLOWED_BRANCHES",
        "permissions": ["finance.view", "operational_expenses.view", "expenses.manage", "fuel.expenses", "repair.payments", "finance.operational_reports"],
    },
    "owner": {"name": "Owner (Legacy)", "dashboard": "dashboard", "description": "Legacy owner account.", "default_data_scope": "ALL_RECORDS", "permissions": ["*"], "system": True, "legacy": True},
    "admin": {"name": "Administrator (Legacy)", "dashboard": "dashboard", "description": "Legacy operational administrator.", "default_data_scope": "ALL_BRANCHES", "inherits": "operations_administrator", "system": True, "legacy": True},
    "dispatcher": {"name": "Dispatcher (Legacy)", "dashboard": "dispatch-requests", "description": "Legacy dispatch account.", "default_data_scope": "ALLOWED_BRANCHES", "inherits": "operations_manager", "system": True, "legacy": True},
    "customer_service": {"name": "Customer Service (Legacy)", "dashboard": "dispatch-requests", "description": "Legacy customer service account.", "default_data_scope": "ASSIGNED_RECORDS", "permissions": ["delivery.create", "delivery.update", "notifications.view"], "system": True, "legacy": True},
    "fleet_owner": {"name": "Fleet Owner", "dashboard": "dashboard", "description": "Fleet owner portal account.", "default_data_scope": "OWN_RECORDS", "permissions": ["fleet_owner.portal"], "system": True, "legacy": True},
    "personal_vehicle_owner": {"name": "Personal Vehicle Owner", "dashboard": "dashboard", "description": "Personal vehicle owner portal account.", "default_data_scope": "OWN_RECORDS", "permissions": ["personal_vehicle.portal"], "system": True, "legacy": True},
}

# Persisted built-in roles override compatibility seeds. Merge only these
# required phase permissions so existing installations gain the workflow
# without replacing administrator-defined custom roles.
SYSTEM_PERMISSION_ADDITIONS = {
    "system_administrator": {"users.manage_operational", "stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify", "stock_transfers.report_variance", "stock_transfers.view_history"},
    "operations_administrator": {"delivery_batches.view", "delivery_batches.create", "delivery_batches.update", "delivery_batches.publish", "delivery_batches.assign", "delivery_routes.manage", "delivery_execution.manage", "delivery_execution.override", "delivery_items.issue", "delivery_items.acknowledge", "returns.receive", "returns.manage", "exceptions.manage", "investigations.manage", "reconciliation.manage", "delivery_batches.close", "delivery_batches.reopen", "branches.view_assigned", "delivery_operations.view_branch", "branch_operations.view", "stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify", "stock_transfers.report_variance", "stock_transfers.view_history"},
    "operations_manager": {"delivery_batches.view", "delivery_batches.create", "delivery_batches.update", "delivery_batches.publish", "delivery_batches.assign", "delivery_routes.manage", "delivery_execution.manage", "returns.manage", "exceptions.manage", "investigations.manage", "reconciliation.manage", "delivery_batches.close"},
    "driver": {"delivery_batches.view", "delivery_routes.execute", "delivery_items.acknowledge", "delivery_execution.manage"},
    "field_agent": {"delivery_batches.view"},
    "issuing_receiving_officer": {"delivery_batches.view", "delivery_items.issue", "returns.receive", "returns.manage"},
    "branch_manager": {"branches.view_assigned", "delivery_operations.view_branch", "branch_operations.view", "stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify", "stock_transfers.report_variance", "stock_transfers.view_history", "driver.view", "vehicle.view", "operations.view", "notifications.view"},
    "branch_warehouse_coordinator": {"stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify", "stock_transfers.report_variance", "stock_transfers.view_history", "notifications.view"},
}

PERMISSION_MODULES = {
    "Users": ["users.view", "users.create", "users.update", "users.manage", "users.manage_operational"],
    "Roles": ["roles.view", "roles.create", "roles.update", "roles.manage"],
    "Permissions": ["permissions.view", "permissions.manage"],
    "Branches": ["branches.view", "branches.view_assigned", "branches.create", "branches.update", "branches.manage", "branch_operations.view"],
    "Stock Transfers": ["stock_transfers.view_incoming", "stock_transfers.receive", "stock_transfers.verify", "stock_transfers.report_variance", "stock_transfers.view_history"],
    "Dispatch": ["delivery.create", "delivery.update", "delivery.batch"],
    "Delivery Operations": ["deliveries.view", "deliveries.create", "deliveries.update", "deliveries.manage", "deliveries.assign", "delivery_operations.view_branch", "delivery.accept", "delivery.execute", "delivery.confirm", "deliveries.view_own", "deliveries.view_assigned", "delivery_schedule.view_assigned", "loading_schedule.view", "delivery_batches.view", "delivery_batches.create", "delivery_batches.update", "delivery_batches.publish", "delivery_batches.assign", "delivery_routes.manage", "delivery_routes.execute", "delivery_items.issue", "delivery_items.acknowledge", "delivery_execution.manage", "delivery_execution.override"],
    "Operations Planner": ["operations.view", "operations.view_all", "operations.reports", "batches.create", "batches.manage", "delivery_scheduler.view", "delivery_scheduler.manage", "delivery_runs.publish", "delivery_runs.lock", "delivery_runs.override_lock"],
    "Operational Tasks": ["trips.execute", "trip.view_own", "returns.record_own", "delivery_execution.accept", "delivery_execution.start", "delivery_execution.stop_update", "delivery_execution.complete", "delivery_execution.override_custody"],
    "Drivers": ["driver.view", "driver.update", "driver.assign", "drivers.assign", "driver.view_waiting"],
    "Field Agents": ["customer.view_assigned", "customer.issue_report"],
    "Vehicles": ["vehicle.view", "vehicle.manage", "vehicle.view_assigned", "vehicle.assign", "vehicles.assign"],
    "Vehicle Movement": ["vehicle_movements.view", "vehicle_movements.create", "vehicle_movements.update", "vehicle_movements.approve"],
    "Maintenance": ["maintenance.view", "maintenance.manage", "fault.view", "fault.manage", "fault.report"],
    "Item Issue and Returns": ["items.issue", "items.reissue", "items.receive", "items.correct", "items.history", "custody.view", "custody.accept", "custody.dispute", "returns.manage"],
    "Delivery Accountability": ["returns.receive", "returns.manage", "exceptions.manage", "investigations.manage", "reconciliation.manage", "delivery_batches.close", "delivery_batches.reopen"],
    "Finance": ["finance.view", "operational_expenses.view", "profitability.view", "expenses.manage", "fuel.expenses", "repair.payments", "finance.operational_reports"],
    "Reports": ["reports.view", "reports.export", "audit.view"],
    "Audit Logs": ["audit.view", "audit.export"],
    "System Settings": ["system.configure", "security.manage", "notifications.view"],
}
PERMISSION_CATALOG = {item for items in PERMISSION_MODULES.values() for item in items}
PERMISSION_CATALOG.update({permission for definition in ROLE_DEFINITIONS.values() for permission in definition.get("permissions", []) if permission != "*"})


def now_utc():
    return datetime.now(timezone.utc)


def normalize_role(value) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or None


def _role_code_from_reference(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("code") or value.get("role_code") or value.get("id") or value.get("_id")
    if value is None:
        return None
    raw = str(value).strip()
    if ObjectId.is_valid(raw) and has_app_context():
        for code, document in _stored_roles().items():
            if str(document.get("_id")) == raw:
                return code
    return normalize_role(raw)


def user_role_codes(user: dict | None) -> list[str]:
    if not user:
        return []
    raw_values = []
    if isinstance(user.get("role_ids"), list):
        raw_values.extend(user["role_ids"])
    if isinstance(user.get("roles"), list):
        raw_values.extend(user["roles"])
    raw_values.extend([user.get("role"), user.get("user_type")])
    values = []
    for item in raw_values:
        code = _role_code_from_reference(item)
        if code and code not in values:
            values.append(code)
    return values


def _stored_roles() -> dict[str, dict]:
    if not has_app_context():
        return {}
    cache = getattr(g, "_flux_stored_role_cache", None)
    if cache is None:
        try:
            cache = {
                normalize_role(item.get("code")): item
                for item in get_collection("roles").find({})
                if normalize_role(item.get("code"))
            }
        except Exception:
            cache = {}
        g._flux_stored_role_cache = cache
    return cache


def _stored_role(code: str) -> dict | None:
    return _stored_roles().get(code)


def role_definition(role: str | None) -> dict:
    code = normalize_role(role)
    stored = _stored_role(code) if code else None
    definition = dict(stored or ROLE_DEFINITIONS.get(code, {}))
    if code in SYSTEM_PERMISSION_ADDITIONS:
        definition["permissions"] = sorted(set(definition.get("permissions", [])) | SYSTEM_PERMISSION_ADDITIONS[code])
    inherited = definition.get("inherits")
    if inherited:
        parent = role_definition(inherited)
        definition["permissions"] = parent.get("permissions", [])
    definition.setdefault("code", code)
    definition.setdefault("status", "active")
    definition.setdefault("default_data_scope", "OWN_RECORDS")
    return definition


def permissions_for_user(user: dict | None) -> list[str]:
    if not user:
        return []
    permissions = set()
    for code in user_role_codes(user):
        definition = role_definition(code)
        if definition and definition.get("status", "active") == "active":
            permissions.update(definition.get("permissions", []))
    permissions.update(str(item).strip() for item in user.get("permission_grants", []) if str(item).strip())
    permissions.difference_update(str(item).strip() for item in user.get("permission_denials", []) if str(item).strip())
    return sorted(permissions)


def effective_data_scope(user: dict | None) -> str:
    scopes = [role_definition(code).get("default_data_scope", "OWN_RECORDS") for code in user_role_codes(user)]
    return max(scopes, key=lambda item: SCOPE_RANK.get(item, 0), default="OWN_RECORDS")


def primary_workspace(user: dict | None) -> str | None:
    codes = user_role_codes(user)
    selected = _role_code_from_reference((user or {}).get("selected_workspace"))
    if selected in codes and role_definition(selected).get("status") == "active":
        return selected
    return codes[0] if codes else None


def user_has_permission(user: dict | None, permission: str) -> bool:
    permissions = permissions_for_user(user)
    return "*" in permissions or permission in permissions


def dashboard_for_role(role: str | None) -> str:
    return role_definition(role).get("dashboard") or "dashboard"


def _assigned_count(code: str) -> int:
    if not has_app_context():
        return 0
    return get_collection("users").count_documents({"$or": [{"role": code}, {"role_ids": code}]})


def serialize_role(role: str, definition: dict) -> dict:
    code = normalize_role(role)
    resolved = role_definition(code)
    return {
        "id": code, "code": code,
        "name": definition.get("name") or code.replace("_", " ").title(),
        "description": definition.get("description") or "",
        "dashboard": resolved.get("dashboard") or "dashboard",
        "permissions": sorted(resolved.get("permissions", [])),
        "default_data_scope": resolved.get("default_data_scope", "OWN_RECORDS"),
        "status": definition.get("status", "active"),
        "system": bool(definition.get("system", code in ROLE_DEFINITIONS)),
        "legacy": bool(definition.get("legacy")),
        "assigned_user_count": _assigned_count(code),
        "created_at": definition.get("created_at").isoformat() if hasattr(definition.get("created_at"), "isoformat") else None,
        "updated_at": definition.get("updated_at").isoformat() if hasattr(definition.get("updated_at"), "isoformat") else None,
    }


def list_roles(include_inactive=True) -> list[dict]:
    definitions = {code: dict(value) for code, value in ROLE_DEFINITIONS.items()}
    if has_app_context():
        try:
            for item in get_collection("roles").find({}):
                definitions[item["code"]] = item
        except Exception:
            pass
    roles = [serialize_role(code, definition) for code, definition in definitions.items()]
    if not include_inactive:
        roles = [role for role in roles if role["status"] == "active"]
    return sorted(roles, key=lambda item: item["name"].lower())


def permission_groups() -> list[dict]:
    result = []
    for module, codes in PERMISSION_MODULES.items():
        result.append({"module": module, "permissions": [{"code": code, "action": code.rsplit(".", 1)[-1].replace("_", " ").title(), "sensitive": code in {"profitability.view", "permissions.manage", "roles.manage", "users.manage", "security.manage"}} for code in sorted(set(codes))]})
    return result


def validate_role_assignment(actor: dict, role_codes: list[str]):
    actor_permissions = set(permissions_for_user(actor))
    elevated = "*" in actor_permissions
    policy_manager = "permissions.manage" in actor_permissions
    for code in role_codes:
        definition = role_definition(code)
        if not definition or definition.get("status") != "active":
            raise ApiError(f"Role '{code}' is unavailable.", status_code=400)
        requested = set(definition.get("permissions", []))
        if not elevated and not policy_manager and not requested.issubset(actor_permissions):
            raise ApiError("You cannot assign a role containing permissions beyond your authority.", status_code=403)
        if "profitability.view" in requested and "profitability.view" not in actor_permissions and not elevated:
            raise ApiError("You are not authorized to grant profitability access.", status_code=403)


def ensure_rbac_indexes():
    ensure_indexes_for_collection(get_collection("roles"), [
        {"keys": [("code", ASCENDING)], "options": {"unique": True}},
        {"keys": [("status", ASCENDING), ("name", ASCENDING)]},
    ], collection_name="roles")
    ensure_indexes_for_collection(get_collection("branches"), [
        {"keys": [("code", ASCENDING)], "options": {"unique": True}},
        {"keys": [("status", ASCENDING), ("name", ASCENDING)]},
    ], collection_name="branches")
    ensure_indexes_for_collection(get_collection("audit_logs"), [
        {"keys": [("created_at", DESCENDING)]},
        {"keys": [("action", ASCENDING), ("created_at", DESCENDING)]},
        {"keys": [("actor_user_id", ASCENDING), ("created_at", DESCENDING)]},
    ], collection_name="audit_logs")


def write_audit(action: str, actor_user_id=None, target_type=None, target_id=None, changes=None, metadata=None):
    actor_id = ObjectId(str(actor_user_id)) if actor_user_id and ObjectId.is_valid(str(actor_user_id)) else None
    metadata = metadata or {}
    change_values = changes or {}
    ip_address = None
    device = None
    if has_app_context():
        try:
            ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
            device = request.headers.get("User-Agent")
        except RuntimeError:
            pass
    get_collection("audit_logs").insert_one({
        "action": action, "actor_user_id": actor_id, "target_type": target_type,
        "target_id": str(target_id) if target_id is not None else None,
        "changes": change_values, "old_values": change_values.get("old") or change_values.get("before") or {},
        "new_values": change_values.get("new") or change_values.get("after") or {},
        "reason": change_values.get("reason"), "branch_id": str(metadata.get("branch_id")) if metadata.get("branch_id") is not None else None,
        "metadata": metadata, "ip_address": ip_address, "device": device, "created_at": now_utc(),
    })


def serialize_audit(document: dict) -> dict:
    return {
        "id": str(document.get("_id")), "action": document.get("action"),
        "actor_user_id": str(document.get("actor_user_id")) if document.get("actor_user_id") else None,
        "target_type": document.get("target_type"), "target_id": document.get("target_id"),
        "changes": document.get("changes") or {}, "metadata": document.get("metadata") or {},
        "old_values": document.get("old_values") or {}, "new_values": document.get("new_values") or {},
        "reason": document.get("reason"), "branch_id": document.get("branch_id"),
        "ip_address": document.get("ip_address"), "device": document.get("device"),
        "created_at": document.get("created_at").isoformat() if document.get("created_at") else None,
    }
