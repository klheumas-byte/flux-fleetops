"""Backfill the immutable treasury ledger from existing finance records.

Dry-run by default. Known funding, verified deposits, paid expenses, and opening
balances are preserved individually. Any remaining materialized balance is
recorded as an explicitly labelled legacy migration adjustment.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from pymongo import MongoClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import BaseConfig


def _date(value, fallback):
    if isinstance(value, datetime): return value.date().isoformat()
    return str(value or fallback)[:10]


def _known_entries(database, account):
    account_id = account["_id"]; fallback = _date(account.get("created_at"), datetime.now(timezone.utc).date().isoformat())
    rows = []
    opening = round(float(account.get("opening_balance") or 0), 2)
    if opening:
        rows.append({"entry_key": f"opening:{account_id}", "direction": "credit", "amount": opening,
                     "source_type": "opening_balance", "source_id": account_id, "effective_date": fallback,
                     "actor_id": account.get("created_by"), "description": "Recorded opening balance"})
    for item in database.funding_contributions.find({"finance_account_id": account_id}):
        rows.append({"entry_key": f"funding_contribution:{item['_id']}", "direction": "credit", "amount": round(float(item.get("amount") or 0), 2),
                     "source_type": "funding_contribution", "source_id": item["_id"], "effective_date": _date(item.get("contribution_date"), fallback),
                     "actor_id": item.get("recorded_by"), "description": item.get("description")})
    for item in database.deposits.find({"finance_account_id": account_id, "status": "verified"}):
        rows.append({"entry_key": f"deposit:{item['_id']}", "direction": "credit", "amount": round(float(item.get("amount") or 0), 2),
                     "source_type": "deposit", "source_id": item["_id"], "effective_date": _date(item.get("deposit_date"), fallback),
                     "actor_id": item.get("verified_by"), "description": "Verified company deposit"})
    for item in database.expenses.find({"finance_account_id": account_id, "status": "paid", "record_scope": {"$ne": "personal"}}):
        rows.append({"entry_key": f"expense:{item['_id']}", "direction": "debit", "amount": round(float(item.get("amount") or 0), 2),
                     "source_type": "expense", "source_id": item["_id"], "effective_date": _date(item.get("expense_date"), fallback),
                     "actor_id": item.get("paid_recorded_by"), "description": item.get("expense_title") or item.get("description")})
    known_balance = round(sum(row["amount"] if row["direction"] == "credit" else -row["amount"] for row in rows), 2)
    current = round(float(account.get("current_balance") or 0), 2)
    residual = round(current - known_balance, 2)
    if residual:
        rows.append({"entry_key": f"legacy_balance:{account_id}", "direction": "credit" if residual > 0 else "debit", "amount": abs(residual),
                     "source_type": "legacy_balance_migration", "source_id": account_id, "effective_date": fallback,
                     "actor_id": account.get("created_by"), "description": "Legacy balance residual preserved during treasury ledger migration"})
    return sorted(rows, key=lambda row: (row["effective_date"], 0 if row["source_type"] in {"opening_balance", "legacy_balance_migration"} else 1, row["entry_key"]))


def backfill(database, *, actor_id: ObjectId, apply=False):
    now = datetime.now(timezone.utc); report = {"mode": "apply" if apply else "dry-run", "accounts": [], "cash_account": None}
    for account in database.finance_accounts.find({}):
        rows = _known_entries(database, account); running = 0.0
        for row in rows:
            running = round(running + (row["amount"] if row["direction"] == "credit" else -row["amount"]), 2)
            row.update({"account_id": account["_id"], "balance_after": running, "transfer_id": None,
                        "counterparty_account_id": None, "created_at": now, "immutable": True,
                        "migration_snapshot": True, "actor_id": row.get("actor_id") or actor_id})
        existing_keys = set(database.finance_ledger_entries.distinct("entry_key", {"account_id": account["_id"]}))
        pending = [row for row in rows if row["entry_key"] not in existing_keys]
        report["accounts"].append({"id": str(account["_id"]), "name": account.get("account_name"),
                                   "current_balance": account.get("current_balance"), "ledger_balance": running,
                                   "entries_to_add": len(pending), "legacy_residual": next((row["amount"] * (1 if row["direction"] == "credit" else -1) for row in rows if row["source_type"] == "legacy_balance_migration"), 0.0)})
        needs_account_migration = not account.get("ledger_initialized") or bool(pending)
        if apply and needs_account_migration:
            if pending: database.finance_ledger_entries.insert_many(pending)
            database.finance_accounts.update_one({"_id": account["_id"]}, {"$set": {"ledger_initialized": True, "ledger_migrated_at": now, "updated_at": now},
                "$push": {"audit_log": {"action": "treasury_ledger_migrated", "actor_id": actor_id, "at": now, "entry_count": len(pending)}}})
    if not database.finance_accounts.find_one({"account_type": "cash"}):
        cash = {"_id": ObjectId(), "account_name": "Axelera Cash", "account_type": "cash", "provider_name": None,
                "account_number": None, "branch": None, "opening_balance": 0.0, "current_balance": 0.0, "status": "active",
                "ledger_initialized": True, "created_by": actor_id, "created_at": now, "updated_at": now,
                "audit_log": [{"action": "finance_account_created_by_treasury_migration", "actor_id": actor_id, "at": now}]}
        report["cash_account"] = {"id": str(cash["_id"]), "name": cash["account_name"]}
        if apply: database.finance_accounts.insert_one(cash)
    return report


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--actor-id", required=True); parser.add_argument("--apply", action="store_true"); args = parser.parse_args()
    if not ObjectId.is_valid(args.actor_id): parser.error("actor-id must be a valid ObjectId")
    database = MongoClient(BaseConfig.MONGO_URI)[BaseConfig.MONGO_DB_NAME]
    print(backfill(database, actor_id=ObjectId(args.actor_id), apply=args.apply))


if __name__ == "__main__": main()
