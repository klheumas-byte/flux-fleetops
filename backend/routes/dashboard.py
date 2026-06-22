from flask import Blueprint
from flask_jwt_extended import get_jwt

from services.dashboard_service import get_dashboard_summary
from utils.decorators import role_required
from utils.responses import success_response


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/summary")
@role_required("owner", "admin")
def get_dashboard_summary_route():
    return success_response(
        data={"dashboard": get_dashboard_summary(current_role=get_jwt().get("role"))}
    )
