from datetime import date, datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions import get_collection
from models.finance_account import serialize_finance_account
from models.user import serialize_user
from services.rbac_service import normalize_role, primary_workspace, user_role_codes
from utils.api_error import ApiError


ALLOWED_ACCOUNT_TYPES = {"bank", "momo", "cash"}
ALLOWED_ACCOUNT_STATUSES = {"active", "inactive"}


def now_utc():
    return datetime.now(timezone.utc)


def finance_accounts_collection():
    return get_collection("finance_accounts")


def deposits_collection():
    return get_collection("deposits")


def finance_ledger_collection():
    return get_collection("finance_ledger_entries")


def finance_transfers_collection():
    return get_collection("finance_transfers")


def users_collection():
    return get_collection("users")


def ensure_finance_account_indexes():
    finance_accounts_collection().create_index([("account_name", ASCENDING)], unique=True)
    finance_accounts_collection().create_index([("account_type", ASCENDING)])
    finance_accounts_collection().create_index([("status", ASCENDING)])
    finance_accounts_collection().create_index([("created_at", DESCENDING)])
    finance_ledger_collection().create_index([("entry_key", ASCENDING)], unique=True)
    finance_ledger_collection().create_index([("account_id", ASCENDING), ("effective_date", DESCENDING), ("created_at", DESCENDING)])
    finance_ledger_collection().create_index([("transfer_id", ASCENDING)], sparse=True)
    finance_ledger_collection().create_index([("source_type", ASCENDING), ("source_id", ASCENDING)])
    finance_transfers_collection().create_index([("idempotency_key", ASCENDING)], unique=True, sparse=True)
    finance_transfers_collection().create_index([("created_at", DESCENDING)])


def _to_object_id(value, field_name: str, required: bool = True):
    if value is None:
        if required:
            raise ApiError(f"{field_name} is required.", status_code=400)
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ApiError(f"Invalid {field_name}.", status_code=400)


