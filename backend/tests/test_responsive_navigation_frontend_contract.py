from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_desktop_shell_has_independent_viewport_scrollers():
    for relative_path in (
        "src/app/components/admin/AdminLayout.tsx",
        "src/app/components/driver/DriverLayout.tsx",
    ):
        layout = source(relative_path)
        assert 'className="flex h-dvh overflow-hidden' in layout
        assert "flex h-dvh min-w-0 flex-1 flex-col overflow-hidden" in layout
        assert "min-h-0 flex-1 overflow-x-hidden overflow-y-auto" in layout

    for relative_path in (
        "src/app/components/admin/Sidebar.tsx",
        "src/app/components/driver/DriverSidebar.tsx",
    ):
        sidebar = source(relative_path)
        assert "fixed left-0 top-0" in sidebar
        assert "h-dvh" in sidebar
        assert "min-h-0 flex-1 overflow-y-auto" in sidebar


def test_mobile_navigation_reuses_the_filtered_desktop_menu():
    for relative_path in (
        "src/app/components/admin/Sidebar.tsx",
        "src/app/components/driver/DriverSidebar.tsx",
    ):
        sidebar = source(relative_path)
        assert "filterAccessibleModules" in sidebar
        assert "mobileGroups.flatMap((group) => group.items).slice(0, 5)" in sidebar
        assert "groups={mobileGroups}" in sidebar

    mobile_nav = source("src/app/components/shared/MobileBottomNav.tsx")
    assert "overflow-x-auto" in mobile_nav
    assert "env(safe-area-inset-bottom)" in mobile_nav
    assert "activeIsInMore" in mobile_nav
    assert "aria-current={activeIsInMore ? 'page' : undefined}" in mobile_nav


def test_notification_badge_tracks_unread_records_and_revalidates_after_reads():
    count_hook = source("src/app/lib/notification-count.ts")
    notification_center = source(
        "src/app/components/shared/NotificationCenter.tsx"
    )
    topbar = source("src/app/components/admin/TopNav.tsx")

    assert "moduleCounts.notifications?.unread_count" in count_hook
    assert "notifyBadgeChanged();" in notification_center
    assert "flux-notifications-changed" in notification_center
    assert "unreadCount > 0" in topbar
    assert "[animation-iteration-count:3]" in topbar
    assert "motion-reduce:animate-none" in topbar


def test_delivery_operations_stay_compact_and_horizontally_scrollable():
    delivery = source("src/app/components/shared/SmartLivingDeliveries.tsx")
    for label in (
        "Certified Deliveries",
        "Daily Runs",
        "Weekly View",
        "Loading Schedule",
        "Returns & Reconciliation",
    ):
        assert label in delivery
    assert "snap-x gap-1 overflow-x-auto" in delivery
    assert "filtersOpen" in delivery
    assert "md:hidden" in delivery


def test_kpi_grid_has_phone_tablet_and_desktop_densities():
    kpi_grid = source("src/app/components/shared/KpiGrid.tsx")
    assert "grid-cols-2" in kpi_grid
    assert "min-[480px]:grid-cols-3" in kpi_grid
    assert "md:grid-cols-4" in kpi_grid


def test_driver_dashboard_and_wallet_use_compact_phone_stat_grids():
    dashboard = source("src/app/components/driver/DriverDashboard.tsx")
    wallet = source("src/app/components/driver/MyWallet.tsx")

    assert 'grid grid-cols-3 gap-2 sm:gap-3 md:grid-cols-4' in dashboard
    assert 'mt-4 grid grid-cols-3 gap-2' in dashboard
    assert 'grid grid-cols-3 gap-2 sm:gap-3 md:grid-cols-2' in dashboard
    assert '[overflow-wrap:anywhere]' in dashboard

    for label in ("Current Due", "Arrears", "Available Credit"):
        assert label in wallet
    assert 'grid grid-cols-3 gap-2 sm:gap-4' in wallet
    assert 'summary.arrears > 0' in wallet
    assert 'summary.credit > 0' in wallet
    assert '[overflow-wrap:anywhere]' in wallet
