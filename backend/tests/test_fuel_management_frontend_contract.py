from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_admin_fuel_management_exposes_purchase_creation_classification_and_task_verification():
    source = (ROOT / "src/app/components/admin/Fuel.tsx").read_text(encoding="utf-8")
    assert "Create Fuel Purchase" in source
    assert "Operational / Company-Funded fuel instruction" in source
    assert "Operational Fuel" in source
    assert "Weekly Remittance Fuel" in source
    assert "createFuelInstruction" in source
    assert "mutateOperationRequest(purchase.id, 'verify'" in source
    assert "Review linked Fuel Purchase above" in source
    assert "/finance/accounts" in source
    assert "treasuryAccounts.map" in source


def test_fuel_management_uses_existing_operational_request_api():
    source = (ROOT / "src/app/lib/operational-request-api.ts").read_text(encoding="utf-8")
    assert "'/operational-requests/fuel-instructions'" in source
    assert "`/operational-requests/${id}/${action}`" in source


def test_driver_fuel_task_collects_actual_station_and_branch():
    source = (ROOT / "src/app/components/shared/OperationalRequests.tsx").read_text(encoding="utf-8")
    assert 'label="Actual station (known station)"' in source
    assert 'label="Actual station name (if not listed)"' in source
    assert 'label="Station branch / location"' in source
    assert "actual_fuel_station_id" in source
    assert "station_branch" in source
    assert 'label="Vehicle fuel level after purchase"' in source
    assert "complete-fuel-purchase" in source
    assert "Submit for Verification" in source
