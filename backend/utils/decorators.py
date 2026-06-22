from functools import wraps

from flask_jwt_extended import get_jwt, jwt_required

from utils.responses import error_response


def login_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


def role_required(*allowed_roles: str):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            current_role = get_jwt().get("role")
            if current_role not in allowed_roles:
                return error_response(
                    "You do not have permission to access this resource.",
                    status_code=403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
