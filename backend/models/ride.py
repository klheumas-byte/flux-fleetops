from bson import ObjectId


def _serialize_reference_id(value):
    if isinstance(value, ObjectId):
        return str(value)
    return value


def serialize_ride(ride_document: dict) -> dict:
    trip_id = ride_document.get("trip_id") or ride_document.get("ride_id")
    trip_source_id = ride_document.get("trip_source_id")
    trip_purpose_id = ride_document.get("trip_purpose_id")

    payload = {
        "id": str(ride_document.get("_id")),
        "trip_id": trip_id,
        "ride_id": trip_id,
        "customer_id": _serialize_reference_id(ride_document.get("customer_id")),
        "driver_id": _serialize_reference_id(ride_document.get("driver_id")),
        "vehicle_id": _serialize_reference_id(ride_document.get("vehicle_id")),
        "trip_source_id": _serialize_reference_id(trip_source_id),
        "trip_purpose_id": _serialize_reference_id(trip_purpose_id),
        "trip_source": ride_document.get("trip_source"),
        "trip_purpose": ride_document.get("trip_purpose"),
        "trip_date": ride_document.get("trip_date"),
        "start_time": ride_document.get("start_time"),
        "end_time": ride_document.get("end_time"),
        "pickup_area": ride_document.get("pickup_area"),
        "destination_area": ride_document.get("destination_area"),
        "odometer_start": ride_document.get("odometer_start"),
        "odometer_end": ride_document.get("odometer_end"),
        "notes": ride_document.get("notes"),
        "status": ride_document.get("status"),
        "created_by": _serialize_reference_id(ride_document.get("created_by")),
        "created_at": ride_document.get("created_at").isoformat()
        if ride_document.get("created_at")
        else None,
        "updated_at": ride_document.get("updated_at").isoformat()
        if ride_document.get("updated_at")
        else None,
        "source_booking_id": _serialize_reference_id(ride_document.get("source_booking_id")),
        "counts_toward_company_collections": ride_document.get("trip_purpose") != "Personal Ride",
        "counts_toward_utilization": True,
        "audit_events": [
            {
                "action": event.get("action"),
                "at": event.get("at").isoformat() if event.get("at") else None,
                "by": _serialize_reference_id(event.get("by")),
                "changes": event.get("changes") or [],
                "note": event.get("note"),
            }
            for event in ride_document.get("audit_events", [])
        ],
    }

    # Legacy aliases kept so existing consumers do not break while the UI shifts to trip language.
    payload["ride_source"] = payload["trip_source"]
    payload["ride_purpose"] = payload["trip_purpose"]
    payload["pickup_location"] = payload["pickup_area"]
    payload["destination"] = payload["destination_area"]
    payload["scheduled_time"] = None
    payload["estimated_fare"] = None
    payload["actual_fare"] = None
    payload["payment_method"] = None
    return payload
