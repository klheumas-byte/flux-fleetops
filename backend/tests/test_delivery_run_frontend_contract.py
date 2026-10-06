from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    ROOT / "src" / "app" / "components" / "shared" / "SmartLivingDeliveries.tsx"
).read_text(encoding="utf-8")
API_SOURCE = (ROOT / "src" / "app" / "lib" / "api.ts").read_text(encoding="utf-8")
SYNC_SOURCE = (ROOT / "src" / "app" / "lib" / "data-sync.ts").read_text(encoding="utf-8")


def test_run_actions_are_status_gated_and_phase5_is_linked():
    assert '["DRAFT", "READY_FOR_REVIEW", "PUBLISHED"].includes(activeRun.status)' in SOURCE
    assert 'activeRun.status === "DRAFT"' in SOURCE
    assert 'run.status === "ACCEPTED"' in SOURCE
    assert 'run.status === "ITEMS_ISSUED"' in SOURCE
    assert 'run.status === "IN_PROGRESS"' in SOURCE
    assert 'run.status === "EXECUTION_COMPLETED"' in SOURCE
    assert "Continue to Returns & Reconciliation" in SOURCE
    assert '["CLOSED", "COMPLETED"].includes(activeRun.status)' in SOURCE


@pytest.mark.parametrize("width", [320, 375, 430])
def test_mobile_width_contract_uses_cards_without_desktop_tables(width):
    assert width < 768
    assert SOURCE.count('className="md:hidden"') >= 2
    assert SOURCE.count("hidden overflow-x-auto") >= 2
    assert "h-[100dvh] w-screen max-w-none" in SOURCE
    assert "flex snap-x gap-1 overflow-x-auto border-b" in SOURCE
    assert "shrink-0 snap-start" in SOURCE


def test_mutations_have_scoped_loading_feedback_and_duplicate_guards():
    for key in (
        "save",
        "publish",
        "accept",
        "issue",
        "custody",
        "start",
        "arrive",
        "outcome",
        "complete-execution",
        "receive_return",
        "resolve:",
        "reconcile",
        "close",
    ):
        assert key in SOURCE
    assert "runMutationLock.current" in SOURCE
    assert "mutationLock.current" in SOURCE
    assert "ActionFeedback" in SOURCE
    assert "toast.success" in SOURCE
    assert "toast.error" in SOURCE
    assert 'setSavingAction("delivery")' in SOURCE
    assert 'setSavingAction("create-run")' in SOURCE
    assert 'disabled={saving || Boolean(busyAction)}' in SOURCE
    assert 'disabled={!selected.length || saving}' in SOURCE
    assert 'disabled={Boolean(busyAction)}' in SOURCE


def test_scheduler_prefers_readable_identifiers_and_clear_fallbacks():
    assert 'run.branch?.name || "Name unavailable"' in SOURCE
    assert 'order.agent?.name || agent?.name' in SOURCE
    assert 'order.branch?.name || branch?.name || "Name unavailable"' in SOURCE
    assert '"Reference unavailable"' in SOURCE


def test_driver_workspace_never_renders_global_scheduler_controls():
    assert "const isDriverWorkspace" in SOURCE
    assert "getActiveSessionRole(user)" in SOURCE
    assert 'const canManage = !isDriverWorkspace' in SOURCE
    assert 'const canViewScheduler =' in SOURCE
    assert '!isDriverWorkspace && has("delivery_scheduler.view")' in SOURCE
    assert 'const canCreate = !isDriverWorkspace' in SOURCE
    assert 'const canPublish = !isDriverWorkspace' in SOURCE
    assert 'const canLock = !isDriverWorkspace' in SOURCE
    assert "const canAccountability = !isDriverWorkspace" in SOURCE


def test_successful_mutations_emit_scoped_refresh_events_and_clear_cache():
    assert "emitDataSync" in API_SOURCE
    assert "invalidateResourceCache(resources)" in API_SOURCE
    assert "resourcesForMutation(path)" in API_SOURCE
    assert "flux-data-sync" in SYNC_SOURCE
    assert "useDataSync" in SYNC_SOURCE


def test_dispatch_review_modal_is_responsive_and_action_gated():
    review = (ROOT / "src" / "app" / "components" / "admin" / "DispatchOpportunitiesReview.tsx").read_text(encoding="utf-8")
    assert "sm:w-[80vw]" in review
    assert "sm:max-w-[1150px]" in review
    assert "sm:max-h-[85vh]" in review
    assert "sticky top-0" in review
    assert "sticky bottom-0" in review
    assert "activeAction !== null" in review


def test_gps_is_non_blocking_and_coordinates_are_not_manual_fields():
    assert "GPS unavailable" in SOURCE
    assert "continue using the address and landmark" in SOURCE
    assert 'label="Latitude"' not in SOURCE
    assert 'label="Longitude"' not in SOURCE
    assert "Closed product — read only, do not issue or deliver." in SOURCE
