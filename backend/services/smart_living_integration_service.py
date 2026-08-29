from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import perf_counter, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from bson import ObjectId
from flask import current_app, has_app_context
from pymongo import ASCENDING, DESCENDING, UpdateOne
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.integration import serialize_integration_record
from services.branch_access_service import assert_user_in_branch, current_user, object_id
from services.auth_service import create_user, reset_user_password_as
from services.rbac_service import user_can_manage_smartliving, user_role_codes, write_audit
from services.smart_living_delivery_service import AGENT_ROLE_CODES, create_certified_order
from utils.api_error import ApiError


SOURCE_SYSTEM = "smartliving"
LOGGER = logging.getLogger(__name__)
MAPPING_TYPES = {"branch", "manager", "agent"}
EXCEPTION_TYPES = {
    "unmapped_branch", "unmapped_agent", "unmapped_manager", "missing_required_data",
    "conflicting_source_record", "invalid_source_data",
}
INTEGRATION_AUDIT_ACTIONS = {
    "smartliving_imported", "smartliving_updated", "smartliving_duplicate_skipped",
    "smartliving_mapping_failed", "smartliving_validation_failed",
    "smartliving_exception_resolved", "smartliving_exception_retried",
    "smartliving_import_batch_completed",
    "smartliving_agent_resolved", "smartliving_agent_provisioned",
    "smartliving_agent_linked", "smartliving_identity_role_linked",
    "smartliving_agent_credentials_reissued",
    "smartliving_manager_matched", "smartliving_manager_provisioned",
    "smartliving_manager_reevaluated", "smartliving_mapping_backfilled",
}
SOURCE_ENDPOINTS = ("completed-cards", "closed-cards")
SOURCE_DATE_FIELDS = {"completed-cards": "created_at", "closed-cards": "at"}
SOURCE_OPTIONS = {"completed-cards", "closed-cards", "both"}
SMARTLIVING_PAGE_LIMIT = 100
DEFAULT_TEMPORARY_PASSWORD = "fleet@12345"
CANONICAL_BLOCKERS = (
    "missing_source_id", "missing_customer_name", "missing_customer_phone", "missing_customer_location",
    "missing_product", "missing_product_name", "missing_product_reference", "missing_quantity",
    "conflicting_quantity", "conflicting_product_line", "stock_not_confirmed",
    "unsupported_status", "unsupported_action", "no_delivery_targets",
    "missing_branch", "unmapped_branch", "missing_agent", "unmapped_agent", "unmapped_manager",
    "invalid_source_date", "duplicate",
)
COMPLETED_CARD_READY_STATUSES = {"pending", "completed", "closed", "delivered"}


def now_utc():
    return datetime.now(timezone.utc)


def _log_info(message: str, *args) -> None:
    logger = current_app.logger if has_app_context() else LOGGER
    logger.info(message, *args)


def mappings():
    return get_collection("integration_mappings")


def exceptions():
    return get_collection("integration_exceptions")


def connections():
    return get_collection("integration_connections")


def discoveries():
    return get_collection("integration_discoveries")


def dry_runs():
    return get_collection("integration_dry_runs")


def orders():
    return get_collection("delivery_orders")


def _duplicate_key_samples(collection, fields: tuple[str, ...], *, string_values_only=False) -> list[dict]:
    seen = set(); duplicates = []
    for row in collection.find({}, {field: 1 for field in fields}):
        values = tuple(row.get(field) for field in fields)
        if string_values_only and not all(isinstance(value, str) for value in values):
            continue
        if values in seen and values not in duplicates:
            duplicates.append(values)
            if len(duplicates) >= 10:
                break
        seen.add(values)
    return [dict(zip(fields, values)) for values in duplicates]


def ensure_mapping_unique_index():
    fields = ("source_system", "mapping_type", "external_key")
    duplicates = _duplicate_key_samples(mappings(), fields)
    if duplicates:
        raise RuntimeError(f"Cannot create integration_mapping_source_unique; duplicate mapping keys exist: {duplicates}")
    mappings().create_index(
        [("source_system", ASCENDING), ("mapping_type", ASCENDING), ("external_key", ASCENDING)],
        name="integration_mapping_source_unique", unique=True,
    )


def ensure_indexes():
    ensure_mapping_unique_index()
    mappings().create_index([("mapping_type", ASCENDING), ("active", ASCENDING), ("updated_at", DESCENDING)])
    exceptions().create_index([("open_key", ASCENDING)], name="integration_exception_open_unique", unique=True, sparse=True)
    exceptions().create_index([("source_system", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)])
    connections().create_index([("source_system", ASCENDING)], name="integration_connection_source_unique", unique=True)
    discoveries().create_index(
        [("source_system", ASCENDING), ("discovery_type", ASCENDING), ("external_key", ASCENDING)],
        name="integration_discovery_source_unique", unique=True,
    )
    dry_runs().create_index([("source_system", ASCENDING), ("created_at", DESCENDING)])
    duplicate_agents = _duplicate_key_samples(get_collection("users"), ("smartliving_agent_id",), string_values_only=True)
    if duplicate_agents:
        raise RuntimeError(f"Cannot create users_smartliving_agent_unique; duplicate SmartLiving agent IDs exist: {duplicate_agents}")
    get_collection("users").create_index(
        [("smartliving_agent_id", ASCENDING)], name="users_smartliving_agent_unique", unique=True, sparse=True,
    )
    duplicate_managers = _duplicate_key_samples(get_collection("users"), ("smartliving_manager_id",), string_values_only=True)
    if duplicate_managers:
        raise RuntimeError(f"Cannot create users_smartliving_manager_unique; duplicate SmartLiving manager IDs exist: {duplicate_managers}")
    get_collection("users").create_index(
        [("smartliving_manager_id", ASCENDING)], name="users_smartliving_manager_unique", unique=True, sparse=True,
    )


def _actor(actor_id: str) -> dict:
    actor = current_user(actor_id)
    if not user_can_manage_smartliving(actor):
        raise ApiError("You do not have permission to manage integrations.", status_code=403)
    return actor


def _text(value, field: str, limit=240) -> str:
    result = str(value or "").strip()
    if not result:
        raise ApiError(f"{field} is required.", status_code=400)
    if len(result) > limit:
        raise ApiError(f"{field} is too long.", status_code=400)
    return result


def _external_key(external_id=None, external_code=None) -> tuple[str, str, str | None]:
    external_id = str(external_id or "").strip()
    external_code = str(external_code or "").strip()
    value = external_id or external_code
    if not value:
        raise ApiError("external_id or external_code is required.", status_code=400)
    return value.casefold(), external_id, external_code or None


def normalize_branch_key(value) -> str:
    """Normalize exact branch labels without fuzzy or similarity matching."""
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


HQ_BRANCH_ALIAS_KEYS = {
    "hq", "head office", "headquarter", "headquarters", "head quarter", "head quarters",
    "head quater", "head quaters",
}


def canonical_branch_alias_key(value) -> str:
    """Resolve only explicit, known source aliases; never fuzzy-match a branch or person."""
    key = normalize_branch_key(value)
    return "hq" if key in HQ_BRANCH_ALIAS_KEYS else key


def _coded_error(code: str, message: str, status_code=409):
    raise ApiError(message, status_code=status_code, errors=[{"code": code, "message": message}])


def _temporary_password() -> str:
    return str(current_app.config.get("SMARTLIVING_TEMPORARY_PASSWORD") or DEFAULT_TEMPORARY_PASSWORD) if has_app_context() else DEFAULT_TEMPORARY_PASSWORD


def _agent_temporary_password(length: int = 20) -> str:
    """Return the same configured first-login password used by manager provisioning."""
    return _temporary_password().strip() or DEFAULT_TEMPORARY_PASSWORD


def _mapping_target(mapping_type: str, fleetops_id, *, branch_id=None):
    target_id = object_id(fleetops_id, "fleetops_id")
    if mapping_type == "branch":
        target = get_collection("branches").find_one({"_id": target_id})
        if not target:
            raise ApiError("FleetOps Branch not found.", status_code=404)
        if str(target.get("status") or ("active" if target.get("active", True) else "inactive")).lower() != "active":
            raise ApiError("FleetOps Branch must be active.", status_code=409)
    elif mapping_type == "manager":
        target = get_collection("users").find_one({"_id": target_id})
        if not target or "branch_manager" not in user_role_codes(target):
            raise ApiError("FleetOps Branch Manager not found.", status_code=404)
        if str(target.get("status") or "").lower() != "active":
            raise ApiError("FleetOps Branch Manager must be active.", status_code=409)
    else:
        target = assert_user_in_branch(target_id, branch_id, AGENT_ROLE_CODES) if branch_id else get_collection("users").find_one({"_id": target_id})
        if not target or not set(AGENT_ROLE_CODES).intersection(user_role_codes(target)):
            raise ApiError("FleetOps Field Agent not found.", status_code=404)
        if str(target.get("status") or ("active" if target.get("active", True) else "inactive")).lower() != "active":
            raise ApiError("FleetOps Field Agent must be active.", status_code=409)
    return target_id


def list_mappings(mapping_type: str, actor_id: str) -> dict:
    _actor(actor_id)
    if mapping_type not in MAPPING_TYPES:
        raise ApiError("Invalid mapping type.", status_code=400)
    rows = mappings().find({"source_system": SOURCE_SYSTEM, "mapping_type": mapping_type}).sort("updated_at", DESCENDING)
    return {"mappings": [serialize_integration_record(row) for row in rows]}


def create_mapping(mapping_type: str, payload: dict, actor_id: str) -> dict:
    _actor(actor_id)
    if mapping_type not in MAPPING_TYPES:
        raise ApiError("Invalid mapping type.", status_code=400)
    external_key, external_id, external_code = _external_key(payload.get("external_id"), payload.get("external_code"))
    if mapping_type == "branch":
        external_key = normalize_branch_key(external_id or external_code)
        semantic_duplicate = next((row for row in mappings().find({"source_system": SOURCE_SYSTEM, "mapping_type": "branch"}) if normalize_branch_key(row.get("external_id") or row.get("external_code") or row.get("external_display_name")) == external_key), None)
        if semantic_duplicate:
            raise ApiError("This normalized SmartLiving branch is already mapped.", status_code=409)
    fleetops_id = _mapping_target(mapping_type, payload.get("fleetops_id"))
    if mapping_type in {"manager", "agent"}:
        other_type = "agent" if mapping_type == "manager" else "manager"
        other_mapping = mappings().find_one({
            "source_system": SOURCE_SYSTEM, "mapping_type": other_type,
            "external_key": external_key, "active": True,
        })
        if other_mapping and other_mapping.get("fleetops_id") != fleetops_id:
            raise ApiError(
                "This SmartLiving identity is already linked to another FleetOps user in its other role.",
                status_code=409,
            )
    timestamp = now_utc()
    document = {
        "source_system": SOURCE_SYSTEM, "mapping_type": mapping_type,
        "external_key": external_key, "external_id": external_id or None, "external_code": external_code,
        "external_display_name": str(payload.get("external_display_name") or "").strip() or None,
        "fleetops_id": fleetops_id, "active": bool(payload.get("active", True)),
        "created_by": object_id(actor_id), "updated_by": object_id(actor_id),
        "created_at": timestamp, "updated_at": timestamp,
    }
    try:
        result = mappings().insert_one(document)
    except DuplicateKeyError:
        raise ApiError("This SmartLiving external identifier is already mapped.", status_code=409) from None
    document["_id"] = result.inserted_id
    write_audit("smartliving_mapping_created", actor_id, "integration_mapping", result.inserted_id, {"new": document})
    return serialize_integration_record(document)


def update_mapping(mapping_type: str, mapping_id: str, payload: dict, actor_id: str) -> dict:
    _actor(actor_id)
    if mapping_type not in MAPPING_TYPES:
        raise ApiError("Invalid mapping type.", status_code=400)
    oid = object_id(mapping_id, "mapping_id")
    existing = mappings().find_one({"_id": oid, "source_system": SOURCE_SYSTEM, "mapping_type": mapping_type})
    if not existing:
        raise ApiError("Integration mapping not found.", status_code=404)
    updates = {"updated_by": object_id(actor_id), "updated_at": now_utc()}
    if "fleetops_id" in payload:
        updates["fleetops_id"] = _mapping_target(existing["mapping_type"], payload["fleetops_id"])
        if mapping_type in {"manager", "agent"}:
            other_type = "agent" if mapping_type == "manager" else "manager"
            other_mapping = mappings().find_one({
                "source_system": SOURCE_SYSTEM, "mapping_type": other_type,
                "external_key": existing["external_key"], "active": True,
            })
            if other_mapping and other_mapping.get("fleetops_id") != updates["fleetops_id"]:
                raise ApiError(
                    "This SmartLiving identity is already linked to another FleetOps user in its other role.",
                    status_code=409,
                )
    if "active" in payload:
        updates["active"] = bool(payload["active"])
    if "external_display_name" in payload:
        updates["external_display_name"] = str(payload.get("external_display_name") or "").strip() or None
    if len(updates) == 2:
        raise ApiError("No editable mapping fields were provided.", status_code=400)
    old_values = dict(existing)
    mappings().update_one({"_id": oid}, {"$set": updates})
    existing.update(updates)
    write_audit("smartliving_mapping_updated", actor_id, "integration_mapping", oid, {"old": old_values, "new": updates})
    return serialize_integration_record(existing)


