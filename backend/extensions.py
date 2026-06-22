from flask import current_app
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, PyMongoError, ServerSelectionTimeoutError


cors = CORS()
jwt = JWTManager()
_mongo_client = None


def init_extensions(app):
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,
    )
    jwt.init_app(app)
    register_jwt_callbacks()


def register_jwt_callbacks():
    @jwt.token_in_blocklist_loader
    def is_token_revoked(_jwt_header, jwt_payload):
        token_blocklist = get_collection("token_blocklist")
        return token_blocklist.find_one({"jti": jwt_payload["jti"]}) is not None


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
