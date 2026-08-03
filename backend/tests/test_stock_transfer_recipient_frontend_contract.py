from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/app/components/shared/StockTransfers.tsx").read_text(encoding="utf-8")


def test_recipient_state_is_owned_by_create_transfer_panel():
    create_panel = SOURCE.split("function CreateTransferPanel", 1)[1].split("function RecipientDetails", 1)[0]
    investigation_panel = SOURCE.split("function InvestigationPanel", 1)[1].split("function EvidenceInput", 1)[0]
    declarations = [
        "const [receiverType, setReceiverType]",
        "const [selectedRecipientId, setSelectedRecipientId]",
        "const [branches, setBranches]",
        "const [receivers, setReceivers]",
        "const [recipientOptionsBusy, setRecipientOptionsBusy]",
    ]
    assert all(declaration in create_panel for declaration in declarations)
    assert all(declaration not in investigation_panel for declaration in declarations)
    assert "options={branches.map" in create_panel
    assert "options={receivers.map" in create_panel
    assert "setBranches(result.branches);\n        onError('');" in create_panel
    assert "setReceivers(result.receivers);\n      onError('');" in create_panel