def _parse_source_datetime(value, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            raise ApiError(f"{field_name} must be a valid ISO-8601 timestamp.", status_code=400) from None
    else:
        raise ApiError(f"{field_name} must be a valid ISO-8601 timestamp.", status_code=400)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _identity(payload: dict) -> dict:
    system = _text(payload.get("source_system"), "source_system", 80).casefold()
    source_type = _text(payload.get("source_type"), "source_type", 80).casefold()
    record_id = _text(payload.get("source_record_id"), "source_record_id", 240)
    if system != SOURCE_SYSTEM:
        raise ApiError("This intake accepts SmartLiving records only.", status_code=400)
    synced = _parse_source_datetime(payload.get("source_synced_at"), "source_synced_at")
    identity = {"source_system": system, "source_type": source_type, "source_record_id": record_id, "source_synced_at": synced}
    if payload.get("source_date") is not None:
        identity["source_date"] = _parse_source_datetime(payload.get("source_date"), "source_date")
        identity["source_date_field"] = _text(payload.get("source_date_field"), "source_date_field", 80)
    return identity


def _source_query(identity: dict) -> dict:
    return {key: identity[key] for key in ("source_system", "source_type", "source_record_id")}


def _source_key(identity: dict) -> str:
    return "|".join(str(identity[key]) for key in ("source_system", "source_type", "source_record_id"))


def _mapping_reference(payload: dict, kind: str) -> tuple[str | None, dict]:
    reference = payload.get(f"{kind}_reference") or {}
    if not isinstance(reference, dict):
        return None, {}
    raw = str(reference.get("external_id") or reference.get("external_code") or "").strip()
    key = normalize_branch_key(raw) if kind == "branch" else raw.casefold()
    return key or None, {
        "external_id": str(reference.get("external_id") or "").strip() or None,
        "external_code": str(reference.get("external_code") or "").strip() or None,
        "external_display_name": str(reference.get("external_display_name") or "").strip() or None,
    }


def _resolve_mapping(payload: dict, kind: str):
    key, context = _mapping_reference(payload, kind)
    if not key:
        return None, context
    mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": kind, "external_key": key, "active": True})
    if mapping and not _mapping_target_is_current(kind, mapping):
        mapping = None
    if not mapping and kind == "branch":
        agent_key, _ = _mapping_reference(payload, "agent")
        branch_id = _confirmed_agent_branch_id(agent_key)
        if branch_id:
            return branch_id, context
    if not mapping and kind in {"agent", "manager"}:
        confirmed = _confirmed_source_users(kind).get(key)
        if confirmed:
            return confirmed["_id"], context
    return (mapping.get("fleetops_id") if mapping else None), context


def _retry_snapshot(payload: dict) -> dict:
    allowed = {
        "source_system", "source_type", "source_record_id", "source_synced_at",
        "branch_reference", "agent_reference", "reference_number", "customer_name",
        "manager_reference",
        "phone", "customer_phone", "alternative_phone", "delivery_address", "landmark",
        "latitude", "longitude", "requested_delivery_date", "notes", "product_lines",
    }
    return {key: payload.get(key) for key in allowed if key in payload}


def _exception(identity: dict, exception_type: str, message: str, payload: dict, actor_id: str, context=None) -> dict:
    if exception_type not in EXCEPTION_TYPES:
        raise ValueError("Unknown integration exception type")
    timestamp = now_utc(); open_key = _source_key(identity)
    document = {
        **_source_query(identity), "source_synced_at": identity["source_synced_at"],
        "open_key": open_key, "exception_type": exception_type, "message": message,
        "status": "open", "source_context": context or {}, "retry_snapshot": _retry_snapshot(payload),
        "attempt_count": 1, "created_by": object_id(actor_id), "updated_by": object_id(actor_id),
        "created_at": timestamp, "updated_at": timestamp,
    }
    try:
        result = exceptions().insert_one(document); document["_id"] = result.inserted_id
    except DuplicateKeyError:
        existing = exceptions().find_one({"open_key": open_key})
        exceptions().update_one({"_id": existing["_id"]}, {"$set": {"message": message, "source_context": context or {}, "retry_snapshot": document["retry_snapshot"], "updated_by": object_id(actor_id), "updated_at": timestamp}, "$inc": {"attempt_count": 1}})
        existing.update({"message": message, "source_context": context or {}, "retry_snapshot": document["retry_snapshot"], "updated_at": timestamp})
        existing["attempt_count"] = int(existing.get("attempt_count") or 1) + 1
        document = existing
    action = "smartliving_mapping_failed" if exception_type.startswith("unmapped_") else "smartliving_validation_failed"
    write_audit(action, actor_id, "integration_exception", document["_id"], {"new": {"exception_type": exception_type}}, {"source_key": open_key})
    return serialize_integration_record(document)


def _comparable(payload: dict, branch_id, agent_id, manager_id=None) -> dict:
    return {
        "branch_id": str(branch_id), "assigned_field_agent_id": str(agent_id),
        "manager_id": str(manager_id) if manager_id else None,
        "reference_number": str(payload.get("reference_number") or payload.get("source_record_id") or "").strip(),
        "customer_name": str(payload.get("customer_name") or "").strip(),
        "phone": str(payload.get("phone") or payload.get("customer_phone") or "").strip(),
        "delivery_address": str(payload.get("delivery_address") or "").strip(),
        "requested_delivery_date": str(payload.get("requested_delivery_date") or "").strip() or None,
        "product_lines": [
            {"product_name": str(item.get("product_name") or "").strip(), "quantity": item.get("quantity", item.get("quantity_requested"))}
            for item in (payload.get("product_lines") or []) if isinstance(item, dict)
        ],
    }


def _existing_comparable(document: dict) -> dict:
    return {
        "branch_id": str(document.get("branch_id")), "assigned_field_agent_id": str(document.get("assigned_field_agent_id")),
        "manager_id": str(document.get("manager_id")) if document.get("manager_id") else None,
        "reference_number": document.get("reference_number"), "customer_name": document.get("customer_name"),
        "phone": document.get("phone") or document.get("customer_phone"), "delivery_address": document.get("delivery_address"),
        "requested_delivery_date": document.get("requested_delivery_date"),
        "product_lines": [{"product_name": item.get("product_name"), "quantity": item.get("quantity", item.get("quantity_requested"))} for item in document.get("product_lines", [])],
    }


def intake_delivery(payload: dict, actor_id: str) -> dict:
    _actor(actor_id)
    try:
        identity = _identity(payload)
    except ApiError as error:
        system = str(payload.get("source_system") or "").strip().casefold()
        source_type = str(payload.get("source_type") or "").strip().casefold()
        record_id = str(payload.get("source_record_id") or "").strip()
        # A stable identity is required before an exception can itself be
        # deduplicated. Identity-less requests remain ordinary request errors.
        if system != SOURCE_SYSTEM or not source_type or not record_id:
            raise
        fallback_identity = {
            "source_system": system, "source_type": source_type,
            "source_record_id": record_id, "source_synced_at": now_utc(),
        }
        exception = _exception(fallback_identity, "invalid_source_data", str(error), payload, actor_id, {"provided_source_synced_at": payload.get("source_synced_at")})
        return {"outcome": "validation_failed", "delivery": None, "exception": exception}
    existing = orders().find_one(_source_query(identity))
    branch_id, branch_context = _resolve_mapping(payload, "branch")
    if not branch_id:
        exception = _exception(identity, "unmapped_branch", "No active FleetOps Branch mapping exists.", payload, actor_id, {"branch": branch_context})
        return {"outcome": "mapping_failed", "delivery": None, "exception": exception}
    agent_id, agent_context = _resolve_mapping(payload, "agent")
    if not agent_id:
        exception = _exception(identity, "unmapped_agent", "No active FleetOps Field Agent mapping exists.", payload, actor_id, {"agent": agent_context, "fleetops_branch_id": branch_id})
        return {"outcome": "mapping_failed", "delivery": None, "exception": exception}
    try:
        assert_user_in_branch(agent_id, branch_id, AGENT_ROLE_CODES)
    except ApiError as error:
        exception = _exception(identity, "invalid_source_data", str(error), payload, actor_id, {"fleetops_branch_id": branch_id, "fleetops_agent_id": agent_id})
        return {"outcome": "validation_failed", "delivery": None, "exception": exception}
    manager_id, manager_context = _resolve_mapping(payload, "manager")
    agent_user = get_collection("users").find_one({"_id": agent_id}, {"manager_id": 1})
    assigned_manager_id = (agent_user or {}).get("manager_id")
    if manager_id and assigned_manager_id and manager_id != assigned_manager_id:
        exception = _exception(identity, "invalid_source_data", "The source manager conflicts with the Field Agent's confirmed manager.", payload, actor_id, {"fleetops_branch_id": branch_id, "fleetops_agent_id": agent_id, "source_manager": manager_context})
        return {"outcome": "validation_failed", "delivery": None, "exception": exception}
    manager_id = manager_id or assigned_manager_id
    if manager_id:
        try:
            assert_user_in_branch(manager_id, branch_id, {"branch_manager"})
        except ApiError as error:
            exception = _exception(identity, "invalid_source_data", str(error), payload, actor_id, {"fleetops_branch_id": branch_id, "fleetops_agent_id": agent_id, "fleetops_manager_id": manager_id})
            return {"outcome": "validation_failed", "delivery": None, "exception": exception}
    comparable = _comparable(payload, branch_id, agent_id, manager_id)
    if existing:
        if _existing_comparable(existing) == comparable:
            write_audit("smartliving_duplicate_skipped", actor_id, "delivery_order", existing["_id"], {}, {"source_key": _source_key(identity), "branch_id": str(branch_id)})
            return {"outcome": "duplicate_skipped", "delivery": serialize_integration_record(existing), "exception": None}
        exception = _exception(identity, "conflicting_source_record", "The source identity already belongs to a different FleetOps delivery payload.", payload, actor_id, {"delivery_order_id": existing["_id"], "fleetops_branch_id": branch_id})
        return {"outcome": "conflict", "delivery": None, "exception": exception}
    canonical = {
        **payload, "branch_id": str(branch_id), "sales_agent_id": str(agent_id),
        "manager_id": str(manager_id) if manager_id else None,
        "reference_number": comparable["reference_number"], "status": "WAITING_SCHEDULING",
    }
    try:
        delivery = create_certified_order(canonical, actor_id, external_identity=identity)
    except ApiError as error:
        if error.status_code == 409:
            raced = orders().find_one(_source_query(identity))
            if raced:
                write_audit("smartliving_duplicate_skipped", actor_id, "delivery_order", raced["_id"], {}, {"source_key": _source_key(identity), "branch_id": str(branch_id)})
                return {"outcome": "duplicate_skipped", "delivery": serialize_integration_record(raced), "exception": None}
        message = str(error).lower()
        exception_type = "missing_required_data" if "required" in message or "at least one" in message else "invalid_source_data"
        exception = _exception(identity, exception_type, str(error), payload, actor_id, {"fleetops_branch_id": branch_id, "fleetops_agent_id": agent_id})
        return {"outcome": "validation_failed", "delivery": None, "exception": exception}
    write_audit("smartliving_imported", actor_id, "delivery_order", delivery["id"], {"new": {"status": "WAITING_SCHEDULING"}}, {"source_key": _source_key(identity), "branch_id": str(branch_id)})
    return {"outcome": "imported", "delivery": delivery, "exception": None}


def list_exceptions(actor_id: str, status=None) -> dict:
    _actor(actor_id); query = {"source_system": SOURCE_SYSTEM}
    if status:
        query["status"] = status
    rows = exceptions().find(query).sort("created_at", DESCENDING).limit(200)
    return {"exceptions": [serialize_integration_record(row) for row in rows]}


def resolve_exception(exception_id: str, notes: str, actor_id: str) -> dict:
    _actor(actor_id); oid = object_id(exception_id, "exception_id")
    document = exceptions().find_one({"_id": oid, "source_system": SOURCE_SYSTEM})
    if not document:
        raise ApiError("Integration exception not found.", status_code=404)
    if document.get("status") == "resolved":
        return serialize_integration_record(document)
    timestamp = now_utc(); updates = {"status": "resolved", "resolution_notes": str(notes or "").strip() or None, "resolved_at": timestamp, "resolved_by": object_id(actor_id), "updated_by": object_id(actor_id), "updated_at": timestamp}
    exceptions().update_one({"_id": oid}, {"$set": updates, "$unset": {"open_key": ""}}); document.update(updates); document.pop("open_key", None)
    write_audit("smartliving_exception_resolved", actor_id, "integration_exception", oid, {"new": updates}, {"source_key": _source_key(document)})
    return serialize_integration_record(document)


def retry_exception(exception_id: str, actor_id: str) -> dict:
    _actor(actor_id); oid = object_id(exception_id, "exception_id")
    document = exceptions().find_one({"_id": oid, "source_system": SOURCE_SYSTEM})
    if not document:
        raise ApiError("Integration exception not found.", status_code=404)
    write_audit("smartliving_exception_retried", actor_id, "integration_exception", oid, {}, {"source_key": _source_key(document)})
    result = intake_delivery(document.get("retry_snapshot") or {}, actor_id)
    if result["outcome"] in {"imported", "duplicate_skipped"}:
        resolve_exception(exception_id, f"Retry completed: {result['outcome']}", actor_id)
    return result


def integration_status(actor_id: str) -> dict:
    _actor(actor_id)
    configured = bool(current_app.config.get("SMARTLIVING_API_BASE_URL") and current_app.config.get("SMARTLIVING_API_KEY"))
    connection_collection = connections(); mapping_collection = mappings(); exception_collection = exceptions()
    with ThreadPoolExecutor(max_workers=5) as pool:
        latest_future = pool.submit(connection_collection.find_one, {"source_system": SOURCE_SYSTEM})
        branch_count_future = pool.submit(mapping_collection.count_documents, {"source_system": SOURCE_SYSTEM, "mapping_type": "branch", "active": True})
        agent_count_future = pool.submit(mapping_collection.count_documents, {"source_system": SOURCE_SYSTEM, "mapping_type": "agent", "active": True})
        manager_count_future = pool.submit(mapping_collection.count_documents, {"source_system": SOURCE_SYSTEM, "mapping_type": "manager", "active": True})
        exception_count_future = pool.submit(exception_collection.count_documents, {"source_system": SOURCE_SYSTEM, "status": "open"})
        latest = latest_future.result() or {}
        branch_mapping_count = branch_count_future.result()
        agent_mapping_count = agent_count_future.result()
        manager_mapping_count = manager_count_future.result()
        open_exception_count = exception_count_future.result()
    return {
        "source_system": SOURCE_SYSTEM,
        "configured": configured,
        "connection_status": latest.get("connection_status") if configured else "not_configured",
        "endpoints": latest.get("endpoints") or [],
        "last_checked": latest.get("last_checked"),
        "api_calls_enabled": False,
        "branch_mapping_count": branch_mapping_count,
        "agent_mapping_count": agent_mapping_count,
        "manager_mapping_count": manager_mapping_count,
        "open_exception_count": open_exception_count,
    }


def _sanitized_shape(value, depth=0):
    """Retain field names and types only; never persist external record values."""
    if depth > 5:
        return "<nested>"
    if isinstance(value, dict):
        return {str(key): _sanitized_shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitized_shape(item, depth + 1) for item in value[:2]]
    if value is None:
        return None
    if isinstance(value, bool):
        return "<boolean>"
    if isinstance(value, (int, float)):
        return "<number>"
    return "<string>"


def _probe_endpoint(base_url: str, api_key: str, endpoint: str) -> dict:
    url = f"{base_url}/{endpoint}?{urlencode({'page': 1, 'limit': 5})}"
    request = Request(url, method="GET", headers={"X-API-Key": api_key, "Accept": "application/json"})
    response = None
    try:
        response = urlopen(request, timeout=30)
    except HTTPError as error:
        response = error
    except (URLError, TimeoutError, OSError) as error:
        return {
            "endpoint": f"/{endpoint}", "reachable": False, "http_status": None,
            "record_count": None, "returned_count": None, "json": False,
            "error": type(getattr(error, "reason", error)).__name__, "sample_structure": [],
        }

    raw = response.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
        is_json = True
    except (TypeError, ValueError):
        payload = None
        is_json = False
    rows = payload.get("rows") if isinstance(payload, dict) and isinstance(payload.get("rows"), list) else []
    pagination = payload.get("pagination") if isinstance(payload, dict) and isinstance(payload.get("pagination"), dict) else {}
    return {
        "endpoint": f"/{endpoint}", "reachable": True, "http_status": int(response.status),
        "record_count": pagination.get("total"), "returned_count": len(rows), "json": is_json,
        "error": None, "sample_structure": [_sanitized_shape(row) for row in rows[:2]],
    }


def _source_configuration() -> tuple[str, str]:
    base_url = str(current_app.config.get("SMARTLIVING_API_BASE_URL") or "").strip().rstrip("/")
    api_key = str(current_app.config.get("SMARTLIVING_API_KEY") or "").strip()
    parsed = urlparse(base_url)
    if not base_url or not api_key or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ApiError("SmartLiving connection is not configured.", status_code=409)
    return base_url, api_key


def _fetch_source_page(base_url: str, api_key: str, endpoint: str, page: int, limit: int = SMARTLIVING_PAGE_LIMIT, stats: dict | None = None) -> dict:
    limit = SMARTLIVING_PAGE_LIMIT
    url = f"{base_url}/{endpoint}?{urlencode({'page': page, 'limit': limit})}"
    payload = None
    for attempt in range(3):
        if stats is not None:
            with stats["lock"]:
                stats["api_calls"] += 1
                stats["retries"] += 1 if attempt else 0
        request = Request(url, method="GET", headers={"X-API-Key": api_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            break
        except HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise ApiError(f"SmartLiving {endpoint} returned HTTP {error.code}.", status_code=502) from None
            if attempt == 2:
                raise ApiError(f"SmartLiving {endpoint} returned HTTP {error.code}.", status_code=502) from None
        except (URLError, TimeoutError, OSError, ValueError):
            if attempt == 2:
                raise ApiError(f"SmartLiving {endpoint} could not be read.", status_code=502) from None
        sleep(0.25 * (attempt + 1))
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ApiError(f"SmartLiving {endpoint} returned an invalid JSON structure.", status_code=502)
    return payload


def _page_date_window(rows: list[dict], endpoint: str) -> tuple[datetime, datetime] | None:
    values = []
    for row in rows:
        value = _source_datetime(row, endpoint)
        if value is None:
            return None
        values.append(value)
    if not values or any(values[index] < values[index + 1] for index in range(len(values) - 1)):
        return None
    return values[0], values[-1]


def _fetch_endpoint_for_period(base_url: str, api_key: str, endpoint: str, from_date: date | None) -> tuple[list[dict], dict]:
    stats = {"api_calls": 0, "retries": 0, "lock": Lock()}
    first = _fetch_source_page(base_url, api_key, endpoint, 1, stats=stats)
    rows = list(first.get("rows") or [])
    pages_fetched = 1
    total_pages = max(int((first.get("pagination") or {}).get("total_pages") or 1), 1)
    window = _page_date_window(rows, endpoint)
    cutoff_reached = bool(from_date and window and window[1].date() < from_date)

    # SmartLiving returns both approved endpoints newest-first. Once a complete,
    # internally ordered page is older than the inclusive lower bound, later
    # pages cannot match. If ordering/date completeness is not demonstrable,
    # fall back to all pages to preserve filtering accuracy.
    if not cutoff_reached and total_pages > 1:
        remaining = range(2, total_pages + 1)
        if from_date:
            previous_oldest = window[1] if window else None
            for page_number in remaining:
                page_payload = _fetch_source_page(base_url, api_key, endpoint, page_number, stats=stats)
                page_rows = list(page_payload.get("rows") or [])
                rows.extend(page_rows); pages_fetched += 1
                page_window = _page_date_window(page_rows, endpoint)
                globally_ordered = bool(page_window and previous_oldest and page_window[0] <= previous_oldest)
                if not globally_ordered:
                    # Continue through the dataset; the local date filter remains authoritative.
                    previous_oldest = None
                    continue
                previous_oldest = page_window[1]
                if previous_oldest.date() < from_date:
                    cutoff_reached = True
                    break
        else:
            with ThreadPoolExecutor(max_workers=min(3, total_pages - 1)) as pool:
                pages = pool.map(lambda page: _fetch_source_page(base_url, api_key, endpoint, page, stats=stats), remaining)
                for page_payload in pages:
                    rows.extend(page_payload.get("rows") or []); pages_fetched += 1
    return rows, {
        "api_calls": stats["api_calls"], "retries": stats["retries"],
        "pages_fetched": pages_fetched, "total_pages": total_pages,
        "records_fetched": len(rows), "cutoff_reached": cutoff_reached,
    }


def fetch_source_records(endpoints=None, *, from_date: date | None = None, with_metrics=False):
    """Read only requested approved endpoints. This function never invokes intake."""
    started = perf_counter()
    base_url, api_key = _source_configuration()
    result = {}
    selected = tuple(endpoints or SOURCE_ENDPOINTS)
    if any(endpoint not in SOURCE_ENDPOINTS for endpoint in selected):
        raise ApiError("Invalid SmartLiving source endpoint.", status_code=400)
    endpoint_metrics = {}
    if len(selected) > 1:
        # The two approved sources are independent. Fetch them concurrently while
        # keeping each source's pagination bounded and rate-limit retries intact.
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            fetched = dict(zip(selected, pool.map(lambda endpoint: _fetch_endpoint_for_period(base_url, api_key, endpoint, from_date), selected)))
        for endpoint, (rows, metrics) in fetched.items():
            result[endpoint] = rows; endpoint_metrics[endpoint] = metrics
    else:
        for endpoint in selected:
            rows, metrics = _fetch_endpoint_for_period(base_url, api_key, endpoint, from_date)
            result[endpoint] = rows; endpoint_metrics[endpoint] = metrics
    duration_ms = round((perf_counter() - started) * 1000)
    metrics = {
        "api_calls": sum(item["api_calls"] for item in endpoint_metrics.values()),
        "pages_fetched": sum(item["pages_fetched"] for item in endpoint_metrics.values()),
        "records_fetched": sum(item["records_fetched"] for item in endpoint_metrics.values()),
        "retries": sum(item["retries"] for item in endpoint_metrics.values()),
        "duration_ms": duration_ms, "endpoints": endpoint_metrics,
    }
    _log_info(
        "[SmartLiving Preview] fetch endpoints=%s api_calls=%s pages=%s records=%s retries=%s duration_ms=%s",
        ",".join(selected), metrics["api_calls"], metrics["pages_fetched"], metrics["records_fetched"], metrics["retries"], duration_ms,
    )
    return (result, metrics) if with_metrics else result


def _nested(document: dict, path: str):
    value = document
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _selected_purchase(document: dict) -> dict:
    purchases = _nested(document, "customer.purchases") or []
    try:
        index = int(_nested(document, "payload.selected_product_index"))
    except (TypeError, ValueError):
        return {}
    return purchases[index] if 0 <= index < len(purchases) and isinstance(purchases[index], dict) else {}


def _external_agent(document: dict, endpoint: str) -> tuple[str | None, str | None]:
    normalized = document.get("_normalized") or {}
    if normalized:
        return normalized.get("agent_id"), normalized.get("agent_name")
    if endpoint == "completed-cards":
        return str(document.get("agent_id") or "").strip() or None, str(document.get("agent_name") or "").strip() or None
    purchase = _selected_purchase(document)
    agent_id = str(purchase.get("agent_id") or _nested(document, "customer.agent_id") or "").strip() or None
    return agent_id, None


def _external_branch(document: dict) -> str | None:
    normalized = document.get("_normalized") or {}
    return normalized.get("branch_name") or str(document.get("agent_branch") or document.get("manager_branch") or "").strip() or None


def _unique_values(rows: list[dict], key_getter, value_getter) -> dict[str, str]:
    values = defaultdict(set)
    for row in rows:
        key = str(key_getter(row) or "").strip()
        value = str(value_getter(row) or "").strip()
        if key and value:
            values[key].add(value)
    return {key: next(iter(options)) for key, options in values.items() if len(options) == 1}


def _source_manager_name(row: dict, purchase: dict, customer: dict) -> str:
    """Read only explicit SmartLiving person-name fields; branch labels and IDs are never names."""
    manager_obj = row.get("manager") or customer.get("manager") or purchase.get("manager") or {}
    if not isinstance(manager_obj, dict):
        manager_obj = {}
    values = (
        row.get("manager_name"), row.get("manager_full_name"), row.get("manager_display_name"),
        purchase.get("manager_name"), purchase.get("manager_full_name"), purchase.get("manager_display_name"),
        customer.get("manager_name"), customer.get("manager_full_name"), customer.get("manager_display_name"),
        manager_obj.get("full_name"), manager_obj.get("name"), manager_obj.get("display_name"),
    )
    return next((str(value).strip() for value in values if str(value or "").strip()), "")


def resolve_agent_manager_branches(source_rows: dict[str, list[dict]]) -> dict[str, dict]:
    """Resolve current source evidence by stable ID; older observations never outvote newer ones."""
    agent_ids = {}; manager_ids = {}
    agent_names = {}; agent_managers = {}; agent_direct_branches = {}
    manager_names = {}; manager_branches = {}

    def observe(store: dict, key: str, value, observed_at: datetime | None):
        text = str(value or "").strip()
        if not key or not text:
            return
        stamp = observed_at.timestamp() if observed_at else float("-inf")
        current = store.get(key)
        if current is None or stamp > current[0]:
            store[key] = (stamp, {text})
        elif stamp == current[0]:
            current[1].add(text)

    def values(store: dict, key: str | None) -> set[str]:
        return set((store.get(key) or (None, set()))[1]) if key else set()

    for endpoint, rows in source_rows.items():
        for row in rows:
            customer = row.get("customer") or {}
            purchase = _selected_purchase(row) if endpoint == "closed-cards" else {}
            if endpoint == "completed-cards":
                agent_id = str(row.get("agent_id") or "").strip()
                agent_name = str(row.get("agent_name") or "").strip()
                direct_branch = str(row.get("agent_branch") or "").strip()
            else:
                agent_id = str(purchase.get("agent_id") or customer.get("agent_id") or "").strip()
                agent_name = ""
                direct_branch = ""
            manager_id = str(row.get("manager_id") or purchase.get("manager_id") or customer.get("manager_id") or "").strip()
            manager_name = _source_manager_name(row, purchase, customer)
            if not agent_id:
                continue
            observed_at = _source_datetime(row, endpoint)
            agent_key = agent_id.casefold(); agent_ids.setdefault(agent_key, agent_id)
            observe(agent_names, agent_key, agent_name, observed_at)
            observe(agent_direct_branches, agent_key, direct_branch, observed_at)
            observe(agent_managers, agent_key, manager_id.casefold(), observed_at)
            if manager_id:
                manager_key = manager_id.casefold(); manager_ids.setdefault(manager_key, manager_id)
                observe(manager_names, manager_key, manager_name, observed_at)
                manager_branch = str(row.get("manager_branch") or (purchase if endpoint == "closed-cards" else {}).get("manager_branch") or customer.get("manager_branch") or "").strip()
                observe(manager_branches, manager_key, manager_branch, observed_at)

    # A manager is a SmartLiving user ID. An exact appearance of that same ID
    # as agent_id with one name is authoritative identity data, not name guessing.
    for manager_key in manager_ids:
        if not values(manager_names, manager_key) and values(agent_names, manager_key):
            manager_names[manager_key] = agent_names[manager_key]

    relationships = {}
    for agent_key, agent_id in agent_ids.items():
        managers = values(agent_managers, agent_key)
        direct_branches = values(agent_direct_branches, agent_key)
        names = values(agent_names, agent_key)
        relationship = {
            "status": "needs_review", "reason": None, "resolution_source": None,
            "agent_id": agent_id,
            "agent_display_name": next(iter(names)) if len(names) == 1 else None,
            "manager_id": None, "manager_display_name": None,
            "direct_branch": None, "manager_branch": None,
            "direct_branch_options": sorted(direct_branches), "manager_branch_options": [],
            "external_branch": None, "fleetops_branch_id": None, "fleetops_branch_name": None,
        }
        if len(managers) > 1:
            relationship.update(status="conflicting", reason="conflicting_manager")
            relationships[agent_key] = relationship; continue
        manager_key = next(iter(managers)) if managers else None
        relationship["manager_id"] = manager_ids.get(manager_key) if manager_key else None
        manager_name_options = values(manager_names, manager_key)
        relationship["manager_display_name"] = next(iter(manager_name_options)) if manager_name_options else None
        manager_branch_options = values(manager_branches, manager_key)
        relationship["manager_branch_options"] = sorted(manager_branch_options)
        manager_branch = sorted(manager_branch_options, key=lambda value: (len(value), value.casefold()))[0] if manager_branch_options else None
        direct_branch_keys = {canonical_branch_alias_key(value) for value in direct_branches if canonical_branch_alias_key(value)}
        if len(direct_branch_keys) > 1:
            relationship.update(status="conflicting", reason="conflicting_direct_branch")
            relationships[agent_key] = relationship; continue
        direct_branch = sorted(direct_branches, key=lambda value: (len(value), value.casefold()))[0] if direct_branches else None
        relationship.update(direct_branch=direct_branch, manager_branch=manager_branch)
        branch_name = direct_branch or manager_branch
        relationship.update(
            external_branch=branch_name, fleetops_branch_name=branch_name,
            resolution_source="direct_branch" if direct_branch else ("manager_branch" if manager_branch else None),
        )
        missing = []
        if len(names) != 1: missing.append("missing_agent_name" if not names else "conflicting_agent_name")
        if not manager_key: missing.append("missing_manager_id")
        if any(item.startswith("conflicting_") for item in missing):
            relationship.update(status="conflicting", reason=next(item for item in missing if item.startswith("conflicting_")))
        elif missing:
            relationship.update(status="needs_review", reason=missing[0])
        else:
            relationship.update(status="resolved", reason=None)
        relationships[agent_key] = relationship
    return relationships


def _discovered_agent_context() -> tuple[dict[str, str], dict[str, str]]:
    names = {}; branches = {}
    for row in discoveries().find({
        "source_system": SOURCE_SYSTEM, "discovery_type": "agent", "currently_observed": {"$ne": False},
    }, {"external_id": 1, "external_display_name": 1, "branch_name": 1}):
        agent_id = str(row.get("external_id") or "").strip()
        display_name = str(row.get("external_display_name") or "").strip()
        branch_name = str(row.get("branch_name") or "").strip()
        if agent_id and display_name and display_name.casefold() != agent_id.casefold():
            names[agent_id] = display_name
        if agent_id and branch_name:
            branches[agent_id] = branch_name
    return names, branches


def _discovered_relationship_context() -> dict[str, dict]:
    return {
        str(row.get("external_id") or "").strip().casefold(): row.get("relationship")
        for row in discoveries().find({
            "source_system": SOURCE_SYSTEM, "discovery_type": "agent", "currently_observed": {"$ne": False},
        }, {"external_id": 1, "relationship": 1})
        if str(row.get("external_id") or "").strip() and isinstance(row.get("relationship"), dict)
    }


def _normalize_source_rows(source_rows: dict[str, list[dict]], *, include_discovered=True, relationships=None) -> dict[str, list[dict]]:
    """Normalize verified endpoint differences while retaining every original source field and ID."""
    completed = source_rows.get("completed-cards") or []
    agent_names = _unique_values(completed, lambda row: row.get("agent_id"), lambda row: row.get("agent_name"))
    agent_branches = _unique_values(completed, lambda row: row.get("agent_id"), lambda row: row.get("agent_branch"))
    manager_branches = _unique_values(completed, lambda row: row.get("manager_id"), lambda row: row.get("manager_branch"))
    discovered_names, discovered_branches = _discovered_agent_context() if include_discovered else ({}, {})
    discovered_relationships = _discovered_relationship_context() if include_discovered else {}
    relationships = relationships if relationships is not None else resolve_agent_manager_branches(source_rows)
    normalized = {}
    for endpoint, rows in source_rows.items():
        normalized[endpoint] = []
        for source_row in rows:
            row = dict(source_row)
            customer = row.get("customer") or {}
            if endpoint == "completed-cards":
                agent_id = str(row.get("agent_id") or "").strip() or None
                agent_name = str(row.get("agent_name") or "").strip() or (discovered_names.get(agent_id) if agent_id else None)
                branch_name = str(row.get("agent_branch") or row.get("manager_branch") or "").strip() or (discovered_branches.get(agent_id) if agent_id else None)
            else:
                purchase = _selected_purchase(row)
                agent_id = str(purchase.get("agent_id") or customer.get("agent_id") or "").strip() or None
                agent_name = (agent_names.get(agent_id) or discovered_names.get(agent_id)) if agent_id else None
                branch_name = (agent_branches.get(agent_id) or discovered_branches.get(agent_id)) if agent_id else None
                manager_id = str(customer.get("manager_id") or "").strip()
                branch_name = branch_name or manager_branches.get(manager_id)
            customer_id = str(row.get("customer_id") or customer.get("_id") or "").strip() or None
            relationship = relationships.get(agent_id.casefold()) if agent_id else None
            cached_relationship = discovered_relationships.get(agent_id.casefold()) if agent_id else None
            if relationship and cached_relationship and relationship.get("status") != "conflicting" and relationship.get("manager_id") == cached_relationship.get("manager_id"):
                relationship = dict(relationship)
                relationship["manager_display_name"] = relationship.get("manager_display_name") or cached_relationship.get("manager_display_name")
                relationship["external_branch"] = relationship.get("external_branch") or cached_relationship.get("external_branch")
                relationship["fleetops_branch_name"] = relationship.get("external_branch")
                if agent_name and relationship.get("manager_id") and relationship.get("manager_display_name") and relationship.get("external_branch"):
                    relationship.update(status="resolved", reason=None)
            manager_id = (relationship or {}).get("manager_id") or str(row.get("manager_id") or customer.get("manager_id") or "").strip() or None
            branch_name = branch_name or (relationship or {}).get("external_branch")
            customer_name = str(row.get("customer_name") or customer.get("name") or "").strip() or None
            customer_phone = str(row.get("customer_phone") or customer.get("phone_number") or "").strip() or None
            customer_location = str(customer.get("location") or "").strip() or None
            customer_occupation = str(customer.get("occupation") or "").strip() or None
            row["_normalized"] = {
                "customer_name": customer_name, "customer_phone": customer_phone,
                "customer_location": customer_location, "customer_occupation": customer_occupation,
                "agent_id": agent_id, "agent_name": agent_name, "branch_name": branch_name,
                "manager_id": manager_id, "manager_name": (relationship or {}).get("manager_display_name"),
                "entities": {
                    "customer": {"id": customer_id, "display_name": customer_name, "phone": customer_phone, "location": customer_location, "occupation": customer_occupation},
                    "agent": {"id": agent_id, "display_name": agent_name},
                    "branch": {"id": normalize_branch_key(branch_name) if branch_name else None, "display_name": branch_name},
                    "manager": {"id": manager_id, "display_name": (relationship or {}).get("manager_display_name")},
                },
                "relationship": relationship,
            }
            normalized[endpoint].append(row)
    return normalized


def discover_source_values(actor_id: str, *, source_rows: dict | None = None, mark_missing_stale: bool | None = None) -> dict:
    _actor(actor_id)
    full_source_scan = source_rows is None
    if source_rows is None:
        source_rows = fetch_source_records()
    if mark_missing_stale is None:
        mark_missing_stale = full_source_scan
    relationships = resolve_agent_manager_branches(source_rows)
    source_rows = _normalize_source_rows(source_rows, include_discovered=False, relationships=relationships)
    timestamp = now_utc(); branch_counts = Counter(); branch_labels = defaultdict(Counter); branch_endpoints = defaultdict(set)
    agent_counts = Counter(); agent_names = defaultdict(Counter); agent_branches = defaultdict(Counter); agent_endpoints = defaultdict(set)
    manager_counts = Counter(); manager_names = defaultdict(set); manager_emails = defaultdict(set)
    manager_phones = defaultdict(set); manager_branches = defaultdict(set); manager_endpoints = defaultdict(set)
    for endpoint, rows in source_rows.items():
        for row in rows:
            for branch in (_external_branch(row),):
                branch = str(branch or "").strip()
                if branch:
                    branch_key = normalize_branch_key(branch)
                    branch_counts[branch_key] += 1; branch_labels[branch_key][branch] += 1; branch_endpoints[branch_key].add(endpoint)
            agent_id, agent_name = _external_agent(row, endpoint)
            if agent_id:
                agent_counts[agent_id] += 1; agent_endpoints[agent_id].add(endpoint)
                current_relationship = relationships.get(agent_id.casefold()) or {}
                agent_name = current_relationship.get("agent_display_name") or agent_name
                if agent_name:
                    agent_names[agent_id][agent_name] += 1
                branch_name = current_relationship.get("direct_branch") or current_relationship.get("external_branch")
                if branch_name:
                    agent_branches[agent_id][branch_name] += 1
            normalized = row.get("_normalized") or {}
            relationship = normalized.get("relationship") or {}
            manager_id = str(relationship.get("manager_id") or normalized.get("manager_id") or "").strip()
            if manager_id:
                manager_counts[manager_id] += 1; manager_endpoints[manager_id].add(endpoint)
                manager_name = str(relationship.get("manager_display_name") or normalized.get("manager_name") or "").strip()
                if manager_name: manager_names[manager_id].add(manager_name)
                branch_name = str(relationship.get("external_branch") or normalized.get("branch_name") or "").strip()
                if branch_name: manager_branches[manager_id].add(branch_name)
                customer = row.get("customer") or {}; purchase = _selected_purchase(row)
                manager_obj = row.get("manager") or customer.get("manager") or purchase.get("manager") or {}
                email = str(row.get("manager_email") or customer.get("manager_email") or purchase.get("manager_email") or manager_obj.get("email") or "").strip()
                phone = str(row.get("manager_phone") or row.get("manager_phone_number") or customer.get("manager_phone") or purchase.get("manager_phone") or manager_obj.get("phone") or manager_obj.get("phone_number") or "").strip()
                if email: manager_emails[manager_id].add(email)
                if phone: manager_phones[manager_id].add(phone)
    scan_marker = str(ObjectId())
    discovery_writes = []
    for branch_key, count in branch_counts.items():
        branch = branch_labels[branch_key].most_common(1)[0][0]
        document = {
            "source_system": SOURCE_SYSTEM, "discovery_type": "branch", "external_key": normalize_branch_key(branch),
            "external_id": None, "external_code": branch, "external_display_name": branch,
            "seen_count": count, "source_endpoints": sorted(branch_endpoints[branch_key]),
            "last_seen_at": timestamp, "scan_marker": scan_marker,
        }
        discovery_writes.append(UpdateOne(
            {"source_system": SOURCE_SYSTEM, "discovery_type": "branch", "external_key": normalize_branch_key(branch)},
            {"$set": document, "$setOnInsert": {"created_at": timestamp}}, upsert=True,
        ))
    for agent_id, count in agent_counts.items():
        preferred_name = next(iter(agent_names[agent_id])) if len(agent_names[agent_id]) == 1 else None
        branch_options = agent_branches[agent_id]
        branch_keys = {normalize_branch_key(value) for value in branch_options}
        branch_name = branch_options.most_common(1)[0][0] if len(branch_keys) == 1 and branch_options else None
        document = {
            "source_system": SOURCE_SYSTEM, "discovery_type": "agent", "external_key": agent_id.casefold(),
            "external_id": agent_id, "external_code": None, "external_display_name": preferred_name,
            "display_name_status": "resolved" if preferred_name else "unavailable", "branch_name": branch_name,
            "display_name_aliases": sorted(agent_names[agent_id]), "seen_count": count,
            "source_endpoints": sorted(agent_endpoints[agent_id]), "last_seen_at": timestamp, "scan_marker": scan_marker,
            "relationship": relationships.get(agent_id.casefold()),
        }
        discovery_writes.append(UpdateOne(
            {"source_system": SOURCE_SYSTEM, "discovery_type": "agent", "external_key": agent_id.casefold()},
            {"$set": document, "$setOnInsert": {"created_at": timestamp}}, upsert=True,
        ))
    for manager_id, count in manager_counts.items():
        names = manager_names[manager_id]; emails = manager_emails[manager_id]
        phones = manager_phones[manager_id]; branches = manager_branches[manager_id]
        conflicts = []
        if len(names) > 1: conflicts.append("CONFLICTING_MANAGER_NAME")
        if len(emails) > 1: conflicts.append("CONFLICTING_MANAGER_EMAIL")
        if len(phones) > 1: conflicts.append("CONFLICTING_MANAGER_PHONE")
        normalized_branch_keys = {normalize_branch_key(value) for value in branches if normalize_branch_key(value)}
        if len(normalized_branch_keys) > 1: conflicts.append("BRANCH_CONFLICT")
        if not names: conflicts.append("MISSING_NAME")
        if not branches: conflicts.append("UNRESOLVED_BRANCH")
        document = {
            "source_system": SOURCE_SYSTEM, "discovery_type": "manager", "external_key": manager_id.casefold(),
            "external_id": manager_id, "external_code": None,
            "external_display_name": next(iter(names)) if len(names) == 1 else None,
            "email": next(iter(emails)) if len(emails) == 1 else None,
            "phone": next(iter(phones)) if len(phones) == 1 else None,
            "branch_name": sorted(branches, key=lambda value: (len(value), value.casefold()))[0] if len(normalized_branch_keys) == 1 else None,
            "branch_keys": sorted(normalized_branch_keys),
            "review_codes": conflicts, "seen_count": count,
            "source_endpoints": sorted(manager_endpoints[manager_id]), "last_seen_at": timestamp,
            "scan_marker": scan_marker,
        }
        discovery_writes.append(UpdateOne(
            {"source_system": SOURCE_SYSTEM, "discovery_type": "manager", "external_key": manager_id.casefold()},
            {"$set": document, "$setOnInsert": {"created_at": timestamp}}, upsert=True,
        ))
    if discovery_writes:
        discoveries().bulk_write(discovery_writes, ordered=False)
    if mark_missing_stale:
        discoveries().update_many(
            {"source_system": SOURCE_SYSTEM, "scan_marker": {"$ne": scan_marker}},
            {"$set": {"currently_observed": False, "updated_at": timestamp}},
        )
    discoveries().update_many(
        {"source_system": SOURCE_SYSTEM, "scan_marker": scan_marker},
        {"$set": {"currently_observed": True, "updated_at": timestamp}},
    )
    return {
        "branches": branch_counts.total(), "unique_branches": len(branch_counts),
        "agents": agent_counts.total(), "unique_agents": len(agent_counts),
        "managers": manager_counts.total(), "unique_managers": len(manager_counts),
        "relationship_counts": {
            "resolved": sum(item.get("status") == "resolved" for item in relationships.values()),
            "unresolved": sum(item.get("status") == "needs_review" for item in relationships.values()),
            "conflicting": sum(item.get("status") == "conflicting" for item in relationships.values()),
        },
        "source_counts": {endpoint.replace("-cards", ""): len(rows) for endpoint, rows in source_rows.items()},
        "last_scanned": timestamp,
    }


def list_discoveries(actor_id: str) -> dict:
    _actor(actor_id)
    result = {"branches": [], "managers": [], "agents": []}
    for row in discoveries().find({"source_system": SOURCE_SYSTEM, "currently_observed": {"$ne": False}}).sort([("discovery_type", ASCENDING), ("external_display_name", ASCENDING)]):
        key = {"branch": "branches", "manager": "managers", "agent": "agents"}.get(row.get("discovery_type"))
        if not key:
            continue
        serialized = serialize_integration_record(row)
        if row.get("discovery_type") == "agent":
            relationship = dict(serialized.get("relationship") or {})
            relationship.update({
                "status": relationship.get("status") or "needs_review",
                "reason": relationship.get("reason"),
                "resolution_source": relationship.get("resolution_source"),
                "agent_id": relationship.get("agent_id"),
                "agent_display_name": relationship.get("agent_display_name"),
                "manager_id": relationship.get("manager_id"),
                "manager_display_name": relationship.get("manager_display_name"),
                "direct_branch": relationship.get("direct_branch"),
                "manager_branch": relationship.get("manager_branch"),
                "direct_branch_options": relationship.get("direct_branch_options") or [],
                "manager_branch_options": relationship.get("manager_branch_options") or [],
                "external_branch": relationship.get("external_branch"),
                "fleetops_branch_id": relationship.get("fleetops_branch_id"),
                "fleetops_branch_name": relationship.get("fleetops_branch_name"),
            })
            serialized["relationship"] = relationship
        result[key].append(serialized)
    return result


STOCK_READY_STATUSES = {"confirmed", "completed", "deducted", "success"}


def _mapping_lookup(mapping_type: str) -> dict:
    result = {
        (normalize_branch_key(row.get("external_id") or row.get("external_code") or row.get("external_display_name")) if mapping_type == "branch" else row["external_key"]): row
        for row in mappings().find({"source_system": SOURCE_SYSTEM, "mapping_type": mapping_type, "active": True})
        if _mapping_target_is_current(mapping_type, row)
    }
    if mapping_type in {"agent", "manager"}:
        for external_key, user in _confirmed_source_users(mapping_type).items():
            result.setdefault(external_key, {
                "source_system": SOURCE_SYSTEM, "mapping_type": mapping_type,
                "external_key": external_key, "fleetops_id": user["_id"],
                "active": True, "resolution_source": "confirmed_user_source_link",
            })
    return result


def _mapping_target_is_current(mapping_type: str, mapping: dict) -> bool:
    target = mapping.get("fleetops_id")
    if not target or not ObjectId.is_valid(str(target)):
        return False
    target_id = ObjectId(str(target))
    if mapping_type == "branch":
        branch = get_collection("branches").find_one({"_id": target_id})
        status = str((branch or {}).get("status") or ("active" if (branch or {}).get("active", True) else "inactive")).casefold()
        return bool(branch and status == "active")
    user = get_collection("users").find_one({"_id": target_id})
    required_role = "field_agent" if mapping_type == "agent" else "branch_manager"
    return bool(
        user and str(user.get("status") or "").strip().casefold() == "active"
        and required_role in user_role_codes(user)
        and (user.get("primary_branch_id") or user.get("allowed_branch_ids"))
    )


def _confirmed_source_users(mapping_type: str) -> dict[str, dict]:
    """Return only unique, active, role-compatible source links; ambiguous links are ignored."""
    source_field = "smartliving_agent_id" if mapping_type == "agent" else "smartliving_manager_id"
    required_role = "field_agent" if mapping_type == "agent" else "branch_manager"
    grouped = defaultdict(list)
    for user in get_collection("users").find({source_field: {"$type": "string"}}):
        source_key = str(user.get(source_field) or "").strip().casefold()
        if not source_key or str(user.get("status") or "").strip().casefold() != "active":
            continue
        if required_role not in user_role_codes(user):
            continue
        if not user.get("primary_branch_id") and not user.get("allowed_branch_ids"):
            continue
        grouped[source_key].append(user)
    return {key: rows[0] for key, rows in grouped.items() if len(rows) == 1}


def _confirmed_agent_branch_id(agent_key: str | None, agent_mappings: dict | None = None):
    if not agent_key:
        return None
    mapping = (agent_mappings or {}).get(agent_key) if agent_mappings is not None else mappings().find_one({
        "source_system": SOURCE_SYSTEM, "mapping_type": "agent", "external_key": agent_key, "active": True,
    })
    user = get_collection("users").find_one({"_id": (mapping or {}).get("fleetops_id")}) if mapping else _confirmed_source_users("agent").get(agent_key)
    if not user or str(user.get("status") or "").strip().casefold() != "active" or "field_agent" not in user_role_codes(user):
        return None
    branch_id = user.get("primary_branch_id")
    if not branch_id:
        return None
    branch = get_collection("branches").find_one({"_id": branch_id})
    status = str((branch or {}).get("status") or ("active" if (branch or {}).get("active", True) else "inactive")).casefold()
    return branch_id if branch and status == "active" else None


def _branch_mapping_by_key(branch_key: str) -> dict | None:
    mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "branch", "external_key": branch_key, "active": True})
    if mapping:
        return mapping
    canonical_key = canonical_branch_alias_key(branch_key)
    return next((row for row in mappings().find({"source_system": SOURCE_SYSTEM, "mapping_type": "branch", "active": True}) if canonical_branch_alias_key(row.get("external_id") or row.get("external_code") or row.get("external_display_name")) == canonical_key), None)


def _completed_groups(rows: list[dict]) -> tuple[list[dict], int]:
    grouped = defaultdict(list)
    for index, row in enumerate(rows):
        source_id = str(row.get("_id") or "").strip()
        grouped[source_id or f"__missing_source_id__:{index}"].append(row)
    return list(grouped.values()), len(rows) - len(grouped)


def _completed_lines(rows: list[dict]) -> tuple[list[dict], list[str]]:
    lines = {}; errors = []
    for row in rows:
        product = row.get("product") or {}
        product_name = str(product.get("name") or "").strip()
        product_reference = str(product.get("_id") or product_name).strip()
        line_key = f"{product_reference.casefold()}|{row.get('product_index')}"
        quantity = product.get("quantity")
        if row.get("qty") not in (None, "") and quantity not in (None, "") and str(row["qty"]) != str(quantity):
            errors.append("conflicting_quantity")
        try:
            quantity = int(quantity if quantity not in (None, "") else row.get("qty"))
        except (TypeError, ValueError):
            quantity = 0
        candidate = {"product_reference": product_reference or None, "product_name": product_name or None, "quantity": quantity}
        if line_key in lines and lines[line_key] != candidate:
            errors.append("conflicting_product_line")
        lines[line_key] = candidate
    if any(not line["product_name"] for line in lines.values()): errors.append("missing_product_name")
    if any(not line["product_reference"] for line in lines.values()): errors.append("missing_product_reference")
    return list(lines.values()), sorted(set(errors))


def _completed_product_names(rows: list[dict]) -> dict[str, str]:
    names = defaultdict(set)
    for row in rows:
        product = row.get("product") or {}
        reference = str(product.get("_id") or "").strip()
        name = str(product.get("name") or "").strip()
        if reference and name:
            names[reference].add(name)
        for component in _nested(row, "inventory_recipe_snapshot.components") or []:
            reference = str((component or {}).get("inventory_product_id") or "").strip()
            name = str((component or {}).get("component_name") or "").strip()
            if reference and name:
                names[reference].add(name)
    return {reference: next(iter(values)) for reference, values in names.items() if len(values) == 1}


def _closed_product_names(row: dict, completed_names: dict[str, str]) -> dict[str, str]:
    names = defaultdict(set)
    for purchase in _nested(row, "customer.purchases") or []:
        product = (purchase or {}).get("product") or {}
        reference = str(product.get("_id") or "").strip()
        name = str(product.get("name") or "").strip()
        if reference and name:
            names[reference].add(name)
    result = {reference: next(iter(values)) for reference, values in names.items() if len(values) == 1}
    for reference, name in completed_names.items():
        result.setdefault(reference, name)
    return result


def _closed_lines(row: dict, completed_names: dict[str, str]) -> tuple[list[dict], list[str]]:
    targets = _nested(row, "payload.target_products") or []
    name_lookup = _closed_product_names(row, completed_names)
    lines = []
    for item in targets:
        if not isinstance(item, dict):
            continue
        reference = str(item.get("id") or "").strip()
        product_name = str(item.get("name") or item.get("product_name") or "").strip() or name_lookup.get(reference)
        try:
            quantity = int(item.get("qty"))
        except (TypeError, ValueError):
            quantity = 0
        lines.append({
            "product_reference": reference or None,
            "product_name": product_name,
            "quantity": quantity,
        })
    details = []
    if not targets: details.append("no_delivery_targets")
    if any(not line["product_reference"] for line in lines): details.append("missing_product_reference")
    if any(not line["product_name"] for line in lines): details.append("missing_target_product_name")
    stock_statuses = [str(item.get("stock_deduction_status") or item.get("stock_status") or "").strip().casefold() for item in targets if isinstance(item, dict)]
    if targets and not any(stock_statuses): details.append("stock_status_unavailable")
    elif any(status not in STOCK_READY_STATUSES for status in stock_statuses): details.append("stock_not_confirmed")
    return lines, details


def _source_datetime(row: dict, endpoint: str) -> datetime | None:
    field = SOURCE_DATE_FIELDS[endpoint]
    try:
        return _parse_source_datetime(row.get(field), field)
    except ApiError:
        return None


def _intake_controls(payload: dict | None, *, require_dates=False) -> dict:
    payload = payload or {}
    source = str(payload.get("source") or "both").strip().lower()
    if source not in SOURCE_OPTIONS:
        raise ApiError("source must be completed-cards, closed-cards, or both.", status_code=400)
    endpoints = list(SOURCE_ENDPOINTS) if source == "both" else [source]
    from_value = str(payload.get("from_date") or "").strip()
    to_value = str(payload.get("to_date") or "").strip()
    if require_dates and (not from_value or not to_value):
        raise ApiError("from_date and to_date are required.", status_code=400)
    try:
        from_date = date.fromisoformat(from_value) if from_value else None
        to_date = date.fromisoformat(to_value) if to_value else None
    except ValueError:
        raise ApiError("from_date and to_date must use YYYY-MM-DD.", status_code=400) from None
    if from_date and to_date and from_date > to_date:
        raise ApiError("from_date cannot be after to_date.", status_code=400)
    if from_date and to_date and (to_date - from_date).days > 366:
        raise ApiError("The intake period cannot exceed 367 days.", status_code=400)
    return {
        "source": source, "endpoints": endpoints, "from_date": from_date,
        "to_date": to_date, "from_date_text": from_value or None, "to_date_text": to_value or None,
        "quick_option": str(payload.get("quick_option") or "custom").strip().lower(),
        "exclude_already_delivered": False,
    }


def _rows_in_period(source_rows: dict, controls: dict) -> tuple[dict, dict]:
    filtered = {}; counts = {"fetched": 0, "outside_period": 0, "missing_or_invalid_date": 0}
    bounded = controls["from_date"] is not None and controls["to_date"] is not None
    for endpoint in controls["endpoints"]:
        selected = []
        for row in source_rows.get(endpoint) or []:
            counts["fetched"] += 1
            source_datetime = _source_datetime(row, endpoint)
            if not source_datetime:
                counts["missing_or_invalid_date"] += 1
                selected.append(row)
                continue
            if bounded and not (controls["from_date"] <= source_datetime.date() <= controls["to_date"]):
                counts["outside_period"] += 1
                continue
            selected.append(row)
        filtered[endpoint] = selected
    return filtered, counts


def _preview_record(source_record_id: str, endpoint: str, outcome: str, blockers: list[str], other_detail: list[str], row: dict, lines: list[dict], mapping_status: str, eligible: bool) -> dict:
    agent_id, agent_name = _external_agent(row, endpoint)
    customer = row.get("customer") or {}
    normalized = row.get("_normalized") or {}
    source_datetime = _source_datetime(row, endpoint)
    source_status = row.get("status") if endpoint == "completed-cards" else row.get("action")
    status_labels = {"close_card": "Closed card", "pending": "Completed card", "completed": "Completed", "closed": "Closed", "delivering": "Out for delivery", "delivered": "Delivered"}
    status_key = str(source_status or "").strip().casefold()
    entities = dict(normalized.get("entities") or {})
    entities["products"] = [{
        "id": line.get("product_reference"), "display_name": line.get("product_name"), "quantity": line.get("quantity"),
    } for line in lines]
    # SmartLiving source completion means intake-ready. Only FleetOps driver
    # execution can mark the physical delivery complete.
    physically_delivered = False
    return {
        "source_record_id": source_record_id, "source_endpoint": endpoint,
        "outcome": outcome, "blockers": sorted(set(blockers)), "reasons": sorted(set(blockers)),
        "other_detail": sorted(set(other_detail)), "eligible": eligible,
        "blocked_eligible": outcome == "blocked",
        "external_branch": _external_branch(row), "branch_name": _external_branch(row),
        "external_agent_id": agent_id, "external_agent_name": agent_name,
        "customer_name": normalized.get("customer_name") or str(row.get("customer_name") or customer.get("name") or "").strip() or None,
        "customer_phone": normalized.get("customer_phone") or str(row.get("customer_phone") or customer.get("phone_number") or "").strip() or None,
        "customer_location": normalized.get("customer_location") or str(customer.get("location") or "").strip() or None,
        "customer_occupation": normalized.get("customer_occupation") or str(customer.get("occupation") or "").strip() or None,
        "entities": entities, "relationship": normalized.get("relationship"),
        "products": [{"name": line.get("product_name"), "reference": line.get("product_reference"), "quantity": line.get("quantity")} for line in lines],
        "product_count": len(lines), "source_status": source_status,
        "source_status_label": status_labels.get(status_key) or status_key.replace("_", " ").title() or "Unknown",
        "source_date": source_datetime, "source_date_field": SOURCE_DATE_FIELDS[endpoint],
        "mapping_status": mapping_status, "import_eligible": outcome == "ready",
        "physically_delivered": physically_delivered, "selected_key": f"{endpoint}:{source_record_id}",
    }


def _classify_blockers(*, source_record_id: str, endpoint: str, row: dict, lines: list[dict],
                       eligible: bool, branch_mappings: dict, agent_mappings: dict,
                       manager_mappings: dict,
                       duplicate=False, already_imported=False, detail_reasons=None) -> tuple[list[str], list[str]]:
    """The single canonical blocker classifier used by preview and READY."""
    blockers = set(); details = set(detail_reasons or [])
    if not source_record_id:
        blockers.add("missing_source_id")
    if not _source_datetime(row, endpoint):
        blockers.add("invalid_source_date")
    customer = row.get("customer") or {}; normalized = row.get("_normalized") or {}
    customer_name = str(normalized.get("customer_name") or row.get("customer_name") or customer.get("name") or "").strip()
    customer_phone = str(normalized.get("customer_phone") or row.get("customer_phone") or customer.get("phone_number") or "").strip()
    customer_location = str(normalized.get("customer_location") or _nested(row, "customer.location") or "").strip()
    if not customer_name: blockers.add("missing_customer_name")
    if not customer_phone: blockers.add("missing_customer_phone")
    if not customer_location: blockers.add("missing_customer_location")
    if not lines:
        blockers.add("missing_product")
    if any(not line.get("product_name") for line in lines):
        blockers.add("missing_product_name")
    if any(not line.get("product_reference") for line in lines):
        blockers.add("missing_product_reference")
    if any(not isinstance(line.get("quantity"), int) or line["quantity"] <= 0 for line in lines):
        blockers.add("missing_quantity")
    specific_detail_blockers = {
        "conflicting_quantity", "conflicting_product_line",
        "unsupported_status", "unsupported_action", "no_delivery_targets",
        "missing_target_product_name",
    }
    blockers.update(reason for reason in details if reason in specific_detail_blockers)
    if "missing_target_product_name" in blockers:
        blockers.remove("missing_target_product_name")
        blockers.add("missing_product_name")
    if eligible:
        branch = str(_external_branch(row) or "").strip()
        agent_id, _ = _external_agent(row, endpoint)
        confirmed_agent_branch = _confirmed_agent_branch_id(agent_id.casefold() if agent_id else None, agent_mappings)
        if not branch:
            blockers.add("missing_branch")
        elif normalize_branch_key(branch) not in branch_mappings and not confirmed_agent_branch:
            blockers.add("unmapped_branch")
        if not agent_id:
            blockers.add("missing_agent")
        elif agent_id.casefold() not in agent_mappings:
            blockers.add("unmapped_agent")
        manager_id = str(normalized.get("manager_id") or "").strip()
        if manager_id and manager_id.casefold() not in manager_mappings:
            blockers.add("unmapped_manager")
    if already_imported:
        blockers.add("duplicate")
    elif duplicate:
        blockers.add("duplicate")
    return sorted(blockers), sorted(details)


def _is_ready(eligible: bool, blockers: list[str]) -> bool:
    """Authoritative READY predicate; classifier blockers encode every required field and safety gate."""
    return eligible and not blockers


def _preview_exception_write(preview: dict, actor_id: str, timestamp):
    mapping_reasons = [reason for reason in preview["blockers"] if reason in {"unmapped_branch", "unmapped_agent", "unmapped_manager"}]
    if not mapping_reasons:
        return None
    open_key = f"dry-run|smartliving|delivery_card|{preview['source_record_id']}"
    exception_type = "unmapped_branch" if "unmapped_branch" in mapping_reasons else "unmapped_manager" if "unmapped_manager" in mapping_reasons else "unmapped_agent"
    document = {
        "source_system": SOURCE_SYSTEM, "source_type": "delivery_card",
        "source_record_id": preview["source_record_id"], "open_key": open_key,
        "exception_type": exception_type, "message": ", ".join(reason.replace("_", " ") for reason in mapping_reasons),
        "status": "open", "preview_only": True, "retryable": False,
        "source_context": {
            "source_endpoint": preview["source_endpoint"], "external_branch": preview["external_branch"],
            "external_agent_id": preview["external_agent_id"], "blocking_reasons": mapping_reasons,
        },
        "updated_by": object_id(actor_id), "updated_at": timestamp,
    }
    return open_key, UpdateOne(
        {"open_key": open_key},
        {"$set": document, "$setOnInsert": {"created_by": object_id(actor_id), "created_at": timestamp, "attempt_count": 0}},
        upsert=True,
    )


def _canonical_payload(endpoint: str, row: dict, lines: list[dict], source_datetime: datetime, controls: dict, batch_id: str) -> dict:
    customer = row.get("customer") or {}
    normalized = row.get("_normalized") or {}
    agent_id, agent_name = _external_agent(row, endpoint)
    coordinates = customer.get("coordinates") or {}
    return {
        "source_system": SOURCE_SYSTEM, "source_type": "delivery_card",
        "source_record_id": str(row.get("_id") or ""), "source_synced_at": now_utc(),
        "source_date": source_datetime, "source_date_field": SOURCE_DATE_FIELDS[endpoint],
        "branch_reference": {"external_code": str(_external_branch(row) or "").strip(), "external_display_name": str(_external_branch(row) or "").strip()},
        "agent_reference": {"external_id": agent_id, "external_display_name": agent_name},
        "manager_reference": {"external_id": normalized.get("manager_id"), "external_display_name": normalized.get("manager_name")},
        "reference_number": str(row.get("_id") or ""),
        "customer_name": str(normalized.get("customer_name") or row.get("customer_name") or customer.get("name") or "").strip(),
        "phone": str(normalized.get("customer_phone") or row.get("customer_phone") or customer.get("phone_number") or "").strip(),
        "delivery_address": str(normalized.get("customer_location") or _nested(row, "customer.location") or "").strip(),
        "latitude": coordinates.get("latitude"), "longitude": coordinates.get("longitude"),
        "product_lines": [{"product_name": line.get("product_name"), "quantity": line.get("quantity")} for line in lines],
        "notes": f"Imported from SmartLiving {endpoint} ({SOURCE_DATE_FIELDS[endpoint]}).",
        "import_metadata": {
            "batch_id": batch_id, "source": controls["source"],
            "from_date": controls["from_date_text"], "to_date": controls["to_date_text"],
        },
    }


def dry_run_import(actor_id: str, controls_payload: dict | None = None, *, source_rows: dict | None = None, persist=True, include_candidates=False) -> dict:
    scan_started = perf_counter()
    _actor(actor_id)
    controls = _intake_controls(controls_payload, require_dates=source_rows is None)
    if source_rows is None:
        source_rows, fetch_metrics = fetch_source_records(
            controls["endpoints"], from_date=controls["from_date"], with_metrics=True,
        )
    else:
        fetch_metrics = {
            "api_calls": 0, "pages_fetched": 0,
            "records_fetched": sum(len(source_rows.get(endpoint) or []) for endpoint in controls["endpoints"]),
            "retries": 0, "duration_ms": 0, "endpoints": {},
        }
    source_rows = {endpoint: source_rows.get(endpoint) or [] for endpoint in controls["endpoints"]}
    source_rows = _normalize_source_rows(source_rows)
    completed_names = _completed_product_names(source_rows.get("completed-cards") or [])
    source_rows, range_counts = _rows_in_period(source_rows, controls)
    completed_rows = source_rows.get("completed-cards") or []; closed_rows = source_rows.get("closed-cards") or []
    completed_groups, collapsed_rows = _completed_groups(completed_rows)
    branch_mappings = _mapping_lookup("branch"); agent_mappings = _mapping_lookup("agent"); manager_mappings = _mapping_lookup("manager")
    existing_ids = {
        str(row.get("source_record_id"))
        for row in orders().find({"source_system": SOURCE_SYSTEM, "source_type": "delivery_card"}, {"source_record_id": 1})
    }
    timestamp = now_utc(); seen_source_ids = set(); preview_exception_writes = {}; previews = []; candidates = {}

    def classify(source_record_id, endpoint, row, lines, detail_reasons, eligible, *, cross_source_duplicate=False):
        already_imported = bool(source_record_id) and source_record_id in existing_ids
        duplicate = bool(source_record_id) and (source_record_id in seen_source_ids or cross_source_duplicate)
        if source_record_id:
            seen_source_ids.add(source_record_id)
        blockers, other_detail = _classify_blockers(
            source_record_id=source_record_id, endpoint=endpoint, row=row, lines=lines, eligible=eligible,
            branch_mappings=branch_mappings, agent_mappings=agent_mappings,
            manager_mappings=manager_mappings,
            duplicate=duplicate, already_imported=already_imported, detail_reasons=detail_reasons,
        )
        # Imported identities are a completed classification, not an eligibility failure.
        if already_imported:
            outcome = "already_imported"
        elif _is_ready(eligible, blockers):
            outcome = "ready"
        elif eligible:
            outcome = "blocked"
        else:
            outcome = "invalid_ignored"
        mapping_blockers = {"missing_branch", "unmapped_branch", "missing_agent", "unmapped_agent", "unmapped_manager"}
        mapping_status = "mapped" if not mapping_blockers.intersection(blockers) else "unmapped"
        preview = _preview_record(source_record_id, endpoint, outcome, blockers, other_detail, row, lines, mapping_status, eligible)
        previews.append(preview)
        if outcome == "ready":
            candidates[preview["selected_key"]] = (endpoint, row, lines, preview["source_date"])
        exception_write = _preview_exception_write(preview, actor_id, timestamp)
        if exception_write:
            open_key, operation = exception_write
            preview_exception_writes[open_key] = operation

    for group in completed_groups:
        row = group[0]; source_record_id = str(row.get("_id") or "").strip(); lines, reasons = _completed_lines(group)
        status = str(row.get("status") or "").strip().casefold()
        eligible = status in COMPLETED_CARD_READY_STATUSES
        if status not in COMPLETED_CARD_READY_STATUSES: reasons.append("unsupported_status")
        classify(source_record_id, "completed-cards", row, lines, reasons, eligible)

    for row in closed_rows:
        source_record_id = str(row.get("_id") or ""); targets = _nested(row, "payload.target_products") or []
        reasons = []; eligible = str(row.get("action") or "").casefold() == "close_card" and bool(targets)
        if str(row.get("action") or "").casefold() != "close_card": reasons.append("unsupported_action")
        lines, line_reasons = _closed_lines(row, completed_names); reasons.extend(line_reasons)
        classify(source_record_id, "closed-cards", row, lines, reasons, eligible)

    if persist:
        seen_exception_keys = set(preview_exception_writes)
        if preview_exception_writes:
            exceptions().bulk_write(list(preview_exception_writes.values()), ordered=False)
        if seen_source_ids:
            stale_query = {
                "source_system": SOURCE_SYSTEM, "preview_only": True, "status": "open",
                "source_record_id": {"$in": list(seen_source_ids)},
            }
            if seen_exception_keys:
                stale_query["open_key"] = {"$nin": list(seen_exception_keys)}
            stale_updates = {"status": "resolved", "resolution_notes": "No longer blocked in latest dry run.", "resolved_at": timestamp, "updated_at": timestamp}
            exceptions().update_many(stale_query, {"$set": stale_updates, "$unset": {"open_key": ""}})
    errors = [item for item in previews if item["outcome"] != "ready"]
    ready = [item for item in previews if item["outcome"] == "ready"]
    blocker_counts = {blocker: sum(blocker in item["blockers"] for item in previews) for blocker in CANONICAL_BLOCKERS}
    source_eligible_count = sum(bool(item["eligible"]) for item in previews)
    blocked_eligible = sum(item["outcome"] == "blocked" for item in previews)
    already_imported_count = sum(item["outcome"] == "already_imported" for item in previews)
    eligible_count = len(ready) + blocked_eligible
    metrics = {
        "eligible": eligible_count, "source_eligible": source_eligible_count,
        "ready": len(ready), "blocked": blocked_eligible,
        "blocked_eligible": blocked_eligible, "already_imported": already_imported_count,
        "duplicates": blocker_counts["duplicate"], "unmapped_branches": blocker_counts["unmapped_branch"],
        "unmapped_agents": blocker_counts["unmapped_agent"],
        "unmapped_managers": blocker_counts["unmapped_manager"],
        "invalid_ignored": sum(item["outcome"] == "invalid_ignored" for item in previews),
        "blocker_counts": blocker_counts,
    }
    if metrics["eligible"] != metrics["ready"] + metrics["blocked_eligible"]:
        raise RuntimeError("SmartLiving preview counter invariant failed")
    scan_duration_ms = round((perf_counter() - scan_started) * 1000)
    performance = {
        **fetch_metrics, "records_matched": len(completed_rows) + len(closed_rows),
        "total_duration_ms": scan_duration_ms,
    }
    _log_info(
        "[SmartLiving Preview] scan source=%s range=%s..%s api_calls=%s pages=%s fetched=%s matched=%s duration_ms=%s",
        controls["source"], controls["from_date_text"], controls["to_date_text"], performance["api_calls"],
        performance["pages_fetched"], performance["records_fetched"], performance["records_matched"], scan_duration_ms,
    )
    summary = {
        "source_system": SOURCE_SYSTEM, "total_scanned": len(completed_rows) + len(closed_rows), "found": len(previews),
        "controls": {
            "source": controls["source"], "from_date": controls["from_date_text"], "to_date": controls["to_date_text"],
            "quick_option": controls["quick_option"], "exclude_already_delivered": controls["exclude_already_delivered"],
        },
        "date_fields": SOURCE_DATE_FIELDS, "range_counts": range_counts, "performance": performance,
        "source_counts": {
            "completed_rows": len(completed_rows), "completed_records": len(completed_groups),
            "closed_rows": len(closed_rows), "closed_records": len(closed_rows),
        },
        **metrics,
        "deduplication": {"completed_rows_collapsed_by_card_id": collapsed_rows, "canonical_source_ids_seen": len(seen_source_ids)},
        "records": previews, "sample_ready": ready[:10], "sample_errors": errors[:20],
        "created_at": timestamp, "created_by": object_id(actor_id), "deliveries_created": 0,
    }
    if persist:
        result = dry_runs().insert_one(summary); summary["_id"] = result.inserted_id
        write_audit("smartliving_dry_run_completed", actor_id, "integration_dry_run", result.inserted_id, {"new": {key: summary[key] for key in ("total_scanned", "eligible", "ready", "duplicates", "unmapped_branches", "unmapped_agents", "invalid_ignored")}})
    serialized = serialize_integration_record(summary)
    if include_candidates:
        serialized["_candidates"] = candidates
    return serialized


def import_selected_records(payload: dict, actor_id: str, *, source_rows: dict | None = None) -> dict:
    _actor(actor_id)
    controls = _intake_controls(payload, require_dates=source_rows is None)
    selected = payload.get("selected_records") or []
    if not isinstance(selected, list) or not selected:
        raise ApiError("Select at least one READY record to import.", status_code=400)
    if len(selected) > 500:
        raise ApiError("No more than 500 records can be imported in one batch.", status_code=400)
    selected_keys = set()
    for item in selected:
        endpoint = str((item or {}).get("source_endpoint") or "").strip()
        record_id = str((item or {}).get("source_record_id") or "").strip()
        if endpoint not in controls["endpoints"] or not record_id:
            raise ApiError("Every selected record must belong to the selected source and include its source ID.", status_code=400)
        selected_keys.add(f"{endpoint}:{record_id}")
    preview = dry_run_import(actor_id, payload, source_rows=source_rows, persist=False, include_candidates=True)
    candidates = preview.pop("_candidates")
    preview_by_key = {item["selected_key"]: item for item in preview.get("records") or []}
    batch_id = str(ObjectId())
    results = []; imported = 0; duplicate = 0
    for key in sorted(selected_keys):
        candidate = candidates.get(key)
        if not candidate:
            preview_record = preview_by_key.get(key)
            outcome = "duplicate_already_imported" if preview_record and preview_record.get("outcome") == "already_imported" else "not_ready_or_not_found"
            results.append({"selected_key": key, "outcome": outcome})
            duplicate += 1 if outcome == "duplicate_already_imported" else 0
            continue
        endpoint, row, lines, source_datetime = candidate
        intake_payload = _canonical_payload(endpoint, row, lines, source_datetime, controls, batch_id)
        outcome = intake_delivery(intake_payload, actor_id)
        results.append({"selected_key": key, "outcome": outcome["outcome"], "delivery": outcome.get("delivery")})
        imported += 1 if outcome["outcome"] == "imported" else 0
        duplicate += 1 if outcome["outcome"] == "duplicate_skipped" else 0
    summary = {
        "batch_id": batch_id, "source": controls["source"], "from_date": controls["from_date_text"], "to_date": controls["to_date_text"],
        "selected": len(selected_keys), "imported": imported, "duplicate_already_imported": duplicate,
        "rejected": len(selected_keys) - imported - duplicate, "results": results, "imported_at": now_utc(), "imported_by": object_id(actor_id),
    }
    write_audit("smartliving_import_batch_completed", actor_id, "integration_import_batch", batch_id, {"new": {key: summary[key] for key in ("source", "from_date", "to_date", "selected", "imported", "duplicate_already_imported", "rejected")}})
    return serialize_integration_record(summary)


def latest_dry_run(actor_id: str) -> dict | None:
    _actor(actor_id)
    row = dry_runs().find_one({"source_system": SOURCE_SYSTEM}, sort=[("created_at", DESCENDING)])
    return serialize_integration_record(row) if row else None


def test_connection(actor_id: str) -> dict:
    _actor(actor_id)
    base_url = str(current_app.config.get("SMARTLIVING_API_BASE_URL") or "").strip().rstrip("/")
    api_key = str(current_app.config.get("SMARTLIVING_API_KEY") or "").strip()
    timestamp = now_utc()
    parsed = urlparse(base_url)
    if not base_url or not api_key or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        endpoint_results = []
        connection_status = "failed"
    else:
        endpoint_results = [
            _probe_endpoint(base_url, api_key, "completed-cards"),
            _probe_endpoint(base_url, api_key, "closed-cards"),
        ]
        connection_status = "connected" if all(
            item["reachable"] and item["json"] and 200 <= item["http_status"] < 300
            for item in endpoint_results
        ) else "failed"
    document = {
        "source_system": SOURCE_SYSTEM, "configured": bool(base_url and api_key),
        "connection_status": connection_status, "endpoints": endpoint_results,
        "last_checked": timestamp, "last_checked_by": object_id(actor_id), "updated_at": timestamp,
    }
    connections().update_one({"source_system": SOURCE_SYSTEM}, {"$set": document}, upsert=True)
    write_audit(
        "smartliving_connection_tested", actor_id, "integration_connection", SOURCE_SYSTEM,
        {"new": {"connection_status": connection_status, "last_checked": timestamp}},
        {"endpoint_statuses": [{"endpoint": item["endpoint"], "http_status": item["http_status"]} for item in endpoint_results]},
    )
    return serialize_integration_record(document)


def _active_branch(branch_id, context: dict | None = None) -> dict | None:
    if not branch_id or not ObjectId.is_valid(str(branch_id)):
        return None
    oid = ObjectId(str(branch_id))
    branch = (context.get("branches_by_id", {}).get(oid) if context else None) or get_collection("branches").find_one({"_id": oid})
    if not branch:
        return None
    status = str(branch.get("status") or ("active" if branch.get("active", True) else "inactive")).lower()
    return branch if status == "active" else None


def _role_names(user: dict) -> str:
    return " + ".join(code.replace("_", " ").title() for code in user_role_codes(user)) or "Existing user"


def _ensure_source_role_link(user: dict, required_role: str, branch: dict, source_field: str,
                             source_id: str, actor_id: str) -> dict:
    """Add one source identity/role without replacing existing account access."""
    if not user or str(user.get("status") or "").lower() != "active":
        _coded_error("DUPLICATE_ACCOUNT", "The selected FleetOps account is not active.")
    if user.get("primary_branch_id") not in (None, branch["_id"]):
        _coded_error("BRANCH_CONFLICT", "The selected account belongs to another primary branch.")
    current_source_id = str(user.get(source_field) or "").strip()
    if current_source_id and current_source_id.casefold() != source_id.casefold():
        _coded_error("DUPLICATE_ACCOUNT", f"The account is linked to a different SmartLiving {required_role.replace('_', ' ')} identity.")
    conflicting_user = get_collection("users").find_one({
        "_id": {"$ne": user["_id"]},
        "$or": [
            {"smartliving_agent_id": source_id},
            {"smartliving_manager_id": source_id},
        ],
    }, {"_id": 1})
    if conflicting_user:
        _coded_error("DUPLICATE_ACCOUNT", "This SmartLiving identity is already linked to another FleetOps user.")

    before_roles = user_role_codes(user)
    after_roles = list(before_roles)
    if required_role not in after_roles:
        after_roles.append(required_role)
    updates = {
        "role_ids": after_roles,
        source_field: source_id,
        "primary_branch_id": user.get("primary_branch_id") or branch["_id"],
        "updated_at": now_utc(),
    }
    if not user.get("role"):
        updates["role"] = after_roles[0]
    if not user.get("selected_workspace"):
        updates["selected_workspace"] = user.get("role") or after_roles[0]
    result = get_collection("users").update_one(
        {"_id": user["_id"], "$or": [{source_field: {"$in": [None, "", source_id]}}, {source_field: {"$exists": False}}]},
        {"$set": updates, "$addToSet": {"allowed_branch_ids": branch["_id"]}},
    )
    if not result.matched_count:
        _coded_error("DUPLICATE_ACCOUNT", "The SmartLiving identity link changed; no account data was overwritten.")
    changed = required_role not in before_roles or not current_source_id or user.get("primary_branch_id") is None
    refreshed = get_collection("users").find_one({"_id": user["_id"]})
    if changed:
        write_audit("smartliving_identity_role_linked", actor_id, "user", user["_id"], {
            "before": {"roles": before_roles, source_field: current_source_id or None,
                       "branch_id": str(user.get("primary_branch_id")) if user.get("primary_branch_id") else None},
            "after": {"roles": after_roles, source_field: source_id, "branch_id": str(branch["_id"])},
        })
    return refreshed


def _branch_manager(branch: dict, manager_id=None, context: dict | None = None) -> dict | None:
    manager_references = [branch.get("manager_id"), *(branch.get("manager_ids") or [])]
    manager_references = list(dict.fromkeys(value for value in manager_references if value))
    selected = manager_id or (manager_references[0] if len(manager_references) == 1 else None)
    if not selected or not ObjectId.is_valid(str(selected)):
        return None
    oid = ObjectId(str(selected))
    manager = (context.get("users_by_id", {}).get(oid) if context else None) or get_collection("users").find_one({"_id": oid})
    if not manager or "branch_manager" not in user_role_codes(manager):
        return None
    if str(manager.get("status") or "").lower() != "active":
        return None
    manager_branches = {manager.get("primary_branch_id"), *(manager.get("allowed_branch_ids") or [])}
    return manager if branch["_id"] in manager_branches else None


def _agent_mapping(external_key: str, context: dict | None = None) -> dict | None:
    if context is not None:
        return context.get("agent_mappings", {}).get(external_key)
    return mappings().find_one({
        "source_system": SOURCE_SYSTEM, "mapping_type": "agent",
        "external_key": external_key, "active": True,
    })


def _resolved_agent_context(discovery: dict, context: dict | None = None) -> tuple[dict | None, dict | None, str | None, list[str]]:
    relationship = discovery.get("relationship") or {}
    resolution = discovery.get("provisioning_resolution") or {}
    name = str(resolution.get("agent_name") or discovery.get("external_display_name") or relationship.get("agent_display_name") or "").strip()
    reasons = []
    agent_id = str(discovery.get("external_id") or "").strip()
    if not agent_id:
        reasons.append("missing_agent_id")
    if not name or name.casefold() == agent_id.casefold():
        reasons.append("missing_agent_name")

    if resolution:
        branch = _active_branch(resolution.get("branch_id"), context)
        if not branch:
            reasons.append("unresolved_branch")
        manager = _branch_manager(branch, resolution.get("manager_id"), context) if branch else None
        if not manager:
            reasons.append("unresolved_manager")
        return branch, manager, name or None, list(dict.fromkeys(reasons))

    source_manager_key = str(relationship.get("manager_id") or "").strip().casefold()
    manager_mapping = (context.get("manager_mappings", {}).get(source_manager_key) if context is not None else mappings().find_one({
        "source_system": SOURCE_SYSTEM, "mapping_type": "manager", "external_key": source_manager_key, "active": True,
    })) if source_manager_key else None
    manager_id = (manager_mapping or {}).get("fleetops_id")
    manager_oid = ObjectId(str(manager_id)) if manager_id and ObjectId.is_valid(str(manager_id)) else None
    manager = ((context or {}).get("users_by_id", {}).get(manager_oid) if manager_oid else None) or (
        get_collection("users").find_one({"_id": manager_oid}) if manager_oid else None
    )
    if not manager or "branch_manager" not in user_role_codes(manager) or str(manager.get("status") or "").lower() != "active":
        manager = None
        reasons.append("unresolved_manager")

    direct_options = relationship.get("direct_branch_options") or []
    direct_keys = {canonical_branch_alias_key(value) for value in direct_options if canonical_branch_alias_key(value)}
    direct_value = relationship.get("direct_branch") or (next(iter(direct_options)) if len(direct_keys) == 1 and direct_options else None) or relationship.get("external_branch")
    if len(direct_keys) > 1:
        reasons.append("conflicting_direct_branch")
        direct_value = None
    direct_key = canonical_branch_alias_key(direct_value)
    direct_mapping = (context.get("branch_mappings", {}).get(direct_key) if context is not None else _branch_mapping_by_key(direct_key)) if direct_key else None
    direct_branch = _active_branch((direct_mapping or {}).get("fleetops_id"), context)
    if direct_value and not direct_branch:
        reasons.append("unresolved_branch")

    manager_branch = _active_branch(manager.get("primary_branch_id"), context) if manager else None
    branch = direct_branch or (manager_branch if not direct_value else None)
    if direct_branch and manager_branch and direct_branch["_id"] != manager_branch["_id"]:
        reasons.append("conflicting_agent_manager_branch")
    if not branch:
        branch = direct_branch or manager_branch
    if not branch and "unresolved_branch" not in reasons:
        reasons.append("unresolved_branch")

    relationship_reason = relationship.get("reason")
    if relationship_reason in {"conflicting_manager", "conflicting_agent_name"}:
        reasons.append(relationship_reason)
    return branch, manager, name or None, list(dict.fromkeys(reasons))


def _provisioning_agent(discovery: dict, context: dict | None = None) -> dict:
    agent_id = str(discovery.get("external_id") or "").strip()
    relationship = discovery.get("relationship") or {}
    direct_options = relationship.get("direct_branch_options") or []
    direct_keys = {canonical_branch_alias_key(value) for value in direct_options if canonical_branch_alias_key(value)}
    source_direct_branch = relationship.get("direct_branch") or (
        sorted(direct_options, key=lambda value: (len(value), value.casefold()))[0]
        if len(direct_keys) == 1 and direct_options else None
    )
    external_key = str(discovery.get("external_key") or agent_id.casefold()).strip()
    branch, manager, name, reasons = _resolved_agent_context(discovery, context)
    mapping = _agent_mapping(external_key, context) if external_key else None
    linked_user = ((context or {}).get("users_by_id", {}).get(mapping.get("fleetops_id")) if mapping else None)
    if mapping and linked_user is None and context is None:
        linked_user = get_collection("users").find_one({"_id": mapping.get("fleetops_id")})
    if not mapping and external_key:
        manager_mapping = ((context or {}).get("manager_mappings", {}).get(external_key) if context is not None else mappings().find_one({
            "source_system": SOURCE_SYSTEM, "mapping_type": "manager", "external_key": external_key, "active": True,
        }))
        if manager_mapping:
            linked_user = ((context or {}).get("users_by_id", {}).get(manager_mapping.get("fleetops_id")) if context is not None else get_collection("users").find_one({"_id": manager_mapping.get("fleetops_id")}))

    identity_match_method = None
    identity_candidates = []
    if not linked_user:
        candidate_users = list((context or {}).get("users_by_id", {}).values()) if context is not None else list(get_collection("users").find({}))
        source_matches = [user for user in candidate_users if agent_id and agent_id.casefold() in {
            str(user.get("smartliving_agent_id") or "").strip().casefold(),
            str(user.get("smartliving_manager_id") or "").strip().casefold(),
        }]
        email = _normalized_identity(discovery.get("email"))
        phone = _normalized_phone(discovery.get("phone"))
        contact_matches = [user for user in candidate_users if (
            email and _normalized_identity(user.get("email")) == email
        ) or (
            phone and _normalized_phone(user.get("phone")) == phone
        )]
        authoritative = list({user["_id"]: user for user in [*source_matches, *contact_matches]}.values())
        if len(authoritative) == 1:
            linked_user = authoritative[0]
            identity_match_method = "source_id" if source_matches else "contact"
        elif len(authoritative) > 1:
            reasons.append("ambiguous_existing_identity")
            identity_candidates = authoritative
        else:
            name_key = _normalized_identity(name)
            name_matches = [user for user in candidate_users if name_key and _normalized_identity(user.get("full_name")) == name_key]
            if name_matches:
                reasons.append("existing_identity_requires_confirmation")
                identity_candidates = name_matches

    inactive = discovery.get("currently_observed") is False or str(discovery.get("provisioning_state") or "").lower() in {"ignored", "inactive"}
    status = "ignored_inactive" if inactive else "needs_review"
    if linked_user:
        if branch and linked_user.get("primary_branch_id") not in (None, branch["_id"]):
            reasons.append("linked_user_branch_conflict")
        elif str(linked_user.get("status") or "").lower() != "active":
            reasons.append("linked_user_inactive")
        elif mapping and set(AGENT_ROLE_CODES).intersection(user_role_codes(linked_user)):
            status = "provisioned" if mapping.get("provisioning_origin") == "smartliving" else "existing"
            reasons = []
        elif not reasons:
            status = "eligible"
    elif mapping:
        reasons.append("linked_user_missing")
    elif not inactive and not reasons:
        status = "eligible"

    code_map = {
        "missing_agent_id": "MISSING_SOURCE_ID", "missing_agent_name": "MISSING_NAME",
        "unresolved_branch": "UNRESOLVED_BRANCH", "missing_branch": "UNRESOLVED_BRANCH",
        "unresolved_manager": "UNRESOLVED_MANAGER", "missing_manager_id": "UNRESOLVED_MANAGER",
        "conflicting_manager": "UNRESOLVED_MANAGER", "conflicting_manager_name": "AMBIGUOUS_MANAGER",
        "conflicting_agent_name": "AMBIGUOUS_IDENTITY",
        "conflicting_manager_branch": "BRANCH_CONFLICT", "conflicting_direct_branch": "BRANCH_CONFLICT",
        "conflicting_agent_manager_branch": "BRANCH_CONFLICT", "linked_user_branch_conflict": "BRANCH_CONFLICT",
        "existing_identity_role_or_branch_conflict": "DUPLICATE_ACCOUNT",
        "existing_identity_requires_confirmation": "AMBIGUOUS_IDENTITY",
        "ambiguous_existing_identity": "AMBIGUOUS_IDENTITY",
    }
    return {
        "discovery_id": str(discovery["_id"]), "agent_id": agent_id or None,
        "name": name, "status": status, "reasons": list(dict.fromkeys(reasons)),
        "error_codes": list(dict.fromkeys(code_map.get(reason, reason.upper()) for reason in reasons)),
        "branch_id": str(branch["_id"]) if branch else None,
        "branch_name": branch.get("name") if branch else None,
        "manager_id": str(manager["_id"]) if manager else None,
        "manager_name": (manager.get("full_name") or manager.get("username")) if manager else None,
        "fleetops_user_name": (linked_user.get("full_name") or linked_user.get("username")) if linked_user else None,
        "identity_match_method": identity_match_method,
        "candidate_user_ids": [str(user["_id"]) for user in identity_candidates],
        "source_direct_branch": source_direct_branch,
        "source_manager_branch": relationship.get("manager_branch"),
        "source_direct_branch_options": relationship.get("direct_branch_options") or [],
        "source_manager_branch_options": relationship.get("manager_branch_options") or [],
        "source_manager_name": relationship.get("manager_display_name"),
        "confirmed_manager_name": (manager.get("full_name") or manager.get("username")) if manager else None,
        "manager_branch_name": ((_active_branch(manager.get("primary_branch_id"), context) or {}).get("name")) if manager else None,
        "conflict_reason": next((code_map.get(reason, reason.upper()) for reason in reasons if reason.startswith("conflicting_")), None),
        "relationship_status": relationship.get("status"), "relationship_reason": relationship.get("reason"),
        "user_id": str(linked_user["_id"]) if linked_user else None,
        "username": linked_user.get("username") if linked_user else None,
        "must_change_password": bool(linked_user.get("must_change_password")) if linked_user else None,
        "default_password_active": bool(linked_user.get("default_password_active")) if linked_user else None,
        "credential_recovery_required": bool(linked_user.get("credential_recovery_required")) if linked_user else False,
        "role": _role_names(linked_user) if linked_user else "Field Agent",
        "account_status": linked_user.get("status") if linked_user else None,
        "resolved_by": str((discovery.get("provisioning_resolution") or {}).get("resolved_by") or "") or None,
        "resolved_at": (discovery.get("provisioning_resolution") or {}).get("resolved_at"),
    }


def _provisioning_context() -> dict:
    active_mappings = list(mappings().find({
        "source_system": SOURCE_SYSTEM, "mapping_type": {"$in": ["branch", "manager", "agent"]}, "active": True,
    }))
    branch_mappings = {canonical_branch_alias_key(row.get("external_id") or row.get("external_code") or row.get("external_display_name")): row for row in active_mappings if row.get("mapping_type") == "branch"}
    agent_mappings = {row["external_key"]: row for row in active_mappings if row.get("mapping_type") == "agent"}
    manager_mappings = {row["external_key"]: row for row in active_mappings if row.get("mapping_type") == "manager"}
    branch_rows = list(get_collection("branches").find({}))
    branches_by_id = {row["_id"]: row for row in branch_rows}
    user_ids = {
        value for value in [
            *(row.get("manager_id") for row in branch_rows),
            *(value for row in branch_rows for value in (row.get("manager_ids") or [])),
            *(row.get("fleetops_id") for row in manager_mappings.values()),
            *(row.get("fleetops_id") for row in agent_mappings.values()),
        ] if isinstance(value, ObjectId)
    }
    # All users are needed for exact source/contact collision detection. Names
    # are surfaced for confirmation only and are never auto-merged.
    user_rows = list(get_collection("users").find({}))
    return {
        "branch_mappings": branch_mappings, "manager_mappings": manager_mappings, "agent_mappings": agent_mappings,
        "branches_by_id": branches_by_id, "users_by_id": {row["_id"]: row for row in user_rows},
    }


def preview_agent_provisioning(actor_id: str) -> dict:
    _actor(actor_id)
    context = _provisioning_context()
    agents = [_provisioning_agent(row, context) for row in discoveries().find({
        "source_system": SOURCE_SYSTEM, "discovery_type": "agent",
    }).sort([("branch_name", ASCENDING), ("external_display_name", ASCENDING), ("external_key", ASCENDING)])]
    counts = Counter(item["status"] for item in agents)
    groups = defaultdict(list)
    for item in agents:
        groups[item.get("branch_name") or "Needs Review"].append(item)
    return {
        "counts": {key: counts.get(key, 0) for key in ("eligible", "existing", "needs_review", "ignored_inactive", "provisioned")},
        "groups": [{"branch_name": key, "agents": value} for key, value in groups.items()],
        "agents": agents,
    }


def _resolution_target(discovery_id: str) -> dict:
    discovery = discoveries().find_one({
        "_id": object_id(discovery_id, "discovery_id"),
        "source_system": SOURCE_SYSTEM, "discovery_type": "agent",
    })
    if not discovery:
        raise ApiError("SmartLiving agent discovery not found.", status_code=404)
    return discovery


def resolve_agent_provisioning(discovery_id: str, payload: dict, actor_id: str) -> dict:
    _actor(actor_id)
    discovery = _resolution_target(discovery_id)
    branch = _active_branch(payload.get("branch_id"))
    if not branch:
        raise ApiError("Select an active FleetOps branch.", status_code=400)
    manager = _branch_manager(branch, payload.get("manager_id"))
    if not manager:
        raise ApiError("Select an active Branch Manager assigned to the selected branch.", status_code=409)
    agent_id = str(discovery.get("external_id") or "").strip()
    agent_name = str(payload.get("agent_name") or discovery.get("external_display_name") or "").strip()
    if not agent_id:
        raise ApiError("A SmartLiving agent_id is required and cannot be repaired locally.", status_code=409)
    if not agent_name or agent_name.casefold() == agent_id.casefold():
        raise ApiError("Enter and confirm a readable agent name.", status_code=400)

    existing_user_id = payload.get("fleetops_user_id")
    if existing_user_id:
        target = object_id(existing_user_id, "fleetops_user_id")
        target_user = get_collection("users").find_one({"_id": target})
        if not target_user or target_user.get("primary_branch_id") != branch["_id"]:
            raise ApiError("The existing account must have the selected branch as its primary branch.", status_code=409)
        if str(target_user.get("status") or "").lower() != "active":
            raise ApiError("The existing account must be active.", status_code=409)
        current_source_id = str(target_user.get("smartliving_agent_id") or "").strip()
        if current_source_id and current_source_id.casefold() != agent_id.casefold():
            raise ApiError("The existing account is linked to another SmartLiving agent.", status_code=409)
        current = _agent_mapping(discovery["external_key"])
        if current and current.get("fleetops_id") != target:
            raise ApiError("This SmartLiving agent is already linked to another FleetOps user.", status_code=409)
        target_user = _ensure_source_role_link(
            target_user, "field_agent", branch, "smartliving_agent_id", agent_id, actor_id,
        )
        if not current:
            create_mapping("agent", {
                "external_id": agent_id, "external_display_name": agent_name, "fleetops_id": str(target),
            }, actor_id)

    timestamp = now_utc()
    resolution = {
        "agent_name": agent_name, "branch_id": branch["_id"], "manager_id": manager["_id"],
        "resolved_by": object_id(actor_id), "resolved_at": timestamp,
        "original_reason": (discovery.get("relationship") or {}).get("reason"),
    }
    relationship = {
        **(discovery.get("relationship") or {}), "status": "resolved", "reason": None,
        "agent_id": agent_id, "agent_display_name": agent_name,
        "fleetops_branch_id": str(branch["_id"]), "fleetops_branch_name": branch.get("name"),
    }
    discoveries().update_one({"_id": discovery["_id"]}, {"$set": {
        "external_display_name": agent_name, "display_name_status": "resolved",
        "provisioning_resolution": resolution, "relationship": relationship, "updated_at": timestamp,
    }})
    discovery.update({"external_display_name": agent_name, "provisioning_resolution": resolution, "relationship": relationship})
    classified = _provisioning_agent(discovery)
    write_audit("smartliving_agent_resolved", actor_id, "integration_discovery", discovery["_id"], {
        "new": {"agent_id": agent_id, "branch_id": str(branch["_id"]), "manager_id": str(manager["_id"]), "status": classified["status"]},
    })
    return classified


def _manager_discovery(discovery_id: str) -> dict:
    row = discoveries().find_one({
        "_id": object_id(discovery_id, "discovery_id"), "source_system": SOURCE_SYSTEM,
        "discovery_type": "manager",
    })
    if not row:
        raise ApiError("SmartLiving manager discovery not found.", status_code=404)
    return row


def _normalized_identity(value) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _normalized_phone(value) -> str:
    return "".join(re.findall(r"\d", str(value or "")))


def _manager_candidates(discovery: dict, users: list[dict]) -> tuple[list[dict], str | None]:
    source_id = str(discovery.get("external_id") or "").strip()
    mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "manager", "external_key": source_id.casefold(), "active": True}) if source_id else None
    if mapping:
        match = next((user for user in users if user.get("_id") == mapping.get("fleetops_id")), None)
        return ([match] if match else []), "source_mapping"
    agent_mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "agent", "external_key": source_id.casefold(), "active": True}) if source_id else None
    if agent_mapping:
        match = next((user for user in users if user.get("_id") == agent_mapping.get("fleetops_id")), None)
        return ([match] if match else []), "cross_role_source_mapping"
    stages = [
        ("source_id", lambda user: str(user.get("smartliving_manager_id") or "").strip().casefold() == source_id.casefold() if source_id else False),
        ("cross_role_source_id", lambda user: str(user.get("smartliving_agent_id") or "").strip().casefold() == source_id.casefold() if source_id else False),
        ("email", lambda user: _normalized_identity(user.get("email")) == _normalized_identity(discovery.get("email")) if discovery.get("email") else False),
        ("phone", lambda user: _normalized_phone(user.get("phone")) == _normalized_phone(discovery.get("phone")) if discovery.get("phone") else False),
        ("full_name", lambda user: _normalized_identity(user.get("full_name") or user.get("name")) == _normalized_identity(discovery.get("external_display_name")) if discovery.get("external_display_name") else False),
    ]
    for method, predicate in stages:
        matches = [user for user in users if predicate(user)]
        if matches:
            return matches, method
    return [], None


