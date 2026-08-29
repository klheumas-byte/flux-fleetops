from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from services.smart_living_integration_service import (
    create_mapping, discover_source_values, dry_run_import, import_selected_records, intake_delivery, integration_status,
    latest_dry_run, list_discoveries, list_exceptions, list_history, list_mappings,
    backfill_provisioning_mappings, create_manager_provisioning, mapping_options,
    match_manager_provisioning, preview_agent_provisioning, preview_manager_provisioning,
    provision_agents, reevaluate_manager_branch, reissue_pending_agent_credentials, resolve_agent_provisioning,
    resolve_exception, retry_exception, test_connection, update_mapping,
)
from utils.decorators import smartliving_admin_required
from utils.responses import success_response


smart_living_integration_bp = Blueprint("smart_living_integration", __name__)


@smart_living_integration_bp.get("/status")
@smartliving_admin_required
def status():
    return success_response(data=integration_status(get_jwt_identity()))


@smart_living_integration_bp.post("/test-connection")
@smartliving_admin_required
def connection_test():
    return success_response(data=test_connection(get_jwt_identity()))


@smart_living_integration_bp.get("/discoveries")
@smartliving_admin_required
def discoveries_list():
    return success_response(data=list_discoveries(get_jwt_identity()))


@smart_living_integration_bp.post("/discover")
@smartliving_admin_required
def discover():
    return success_response(data=discover_source_values(get_jwt_identity()))


@smart_living_integration_bp.get("/dry-run/latest")
@smartliving_admin_required
def dry_run_latest():
    return success_response(data={"dry_run": latest_dry_run(get_jwt_identity())})


@smart_living_integration_bp.post("/dry-run")
@smartliving_admin_required
def dry_run():
    return success_response(data={"dry_run": dry_run_import(get_jwt_identity(), request.get_json(silent=True) or {})})


@smart_living_integration_bp.post("/import-selected")
@smartliving_admin_required
def import_selected():
    return success_response(data={"import_batch": import_selected_records(request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_integration_bp.get("/mapping-options")
@smartliving_admin_required
def options():
    return success_response(data=mapping_options(get_jwt_identity()))


@smart_living_integration_bp.get("/managers/preview")
@smartliving_admin_required
def managers_preview():
    return success_response(data=preview_manager_provisioning(get_jwt_identity()))


@smart_living_integration_bp.post("/managers/<discovery_id>/match")
@smartliving_admin_required
def manager_match(discovery_id):
    return success_response(data=match_manager_provisioning(discovery_id, request.get_json(silent=True) or {}, get_jwt_identity()))


@smart_living_integration_bp.post("/managers/<discovery_id>/create")
@smartliving_admin_required
def manager_create(discovery_id):
    return success_response(data=create_manager_provisioning(discovery_id, request.get_json(silent=True) or {}, get_jwt_identity()), status_code=201)


@smart_living_integration_bp.post("/managers/<discovery_id>/re-evaluate")
@smartliving_admin_required
def manager_reevaluate(discovery_id):
    return success_response(data=reevaluate_manager_branch(discovery_id, get_jwt_identity()))


@smart_living_integration_bp.post("/managers/backfill")
@smartliving_admin_required
def manager_backfill():
    return success_response(data={"backfill": backfill_provisioning_mappings(request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_integration_bp.get("/agents/preview")
@smartliving_admin_required
def agents_preview():
    return success_response(data=preview_agent_provisioning(get_jwt_identity()))


@smart_living_integration_bp.post("/agents/<discovery_id>/resolve")
@smartliving_admin_required
def agent_resolve(discovery_id):
    return success_response(data={"agent": resolve_agent_provisioning(
        discovery_id, request.get_json(silent=True) or {}, get_jwt_identity(),
    )})


@smart_living_integration_bp.post("/agents/provision")
@smartliving_admin_required
def agents_provision():
    response, status_code = success_response(data={"provisioning": provision_agents(
        request.get_json(silent=True) or {}, get_jwt_identity(),
    )})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response, status_code


@smart_living_integration_bp.post("/agents/reissue-credentials")
@smartliving_admin_required
def agents_reissue_credentials():
    response, status_code = success_response(data={"credential_reissue": reissue_pending_agent_credentials(
        request.get_json(silent=True) or {}, get_jwt_identity(),
    )})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response, status_code


@smart_living_integration_bp.get("/mappings/<mapping_type>")
@smartliving_admin_required
def mappings_list(mapping_type):
    return success_response(data=list_mappings(mapping_type, get_jwt_identity()))


@smart_living_integration_bp.post("/mappings/<mapping_type>")
@smartliving_admin_required
def mappings_create(mapping_type):
    return success_response(data={"mapping": create_mapping(mapping_type, request.get_json(silent=True) or {}, get_jwt_identity())}, status_code=201)


@smart_living_integration_bp.patch("/mappings/<mapping_type>/<mapping_id>")
@smartliving_admin_required
def mappings_update(mapping_type, mapping_id):
    return success_response(data={"mapping": update_mapping(mapping_type, mapping_id, request.get_json(silent=True) or {}, get_jwt_identity())})


@smart_living_integration_bp.get("/exceptions")
@smartliving_admin_required
def exceptions_list():
    return success_response(data=list_exceptions(get_jwt_identity(), request.args.get("status")))


@smart_living_integration_bp.post("/exceptions/<exception_id>/resolve")
@smartliving_admin_required
def exception_resolve(exception_id):
    payload = request.get_json(silent=True) or {}
    return success_response(data={"exception": resolve_exception(exception_id, payload.get("notes"), get_jwt_identity())})


@smart_living_integration_bp.post("/exceptions/<exception_id>/retry")
@smartliving_admin_required
def exception_retry(exception_id):
    return success_response(data=retry_exception(exception_id, get_jwt_identity()))


@smart_living_integration_bp.get("/history")
@smartliving_admin_required
def history():
    return success_response(data=list_history(get_jwt_identity()))


# This authenticated canonical intake endpoint is for a future adapter. It does
# not fetch, poll, or call SmartLiving.
@smart_living_integration_bp.post("/intake")
@smartliving_admin_required
def intake():
    result = intake_delivery(request.get_json(silent=True) or {}, get_jwt_identity())
    return success_response(data=result, status_code=201 if result["outcome"] == "imported" else 200)
