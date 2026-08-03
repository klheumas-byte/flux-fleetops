from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/app/components/shared/StockTransfers.tsx").read_text(encoding="utf-8")


@pytest.mark.parametrize("item_count", [1, 10, 35])
def test_loading_list_is_count_independent_and_footer_stays_outside_scroller(item_count):
    assert item_count > 0
    assert "(transfer.transfer_items || []).map(item =>" in SOURCE
    assert 'className="min-h-0 flex-1 overflow-y-auto overscroll-contain' in SOURCE
    assert '<footer className="sticky bottom-0' in SOURCE
    assert "Confirm Loading" in SOURCE


@pytest.mark.parametrize("viewport", ["desktop", "mobile-portrait", "mobile-landscape"])
def test_loading_modal_has_desktop_and_mobile_viewport_caps(viewport):
    assert viewport
    assert "h-[100dvh] max-h-[100dvh] w-full" in SOURCE
    assert "sm:h-auto sm:max-h-[85vh] sm:max-w-lg sm:rounded-xl" in SOURCE
    assert '<header className="sticky top-0' in SOURCE
    assert "min-h-12" in SOURCE


def test_loading_validation_bulk_fill_and_duplicate_guard_are_frontend_owned():
    assert "Confirm All as Expected" in SOURCE
    assert "Quantity cannot be negative." in SOURCE
    assert "Enter a valid number." in SOURCE
    assert "submitLock.current" in SOURCE
    assert "backendError" in SOURCE
    assert "mutateStockTransfer(record.id, action, payload)" in SOURCE
    assert "run(loadingTransfer, 'release', { loaded_quantities: quantities })" in SOURCE