def _manager_item(discovery: dict, users: list[dict] | None = None) -> dict:
    users = users if users is not None else list(get_collection("users").find({}))
    raw_codes = discovery.get("review_codes")
    codes = [str(code) for code in raw_codes] if isinstance(raw_codes, list) else ([str(raw_codes)] if raw_codes else [])
    resolution = discovery.get("manager_provisioning_resolution") or {}
    source_id = str(discovery.get("external_id") or "").strip()
    source_name = str(discovery.get("external_display_name") or "").strip()
    manager_name = source_name if source_name and "CONFLICTING_MANAGER_NAME" not in codes else str(resolution.get("manager_name") or "").strip()
    if manager_name and manager_name.casefold() != source_id.casefold():
        codes = [code for code in codes if code not in {"MISSING_NAME", "CONFLICTING_MANAGER_NAME"}]
    else:
        manager_name = None
        codes.append("MISSING_NAME")

    source_branch = str(discovery.get("branch_name") or "").strip()
    source_branch_options = list(discovery.get("branch_keys")) if isinstance(discovery.get("branch_keys"), list) else []
    branch = _active_branch(resolution.get("branch_id"))
    if not branch:
        option_keys = list(dict.fromkeys(normalize_branch_key(value) for value in (source_branch_options or [source_branch]) if normalize_branch_key(value)))
        option_mappings = [_branch_mapping_by_key(key) for key in option_keys]
        mapped_branch_ids = {row.get("fleetops_id") for row in option_mappings if row}
        all_evidence_confirmed = bool(option_keys) and len(option_mappings) == len(option_keys) and all(option_mappings)
        if len(mapped_branch_ids) == 1 and ("BRANCH_CONFLICT" not in codes or all_evidence_confirmed):
            branch = _active_branch(next(iter(mapped_branch_ids)))
            if branch and all_evidence_confirmed:
                codes = [code for code in codes if code != "BRANCH_CONFLICT"]
    if branch:
        codes = [code for code in codes if code != "UNRESOLVED_BRANCH"]
        if resolution.get("branch_id"):
            codes = [code for code in codes if code != "BRANCH_CONFLICT"]
    if not branch:
        codes.append("UNRESOLVED_BRANCH")

    identity = {**discovery, "external_display_name": manager_name}
    identity_candidates, match_method = _manager_candidates(identity, users)
    if len(identity_candidates) > 1:
        codes.append("AMBIGUOUS_MANAGER")
    manager = identity_candidates[0] if len(identity_candidates) == 1 else None
    authoritative_cross_role = match_method in {"cross_role_source_mapping", "cross_role_source_id"}
    needs_branch_suggestions = not manager or ("branch_manager" not in user_role_codes(manager) and not authoritative_cross_role) or (
        branch and manager.get("primary_branch_id") not in (None, branch["_id"])
    )
    branch_candidates = [
        user for user in users
        if needs_branch_suggestions and branch and "branch_manager" in user_role_codes(user)
        and str(user.get("status") or "").lower() == "active"
        and branch["_id"] in {user.get("primary_branch_id"), *(user.get("allowed_branch_ids") or [])}
    ]
    candidates = list(identity_candidates)
    seen_candidate_ids = {user.get("_id") for user in candidates}
    candidates.extend(user for user in branch_candidates if user.get("_id") not in seen_candidate_ids)
    name_resolution_source = "smartliving" if manager_name else None
    if not manager_name and manager and match_method in {"source_mapping", "source_id", "cross_role_source_mapping", "cross_role_source_id", "email", "phone"}:
        authoritative_name = str(manager.get("full_name") or manager.get("username") or "").strip()
        if authoritative_name and authoritative_name.casefold() != source_id.casefold():
            manager_name = authoritative_name
            identity["external_display_name"] = manager_name
            codes = [code for code in codes if code not in {"MISSING_NAME", "CONFLICTING_MANAGER_NAME"}]
            name_resolution_source = f"fleetops_{match_method}"
    elif manager_name and resolution.get("manager_name") == manager_name:
        name_resolution_source = str(resolution.get("name_resolution_source") or "admin_confirmation")
    if manager:
        if "branch_manager" not in user_role_codes(manager) and not authoritative_cross_role: codes.append("DUPLICATE_ACCOUNT")
        if str(manager.get("status") or "").lower() != "active": codes.append("UNRESOLVED_MANAGER")
        if branch and manager.get("primary_branch_id") not in (None, branch["_id"]): codes.append("BRANCH_CONFLICT")
    linked_identity = bool(manager and match_method == "source_mapping" and "branch_manager" in user_role_codes(manager) and branch and manager.get("primary_branch_id") == branch["_id"])
    status = "needs_review" if codes else ("linked" if linked_identity else "ready_to_link" if manager else "ready_to_create")
    branch_names = {row["_id"]: row.get("name") for row in get_collection("branches").find({"_id": {"$in": [user.get("primary_branch_id") for user in candidates if user.get("primary_branch_id")]}})}
    return {
        "discovery_id": str(discovery["_id"]), "source_id": str(discovery.get("external_id") or "").strip() or None,
        "manager_name": manager_name, "email": str(discovery.get("email") or "").strip() or None, "phone": str(discovery.get("phone") or "").strip() or None,
        "source_branch": source_branch or None, "source_branch_options": source_branch_options, "branch_id": str(branch["_id"]) if branch else None,
        "branch_name": branch.get("name") if branch else None, "fleetops_user_id": str(manager["_id"]) if manager else None,
        "fleetops_user_name": (manager.get("full_name") or manager.get("username")) if manager else None,
        "fleetops_username": manager.get("username") if manager else None,
        "fleetops_roles": _role_names(manager) if manager else None,
        "fleetops_status": manager.get("status") if manager else None,
        "match_method": match_method, "account_status": "existing" if candidates else "missing",
        "name_resolution_source": name_resolution_source,
        "mapping_status": "linked" if match_method == "source_mapping" and manager else "unlinked", "status": status,
        "error_codes": list(dict.fromkeys(codes)),
        "candidate_ids": [str(user["_id"]) for user in candidates],
        "candidates": [{
            "id": str(user["_id"]), "name": user.get("full_name") or user.get("username") or "Name unavailable",
            "role": _role_names(user),
            "match_reason": match_method if user in identity_candidates else "branch_access",
            "username": user.get("username") or None,
            "branch_id": str(user.get("primary_branch_id")) if user.get("primary_branch_id") else None,
            "branch_name": branch_names.get(user.get("primary_branch_id")),
        } for user in candidates],
    }


