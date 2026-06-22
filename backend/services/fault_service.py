from datetime import datetime, timezone
from time import perf_counter

from bson import ObjectId
from flask import current_app
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.fault import serialize_fault
from models.fault_catalog import serialize_fault_category, serialize_fault_component
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.assignment_service import get_active_assignment_for_driver
from services.notification_service import notify_roles
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import build_cache_key, get_ttl_cached, log_db_duration, set_ttl_cached


ALLOWED_FAULT_SEVERITIES = {"low", "medium", "high", "critical"}
ALLOWED_FAULT_STATUSES = {
    "reported",
    "under_review",
    "approved",
    "rejected",
    "converted_to_maintenance",
    "resolved",
}
FAULT_APPROVAL_QUEUE_STATUSES = {
    "reported",
    "under_review",
    "approved",
    "rejected",
    "converted_to_maintenance",
    "resolved",
}
ACTIVE_STATUS = "active"
INACTIVE_STATUS = "inactive"
FAULT_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}
FAULT_LIST_PROJECTION = {
    "vehicle_id": 1,
    "driver_id": 1,
    "category_id": 1,
    "component_id": 1,
    "severity": 1,
    "description": 1,
    "photos": 1,
    "status": 1,
    "admin_notes": 1,
    "owner_notes": 1,
    "resolution_notes": 1,
    "maintenance_job_id": 1,
    "reported_at": 1,
    "reviewed_by": 1,
    "reviewed_at": 1,
    "approved_at": 1,
    "rejected_at": 1,
    "rejection_reason": 1,
    "requested_info_at": 1,
    "request_info_note": 1,
    "converted_to_maintenance_by": 1,
    "converted_to_maintenance_at": 1,
    "resolved_at": 1,
    "created_by": 1,
    "updated_by": 1,
    "approved_by": 1,
    "rejected_by": 1,
    "requested_info_by": 1,
    "converted_by": 1,
    "created_at": 1,
    "updated_at": 1,
}

DEFAULT_FAULT_CATALOG = {
    "engine": {
        "name": "Engine",
        "components": [
            "Overheating",
            "Oil Leak",
            "Injector",
            "Spark Plug",
            "Timing Belt",
            "Engine Noise",
            "Smoke",
            "Other",
        ],
    },
    "electrical": {
        "name": "Electrical",
        "components": [
            "Battery",
            "Alternator",
            "Starter",
            "Relay",
            "Fuse",
            "Horn",
            "Headlight",
            "Tail Light",
            "Dashboard",
            "Wiring",
            "Other",
        ],
    },
    "transmission": {
        "name": "Transmission",
        "components": [
            "Gearbox",
            "Clutch",
            "Torque Converter",
            "Drive Shaft",
            "Transmission Fluid",
            "Other",
        ],
    },
    "suspension": {
        "name": "Suspension",
        "components": [
            "Shock Absorber",
            "Control Arm",
            "Ball Joint",
            "Steering Rack",
            "Bushings",
            "Other",
        ],
    },
    "brakes": {
        "name": "Brakes",
        "components": [
            "Brake Pads",
            "Brake Disc",
            "Brake Fluid",
            "Hand Brake",
            "ABS",
            "Other",
        ],
    },
    "tyres": {
        "name": "Tyres",
        "components": [
            "Puncture",
            "Tyre Wear",
            "Low Pressure",
            "Alignment",
            "Balancing",
            "Rim Damage",
            "Other",
        ],
    },
    "cooling_system": {
        "name": "Cooling System",
        "components": [
            "Radiator",
            "Water Pump",
            "Thermostat",
            "Fan",
            "Coolant Leak",
            "Other",
        ],
    },
    "fuel_system": {
        "name": "Fuel System",
        "components": [
            "Fuel Pump",
            "Fuel Filter",
            "Fuel Leak",
            "Injector",
            "Fuel Tank",
            "Other",
        ],
    },
    "body": {
        "name": "Body",
        "components": [
            "Door",
            "Bumper",
            "Windshield",
            "Mirror",
            "Paint",
            "Other",
        ],
    },
    "interior": {
        "name": "Interior",
        "components": [
            "Seat",
            "Air Conditioning",
            "Dashboard",
            "Seat Belt",
            "Window Switch",
            "Other",
        ],
    },
    "other": {
        "name": "Other",
        "components": [
            "Other",
        ],
    },
}


