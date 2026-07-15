import os

from app import flask_app


def main() -> None:
    host = os.getenv("FLUX_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("FLUX_PORT", "5001")))
    debug = str(os.getenv("FLASK_DEBUG", "0")).strip().lower() in {"1", "true", "yes", "on"}
    flask_app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    main()
