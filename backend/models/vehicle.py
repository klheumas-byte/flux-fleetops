from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_vehicle(vehicle_document: dict, *, include_sensitive: bool = True) -> dict:
    insurance_profile = vehicle_document.get("insurance_profile") or {}
    data = {
        "id": str(vehicle_document.get("_id")),
        "registration_number": vehicle_document.get("registration_number"),
        "vehicle_type": vehicle_document.get("vehicle_type"),
        "make": vehicle_document.get("make"),
        "model": vehicle_document.get("model"),
        "year": vehicle_document.get("year"),
        "color": vehicle_document.get("color"),
        "transmission": vehicle_document.get("transmission"),
        "fuel_type": vehicle_document.get("fuel_type"),
        "chassis_number": vehicle_document.get("chassis_number"),
        "engine_number": vehicle_document.get("engine_number"),
        "insurance_expiry": vehicle_document.get("insurance_expiry"),
        "insurance_profile": {
            "insurance_company": insurance_profile.get("insurance_company"),
            "policy_number": insurance_profile.get("policy_number"),
            "insurance_type": insurance_profile.get("insurance_type"),
            "start_date": insurance_profile.get("start_date"),
            "expiry_date": insurance_profile.get("expiry_date"),
            "coverage_duration_months": insurance_profile.get("coverage_duration_months"),
            "claims_officer_name": insurance_profile.get("claims_officer_name"),
            "claims_officer_phone": insurance_profile.get("claims_officer_phone"),
            "claims_officer_email": insurance_profile.get("claims_officer_email"),
            "emergency_contact": insurance_profile.get("emergency_contact"),
            "excess_amount": insurance_profile.get("excess_amount"),
            "covered_risks": insurance_profile.get("covered_risks") or [],
            "excluded_risks": insurance_profile.get("excluded_risks") or [],
        },
        "roadworthy_expiry": vehicle_document.get("roadworthy_expiry"),
        "default_weekly_target": vehicle_document.get("default_weekly_target"),
        "default_daily_target": vehicle_document.get("default_daily_target"),
        "current_odometer": vehicle_document.get("current_odometer"),
        "vehicle_cost_items": vehicle_document.get("vehicle_cost_items") or [],
        "economics": vehicle_document.get("economics"),
        "status": vehicle_document.get("status"),
        "assigned_driver_id": _serialize_reference_id(vehicle_document.get("assigned_driver_id")),
        "assigned_driver_details": vehicle_document.get("assigned_driver_details"),
        "created_by": _serialize_reference_id(vehicle_document.get("created_by")),
        "updated_by": _serialize_reference_id(vehicle_document.get("updated_by")),
        "created_at": vehicle_document.get("created_at").isoformat()
        if vehicle_document.get("created_at")
        else None,
        "updated_at": vehicle_document.get("updated_at").isoformat()
        if vehicle_document.get("updated_at")
        else None,
    }
    if include_sensitive:
        data["purchase_cost"] = vehicle_document.get("purchase_cost")
        data["insurance_cost"] = vehicle_document.get("insurance_cost")
        data["roadworthy_cost"] = vehicle_document.get("roadworthy_cost")
        data["shipping_cost"] = vehicle_document.get("shipping_cost")
        data["clearing_cost"] = vehicle_document.get("clearing_cost")
        data["ama_permit_cost"] = vehicle_document.get("ama_permit_cost")
        data["vehicle_license_cost"] = vehicle_document.get("vehicle_license_cost")
        data["tracker_cost"] = vehicle_document.get("tracker_cost")
        data["branding_cost"] = vehicle_document.get("branding_cost")
        data["initial_repairs_cost"] = vehicle_document.get("initial_repairs_cost")
        data["registration_cost"] = vehicle_document.get("registration_cost")
        data["other_setup_cost"] = vehicle_document.get("other_setup_cost")
    return data
