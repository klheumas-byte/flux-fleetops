from flask import Blueprint
from flask_jwt_extended import get_jwt

from services.dashboard_service import get_dashboard_summary_fast
from utils.decorators import role_required
from utils.responses import success_response


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/summary")
@role_required("owner", "admin")
def get_dashboard_summary_route():
    dashboard = get_dashboard_summary_fast(current_role=get_jwt().get("role"))
    section_payloads = dashboard.get("section_payloads") or {}
    return success_response(
        data={
            "dashboard": dashboard,
            "fleetInvestmentSummary": section_payloads.get("fleetInvestmentSummary", {}),
            "operationsSummary": section_payloads.get("operationsSummary", {}),
            "revenueSummary": section_payloads.get("revenueSummary", {}),
            "incidentsClaimsSummary": section_payloads.get("incidentsClaimsSummary", {}),
            "complianceSummary": section_payloads.get("complianceSummary", {}),
            "maintenanceSummary": section_payloads.get("maintenanceSummary", {}),
            "supportingLookups": section_payloads.get("supportingLookups", {}),
            "warnings": dashboard.get("warnings") or [],
        }
    )
