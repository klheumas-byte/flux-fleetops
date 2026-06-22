from flask import Flask

from .analytics import analytics_bp
from .admins import admins_bp
from .assignments import assignments_bp
from .auth import auth_bp
from .bookings import bookings_bp
from .calendar import calendar_bp
from .collections import collections_bp
from .company_funds import company_funds_bp
from .customers import customers_bp
from .dashboard import dashboard_bp
from .deposits import deposits_bp
from .driver_portal import driver_portal_bp
from .drivers import drivers_bp
from .expenses import expenses_bp
from .faults import faults_bp
from .finance_accounts import finance_accounts_bp
from .fuel_logs import fuel_logs_bp
from .fuel_stations import fuel_stations_bp
from .maintenance import maintenance_bp
from .master_data import master_data_bp
from .notifications import notifications_bp
from .preventive_maintenance import preventive_maintenance_bp
from .reports import reports_bp
from .rides import rides_bp
from .system_settings import system_settings_bp
from .users import users_bp
from .vehicles import vehicles_bp
from .wallets import wallets_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
    app.register_blueprint(admins_bp, url_prefix="/api/admins")
    app.register_blueprint(assignments_bp, url_prefix="/api/assignments")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(bookings_bp, url_prefix="/api/bookings")
    app.register_blueprint(calendar_bp, url_prefix="/api/calendar")
    app.register_blueprint(collections_bp, url_prefix="/api/collections")
    app.register_blueprint(company_funds_bp, url_prefix="/api/company-funds")
    app.register_blueprint(customers_bp, url_prefix="/api/customers")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(deposits_bp, url_prefix="/api/deposits")
    app.register_blueprint(driver_portal_bp, url_prefix="/api/driver")
    app.register_blueprint(drivers_bp, url_prefix="/api/drivers")
    app.register_blueprint(expenses_bp, url_prefix="/api/expenses")
    app.register_blueprint(faults_bp, url_prefix="/api/faults")
    app.register_blueprint(finance_accounts_bp, url_prefix="/api/finance")
    app.register_blueprint(fuel_logs_bp, url_prefix="/api/fuel-logs")
    app.register_blueprint(fuel_stations_bp, url_prefix="/api/fuel-stations")
    app.register_blueprint(maintenance_bp, url_prefix="/api/maintenance")
    app.register_blueprint(master_data_bp, url_prefix="/api/master-data")
    app.register_blueprint(notifications_bp, url_prefix="/api/notifications")
    app.register_blueprint(preventive_maintenance_bp, url_prefix="/api/preventive-maintenance")
    app.register_blueprint(reports_bp, url_prefix="/api/reports")
    app.register_blueprint(rides_bp, url_prefix="/api/rides")
    app.register_blueprint(system_settings_bp, url_prefix="/api/system-settings")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(vehicles_bp, url_prefix="/api/vehicles")
    app.register_blueprint(wallets_bp, url_prefix="/api/wallets")