def preview_manager_provisioning(actor_id: str) -> dict:
    _actor(actor_id)
    users = list(get_collection("users").find({}))
    items = [_manager_item(row, users) for row in discoveries().find({"source_system": SOURCE_SYSTEM, "discovery_type": "manager", "currently_observed": {"$ne": False}}).sort("branch_name", ASCENDING)]
    counts = Counter(item["status"] for item in items)
    branches = [{"id": str(row["_id"]), "name": row.get("name") or "Unresolved branch"} for row in get_collection("branches").find({"$or": [{"status": "active"}, {"status": {"$exists": False}, "active": {"$ne": False}}]}).sort("name", ASCENDING)]
    return {
        "contract_version": 1,
        "counts": {key: int(counts.get(key, 0)) for key in ("linked", "ready_to_link", "ready_to_create", "needs_review")},
        "managers": items,
        "branches": branches,
        "contract_errors": [],
    }


def _reevaluate_branch_agents(branch: dict, source_branch: str, actor_id: str) -> dict:
    key = normalize_branch_key(source_branch)
    rows = list(discoveries().find({"source_system": SOURCE_SYSTEM, "discovery_type": "agent"}))
    affected = [row for row in rows if normalize_branch_key((row.get("relationship") or {}).get("external_branch") or row.get("branch_name")) == key]
    before = Counter(_provisioning_agent(row)["status"] for row in affected)
    timestamp = now_utc()
    for row in affected:
        relationship = dict(row.get("relationship") or {})
        relationship.update({"fleetops_branch_id": str(branch["_id"]), "fleetops_branch_name": branch.get("name")})
        discoveries().update_one({"_id": row["_id"]}, {"$set": {"relationship": relationship, "updated_at": timestamp}})
    refreshed = [discoveries().find_one({"_id": row["_id"]}) for row in affected]
    after = Counter(_provisioning_agent(row)["status"] for row in refreshed)
    result = {"affected": len(affected), "before": dict(before), "after": dict(after)}
    write_audit("smartliving_manager_reevaluated", actor_id, "branch", branch["_id"], {"new": result})
    return result


