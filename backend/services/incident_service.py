from datetime import date, datetime, timezone
from uuid import uuid4

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from models.incident import serialize_incident
from models.user import serialize_user
from models.vehicle import serialize_vehicle
from services.maintenance_service import create_maintenance_job
from services.notification_service import notify_roles
from utils.api_error import ApiError
from utils.file_validation import validate_attachment_list
from utils.mongo_indexes import ensure_indexes_for_collection


ALLOWED_INCIDENT_TYPES = {
    "accident",
    "breakdown",
    "theft",
    "fire",
    "third_party_damage",
    "injury",
    "other",
}
ALLOWED_INCIDENT_STATUSES = {
    "reported",
    "under_review",
    "police_report_pending",
    "insurance_notified",
    "claim_submitted",
    "assessment_scheduled",
    "repair_approved",
    "repair_in_progress",
    "resolved",
    "rejected",
    "closed",
}
ALLOWED_CLAIM_ELIGIBILITY = {
    "Not eligible",
    "Limited coverage",
    "Potentially eligible",
    "Review needed",
}
ALLOWED_CLAIM_STATUSES = {
    "not_started",
    "under_review",
    "submitted",
    "assessment_scheduled",
    "approved",
    "partially_paid",
    "paid",
    "rejected",
    "closed",
}
EMERGENCY_CHECKLIST = [
    "Stop safely",
    "Take photos/videos",
    "Call police if needed",
    "Call fleet office",
    "Collect witness/third-party details",
    "Do not admit fault",
]
OUT_OF_SERVICE_STATUSES = {
    "reported",
    "under_review",
    "police_report_pending",
    "insurance_notified",
    "claim_submitted",
    "assessment_scheduled",
    "repair_approved",
    "repair_in_progress",
}


def now_utc():
    return datetime.now(timezone.utc)


def incidents_collection():
    return get_collection("incidents")


def users_collection():
    return get_collection("users")


def vehicles_collection():
    return get_collection("vehicles")


