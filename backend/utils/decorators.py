from functools import wraps

from flask import current_app, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from utils.responses import error_response


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