def now_utc():
    return datetime.now(timezone.utc)


def faults_collection():
    return get_collection("faults")


def fault_categories_collection():
    return get_collection("fault_categories")


def fault_components_collection():
    return get_collection("fault_components")


def maintenance_jobs_collection():
    return get_collection("maintenance_jobs")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def ensure_fault_indexes():
    ensure_indexes_for_collection(
        faults_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("category_id", ASCENDING)]},
            {"keys": [("component_id", ASCENDING)]},
            {"keys": [("severity", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("reported_at", DESCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("created_by", ASCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("status", ASCENDING)]},
        ],
        collection_name="faults",
    )
    ensure_indexes_for_collection(
        fault_categories_collection(),
        [
            {"keys": [("code", ASCENDING)], "options": {"unique": True}},
            {"keys": [("status", ASCENDING)]},
        ],
        collection_name="fault_categories",
    )
    ensure_indexes_for_collection(
        fault_components_collection(),
        [
            {"keys": [("category_id", ASCENDING)]},
            {"keys": [("code", ASCENDING)]},
            {"keys": [("category_id", ASCENDING), ("name", ASCENDING)], "options": {"unique": True}},
        ],
        collection_name="fault_components",
    )
    ensure_indexes_for_collection(
        maintenance_jobs_collection(),
        [
            {"keys": [("fault_id", ASCENDING)], "options": {"unique": True}},
        ],
        collection_name="maintenance_jobs_fault_link",
    )


def seed_default_fault_catalog():
    timestamp = now_utc()
    for category_code, config in DEFAULT_FAULT_CATALOG.items():
        category_document = fault_categories_collection().find_one({"code": category_code})
        if not category_document:
            category_result = fault_categories_collection().insert_one(
                {
                    "name": config["name"],
                    "code": category_code,
                    "status": ACTIVE_STATUS,
                    "created_by": None,
                    "updated_by": None,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            )
            category_document = fault_categories_collection().find_one({"_id": category_result.inserted_id})

        for component_name in config["components"]:
            component_code = _slugify(component_name)
            if not fault_components_collection().find_one(
                {"category_id": category_document["_id"], "name": component_name}
            ):
                fault_components_collection().insert_one(
                    {
                        "category_id": category_document["_id"],
                        "name": component_name,
                        "code": component_code,
                        "status": ACTIVE_STATUS,
                        "created_by": None,
                        "updated_by": None,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    }
                )


def _slugify(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("&", "and")
        .replace("/", " ")
        .replace("-", " ")
        .replace("  ", " ")
        .replace(" ", "_")
    )


def _to_object_id(value, field_name: str, required: bool = True):
    if value is None or value == "":
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _validate_severity(value: str | None):
    severity = (value or "").strip().lower()
    if severity not in ALLOWED_FAULT_SEVERITIES:
        raise ApiError("severity must be one of: low, medium, high, critical.", status_code=400)
    return severity


def _get_user_document(user_id: str | ObjectId, field_name: str = "user_id"):
    user_object_id = _to_object_id(user_id, field_name)
    user = users_collection().find_one({"_id": user_object_id})
    if not user:
        raise ApiError("User not found.", status_code=404)
    return user


def _get_vehicle_document(vehicle_id: str | ObjectId):
    vehicle_object_id = _to_object_id(vehicle_id, "vehicle_id")
    vehicle = vehicles_collection().find_one({"_id": vehicle_object_id})
    if not vehicle:
        raise ApiError("Vehicle not found.", status_code=404)
    return vehicle


def _get_fault_document(fault_id: str | ObjectId):
    fault_object_id = _to_object_id(fault_id, "fault_id")
    fault_document = faults_collection().find_one({"_id": fault_object_id})
    if not fault_document:
        raise ApiError("Fault not found.", status_code=404)
    return fault_document


def _get_category_document(category_id: str | ObjectId):
    category_object_id = _to_object_id(category_id, "category_id")
    category_document = fault_categories_collection().find_one({"_id": category_object_id})
    if not category_document:
        raise ApiError("Fault category not found.", status_code=404)
    return category_document


def _get_component_document(component_id: str | ObjectId):
    component_object_id = _to_object_id(component_id, "component_id")
    component_document = fault_components_collection().find_one({"_id": component_object_id})
    if not component_document:
        raise ApiError("Fault component not found.", status_code=404)
    return component_document


def _ensure_category_component_match(category_document: dict, component_document: dict):
    if component_document.get("category_id") != category_document.get("_id"):
        raise ApiError("Selected component does not belong to the selected category.", status_code=400)


def _validate_driver_fault_scope(current_user_id: str, vehicle_id: str | None, driver_id: str | None):
    active_assignment = get_active_assignment_for_driver(current_user_id)
    if not active_assignment:
        raise ApiError("You must have an active vehicle assignment to report a fault.", status_code=403)

    assigned_vehicle_id = active_assignment.get("vehicle_id")
    resolved_vehicle_id = vehicle_id or assigned_vehicle_id
    resolved_driver_id = driver_id or current_user_id

    if resolved_driver_id != current_user_id:
        raise ApiError("Drivers can only report faults for themselves.", status_code=403)
    if resolved_vehicle_id != assigned_vehicle_id:
        raise ApiError("Drivers can only report faults for their assigned vehicle.", status_code=403)

    return _to_object_id(resolved_driver_id, "driver_id"), _to_object_id(resolved_vehicle_id, "vehicle_id")


def _validate_photos(photos):
    if photos is None:
        return []
    if not isinstance(photos, list):
        raise ApiError("photos must be an array of image strings.", status_code=400)
    normalized_photos = []
    for photo in photos:
        if not isinstance(photo, str):
            raise ApiError("photos must only contain strings.", status_code=400)
        if photo.strip():
            normalized_photos.append(photo.strip())
    return normalized_photos


def _serialize_category_and_component(category_document: dict, component_document: dict):
    return {
        "category": serialize_fault_category(category_document),
        "component": serialize_fault_component(component_document),
    }


def _enrich_fault(
    fault_document: dict,
    *,
    vehicle_map: dict[str, dict] | None = None,
    user_map: dict[str, dict] | None = None,
    category_map: dict[str, dict] | None = None,
    component_map: dict[str, dict] | None = None,
) -> dict:
    fault = serialize_fault(fault_document)
    vehicle_document = None
    driver_document = None
    created_by_document = None
    updated_by_document = None
    reviewed_by_document = None
    approved_by_document = None
    rejected_by_document = None
    requested_info_by_document = None
    converted_by_document = None
    category_document = None
    component_document = None

    if vehicle_map is not None and fault_document.get("vehicle_id"):
        vehicle_document = vehicle_map.get(str(fault_document.get("vehicle_id")))
    elif fault_document.get("vehicle_id"):
        vehicle_document = vehicles_collection().find_one({"_id": fault_document.get("vehicle_id")})

    if user_map is not None:
        if fault_document.get("driver_id"):
            driver_document = user_map.get(str(fault_document.get("driver_id")))
        if fault_document.get("created_by"):
            created_by_document = user_map.get(str(fault_document.get("created_by")))
        if fault_document.get("updated_by"):
            updated_by_document = user_map.get(str(fault_document.get("updated_by")))
        if fault_document.get("reviewed_by"):
            reviewed_by_document = user_map.get(str(fault_document.get("reviewed_by")))
        if fault_document.get("approved_by"):
            approved_by_document = user_map.get(str(fault_document.get("approved_by")))
        if fault_document.get("rejected_by"):
            rejected_by_document = user_map.get(str(fault_document.get("rejected_by")))
        if fault_document.get("requested_info_by"):
            requested_info_by_document = user_map.get(str(fault_document.get("requested_info_by")))
        converted_by_id = fault_document.get("converted_to_maintenance_by") or fault_document.get("converted_by")
        if converted_by_id:
            converted_by_document = user_map.get(str(converted_by_id))
    else:
        driver_document = users_collection().find_one({"_id": fault_document.get("driver_id")})
        created_by_document = users_collection().find_one({"_id": fault_document.get("created_by")})
        updated_by_document = users_collection().find_one({"_id": fault_document.get("updated_by")})
        reviewed_by_document = users_collection().find_one({"_id": fault_document.get("reviewed_by")})
        approved_by_document = users_collection().find_one({"_id": fault_document.get("approved_by")})
        rejected_by_document = users_collection().find_one({"_id": fault_document.get("rejected_by")})
        requested_info_by_document = users_collection().find_one({"_id": fault_document.get("requested_info_by")})
        converted_by_document = users_collection().find_one(
            {"_id": fault_document.get("converted_to_maintenance_by") or fault_document.get("converted_by")}
        )

    if category_map is not None and fault_document.get("category_id"):
        category_document = category_map.get(str(fault_document.get("category_id")))
    elif fault_document.get("category_id"):
        category_document = fault_categories_collection().find_one({"_id": fault_document.get("category_id")})

    if component_map is not None and fault_document.get("component_id"):
        component_document = component_map.get(str(fault_document.get("component_id")))
    elif fault_document.get("component_id"):
        component_document = fault_components_collection().find_one({"_id": fault_document.get("component_id")})

    fault["vehicle"] = serialize_vehicle(vehicle_document) if vehicle_document else None
    fault["driver"] = serialize_user(driver_document) if driver_document else None
    fault["created_by_user"] = serialize_user(created_by_document) if created_by_document else None
    fault["updated_by_user"] = serialize_user(updated_by_document) if updated_by_document else None
    fault["reviewed_by_user"] = serialize_user(reviewed_by_document) if reviewed_by_document else None
    fault["approved_by_user"] = serialize_user(approved_by_document) if approved_by_document else None
    fault["rejected_by_user"] = serialize_user(rejected_by_document) if rejected_by_document else None
    fault["requested_info_by_user"] = (
        serialize_user(requested_info_by_document) if requested_info_by_document else None
    )
    fault["converted_by_user"] = serialize_user(converted_by_document) if converted_by_document else None
    fault["category"] = serialize_fault_category(category_document) if category_document else None
    fault["component"] = serialize_fault_component(component_document) if component_document else None
    return fault


def _load_fault_relationship_maps(documents: list[dict]) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict]]:
    vehicle_ids = {document.get("vehicle_id") for document in documents if document.get("vehicle_id")}
    category_ids = {document.get("category_id") for document in documents if document.get("category_id")}
    component_ids = {document.get("component_id") for document in documents if document.get("component_id")}
    user_ids = set()
    for document in documents:
        for field in (
            "driver_id",
            "created_by",
            "updated_by",
            "reviewed_by",
            "approved_by",
            "rejected_by",
            "requested_info_by",
            "converted_to_maintenance_by",
            "converted_by",
        ):
            if document.get(field):
                user_ids.add(document.get(field))

    vehicle_map = {}
    user_map = {}
    category_map = {}
    component_map = {}

    if vehicle_ids:
        started_at = perf_counter()
        vehicle_map = {str(item["_id"]): item for item in vehicles_collection().find({"_id": {"$in": list(vehicle_ids)}})}
        log_db_duration("faults.load_vehicles", started_at)
    if user_ids:
        started_at = perf_counter()
        user_map = {str(item["_id"]): item for item in users_collection().find({"_id": {"$in": list(user_ids)}})}
        log_db_duration("faults.load_users", started_at)
    if category_ids:
        started_at = perf_counter()
        category_map = {
            str(item["_id"]): item
            for item in fault_categories_collection().find({"_id": {"$in": list(category_ids)}})
        }
        log_db_duration("faults.load_categories", started_at)
    if component_ids:
        started_at = perf_counter()
        component_map = {
            str(item["_id"]): item
            for item in fault_components_collection().find({"_id": {"$in": list(component_ids)}})
        }
        log_db_duration("faults.load_components", started_at)

    return vehicle_map, user_map, category_map, component_map


