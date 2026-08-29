from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_preview_period_uses_modal_and_existing_dry_run_endpoint():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    api = source("src/app/lib/smart-living-integration-api.ts")

    assert "openPreviewDialog" in component
    assert "PreviewPeriodDialog" in component
    assert 'DialogTitle>Preview SmartLiving deliveries' in component
    assert 'aria-label="From Date"' in component
    assert 'aria-label="To Date"' in component
    assert "Today" in component and "This Week" in component and "Last Week" in component
    assert "From Date must be on or before To Date." in component
    assert "Scanning…" in component
    assert "Preview Deliveries" in component
    assert "smartLivingIntegrationApi.dryRun(previewControls)" in component
    assert "'/integrations/smartliving/dry-run'" in api


def test_preview_totals_and_import_remain_separate_actions():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")

    for label in ("Scanned", "Eligible", "Ready", "Blocked", "Already imported", "Unmapped branch", "Unmapped agent", "Invalid / ignored"):
        assert f'label="{label}"' in component
    assert "no delivery\n        orders were created" in component
    assert "Import selected READY" in component
    assert "smartLivingIntegrationApi.importSelected" in component
    assert "record.import_eligible" in component
    assert "disabled={!record.import_eligible}" in component
    assert "new Set(ready.map((record) => record.selected_key))" in component
    assert "if (tab === 'dry-run') await loadDryRun()" in component
    assert "Refresh Preview" in component
    assert "record.reasons.join(', ').replaceAll('_', ' ')" in component
    assert "SmartLiving" in component and "ready for FleetOps physical delivery processing" in component
    assert "Action: {resolutionAction(record.reasons)}" in component
    assert "EXCLUDED — already delivered" not in component


def test_agent_provisioning_has_client_side_agent_search():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")

    assert 'id="agent-provisioning-search"' in component
    assert 'type="search"' in component
    assert "const visibleAgentRows = agentRows.filter(matchesSearch)" in component
    assert "username" in component and "confirmed_manager_name" in component
    assert "Showing {visibleAgentRows.length} of {agentRows.length} agents" in component
    assert "visibleGroups.map((group)" in component


def test_preview_prioritizes_readable_values_and_hides_ids_in_details():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    api = source("src/app/lib/smart-living-integration-api.ts")

    for field in ("customer_phone", "customer_location", "customer_occupation", "branch_name", "source_status_label"):
        assert field in component and field in api
    assert "<dt>Occupation</dt>" in component
    assert "View Details" in component and "Source details" in component
    assert "Source ID:" in component and "Agent ID:" in component and "Product ID:" in component
    assert "href={`tel:${record.customer_phone.replace" in component
    assert "Not provided" in component
    assert "record.external_agent_name||record.external_agent_id" not in component
    assert "product.name||product.reference" not in component
    assert "item.external_display_name||item.external_id" not in component
    assert "mapping.external_display_name || mapping.external_id" not in component
    assert "Name unavailable" in component


def test_agent_relationship_is_readable_and_raw_ids_stay_in_source_details():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    api = source("src/app/lib/smart-living-integration-api.ts")

    assert "AgentRelationship" in component
    assert " → " in component
    assert "Needs Review" in component and "Resolved" in component
    assert "Manager ID:" in component and "FleetOps Branch ID:" in component
    assert "relationship?: SmartLivingAgentRelationship" in api


def test_smartliving_integration_uses_one_owner_admin_rule_across_navigation():
    access = source("src/app/lib/role-access.ts")
    sidebar = source("src/app/components/admin/Sidebar.tsx")
    dashboard = source("src/app/components/admin/RoleDashboard.tsx")
    legacy_admin_dashboard = source("src/app/components/admin/Dashboard.tsx")
    top_navigation = source("src/app/components/admin/TopNav.tsx")

    assert "SMARTLIVING_GLOBAL_ADMIN_ROLES: readonly SessionUserRole[] = ['owner', 'admin']" in access
    assert "return canManageSmartLiving(role)" in access
    assert "system_administrator: FULL_ACCESS" not in access
    assert "operations_administrator: OPERATIONAL_ADMIN" not in access
    assert "const SMARTLIVING_ITEM: SidebarItem" in sidebar
    assert "canManageSmartLiving(userRole)" in sidebar
    assert "item={SMARTLIVING_ITEM}" in sidebar
    assert "label:'SmartLiving Integration',page:'smart-living-integration'" not in dashboard
    assert "onNavigate('smart-living-integration')" in legacy_admin_dashboard
    assert "SmartLiving Integration" in legacy_admin_dashboard
    assert "aria-label=\"Open SmartLiving Integration\"" in top_navigation
    assert "canManageSmartLiving(userRole)" in top_navigation


def test_manager_and_agent_frontend_calls_match_registered_backend_routes():
    api = source("src/app/lib/smart-living-integration-api.ts")
    routes = source("backend/routes/smart_living_integration.py")
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")

    contracts = (
        ("GET", "/managers/preview", "'/integrations/smartliving/managers/preview'"),
        ("POST", "/managers/<discovery_id>/match", "`/integrations/smartliving/managers/${discoveryId}/match`"),
        ("POST", "/managers/<discovery_id>/create", "`/integrations/smartliving/managers/${discoveryId}/create`"),
        ("POST", "/managers/<discovery_id>/re-evaluate", "`/integrations/smartliving/managers/${discoveryId}/re-evaluate`"),
        ("POST", "/managers/backfill", "'/integrations/smartliving/managers/backfill'"),
        ("GET", "/agents/preview", "'/integrations/smartliving/agents/preview'"),
        ("POST", "/agents/<discovery_id>/resolve", "`/integrations/smartliving/agents/${discoveryId}/resolve`"),
        ("POST", "/agents/provision", "'/integrations/smartliving/agents/provision'"),
    )
    for method, path, frontend_path in contracts:
        assert f'@smart_living_integration_bp.{method.lower()}("{path}")' in routes
        assert frontend_path in api
    assert "Branch Manager Provisioning" in component
    assert component.index("Branch Manager Provisioning") < component.index("Agent Provisioning")


