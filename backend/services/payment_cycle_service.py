from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone

from bson import ObjectId
from flask import has_app_context
from pymongo import ASCENDING, DESCENDING

from extensions import get_collection
from utils.api_error import ApiError
from utils.mongo_indexes import ensure_indexes_for_collection
from utils.performance import invalidate_ttl_cache


# Ghana observes GMT year-round. A named fixed offset keeps calculations explicit
# without requiring the optional system tzdata package on Windows deployments.
GHANA_TZ = timezone(timedelta(0), "Africa/Accra")
PENDING_PAYMENT_STATUSES = {"pending", "submitted", "received"}
APPROVED_PAYMENT_STATUSES = {"approved"}
REJECTED_PAYMENT_STATUSES = {"rejected"}
ARCHIVED_PAYMENT_STATUSES = {"reversed"}
AGREEMENT_STATUSES = {"active", "paused", "ended"}
WEEK_PATTERNS = {"mon_sat": 5, "mon_sun": 6}
PAYMENT_DEADLINES = {
    "week_end": None,
    "saturday": 5,
    "sunday": 6,
    "monday_next_week": 7,
}
WORK_EXCEPTION_REASONS = {
    "sick_health",
    "emergency_personal",
    "vehicle_issue",
    "company_assignment",
    "low_work_market_issue",
    "external_issue",
    "other",
}
LEGACY_REASON_MAP = {
    "illness": "sick_health",
    "accident": "external_issue",
    "vehicle_breakdown": "vehicle_issue",
    "time_off": "emergency_personal",
    "low_earnings": "low_work_market_issue",
}
PROBLEM_REASONS = WORK_EXCEPTION_REASONS | set(LEGACY_REASON_MAP)
REQUESTED_ACTIONS = {"reduction", "full_exemption"}
LEGACY_ACTION_MAP = {"exemption": "full_exemption"}
REQUEST_STATUSES = {"submitted", "under_review", "needs_more_information", "approved", "partially_approved", "declined"}
OPEN_REQUEST_STATUSES = {"submitted", "under_review", "needs_more_information"}
CONFLICTING_REQUEST_STATUSES = OPEN_REQUEST_STATUSES | {"approved", "partially_approved"}


def now_utc():
    return datetime.now(timezone.utc)


def collections_collection(): return get_collection("collections")
def assignments_collection(): return get_collection("assignments")
def users_collection(): return get_collection("users")
def vehicles_collection(): return get_collection("vehicles")
def non_working_collection(): return get_collection("weekly_non_working_requests")


def _invalidate_remittance_caches(driver_id=None):
    prefixes=["collections:"]
    if driver_id: prefixes.extend([f"driver_wallet|driver_user_id={driver_id}", f"driver_dashboard_summary|driver_user_id={driver_id}"])
    invalidate_ttl_cache(*prefixes)


def _notify_non_working_submitted(document):
    if not has_app_context(): return
    from services.notification_service import notify_roles
    notify_roles(["owner", "admin"], "Non-working request needs review",
                 f"A driver requested non-working treatment for {document['start_date']} to {document['end_date']}.",
                 category="finance", priority="high", reference_type="weekly_non_working_request",
                 reference_id=document["_id"], action_type="review_non_working", action_url="/admin/accountability",
                 action_label="Review request", dedupe_key=f"weekly-non-working:{document['_id']}:review")
    if document.get("reason_code") in {"vehicle_issue", "company_assignment", "accident", "vehicle_breakdown"}:
        notify_roles(["operations_administrator", "operations_manager", "dispatcher"], "Driver remittance problem needs operational attention",
                     f"A driver reported {str(document.get('reason_code')).replace('_', ' ')} for {document['start_date']} to {document['end_date']}. No vehicle or trip status was changed.",
                     category="operations", priority="high", reference_type="weekly_non_working_request",
                     reference_id=document["_id"], action_url="driver-remittances",
                     action_label="Review report", dedupe_key=f"weekly-problem:{document['_id']}:operations")


def _notify_non_working_decided(document):
    if not has_app_context(): return
    from services.notification_service import create_notification
    create_notification(document["driver_id"], "Non-working request reviewed",
                        f"Request status: {document.get('request_status') or document.get('attendance_status')}. Financial treatment: {document.get('financial_treatment') or 'none'}.",
                        category="finance", priority="medium", reference_type="weekly_non_working_request",
                        reference_id=document["_id"], action_url="/driver/wallet",
                        dedupe_key=f"weekly-non-working:{document['_id']}:decision:{document.get('updated_at')}")


def ensure_remittance_indexes():
    ensure_indexes_for_collection(non_working_collection(), [
        {"keys": [("assignment_id", ASCENDING), ("week_start", ASCENDING)]},
        {"keys": [("driver_id", ASCENDING), ("created_at", DESCENDING)]},
        {"keys": [("attendance_status", ASCENDING), ("financial_status", ASCENDING)]},
        {"keys": [("request_status", ASCENDING), ("created_at", DESCENDING)]},
        {"keys": [("assignment_id", ASCENDING), ("week_starts", ASCENDING), ("request_status", ASCENDING)]},
        {"keys": [("assignment_id", ASCENDING), ("affected_dates", ASCENDING), ("request_status", ASCENDING)]},
        {"keys": [("driver_id", ASCENDING), ("reason_code", ASCENDING), ("created_at", DESCENDING)]},
        {"keys": [("request_key", ASCENDING)], "options": {"unique": True, "sparse": True}},
    ], collection_name="weekly_non_working_requests")
    ensure_indexes_for_collection(collections_collection(), [
        {"keys": [("payment_submission_key", ASCENDING)], "options": {"unique": True, "sparse": True}},
    ], collection_name="collections")


def _as_date(value, field_name="date"):
    if isinstance(value, datetime): return value.astimezone(GHANA_TZ).date() if value.tzinfo else value.date()
    if isinstance(value, date): return value
    try: return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError): raise ApiError(f"{field_name} must be a valid ISO date.", status_code=400)


def _coerce_datetime(value=None):
    if value is None: return now_utc()
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=GHANA_TZ)
    if isinstance(value, date): return datetime.combine(value, time.min, tzinfo=GHANA_TZ)
    try: parsed = datetime.fromisoformat(str(value))
    except ValueError: return now_utc()
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=GHANA_TZ)


def _object_id(value, field_name):
    if isinstance(value, ObjectId): return value
    if ObjectId.is_valid(str(value or "")): return ObjectId(str(value))
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _date_span(start: date, end: date) -> list[str]:
    values = []
    cursor = start
    while cursor <= end:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def _request_date_set(document) -> set[str]:
    explicit = document.get("affected_dates")
    if isinstance(explicit, list) and explicit:
        return {str(value)[:10] for value in explicit}
    try:
        return set(_date_span(_as_date(document.get("start_date")), _as_date(document.get("end_date"))))
    except ApiError:
        return set()


def _find_overlapping_request(assignment_id, affected_dates, *, exclude_id=None):
    query = {"assignment_id": assignment_id, "request_status": {"$in": list(CONFLICTING_REQUEST_STATUSES)}}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    requested = set(affected_dates)
    for row in non_working_collection().find(query):
        if requested.intersection(_request_date_set(row)):
            return row
    return None


def _public_history(items):
    result=[]
    for item in items or []:
        result.append({key:(str(value) if isinstance(value,ObjectId) else value.isoformat() if isinstance(value,datetime) else value) for key,value in item.items()})
    return result


def get_weekly_cycle_window(value=None, *, week_pattern="mon_sat", payment_deadline="week_end"):
    reference = _coerce_datetime(value).astimezone(GHANA_TZ)
    start_date = (reference - timedelta(days=reference.weekday())).date()
    start = datetime.combine(start_date, time.min, tzinfo=GHANA_TZ)
    week_end_day = WEEK_PATTERNS.get(week_pattern, 5)
    deadline_day = PAYMENT_DEADLINES.get(payment_deadline)
    if deadline_day is None:
        deadline_day = week_end_day
    deadline = start + timedelta(days=deadline_day, hours=23, minutes=59, seconds=59)
    iso_week = start_date.isocalendar()
    return {"cycle_key": f"{iso_week.year}-W{iso_week.week:02d}", "week_start": start_date.isoformat(),
            "week_end": (start_date + timedelta(days=week_end_day)).isoformat(), "payment_deadline": deadline.date().isoformat(),
            "week_start_dt": start, "week_end_dt": deadline, "payment_deadline_dt": deadline}


def collection_cycle_window(document):
    if document.get("cycle_key") and document.get("week_start"):
        start = _coerce_datetime(document["week_start"])
        deadline = _coerce_datetime(document.get("payment_deadline") or document.get("week_end")) + timedelta(hours=23, minutes=59, seconds=59)
        end = _coerce_datetime(document.get("week_end") or document.get("payment_deadline")) + timedelta(hours=23, minutes=59, seconds=59)
        return {"cycle_key": document["cycle_key"], "week_start": document["week_start"], "week_end": document.get("week_end"),
                "payment_deadline": document.get("payment_deadline"), "week_start_dt": start, "week_end_dt": end, "payment_deadline_dt": deadline}
    return get_weekly_cycle_window(document.get("collection_date"))


