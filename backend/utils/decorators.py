from functools import wraps

from flask import current_app, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from utils.responses import error_response
from extensions import get_collection
from bson import ObjectId


PASSWORD_CHANGE_EXEMPT_PATHS = {
    "/api/auth/me",
    "/api/auth/change-password",
    "/api/auth/logout",
}


def _current_account_denial():
    """Enforce mutable account state rather than trusting a stale JWT claim."""
    if not current_app.config.get("MONGO_URI"):
        return None
    current_user_id = get_jwt_identity()
    if not ObjectId.is_valid(str(current_user_id)):
        return error_response("Invalid user identity.", status_code=401)
    user = get_collection("users").find_one(
        {"_id": ObjectId(str(current_user_id))},
        {"status": 1, "must_change_password": 1},
    )
    if not user:
        return error_response("User account no longer exists.", status_code=401)
    if str(user.get("status") or "").strip().lower() != "active":
        return error_response("This account is not active.", status_code=403)
    if user.get("must_change_password") and request.path not in PASSWORD_CHANGE_EXEMPT_PATHS:
        return error_response(
            "You must change your temporary password before continuing.",
            status_code=428,
        )
    return None


def _normalize_role(value):
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 200

        @jwt_required()
        def protected():
            denial = _current_account_denial()
            if denial is not None:
                return denial
            current_app.logger.info(
                "[Flux Auth] authorized endpoint=%s method=%s user_id=%s role=%s decision=allow reason=login_required",
                request.path,
                request.method,
                get_jwt_identity(),
                _normalize_role(get_jwt().get("role")) or "unknown",
            )
            return fn(*args, **kwargs)

        return protected()

    return wrapper


def role_required(*allowed_roles: str):
    normalized_allowed_roles = tuple(filter(None, (_normalize_role(role) for role in allowed_roles)))

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if request.method == "OPTIONS":
                return "", 200

            @jwt_required()
            def protected():
                current_role = _normalize_role(get_jwt().get("role"))
                current_user_id = get_jwt_identity()
                if current_role not in normalized_allowed_roles:
                    current_app.logger.warning(
                        "[Flux Auth] authorized endpoint=%s method=%s user_id=%s role=%s decision=reject reason=role_not_allowed allowed_roles=%s",
                        request.path,
                        request.method,
                        current_user_id,
                        current_role or "unknown",
                        ",".join(normalized_allowed_roles),
                    )
                    return error_response(
                        "You do not have permission to access this resource.",
                        status_code=403,
                    )
                denial = _current_account_denial()
                if denial is not None:
                    return denial
                current_app.logger.info(
                    "[Flux Auth] authorized endpoint=%s method=%s user_id=%s role=%s decision=allow allowed_roles=%s",
                    request.path,
                    request.method,
                    current_user_id,
                    current_role or "unknown",
                    ",".join(normalized_allowed_roles),
                )
                return fn(*args, **kwargs)

            return protected()

        return wrapper

    return decorator


def driver_mode_required(capability: str):
    if capability not in {"operations", "targets"}:
        raise ValueError("Driver capability must be operations or targets.")

    allowed_modes = {
        "operations": {"operations_only", "hybrid"},
        "targets": {"target_only", "hybrid"},
    }[capability]

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            current_user_id = get_jwt_identity()
            if not ObjectId.is_valid(str(current_user_id)):
                return error_response("Invalid user identity.", status_code=401)
            if not current_app.config.get("MONGO_URI"):
                # Small isolated route tests and legacy integrations may not
                # configure MongoDB. Preserve the pre-Sprint-4 hybrid default.
                mode = get_jwt().get("operating_mode") or "hybrid"
            else:
                # Operating mode is mutable. Authorize from current settings,
                # never the stale snapshot embedded in the login token.
                driver = get_collection("users").find_one(
                    {"_id": ObjectId(str(current_user_id)), "role": "driver"},
                    {"driver_profile.operating_mode": 1},
                )
                mode = ((driver or {}).get("driver_profile") or {}).get("operating_mode") or "hybrid"
            if mode not in allowed_modes:
                return error_response(
                    f"Your driver operating mode does not allow {capability} access.",
                    status_code=403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


DRIVER_TARGET_PATHS = {
    "/api/driver/dashboard-summary",
    "/api/driver/wallet",
    "/api/driver/payments",
}
DRIVER_TARGET_PATH_PREFIXES = (
    "/api/driver/private-finance",
    "/api/bookings",
    "/api/calendar",
    "/api/customers",
)
DRIVER_OPERATION_PATH_PREFIXES = (
    "/api/dispatch",
    "/api/dispatch-planner",
    "/api/dispatch-requests",
    "/api/expenses",
    "/api/fuel-logs",
    "/api/fuel-stations",
    "/api/operational-requests",
    "/api/rides",
    "/api/stock-transfers",
    "/api/vehicle-movements",
    "/api/waybills",
)

DRIVER_UNIVERSAL_SAFETY_PREFIXES = (
    "/api/faults",
    "/api/incidents",
    "/api/maintenance-overrides",
    "/api/assignments/my-handovers",
    "/api/driver/maintenance",
    "/api/driver/preventive-maintenance",
)


def request_driver_capability(path: str) -> str | None:
    normalized_path = path.rstrip("/") or "/"
    if any(normalized_path.startswith(prefix) for prefix in DRIVER_UNIVERSAL_SAFETY_PREFIXES):
        return None
    if normalized_path in DRIVER_TARGET_PATHS:
        return "targets"
    if any(normalized_path.startswith(prefix) for prefix in DRIVER_TARGET_PATH_PREFIXES):
        return "targets"
    if normalized_path.startswith("/api/driver/") and normalized_path != "/api/driver/active-assignment":
        return "operations"
    if any(normalized_path.startswith(prefix) for prefix in DRIVER_OPERATION_PATH_PREFIXES):
        return "operations"
    return None