def ensure_incident_indexes():
    ensure_indexes_for_collection(
        incidents_collection(),
        [
            {"keys": [("vehicle_id", ASCENDING)]},
            {"keys": [("driver_id", ASCENDING)]},
            {"keys": [("status", ASCENDING)]},
            {"keys": [("incident_type", ASCENDING)]},
            {"keys": [("incident_at", DESCENDING)]},
            {"keys": [("claim_status", ASCENDING)]},
            {"keys": [("created_at", DESCENDING)]},
            {"keys": [("updated_at", DESCENDING)]},
            {"keys": [("vehicle_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
            {"keys": [("status", ASCENDING), ("created_at", DESCENDING)]},
        ],
        collection_name="incidents",
    )


def _to_object_id(value, field_name: str, *, required: bool = True) -> ObjectId | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Please select a valid {field_name.replace('_', ' ')}.", status_code=400)


def _normalize_string(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_slug(value):
    normalized = _normalize_string(value)
    return normalized.lower() if normalized else None


def _parse_datetime(value, field_name: str, *, required: bool = False) -> datetime | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"Please provide {field_name.replace('_', ' ')}.", status_code=400)
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise ApiError(f"{field_name.replace('_', ' ')} must be a valid date and time.", status_code=400)
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(f"{field_name.replace('_', ' ')} must be a valid date and time.", status_code=400) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_date(value, field_name: str, *, required: bool = False) -> date | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"Please provide {field_name.replace('_', ' ')}.", status_code=400)
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        raise ApiError(f"{field_name.replace('_', ' ')} must be a valid date.", status_code=400)
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ApiError(f"{field_name.replace('_', ' ')} must be a valid date.", status_code=400) from exc


def _serialize_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _validate_amount(value, field_name: str, *, required: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"Please provide {field_name.replace('_', ' ')}.", status_code=400)
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name.replace('_', ' ')} must be a number.", status_code=400)
    if float(value) < 0:
        raise ApiError(f"{field_name.replace('_', ' ')} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _get_user_document(user_id: str | ObjectId, field_name: str = "user_id") -> dict:
    user_object_id = _to_object_id(user_id, field_name)
    document = users_collection().find_one({"_id": user_object_id})
    if not document:
        raise ApiError("User not found.", status_code=404)
    return document


def _get_vehicle_document(vehicle_id: str | ObjectId) -> dict:
    vehicle_object_id = _to_object_id(vehicle_id, "vehicle_id")
    document = vehicles_collection().find_one({"_id": vehicle_object_id})
    if not document:
        raise ApiError("Vehicle not found.", status_code=404)
    return document


def _get_incident_document(incident_id: str | ObjectId) -> dict:
    incident_object_id = _to_object_id(incident_id, "incident_id")
    document = incidents_collection().find_one({"_id": incident_object_id})
    if not document:
        raise ApiError("Incident not found.", status_code=404)
    return document


def _slugify_label(value: str | None) -> str | None:
    if not value:
        return None
    return (
        value.strip()
        .lower()
        .replace("&", "and")
        .replace("/", " ")
        .replace("-", " ")
        .replace("  ", " ")
        .replace(" ", "_")
    )


def _normalize_risk_list(values) -> list[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        raise ApiError("Insurance risks must be provided as a list.", status_code=400)
    normalized: list[str] = []
    for item in values:
        label = _normalize_string(item)
        if label:
            normalized.append(label)
    return normalized


def _validate_incident_type(value: str | None) -> str:
    incident_type = _normalize_slug(value)
    if incident_type not in ALLOWED_INCIDENT_TYPES:
        raise ApiError(
            "Incident type must be one of: accident, breakdown, theft, fire, third_party_damage, injury, other.",
            status_code=400,
        )
    return incident_type


def _validate_incident_status(value: str | None) -> str:
    status = _normalize_slug(value)
    if status not in ALLOWED_INCIDENT_STATUSES:
        raise ApiError("Please choose a valid incident status.", status_code=400)
    return status


def _validate_claim_status(value: str | None, *, required: bool = False) -> str | None:
    if value in (None, ""):
        if required:
            raise ApiError("Please choose a valid claim status.", status_code=400)
        return None
    claim_status = _normalize_slug(value)
    if claim_status not in ALLOWED_CLAIM_STATUSES:
        raise ApiError("Please choose a valid claim status.", status_code=400)
    return claim_status


def _validate_claim_eligibility(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    normalized = _normalize_string(value)
    if normalized not in ALLOWED_CLAIM_ELIGIBILITY:
        raise ApiError("Please choose a valid claim eligibility override.", status_code=400)
    return normalized


def _validate_boolean(value, field_name: str, *, required: bool = False) -> bool | None:
    if value in (None, ""):
        if required:
            raise ApiError(f"Please answer {field_name.replace('_', ' ')}.", status_code=400)
        return None
    if not isinstance(value, bool):
        raise ApiError(f"{field_name.replace('_', ' ')} must be yes or no.", status_code=400)
    return value


def _validate_driver_incident_scope(current_user_id: str, vehicle_id: str | None, driver_id: str | None) -> tuple[ObjectId, ObjectId]:
    user_document = _get_user_document(current_user_id, "current_user_id")
    assigned_vehicle_id = ((user_document.get("driver_profile") or {}).get("assigned_vehicle_id"))
    if not assigned_vehicle_id:
        raise ApiError("You need an assigned vehicle before you can report an incident.", status_code=403)
    if driver_id and str(driver_id) != current_user_id:
        raise ApiError("Drivers can only report incidents for themselves.", status_code=403)
    if vehicle_id and str(vehicle_id) != str(assigned_vehicle_id):
        raise ApiError("Drivers can only report incidents for their assigned vehicle.", status_code=403)
    return _to_object_id(current_user_id, "driver_id"), _to_object_id(assigned_vehicle_id, "vehicle_id")


def _validate_attachments(attachments) -> list[dict]:
    validated_attachments = validate_attachment_list(attachments, field_name="attachments", max_files=10)
    normalized: list[dict] = []
    for item in validated_attachments:
        normalized.append(
            {
                "id": _normalize_string(item.get("id")) or str(uuid4()),
                "name": _normalize_string(item.get("name")) or "Attachment",
                "file_name": _normalize_string(item.get("file_name")) or "attachment",
                "file_kind": _normalize_slug(item.get("file_kind")) or "document",
                "content_type": _normalize_string(item.get("content_type")),
                "data_url": item.get("data_url"),
                "size_bytes": item.get("size_bytes") if isinstance(item.get("size_bytes"), int) else None,
                "uploaded_at": now_utc(),
            }
        )
    return normalized


def _build_vehicle_insurance_snapshot(vehicle_document: dict, *, incident_type: str) -> dict:
    insurance_profile = vehicle_document.get("insurance_profile") or {}
    company = _normalize_string(insurance_profile.get("insurance_company"))
    policy_number = _normalize_string(insurance_profile.get("policy_number"))
    insurance_type = _normalize_string(insurance_profile.get("insurance_type"))
    expiry_date = _normalize_string(insurance_profile.get("expiry_date") or vehicle_document.get("insurance_expiry"))
    start_date = _normalize_string(insurance_profile.get("start_date"))
    claims_officer_name = _normalize_string(insurance_profile.get("claims_officer_name"))
    claims_officer_phone = _normalize_string(insurance_profile.get("claims_officer_phone"))
    claims_officer_email = _normalize_string(insurance_profile.get("claims_officer_email"))
    emergency_contact = _normalize_string(insurance_profile.get("emergency_contact"))
    covered_risks = _normalize_risk_list(insurance_profile.get("covered_risks"))
    excluded_risks = _normalize_risk_list(insurance_profile.get("excluded_risks"))
    coverage_duration_months = insurance_profile.get("coverage_duration_months")
    excess_amount = insurance_profile.get("excess_amount")

    insurance_status = "Missing"
    expiry = _parse_date(expiry_date, "insurance expiry", required=False) if expiry_date else None
    today = now_utc().date()
    if company or policy_number or insurance_type:
        insurance_status = "Expired" if expiry and expiry < today else "Active"

    incident_slug = _slugify_label(incident_type)
    excluded_matches = {_slugify_label(item) for item in excluded_risks}
    covered_matches = {_slugify_label(item) for item in covered_risks}

    if insurance_status == "Missing":
        claim_eligibility = "Not eligible"
        eligibility_reason = "No insurance details are linked to this vehicle."
    elif insurance_status == "Expired":
        claim_eligibility = "Not eligible"
        eligibility_reason = "The vehicle insurance policy has expired."
    elif incident_slug in excluded_matches:
        claim_eligibility = "Not eligible"
        eligibility_reason = "This incident type appears in the excluded risk list."
    elif (insurance_type or "").lower() == "third party":
        claim_eligibility = "Limited coverage"
        eligibility_reason = "Third Party insurance may only cover third-party liability."
    elif (insurance_type or "").lower() == "comprehensive":
        if covered_matches and incident_slug and incident_slug not in covered_matches:
            claim_eligibility = "Review needed"
            eligibility_reason = "Comprehensive cover exists, but the incident risk needs manual review."
        else:
            claim_eligibility = "Potentially eligible"
            eligibility_reason = "Comprehensive insurance is active and may cover this incident."
    else:
        claim_eligibility = "Review needed"
        eligibility_reason = "Insurance details need manual review."

    return {
        "company": company,
        "policy_number": policy_number,
        "insurance_type": insurance_type,
        "start_date": start_date,
        "expiry_date": expiry_date,
        "coverage_duration_months": coverage_duration_months,
        "claims_officer_name": claims_officer_name,
        "claims_officer_phone": claims_officer_phone,
        "claims_officer_email": claims_officer_email,
        "emergency_contact": emergency_contact,
        "excess_amount": round(float(excess_amount), 2) if isinstance(excess_amount, (int, float)) else None,
        "covered_risks": covered_risks,
        "excluded_risks": excluded_risks,
        "status": insurance_status,
        "claim_eligibility": claim_eligibility,
        "eligibility_reason": eligibility_reason,
        "eligibility_overridden": False,
        "eligibility_override_reason": None,
        "claim_number": None,
        "claim_submitted_date": None,
        "assessment_date": None,
        "claim_status": "not_started",
        "insurance_notified": False,
        "insurance_notified_at": None,
    }


def _append_audit_log(
    document: dict,
    *,
    action: str,
    actor_id: str,
    actor_role: str,
    changes: list[str] | None = None,
    note: str | None = None,
    reason: str | None = None,
):
    entry = {
        "id": str(uuid4()),
        "action": action,
        "actor_id": _to_object_id(actor_id, "actor_id"),
        "actor_role": actor_role,
        "note": note,
        "reason": reason,
        "changes": changes or [],
        "created_at": now_utc(),
    }
    incidents_collection().update_one({"_id": document["_id"]}, {"$push": {"audit_logs": entry}})
    document.setdefault("audit_logs", []).append(entry)


def _update_outstanding_claim_fields(document: dict):
    approved = float(document.get("insurance_approved_amount") or 0)
    paid = float(document.get("paid_amount") or 0)
    document["outstanding_claim"] = round(max(approved - paid, 0), 2)


def _update_downtime_fields(document: dict, *, vehicle_document: dict | None = None):
    start_date = _parse_date(document.get("downtime_start_date"), "downtime_start_date", required=False)
    end_date = _parse_date(document.get("downtime_end_date"), "downtime_end_date", required=False)
    if start_date is None and not document.get("can_vehicle_move"):
        start_date = (document.get("incident_at") or now_utc()).date()
        document["downtime_start_date"] = start_date.isoformat()
    if document.get("status") in {"resolved", "closed"} and start_date and end_date is None:
        end_date = now_utc().date()
        document["downtime_end_date"] = end_date.isoformat()
    if start_date:
        comparison_end = end_date or now_utc().date()
        document["downtime_days"] = max((comparison_end - start_date).days + 1, 0)
    else:
        document["downtime_days"] = 0

    if document.get("estimated_revenue_lost") is None:
        daily_target = float((vehicle_document or {}).get("default_daily_target") or 0)
        document["estimated_revenue_lost"] = round(daily_target * float(document.get("downtime_days") or 0), 2)


def _status_for_incident_vehicle(document: dict) -> str:
    if document.get("status") in {"resolved", "closed"}:
        return "assigned" if document.get("driver_id") else "available"
    if document.get("status") in OUT_OF_SERVICE_STATUSES and not document.get("can_vehicle_move"):
        return "out_of_service"
    if document.get("status") in OUT_OF_SERVICE_STATUSES:
        return "accident"
    return "available"


def _sync_vehicle_status_for_incident(document: dict):
    vehicle_document = _get_vehicle_document(document.get("vehicle_id"))
    target_status = document.get("vehicle_status_after_incident") or _status_for_incident_vehicle(document)
    vehicles_collection().update_one(
        {"_id": vehicle_document["_id"]},
        {"$set": {"status": target_status, "updated_at": now_utc()}},
    )
    document["vehicle_status_after_incident"] = target_status


def _enrich_incident(document: dict, *, vehicle_map: dict[str, dict] | None = None, user_map: dict[str, dict] | None = None) -> dict:
    serialized = serialize_incident(document)
    vehicle_document = None
    replacement_vehicle_document = None
    driver_document = None
    if vehicle_map is not None:
        if document.get("vehicle_id"):
            vehicle_document = vehicle_map.get(str(document.get("vehicle_id")))
        if document.get("replacement_vehicle_id"):
            replacement_vehicle_document = vehicle_map.get(str(document.get("replacement_vehicle_id")))
    else:
        if document.get("vehicle_id"):
            vehicle_document = vehicles_collection().find_one({"_id": document.get("vehicle_id")})
        if document.get("replacement_vehicle_id"):
            replacement_vehicle_document = vehicles_collection().find_one({"_id": document.get("replacement_vehicle_id")})

    if user_map is not None and document.get("driver_id"):
        driver_document = user_map.get(str(document.get("driver_id")))
    elif document.get("driver_id"):
        driver_document = users_collection().find_one({"_id": document.get("driver_id")})

    serialized["vehicle"] = serialize_vehicle(vehicle_document) if vehicle_document else None
    serialized["replacement_vehicle"] = serialize_vehicle(replacement_vehicle_document) if replacement_vehicle_document else None
    serialized["driver"] = serialize_user(driver_document) if driver_document else None
    return serialized


def _load_relationship_maps(documents: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    vehicle_ids = set()
    user_ids = set()
    for document in documents:
        if document.get("vehicle_id"):
            vehicle_ids.add(document.get("vehicle_id"))
        if document.get("replacement_vehicle_id"):
            vehicle_ids.add(document.get("replacement_vehicle_id"))
        if document.get("driver_id"):
            user_ids.add(document.get("driver_id"))
    vehicle_map = (
        {str(item["_id"]): item for item in vehicles_collection().find({"_id": {"$in": list(vehicle_ids)}})}
        if vehicle_ids
        else {}
    )
    user_map = (
        {str(item["_id"]): item for item in users_collection().find({"_id": {"$in": list(user_ids)}})}
        if user_ids
        else {}
    )
    return vehicle_map, user_map


def _build_dashboard(documents: list[dict], *, vehicle_map: dict[str, dict]) -> dict:
    total_repair_cost = round(sum(float(item.get("repair_cost") or 0) for item in documents), 2)
    total_approved = round(sum(float(item.get("insurance_approved_amount") or 0) for item in documents), 2)
    total_paid = round(sum(float(item.get("paid_amount") or 0) for item in documents), 2)
    total_outstanding = round(sum(float(item.get("outstanding_claim") or 0) for item in documents), 2)
    total_downtime_days = int(sum(int(item.get("downtime_days") or 0) for item in documents))
    total_revenue_lost = round(sum(float(item.get("estimated_revenue_lost") or 0) for item in documents), 2)
    open_incidents = sum(1 for item in documents if item.get("status") not in {"resolved", "rejected", "closed"})

    driver_summary: dict[str, dict] = {}
    for item in documents:
        driver_id = str(item.get("driver_id") or "")
        if not driver_id:
            continue
        summary = driver_summary.setdefault(
            driver_id,
            {
                "driver_id": driver_id,
                "driver_name": None,
                "incident_count": 0,
                "open_incidents": 0,
                "downtime_days": 0,
                "estimated_revenue_lost": 0.0,
                "critical_incidents": 0,
            },
        )
        summary["incident_count"] += 1
        if item.get("status") not in {"resolved", "rejected", "closed"}:
            summary["open_incidents"] += 1
        summary["downtime_days"] += int(item.get("downtime_days") or 0)
        summary["estimated_revenue_lost"] += float(item.get("estimated_revenue_lost") or 0)
        if item.get("incident_type") in {"accident", "injury", "fire", "theft"}:
            summary["critical_incidents"] += 1

    user_map = {
        str(item["_id"]): item
        for item in users_collection().find({"_id": {"$in": [_to_object_id(driver_id, "driver_id") for driver_id in driver_summary]}})
    } if driver_summary else {}
    for driver_id, summary in driver_summary.items():
        summary["driver_name"] = (user_map.get(driver_id) or {}).get("full_name")
        summary["estimated_revenue_lost"] = round(summary["estimated_revenue_lost"], 2)

    insurance_directory = []
    insurance_alerts = []
    today = now_utc().date()
    for vehicle in vehicle_map.values():
        insurance_profile = vehicle.get("insurance_profile") or {}
        expiry_date = _parse_date(
            insurance_profile.get("expiry_date") or vehicle.get("insurance_expiry"),
            "insurance expiry",
            required=False,
        )
        status = "Missing"
        days_to_expiry = None
        if insurance_profile.get("insurance_company") or insurance_profile.get("policy_number") or insurance_profile.get("insurance_type"):
            if expiry_date:
                days_to_expiry = (expiry_date - today).days
                status = "Expired" if days_to_expiry < 0 else "Active"
            else:
                status = "Active"
            insurance_directory.append(
                {
                    "vehicle_id": str(vehicle["_id"]),
                    "vehicle": serialize_vehicle(vehicle, include_sensitive=False),
                    "insurance_company": insurance_profile.get("insurance_company"),
                    "policy_number": insurance_profile.get("policy_number"),
                    "insurance_type": insurance_profile.get("insurance_type"),
                    "claims_officer_name": insurance_profile.get("claims_officer_name"),
                    "claims_officer_phone": insurance_profile.get("claims_officer_phone"),
                    "claims_officer_email": insurance_profile.get("claims_officer_email"),
                    "emergency_contact": insurance_profile.get("emergency_contact"),
                    "renewal_date": insurance_profile.get("expiry_date") or vehicle.get("insurance_expiry"),
                    "status": status,
                }
            )
        if status == "Expired":
            insurance_alerts.append(
                {
                    "type": "insurance_expired",
                    "vehicle_id": str(vehicle["_id"]),
                    "vehicle_registration_number": vehicle.get("registration_number"),
                    "message": f"Insurance has expired for vehicle {vehicle.get('registration_number')}.",
                }
            )
        elif days_to_expiry is not None and days_to_expiry <= 30:
            insurance_alerts.append(
                {
                    "type": "insurance_expiring_soon",
                    "vehicle_id": str(vehicle["_id"]),
                    "vehicle_registration_number": vehicle.get("registration_number"),
                    "message": f"Insurance expires in {days_to_expiry} day(s) for vehicle {vehicle.get('registration_number')}.",
                }
            )

    incident_alerts = []
    for item in documents:
        claim = item.get("insurance_claim") or {}
        if claim.get("status") == "Expired":
            incident_alerts.append(
                {
                    "type": "incident_reported_with_expired_insurance",
                    "incident_id": str(item["_id"]),
                    "message": "Incident was reported with expired insurance coverage.",
                }
            )
        if claim.get("status") == "Missing":
            incident_alerts.append(
                {
                    "type": "incident_reported_with_no_insurance",
                    "incident_id": str(item["_id"]),
                    "message": "Incident was reported for a vehicle with no insurance details linked.",
                }
            )

    return {
        "summary": {
            "total_incidents": len(documents),
            "open_incidents": open_incidents,
            "repair_cost": total_repair_cost,
            "insurance_approved_amount": total_approved,
            "amount_paid": total_paid,
            "outstanding_claim": total_outstanding,
            "downtime_days": total_downtime_days,
            "estimated_revenue_lost": total_revenue_lost,
        },
        "high_risk_drivers": sorted(
            driver_summary.values(),
            key=lambda item: (
                -item["incident_count"],
                -item["critical_incidents"],
                -item["downtime_days"],
            ),
        )[:5],
        "insurance_directory": sorted(
            insurance_directory,
            key=lambda item: (
                item.get("status") != "Expired",
                item.get("renewal_date") or "9999-12-31",
            ),
        ),
        "alerts": insurance_alerts + incident_alerts,
    }


def list_incidents(*, current_user_id: str, current_role: str) -> dict:
    query = {}
    if current_role == "driver":
        query["driver_id"] = _to_object_id(current_user_id, "current_user_id")
    documents = list(incidents_collection().find(query).sort([("incident_at", DESCENDING), ("created_at", DESCENDING)]))
    vehicle_map, user_map = _load_relationship_maps(documents)
    dashboard = _build_dashboard(documents, vehicle_map=vehicle_map)
    return {
        "incidents": [_enrich_incident(document, vehicle_map=vehicle_map, user_map=user_map) for document in documents],
        "dashboard": dashboard["summary"],
        "high_risk_drivers": dashboard["high_risk_drivers"],
        "insurance_directory": dashboard["insurance_directory"],
        "alerts": dashboard["alerts"],
        "status_options": sorted(ALLOWED_INCIDENT_STATUSES),
    }


def get_incident_by_id(incident_id: str, *, current_user_id: str, current_role: str) -> dict:
    document = _get_incident_document(incident_id)
    if current_role == "driver" and str(document.get("driver_id")) != current_user_id:
        raise ApiError("You can only view incidents you reported.", status_code=403)
    return _enrich_incident(document)


def create_incident(payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin", "driver"}:
        raise ApiError("You do not have permission to report incidents.", status_code=403)

    incident_type = _validate_incident_type(payload.get("incident_type"))
    incident_at = _parse_datetime(payload.get("incident_at"), "incident_at", required=True)
    location = _normalize_string(payload.get("location"))
    description = _normalize_string(payload.get("description"))
    if not location:
        raise ApiError("Please enter where the incident happened.", status_code=400)
    if not description:
        raise ApiError("Please describe what happened.", status_code=400)

    if current_role == "driver":
        driver_object_id, vehicle_object_id = _validate_driver_incident_scope(
            current_user_id=current_user_id,
            vehicle_id=payload.get("vehicle_id"),
            driver_id=payload.get("driver_id"),
        )
    else:
        driver_object_id = _to_object_id(payload.get("driver_id"), "driver_id")
        vehicle_object_id = _to_object_id(payload.get("vehicle_id"), "vehicle_id")
        driver_document = _get_user_document(driver_object_id, "driver_id")
        if driver_document.get("role") != "driver":
            raise ApiError("Please select a valid driver account.", status_code=400)

    vehicle_document = _get_vehicle_document(vehicle_object_id)

    timestamp = now_utc()
    document = {
        "vehicle_id": vehicle_object_id,
        "driver_id": driver_object_id,
        "replacement_vehicle_id": None,
        "maintenance_job_id": None,
        "incident_type": incident_type,
        "status": "reported",
        "incident_at": incident_at,
        "location": location,
        "description": description,
        "can_vehicle_move": _validate_boolean(payload.get("can_vehicle_move"), "can_vehicle_move", required=True),
        "third_party_involved": _validate_boolean(payload.get("third_party_involved"), "third_party_involved", required=True),
        "witness_name": _normalize_string(payload.get("witness_name")),
        "witness_phone": _normalize_string(payload.get("witness_phone")),
        "police_station": _normalize_string(payload.get("police_station")),
        "police_report_number": _normalize_string(payload.get("police_report_number")),
        "attachments": _validate_attachments(payload.get("attachments") or payload.get("photos") or []),
        "investigation_notes": [],
        "claim_number": None,
        "claim_submitted_date": None,
        "assessment_date": None,
        "claim_status": "not_started",
        "repair_cost": None,
        "insurance_approved_amount": None,
        "paid_amount": None,
        "outstanding_claim": 0.0,
        "downtime_start_date": None,
        "downtime_end_date": None,
        "downtime_days": 0,
        "estimated_revenue_lost": None,
        "vehicle_status_after_incident": None,
        "insurance_claim": _build_vehicle_insurance_snapshot(vehicle_document, incident_type=incident_type),
        "emergency_checklist": EMERGENCY_CHECKLIST,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "updated_by": _to_object_id(current_user_id, "updated_by"),
        "created_at": timestamp,
        "updated_at": timestamp,
        "audit_logs": [],
    }
    _update_outstanding_claim_fields(document)
    _update_downtime_fields(document, vehicle_document=vehicle_document)
    document["vehicle_status_after_incident"] = _status_for_incident_vehicle(document)

    result = incidents_collection().insert_one(document)
    document["_id"] = result.inserted_id
    _sync_vehicle_status_for_incident(document)
    _append_audit_log(
        document,
        action="incident_reported",
        actor_id=current_user_id,
        actor_role=current_role,
        changes=["Initial incident report submitted."],
        note=document.get("description"),
    )

    notify_roles(
        ["owner", "admin"],
        title="New Incident Reported",
        message=f"An incident was reported for vehicle {vehicle_document.get('registration_number')}.",
        category="maintenance",
        priority="high",
        reference_type="incident",
        reference_id=document["_id"],
    )
    if document["insurance_claim"].get("status") in {"Expired", "Missing"}:
        notify_roles(
            ["owner", "admin"],
            title="Incident Insurance Warning",
            message=(
                "This incident was reported with expired insurance."
                if document["insurance_claim"].get("status") == "Expired"
                else "This incident was reported with no linked insurance details."
            ),
            category="maintenance",
            priority="high",
            reference_type="incident",
            reference_id=document["_id"],
        )

    return _enrich_incident(document)


def update_incident(incident_id: str, payload: dict, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only admins and owners can update incidents.", status_code=403)

    document = _get_incident_document(incident_id)
    vehicle_document = _get_vehicle_document(document.get("vehicle_id"))
    update_fields: dict = {}
    audit_changes: list[str] = []

    if "status" in payload:
        next_status = _validate_incident_status(payload.get("status"))
        update_fields["status"] = next_status
        audit_changes.append(f"Status changed to {next_status.replace('_', ' ')}.")

    if "investigation_note" in payload:
        note = _normalize_string(payload.get("investigation_note"))
        if note:
            note_entry = {
                "id": str(uuid4()),
                "note": note,
                "created_at": now_utc().isoformat(),
                "created_by": current_user_id,
                "created_by_role": current_role,
            }
            update_fields["$push_investigation_note"] = note_entry
            audit_changes.append("Investigation note added.")

    if "attachments" in payload:
        attachments = _validate_attachments(payload.get("attachments"))
        if attachments:
            update_fields["$push_attachments"] = attachments
            audit_changes.append(f"{len(attachments)} attachment(s) added.")

    if "replacement_vehicle_id" in payload:
        replacement_vehicle_id = _to_object_id(payload.get("replacement_vehicle_id"), "replacement_vehicle_id", required=False)
        if replacement_vehicle_id:
            _get_vehicle_document(replacement_vehicle_id)
        update_fields["replacement_vehicle_id"] = replacement_vehicle_id
        audit_changes.append("Replacement vehicle updated.")

    if "vehicle_status_after_incident" in payload:
        vehicle_status = _normalize_slug(payload.get("vehicle_status_after_incident"))
        if vehicle_status not in {"accident", "out_of_service", "available", "assigned", "maintenance", "suspended"}:
            raise ApiError("Please choose a valid vehicle status for this incident.", status_code=400)
        update_fields["vehicle_status_after_incident"] = vehicle_status
        audit_changes.append(f"Vehicle status set to {vehicle_status.replace('_', ' ')}.")

    if "claim_number" in payload:
        update_fields["claim_number"] = _normalize_string(payload.get("claim_number"))
        audit_changes.append("Claim number updated.")
    if "claim_submitted_date" in payload:
        update_fields["claim_submitted_date"] = _serialize_date(
            _parse_date(payload.get("claim_submitted_date"), "claim_submitted_date", required=False)
        )
        audit_changes.append("Claim submitted date updated.")
    if "assessment_date" in payload:
        update_fields["assessment_date"] = _serialize_date(
            _parse_date(payload.get("assessment_date"), "assessment_date", required=False)
        )
        audit_changes.append("Assessment date updated.")
    if "claim_status" in payload:
        update_fields["claim_status"] = _validate_claim_status(payload.get("claim_status"))
        audit_changes.append("Claim status updated.")
    if "repair_cost" in payload:
        update_fields["repair_cost"] = _validate_amount(payload.get("repair_cost"), "repair_cost")
        audit_changes.append("Repair cost updated.")
    if "insurance_approved_amount" in payload:
        update_fields["insurance_approved_amount"] = _validate_amount(
            payload.get("insurance_approved_amount"),
            "insurance_approved_amount",
        )
        audit_changes.append("Insurance approved amount updated.")
    if "paid_amount" in payload:
        update_fields["paid_amount"] = _validate_amount(payload.get("paid_amount"), "paid_amount")
        audit_changes.append("Paid amount updated.")
    if "estimated_revenue_lost" in payload:
        update_fields["estimated_revenue_lost"] = _validate_amount(
            payload.get("estimated_revenue_lost"),
            "estimated_revenue_lost",
        )
        audit_changes.append("Estimated revenue lost updated.")
    if "downtime_start_date" in payload:
        update_fields["downtime_start_date"] = _serialize_date(
            _parse_date(payload.get("downtime_start_date"), "downtime_start_date", required=False)
        )
        audit_changes.append("Downtime start updated.")
    if "downtime_end_date" in payload:
        update_fields["downtime_end_date"] = _serialize_date(
            _parse_date(payload.get("downtime_end_date"), "downtime_end_date", required=False)
        )
        audit_changes.append("Downtime end updated.")

    if "insurance_notified" in payload:
        insurance_notified = _validate_boolean(payload.get("insurance_notified"), "insurance_notified", required=True)
        claim_snapshot = dict(document.get("insurance_claim") or {})
        claim_snapshot["insurance_notified"] = insurance_notified
        claim_snapshot["insurance_notified_at"] = now_utc() if insurance_notified else None
        update_fields["insurance_claim"] = claim_snapshot
        if insurance_notified and "status" not in payload:
            update_fields["status"] = "insurance_notified"
        audit_changes.append("Insurance notification status updated.")

    if "claim_eligibility_override" in payload:
        claim_snapshot = dict(update_fields.get("insurance_claim") or document.get("insurance_claim") or {})
        claim_snapshot["claim_eligibility"] = _validate_claim_eligibility(payload.get("claim_eligibility_override"))
        claim_snapshot["eligibility_overridden"] = True
        claim_snapshot["eligibility_override_reason"] = _normalize_string(payload.get("claim_eligibility_override_reason"))
        if not claim_snapshot["eligibility_override_reason"]:
            raise ApiError("Please include a reason for the claim eligibility override.", status_code=400)
        update_fields["insurance_claim"] = claim_snapshot
        audit_changes.append("Claim eligibility overridden.")

    if not update_fields:
        raise ApiError("Please provide at least one incident update.", status_code=400)

    if update_fields.get("claim_status") is not None and "insurance_claim" not in update_fields:
        claim_snapshot = dict(document.get("insurance_claim") or {})
        claim_snapshot["claim_status"] = update_fields.get("claim_status")
        if "claim_number" in update_fields:
            claim_snapshot["claim_number"] = update_fields.get("claim_number")
        if "claim_submitted_date" in update_fields:
            claim_snapshot["claim_submitted_date"] = update_fields.get("claim_submitted_date")
        if "assessment_date" in update_fields:
            claim_snapshot["assessment_date"] = update_fields.get("assessment_date")
        update_fields["insurance_claim"] = claim_snapshot

    document.update({key: value for key, value in update_fields.items() if not key.startswith("$push_")})
    _update_outstanding_claim_fields(document)
    _update_downtime_fields(document, vehicle_document=vehicle_document)

    update_fields["outstanding_claim"] = document.get("outstanding_claim")
    update_fields["downtime_days"] = document.get("downtime_days")
    update_fields["estimated_revenue_lost"] = document.get("estimated_revenue_lost")
    update_fields["updated_by"] = _to_object_id(current_user_id, "updated_by")
    update_fields["updated_at"] = now_utc()

    mongo_update = {"$set": {key: value for key, value in update_fields.items() if not key.startswith("$push_")}}
    if update_fields.get("$push_investigation_note"):
        mongo_update.setdefault("$push", {})["investigation_notes"] = update_fields["$push_investigation_note"]
        document.setdefault("investigation_notes", []).append(update_fields["$push_investigation_note"])
    if update_fields.get("$push_attachments"):
        mongo_update.setdefault("$push", {})["attachments"] = {"$each": update_fields["$push_attachments"]}
        document.setdefault("attachments", []).extend(update_fields["$push_attachments"])

    incidents_collection().update_one({"_id": document["_id"]}, mongo_update)
    if "status" in update_fields or "vehicle_status_after_incident" in update_fields:
        _sync_vehicle_status_for_incident(document)
    _append_audit_log(
        document,
        action="incident_updated",
        actor_id=current_user_id,
        actor_role=current_role,
        changes=audit_changes,
        note=_normalize_string(payload.get("investigation_note")),
        reason=_normalize_string(payload.get("claim_eligibility_override_reason")),
    )
    return _enrich_incident(document)


def create_maintenance_job_from_incident(incident_id: str, *, current_user_id: str, current_role: str) -> dict:
    if current_role not in {"owner", "admin"}:
        raise ApiError("Only admins and owners can create repair jobs from incidents.", status_code=403)
    document = _get_incident_document(incident_id)
    if document.get("maintenance_job_id"):
        raise ApiError("A maintenance job has already been created for this incident.", status_code=400)

    maintenance_job = create_maintenance_job(
        {
            "vehicle_id": str(document.get("vehicle_id")),
            "driver_id": str(document.get("driver_id")) if document.get("driver_id") else None,
            "maintenance_type": "accident_repair" if document.get("incident_type") in {"accident", "third_party_damage", "fire"} else "repair",
            "title": f"Incident Repair - {document.get('incident_type', 'incident').replace('_', ' ').title()}",
            "description": document.get("description") or "Repair created from incident report.",
            "priority": "high" if document.get("incident_type") in {"accident", "injury", "fire", "theft"} else "medium",
            "status": "pending",
            "current_stage": "assigned_to_mechanic",
            "notes": f"Created from incident at {document.get('location')}.",
            "next_action": "Review incident damage and begin assessment.",
        },
        current_user_id=current_user_id,
        current_role=current_role,
    )

    timestamp = now_utc()
    incidents_collection().update_one(
        {"_id": document["_id"]},
        {
            "$set": {
                "maintenance_job_id": ObjectId(maintenance_job["id"]),
                "status": "repair_approved",
                "updated_by": _to_object_id(current_user_id, "updated_by"),
                "updated_at": timestamp,
            }
        },
    )
    document["maintenance_job_id"] = ObjectId(maintenance_job["id"])
    document["status"] = "repair_approved"
    document["updated_by"] = _to_object_id(current_user_id, "updated_by")
    document["updated_at"] = timestamp
    _sync_vehicle_status_for_incident(document)
    _append_audit_log(
        document,
        action="maintenance_job_created",
        actor_id=current_user_id,
        actor_role=current_role,
        changes=["Repair job created from incident."],
    )
    return {
        "incident": _enrich_incident(document),
        "job": maintenance_job,
    }
