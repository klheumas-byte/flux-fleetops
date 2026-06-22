from flask import Blueprint

from services.deposit_service import get_company_funds_summary
from utils.decorators import role_required
from utils.responses import success_response


company_funds_bp = Blueprint("company_funds", __name__)


@company_funds_bp.get("")
@role_required("owner")
def get_company_funds():
    return success_response(data={"funds": get_company_funds_summary()})
