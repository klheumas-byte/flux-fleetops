from bson import ObjectId


def _value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_value(item) for item in value]
    return value


def _workflow_stage(document: dict) -> str:
    """Expose the Phase 4 lifecycle without rewriting legacy status values."""
    status = document.get("status") or "draft"
    if document.get("branch_receiving_status") == "RECEIVED_WITH_VARIANCE":
        return "received_with_variance"
    if document.get("branch_receiving_status") == "VERIFIED":
        return "verified"
    if (document.get("operation_type") or "stock_transfer") == "supplier_pickup":
        if status in {"draft", "pending_approval"}:
            return "draft"
        if status == "approved":
            return "approved"
        if status == "scheduled":
            if document.get("pickup_confirmation"):
                return "pickup_confirmed"
            if document.get("supplier_arrived_at"):
                return "arrived_at_supplier"
            return "driver_accepted" if document.get("acknowledged_at") else "driver_assigned"
        if status == "released":
            return "loaded"
        if status == "in_transit":
            return "in_transit"
        if status == "awaiting_receipt":
            return "delivered"
        if status == "completed":
            return "completed"
        return status
    if status in {"draft", "pending_approval"}:
        return "draft"
    if status == "approved":
        return "approved"
    if status == "scheduled":
        return "waybill_confirmed" if document.get("acknowledged_at") else "driver_assigned"
    if status == "released":
        return "loaded"
    if status == "in_transit":
        return "in_transit"
    if status == "awaiting_receipt":
        if document.get("linked_delivery_exception_id"):
            return "delivery_exception"
        if document.get("receiving_status") != "received":
            return "delivered"
        return "variance" if document.get("quantity_variance") else "received"
    return status


def serialize_stock_transfer(document: dict, *, include_items: bool = False) -> dict:
    payload = {
        "id": str(document.get("_id")),
        "transfer_id": document.get("transfer_id"),
        "operation_type": document.get("operation_type") or "stock_transfer",
        "origin_type": document.get("origin_type") or "internal_location",
        "supplier": _serialize_mapping(document.get("supplier")),
        "supplier_reference": document.get("supplier_reference"),
        "sending_location_id": _value(document.get("sending_location_id")),
        "receiving_location_id": _value(document.get("receiving_location_id")),
        "destination_branch_id": _value(document.get("destination_branch_id") or document.get("receiving_location_id")),
        "sending_location": document.get("sending_location"),
        "receiving_location": document.get("receiving_location"),
        "approved_by": _value(document.get("approved_by")),
        "approved_at": _value(document.get("approved_at")),
        "released_by": _value(document.get("released_by")),
        "received_by": _value(document.get("received_by")),
        "received_by_user_id": _value(document.get("received_by_user_id") or document.get("received_by")),
        "receiver_name": document.get("receiver_name"),
        "receiver_role": document.get("receiver_role"),
        "receiving_branch_id": _value(document.get("receiving_branch_id") or document.get("destination_branch_id") or document.get("receiving_location_id")),
        "received_at": _value(document.get("received_at")),
        "branch_receiving_status": document.get("branch_receiving_status"),
        "receipt_confirmation": _serialize_mapping(document.get("receipt_confirmation")),
        "dispatch_status": document.get("dispatch_status"),
        "receiving_status": document.get("receiving_status"),
        "reservation_status": document.get("reservation_status"),
        "vehicle_required": bool(document.get("vehicle_required", True)),
        "vehicle_id": _value(document.get("vehicle_id")),
        "driver_id": _value(document.get("driver_id")),
        "scheduled_at": _value(document.get("scheduled_at")),
        "dispatch_date": _value(document.get("started_at") or document.get("released_at")),
        "expected_arrival": _value(document.get("expected_arrival") or document.get("scheduled_at")),
        "requested_date": _value(document.get("requested_date")),
        "purpose": document.get("purpose"),
        "recipient": _serialize_mapping(document.get("recipient")),
        "actual_receiver": _serialize_mapping(document.get("actual_receiver")),
        "linked_delivery_exception_id": _value(document.get("linked_delivery_exception_id")),
        "delivery_exception_status": document.get("delivery_exception_status"),
        "delivery_exception_summary": _serialize_mapping(document.get("delivery_exception_summary")),
        "original_stock_transfer_id": _value(document.get("original_stock_transfer_id")),
        "source_delivery_exception_id": _value(document.get("source_delivery_exception_id")),
        "replacement_request_id": _value(document.get("replacement_request_id")),
        "linked_replacement_transfer_id": _value(document.get("linked_replacement_transfer_id")),
        "linked_replacement_status": document.get("linked_replacement_status"),
        "verified_at": _value(document.get("verified_at")),
        "verified_by": _value(document.get("verified_by")),
        "acknowledged_at": _value(document.get("acknowledged_at")),
        "acknowledged_by": _value(document.get("acknowledged_by")),
        "supplier_arrived_at": _value(document.get("supplier_arrived_at")),
        "supplier_arrived_by": _value(document.get("supplier_arrived_by")),
        "supplier_handover": _serialize_mapping(document.get("supplier_handover")),
        "pickup_confirmation": _serialize_mapping(document.get("pickup_confirmation")),
        "collected_quantities": document.get("collected_quantities") or [],
        "supplier_shortfall_ids": _value(document.get("supplier_shortfall_ids") or []),
        "loaded_quantities": document.get("loaded_quantities") or [],
        "released_at": _value(document.get("released_at")),
        "started_at": _value(document.get("started_at")),
        "started_by": _value(document.get("started_by")),
        "arrived_at": _value(document.get("arrived_at")),
        "arrived_by": _value(document.get("arrived_by")),
        "linked_vehicle_movement_id": _value(document.get("linked_vehicle_movement_id")),
        "linked_waybill_id": _value(document.get("linked_waybill_id")),
        "linked_assignment_id": _value(document.get("linked_assignment_id")),
        "custody_history": [_serialize_mapping(item) for item in (document.get("custody_history") or [])],
        "status": document.get("status"),
        "workflow_stage": _workflow_stage(document),
        "quantity_variance": document.get("quantity_variance") or [],
        "variance_review": _serialize_mapping(document.get("variance_review")),
        "notes": document.get("notes"),
        "created_at": _value(document.get("created_at")),
        "updated_at": _value(document.get("updated_at")),
        "version": int(document.get("version") or 1),
        "item_count": int(document.get("item_count") or len(document.get("transfer_items") or [])),
        "total_quantity": sum(float(item.get("quantity") or 0) for item in (document.get("transfer_items") or [])),
        "audit_log": [
            _serialize_mapping(item) for item in (document.get("audit_log") or [])
        ],
    }
    if include_items:
        payload["transfer_items"] = document.get("transfer_items") or []
        payload["received_items"] = document.get("received_items") or []
    return payload


def _serialize_mapping(document: dict | None) -> dict | None:
    if document is None:
        return None
    return {key: _value(value) for key, value in document.items()}