def test_manager_review_is_human_readable_and_exposes_all_required_actions():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    api = source("src/app/lib/smart-living-integration-api.ts")
    manager_component = component[component.index("function ManagerProvisioning"):component.index("function AgentProvisioning")]
    headers = ["Name</th>", "Role</th>", "Branch</th>", "Source system</th>", "FleetOps account</th>", "Status</th>", "Action</th>"]
    assert [manager_component.index(header) for header in headers] == sorted(manager_component.index(header) for header in headers)
    for label in ("Needs Review", "Ready to Link", "Ready to Create", "Linked", "Resolve", "Link Existing", "Create Account"):
        assert label in manager_component
    manager_table = manager_component[:manager_component.index("function ManagerSourceDetails")]
    assert "item.source_id" not in manager_table
    assert "<ManagerSourceDetails item={item}" in component
    assert "SmartLiving manager ID:" in component and "Candidate user IDs:" in component
    assert "Technical Details" in manager_component
    assert "Manager identity missing" in manager_component
    assert "SmartLiving source has no manager name" in manager_component
    assert "Source branch evidence:" in manager_component
    assert "Mapping:" in manager_component and "Branch access candidate" in manager_component
    assert "normalizeManagerProvisioningPreview(response.data)" in api
    assert "Array.isArray(item.candidates)" in component
    assert "Array.isArray(item.source_branch_options)" in component
    assert "class ProvisioningErrorBoundary" in component
    assert "Branch Manager provisioning unavailable" in component and "Retry" in component
    assert "managerProvisioningLoading" in component and "managerProvisioningError" in component


def test_agent_reconciliation_table_is_readable_and_bulk_selection_is_eligible_only():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    agent_component = component[component.index("function AgentProvisioning"):component.index("function AgentTechnicalDetails")]
    headers = [
        "Agent</th>", "Direct Source Branch</th>", "Confirmed Manager</th>",
        "Manager Branch</th>", "Existing FleetOps Account</th>",
        "Conflict Reason</th>", "Resolution Action</th>",
    ]
    assert [agent_component.index(header) for header in headers] == sorted(agent_component.index(header) for header in headers)
    assert "Agent identity missing" in agent_component
    assert "Link Existing and Resolve" in agent_component and "Resolve for Create New" in agent_component
    assert "const eligible = agentRows.filter((item) => item.status === 'eligible')" in agent_component
    assert "disabled={item.status !== 'eligible' || busy}" in agent_component
    assert "item.agent_id" not in agent_component


def test_agent_provisioning_shows_one_time_credentials_and_canonical_bulk_counts():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    agent_component = component[component.index("function AgentProvisioning"):component.index("function AgentTechnicalDetails")]
    api = source("src/app/lib/smart-living-integration-api.ts")
    assert "Provision Eligible Agents" in agent_component
    assert "Created ${totals.created}; linked ${totals.linked}; skipped ${totals.skipped}; failed ${totals.failed}." in agent_component
    assert "const batchSize = 10" in agent_component
    assert "Safe completed batches were kept; retry to continue." in agent_component
    assert "Provisioning ${provisioningProgress.completed} of ${provisioningProgress.total}" in agent_component
    assert "Reissue pending credentials" in agent_component
    assert "never-logged-in agents" in agent_component
    assert "reissueAgentCredentials" in api
    assert "Passwords are shown only" in agent_component and "navigator.clipboard.writeText" in agent_component
    for header in ("Name", "Username", "Branch", "Manager", "Role", "Status", "Temporary Password"):
        assert f'>{header}</th>' in agent_component
    assert "temporary_password?: string" in api
    assert all(f"{field}: number" in api for field in ("preview_eligible", "created", "linked", "skipped", "failed"))


def test_agent_login_guidance_and_owner_admin_copy_actions_are_explicit():
    login = source("src/app/components/Login.tsx")
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    access = source("src/app/lib/role-access.ts")

    assert "emailOrPhone.trim().toLowerCase()" in login
    assert "Username example: <code>abigail.mccarthy</code>" in login
    assert "capitalization does not matter" in login
    assert "Copy Username" in component
    assert "Copy Password" in component
    assert "Copy Credentials" in component
    assert "Username: ${item.username}" in component
    assert "SMARTLIVING_GLOBAL_ADMIN_ROLES: readonly SessionUserRole[] = ['owner', 'admin']" in access


def test_manager_and_agent_provisioning_share_copyable_login_details():
    component = source("src/app/components/admin/SmartLivingIntegration.tsx")
    api = source("src/app/lib/smart-living-integration-api.ts")
    backend = source("backend/services/smart_living_integration_service.py")

    for text in (
        "Flux FleetOps Login Details",
        "Name: ${account.name}",
        "Username: ${account.username}",
        "Password: fleet@12345",
        "Role: ${account.roles}",
        "Branch: ${account.branch}",
        "Use your username and password to sign in. You can change your password after login.",
        "Copy Login Details",
        "Login details copied for ${account.name}.",
    ):
        assert text in component
    assert component.count("<ProvisionedLoginAccounts accounts={linkedLoginAccounts} />") == 2
    assert "item.fleetops_username!" in component
    assert "item.username!" in component
    assert "sm:grid-cols-2 xl:grid-cols-3" in component
    for field in ("fleetops_username", "fleetops_roles", "fleetops_status"):
        assert field in api and f'"{field}"' in backend
