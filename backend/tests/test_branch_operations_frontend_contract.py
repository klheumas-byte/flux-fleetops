from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def test_branch_workspace_is_wired_to_existing_delivery_module():
    app=(ROOT/"src/app/App.tsx").read_text(encoding="utf-8"); sidebar=(ROOT/"src/app/components/admin/Sidebar.tsx").read_text(encoding="utf-8"); dashboard=(ROOT/"src/app/components/branch/BranchOperations.tsx").read_text(encoding="utf-8")
    assert "<BranchOperations onNavigate={navigateToPage}" in app and "<BranchTeam />" in app
    assert "Branch Operations" in sidebar and "Branch Team" in sidebar
    assert "fetchBranchOverview" in dashboard and "smart-living-deliveries" in dashboard
def test_branch_team_form_does_not_offer_role_or_branch_selection():
    team=(ROOT/"src/app/components/branch/BranchTeam.tsx").read_text(encoding="utf-8")
    assert "Role and branch are assigned automatically" in team
    assert "<select" not in team.lower()
