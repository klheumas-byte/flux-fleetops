from flask import jsonify


def success_response(data=None, message: str = "Loaded successfully.", status_code: int = 200):
    return jsonify({"success": True, "message": message, "data": [] if data is None else data}), status_code


def error_response(message: str, status_code: int = 400, errors=None, data=None, public_message: str = "Data could not be loaded"):
    return (
        jsonify(
            {
                "success": False,
                "data": [] if data is None else data,
                "error": message,
                "message": public_message,
                "errors": errors or [],
            }
        ),
        status_code,
    )