def _sort_fault_documents(documents: list[dict]) -> list[dict]:
    def sort_key(document: dict):
        severity_rank = FAULT_SEVERITY_ORDER.get(document.get("severity"), 99)
        status_rank = 0 if document.get("status") in {"reported", "under_review"} else 1
        reported_at = document.get("reported_at") or document.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)
        return (status_rank, severity_rank, -reported_at.timestamp())

    return sorted(documents, key=sort_key)


def _set_vehicle_to_maintenance_if_critical(fault_document: dict):
    if fault_document.get("severity") != "critical":
        return

    vehicles_collection().update_one(
        {"_id": fault_document.get("vehicle_id")},
        {
            "$set": {
                "status": "maintenance",
                "updated_at": now_utc(),
            }
        },
    )


def list_faults(current_user_id: str, current_role: str) -> list[dict]:
    query = {}
    if current_role == "driver":
        query["driver_id"] = _to_object_id(current_user_id, "current_user_id")

    query_started_at = perf_counter()
    documents = list(
        faults_collection().find(query, FAULT_LIST_PROJECTION).sort([("reported_at", DESCENDING), ("created_at", DESCENDING)])
    )
    log_db_duration("faults.list.query", query_started_at)
    vehicle_map, user_map, category_map, component_map = _load_fault_relationship_maps(documents)
    return [
        _enrich_fault(
            document,
            vehicle_map=vehicle_map,
            user_map=user_map,
            category_map=category_map,
            component_map=component_map,
        )
        for document in documents
    ]