def agreement_from_assignment(assignment):
    explicit = str(assignment.get("remittance_status") or "").lower()
    status = explicit if explicit in AGREEMENT_STATUSES else ("ended" if assignment.get("status") in {"ended", "completed", "cancelled"} else "active")
    return {"id": str(assignment.get("_id")), "assignment_id": str(assignment.get("_id")),
            "driver_id": str(assignment.get("driver_id")), "vehicle_id": str(assignment.get("vehicle_id")),
            "weekly_amount": round(float(assignment.get("remittance_weekly_amount") or assignment.get("weekly_target") or 0), 2),
            "effective_start": assignment.get("remittance_start_date") or assignment.get("start_date"),
            "effective_end": assignment.get("remittance_end_date") or assignment.get("end_date"),
            "week_pattern": assignment.get("remittance_week_pattern") or "mon_sat",
            "payment_deadline": assignment.get("remittance_payment_deadline") or "week_end", "status": status,
            "rate_history": _public_history(assignment.get("remittance_rate_history")), "status_history": _public_history(assignment.get("remittance_status_history")),
            "agreement_history": _public_history(assignment.get("remittance_agreement_history")),
            "legacy_mapping": not bool(assignment.get("remittance_configured_at"))}


def _rate_for_week(assignment, week_start):
    selected = None
    for item in sorted(assignment.get("remittance_rate_history") or [], key=lambda row: str(row.get("effective_from") or "")):
        if not item.get("effective_from"): continue
        start = _as_date(item["effective_from"], "effective_from")
        end = _as_date(item["effective_to"], "effective_to") if item.get("effective_to") else None
        if start <= week_start and (end is None or week_start <= end): selected = item
    return round(float((selected or {}).get("weekly_amount") or assignment.get("remittance_weekly_amount") or assignment.get("weekly_target") or 0), 2)


def _status_for_week(assignment, week_start):
    selected = None
    for item in sorted(assignment.get("remittance_status_history") or [], key=lambda row: str(row.get("effective_from") or "")):
        if item.get("effective_from") and _as_date(item["effective_from"]) <= week_start:
            selected = item.get("status")
    return selected or "active"


def _payment_actor_summary(user):
    if not user:
        return None
    return {"id": str(user.get("_id")), "full_name": user.get("full_name"),
            "role": user.get("role"), "email": user.get("email")}


