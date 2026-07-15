import os
from threading import Thread
from time import perf_counter
from datetime import datetime, timezone

from flask import Flask, g, request

from config import get_config
from extensions import get_database_connection_status, get_mongo_client, init_extensions
from routes import register_blueprints
from services.assignment_service import ensure_assignment_indexes
from services.booking_service import ensure_booking_indexes
from services.auth_service import ensure_indexes
from services.collection_service import ensure_collection_indexes
from services.customer_service import ensure_customer_indexes
from services.dashboard_service import ensure_dashboard_indexes
from services.deposit_service import ensure_deposit_indexes
from services.dispatch_request_service import ensure_dispatch_request_indexes
from services.dispatch_financial_service import ensure_dispatch_financial_indexes
from services.dispatch_opportunity_service import ensure_dispatch_opportunity_indexes
from services.dispatch_return_service import ensure_dispatch_return_indexes
from services.dispatch_planner_service import ensure_dispatch_planner_indexes
from services.expense_service import ensure_expense_indexes
from services.fault_service import ensure_fault_indexes, seed_default_fault_catalog
from services.finance_account_service import ensure_finance_account_indexes
from services.fuel_service import ensure_fuel_indexes, seed_default_fuel_stations
from services.incident_service import ensure_incident_indexes
from services.maintenance_service import ensure_maintenance_indexes
from services.master_data_service import ensure_master_data_indexes
from services.notification_service import ensure_notification_indexes, reconcile_legacy_actionable_notifications
from services.preventive_maintenance_service import (
    ensure_preventive_maintenance_indexes,
    seed_default_compliance_item_types,
    seed_preventive_schedules_for_existing_vehicles,
)
from services.report_service import ensure_report_indexes
from services.ride_service import ensure_ride_indexes
from services.system_settings_service import ensure_system_settings_indexes
from services.vehicle_service import ensure_vehicle_indexes
from services.vehicle_movement_service import ensure_vehicle_movement_indexes
from services.wallet_service import ensure_wallet_indexes
from utils.errors import register_error_handlers
from utils.logging_setup import configure_backend_logging