def list_fault_approvals(current_role: str) -> list[dict]:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to view the fault approval queue.", status_code=403)

    request_started_at = perf_counter()
    documents = list(
        faults_collection()
        .find({"status": {"$in": list(FAULT_APPROVAL_QUEUE_STATUSES)}}, FAULT_LIST_PROJECTION)
        .sort([("reported_at", DESCENDING), ("created_at", DESCENDING)])
    )
    log_db_duration("faults.approvals.query", request_started_at)
    sorted_documents = _sort_fault_documents(documents)
    enrichment_started_at = perf_counter()
    vehicle_map, user_map, category_map, component_map = _load_fault_relationship_maps(sorted_documents)
    result = [
        _enrich_fault(
            document,
            vehicle_map=vehicle_map,
            user_map=user_map,
            category_map=category_map,
            component_map=component_map,
        )
        for document in sorted_documents
    ]
    current_app.logger.info(
        "[Flux Faults] approvals count=%s enrichment_ms=%.2f total_ms=%.2f",
        len(result),
        (perf_counter() - enrichment_started_at) * 1000,
        (perf_counter() - request_started_at) * 1000,
    )
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    if total_duration_ms > 2000:
        current_app.logger.warning(
            "SLOW API WARNING endpoint=/api/faults/approvals role=%s duration_ms=%.2f",
            current_role,
            total_duration_ms,
        )
    return result