def _payment_summary(item, actor_lookup=None):
    actor_lookup = actor_lookup or {}
    submitted_by_id = item.get("submitted_by_driver_id")
    approved_by_id = item.get("approved_by_admin_id")
    rejected_by_id = item.get("rejected_by_admin_id")
    reversed_by_id = item.get("reversed_by_admin_id")
    allocations = _allocations(item)
    result = {key: item.get(key) for key in ("submitted_amount", "admin_received_amount", "status", "collection_date", "payment_method", "reference_number", "admin_approval_note", "rejection_reason", "is_late")}
    result.update({"id": str(item.get("_id")), "amount": round(float(item.get("amount") or 0), 2), "actual_payment_date": item.get("collection_date"), "driver_note": item.get("driver_note") or item.get("notes"),
                   "submitted_by_user": _payment_actor_summary(actor_lookup.get(submitted_by_id)),
                   "confirmed_by_user": _payment_actor_summary(actor_lookup.get(approved_by_id)),
                   "rejected_by_user": _payment_actor_summary(actor_lookup.get(rejected_by_id)),
                   "reversed_by_user": _payment_actor_summary(actor_lookup.get(reversed_by_id)) or item.get("reversal_actor"),
                   "submitted_by_id": str(submitted_by_id) if submitted_by_id else None,
                   "confirmed_by_id": str(approved_by_id) if approved_by_id else None,
                   "reversal_reason": item.get("reversal_reason") or item.get("correction_reason"),
                   "decision_reason": item.get("admin_approval_note"),
                   "weeks_covered": [row.get("cycle_key") for row in allocations if row.get("cycle_key")],
                   "allocations": allocations})
    for key in ("created_at", "submitted_at", "approved_at", "rejected_at", "reversed_at"):
        value = item.get(key); result[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return result


def _allocations(item):
    explicit = item.get("remittance_allocations")
    if isinstance(explicit, list): return [row for row in explicit if float(row.get("amount") or 0) > 0]
    window = collection_cycle_window(item)
    return [{"cycle_key": window["cycle_key"], "week_start": window["week_start"], "amount": float(item.get("amount") or 0), "legacy": True}]


def _allocations_as_of(item, cutoff):
    """Return the allocation state known at a historical cutoff without rewriting audit time."""
    current = _allocations(item)
    history = sorted(
        item.get("remittance_allocation_history") or [],
        key=lambda row: _coerce_datetime(row.get("changed_at")),
    )
    eligible = [row for row in history if _coerce_datetime(row.get("changed_at")) <= cutoff]
    if eligible:
        return [row for row in (eligible[-1].get("after") or []) if float(row.get("amount") or 0) > 0]
    if history and _coerce_datetime(history[0].get("changed_at")) > cutoff:
        before = history[0].get("before")
        if isinstance(before, list):
            return [row for row in before if float(row.get("amount") or 0) > 0]
    allocated_at = item.get("remittance_allocated_at")
    if allocated_at and _coerce_datetime(allocated_at) > cutoff:
        return []
    return current


def _is_remittance_payment(item):
    """Safely map legacy assignment collections without absorbing dispatch cash."""
    if item.get("dispatch_job_id") or item.get("dispatch_financial_id"):
        return False
    source_key = str(item.get("collection_source_key") or "").lower()
    if source_key.startswith("dispatch:"):
        return False
    purpose = str(item.get("payment_purpose") or "").lower()
    return purpose in {"", "weekly_remittance", "weekly_target"}


def _payment_status_as_of(item, end_of_as_of):
    history = sorted(
        item.get("status_history") or [],
        key=lambda row: _coerce_datetime(row.get("at") or row.get("changed_at")),
    )
    selected = None
    for event in history:
        if _coerce_datetime(event.get("at") or event.get("changed_at")) <= end_of_as_of:
            selected = str(event.get("status") or "").lower()
    if selected:
        return selected
    current = str(item.get("status") or "").lower()
    approved_at = item.get("approved_at")
    reversed_at = item.get("reversed_at")
    if current == "approved" and approved_at and _coerce_datetime(approved_at) > end_of_as_of:
        return "submitted"
    if current == "reversed" and reversed_at and _coerce_datetime(reversed_at) > end_of_as_of:
        return "approved" if approved_at and _coerce_datetime(approved_at) <= end_of_as_of else "submitted"
    return current


def serialize_non_working(document):
    if not document: return None
    result = {key: value for key, value in document.items() if key != "_id"}; result["id"] = str(document.get("_id"))
    for key, value in list(result.items()):
        if isinstance(value, ObjectId): result[key] = str(value)
        elif isinstance(value, datetime): result[key] = value.isoformat()
        elif isinstance(value, list):
            result[key] = [{k: (str(v) if isinstance(v, ObjectId) else v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()} if isinstance(row, dict) else row for row in value]
    return result


def _decision_actor_snapshot(actor_id):
    actor = users_collection().find_one({"_id": actor_id}, {"full_name": 1, "role": 1, "email": 1})
    if not actor:
        return {"id": str(actor_id), "full_name": None, "role": None, "email": None}
    return {"id": str(actor["_id"]), "full_name": actor.get("full_name"), "role": actor.get("role"), "email": actor.get("email")}


def _request_as_of(document, end_of_as_of):
    row = dict(document)
    if _coerce_datetime(row.get("created_at")) > end_of_as_of:
        return None
    selected_status = "submitted"
    for event in sorted(row.get("request_status_history") or [], key=lambda item: _coerce_datetime(item.get("at"))):
        if _coerce_datetime(event.get("at")) <= end_of_as_of:
            selected_status = event.get("status") or selected_status
    row["request_status"] = selected_status
    if row.get("financial_decided_at") and _coerce_datetime(row.get("financial_decided_at")) > end_of_as_of:
        row.update({"attendance_status": "pending", "financial_status": "pending", "financial_treatment": None,
                    "approved_amount": None, "revised_amount_due": None, "approved_adjustment": 0.0,
                    "revised_deadline": None, "decision_reason": None})
    return row


def _empty_position(as_of=None):
    return {"gross_expected": 0.0, "approved_waivers_reductions": 0.0, "adjusted_expected": 0.0,
            "confirmed_receipts": 0.0, "total_confirmed_receipts": 0.0, "confirmed_allocated_payments": 0.0,
            "available_credit": 0.0, "applicable_credit": 0.0,
            "outstanding": 0.0, "total_unpaid": 0.0, "current_week_unpaid": 0.0,
            "pending_confirmation": 0.0, "arrears": 0.0, "overdue_balance": 0.0,
            "defaulted_week_count": 0, "defaulted_weeks": [], "currently_unpaid_overdue_weeks": [],
            "as_of": _coerce_datetime(as_of).astimezone(GHANA_TZ).date().isoformat()}


def build_weekly_ledger(assignment, *, as_of=None, start_date=None, limit=None, payment_documents=None, decision_documents=None):
    agreement = agreement_from_assignment(assignment)
    if not agreement["effective_start"] or agreement["weekly_amount"] <= 0:
        return {"agreement": agreement, "weeks": [], "position": _empty_position(as_of)}
    reference = _coerce_datetime(as_of); reference_date = reference.astimezone(GHANA_TZ).date()
    agreement_start = _as_date(agreement["effective_start"], "effective_start"); first_week = agreement_start - timedelta(days=agreement_start.weekday())
    cursor = first_week
    requested_start_week = None
    if start_date:
        requested = _as_date(start_date, "start_date"); requested_start_week = requested - timedelta(days=requested.weekday())
    agreement_end = _as_date(agreement["effective_end"], "effective_end") if agreement["effective_end"] else reference_date
    last_date = min(reference_date, agreement_end)
    windows = []
    while cursor <= last_date and len(windows) < 520:
        windows.append(get_weekly_cycle_window(
            cursor,
            week_pattern=agreement["week_pattern"],
            payment_deadline=agreement["payment_deadline"],
        )); cursor += timedelta(days=7)
    if not windows: return {"agreement": agreement, "weeks": [], "position": _empty_position(as_of)}

    week_starts = [row["week_start"] for row in windows]
    decision_rows = decision_documents if decision_documents is not None else list(non_working_collection().find({"assignment_id": assignment["_id"], "$or": [{"week_start": {"$in": week_starts}}, {"week_starts": {"$in": week_starts}}]}))
    decision_cutoff = datetime.combine(reference_date, time.max, tzinfo=GHANA_TZ)
    decision_rows = [row for item in decision_rows if (row := _request_as_of(item, decision_cutoff)) is not None]
    decisions_by_week = {key: [] for key in week_starts}
    for row in decision_rows:
        affected = row.get("week_starts") or [row.get("week_start")]
        for affected_week in affected:
            if affected_week in week_starts:
                decisions_by_week[affected_week].append(row)
    decisions = {}
    for week_start, rows in decisions_by_week.items():
        if not rows:
            continue
        rows.sort(key=lambda row: _coerce_datetime(row.get("financial_decided_at") or row.get("updated_at") or row.get("created_at")))
        approved_rows = [row for row in rows if row.get("attendance_status") == "confirmed" and row.get("financial_status") == "approved"]
        decisions[week_start] = approved_rows[-1] if approved_rows else rows[-1]
    payments = payment_documents if payment_documents is not None else list(collections_collection().find({"assignment_id": assignment["_id"], "status": {"$in": list(PENDING_PAYMENT_STATUSES | APPROVED_PAYMENT_STATUSES | REJECTED_PAYMENT_STATUSES | ARCHIVED_PAYMENT_STATUSES)}, "collection_date": {"$lte": reference_date.isoformat()}}).sort([("collection_date", ASCENDING), ("created_at", ASCENDING)]))
    end_of_as_of = datetime.combine(reference_date, time.max, tzinfo=GHANA_TZ)
    payments = [
        row for row in payments
        if _is_remittance_payment(row)
        and str(row.get("collection_date") or "")[:10] <= reference_date.isoformat()
        and _coerce_datetime(row.get("submitted_at") or row.get("created_at") or row.get("collection_date")) <= end_of_as_of
    ]
    actor_ids = {
        actor_id for payment in payments
        for actor_id in (payment.get("submitted_by_driver_id"), payment.get("approved_by_admin_id"), payment.get("rejected_by_admin_id"), payment.get("reversed_by_admin_id"))
        if isinstance(actor_id, ObjectId)
    }
    actor_lookup = {row["_id"]: row for row in users_collection().find(
        {"_id": {"$in": list(actor_ids)}}, {"full_name": 1, "role": 1, "email": 1}
    )} if actor_ids else {}
    approved = {row["cycle_key"]: 0.0 for row in windows}; pending = dict(approved); history = {key: [] for key in approved}
    approved_receipts = allocated_total = pending_receipts = available_credit = 0.0
    credit_payments = []
    for payment in payments:
        status = _payment_status_as_of(payment, end_of_as_of); amount = float(payment.get("amount") or 0)
        allocations = _allocations_as_of(payment, end_of_as_of)
        if status in APPROVED_PAYMENT_STATUSES:
            approved_receipts += amount
            payment_allocated = round(sum(float(row.get("amount") or 0) for row in allocations), 2)
            payment_credit = max(round(amount-payment_allocated, 2), 0)
            available_credit += payment_credit
            if payment_credit:
                credit_row = _payment_summary(payment, actor_lookup)
                credit_row["status"] = status
                credit_row.update({"allocated_amount": payment_allocated, "unallocated_amount": payment_credit,
                                   "allocations": allocations})
                credit_payments.append(credit_row)
            for allocation in allocations:
                value = round(float(allocation.get("amount") or 0), 2); allocated_total += value; key = allocation.get("cycle_key")
                if key in approved:
                    approved[key] += value
                    payment_row = _payment_summary(payment, actor_lookup)
                    payment_row["status"] = status
                    payment_row["allocated_amount"] = value
                    history[key].append(payment_row)
        elif status in PENDING_PAYMENT_STATUSES:
            pending_receipts += amount
            # An explicit allocation list, including an empty list, is
            # authoritative. Only records that predate allocation support use
            # the payment-date cycle fallback.
            pending_allocations = (
                allocations
                if isinstance(payment.get("remittance_allocations"), list)
                else [{"cycle_key": collection_cycle_window(payment)["cycle_key"], "amount": amount}]
            )
            for allocation in pending_allocations:
                key = allocation.get("cycle_key"); value = round(float(allocation.get("amount") or 0), 2)
                if key in pending:
                    pending[key] += value
                    payment_row = _payment_summary(payment, actor_lookup); payment_row["status"] = status; payment_row["allocated_amount"] = value; history[key].append(payment_row)
        elif status in REJECTED_PAYMENT_STATUSES | ARCHIVED_PAYMENT_STATUSES:
            audit_allocations = allocations or [{"cycle_key": collection_cycle_window(payment)["cycle_key"], "amount": amount}]
            for allocation in audit_allocations:
                key = allocation.get("cycle_key")
                if key in history:
                    payment_row = _payment_summary(payment, actor_lookup)
                    payment_row["status"] = status
                    payment_row["allocated_amount"] = round(float(allocation.get("amount") or 0), 2)
                    history[key].append(payment_row)

    weeks = []
    for window in windows:
        week_date = _as_date(window["week_start"]); week_agreement_status = _status_for_week(assignment, week_date)
        original = 0.0 if week_agreement_status in {"paused", "ended"} else _rate_for_week(assignment, week_date); decision = decisions.get(window["week_start"])
        adjustment = 0.0; waived = False
        if decision and decision.get("attendance_status") == "confirmed" and decision.get("financial_status") == "approved":
            week_decision = (decision.get("affected_week_decisions") or {}).get(window["week_start"], {})
            if decision.get("financial_treatment") == "waive": adjustment, waived = original, True
            elif decision.get("financial_treatment") == "reduce":
                revised_due = week_decision.get("revised_amount_due")
                if revised_due is None:
                    revised_due = decision.get("revised_amount_due")
                if revised_due is None:
                    revised_due = decision.get("approved_amount")
                adjustment = max(original - float(revised_due or 0), 0)
        final_due = round(max(original-adjustment, 0), 2); paid = round(approved[window["cycle_key"]], 2); waiting = round(pending[window["cycle_key"]], 2); outstanding = round(max(final_due-paid, 0), 2)
        original_deadline = _coerce_datetime(window["payment_deadline"]) + timedelta(hours=23, minutes=59, seconds=59)
        # Work exceptions can revise the obligation, never its deadline.
        deadline = original_deadline
        is_overdue = outstanding > 0 and reference > deadline
        if week_agreement_status in {"paused", "ended"}: status = week_agreement_status
        elif waived: status = "waived"
        elif final_due <= paid: status = "reduced" if adjustment else "paid"
        elif waiting: status = "pending_confirmation"
        elif paid: status = "partial"
        elif is_overdue: status = "overdue"
        else: status = "reduced" if adjustment else "due"
        week_payments = []
        confirmed_by_deadline = 0.0
        for payment in history[window["cycle_key"]]:
            payment = dict(payment)
            paid_at = payment.get("actual_payment_date") or payment.get("collection_date")
            payment["is_late"] = bool(paid_at and _coerce_datetime(paid_at) > deadline)
            if payment.get("status") in APPROVED_PAYMENT_STATUSES and paid_at and _coerce_datetime(paid_at) <= deadline:
                confirmed_by_deadline += float(payment.get("allocated_amount") or 0)
            week_payments.append(payment)
        defaulted = bool(final_due > 0 and reference > deadline and round(confirmed_by_deadline, 2) < final_due)
        if waived: payment_status = "excused_no_payment_due"
        elif defaulted and outstanding <= 0: payment_status = "paid_late"
        elif defaulted and paid > 0: payment_status = "part_paid"
        elif defaulted: payment_status = "overdue"
        elif outstanding <= 0: payment_status = "paid"
        elif waiting > 0: payment_status = "pending_confirmation"
        elif adjustment > 0: payment_status = "reduced_amount_due"
        elif paid > 0: payment_status = "part_paid"
        else: payment_status = "not_yet_due"
        if payment_status == "paid_late": status = "paid_late"
        request_status = (decision or {}).get("request_status")
        if request_status in {"submitted", "under_review"}: next_responsible_person = "admin"
        elif request_status == "needs_more_information": next_responsible_person = "driver"
        elif waiting > 0: next_responsible_person = "admin_payment_confirmation"
        elif outstanding > 0: next_responsible_person = "driver"
        else: next_responsible_person = None
        payment_status_labels = {"not_yet_due": "Not Yet Due", "paid": "Paid", "part_paid": "Part-Paid", "overdue": "Overdue", "paid_late": "Paid Late", "pending_confirmation": "Pending Confirmation", "reduced_amount_due": "Reduced Amount Due", "excused_no_payment_due": "Excused — No Payment Due"}
        weeks.append({"cycle_key": window["cycle_key"], "assignment_id": str(assignment["_id"]), "vehicle_id": str(assignment.get("vehicle_id")), "week_start": window["week_start"], "week_end": window["week_end"], "payment_deadline": window["payment_deadline"],
                      "original_deadline": window["payment_deadline"], "effective_deadline": deadline.date().isoformat(),
                      "original_amount": original, "weekly_target": original, "approved_adjustment": round(adjustment,2), "final_due": final_due,
                      "confirmed_allocated_payments": paid, "approved_total": paid, "pending_total": waiting, "submitted_total": round(paid+waiting,2),
                      "outstanding": outstanding, "outstanding_balance": outstanding, "achievement_percentage": round((paid/final_due*100) if final_due else 100,2),
                      "status": status, "is_overdue": is_overdue, "is_partial": paid > 0 and outstanding > 0,
                      "is_reduced": adjustment > 0 and not waived, "is_waived": waived,
                      "payment_status": payment_status, "payment_status_label": payment_status_labels[payment_status],
                      "exception_reason": (decision or {}).get("reason_code") if decision and decision.get("financial_status") == "approved" else None,
                      "exception_explanation": (decision or {}).get("explanation") if decision and decision.get("financial_status") == "approved" else None,
                      "defaulted": defaulted, "confirmed_by_deadline": round(confirmed_by_deadline, 2),
                      "request_status": request_status, "next_responsible_person": next_responsible_person,
                      "agreement_status": week_agreement_status, "problem_request": serialize_non_working(decision),
                      "non_working_request": serialize_non_working(decision), "revision_history": (serialize_non_working(decision) or {}).get("audit_history", []), "payments": week_payments})
    position_weeks = [row for row in weeks if not requested_start_week or _as_date(row["week_start"]) >= requested_start_week]
    excluded_weeks = [row for row in weeks if row not in position_weeks]
    gross = round(sum(row["original_amount"] for row in position_weeks),2); adjustments = round(sum(row["approved_adjustment"] for row in position_weeks),2); adjusted = round(sum(row["final_due"] for row in position_weeks),2)
    applicable = round(sum(min(row["confirmed_allocated_payments"], row["final_due"]) for row in position_weeks),2)
    available_credit = round(available_credit,2)
    outstanding_before_credit = round(sum(row["outstanding"] for row in position_weeks),2)
    overdue_before_credit=round(sum(row["outstanding"] for row in position_weeks if row["is_overdue"]),2)
    current_cycle_key=get_weekly_cycle_window(reference_date,week_pattern=agreement["week_pattern"],payment_deadline=agreement["payment_deadline"])["cycle_key"]
    current_week_unpaid=round(sum(row["outstanding"] for row in position_weeks if row["cycle_key"]==current_cycle_key),2)
    defaulted_weeks=[row["cycle_key"] for row in position_weeks if row["defaulted"]]
    unpaid_overdue_weeks=[row["cycle_key"] for row in position_weeks if row["is_overdue"]]
    position = {"gross_expected":gross,"approved_waivers_reductions":adjustments,"adjusted_expected":adjusted,"confirmed_receipts":applicable,
                "total_confirmed_receipts":round(approved_receipts,2),"confirmed_allocated_payments":applicable,"available_credit":available_credit,
                "applicable_credit":available_credit,"outstanding":outstanding_before_credit,
                "pending_confirmation":round(pending_receipts,2),"arrears":overdue_before_credit,
                "overdue_balance":overdue_before_credit,"current_week_unpaid":current_week_unpaid,
                "total_unpaid":outstanding_before_credit,"defaulted_week_count":len(defaulted_weeks),
                "defaulted_weeks":defaulted_weeks,"currently_unpaid_overdue_weeks":unpaid_overdue_weeks,
                "range_start":position_weeks[0]["week_start"] if position_weeks else None,"range_end":reference_date.isoformat(),"as_of":reference_date.isoformat()}
    result_weeks = sorted(position_weeks,key=lambda row:row["week_start"],reverse=True)
    return {"agreement":agreement,"weeks":result_weeks[:limit] if limit else result_weeks,
            "position":position,"credit_payments":credit_payments}


def summarize_cycle(*, assignment_document, cycle_window, collection_documents, as_of=None):
    target = _rate_for_week(assignment_document,_as_date(cycle_window["week_start"])); submitted=sum(float(row.get("amount") or 0) for row in collection_documents if row.get("status") in PENDING_PAYMENT_STATUSES|APPROVED_PAYMENT_STATUSES); paid=sum(float(row.get("amount") or 0) for row in collection_documents if row.get("status") in APPROVED_PAYMENT_STATUSES); due=round(max(target-paid,0),2)
    deadline=_coerce_datetime(cycle_window["payment_deadline"])+timedelta(hours=23,minutes=59,seconds=59); reference=_coerce_datetime(as_of)
    status="paid" if due<=0 else "partial" if paid else "overdue" if reference>deadline else "due"
    return {"cycle_key":cycle_window["cycle_key"],"assignment_id":str(assignment_document.get("_id")),"week_start":cycle_window["week_start"],"week_end":cycle_window["week_end"],"payment_deadline":cycle_window["payment_deadline"],"original_amount":target,"weekly_target":target,"approved_adjustment":0.0,"final_due":target,"submitted_total":round(submitted,2),"approved_total":round(paid,2),"confirmed_allocated_payments":round(paid,2),"outstanding":due,"outstanding_balance":due,"achievement_percentage":round((paid/target*100) if target else 100,2),"status":status,"payments":[_payment_summary(row) for row in collection_documents]}


def assignment_collections_by_cycle(assignment_id):
    grouped={}
    for item in collections_collection().find({"assignment_id":assignment_id}): grouped.setdefault(item.get("cycle_key") or collection_cycle_window(item)["cycle_key"],[]).append(item)
    return grouped


def list_assignment_weekly_cycles(assignment_document, *, limit=8): return build_weekly_ledger(assignment_document,limit=limit)["weeks"]


def get_current_cycle_for_assignment(assignment_document):
    window=get_weekly_cycle_window(); ledger=build_weekly_ledger(assignment_document)
    return next((row for row in ledger["weeks"] if row["cycle_key"]==window["cycle_key"]),summarize_cycle(assignment_document=assignment_document,cycle_window=window,collection_documents=[]))


def auto_allocate_confirmed_payment(document, *, current_user_id):
    if document.get("status")!="approved" or not document.get("assignment_id") or not _is_remittance_payment(document) or isinstance(document.get("remittance_allocations"),list): return document
    assignment=assignments_collection().find_one({"_id":document["assignment_id"]})
    if not assignment:return document
    # Include obligations through today: a late receipt must clear old debt before becoming credit.
    other_payments=list(collections_collection().find({"assignment_id":assignment["_id"],"_id":{"$ne":document["_id"]},"status":{"$in":list(PENDING_PAYMENT_STATUSES|APPROVED_PAYMENT_STATUSES)}}).sort([("collection_date",ASCENDING),("created_at",ASCENDING)]))
    ledger=build_weekly_ledger(assignment,payment_documents=other_payments); remaining=round(float(document.get("amount") or 0),2); allocations=[]
    for week in sorted(ledger["weeks"],key=lambda row:row["week_start"]):
        if remaining<=0:break
        amount=min(round(float(week["outstanding"]),2),remaining)
        if amount>0: allocations.append({"cycle_key":week["cycle_key"],"week_start":week["week_start"],"amount":amount});remaining=round(remaining-amount,2)
    timestamp=now_utc(); fields={"remittance_allocations":allocations,"remittance_unallocated_credit":remaining,"remittance_allocated_at":timestamp,"remittance_allocated_by":_object_id(current_user_id,"current_user_id")}
    result=collections_collection().update_one({"_id":document["_id"],"remittance_allocations":{"$exists":False}},{"$set":fields})
    if result.modified_count: document.update(fields)
    else:
        fresh=collections_collection().find_one({"_id":document["_id"]});document.update({key:fresh.get(key) for key in fields})
    return document


def normalize_payment_allocations(assignment, allocations, payment_amount, *, exclude_payment_id=None):
    """Validate editable allocations against obligation balances without creating parallel records."""
    query={"assignment_id":assignment["_id"],"status":{"$in":list(PENDING_PAYMENT_STATUSES|APPROVED_PAYMENT_STATUSES)}}
    if exclude_payment_id: query["_id"]={"$ne":exclude_payment_id}
    other_payments=list(collections_collection().find(query).sort([("collection_date",ASCENDING),("created_at",ASCENDING)]))
    valid={row["cycle_key"]:row for row in build_weekly_ledger(assignment,payment_documents=other_payments)["weeks"]}
    normalized=[];total=0.0;seen=set()
    for item in allocations or []:
        key=str(item.get("cycle_key") or "")
        try: amount=round(float(item.get("amount") or 0),2)
        except (TypeError,ValueError): raise ApiError("Each allocation amount must be a number.",status_code=400)
        if key not in valid or key in seen or amount<=0:
            raise ApiError("Each allocation must use one eligible week once and a positive amount.",status_code=400)
        if amount>round(float(valid[key]["outstanding"]),2):
            raise ApiError(f"Allocation for {key} exceeds its remaining balance.",status_code=400)
        seen.add(key);total=round(total+amount,2)
        normalized.append({"cycle_key":key,"week_start":valid[key]["week_start"],"amount":amount})
    if total>round(float(payment_amount or 0),2):
        raise ApiError("Allocations cannot exceed the payment amount.",status_code=400)
    return normalized


def replace_payment_allocations(collection_id, allocations, *, current_user_id):
    payment=collections_collection().find_one({"_id":_object_id(collection_id,"collection_id"),"status":"approved"})
    if not payment:raise ApiError("Confirmed payment not found.",status_code=404)
    if not _is_remittance_payment(payment):raise ApiError("Dispatch receipts cannot be allocated to weekly remittance.",status_code=400)
    assignment=assignments_collection().find_one({"_id":payment.get("assignment_id")})
    if not assignment:raise ApiError("Payment assignment not found.",status_code=404)
    payment_amount=round(float(payment.get("amount") or 0),2)
    normalized=normalize_payment_allocations(assignment,allocations,payment_amount,exclude_payment_id=payment["_id"])
    total=round(sum(row["amount"] for row in normalized),2)
    timestamp=now_utc();actor=_object_id(current_user_id,"current_user_id");event={"changed_at":timestamp,"changed_by":actor,"before":payment.get("remittance_allocations"),"after":normalized}
    collections_collection().update_one({"_id":payment["_id"]},{"$set":{"remittance_allocations":normalized,"remittance_unallocated_credit":round(payment_amount-total,2),"remittance_allocated_at":timestamp,"remittance_allocated_by":actor},"$push":{"remittance_allocation_history":event}})
    _invalidate_remittance_caches(payment.get("driver_id"))
    return {"collection_id":str(payment["_id"]),"allocations":normalized,"credit":round(payment_amount-total,2)}


def apply_confirmed_credit(assignment_id, allocations=None, *, current_user_id):
    """Allocate existing confirmed, unallocated money to obligations; never create another receipt."""
    assignment=assignments_collection().find_one({"_id":_object_id(assignment_id,"assignment_id")})
    if not assignment: raise ApiError("Weekly remittance agreement not found.",status_code=404)
    ledger=build_weekly_ledger(assignment)
    outstanding=sorted(
        [row for row in ledger["weeks"] if row["outstanding"]>0 and row["is_overdue"]],
        key=lambda row:row["week_start"],
    )
    available=round(float(ledger["position"]["available_credit"]),2)
    if available<=0: raise ApiError("No confirmed unallocated credit is available.",status_code=400)
    if allocations is None:
        requested=[];remaining=available
        for week in outstanding:
            amount=min(remaining,round(float(week["outstanding"]),2))
            if amount>0: requested.append({"cycle_key":week["cycle_key"],"amount":amount});remaining=round(remaining-amount,2)
            if remaining<=0: break
    else:
        requested=allocations
    valid={row["cycle_key"]:row for row in outstanding};targets=[];requested_total=0.0;seen=set()
    for item in requested or []:
        key=str(item.get("cycle_key") or "")
        try: amount=round(float(item.get("amount") or 0),2)
        except (TypeError,ValueError): raise ApiError("Each allocation amount must be a number.",status_code=400)
        if key not in valid or key in seen or amount<=0: raise ApiError("Credit can only be applied once to an outstanding eligible week.",status_code=400)
        if amount>round(float(valid[key]["outstanding"]),2): raise ApiError(f"Allocation for {key} exceeds its remaining balance.",status_code=400)
        seen.add(key);requested_total=round(requested_total+amount,2);targets.append({"cycle_key":key,"week_start":valid[key]["week_start"],"amount":amount})
    if requested_total<=0: raise ApiError("At least one credit allocation is required.",status_code=400)
    if requested_total>available: raise ApiError("Allocations cannot exceed available confirmed credit.",status_code=400)

    payments=list(collections_collection().find({"assignment_id":assignment["_id"],"status":"approved"}).sort([("approved_at",ASCENDING),("created_at",ASCENDING)]))
    actor=_object_id(current_user_id,"current_user_id");timestamp=now_utc();target_index=0
    for payment in payments:
        before=_allocations(payment);payment_amount=round(float(payment.get("amount") or 0),2)
        payment_remaining=round(max(payment_amount-sum(float(row.get("amount") or 0) for row in before),0),2)
        if payment_remaining<=0: continue
        after=[dict(row) for row in before]
        while payment_remaining>0 and target_index<len(targets):
            target=targets[target_index];take=min(payment_remaining,target["amount"])
            existing=next((row for row in after if row.get("cycle_key")==target["cycle_key"]),None)
            if existing: existing["amount"]=round(float(existing.get("amount") or 0)+take,2)
            else: after.append({"cycle_key":target["cycle_key"],"week_start":target["week_start"],"amount":take})
            payment_remaining=round(payment_remaining-take,2);target["amount"]=round(target["amount"]-take,2)
            if target["amount"]<=0: target_index+=1
        if after!=before:
            event={"changed_at":timestamp,"changed_by":actor,"before":before,"after":after,"reason":"apply_confirmed_credit"}
            result=collections_collection().update_one({"_id":payment["_id"],"remittance_allocations":payment.get("remittance_allocations")},{"$set":{"remittance_allocations":after,"remittance_unallocated_credit":payment_remaining,"remittance_allocated_at":timestamp,"remittance_allocated_by":actor},"$push":{"remittance_allocation_history":event}})
            if not result.modified_count: raise ApiError("Credit changed while it was being allocated. Refresh and try again.",status_code=409)
        if target_index>=len(targets): break
    if target_index<len(targets): raise ApiError("Available credit changed while it was being allocated. Refresh and try again.",status_code=409)
    _invalidate_remittance_caches(assignment.get("driver_id"))
    refreshed=build_weekly_ledger(assignment)
    return {"assignment_id":str(assignment["_id"]),"applied":requested_total,"position":refreshed["position"],"weeks":refreshed["weeks"]}


def submit_non_working_request(payload, *, current_user_id, request_key=None, driver_id=None, entered_by_role="driver"):
    actor = _object_id(current_user_id, "current_user_id")
    target_driver_id = _object_id(driver_id or current_user_id, "driver_id")
    assignment_query = {"driver_id": target_driver_id, "status": {"$in": ["active", "suspended"]}, "target_enabled": {"$ne": False}}
    if payload.get("assignment_id"):
        assignment_query["_id"] = _object_id(payload.get("assignment_id"), "assignment_id")
    assignment = assignments_collection().find_one(assignment_query, sort=[("created_at", DESCENDING)])
    if not assignment:
        raise ApiError("No active weekly remittance agreement was found for this driver.", status_code=400)
    selection_type = str(payload.get("selection_type") or "date_range").strip().lower()
    if selection_type not in {"single_day", "multiple_days", "date_range", "whole_week"}:
        raise ApiError("selection_type must be single_day, multiple_days, date_range, or whole_week.", status_code=400)
    supplied_dates = payload.get("affected_dates") or []
    if supplied_dates and not isinstance(supplied_dates, list):
        raise ApiError("affected_dates must be a list of ISO dates.", status_code=400)
    parsed_dates = sorted({_as_date(value, "affected_dates") for value in supplied_dates})
    start = parsed_dates[0] if parsed_dates else _as_date(payload.get("start_date"), "start_date")
    end = parsed_dates[-1] if parsed_dates else _as_date(payload.get("end_date") or payload.get("start_date"), "end_date")
    if end < start:
        raise ApiError("end_date cannot be before start_date.", status_code=400)
    agreement = agreement_from_assignment(assignment)
    if selection_type == "whole_week":
        whole_week = get_weekly_cycle_window(start, week_pattern=agreement["week_pattern"])
        start, end = _as_date(whole_week["week_start"]), _as_date(whole_week["week_end"])
        parsed_dates = []
    affected_dates = [value.isoformat() for value in parsed_dates] if parsed_dates else _date_span(start, end)
    if selection_type == "single_day" and len(affected_dates) != 1:
        raise ApiError("A single-day exception must contain exactly one affected date.", status_code=400)
    if selection_type == "multiple_days" and len(affected_dates) < 2:
        raise ApiError("A multiple-day exception must contain at least two affected dates.", status_code=400)
    reason_code = str(payload.get("reason_code") or "other").strip().lower()
    reason_code = LEGACY_REASON_MAP.get(reason_code, reason_code)
    if reason_code not in WORK_EXCEPTION_REASONS:
        raise ApiError("Invalid work-exception reason category.", status_code=400)
    explanation = str(payload.get("explanation") or payload.get("notes") or payload.get("reason") or "").strip()
    if not explanation:
        raise ApiError("explanation is required for a work exception.", status_code=400)
    requested_action = str(payload.get("requested_action") or "full_exemption").strip().lower()
    requested_action = LEGACY_ACTION_MAP.get(requested_action, requested_action)
    if requested_action not in REQUESTED_ACTIONS:
        raise ApiError("requested_action must be reduction or full_exemption.", status_code=400)
    attachments = payload.get("attachments") if payload.get("attachments") is not None else payload.get("evidence") or []
    if not isinstance(attachments, list) or len(attachments) > 10:
        raise ApiError("attachments must be a list with at most 10 items.", status_code=400)
    week = get_weekly_cycle_window(start, week_pattern=agreement["week_pattern"])
    key = f"remittance-problem:{target_driver_id}:{request_key}" if request_key else None
    if key:
        existing = non_working_collection().find_one({"request_key": key})
        if existing:
            return serialize_non_working(existing)
    affected_weeks = []
    cursor = _as_date(week["week_start"])
    while cursor <= end:
        affected_weeks.append(cursor.isoformat())
        cursor += timedelta(days=7)
    overlap = _find_overlapping_request(assignment["_id"], affected_dates)
    if overlap:
        raise ApiError(f"An overlapping request already exists ({overlap['_id']}). Update that request instead.", status_code=409)
    timestamp = now_utc()
    original_weekly_amounts = {
        week_start: _rate_for_week(assignment, _as_date(week_start))
        for week_start in affected_weeks
    }
    document = {
        "assignment_id": assignment["_id"], "driver_id": target_driver_id, "vehicle_id": assignment.get("vehicle_id"),
        "week_start": week["week_start"], "week_starts": affected_weeks, "cycle_key": week["cycle_key"],
        "start_date": start.isoformat(), "end_date": end.isoformat(), "selection_type": selection_type,
        "affected_dates": affected_dates, "affected_working_days": len(affected_dates), "reason": explanation,
        "reason_code": reason_code, "explanation": explanation, "notes": explanation,
        "requested_action": requested_action, "attachments": attachments, "evidence": attachments,
        "request_status": "submitted", "attendance_status": "pending", "financial_status": "pending",
        "financial_treatment": None, "approved_amount": None, "revised_amount_due": None,
        "original_amount": original_weekly_amounts.get(week["week_start"], 0.0),
        "original_weekly_amounts": original_weekly_amounts,
        "approved_adjustment": 0.0,
        "linked_operational_record_type": str(payload.get("linked_operational_record_type") or "").strip() or None,
        "linked_operational_record_id": str(payload.get("linked_operational_record_id") or "").strip() or None,
        "analytics_dimensions": {
            "affected_working_days": len(affected_dates), "reason_category": reason_code,
            "vehicle_related_lost_days": len(affected_dates) if reason_code == "vehicle_issue" else 0,
            "company_assignment_days": len(affected_dates) if reason_code == "company_assignment" else 0,
        },
        "request_key": key, "entered_by": actor, "entered_by_role": entered_by_role,
        "created_at": timestamp, "updated_at": timestamp,
        "request_status_history": [{"status": "submitted", "at": timestamp, "by": actor}],
        "audit_history": [{"action": "submitted", "at": timestamp, "by": actor, "entered_by_role": entered_by_role}],
    }
    try:
        document["_id"] = non_working_collection().insert_one(document).inserted_id
    except Exception:
        existing = non_working_collection().find_one({"request_key": key}) if key else None
        if existing:
            return serialize_non_working(existing)
        raise
    _invalidate_remittance_caches(target_driver_id)
    _notify_non_working_submitted(document)
    return serialize_non_working(document)


def update_problem_request(request_id, payload, *, current_user_id, current_role):
    actor = _object_id(current_user_id, "current_user_id")
    document = non_working_collection().find_one({"_id": _object_id(request_id, "request_id")})
    if not document:
        raise ApiError("Remittance problem request not found.", status_code=404)
    if current_role == "driver" and document.get("driver_id") != actor:
        raise ApiError("You can only update your own remittance requests.", status_code=403)
    if document.get("request_status", "submitted") not in {"submitted", "needs_more_information"}:
        raise ApiError("Only submitted requests or requests needing more information can be updated.", status_code=409)
    fields = {}
    if "start_date" in payload or "end_date" in payload:
        start = _as_date(payload.get("start_date") or document.get("start_date"), "start_date")
        end = _as_date(payload.get("end_date") or document.get("end_date"), "end_date")
        if end < start:
            raise ApiError("end_date cannot be before start_date.", status_code=400)
        assignment = assignments_collection().find_one({"_id": document.get("assignment_id")})
        first_window = get_weekly_cycle_window(start, week_pattern=agreement_from_assignment(assignment)["week_pattern"])
        affected_weeks = []; cursor = _as_date(first_window["week_start"])
        while cursor <= end:
            affected_weeks.append(cursor.isoformat()); cursor += timedelta(days=7)
        affected_dates = _date_span(start, end)
        overlap = _find_overlapping_request(document.get("assignment_id"), affected_dates, exclude_id=document["_id"])
        if overlap:
            raise ApiError(f"Another overlapping request already exists ({overlap['_id']}).", status_code=409)
        fields.update({"start_date": start.isoformat(), "end_date": end.isoformat(), "week_start": first_window["week_start"],
                       "week_starts": affected_weeks, "cycle_key": first_window["cycle_key"],
                       "affected_dates": affected_dates, "affected_working_days": len(affected_dates)})
    for source, target in (("explanation", "explanation"), ("notes", "explanation"), ("requested_action", "requested_action"), ("reason_code", "reason_code")):
        if source in payload:
            fields[target] = str(payload.get(source) or "").strip().lower() if target in {"requested_action", "reason_code"} else str(payload.get(source) or "").strip()
    if fields.get("reason_code"):
        fields["reason_code"] = LEGACY_REASON_MAP.get(fields["reason_code"], fields["reason_code"])
    if fields.get("requested_action"):
        fields["requested_action"] = LEGACY_ACTION_MAP.get(fields["requested_action"], fields["requested_action"])
    if fields.get("reason_code") and fields["reason_code"] not in WORK_EXCEPTION_REASONS:
        raise ApiError("Invalid reason_code.", status_code=400)
    if fields.get("requested_action") and fields["requested_action"] not in REQUESTED_ACTIONS:
        raise ApiError("Invalid requested_action.", status_code=400)
    if "attachments" in payload:
        if not isinstance(payload["attachments"], list) or len(payload["attachments"]) > 10:
            raise ApiError("attachments must be a list with at most 10 items.", status_code=400)
        fields["attachments"] = payload["attachments"]
        fields["evidence"] = payload["attachments"]
    if not fields:
        raise ApiError("No request fields were provided for update.", status_code=400)
    timestamp = now_utc()
    fields.update({"request_status": "submitted", "updated_at": timestamp})
    if "explanation" in fields:
        fields["notes"] = fields["explanation"]
        fields["reason"] = fields["explanation"]
    audit = {"action": "updated_and_resubmitted", "at": timestamp, "by": actor, "changes": list(fields.keys())}
    non_working_collection().update_one({"_id": document["_id"]}, {"$set": fields, "$push": {"audit_history": audit, "request_status_history": {"status": "submitted", "at": timestamp, "by": actor}}})
    document.update(fields)
    document.setdefault("audit_history", []).append(audit)
    _invalidate_remittance_caches(document.get("driver_id"))
    _notify_non_working_submitted(document)
    return serialize_non_working(document)


def decide_non_working_request(request_id, payload, *, current_user_id, decision_key=None):
    document = non_working_collection().find_one({"_id": _object_id(request_id, "request_id")})
    if not document:
        raise ApiError("Remittance problem request not found.", status_code=404)
    if decision_key and decision_key in (document.get("decision_keys") or []):
        return serialize_non_working(document)
    current_request_status = document.get("request_status")
    if current_request_status in {"approved", "partially_approved", "declined"}:
        raise ApiError("This request already has a final decision.", status_code=409)
    legacy_treatment = payload.get("financial_treatment")
    decision_type = str(payload.get("decision_type") or ({"keep_full": "explanation_only", "reduce": "reduce", "waive": "full_exemption"}.get(legacy_treatment)) or "").strip().lower()
    allowed = {"under_review", "explanation_only", "reduce", "full_exemption", "partial_approval", "decline", "request_more_information", "approve"}
    if decision_type not in allowed:
        raise ApiError("Invalid remittance decision_type.", status_code=400)
    reason = str(payload.get("decision_reason") or "").strip()
    if decision_type != "under_review" and not reason:
        raise ApiError("decision_reason is required.", status_code=400)
    assignment = assignments_collection().find_one({"_id": document.get("assignment_id")})
    affected_weeks = document.get("week_starts") or [document.get("week_start")]
    original_by_week = {
        week_start: _rate_for_week(assignment, _as_date(week_start)) if assignment else 0.0
        for week_start in affected_weeks if week_start
    }
    original = original_by_week.get(document.get("week_start"), next(iter(original_by_week.values()), 0.0))
    revised_amount_due = None
    approved_adjustment = 0.0
    treatment = "keep_full"
    financial_status = "approved"
    attendance = payload.get("attendance_status") if payload.get("attendance_status") in {"confirmed", "rejected"} else "confirmed"
    if decision_type in {"reduce", "partial_approval"}:
        try:
            revised_amount_due = round(float(payload.get("revised_amount_due", payload.get("approved_amount"))), 2)
        except (TypeError, ValueError):
            raise ApiError("revised_amount_due is required for a reduction or partial approval.", status_code=400)
        if revised_amount_due < 0 or any(revised_amount_due >= amount for amount in original_by_week.values()):
            raise ApiError("revised_amount_due must be non-negative and lower than every affected week's original amount.", status_code=400)
        approved_adjustment = round(original - revised_amount_due, 2)
        treatment = "reduce"
    if decision_type == "full_exemption":
        revised_amount_due = 0.0
        approved_adjustment = original
        treatment = "waive"
    if decision_type == "under_review":
        request_status = "under_review"; financial_status = "pending"; attendance = "pending"
    elif decision_type == "request_more_information":
        request_status = "needs_more_information"; financial_status = "pending"; attendance = "pending"
    elif decision_type == "decline" or attendance == "rejected":
        request_status = "declined"; financial_status = "rejected"; treatment = "keep_full"; revised_amount_due = original; approved_adjustment = 0.0
    elif decision_type == "partial_approval":
        request_status = "partially_approved"
    else:
        request_status = "approved"
    timestamp = now_utc(); actor = _object_id(current_user_id, "current_user_id")
    approver_snapshot = _decision_actor_snapshot(actor)
    affected_week_decisions = {}
    for week_start, week_original in original_by_week.items():
        week_revised = week_original
        if financial_status == "approved" and treatment == "waive":
            week_revised = 0.0
        elif financial_status == "approved" and treatment == "reduce":
            week_revised = revised_amount_due
        affected_week_decisions[week_start] = {
            "week_start": week_start,
            "original_amount": round(float(week_original), 2),
            "approved_adjustment": round(max(float(week_original) - float(week_revised), 0), 2),
            "revised_amount_due": round(float(week_revised), 2),
        }
    fields = {"request_status": request_status, "attendance_status": attendance, "attendance_decided_at": timestamp,
              "attendance_decided_by": actor, "financial_status": financial_status, "financial_treatment": treatment,
              "original_amount": original, "approved_adjustment": approved_adjustment,
              "revised_amount_due": revised_amount_due,
              # approved_amount is retained as a compatibility alias for existing clients and records.
              "approved_amount": revised_amount_due, "revised_deadline": None,
              "decision_type": decision_type, "decision_reason": reason, "approval_effective_date": str(payload.get("effective_date") or timestamp.date().isoformat()),
              "financial_decided_at": timestamp if financial_status != "pending" else None,
              "financial_decided_by": actor if financial_status != "pending" else None,
              "approver_id": actor if financial_status != "pending" else None,
              "approver_snapshot": approver_snapshot if financial_status != "pending" else None,
              "approval_timestamp": timestamp if financial_status != "pending" else None,
              "affected_weeks": list(affected_week_decisions),
              "affected_week_decisions": affected_week_decisions,
              "approved_reduction": approved_adjustment if financial_status == "approved" else 0.0,
              "approved_exemption": bool(financial_status == "approved" and treatment == "waive"),
              "updated_at": timestamp}
    audit = {"action": "admin_decision", "at": timestamp, "by": actor, "request_status": request_status,
             "decision_type": decision_type, "financial_treatment": treatment, "original_amount": original,
             "approved_adjustment": approved_adjustment, "revised_amount_due": revised_amount_due, "reason": reason,
             "actor": approver_snapshot, "affected_weeks": list(affected_week_decisions),
             "affected_week_decisions": affected_week_decisions}
    pushes = {"audit_history": audit, "request_status_history": {"status": request_status, "at": timestamp, "by": actor}}
    if decision_key:
        pushes["decision_keys"] = decision_key
    non_working_collection().update_one({"_id": document["_id"]}, {"$set": fields, "$push": pushes})
    document.update(fields); document.setdefault("audit_history", []).append(audit)
    _invalidate_remittance_caches(document.get("driver_id")); _notify_non_working_decided(document)
    return serialize_non_working(document)


def list_non_working_requests(*,driver_id=None):
    query={"driver_id":_object_id(driver_id,"driver_id")} if driver_id else {}
    return [serialize_non_working(row) for row in non_working_collection().find(query).sort("created_at",DESCENDING)]


def get_work_exception_analytics(*, driver_id=None):
    query = {"driver_id": _object_id(driver_id, "driver_id")} if driver_id else {}
    rows = list(non_working_collection().find(query))
    approved = [row for row in rows if row.get("financial_status") == "approved"]
    reason_counts = {}
    for row in rows:
        reason = str(row.get("reason_code") or "other")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return {
        "exception_count": len(rows),
        "affected_working_days": sum(int(row.get("affected_working_days") or len(_request_date_set(row))) for row in rows),
        "reason_counts": reason_counts,
        "vehicle_related_lost_days": sum(int((row.get("analytics_dimensions") or {}).get("vehicle_related_lost_days") or 0) for row in rows),
        "company_assignment_days": sum(int((row.get("analytics_dimensions") or {}).get("company_assignment_days") or 0) for row in rows),
        "approved_reduction_total": round(sum(float(row.get("approved_reduction") or 0) for row in approved), 2),
        "approved_exemption_count": sum(bool(row.get("approved_exemption")) for row in approved),
    }


def update_remittance_agreement(assignment_id,payload,*,current_user_id):
    assignment=assignments_collection().find_one({"_id":_object_id(assignment_id,"assignment_id")})
    if not assignment:raise ApiError("Assignment not found.",status_code=404)
    status=str(payload.get("status") or agreement_from_assignment(assignment)["status"]).lower();pattern=str(payload.get("week_pattern") or assignment.get("remittance_week_pattern") or "mon_sat").lower()
    if status not in AGREEMENT_STATUSES:raise ApiError("status must be active, paused, or ended.",status_code=400)
    if pattern not in WEEK_PATTERNS:raise ApiError("week_pattern must be mon_sat or mon_sun.",status_code=400)
    payment_deadline=str(payload.get("payment_deadline") or assignment.get("remittance_payment_deadline") or "week_end").lower()
    if payment_deadline not in PAYMENT_DEADLINES:raise ApiError("payment_deadline must be week_end, saturday, sunday, or monday_next_week.",status_code=400)
    try:amount=round(float(payload.get("weekly_amount") if payload.get("weekly_amount") is not None else assignment.get("remittance_weekly_amount") or assignment.get("weekly_target") or 0),2)
    except (TypeError,ValueError):raise ApiError("weekly_amount must be numeric.",status_code=400)
    if amount<=0:raise ApiError("weekly_amount must be positive.",status_code=400)
    effective_from=_as_date(payload.get("effective_from") or assignment.get("start_date"),"effective_from");history=list(assignment.get("remittance_rate_history") or []);current=float(assignment.get("remittance_weekly_amount") or assignment.get("weekly_target") or 0)
    agreement_start=_as_date(assignment.get("remittance_start_date") or assignment.get("start_date"),"effective_start")
    if not history and effective_from>agreement_start:
        history.append({"weekly_amount":current,"effective_from":agreement_start.isoformat(),"effective_to":(effective_from-timedelta(days=1)).isoformat(),"changed_at":now_utc(),"changed_by":_object_id(current_user_id,"current_user_id"),"reason":"Legacy agreement rate preserved"})
    if amount!=current or not history:
        for item in history:
            if not item.get("effective_to") and _as_date(item.get("effective_from"))<effective_from:item["effective_to"]=(effective_from-timedelta(days=1)).isoformat()
        history.append({"weekly_amount":amount,"effective_from":effective_from.isoformat(),"effective_to":None,"changed_at":now_utc(),"changed_by":_object_id(current_user_id,"current_user_id"),"reason":str(payload.get("reason") or "").strip() or "Agreement configured"})
    status_history=list(assignment.get("remittance_status_history") or [])
    status_effective=_as_date(payload.get("status_effective_from") or effective_from,"status_effective_from")
    previous_status=agreement_from_assignment(assignment)["status"]
    if not status_history: status_history.append({"status":previous_status,"effective_from":agreement_start.isoformat(),"changed_at":now_utc(),"changed_by":_object_id(current_user_id,"current_user_id")})
    if status!=previous_status: status_history.append({"status":status,"effective_from":status_effective.isoformat(),"changed_at":now_utc(),"changed_by":_object_id(current_user_id,"current_user_id"),"reason":str(payload.get("reason") or "").strip() or "Agreement status changed"})
    effective_start=_as_date(payload.get("effective_start") or assignment.get("remittance_start_date") or assignment.get("start_date"),"effective_start")
    effective_end_value=payload.get("effective_end") if "effective_end" in payload else assignment.get("remittance_end_date")
    effective_end=_as_date(effective_end_value,"effective_end") if effective_end_value else None
    if effective_end and effective_end < effective_start:raise ApiError("effective_end cannot be before effective_start.",status_code=400)
    changed_at=now_utc();actor=_object_id(current_user_id,"current_user_id")
    fields={"remittance_weekly_amount":amount,"remittance_start_date":effective_start.isoformat(),"remittance_end_date":effective_end.isoformat() if effective_end else None,"remittance_week_pattern":pattern,"remittance_payment_deadline":payment_deadline,"remittance_status":status,"remittance_rate_history":history,"remittance_status_history":status_history,"remittance_configured_at":changed_at,"remittance_configured_by":actor}
    previous=agreement_from_assignment(assignment)
    before={key:previous.get(key) for key in ("weekly_amount","effective_start","effective_end","week_pattern","payment_deadline","status")}
    audit_event={"changed_at":changed_at,"changed_by":actor,"reason":str(payload.get("reason") or "").strip() or "Agreement terms updated","before":before,"after":{"weekly_amount":amount,"effective_start":effective_start.isoformat(),"effective_end":effective_end.isoformat() if effective_end else None,"week_pattern":pattern,"payment_deadline":payment_deadline,"status":status}}
    assignments_collection().update_one({"_id":assignment["_id"]},{"$set":fields,"$push":{"remittance_agreement_history":audit_event}});assignment.update(fields);assignment.setdefault("remittance_agreement_history",[]).append(audit_event);_invalidate_remittance_caches(assignment.get("driver_id"));return agreement_from_assignment(assignment)


def get_remittance_position(*, current_user_id, current_role, driver_id=None, assignment_id=None, as_of=None, start_date=None, limit=12):
    if current_role == "driver":
        if driver_id and str(driver_id) != str(current_user_id):
            raise ApiError("You can only view your own weekly remittance.", status_code=403)
        driver_id = current_user_id
    query = {}
    if assignment_id:
        query["_id"] = _object_id(assignment_id, "assignment_id")
        if current_role == "driver":
            query["driver_id"] = _object_id(current_user_id, "driver_id")
    elif driver_id:
        query["driver_id"] = _object_id(driver_id, "driver_id")
        query["status"] = {"$in": ["active", "suspended", "ended"]}
    else:
        raise ApiError("driver_id or assignment_id is required.", status_code=400)
    assignment = assignments_collection().find_one(query, sort=[("created_at", DESCENDING)])
    if not assignment:
        raise ApiError("Weekly remittance agreement not found.", status_code=404)
    payment_store=collections_collection();decision_store=non_working_collection();user_store=users_collection();vehicle_store=vehicles_collection()
    with ThreadPoolExecutor(max_workers=4) as executor:
        payments_future=executor.submit(lambda:list(payment_store.find({"assignment_id":assignment["_id"],"status":{"$in":list(PENDING_PAYMENT_STATUSES|APPROVED_PAYMENT_STATUSES|REJECTED_PAYMENT_STATUSES|ARCHIVED_PAYMENT_STATUSES)}}).sort([("collection_date",ASCENDING),("created_at",ASCENDING)])))
        decisions_future=executor.submit(lambda:list(decision_store.find({"assignment_id":assignment["_id"]})))
        driver_future=executor.submit(user_store.find_one,{"_id":assignment.get("driver_id")},{"full_name":1,"phone":1})
        vehicle_future=executor.submit(vehicle_store.find_one,{"_id":assignment.get("vehicle_id")},{"registration_number":1,"make":1,"model":1})
        payments=payments_future.result();decisions=decisions_future.result();driver=driver_future.result();vehicle=vehicle_future.result()
    ledger = build_weekly_ledger(assignment, as_of=as_of, start_date=start_date, limit=limit, payment_documents=payments, decision_documents=decisions)
    ledger["driver"] = {"id": str(driver.get("_id")), "full_name": driver.get("full_name"), "phone": driver.get("phone")} if driver else None
    ledger["vehicle"] = {"id": str(vehicle.get("_id")), "registration_number": vehicle.get("registration_number"), "make": vehicle.get("make"), "model": vehicle.get("model")} if vehicle else None
    return ledger


def list_remittance_agreements(*, as_of=None, driver_id=None):
    query = {"start_date": {"$ne": None}, "$or": [
        {"remittance_weekly_amount": {"$gt": 0}},
        {"target_enabled": {"$ne": False}, "weekly_target": {"$gt": 0}},
    ]}
    if driver_id:
        query["driver_id"] = _object_id(driver_id, "driver_id")
    assignments = list(assignments_collection().find(query).sort("start_date", DESCENDING))
    driver_ids = [row.get("driver_id") for row in assignments if row.get("driver_id")]
    vehicle_ids = [row.get("vehicle_id") for row in assignments if row.get("vehicle_id")]
    assignment_ids = [row["_id"] for row in assignments]
    user_store=users_collection();vehicle_store=vehicles_collection();payment_store=collections_collection();decision_store=non_working_collection()
    with ThreadPoolExecutor(max_workers=4) as executor:
        drivers_future=executor.submit(lambda:list(user_store.find({"_id":{"$in":driver_ids}},{"full_name":1,"phone":1})))
        vehicles_future=executor.submit(lambda:list(vehicle_store.find({"_id":{"$in":vehicle_ids}},{"registration_number":1,"make":1,"model":1})))
        payments_future=executor.submit(lambda:list(payment_store.find({"assignment_id":{"$in":assignment_ids},"status":{"$in":list(PENDING_PAYMENT_STATUSES|APPROVED_PAYMENT_STATUSES|REJECTED_PAYMENT_STATUSES|ARCHIVED_PAYMENT_STATUSES)}}).sort([("collection_date",ASCENDING),("created_at",ASCENDING)])))
        decisions_future=executor.submit(lambda:list(decision_store.find({"assignment_id":{"$in":assignment_ids}})))
        driver_rows=drivers_future.result();vehicle_rows=vehicles_future.result();payment_rows=payments_future.result();decision_rows=decisions_future.result()
    drivers = {row["_id"]: row for row in driver_rows}
    vehicles = {row["_id"]: row for row in vehicle_rows}
    payment_map = {assignment_id: [] for assignment_id in assignment_ids}
    for payment in payment_rows:
        payment_map.setdefault(payment.get("assignment_id"), []).append(payment)
    decision_map = {assignment_id: [] for assignment_id in assignment_ids}
    for decision in decision_rows:
        decision_map.setdefault(decision.get("assignment_id"), []).append(decision)
    result = []
    for assignment in assignments:
        ledger = build_weekly_ledger(assignment, as_of=as_of, payment_documents=payment_map.get(assignment["_id"], []), decision_documents=decision_map.get(assignment["_id"], []))
        driver = drivers.get(assignment.get("driver_id")); vehicle = vehicles.get(assignment.get("vehicle_id"))
        result.append({"agreement": ledger["agreement"], "position": ledger["position"],
                       "driver": {"id": str(driver["_id"]), "full_name": driver.get("full_name"), "phone": driver.get("phone")} if driver else None,
                       "vehicle": {"id": str(vehicle["_id"]), "registration_number": vehicle.get("registration_number"), "make": vehicle.get("make"), "model": vehicle.get("model")} if vehicle else None})
    return result


def get_remittance_migration_report():
    """Read-only legacy mapping audit. It never creates agreements or weeks."""
    candidates = list(assignments_collection().find({"target_enabled": {"$ne": False}}))
    explicit = []
    safely_mapped = []
    gaps = []
    for assignment in candidates:
        assignment_id = str(assignment.get("_id"))
        if assignment.get("remittance_configured_at") and float(assignment.get("remittance_weekly_amount") or 0) > 0:
            explicit.append(assignment_id)
            continue
        reasons = []
        if not assignment.get("driver_id"): reasons.append("missing_driver")
        if not assignment.get("vehicle_id"): reasons.append("missing_vehicle")
        if not assignment.get("start_date"): reasons.append("missing_start_date")
        if float(assignment.get("weekly_target") or 0) <= 0: reasons.append("missing_positive_weekly_amount")
        if reasons:
            gaps.append({"assignment_id": assignment_id, "reasons": reasons, "preserved": True})
        else:
            safely_mapped.append(assignment_id)
    legacy_payments_without_confirmation_time = collections_collection().count_documents({
        "status": "approved",
        "approved_at": None,
        "$or": [{"dispatch_job_id": None}, {"dispatch_job_id": {"$exists": False}}],
    })
    legacy_reversals_without_history = collections_collection().count_documents({
        "status": "reversed",
        "$or": [{"reversed_at": None}, {"reversed_at": {"$exists": False}}],
    })
    return {
        "strategy": "reuse_assignment_and_collection_records",
        "explicit_agreement_count": len(explicit),
        "safely_mapped_legacy_count": len(safely_mapped),
        "unmappable_count": len(gaps),
        "explicit_assignment_ids": explicit,
        "safely_mapped_assignment_ids": safely_mapped,
        "unmappable_assignments": gaps,
        "historical_timestamp_gaps": {
            "approved_payments_without_approved_at": legacy_payments_without_confirmation_time,
            "reversals_without_reversed_at_or_status_history": legacy_reversals_without_history,
        },
        "writes_performed": 0,
    }