def _linked_manager_item(discovery: dict, user: dict, branch: dict, manager_name: str) -> dict:
    source_id = str(discovery.get("external_id") or "").strip() or None
    return {
        "discovery_id": str(discovery["_id"]), "source_id": source_id, "manager_name": manager_name,
        "email": str(discovery.get("email") or "").strip() or None, "phone": str(discovery.get("phone") or "").strip() or None,
        "source_branch": str(discovery.get("branch_name") or "").strip() or None,
        "source_branch_options": list(discovery.get("branch_keys")) if isinstance(discovery.get("branch_keys"), list) else [],
        "branch_id": str(branch["_id"]), "branch_name": branch.get("name") or None,
        "fleetops_user_id": str(user["_id"]), "fleetops_user_name": user.get("full_name") or user.get("username") or manager_name,
        "fleetops_username": user.get("username") or None, "fleetops_roles": _role_names(user),
        "fleetops_status": user.get("status") or None,
        "match_method": "source_mapping", "name_resolution_source": "fleetops_link",
        "account_status": "existing", "mapping_status": "linked", "status": "linked", "error_codes": [],
        "candidate_ids": [str(user["_id"])], "candidates": [{
            "id": str(user["_id"]), "name": user.get("full_name") or user.get("username") or manager_name,
            "role": "Branch Manager",
            "username": user.get("username") or None, "branch_id": str(branch["_id"]), "branch_name": branch.get("name") or None,
        }],
    }