def list_critical_faults(current_role: str) -> list[dict]:
    if current_role not in {"owner", "admin"}:
        raise ApiError("You do not have permission to view critical faults.", status_code=403)

    request_started_at = perf_counter()
    documents = list(
        faults_collection()
        .find({"severity": "critical", "status": {"$ne": "resolved"}}, FAULT_LIST_PROJECTION)
        .sort([("reported_at", DESCENDING), ("created_at", DESCENDING)])
    )
    log_db_duration("faults.critical.query", request_started_at)
    sorted_documents = _sort_fault_documents(documents)
    vehicle_map, user_map, category_map, component_map = _load_fault_relationship_maps(sorted_documents)
    result = [
        _enrich_fault(
            document,
            vehicle_map=vehicle_map,
            user_map=user_map,
            category_map=category_map,
            component_map=component_map,
        )
        for document in sorted_documents
    ]
    current_app.logger.info(
        "[Flux Faults] critical count=%s total_ms=%.2f",
        len(result),
        (perf_counter() - request_started_at) * 1000,
    )
    total_duration_ms = (perf_counter() - request_started_at) * 1000
    if total_duration_ms > 2000:
        current_app.logger.warning(
            "SLOW API WARNING endpoint=/api/faults/critical role=%s duration_ms=%.2f",
            current_role,
            total_duration_ms,
        )
    return result


def get_fault_by_id(fault_id: str, current_user_id: str, current_role: str) -> dict:
    document = _get_fault_document(fault_id)
    if current_role == "driver" and str(document.get("driver_id")) != current_user_id:
        raise ApiError("You do not have permission to view this fault.", status_code=403)
    return _enrich_fault(document)


