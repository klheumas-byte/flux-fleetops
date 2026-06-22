from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_customer(customer_document: dict) -> dict:
    created_at = customer_document.get("created_at")
    updated_at = customer_document.get("updated_at")
    legacy_creator_name = customer_document.get("created_by_name") or "Unknown / Legacy Record"
    legacy_creator_role = customer_document.get("created_by_role") or (
        "legacy" if not customer_document.get("created_by_user_id") and not customer_document.get("created_by") else None
    )
    return {
        "id": str(customer_document.get("_id")),
        "customer_id": customer_document.get("customer_id"),
        "full_name": customer_document.get("full_name"),
        "phone_number": customer_document.get("phone_number"),
        "alternate_phone": customer_document.get("alternate_phone"),
        "email_address": customer_document.get("email_address"),
        "date_of_birth": customer_document.get("date_of_birth"),
        "occupation": customer_document.get("occupation"),
        "organization_name": customer_document.get("organization_name"),
        "position_title": customer_document.get("position_title"),
        "pickup_location": customer_document.get("pickup_location"),
        "destination_location": customer_document.get("destination_location"),
        "preferred_pickup_location": customer_document.get("preferred_pickup_location"),
        "preferred_dropoff_location": customer_document.get("preferred_dropoff_location"),
        "residential_area": customer_document.get("residential_area"),
        "work_area": customer_document.get("work_area"),
        "customer_category_id": _serialize_reference_id(customer_document.get("customer_category_id")),
        "customer_category": customer_document.get("customer_category"),
        "customer_source_id": _serialize_reference_id(customer_document.get("customer_source_id")),
        "customer_source": customer_document.get("customer_source"),
        "organization_type_id": _serialize_reference_id(customer_document.get("organization_type_id")),
        "organization_type": customer_document.get("organization_type"),
        "industry_id": _serialize_reference_id(customer_document.get("industry_id")),
        "industry": customer_document.get("industry"),
        "company_name": customer_document.get("company_name"),
        "company_industry": customer_document.get("company_industry"),
        "relationship_category_id": _serialize_reference_id(customer_document.get("relationship_category_id")),
        "relationship_category": customer_document.get("relationship_category"),
        "opportunity_level_id": _serialize_reference_id(customer_document.get("opportunity_level_id")),
        "opportunity_level": customer_document.get("opportunity_level"),
        "network_value_id": _serialize_reference_id(customer_document.get("network_value_id")),
        "network_value": customer_document.get("network_value"),
        "is_transport_customer": bool(customer_document.get("is_transport_customer", False)),
        "is_business_lead": bool(customer_document.get("is_business_lead", False)),
        "lead_status_id": _serialize_reference_id(customer_document.get("lead_status_id")),
        "lead_status": customer_document.get("lead_status"),
        "potential_service_id": _serialize_reference_id(customer_document.get("potential_service_id")),
        "potential_service": customer_document.get("potential_service"),
        "lead_value_estimate": customer_document.get("lead_value_estimate"),
        "follow_up_date": customer_document.get("follow_up_date"),
        "next_follow_up_date": customer_document.get("next_follow_up_date"),
        "follow_up_priority": customer_document.get("follow_up_priority"),
        "follow_up_completed_at": customer_document.get("follow_up_completed_at").isoformat()
        if customer_document.get("follow_up_completed_at")
        else None,
        "preferred_driver_id": _serialize_reference_id(customer_document.get("preferred_driver_id")),
        "assigned_driver_id": _serialize_reference_id(customer_document.get("preferred_driver_id")),
        "notes": customer_document.get("notes"),
        "relationship_notes": customer_document.get("relationship_notes"),
        "lead_notes": customer_document.get("lead_notes"),
        "important_notes": customer_document.get("important_notes"),
        "referred_by": customer_document.get("referred_by"),
        "status": customer_document.get("status"),
        "created_by": _serialize_reference_id(customer_document.get("created_by")),
        "created_by_user_id": _serialize_reference_id(customer_document.get("created_by_user_id") or customer_document.get("created_by")),
        "created_by_name": legacy_creator_name,
        "created_by_role": legacy_creator_role,
        "created_by_driver_id": _serialize_reference_id(customer_document.get("created_by_driver_id")),
        "source": customer_document.get("source"),
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "follow_up_history": [
            {
                "action": event.get("action"),
                "date": event.get("date"),
                "next_follow_up_date": event.get("next_follow_up_date"),
                "priority": event.get("priority"),
                "note": event.get("note"),
                "at": event.get("at").isoformat() if event.get("at") else None,
                "by": _serialize_reference_id(event.get("by")),
            }
            for event in customer_document.get("follow_up_history", [])
        ],
        "audit_events": [
            {
                "action": event.get("action"),
                "at": event.get("at").isoformat() if event.get("at") else None,
                "by": _serialize_reference_id(event.get("by")),
                "changes": event.get("changes") or [],
                "note": event.get("note"),
            }
            for event in customer_document.get("audit_events", [])
        ],
    }
