from flask import Flask
from flask import current_app
from flask_jwt_extended.exceptions import JWTExtendedException
from pymongo.errors import PyMongoError
from werkzeug.exceptions import HTTPException

from utils.api_error import ApiError
from utils.responses import error_response


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return error_response(
            error.message,
            status_code=error.status_code,
            errors=error.errors,
        )

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        return error_response(error.description, status_code=error.code or 500)

    @app.errorhandler(JWTExtendedException)
    def handle_jwt_error(error: JWTExtendedException):
        return error_response(str(error), status_code=401)

    @app.errorhandler(PyMongoError)
    def handle_mongo_error(error: PyMongoError):
        current_app.logger.exception("[Flux API] Unhandled MongoDB error: %s", error)
        return error_response("A database error occurred.", status_code=500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        if app.config["DEBUG"]:
            raise error
        current_app.logger.exception("[Flux API] Unhandled server error: %s", error)
        return error_response("An unexpected server error occurred.", status_code=500)
