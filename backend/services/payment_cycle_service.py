from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId

from extensions import get_collection


PENDING_PAYMENT_STATUSES = {"pending", "submitted", "received"}
APPROVED_PAYMENT_STATUSES = {"approved"}
REJECTED_PAYMENT_STATUSES = {"rejected"}
ARCHIVED_PAYMENT_STATUSES = {"reversed"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def collections_collection():
    return get_collection("collections")


def assignments_collection():
    return get_collection("assignments")


def users_collection():
    return get_collection("users")


def _coerce_datetime(value: str | datetime | date | None = None) -> datetime:
    if value is None:
        return now_utc()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return now_utc()
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def get_weekly_cycle_window(value: str | datetime | date | None = None) -> dict:
    reference = _coerce_datetime(value).astimezone(timezone.utc)
    week_start_dt = datetime.combine(
        (reference - timedelta(days=reference.weekday())).date(),
        time.min,
        tzinfo=timezone.utc,
    )
    payment_deadline_dt = week_start_dt + timedelta(days=5, hours=23, minutes=59, seconds=59)
    week_end_dt = payment_deadline_dt
    iso_week = week_start_dt.isocalendar()

    return {
        "cycle_key": f"{iso_week.year}-W{iso_week.week:02d}",
        "week_start": week_start_dt.date().isoformat(),
        "week_end": week_end_dt.date().isoformat(),
        "payment_deadline": payment_deadline_dt.date().isoformat(),
        "week_start_dt": week_start_dt,
        "week_end_dt": week_end_dt,
        "payment_deadline_dt": payment_deadline_dt,
    }


def collection_cycle_window(collection_document: dict) -> dict:
    if collection_document.get("cycle_key") and collection_document.get("week_start"):
        week_start_dt = _coerce_datetime(collection_document.get("week_start"))
        payment_deadline_dt = _coerce_datetime(collection_document.get("payment_deadline")) + timedelta(
            hours=23, minutes=59, seconds=59
        )
        week_end_dt = _coerce_datetime(collection_document.get("week_end")) + timedelta(
            hours=23, minutes=59, seconds=59
        )
        return {
            "cycle_key": collection_document.get("cycle_key"),
            "week_start": collection_document.get("week_start"),
            "week_end": collection_document.get("week_end"),
            "payment_deadline": collection_document.get("payment_deadline"),
            "week_start_dt": week_start_dt,
            "week_end_dt": week_end_dt,
            "payment_deadline_dt": payment_deadline_dt,
        }

    return get_weekly_cycle_window(collection_document.get("collection_date"))


def _cycle_status(weekly_target: float, approved_total: float, payment_deadline: str, *, as_of: datetime | None = None) -> str:
    if weekly_target > 0 and approved_total >= weekly_target:
        return "completed"

    reference = (as_of or now_utc()).astimezone(timezone.utc)
    deadline_dt = _coerce_datetime(payment_deadline) + timedelta(hours=23, minutes=59, seconds=59)
    if reference > deadline_dt:
        return "overdue"
    return "open"


def summarize_cycle(
    *,
    assignment_document: dict,
    cycle_window: dict,
    collection_documents: list[dict],
    as_of: datetime | None = None,
) -> dict:
    submitted_total = 0.0
    approved_total = 0.0
    payment_history = []

    for collection in collection_documents:
        amount = float(collection.get("amount") or 0)
        status = (collection.get("status") or "").strip().lower()
        if status in PENDING_PAYMENT_STATUSES or status in APPROVED_PAYMENT_STATUSES:
            submitted_total += amount
        if status in APPROVED_PAYMENT_STATUSES:
            approved_total += amount

        payment_history.append(
            {
                "id": str(collection.get("_id")) if isinstance(collection.get("_id"), ObjectId) else collection.get("id"),
                "amount": amount,
                "submitted_amount": collection.get("submitted_amount"),
                "admin_received_amount": collection.get("admin_received_amount"),
                "status": status,
                "collection_date": collection.get("collection_date"),
                "payment_method": collection.get("payment_method"),
                "reference_number": collection.get("reference_number"),
                "driver_note": collection.get("driver_note") or collection.get("notes"),
                "admin_approval_note": collection.get("admin_approval_note"),
                "rejection_reason": collection.get("rejection_reason"),
                "is_late": bool(collection.get("is_late")),
            }
        )

    weekly_target = float(assignment_document.get("weekly_target") or 0)
    outstanding_balance = round(max(weekly_target - approved_total, 0), 2)
    achievement_percentage = round((approved_total / weekly_target * 100) if weekly_target > 0 else 0, 2)

    return {
        "cycle_key": cycle_window["cycle_key"],
        "assignment_id": str(assignment_document.get("_id")),
        "week_start": cycle_window["week_start"],
        "week_end": cycle_window["week_end"],
        "payment_deadline": cycle_window["payment_deadline"],
        "weekly_target": weekly_target,
        "submitted_total": round(submitted_total, 2),
        "approved_total": round(approved_total, 2),
        "outstanding_balance": outstanding_balance,
        "achievement_percentage": achievement_percentage,
        "status": _cycle_status(weekly_target, approved_total, cycle_window["payment_deadline"], as_of=as_of),
        "payments": sorted(
            payment_history,
            key=lambda item: (item.get("collection_date") or "", item.get("id") or ""),
            reverse=True,
        ),
    }


def assignment_collections_by_cycle(assignment_id: ObjectId) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for collection in collections_collection().find({"assignment_id": assignment_id}):
        cycle_key = collection.get("cycle_key") or collection_cycle_window(collection)["cycle_key"]
        grouped.setdefault(cycle_key, []).append(collection)
    return grouped


def list_assignment_weekly_cycles(assignment_document: dict, *, limit: int = 8) -> list[dict]:
    grouped = assignment_collections_by_cycle(assignment_document["_id"])
    cycles: list[dict] = []

    if not grouped:
        current_window = get_weekly_cycle_window()
        return [
            summarize_cycle(
                assignment_document=assignment_document,
                cycle_window=current_window,
                collection_documents=[],
            )
        ]

    for cycle_key, documents in grouped.items():
        first_document = documents[0]
        cycle_window = collection_cycle_window(first_document)
        cycle_window["cycle_key"] = cycle_key
        cycles.append(
            summarize_cycle(
                assignment_document=assignment_document,
                cycle_window=cycle_window,
                collection_documents=documents,
            )
        )

    cycles.sort(key=lambda item: item["week_start"], reverse=True)
    return cycles[:limit]


def get_current_cycle_for_assignment(assignment_document: dict) -> dict:
    current_window = get_weekly_cycle_window()
    matching = list(
        collections_collection().find(
            {
                "assignment_id": assignment_document["_id"],
                "cycle_key": current_window["cycle_key"],
            }
        )
    )
    return summarize_cycle(
        assignment_document=assignment_document,
        cycle_window=current_window,
        collection_documents=matching,
    )
