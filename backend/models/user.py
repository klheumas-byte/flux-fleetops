from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _normalize_role(value):
    if value is None:
        return None
    return str(value).strip().lower() or None


def serialize_driver_profile(user_document: dict) -> dict | None:
    role_ids = [_normalize_role(item) for item in user_document.get("role_ids", [])]
    if _normalize_role(user_document.get("role")) != "driver" and "driver" not in role_ids:
        return None

    driver_profile = user_document.get("driver_profile") or {}
    legacy_guarantor = user_document.get("guarantor")
    guarantor = driver_profile.get("guarantor") if isinstance(driver_profile, dict) else None

    if guarantor is None and legacy_guarantor is not None:
        guarantor = legacy_guarantor

    if not driver_profile and guarantor is None:
        return None

    return {
        "ghana_card_number": driver_profile.get("ghana_card_number"),
        "license_number": driver_profile.get("license_number"),
        "license_expiry": driver_profile.get("license_expiry"),
        "license_class": driver_profile.get("license_class"),
        "years_experience": driver_profile.get("years_experience"),
        "can_drive_manual": driver_profile.get("can_drive_manual"),
        "can_drive_automatic": driver_profile.get("can_drive_automatic"),
        "emergency_contact_name": driver_profile.get("emergency_contact_name"),
        "emergency_contact_phone": driver_profile.get("emergency_contact_phone"),
        "deposit_required": driver_profile.get("deposit_required"),
        "deposit_paid": driver_profile.get("deposit_paid"),
        "deposit_balance": driver_profile.get("deposit_balance"),
        "approval_status": driver_profile.get("approval_status"),
        "assigned_vehicle_id": _serialize_reference_id(driver_profile.get("assigned_vehicle_id")),
        "operating_mode": driver_profile.get("operating_mode") or "hybrid",
        "target_enabled": driver_profile.get("target_enabled", True),
        "target_amount": driver_profile.get("target_amount"),
        "target_frequency": driver_profile.get("target_frequency") or "weekly",
        "private_finance_enabled": driver_profile.get("private_finance_enabled", False),
        "settings_effective_date": driver_profile.get("settings_effective_date"),
        "settings_history": [
            {
                **entry,
                "changed_by": _serialize_reference_id(entry.get("changed_by")),
                "changed_at": entry.get("changed_at").isoformat()
                if hasattr(entry.get("changed_at"), "isoformat")
                else entry.get("changed_at"),
            }
            for entry in driver_profile.get("settings_history", [])
        ],
        "guarantor": guarantor,
    }


def serialize_user(user_document: dict) -> dict:
    from services.rbac_service import effective_data_scope, permissions_for_user, primary_workspace, role_definition, user_role_codes

    role = _normalize_role(user_document.get("role") or user_document.get("user_type"))
    role_ids = user_role_codes(user_document)
    role = role or (role_ids[0] if role_ids else None)
    workspace = primary_workspace(user_document) or role
    definition = role_definition(workspace)
    canonical_roles = []
    for code in role_ids:
        role_info = role_definition(code)
        canonical_roles.append({
            "id": str(role_info.get("_id") or code),
            "code": code,
            "name": role_info.get("name") or code.replace("_", " ").title(),
            "active": role_info.get("status", "active") == "active",
            "dashboard": role_info.get("dashboard") or "dashboard",
        })
    return {
        "id": str(user_document.get("_id")),
        "full_name": user_document.get("full_name"),
        "email": user_document.get("email"),
        "phone": user_document.get("phone"),
        "role": role,
        "role_ids": role_ids,
        "roles": canonical_roles,
        "selected_workspace": workspace,
        "role_name": definition.get("name") or str(role or "").replace("_", " ").title(),
        "permissions": permissions_for_user(user_document),
        "dashboard": definition.get("dashboard") or "dashboard",
        "data_scope": effective_data_scope(user_document),
        "username": user_document.get("username"),
        "branch": user_document.get("branch"),
        "primary_branch_id": _serialize_reference_id(user_document.get("primary_branch_id")),
        "allowed_branch_ids": [_serialize_reference_id(value) for value in user_document.get("allowed_branch_ids", [])],
        "operational_scope": user_document.get("operational_scope") or ("BRANCH" if user_document.get("home_branch_id") or user_document.get("primary_branch_id") else "COMPANY_WIDE"),
        "home_branch_id": _serialize_reference_id(user_document.get("home_branch_id") or user_document.get("primary_branch_id")),
        "created_by": _serialize_reference_id(user_document.get("created_by")),
        "permission_grants": user_document.get("permission_grants", []),
        "permission_denials": user_document.get("permission_denials", []),
        "status": user_document.get("status"),
        "active": str(user_document.get("status") or "").strip().lower() == "active",
        "last_login": user_document.get("last_login").isoformat() if user_document.get("last_login") else None,
        "created_at": user_document.get("created_at").isoformat() if user_document.get("created_at") else None,
        "updated_at": user_document.get("updated_at").isoformat() if user_document.get("updated_at") else None,
        "must_change_password": bool(user_document.get("must_change_password", False)),
        "password_changed_at": user_document.get("password_changed_at").isoformat() if user_document.get("password_changed_at") else None,
        "driver_profile": serialize_driver_profile(user_document),
    }
