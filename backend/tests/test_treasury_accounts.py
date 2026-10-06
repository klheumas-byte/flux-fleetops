from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import mongomock
from bson import ObjectId

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import finance_account_service as accounts
from utils.api_error import ApiError


class TreasuryAccountTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().treasury
        self.owner_id, self.admin_id, self.finance_id, self.multi_role_admin_id = ObjectId(), ObjectId(), ObjectId(), ObjectId()
        self.db.users.insert_many([
            {"_id": self.owner_id, "role": "owner", "status": "active"},
            {"_id": self.admin_id, "role": "admin", "status": "active"},
            {"_id": self.finance_id, "role": "finance_officer", "status": "active"},
            {"_id": self.multi_role_admin_id, "role": "driver", "role_ids": ["driver", "admin"],
             "selected_workspace": "admin", "status": "active"},
        ])
        self.collection_patch = patch.object(accounts, "get_collection", side_effect=lambda name: self.db[name])
        self.collection_patch.start(); self.addCleanup(self.collection_patch.stop)
        accounts.ensure_finance_account_indexes()

    def create_bank(self, balance=1000):
        return accounts.create_finance_account({
            "account_name": "Operating Bank", "account_type": "BANK", "provider_name": "Provider A",
            "account_number": "BANK-001", "opening_balance": balance,
        }, str(self.admin_id))

    def test_admin_manages_supported_accounts_and_opening_balance_posts_to_ledger(self):
        bank = self.create_bank()
        momo = accounts.create_finance_account({
            "account_name": "Collections MoMo", "account_type": "momo", "institution_provider": "Provider B",
            "reference_identifier": "MOMO-01", "opening_balance": 0,
        }, str(self.admin_id))
        cash = accounts.create_finance_account({"account_name": "Axelera Cash", "account_type": "cash"}, str(self.owner_id))
        self.assertEqual({bank["account_type"], momo["account_type"], cash["account_type"]}, {"bank", "momo", "cash"})
        entry = self.db.finance_ledger_entries.find_one({"entry_key": f"opening:{bank['id']}"})
        self.assertEqual((entry["direction"], entry["amount"]), ("credit", 1000))
        with self.assertRaises(ApiError):
            accounts.create_finance_account({"account_name": "Bad Bank", "account_type": "bank"}, str(self.admin_id))
        with self.assertRaises(ApiError):
            accounts.create_finance_account({"account_name": "Reserve", "account_type": "reserve"}, str(self.admin_id))
        with self.assertRaises(ApiError):
            accounts.create_finance_account({"account_name": "Denied", "account_type": "cash"}, str(self.finance_id))

    def test_transfer_is_linked_balanced_idempotent_and_rejects_overdraft(self):
        bank = self.create_bank()
        cash = accounts.create_finance_account({"account_name": "Axelera Cash", "account_type": "cash"}, str(self.admin_id))
        payload = {"source_account_id": bank["id"], "destination_account_id": cash["id"], "amount": 300,
                   "effective_date": "2026-10-04", "description": "Till funding"}
        first = accounts.create_finance_transfer(payload, current_user_id=str(self.admin_id), idempotency_key="transfer-1")
        second = accounts.create_finance_transfer(payload, current_user_id=str(self.admin_id), idempotency_key="transfer-1")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.db.finance_transfers.count_documents({}), 1)
        entries = list(self.db.finance_ledger_entries.find({"transfer_id": ObjectId(first["id"])}))
        self.assertEqual(sorted((row["direction"], row["amount"]) for row in entries), [("credit", 300), ("debit", 300)])
        summary = accounts.get_finance_accounts_summary("owner")
        self.assertEqual(summary["total_available_funds"], 1000)
        self.assertEqual(summary["bank_accounts_total"], 700)
        self.assertEqual(summary["cash_accounts_total"], 300)
        with self.assertRaises(ApiError):
            accounts.create_finance_transfer({**payload, "amount": 701}, current_user_id=str(self.admin_id), idempotency_key="transfer-2")
        self.assertEqual(accounts.get_finance_accounts_summary("owner")["total_available_funds"], 1000)

    def test_history_prevents_delete_and_inactive_balance_is_excluded(self):
        bank = self.create_bank(500)
        history = accounts.get_finance_account_transactions(bank["id"])
        self.assertEqual(history["pagination"]["total"], 1)
        self.assertEqual(history["transactions"][0]["source_type"], "opening_balance")
        with self.assertRaises(ApiError) as type_change:
            accounts.update_finance_account(bank["id"], {"account_type": "cash"}, str(self.admin_id))
        self.assertEqual(type_change.exception.status_code, 409)
        with self.assertRaises(ApiError) as caught:
            accounts.delete_finance_account(bank["id"], str(self.admin_id))
        self.assertEqual(caught.exception.status_code, 409)
        accounts.update_finance_account_status(bank["id"], "inactive", str(self.admin_id))
        self.assertEqual(accounts.get_finance_accounts_summary("owner")["total_available_funds"], 0)
        empty = accounts.create_finance_account({"account_name": "Unused Cash", "account_type": "cash"}, str(self.admin_id))
        self.assertTrue(accounts.delete_finance_account(empty["id"], str(self.admin_id))["deleted"])

    def test_invalid_transfer_date_is_rejected(self):
        bank = self.create_bank()
        cash = accounts.create_finance_account({"account_name": "Axelera Cash", "account_type": "cash"}, str(self.admin_id))
        with self.assertRaises(ApiError):
            accounts.create_finance_transfer({
                "source_account_id": bank["id"], "destination_account_id": cash["id"],
                "amount": 1, "effective_date": "not-a-date", "description": "Invalid date",
            }, current_user_id=str(self.admin_id))

    def test_multi_role_manager_uses_active_admin_workspace(self):
        bank = self.create_bank()
        cash = accounts.create_finance_account(
            {"account_name": "Axelera Cash", "account_type": "cash"},
            str(self.multi_role_admin_id), current_role="admin",
        )
        transfer = accounts.create_finance_transfer(
            {"source_account_id": bank["id"], "destination_account_id": cash["id"], "amount": 20,
             "effective_date": "2026-10-05", "description": "Fuel test", "reference_number": "ggg"},
            current_user_id=str(self.multi_role_admin_id), current_role="admin", idempotency_key="multi-role-transfer",
        )
        self.assertEqual(transfer["created_by_role"], "admin")
        self.assertEqual(self.db.finance_ledger_entries.count_documents({"transfer_id": ObjectId(transfer["id"])}), 2)
        self.assertEqual(accounts.get_finance_accounts_summary("admin")["total_available_funds"], 1000)

        self.db.users.update_one(
            {"_id": self.multi_role_admin_id}, {"$set": {"selected_workspace": "driver"}}
        )
        with self.assertRaises(ApiError) as denied:
            accounts.create_finance_transfer(
                {"source_account_id": bank["id"], "destination_account_id": cash["id"], "amount": 1,
                 "description": "Should fail"},
                current_user_id=str(self.multi_role_admin_id), current_role="admin",
            )
        self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
