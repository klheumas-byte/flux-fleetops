"""Run one bounded preventive-maintenance reminder sweep for a scheduler."""

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import flask_app  # noqa: E402
from services.maintenance_reminder_service import (  # noqa: E402
    run_maintenance_reminder_sweep,
)


def main() -> int:
    with flask_app.app_context():
        if not flask_app.config.get("MAINTENANCE_REMINDER_SWEEP_ENABLED", True):
            print("Maintenance reminder sweep is disabled.")
            return 0
        summary = run_maintenance_reminder_sweep(
            batch_size=flask_app.config.get("MAINTENANCE_REMINDER_SWEEP_BATCH_SIZE", 50)
        )
        print(summary)
        return 0 if summary.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