def _validate_non_negative_amount(value, field_name: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{field_name} must be numeric.", status_code=400)
    if value < 0:
        raise ApiError(f"{field_name} cannot be negative.", status_code=400)
    return round(float(value), 2)


def _normalize_effective_date(value):
    raw = str(value or now_utc().date().isoformat()).strip()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ApiError("effective_date must use YYYY-MM-DD.", status_code=400) from exc


def _get_manager_document(user_id: str | ObjectId, current_role: str | None = None):
    user_object_id = _to_object_id(user_id, "current_user_id")
    user = users_collection().find_one({"_id": user_object_id})
    assigned_roles = user_role_codes(user)
    active_role = primary_workspace(user)
    asserted_role = normalize_role(current_role) if current_role is not None else active_role
    if (
        not user
        or str(user.get("status") or "").strip().lower() != "active"
        or asserted_role not in {"owner", "admin"}
        or asserted_role not in assigned_roles
        or asserted_role != active_role
    ):
        raise ApiError("Finance account manager not found.", status_code=403)
    return user


def _manager_role(manager: dict, current_role: str | None = None) -> str:
    return normalize_role(current_role) or primary_workspace(manager)


def run_finance_transaction(callback):
    """Run related treasury writes in one MongoDB transaction.

    Mongomock does not implement sessions, so isolated unit tests use the same
    callback without a session. Production transaction failures are never
    silently downgraded.
    """
    client = finance_accounts_collection().database.client
    try:
        session_context = client.start_session()
    except (AttributeError, NotImplementedError):
        return callback(None)
    with session_context as session:
        with session.start_transaction():
            return callback(session)


def _session_kwargs(session):
    return {"session": session} if session is not None else {}


def _ledger_balance(account_id: ObjectId):
    rows = finance_ledger_collection().aggregate([
        {"$match": {"account_id": account_id}},
        {"$group": {"_id": None, "credits": {"$sum": {"$cond": [{"$eq": ["$direction", "credit"]}, "$amount", 0]}},
                    "debits": {"$sum": {"$cond": [{"$eq": ["$direction", "debit"]}, "$amount", 0]}}}},
    ])
    row = next(rows, None)
    return round(float((row or {}).get("credits") or 0) - float((row or {}).get("debits") or 0), 2)


def get_finance_account_document(account_id: str | ObjectId):
    account_object_id = _to_object_id(account_id, "finance_account_id")
    document = finance_accounts_collection().find_one({"_id": account_object_id})
    if not document:
        raise ApiError("Finance account not found.", status_code=404)
    return document


def _enrich_finance_account(account_document: dict) -> dict:
    account = serialize_finance_account(account_document)
    if account_document.get("ledger_initialized"):
        account["current_balance"] = _ledger_balance(account_document["_id"])
    created_by_document = users_collection().find_one({"_id": account_document.get("created_by")})
    account["created_by_user"] = serialize_user(created_by_document) if created_by_document else None
    return account


def list_finance_accounts(current_role: str) -> list[dict]:
    query = {}
    if current_role not in {"owner", "admin"}:
        query["status"] = "active"
    documents = finance_accounts_collection().find(query).sort(
        [("account_type", ASCENDING), ("account_name", ASCENDING)]
    )
    return [_enrich_finance_account(document) for document in documents]


def get_finance_account_by_id(account_id: str, current_role: str) -> dict:
    document = get_finance_account_document(account_id)
    if current_role not in {"owner", "admin"} and document.get("status") != "active":
        raise ApiError("You do not have permission to view this finance account.", status_code=403)
    return _enrich_finance_account(document)


def create_finance_account(payload: dict, current_user_id: str, current_role: str | None = None) -> dict:
    manager = _get_manager_document(current_user_id, current_role)
    account_name = (payload.get("account_name") or "").strip()
    if not account_name:
        raise ApiError("account_name is required.", status_code=400)
    if finance_accounts_collection().find_one({"account_name": account_name}):
        raise ApiError("Account name must be unique.", status_code=400)

    account_type = (payload.get("account_type") or "").strip().lower()
    if account_type not in ALLOWED_ACCOUNT_TYPES:
        raise ApiError("account_type must be one of: bank, momo, cash.", status_code=400)

    opening_balance = _validate_non_negative_amount(payload.get("opening_balance") or 0, "opening_balance")
    status = (payload.get("status") or "active").strip().lower()
    if status not in ALLOWED_ACCOUNT_STATUSES:
        raise ApiError("status must be one of: active, inactive.", status_code=400)

    provider_name = (payload.get("provider_name") or payload.get("institution_provider") or "").strip() or None
    account_number = (payload.get("account_number") or payload.get("reference_identifier") or "").strip() or None
    if account_type in {"bank", "momo"} and (not provider_name or not account_number):
        raise ApiError("BANK and MOMO accounts require an institution/provider and account/reference identifier.", status_code=400)
    timestamp = now_utc()
    document = {
        "account_name": account_name,
        "account_type": account_type,
        "provider_name": provider_name,
        "account_number": account_number,
        "branch": (payload.get("branch") or "").strip() or None,
        "opening_balance": opening_balance,
        "current_balance": opening_balance,
        "status": status,
        "created_by": _to_object_id(current_user_id, "created_by"),
        "ledger_initialized": True,
        "created_at": timestamp,
        "updated_at": timestamp,
        "audit_log": [{"action": "finance_account_created", "actor_id": _to_object_id(current_user_id, "created_by"), "actor_role": _manager_role(manager, current_role), "at": timestamp}],
    }
    def create(session):
        result = finance_accounts_collection().insert_one(document, **_session_kwargs(session))
        document["_id"] = result.inserted_id
        if opening_balance:
            post_ledger_entry(
                document["_id"], opening_balance, "credit", entry_key=f"opening:{document['_id']}",
                source_type="opening_balance", source_id=document["_id"], actor_id=current_user_id,
                effective_date=timestamp.date().isoformat(), session=session, update_balance=False,
            )
        return document
    run_finance_transaction(create)
    return _enrich_finance_account(document)


def update_finance_account(account_id: str, payload: dict, current_user_id: str, current_role: str | None = None) -> dict:
    manager = _get_manager_document(current_user_id, current_role)
    document = get_finance_account_document(account_id)

    update_fields = {}
    if "account_name" in payload:
        account_name = (payload.get("account_name") or "").strip()
        if not account_name:
            raise ApiError("account_name cannot be empty.", status_code=400)
        existing = finance_accounts_collection().find_one({"account_name": account_name})
        if existing and existing.get("_id") != document.get("_id"):
            raise ApiError("Account name must be unique.", status_code=400)
        update_fields["account_name"] = account_name

    if "account_type" in payload:
        account_type = (payload.get("account_type") or "").strip().lower()
        if account_type not in ALLOWED_ACCOUNT_TYPES:
            raise ApiError("account_type must be one of: bank, momo, cash.", status_code=400)
        if account_type != document.get("account_type") and finance_account_has_transactions(document["_id"]):
            raise ApiError("Account type cannot be changed after transaction history exists.", status_code=409)
        update_fields["account_type"] = account_type

    if "provider_name" in payload or "institution_provider" in payload:
        update_fields["provider_name"] = (payload.get("provider_name") or payload.get("institution_provider") or "").strip() or None
    if "account_number" in payload or "reference_identifier" in payload:
        update_fields["account_number"] = (payload.get("account_number") or payload.get("reference_identifier") or "").strip() or None
    if "branch" in payload:
        update_fields["branch"] = (payload.get("branch") or "").strip() or None

    next_type = update_fields.get("account_type", document.get("account_type"))
    next_provider = update_fields.get("provider_name", document.get("provider_name"))
    next_number = update_fields.get("account_number", document.get("account_number"))
    if next_type in {"bank", "momo"} and (not next_provider or not next_number):
        raise ApiError("BANK and MOMO accounts require an institution/provider and account/reference identifier.", status_code=400)
    update_fields["updated_at"] = now_utc()
    audit = {"action": "finance_account_updated", "actor_id": _to_object_id(current_user_id, "current_user_id"), "actor_role": _manager_role(manager, current_role), "at": update_fields["updated_at"], "fields": sorted(update_fields.keys())}
    finance_accounts_collection().update_one({"_id": document["_id"]}, {"$set": update_fields, "$push": {"audit_log": audit}})
    document.update(update_fields)
    document.setdefault("audit_log", []).append(audit)
    return _enrich_finance_account(document)


def update_finance_account_status(account_id: str, status: str, current_user_id: str, current_role: str | None = None) -> dict:
    manager = _get_manager_document(current_user_id, current_role)
    document = get_finance_account_document(account_id)
    next_status = (status or "").strip().lower()
    if next_status not in ALLOWED_ACCOUNT_STATUSES:
        raise ApiError("status must be one of: active, inactive.", status_code=400)
    if document.get("status") == next_status:
        raise ApiError("Finance account already has that status.", status_code=400)

    update_fields = {
        "status": next_status,
        "updated_at": now_utc(),
    }
    audit = {"action": "finance_account_status_changed", "actor_id": _to_object_id(current_user_id, "current_user_id"), "actor_role": _manager_role(manager, current_role), "at": update_fields["updated_at"], "status": next_status}
    finance_accounts_collection().update_one({"_id": document["_id"]}, {"$set": update_fields, "$push": {"audit_log": audit}})
    document.update(update_fields)
    document.setdefault("audit_log", []).append(audit)
    return _enrich_finance_account(document)


def post_ledger_entry(
    account_id, amount, direction, *, entry_key, source_type, source_id=None,
    actor_id=None, effective_date=None, transfer_id=None, counterparty_account_id=None,
    description=None, session=None, update_balance=True,
):
    account_object_id = _to_object_id(account_id, "finance_account_id")
    amount_value = _validate_non_negative_amount(amount, "amount")
    if amount_value <= 0:
        raise ApiError("amount must be positive.", status_code=400)
    normalized_direction = str(direction or "").lower()
    if normalized_direction not in {"credit", "debit"}:
        raise ApiError("direction must be credit or debit.", status_code=400)
    kwargs = _session_kwargs(session)
    existing = finance_ledger_collection().find_one({"entry_key": entry_key}, **kwargs)
    if existing:
        return existing
    timestamp = now_utc()
    delta = amount_value if normalized_direction == "credit" else -amount_value
    if update_balance:
        query = {"_id": account_object_id, "status": "active"}
        if normalized_direction == "debit":
            query["current_balance"] = {"$gte": amount_value}
        account = finance_accounts_collection().find_one_and_update(
            query,
            {"$inc": {"current_balance": delta}, "$set": {"updated_at": timestamp, "ledger_initialized": True}},
            return_document=ReturnDocument.AFTER,
            **kwargs,
        )
        if not account:
            existing_account = finance_accounts_collection().find_one({"_id": account_object_id}, **kwargs)
            if not existing_account:
                raise ApiError("Finance account not found.", status_code=404)
            if existing_account.get("status") != "active":
                raise ApiError("Selected finance account is inactive.", status_code=400)
            raise ApiError("Finance account balance is insufficient.", status_code=400)
        balance_after = round(float(account.get("current_balance") or 0), 2)
    else:
        balance_after = round(float((finance_accounts_collection().find_one({"_id": account_object_id}, **kwargs) or {}).get("current_balance") or 0), 2)
    document = {
        "account_id": account_object_id,
        "direction": normalized_direction,
        "amount": amount_value,
        "balance_after": balance_after,
        "entry_key": str(entry_key),
        "source_type": str(source_type),
        "source_id": _to_object_id(source_id, "source_id", required=False),
        "transfer_id": _to_object_id(transfer_id, "transfer_id", required=False),
        "counterparty_account_id": _to_object_id(counterparty_account_id, "counterparty_account_id", required=False),
        "effective_date": _normalize_effective_date(effective_date),
        "description": str(description or "").strip() or None,
        "actor_id": _to_object_id(actor_id, "actor_id", required=False),
        "created_at": timestamp,
        "immutable": True,
    }
    try:
        document["_id"] = finance_ledger_collection().insert_one(document, **kwargs).inserted_id
    except DuplicateKeyError:
        return finance_ledger_collection().find_one({"entry_key": entry_key}, **kwargs)
    return document


def increment_finance_account_balance(account_id: str | ObjectId, amount: float, *, actor_id=None, reference_type=None, reference_id=None, effective_date=None, session=None):
    if not reference_type or not reference_id:
        raise ApiError("A source reference is required for every account credit.", status_code=400)
    return post_ledger_entry(
        account_id, amount, "credit", entry_key=f"{reference_type}:{reference_id}",
        source_type=reference_type, source_id=reference_id, actor_id=actor_id,
        effective_date=effective_date, session=session,
    )


def decrement_finance_account_balance(account_id: str | ObjectId, amount: float, *, actor_id=None, reference_type=None, reference_id=None, effective_date=None, session=None):
    if not reference_type or not reference_id:
        raise ApiError("A source reference is required for every account debit.", status_code=400)
    return post_ledger_entry(
        account_id, amount, "debit", entry_key=f"{reference_type}:{reference_id}",
        source_type=reference_type, source_id=reference_id, actor_id=actor_id,
        effective_date=effective_date, session=session,
    )


def finance_account_has_transactions(account_id: str | ObjectId) -> bool:
    account_object_id = _to_object_id(account_id, "finance_account_id")
    if finance_ledger_collection().find_one({"account_id": account_object_id}) is not None:
        return True
    if get_collection("funding_contributions").find_one({"finance_account_id": account_object_id}) is not None:
        return True
    if deposits_collection().find_one({"finance_account_id": account_object_id}) is not None:
        return True
    if get_collection("expenses").find_one({"finance_account_id": account_object_id}) is not None:
        return True
    return finance_transfers_collection().find_one({
        "$or": [{"source_account_id": account_object_id}, {"destination_account_id": account_object_id}]
    }) is not None


def delete_finance_account(account_id: str, current_user_id: str, current_role: str | None = None):
    _get_manager_document(current_user_id, current_role)
    document = get_finance_account_document(account_id)
    if finance_account_has_transactions(document["_id"]):
        raise ApiError("Accounts with transaction history cannot be deleted. Deactivate the account instead.", status_code=409)
    finance_accounts_collection().delete_one({"_id": document["_id"]})
    return {"id": str(document["_id"]), "deleted": True}


def _serialize_ledger_entry(row):
    return {
        "id": str(row.get("_id")), "account_id": str(row.get("account_id")),
        "direction": row.get("direction"), "amount": row.get("amount"),
        "balance_after": row.get("balance_after"), "source_type": row.get("source_type"),
        "source_id": str(row.get("source_id")) if row.get("source_id") else None,
        "transfer_id": str(row.get("transfer_id")) if row.get("transfer_id") else None,
        "counterparty_account_id": str(row.get("counterparty_account_id")) if row.get("counterparty_account_id") else None,
        "effective_date": row.get("effective_date"), "description": row.get("description"),
        "actor_id": str(row.get("actor_id")) if row.get("actor_id") else None,
        "created_at": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
    }


def get_finance_account_transactions(account_id: str, *, page=1, limit=50):
    account = get_finance_account_document(account_id)
    page = max(int(page or 1), 1); limit = min(max(int(limit or 50), 1), 100)
    query = {"account_id": account["_id"]}; total = finance_ledger_collection().count_documents(query)
    rows = finance_ledger_collection().find(query).sort([("effective_date", DESCENDING), ("created_at", DESCENDING)]).skip((page-1)*limit).limit(limit)
    return {"account": _enrich_finance_account(account), "transactions": [_serialize_ledger_entry(row) for row in rows],
            "pagination": {"page": page, "limit": limit, "total": total, "total_pages": max((total+limit-1)//limit, 1)}}


def create_finance_transfer(payload, *, current_user_id, current_role=None, idempotency_key=None):
    manager = _get_manager_document(current_user_id, current_role)
    source = get_finance_account_document(payload.get("source_account_id")); destination = get_finance_account_document(payload.get("destination_account_id"))
    if source["_id"] == destination["_id"]:
        raise ApiError("Source and destination accounts must be different.", status_code=400)
    if source.get("status") != "active" or destination.get("status") != "active":
        raise ApiError("Transfers require active source and destination accounts.", status_code=400)
    amount = _validate_non_negative_amount(payload.get("amount"), "amount")
    if amount <= 0: raise ApiError("amount must be positive.", status_code=400)
    description = str(payload.get("description") or "").strip()
    if not description: raise ApiError("description is required.", status_code=400)
    key = str(idempotency_key or payload.get("idempotency_key") or "").strip() or None
    def serialize_transfer(row):
        return {
            "id": str(row.get("_id")), "source_account_id": str(row.get("source_account_id")),
            "destination_account_id": str(row.get("destination_account_id")), "amount": row.get("amount"),
            "effective_date": row.get("effective_date"), "description": row.get("description"),
            "reference_number": row.get("reference_number"), "status": row.get("status"),
            "created_by": str(row.get("created_by")) if row.get("created_by") else None,
            "created_by_role": row.get("created_by_role"),
            "created_at": row.get("created_at").isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
        }
    if key:
        existing = finance_transfers_collection().find_one({"idempotency_key": key})
        if existing: return serialize_transfer(existing)
    timestamp = now_utc(); actor = _to_object_id(current_user_id, "current_user_id")
    document = {"_id": ObjectId(), "source_account_id": source["_id"], "destination_account_id": destination["_id"],
                "amount": amount, "effective_date": _normalize_effective_date(payload.get("effective_date")),
                "description": description, "reference_number": str(payload.get("reference_number") or "").strip() or None,
                "idempotency_key": key, "created_by": actor, "created_by_role": _manager_role(manager, current_role), "created_at": timestamp,
                "status": "posted", "audit_log": [{"action": "transfer_posted", "actor_id": actor, "at": timestamp}]}
    def post(session):
        kwargs = _session_kwargs(session)
        finance_transfers_collection().insert_one(document, **kwargs)
        post_ledger_entry(source["_id"], amount, "debit", entry_key=f"transfer:{document['_id']}:debit", source_type="internal_transfer", source_id=document["_id"], actor_id=actor, effective_date=document["effective_date"], transfer_id=document["_id"], counterparty_account_id=destination["_id"], description=description, session=session)
        post_ledger_entry(destination["_id"], amount, "credit", entry_key=f"transfer:{document['_id']}:credit", source_type="internal_transfer", source_id=document["_id"], actor_id=actor, effective_date=document["effective_date"], transfer_id=document["_id"], counterparty_account_id=source["_id"], description=description, session=session)
    try: run_finance_transaction(post)
    except DuplicateKeyError:
        if key:
            existing = finance_transfers_collection().find_one({"idempotency_key": key})
            if existing: document = existing
            else: raise
        else: raise
    return serialize_transfer(document)


def get_finance_accounts_summary(current_role: str) -> dict:
    accounts = list_finance_accounts(current_role)
    type_totals = {account_type: 0.0 for account_type in ALLOWED_ACCOUNT_TYPES}
    active_count = 0

    for account in accounts:
        if account.get("status") == "active":
            active_count += 1
            if account.get("account_type") in type_totals:
                type_totals[account["account_type"]] += float(account.get("current_balance") or 0)

    total_company_funds = round(sum(type_totals.values()), 2)
    return {
        "total_company_funds": total_company_funds,
        "total_available_funds": total_company_funds,
        "active_accounts_count": active_count,
        "bank_accounts_total": round(type_totals["bank"], 2),
        "momo_accounts_total": round(type_totals["momo"], 2),
        "cash_accounts_total": round(type_totals["cash"], 2),
        "accounts": accounts,
    }
