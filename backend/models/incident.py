from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_incident_attachment(attachment_document: dict) -> dict:
    return {
        "id": attachment_document.get("id"),
        "name": attachment_document.get("name"),
        "file_name": attachment_document.get("file_name"),
        "file_kind": attachment_document.get("file_kind"),
        "content_type": attachment_document.get("content_type"),
        "data_url": attachment_document.get("data_url"),
        "size_bytes": attachment_document.get("size_bytes"),
        "uploaded_at": attachment_document.get("uploaded_at").isoformat()
        if attachment_document.get("uploaded_at")
        else None,
    }


def serialize_incident_audit_log(audit_document: dict) -> dict:
    return {
        "id": audit_document.get("id"),
        "action": audit_document.get("action"),
        "actor_id": _serialize_reference_id(audit_document.get("actor_id")),
        "actor_role": audit_document.get("actor_role"),
        "note": audit_document.get("note"),
        "reason": audit_document.get("reason"),
        "changes": audit_document.get("changes") or [],
        "created_at": audit_document.get("created_at").isoformat()
        if audit_document.get("created_at")
        else None,
    }


def serialize_vehicle_insurance_snapshot(snapshot_document: dict | None) -> dict | None:
    if not snapshot_document:
        return None
    return {
        "company": snapshot_document.get("company"),
        "policy_number": snapshot_document.get("policy_number"),
        "insurance_type": snapshot_document.get("insurance_type"),
        "start_date": snapshot_document.get("start_date"),
        "expiry_date": snapshot_document.get("expiry_date"),
        "coverage_duration_months": snapshot_document.get("coverage_duration_months"),
        "claims_officer_name": snapshot_document.get("claims_officer_name"),
        "claims_officer_phone": snapshot_document.get("claims_officer_phone"),
        "claims_officer_email": snapshot_document.get("claims_officer_email"),
        "emergency_contact": snapshot_document.get("emergency_contact"),
        "excess_amount": snapshot_document.get("excess_amount"),
        "covered_risks": snapshot_document.get("covered_risks") or [],
        "excluded_risks": snapshot_document.get("excluded_risks") or [],
        "status": snapshot_document.get("status"),
        "claim_eligibility": snapshot_document.get("claim_eligibility"),
        "eligibility_reason": snapshot_document.get("eligibility_reason"),
        "eligibility_overridden": bool(snapshot_document.get("eligibility_overridden")),
        "eligibility_override_reason": snapshot_document.get("eligibility_override_reason"),
        "claim_number": snapshot_document.get("claim_number"),
        "claim_submitted_date": snapshot_document.get("claim_submitted_date"),
        "assessment_date": snapshot_document.get("assessment_date"),
        "claim_status": snapshot_document.get("claim_status"),
        "insurance_notified": bool(snapshot_document.get("insurance_notified")),
        "insurance_notified_at": snapshot_document.get("insurance_notified_at").isoformat()
        if snapshot_document.get("insurance_notified_at")
        else None,
    }


def serialize_incident(incident_document: dict) -> dict:
    return {
        "id": str(incident_document.get("_id")),
        "vehicle_id": _serialize_reference_id(incident_document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(incident_document.get("driver_id")),
        "replacement_vehicle_id": _serialize_reference_id(incident_document.get("replacement_vehicle_id")),
        "maintenance_job_id": _serialize_reference_id(incident_document.get("maintenance_job_id")),
        "incident_type": incident_document.get("incident_type"),
        "status": incident_document.get("status"),
        "incident_at": incident_document.get("incident_at").isoformat()
        if incident_document.get("incident_at")
        else None,
        "location": incident_document.get("location"),
        "description": incident_document.get("description"),
        "can_vehicle_move": incident_document.get("can_vehicle_move"),
        "third_party_involved": incident_document.get("third_party_involved"),
        "witness_name": incident_document.get("witness_name"),
        "witness_phone": incident_document.get("witness_phone"),
        "police_station": incident_document.get("police_station"),
        "police_report_number": incident_document.get("police_report_number"),
        "attachments": [
            serialize_incident_attachment(item)
            for item in incident_document.get("attachments", [])
        ],
        "investigation_notes": incident_document.get("investigation_notes") or [],
        "claim_number": incident_document.get("claim_number"),
        "claim_submitted_date": incident_document.get("claim_submitted_date"),
        "assessment_date": incident_document.get("assessment_date"),
        "claim_status": incident_document.get("claim_status"),
        "repair_cost": incident_document.get("repair_cost"),
        "insurance_approved_amount": incident_document.get("insurance_approved_amount"),
        "paid_amount": incident_document.get("paid_amount"),
        "outstanding_claim": incident_document.get("outstanding_claim"),
        "downtime_start_date": incident_document.get("downtime_start_date"),
        "downtime_end_date": incident_document.get("downtime_end_date"),
        "downtime_days": incident_document.get("downtime_days"),
        "estimated_revenue_lost": incident_document.get("estimated_revenue_lost"),
        "vehicle_status_after_incident": incident_document.get("vehicle_status_after_incident"),
        "insurance_claim": serialize_vehicle_insurance_snapshot(incident_document.get("insurance_claim")),
        "emergency_checklist": incident_document.get("emergency_checklist") or [],
        "created_by": _serialize_reference_id(incident_document.get("created_by")),
        "updated_by": _serialize_reference_id(incident_document.get("updated_by")),
        "created_at": incident_document.get("created_at").isoformat()
        if incident_document.get("created_at")
        else None,
        "updated_at": incident_document.get("updated_at").isoformat()
        if incident_document.get("updated_at")
        else None,
        "audit_logs": [
            serialize_incident_audit_log(item)
            for item in incident_document.get("audit_logs", [])
        ],
    }
