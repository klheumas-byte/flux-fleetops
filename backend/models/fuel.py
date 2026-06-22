from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_fuel_station(station_document: dict) -> dict:
    return {
        "id": str(station_document.get("_id")),
        "station_name": station_document.get("station_name"),
        "brand_name": station_document.get("brand_name"),
        "location": station_document.get("location"),
        "city": station_document.get("city"),
        "contact_number": station_document.get("contact_number"),
        "status": station_document.get("status"),
        "created_by": _serialize_reference_id(station_document.get("created_by")),
        "created_at": station_document.get("created_at").isoformat()
        if station_document.get("created_at")
        else None,
        "updated_at": station_document.get("updated_at").isoformat()
        if station_document.get("updated_at")
        else None,
    }


def serialize_fuel_log(log_document: dict) -> dict:
    return {
        "id": str(log_document.get("_id")),
        "vehicle_id": _serialize_reference_id(log_document.get("vehicle_id")),
        "driver_id": _serialize_reference_id(log_document.get("driver_id")),
        "assignment_id": _serialize_reference_id(log_document.get("assignment_id")),
        "fuel_station_id": _serialize_reference_id(log_document.get("fuel_station_id")),
        "fuel_date": log_document.get("fuel_date"),
        "fuel_type": log_document.get("fuel_type"),
        "litres": log_document.get("litres"),
        "amount": log_document.get("amount"),
        "price_per_litre": log_document.get("price_per_litre"),
        "odometer_reading": log_document.get("odometer_reading"),
        "receipt_image": log_document.get("receipt_image"),
        "notes": log_document.get("notes"),
        "status": log_document.get("status"),
        "submitted_by": _serialize_reference_id(log_document.get("submitted_by")),
        "approved_by": _serialize_reference_id(log_document.get("approved_by")),
        "rejected_by": _serialize_reference_id(log_document.get("rejected_by")),
        "rejection_reason": log_document.get("rejection_reason"),
        "cost_per_km": log_document.get("cost_per_km"),
        "distance_since_last_fill": log_document.get("distance_since_last_fill"),
        "previous_odometer": log_document.get("previous_odometer"),
        "abnormal_spending": bool(log_document.get("abnormal_spending")),
        "created_at": log_document.get("created_at").isoformat()
        if log_document.get("created_at")
        else None,
        "updated_at": log_document.get("updated_at").isoformat()
        if log_document.get("updated_at")
        else None,
    }
