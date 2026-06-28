import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
MAX_LOG_BYTES = 1_048_576
BACKUP_COUNT = 5


def configure_backend_logging(app) -> None:
    logs_dir = Path(app.root_path) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    formatter = logging.Formatter(LOG_FORMAT)

    app_logger = app.logger
    app_logger.setLevel(log_level)

    _add_rotating_handler(
        app_logger,
        handler_name="flux-file-info",
        file_path=logs_dir / "flux-fleet.log",
        formatter=formatter,
        level=log_level,
    )
    _add_rotating_handler(
        app_logger,
        handler_name="flux-file-error",
        file_path=logs_dir / "flux-fleet-error.log",
        formatter=formatter,
        level=logging.ERROR,
    )


def _add_rotating_handler(logger, *, handler_name: str, file_path: Path, formatter, level: int) -> None:
    if any(getattr(handler, "name", None) == handler_name for handler in logger.handlers):
        return

    handler = RotatingFileHandler(
        file_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    handler.name = handler_name
    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
