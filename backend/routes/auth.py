from flask import Blueprint, request
from flask_jwt_extended import get_jwt, get_jwt_identity
from flask import current_app
from pymongo.errors import PyMongoError

from services.auth_service import (
    authenticate_user,
    build_auth_payload,
    create_user,
    get_user_by_id,
    revoke_token,
)
from utils.decorators import login_required
from utils.api_error import ApiError
from utils.responses import error_response, success_response


auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
def register():
    payload = request.get_json(silent=True) or {}
    requested_role = payload.get("role", "driver")

    if requested_role != "driver":
        return error_response(
            "Only driver self-registration is allowed. Owner and admin accounts must be created internally.",
            status_code=403,
        )

    driver_payload = {**payload, "status": "inactive"}
    user = create_user(driver_payload, role="driver")
    return success_response(
        data={"user": user},
        message="Driver account created successfully and is pending approval.",
        status_code=201,
    )


@auth_bp.post("/login")
def login():
    try:
        payload = request.get_json(silent=True) or {}
        identifier = payload.get("identifier") or payload.get("email") or payload.get("phone")
        password = payload.get("password")

        if not identifier or not password:
            return error_response("Identifier and password are required.", status_code=400)

        auth_result = authenticate_user(identifier=identifier, password=password)
        return success_response(
            data=build_auth_payload(auth_result["user"], auth_result["access_token"]),
            message="Login successful.",
        )
    except ApiError:
        raise
    except PyMongoError as error:
        current_app.logger.exception("[Flux Auth] Login database error: %s", error)
        return error_response(
            "Authentication data store is temporarily unavailable.",
            status_code=503,
            public_message="Authentication is temporarily unavailable. Please try again.",
        )


@auth_bp.get("/me")
@login_required
def me():
    try:
        current_app.logger.info(
            "[Flux Auth] endpoint=/api/auth/me method=GET user_id=%s role=%s decision=allow reason=session_lookup",
            get_jwt_identity(),
            str(get_jwt().get("role") or "").strip().lower() or "unknown",
        )
        user = get_user_by_id(get_jwt_identity())
        return success_response(data={"user": user})
    except ApiError:
        raise
    except PyMongoError as error:
        current_app.logger.exception("[Flux Auth] Session lookup database error: %s", error)
        return error_response(
            "Authentication data store is temporarily unavailable.",
            status_code=503,
            public_message="Authentication is temporarily unavailable. Please try again.",
        )


@auth_bp.post("/logout")
@login_required
def logout():
    token_payload = get_jwt()
    revoke_token(token_payload["jti"], token_payload["exp"])
    return success_response(message="Logout successful.")
