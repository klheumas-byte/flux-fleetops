from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_admin_and_driver_mobile_navigation_reuse_permission_filtered_items():
    admin = source("src/app/components/admin/Sidebar.tsx")
    driver = source("src/app/components/driver/DriverSidebar.tsx")

    assert "filterAccessibleModules(userRole" in admin
    assert "items: [DASHBOARD_ITEM]" in admin
    assert "...visibleSections" in admin
    assert "filterAccessibleModules('driver'" in driver
    assert "canDriverAccessModule" in driver
    assert "...visibleSections" in driver
    assert "<MobileBottomNav" in admin
    assert "<MobileBottomNav" in driver


def test_responsive_shell_keeps_fixed_navigation_clear_of_content():
    mobile_nav = source("src/app/components/shared/MobileBottomNav.tsx")
    admin_layout = source("src/app/components/admin/AdminLayout.tsx")
    driver_layout = source("src/app/components/driver/DriverLayout.tsx")
    admin_sidebar = source("src/app/components/admin/Sidebar.tsx")

    assert "fixed inset-x-0 bottom-0" in mobile_nav
    assert "overflow-x-auto" in mobile_nav
    assert "env(safe-area-inset-bottom)" in mobile_nav
    assert "fixed left-0 top-0" in admin_sidebar
    assert "h-dvh" in admin_sidebar
    assert "overflow-y-auto" in admin_sidebar
    assert "flex h-dvh overflow-hidden" in admin_layout
    assert "flex h-dvh overflow-hidden" in driver_layout
    assert "env(safe-area-inset-bottom)" in admin_layout
    assert "env(safe-area-inset-bottom)" in driver_layout


def test_headers_use_unread_badge_and_delivery_views_are_swipeable():
    admin_topbar = source("src/app/components/admin/TopNav.tsx")
    driver_topbar = source("src/app/components/driver/DriverTopNav.tsx")
    deliveries = source("src/app/components/shared/SmartLivingDeliveries.tsx")

    for topbar in (admin_topbar, driver_topbar):
        assert "sticky top-0" in topbar
        assert "unreadCount" in topbar
        assert "motion-reduce:animate-none" in topbar
    assert 'label: "Certified Deliveries"' in deliveries
    assert 'label: "Daily Runs"' in deliveries
    assert 'label: "Weekly View"' in deliveries
    assert 'label: "Loading Schedule"' in deliveries
    assert 'label: "Returns & Reconciliation"' in deliveries
    assert "overflow-x-auto" in deliveries
    assert "filtersOpen" in deliveries