def _reconcile_branch_manager_reference(branch: dict, user: dict, timestamp) -> None:
    """Keep the legacy singular manager reference aligned without guessing identities.

    Active branches may intentionally have multiple managers through ``manager_ids``.
    The singular ``manager_id`` is only replaced automatically when it is empty,
    already points at this user, or points at an inactive account that has already
    been retired. An active different person is never inferred to be a duplicate.
    """
    branches = get_collection("branches")
    incumbent_id = branch.get("manager_id")
    replace_incumbent = incumbent_id in (None, user["_id"])
    if incumbent_id and incumbent_id != user["_id"]:
        incumbent = get_collection("users").find_one({"_id": incumbent_id}, {"status": 1, "active": 1})
        incumbent_status = str(
            (incumbent or {}).get("status")
            or ("active" if (incumbent or {}).get("active", True) else "inactive")
        ).lower()
        replace_incumbent = not incumbent or incumbent_status != "active"

    updates = {"updated_at": timestamp}
    if replace_incumbent:
        updates.update({"manager_id": user["_id"], "manager_name": user.get("full_name") or user.get("username")})
    branches.update_one(
        {"_id": branch["_id"]},
        {"$set": updates, "$addToSet": {"manager_ids": user["_id"]}},
    )
    if replace_incumbent and incumbent_id and incumbent_id != user["_id"]:
        branches.update_one({"_id": branch["_id"]}, {"$pull": {"manager_ids": incumbent_id}})