def create_app(config_name: str | None = None) -> Flask:
    startup_started_at = perf_counter()
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))
    configure_backend_logging(app)

    init_extensions(app)
    app.extensions.setdefault("flux_startup_maintenance_started", False)
    route_registration_started_at = perf_counter()
    register_blueprints(app)
    app.logger.info(
        "[Flux Startup] Route registration completed in %.2fms",
        (perf_counter() - route_registration_started_at) * 1000,
    )
    register_error_handlers(app)
    register_cli_commands(app)

    def run_startup_maintenance():
        with app.app_context():
            db_started_at = perf_counter()
            try:
                get_mongo_client().admin.command("ping")
                app.logger.info(
                    "[Flux Startup] Database connection verified in %.2fms",
                    (perf_counter() - db_started_at) * 1000,
                )
            except Exception:
                app.logger.exception("[Flux Startup] Database connection check failed during startup.")

            index_started_at = perf_counter()
            try:
                ensure_indexes()
                ensure_assignment_indexes()
                ensure_booking_indexes()
                ensure_collection_indexes()
                ensure_customer_indexes()
                ensure_dashboard_indexes()
                ensure_deposit_indexes()
                ensure_dispatch_request_indexes()
                ensure_dispatch_financial_indexes()
                ensure_dispatch_opportunity_indexes()
                ensure_dispatch_return_indexes()
                ensure_dispatch_planner_indexes()
                ensure_expense_indexes()
                ensure_fault_indexes()
                ensure_finance_account_indexes()
                ensure_fuel_indexes()
                ensure_incident_indexes()
                ensure_maintenance_indexes()
                ensure_master_data_indexes()
                ensure_notification_indexes()
                ensure_preventive_maintenance_indexes()
                ensure_report_indexes()
                ensure_ride_indexes()
                ensure_system_settings_indexes()
                ensure_vehicle_indexes()
                ensure_vehicle_movement_indexes()
                ensure_wallet_indexes()
                app.logger.info(
                    "[Flux Startup] Index checks completed in %.2fms",
                    (perf_counter() - index_started_at) * 1000,
                )
            except Exception:
                app.logger.exception("[Flux Startup] Index checks failed.")

            try:
                reconcile_legacy_actionable_notifications()
            except Exception:
                app.logger.exception("[Flux Startup] Legacy notification reconciliation failed.")

            seed_started_at = perf_counter()
            try:
                seed_default_fault_catalog()
                seed_default_fuel_stations()
                seed_default_compliance_item_types()
                seed_preventive_schedules_for_existing_vehicles()
                app.logger.info(
                    "[Flux Startup] Seed checks completed in %.2fms",
                    (perf_counter() - seed_started_at) * 1000,
                )
            except Exception:
                app.logger.exception("[Flux Startup] Seed checks failed.")

    if not app.config.get("RUN_STARTUP_MAINTENANCE", True):
        app.logger.info("[Flux Startup] Startup maintenance skipped by configuration.")
    elif not app.extensions["flux_startup_maintenance_started"]:
        app.extensions["flux_startup_maintenance_started"] = True
        Thread(target=run_startup_maintenance, daemon=True).start()
    app.logger.info(
        "[Flux Startup] App factory completed in %.2fms pid=%s reloader_child=%s",
        (perf_counter() - startup_started_at) * 1000,
        os.getpid(),
        str(os.getenv("WERKZEUG_RUN_MAIN", "")).lower() == "true",
    )

    def _health_payload():
        database = get_database_connection_status()
        backend_ok = database["connected"]
        return {
            "success": backend_ok,
            "message": "Flux Fleet backend is healthy." if backend_ok else "Flux Fleet backend is running but database is unavailable.",
            "data": {
                "service": "flux-fleet-backend",
                "environment": app.config["ENV_NAME"],
                "debug": bool(app.config["DEBUG"]),
                "database": database,
            },
        }, (200 if backend_ok else 503)

    @app.get("/health")
    def healthcheck():
        return _health_payload()

    @app.get("/api/health")
    def api_healthcheck():
        return _health_payload()

    @app.before_request
    def _start_request_timer():
        g.request_started_at = perf_counter()
        g.request_started_at_utc = datetime.now(timezone.utc)

    @app.before_request
    def _handle_api_preflight():
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            return "", 200

    @app.after_request
    def _log_request_timing(response):
        started_at = getattr(g, "request_started_at", None)
        if started_at is None:
            return response
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        started_at_utc = getattr(g, "request_started_at_utc", None)
        ended_at_utc = datetime.now(timezone.utc)
        response.headers["X-Response-Time-ms"] = str(duration_ms)
        if getattr(g, "request_path", "").startswith("/api"):
            app.logger.info(
                "[Flux API] %s %s role=%s start=%s end=%s duration_ms=%s status=%s",
                getattr(g, "request_method", None) or "",
                getattr(g, "request_path", None) or "",
                getattr(g, "request_role", None) or "anonymous",
                started_at_utc.isoformat() if started_at_utc else "",
                ended_at_utc.isoformat(),
                duration_ms,
                response.status_code,
            )
        if duration_ms > 2000:
            app.logger.warning(
                "SLOW API WARNING %s %s role=%s duration_ms=%s status=%s",
                getattr(g, "request_method", None) or "",
                getattr(g, "request_path", None) or "",
                getattr(g, "request_role", None) or "anonymous",
                duration_ms,
                response.status_code,
            )
        return response

    @app.before_request
    def _store_request_context():
        from flask import request

        g.request_method = request.method
        g.request_path = request.path
        g.request_role = None
        try:
            from flask_jwt_extended import get_jwt

            g.request_role = get_jwt().get("role")
        except Exception:
            g.request_role = None

    return app

def register_cli_commands(app: Flask) -> None:
    @app.cli.command("maintenance-reminder-sweep")
    def maintenance_reminder_sweep_command():
        """Run one bounded preventive/maintenance reminder reconciliation."""
        from services.maintenance_reminder_service import run_maintenance_reminder_sweep

        if not app.config.get("MAINTENANCE_REMINDER_SWEEP_ENABLED", True):
            print("Maintenance reminder sweep is disabled.")
            return
        summary = run_maintenance_reminder_sweep(
            batch_size=app.config.get("MAINTENANCE_REMINDER_SWEEP_BATCH_SIZE", 50)
        )
        print(summary)


flask_app = create_app()


if __name__ == "__main__":
    host = os.getenv("FLUX_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("FLUX_PORT", "5001")))
    flask_app.run(
        host=host,
        port=port,
        debug=flask_app.config["DEBUG"],
        use_reloader=flask_app.config["DEBUG"],
    )