def create_fault(payload: dict, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"driver", "admin", "owner"}:
        raise ApiError("You do not have permission to create fault reports.", status_code=403)

    category_document = _get_category_document(payload.get("category_id"))
    component_document = _get_component_document(payload.get("component_id"))
    _ensure_category_component_match(category_document, component_document)

    if category_document.get("status") != ACTIVE_STATUS or component_document.get("status") != ACTIVE_STATUS:
        raise ApiError("Selected fault category or component is inactive.", status_code=400)

    severity = _validate_severity(payload.get("severity"))
    description = (payload.get("description") or "").strip()
    if not description:
        raise ApiError("description is required.", status_code=400)

    if current_role == "driver":
        driver_object_id, vehicle_object_id = _validate_driver_fault_scope(
            current_user_id=current_user_id,
            vehicle_id=payload.get("vehicle_id"),
            driver_id=payload.get("driver_id"),
        )
    else:
        driver_object_id = _to_object_id(payload.get("driver_id"), "driver_id")
        vehicle_object_id = _to_object_id(payload.get("vehicle_id"), "vehicle_id")
        driver_document = _get_user_document(driver_object_id, "driver_id")
        if driver_document.get("role") != "driver":
            raise ApiError("Selected driver must have the driver role.", status_code=400)
        _get_vehicle_document(vehicle_object_id)

    photos = _validate_photos(payload.get("photos"))
    timestamp = now_utc()
    document = {
        "vehicle_id": vehicle_object_id,
        "driver_id": driver_object_id,
        "category_id": category_document["_id"],
        "component_id": component_document["_id"],
        "severity": severity,
        "description": description,
        "photos": photos,
        "status": "reported",
        "admin_notes": (payload.get("admin_notes") or "").strip() or None,
        "owner_notes": (payload.get("owner_notes") or "").strip() or None,
        "resolution_notes": None,
        "maintenance_job_id": None,
        "reported_at": timestamp,
        "reviewed_by": None,
        "reviewed_at": None,
        "approved_at": None,
        "rejected_at": None,
        "rejection_reason": None,
        "requested_info_at": None,
        "request_info_note": None,
        "converted_to_maintenance_by": None,
        "converted_to_maintenance_at": None,
        "resolved_at": None,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "approved_by": None,
        "rejected_by": None,
        "requested_info_by": None,
        "converted_by": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = faults_collection().insert_one(document)
    document["_id"] = result.inserted_id

    vehicle_registration = _get_vehicle_document(vehicle_object_id).get("registration_number") or "vehicle"

    if current_role == "driver":
        notify_roles(
            ["admin", "owner"],
            title="New Fault Report Submitted",
            message=f"A new fault report was submitted for vehicle {vehicle_registration}.",
            category="maintenance",
            priority="high" if severity in {"high", "critical"} else "medium",
            reference_type="fault",
            reference_id=document["_id"],
        )

    if severity == "critical":
        notify_roles(
            ["admin", "owner"],
            title="Critical Vehicle Fault",
            message=f"Critical fault reported for vehicle {vehicle_registration}. Immediate review required.",
            category="maintenance",
            priority="critical",
            reference_type="fault",
            reference_id=document["_id"],
        )

    return _enrich_fault(document)


def update_fault(fault_id: str, payload: dict, current_user_id: str, current_role: str) -> dict:
    document = _get_fault_document(fault_id)
    update_fields = {}

    if current_role == "driver":
        if str(document.get("driver_id")) != current_user_id:
            raise ApiError("You do not have permission to update this fault.", status_code=403)
        if document.get("status") not in {"reported", "under_review"}:
            raise ApiError("This fault can no longer be updated by the driver.", status_code=400)

        if "category_id" in payload:
            category_document = _get_category_document(payload.get("category_id"))
            component_document = _get_component_document(payload.get("component_id") or document.get("component_id"))
            _ensure_category_component_match(category_document, component_document)
            update_fields["category_id"] = category_document["_id"]
        if "component_id" in payload:
            category_document = _get_category_document(update_fields.get("category_id") or document.get("category_id"))
            component_document = _get_component_document(payload.get("component_id"))
            _ensure_category_component_match(category_document, component_document)
            update_fields["component_id"] = component_document["_id"]
        if "severity" in payload:
            update_fields["severity"] = _validate_severity(payload.get("severity"))
        if "description" in payload:
            description = (payload.get("description") or "").strip()
            if not description:
                raise ApiError("description cannot be empty.", status_code=400)
            update_fields["description"] = description
        if "photos" in payload:
            update_fields["photos"] = _validate_photos(payload.get("photos"))
    else:
        if "admin_notes" in payload:
            update_fields["admin_notes"] = (payload.get("admin_notes") or "").strip() or None
        if "owner_notes" in payload:
            update_fields["owner_notes"] = (payload.get("owner_notes") or "").strip() or None
        if "resolution_notes" in payload:
            update_fields["resolution_notes"] = (payload.get("resolution_notes") or "").strip() or None
        if payload.get("status") == "resolved":
            if document.get("status") not in {"approved", "converted_to_maintenance"}:
                raise ApiError("Only approved or converted faults can be resolved.", status_code=400)
            update_fields["status"] = "resolved"
            update_fields["resolved_at"] = now_utc()

    if not update_fields:
        raise ApiError("No valid fault fields provided for update.", status_code=400)

    update_fields["updated_by"] = _to_object_id(current_user_id, "updated_by")
    update_fields["updated_at"] = now_utc()
    faults_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_fault(document)


def approve_fault(fault_id: str, current_user_id: str, notes: str | None = None) -> dict:
    document = _get_fault_document(fault_id)
    if document.get("status") in {"approved", "converted_to_maintenance", "resolved"}:
        raise ApiError("This fault cannot be approved again.", status_code=400)
    if document.get("status") == "rejected":
        raise ApiError("Rejected faults cannot be approved.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "approved",
        "admin_notes": (notes or "").strip() or document.get("admin_notes"),
        "reviewed_by": _to_object_id(current_user_id, "reviewed_by"),
        "reviewed_at": timestamp,
        "approved_by": _to_object_id(current_user_id, "approved_by"),
        "approved_at": timestamp,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "requested_info_by": None,
        "requested_info_at": None,
        "request_info_note": None,
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "updated_at": timestamp,
    }
    faults_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    _set_vehicle_to_maintenance_if_critical(document)
    return _enrich_fault(document)


def reject_fault(fault_id: str, current_user_id: str, notes: str | None) -> dict:
    document = _get_fault_document(fault_id)
    if document.get("status") in {"rejected", "converted_to_maintenance", "resolved"}:
        raise ApiError("This fault cannot be rejected.", status_code=400)

    note = (notes or "").strip()
    if not note:
        raise ApiError("admin_notes is required when rejecting a fault.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "rejected",
        "admin_notes": note,
        "reviewed_by": _to_object_id(current_user_id, "reviewed_by"),
        "reviewed_at": timestamp,
        "approved_by": None,
        "approved_at": None,
        "rejected_by": _to_object_id(current_user_id, "rejected_by"),
        "rejected_at": timestamp,
        "rejection_reason": note,
        "requested_info_by": None,
        "requested_info_at": None,
        "request_info_note": None,
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "updated_at": timestamp,
    }
    faults_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_fault(document)


def request_fault_info(fault_id: str, current_user_id: str, notes: str | None) -> dict:
    document = _get_fault_document(fault_id)
    if document.get("status") in {"converted_to_maintenance", "resolved"}:
        raise ApiError("This fault can no longer be sent back for more information.", status_code=400)

    note = (notes or "").strip()
    if not note:
        raise ApiError("admin_notes is required when requesting more information.", status_code=400)

    timestamp = now_utc()
    update_fields = {
        "status": "under_review",
        "admin_notes": note,
        "reviewed_by": _to_object_id(current_user_id, "reviewed_by"),
        "reviewed_at": timestamp,
        "approved_by": None,
        "approved_at": None,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "requested_info_by": _to_object_id(current_user_id, "requested_info_by"),
        "requested_info_at": timestamp,
        "request_info_note": note,
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "updated_at": timestamp,
    }
    faults_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_fault(document)


def convert_fault_to_maintenance(fault_id: str, current_user_id: str) -> dict:
    document = _get_fault_document(fault_id)
    if document.get("status") != "approved":
        raise ApiError("Only approved faults can be converted to maintenance.", status_code=400)
    if document.get("maintenance_job_id"):
        raise ApiError("This fault has already been converted to a maintenance job.", status_code=400)

    category_document = _get_category_document(document.get("category_id"))
    component_document = _get_component_document(document.get("component_id"))
    timestamp = now_utc()
    maintenance_job = {
        "fault_id": document["_id"],
        "vehicle_id": document.get("vehicle_id"),
        "driver_id": document.get("driver_id"),
        "category_id": document.get("category_id"),
        "component_id": document.get("component_id"),
        "severity": document.get("severity"),
        "description": document.get("description"),
        "photos": document.get("photos") or [],
        "status": "pending",
        "created_from_fault": True,
        "category_snapshot": serialize_fault_category(category_document),
        "component_snapshot": serialize_fault_component(component_document),
        "created_by": _to_object_id(current_user_id, "created_by"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = maintenance_jobs_collection().insert_one(maintenance_job)

    update_fields = {
        "status": "converted_to_maintenance",
        "maintenance_job_id": result.inserted_id,
        "converted_by": _to_object_id(current_user_id, "converted_by"),
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "updated_at": timestamp,
    }
    faults_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return _enrich_fault(document)


def list_fault_options(current_role: str) -> dict:
    cache_key = build_cache_key("fault_options", current_role=current_role)
    cached = get_ttl_cached(cache_key)
    if cached is not None:
        return cached

    category_query = {}
    component_query = {}
    if current_role != "owner":
        category_query["status"] = ACTIVE_STATUS
        component_query["status"] = ACTIVE_STATUS

    query_started_at = perf_counter()
    categories = list(
        fault_categories_collection().find(category_query, {"name": 1, "code": 1, "status": 1}).sort([("name", ASCENDING)])
    )
    components = list(
        fault_components_collection().find(
            component_query,
            {"name": 1, "code": 1, "status": 1, "category_id": 1},
        ).sort([("name", ASCENDING)])
    )
    log_db_duration("faults.options.query", query_started_at)
    result = {
        "categories": [serialize_fault_category(category) for category in categories],
        "components": [serialize_fault_component(component) for component in components],
    }
    return set_ttl_cached(cache_key, result, ttl_seconds=30)


def create_fault_category(payload: dict, current_user_id: str) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ApiError("name is required.", status_code=400)
    code = _slugify(name)
    if fault_categories_collection().find_one({"code": code}):
        raise ApiError("A fault category with that name already exists.", status_code=400)

    timestamp = now_utc()
    document = {
        "name": name,
        "code": code,
        "status": ACTIVE_STATUS,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = fault_categories_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return serialize_fault_category(document)


def update_fault_category(category_id: str, payload: dict, current_user_id: str) -> dict:
    document = _get_category_document(category_id)
    update_fields = {}
    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ApiError("name cannot be empty.", status_code=400)
        code = _slugify(name)
        existing = fault_categories_collection().find_one({"code": code})
        if existing and existing.get("_id") != document.get("_id"):
            raise ApiError("A fault category with that name already exists.", status_code=400)
        update_fields["name"] = name
        update_fields["code"] = code
    if "status" in payload:
        status = (payload.get("status") or "").strip().lower()
        if status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
            raise ApiError("status must be active or inactive.", status_code=400)
        update_fields["status"] = status

    if not update_fields:
        raise ApiError("No valid category fields provided for update.", status_code=400)

    update_fields["updated_by"] = _to_object_id(current_user_id, "updated_by")
    update_fields["updated_at"] = now_utc()
    fault_categories_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return serialize_fault_category(document)


def create_fault_component(payload: dict, current_user_id: str) -> dict:
    category_document = _get_category_document(payload.get("category_id"))
    name = (payload.get("name") or "").strip()
    if not name:
        raise ApiError("name is required.", status_code=400)
    if fault_components_collection().find_one({"category_id": category_document["_id"], "name": name}):
        raise ApiError("A fault component with that name already exists for this category.", status_code=400)

    timestamp = now_utc()
    document = {
        "category_id": category_document["_id"],
        "name": name,
        "code": _slugify(name),
        "status": ACTIVE_STATUS,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    result = fault_components_collection().insert_one(document)
    document["_id"] = result.inserted_id
    return serialize_fault_component(document)


def update_fault_component(component_id: str, payload: dict, current_user_id: str) -> dict:
    document = _get_component_document(component_id)
    update_fields = {}
    target_category_document = _get_category_document(payload.get("category_id") or document.get("category_id"))

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ApiError("name cannot be empty.", status_code=400)
        existing = fault_components_collection().find_one(
            {"category_id": target_category_document["_id"], "name": name}
        )
        if existing and existing.get("_id") != document.get("_id"):
            raise ApiError("A fault component with that name already exists for this category.", status_code=400)
        update_fields["name"] = name
        update_fields["code"] = _slugify(name)

    if "category_id" in payload:
        update_fields["category_id"] = target_category_document["_id"]
    if "status" in payload:
        status = (payload.get("status") or "").strip().lower()
        if status not in {ACTIVE_STATUS, INACTIVE_STATUS}:
            raise ApiError("status must be active or inactive.", status_code=400)
        update_fields["status"] = status

    if not update_fields:
        raise ApiError("No valid component fields provided for update.", status_code=400)

    update_fields["updated_by"] = _to_object_id(current_user_id, "updated_by")
    update_fields["updated_at"] = now_utc()
    fault_components_collection().update_one({"_id": document["_id"]}, {"$set": update_fields})
    document.update(update_fields)
    return serialize_fault_component(document)
