from flask import current_app, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, PyMongoError, ServerSelectionTimeoutError
from pymongo.read_preferences import ReadPreference

from utils.responses import error_response


cors = CORS()
jwt = JWTManager()
_mongo_client = None


def init_extensions(app):
    cors.init_app(
        app,
        resources={
            r"/api/.*": {
                "origins": app.config["CORS_ORIGINS"],
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization"],
            }
        },
        supports_credentials=False,
        automatic_options=True,
        vary_header=True,
    )
    jwt.init_app(app)
    register_jwt_callbacks()


def register_jwt_callbacks():
    def unauthorized_response():
        return error_response(
            "Unauthorized. Please login again.",
            status_code=401,
            public_message="Unauthorized. Please login again.",
        )

    def log_auth_rejection(reason: str, *, jwt_payload: dict | None = None):
        current_app.logger.warning(
            "[Flux Auth] endpoint=%s method=%s user_id=%s role=%s decision=reject reason=%s has_authorization=%s",
            request.path,
            request.method,
            (jwt_payload or {}).get("sub"),
            str((jwt_payload or {}).get("role") or "").strip().lower() or "unknown",
            reason,
            bool(request.headers.get("Authorization")),
        )

    @jwt.token_in_blocklist_loader
    def is_token_revoked(_jwt_header, jwt_payload):
        token_blocklist = get_collection("token_blocklist").with_options(
            read_preference=ReadPreference.SECONDARY_PREFERRED
        )
        is_revoked = token_blocklist.find_one({"jti": jwt_payload["jti"]}) is not None
        if is_revoked:
            log_auth_rejection("token_revoked", jwt_payload=jwt_payload)
        return is_revoked

    @jwt.unauthorized_loader
    def handle_missing_token(reason):
        log_auth_rejection(f"missing_token:{reason}")
        return unauthorized_response()

    @jwt.invalid_token_loader
    def handle_invalid_token(reason):
        log_auth_rejection(f"invalid_token:{reason}")
        return unauthorized_response()

    @jwt.expired_token_loader
    def handle_expired_token(_jwt_header, jwt_payload):
        log_auth_rejection("token_expired", jwt_payload=jwt_payload)
        return unauthorized_response()

    @jwt.revoked_token_loader
    def handle_revoked_token(_jwt_header, jwt_payload):
        log_auth_rejection("token_revoked_loader", jwt_payload=jwt_payload)
        return unauthorized_response()

    @jwt.needs_fresh_token_loader
    def handle_needs_fresh_token(_jwt_header, jwt_payload):
        log_auth_rejection("fresh_token_required", jwt_payload=jwt_payload)
        return unauthorized_response()


def get_mongo_client() -> MongoClient:
    global _mongo_client

    if _mongo_client is None:
        _mongo_client = MongoClient(
            current_app.config["MONGO_URI"],
            serverSelectionTimeoutMS=current_app.config["MONGO_SERVER_SELECTION_TIMEOUT_MS"],
            connectTimeoutMS=current_app.config["MONGO_CONNECT_TIMEOUT_MS"],
            socketTimeoutMS=current_app.config["MONGO_SOCKET_TIMEOUT_MS"],
            retryWrites=True,
        )
    return _mongo_client


def get_database():
    return get_mongo_client()[current_app.config["MONGO_DB_NAME"]]


def get_collection(name: str):
    return get_database()[name]


def get_database_connection_status() -> dict:
    try:
        get_mongo_client().admin.command("ping")
        return {
            "connected": True,
            "message": "MongoDB connection is healthy.",
        }
    except (ServerSelectionTimeoutError, ConnectionFailure, PyMongoError) as error:
        return {
            "connected": False,
            "message": str(error),
        }