def _link_manager(discovery: dict, user: dict, branch: dict, actor_id: str, action: str, *, reevaluate_agents=True, recompute_result=True, manager_name=None) -> dict:
    source_id = str(discovery.get("external_id") or "").strip()
    if not source_id: _coded_error("UNRESOLVED_MANAGER", "A SmartLiving manager source ID is required.")
    if str(user.get("status") or "").lower() != "active": _coded_error("UNRESOLVED_MANAGER", "The selected account is inactive.")
    if user.get("primary_branch_id") not in (None, branch["_id"]): _coded_error("BRANCH_CONFLICT", "The selected manager already belongs to another primary branch.")
    current_source_id = str(user.get("smartliving_manager_id") or "").strip()
    if current_source_id and current_source_id.casefold() != source_id.casefold(): _coded_error("DUPLICATE_ACCOUNT", "The account is linked to a different SmartLiving manager.")
    mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "manager", "external_key": source_id.casefold()})
    if mapping and mapping.get("fleetops_id") != user["_id"]: _coded_error("DUPLICATE_ACCOUNT", "The SmartLiving manager is already linked to another account.")
    manager_name = str(manager_name or discovery.get("external_display_name") or (discovery.get("manager_provisioning_resolution") or {}).get("manager_name") or user.get("full_name") or user.get("username") or "").strip()
    if not manager_name or manager_name.casefold() == source_id.casefold(): _coded_error("MISSING_NAME", "A readable manager name is required.")
    user = _ensure_source_role_link(
        user, "branch_manager", branch, "smartliving_manager_id", source_id, actor_id,
    )
    if not mapping:
        try:
            create_mapping("manager", {"external_id": source_id, "external_display_name": manager_name, "fleetops_id": str(user["_id"])}, actor_id)
        except ApiError as error:
            mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "manager", "external_key": source_id.casefold()})
            if error.status_code != 409 or not mapping or mapping.get("fleetops_id") != user["_id"]: raise
    timestamp = now_utc()
    _reconcile_branch_manager_reference(branch, user, timestamp)
    resolution = dict(discovery.get("manager_provisioning_resolution") or {})
    resolution.update({"manager_name": manager_name, "fleetops_user_id": user["_id"], "name_resolution_source": "fleetops_link", "resolved_by": object_id(actor_id), "resolved_at": timestamp})
    discoveries().update_one({"_id": discovery["_id"]}, {"$set": {"manager_provisioning_resolution": resolution, "updated_at": timestamp}})
    reevaluation = _reevaluate_branch_agents(branch, discovery.get("branch_name"), actor_id) if reevaluate_agents else None
    write_audit(action, actor_id, "user", user["_id"], {"new": {"source_id": source_id, "branch_id": str(branch["_id"])}})
    manager_result = _manager_item(discoveries().find_one({"_id": discovery["_id"]})) if recompute_result else _linked_manager_item(discovery, user, branch, manager_name)
    return {"manager": manager_result, "agent_reevaluation": reevaluation}


def match_manager_provisioning(discovery_id: str, payload: dict, actor_id: str) -> dict:
    _actor(actor_id); discovery = _manager_discovery(discovery_id)
    resolution = dict(discovery.get("manager_provisioning_resolution") or {})
    manager_name = str(payload.get("manager_name") or "").strip()
    if manager_name:
        if len(manager_name) > 160 or manager_name.casefold() == str(discovery.get("external_id") or "").strip().casefold():
            _coded_error("MISSING_NAME", "Enter and confirm a readable manager name.", 400)
        resolution["manager_name"] = manager_name
        resolution["name_resolution_source"] = "admin_confirmation"
    if payload.get("branch_id"):
        branch = _active_branch(payload.get("branch_id"))
        if not branch:
            _coded_error("UNRESOLVED_BRANCH", "Select an active FleetOps branch.", 400)
        resolution["branch_id"] = branch["_id"]
        source_branch = str(discovery.get("branch_name") or "").strip()
        branch_key = normalize_branch_key(source_branch)
        if branch_key and len(discovery.get("branch_keys") or [branch_key]) == 1:
            existing = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "branch", "external_key": branch_key})
            if existing and (existing.get("fleetops_id") != branch["_id"] or not existing.get("active", True)):
                update_mapping("branch", str(existing["_id"]), {"fleetops_id": str(branch["_id"]), "active": True}, actor_id)
            elif not existing:
                create_mapping("branch", {"external_code": source_branch, "external_display_name": source_branch, "fleetops_id": str(branch["_id"])}, actor_id)
    if manager_name or payload.get("branch_id"):
        resolution.update({"resolved_by": object_id(actor_id), "resolved_at": now_utc()})
        discoveries().update_one({"_id": discovery["_id"]}, {"$set": {"manager_provisioning_resolution": resolution, "updated_at": now_utc()}})
        discovery = _manager_discovery(discovery_id)
    item = _manager_item(discovery)
    if payload.get("resolve_only") is True:
        write_audit("smartliving_manager_reevaluated", actor_id, "integration_discovery", discovery["_id"], {"new": {"status": item["status"], "error_codes": item["error_codes"]}})
        return {"manager": item, "agent_reevaluation": None}
    if item.get("status") == "linked":
        return {"manager": item, "agent_reevaluation": None}
    if not item.get("branch_id"): _coded_error("UNRESOLVED_BRANCH", "Map this SmartLiving branch before matching its manager.")
    user_id = payload.get("fleetops_user_id") or (item.get("fleetops_user_id") if item.get("status") == "ready_to_link" else None)
    if not user_id: _coded_error("AMBIGUOUS_MANAGER", "Select one confirmed FleetOps Branch Manager.")
    if "MISSING_NAME" in item.get("error_codes", []) and not manager_name:
        _coded_error("MISSING_NAME", "Confirm the manager's readable name before linking a branch-access candidate.", 400)
    user = get_collection("users").find_one({"_id": object_id(user_id, "fleetops_user_id")})
    branch = _active_branch(item["branch_id"])
    return _link_manager(discovery, user or {}, branch, actor_id, "smartliving_manager_matched")


def create_manager_provisioning(discovery_id: str, payload: dict, actor_id: str) -> dict:
    _actor(actor_id); discovery = _manager_discovery(discovery_id)
    if payload.get("approved") is not True: _coded_error("MANAGER_NOT_APPROVED", "Manager creation requires explicit approval.", 400)
    source_id = str(discovery.get("external_id") or "").strip()
    if not source_id: _coded_error("UNRESOLVED_MANAGER", "A SmartLiving manager source ID is required.")
    raw_codes = discovery.get("review_codes")
    codes = [str(code) for code in raw_codes] if isinstance(raw_codes, list) else ([str(raw_codes)] if raw_codes else [])
    resolution = discovery.get("manager_provisioning_resolution") or {}
    source_name = str(discovery.get("external_display_name") or "").strip()
    name = source_name if source_name and "CONFLICTING_MANAGER_NAME" not in codes else str(resolution.get("manager_name") or "").strip()

    manager_mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "manager", "external_key": source_id.casefold(), "active": True})
    existing = get_collection("users").find_one({"_id": manager_mapping.get("fleetops_id")}) if manager_mapping else None
    if not existing:
        existing = get_collection("users").find_one({"smartliving_manager_id": source_id})
    if not existing:
        agent_mapping = mappings().find_one({"source_system": SOURCE_SYSTEM, "mapping_type": "agent", "external_key": source_id.casefold(), "active": True})
        existing = get_collection("users").find_one({"_id": agent_mapping.get("fleetops_id")}) if agent_mapping else None
    if not existing:
        existing = get_collection("users").find_one({"smartliving_agent_id": source_id})
    if existing and (not name or name.casefold() == source_id.casefold()):
        name = str(existing.get("full_name") or existing.get("username") or "").strip()
    if name and name.casefold() != source_id.casefold():
        codes = [code for code in codes if code not in {"MISSING_NAME", "CONFLICTING_MANAGER_NAME"}]
    else:
        _coded_error("MISSING_NAME", "Confirm a readable manager name before creating an account.")

    source_branch = str(discovery.get("branch_name") or "").strip()
    branch_key = normalize_branch_key(source_branch)
    branch_mapping = _branch_mapping_by_key(branch_key) if branch_key and "BRANCH_CONFLICT" not in codes else None
    branch = _active_branch((branch_mapping or {}).get("fleetops_id")) or _active_branch(resolution.get("branch_id"))
    if branch:
        codes = [code for code in codes if code != "UNRESOLVED_BRANCH"]
        if resolution.get("branch_id"): codes = [code for code in codes if code != "BRANCH_CONFLICT"]
    else:
        _coded_error("UNRESOLVED_BRANCH", "Confirm an active branch before creating an account.")
    if codes: _coded_error(codes[0], "Resolve the manager source data before creating an account.")

    if existing:
        return _link_manager(discovery, existing, branch, actor_id, "smartliving_manager_provisioned", reevaluate_agents=False, recompute_result=False, manager_name=name)

    username = _username_stem(name)
    identity_filters = [{"username": username}, {"full_name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}]
    email = str(discovery.get("email") or "").strip().casefold()
    phone = str(discovery.get("phone") or "").strip()
    if email: identity_filters.append({"email": email})
    if phone: identity_filters.append({"phone": phone})
    if get_collection("users").find_one({"$or": identity_filters}):
        _coded_error("DUPLICATE_ACCOUNT", "An exact existing account was found. Review it and use Link Existing.")
    password = _temporary_password()
    try:
        created = create_user({"full_name": name, "username": username, "email": discovery.get("email"), "phone": discovery.get("phone"), "password": password, "status": "active", "role": "branch_manager", "role_ids": ["branch_manager"], "primary_branch_id": str(branch["_id"]), "allowed_branch_ids": [str(branch["_id"])], "created_by": actor_id, "temporary_password": True}, "branch_manager", allow_missing_phone=True, trusted_fields={"smartliving_manager_id": source_id, "provisioning_source": SOURCE_SYSTEM, "default_password_active": True, "default_password_issued_at": now_utc()})
        user = get_collection("users").find_one({"_id": ObjectId(created["id"])})
    except (DuplicateKeyError, ApiError):
        user = get_collection("users").find_one({"smartliving_manager_id": source_id})
        if not user: raise
    return _link_manager(discovery, user, branch, actor_id, "smartliving_manager_provisioned", reevaluate_agents=False, recompute_result=False, manager_name=name)


def reevaluate_manager_branch(discovery_id: str, actor_id: str) -> dict:
    _actor(actor_id); discovery = _manager_discovery(discovery_id); item = _manager_item(discovery)
    branch = _active_branch(item.get("branch_id"))
    if not branch: _coded_error("UNRESOLVED_BRANCH", "Map this SmartLiving branch before re-evaluating agents.")
    return {"manager": item, "agent_reevaluation": _reevaluate_branch_agents(branch, discovery.get("branch_name"), actor_id)}


def backfill_provisioning_mappings(payload: dict, actor_id: str) -> dict:
    """Collision-aware backfill. Dry-run is the default and uncertain records are never deleted."""
    _actor(actor_id); apply_changes = payload.get("apply") is True
    branch_rows = list(mappings().find({"source_system": SOURCE_SYSTEM, "mapping_type": "branch"}))
    grouped = defaultdict(list)
    for row in branch_rows:
        grouped[normalize_branch_key(row.get("external_id") or row.get("external_code") or row.get("external_display_name"))].append(row)
    normalized = conflicts = manager_links = skipped = confirmed_branch_aliases = 0
    for key, rows in grouped.items():
        if not key or len(rows) != 1:
            conflicts += len(rows); continue
        row = rows[0]
        if row.get("external_key") != key:
            normalized += 1
            if apply_changes:
                mappings().update_one({"_id": row["_id"]}, {"$set": {"external_key": key, "updated_at": now_utc(), "updated_by": object_id(actor_id)}})
    for mapping in mappings().find({"source_system": SOURCE_SYSTEM, "mapping_type": "manager", "active": True}):
        user = get_collection("users").find_one({"_id": mapping.get("fleetops_id")})
        source_id = str(mapping.get("external_id") or mapping.get("external_code") or "").strip()
        if not user or not source_id or "branch_manager" not in user_role_codes(user): skipped += 1; continue
        current = str(user.get("smartliving_manager_id") or "").strip()
        if current and current.casefold() != source_id.casefold(): conflicts += 1; continue
        if not current:
            manager_links += 1
            if apply_changes:
                get_collection("users").update_one({"_id": user["_id"], "smartliving_manager_id": {"$in": [None, ""]}}, {"$set": {"smartliving_manager_id": source_id, "updated_at": now_utc()}})
    for discovery in discoveries().find({
        "source_system": SOURCE_SYSTEM, "discovery_type": "manager",
        "manager_provisioning_resolution.branch_id": {"$exists": True},
    }):
        resolution = discovery.get("manager_provisioning_resolution") or {}
        branch = _active_branch(resolution.get("branch_id"))
        if not branch:
            skipped += 1
            continue
        for source_alias in discovery.get("branch_keys") or []:
            alias_key = normalize_branch_key(source_alias)
            if not alias_key:
                continue
            existing = mappings().find_one({
                "source_system": SOURCE_SYSTEM, "mapping_type": "branch", "external_key": alias_key,
            })
            if existing:
                if existing.get("fleetops_id") != branch["_id"]:
                    conflicts += 1
                continue
            confirmed_branch_aliases += 1
            if apply_changes:
                create_mapping("branch", {
                    "external_code": source_alias, "external_display_name": source_alias,
                    "fleetops_id": str(branch["_id"]),
                }, actor_id)
    result = {
        "dry_run": not apply_changes, "branch_keys_normalized": normalized,
        "confirmed_branch_aliases_created": confirmed_branch_aliases,
        "manager_source_ids_linked": manager_links, "conflicts": conflicts, "skipped": skipped,
    }
    if apply_changes:
        write_audit("smartliving_mapping_backfilled", actor_id, "integration_mapping", None, {"new": result})
    return result


def _username_stem(full_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode("ascii").lower()
    parts = [part for part in re.split(r"[^a-z0-9]+", ascii_name) if part]
    if not parts:
        return "field.agent"
    return parts[0] if len(parts) == 1 else f"{parts[0]}.{parts[-1]}"


def _provisioning_username(full_name: str, source_id: str, source_field="smartliving_agent_id") -> str:
    stem = _username_stem(full_name)
    existing = get_collection("users").find_one(
        {"username": {"$regex": f"^{re.escape(stem)}$", "$options": "i"}}, {source_field: 1},
    )
    if not existing or existing.get(source_field) == source_id:
        return stem
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
    for length in (8, 12, 16, 24, 32, 64):
        candidate = f"{stem}.{digest[:length]}"
        existing = get_collection("users").find_one(
            {"username": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}}, {source_field: 1},
        )
        if not existing or existing.get(source_field) == source_id:
            return candidate
    raise ApiError("Unable to allocate a unique username for this agent.", status_code=409)


def _provision_one(discovery: dict, actor_id: str, context: dict | None = None,
                   username_override: str | None = None) -> tuple[str, dict]:
    classified = _provisioning_agent(discovery, context)
    if classified["status"] in {"existing", "provisioned"}:
        return "duplicate", classified
    if classified["status"] != "eligible":
        return "skipped", classified
    agent_id = classified["agent_id"]
    existing = get_collection("users").find_one({"smartliving_agent_id": agent_id})
    if not existing:
        manager_mapping = mappings().find_one({
            "source_system": SOURCE_SYSTEM, "mapping_type": "manager",
            "external_key": agent_id.casefold(), "active": True,
        })
        existing = get_collection("users").find_one({"_id": manager_mapping.get("fleetops_id")}) if manager_mapping else None
    if not existing:
        existing = get_collection("users").find_one({"smartliving_manager_id": agent_id})
    if not existing and classified.get("user_id"):
        existing = get_collection("users").find_one({"_id": ObjectId(classified["user_id"])})
    created_account = False
    temporary_password = None
    if existing:
        if existing.get("primary_branch_id") not in (None, ObjectId(classified["branch_id"])):
            classified.update(status="needs_review", reasons=["existing_identity_role_or_branch_conflict"])
            return "skipped", classified
        user = _ensure_source_role_link(
            existing, "field_agent", _active_branch(classified["branch_id"]),
            "smartliving_agent_id", agent_id, actor_id,
        )
        get_collection("users").update_one(
            {"_id": user["_id"]},
            {"$set": {"manager_id": ObjectId(classified["manager_id"]), "updated_at": now_utc()}},
        )
        user = get_collection("users").find_one({"_id": user["_id"]})
    else:
        username = username_override or _provisioning_username(classified["name"], agent_id)
        temporary_password = _agent_temporary_password()
        try:
            created = create_user({
                "full_name": classified["name"], "username": username,
                "password": temporary_password, "status": "active",
                "role": "field_agent", "role_ids": ["field_agent"],
                "primary_branch_id": classified["branch_id"], "allowed_branch_ids": [],
                "created_by": actor_id, "temporary_password": True,
            }, "field_agent", allow_missing_phone=True, trusted_fields={
                "smartliving_agent_id": agent_id, "manager_id": ObjectId(classified["manager_id"]),
                "provisioning_source": SOURCE_SYSTEM, "default_password_active": True,
                "default_password_issued_at": now_utc(),
            })
            user = get_collection("users").find_one({"_id": ObjectId(created["id"])})
            created_account = True
        except (DuplicateKeyError, ApiError):
            user = get_collection("users").find_one({"smartliving_agent_id": agent_id})
            if not user:
                raise

    mapping = _agent_mapping(discovery["external_key"])
    if mapping and mapping.get("fleetops_id") != user["_id"]:
        raise ApiError("SmartLiving agent mapping changed during provisioning; no link was overwritten.", status_code=409)
    if not mapping:
        try:
            created_mapping = create_mapping("agent", {
                "external_id": agent_id, "external_display_name": classified["name"], "fleetops_id": str(user["_id"]),
            }, actor_id)
            if created_account:
                mappings().update_one({"_id": ObjectId(created_mapping["id"])}, {"$set": {"provisioning_origin": SOURCE_SYSTEM}})
        except ApiError as error:
            mapping = _agent_mapping(discovery["external_key"])
            if error.status_code != 409 or not mapping or mapping.get("fleetops_id") != user["_id"]:
                raise
    refreshed = _provisioning_agent(discoveries().find_one({"_id": discovery["_id"]}))
    write_audit("smartliving_agent_provisioned" if created_account else "smartliving_agent_linked", actor_id, "user", user["_id"], {"new": {
        "agent_id": agent_id, "username": user.get("username"), "branch_id": classified["branch_id"],
        "manager_id": classified["manager_id"], "default_password_active": bool(user.get("default_password_active")),
    }})
    result = {
        **refreshed,
        "name": user.get("full_name") or classified["name"],
        "username": user.get("username"),
        "branch_name": classified["branch_name"],
        "manager_name": classified["manager_name"],
        "role": _role_names(user), "account_status": user.get("status"),
    }
    if created_account:
        # Returned exactly once. Only the hash is stored by create_user.
        result.update({"temporary_password": temporary_password, "credential_available_once": True})
    return ("created" if created_account else "linked"), result


def provision_agents(payload: dict, actor_id: str) -> dict:
    started_at = perf_counter()
    _actor(actor_id)
    requested = payload.get("discovery_ids") or []
    provision_all = bool(payload.get("all_eligible"))
    if not provision_all and (not isinstance(requested, list) or not requested):
        raise ApiError("Select at least one Eligible agent or choose all eligible.", status_code=400)
    query = {"source_system": SOURCE_SYSTEM, "discovery_type": "agent"}
    if not provision_all:
        if any(not ObjectId.is_valid(str(value)) for value in requested):
            raise ApiError("One or more discovery IDs are invalid.", status_code=400)
        query["_id"] = {"$in": [ObjectId(str(value)) for value in requested]}
    rows = list(discoveries().find(query))
    context = _provisioning_context()
    if provision_all:
        rows = [row for row in rows if _provisioning_agent(row, context)["status"] == "eligible"]
    preview_eligible = sum(_provisioning_agent(row, context)["status"] == "eligible" for row in rows)

    # Reserve usernames from the single preview snapshot before concurrent
    # writes. This keeps same-name agents unique without one database lookup
    # per candidate and still leaves the unique index as the final race guard.
    used_usernames = {
        str(user.get("username") or "").strip().casefold()
        for user in context.get("users_by_id", {}).values()
        if str(user.get("username") or "").strip()
    }
    username_overrides = {}
    for row in rows:
        classified = _provisioning_agent(row, context)
        if classified["status"] != "eligible" or classified.get("user_id"):
            continue
        stem = _username_stem(classified["name"])
        candidate = stem
        if candidate.casefold() in used_usernames:
            digest = hashlib.sha256(classified["agent_id"].encode("utf-8")).hexdigest()
            candidate = next((
                f"{stem}.{digest[:length]}" for length in (8, 12, 16, 24, 32, 64)
                if f"{stem}.{digest[:length]}".casefold() not in used_usernames
            ), None)
            if not candidate:
                raise ApiError("Unable to allocate a unique username for this agent.", status_code=409)
        used_usernames.add(candidate.casefold())
        username_overrides[row["_id"]] = candidate

    def process(row):
        try:
            outcome, item = _provision_one(
                row, actor_id, context, username_overrides.get(row["_id"]),
            )
        except Exception as error:
            LOGGER.exception("SmartLiving agent provisioning failed discovery_id=%s", row.get("_id"))
            outcome = "failed"
            item = {
                "discovery_id": str(row.get("_id")),
                "agent_id": str(row.get("external_id") or "") or None,
                "name": row.get("external_display_name"),
                "status": "failed", "reasons": ["provisioning_failed"],
                "error_codes": ["PROVISIONING_FAILED"],
                "message": error.message if isinstance(error, ApiError) else "Provisioning failed safely; no password was exposed.",
            }
        return outcome, item

    app = current_app._get_current_object() if has_app_context() else None
    def process_with_context(row):
        if app is None:
            return process(row)
        with app.app_context():
            return process(row)

    max_workers = min(6, len(rows))
    processed = []
    if max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            processed = list(pool.map(process_with_context, rows))
    else:
        processed = [process_with_context(row) for row in rows]

    results = []; counts = Counter()
    for outcome, item in processed:
        counts[outcome] += 1; results.append({"outcome": outcome, **item})
    return {
        "preview_eligible": preview_eligible, "selected": len(rows),
        "created": counts["created"], "linked": counts["linked"],
        "skipped": counts["skipped"] + counts["duplicate"], "failed": counts["failed"],
        # Backward-compatible counters for existing clients.
        "provisioned": counts["created"] + counts["linked"],
        "duplicate": counts["duplicate"], "rejected": counts["skipped"],
        "results": results, "duration_ms": round((perf_counter() - started_at) * 1000, 1),
    }


def reissue_pending_agent_credentials(payload: dict, actor_id: str) -> dict:
    """Replace credentials lost with an interrupted provisioning response.

    Only never-used, first-login SmartLiving accounts are eligible. This does
    not retrieve a stored password; it invalidates the old hash and returns a
    newly generated password once.
    """
    actor = _actor(actor_id)
    requested = payload.get("user_ids") or []
    if not isinstance(requested, list) or not requested or any(not ObjectId.is_valid(str(value)) for value in requested):
        raise ApiError("Select at least one pending SmartLiving Field Agent account.", status_code=400)
    if len(requested) > 10:
        raise ApiError("Reissue credentials in batches of 10 or fewer accounts.", status_code=400)
    ids = [ObjectId(str(value)) for value in requested]
    query = {
        "_id": {"$in": ids}, "provisioning_source": SOURCE_SYSTEM,
        "status": "active", "last_login": None,
        "must_change_password": True, "default_password_active": True,
        "credential_recovery_required": True,
        "smartliving_agent_id": {"$type": "string"},
        "$or": [{"role": "field_agent"}, {"role_ids": "field_agent"}],
    }
    users = list(get_collection("users").find(query))
    eligible_ids = {user["_id"] for user in users}
    branches = {row["_id"]: row for row in get_collection("branches").find({
        "_id": {"$in": list({user.get("primary_branch_id") for user in users if user.get("primary_branch_id")})},
    })}
    manager_ids = {user.get("manager_id") for user in users if user.get("manager_id")}
    managers = {row["_id"]: row for row in get_collection("users").find({"_id": {"$in": list(manager_ids)}})}
    actor_role = str(actor.get("selected_workspace") or actor.get("role") or "admin")
    def reissue(user):
        password = _agent_temporary_password()
        reset_user_password_as(actor_id, actor_role, str(user["_id"]), password)
        get_collection("users").update_one({"_id": user["_id"]}, {"$set": {
            "default_password_active": True, "default_password_issued_at": now_utc(),
        }, "$unset": {"credential_recovery_required": ""}})
        branch = branches.get(user.get("primary_branch_id")) or {}
        manager = managers.get(user.get("manager_id")) or {}
        return {
            "user_id": str(user["_id"]), "name": user.get("full_name"), "username": user.get("username"),
            "branch_name": branch.get("name"), "manager_name": manager.get("full_name") or manager.get("username"),
            "role": "Field Agent", "account_status": "active", "temporary_password": password,
            "credential_available_once": True,
        }
    app = current_app._get_current_object() if has_app_context() else None
    def reissue_with_context(user):
        if app is None:
            return reissue(user)
        with app.app_context():
            return reissue(user)
    if len(users) > 1:
        with ThreadPoolExecutor(max_workers=min(6, len(users))) as pool:
            credentials = list(pool.map(reissue_with_context, users))
    else:
        credentials = [reissue_with_context(user) for user in users]
    result = {"requested": len(ids), "reissued": len(credentials), "skipped": len(ids) - len(eligible_ids), "credentials": credentials}
    write_audit("smartliving_agent_credentials_reissued", actor_id, "user", None, {
        "new": {"reissued_user_ids": [item["user_id"] for item in credentials], "skipped": result["skipped"]},
    })
    return result


def mapping_options(actor_id: str) -> dict:
    _actor(actor_id)
    branches = [
        {"id": str(row["_id"]), "name": row.get("name"), "code": row.get("code"),
         "manager_id": str(row.get("manager_id")) if row.get("manager_id") else None}
        for row in get_collection("branches").find({"$or": [{"status": "active"}, {"status": {"$exists": False}, "active": {"$ne": False}}]}).sort("name", ASCENDING)
    ]
    agents = []
    selectable_agent_roles = set(AGENT_ROLE_CODES) | {"branch_manager"}
    for row in get_collection("users").find({"status": "active", "$or": [{"role": {"$in": list(selectable_agent_roles)}}, {"role_ids": {"$in": list(selectable_agent_roles)}}]}).sort("full_name", ASCENDING):
        agents.append({
            "id": str(row["_id"]), "name": row.get("full_name") or row.get("name") or row.get("email"),
            "primary_branch_id": str(row.get("primary_branch_id")) if row.get("primary_branch_id") else None,
        })
    managers = []
    for row in get_collection("users").find({"status": "active", "$or": [{"role": "branch_manager"}, {"role_ids": "branch_manager"}]}).sort("full_name", ASCENDING):
        managers.append({
            "id": str(row["_id"]), "name": row.get("full_name") or row.get("username"),
            "primary_branch_id": str(row.get("primary_branch_id")) if row.get("primary_branch_id") else None,
        })
    return {"branches": branches, "agents": agents, "managers": managers}


def list_history(actor_id: str) -> dict:
    _actor(actor_id)
    rows = get_collection("audit_logs").find({"action": {"$in": sorted(INTEGRATION_AUDIT_ACTIONS)}}).sort("created_at", DESCENDING).limit(100)
    return {"events": [serialize_integration_record(row) for row in rows]}
