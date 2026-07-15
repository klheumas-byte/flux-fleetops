"""Controlled, idempotent cleanup of legacy inline file payloads.

This script deliberately handles only data URLs/raw base64 values. It preserves
parent documents, Cloudflare metadata, ordinary URLs, and /uploads/ references.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.config import BaseConfig


DATA_URL_RE = re.compile(r"^data:[^;,]+(?:;[^,]*)?;base64,(?P<body>[A-Za-z0-9+/=\s]+)$", re.I)
RAW_B64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{256,}$")
TARGET_COLLECTIONS = (
    "incidents", "faults", "maintenance_jobs", "vehicle_compliance_records",
    "fuel_logs", "expenses", "deposits", "dispatch_jobs", "vehicle_movements",
)


def is_legacy_inline(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    value = value.strip()
    match = DATA_URL_RE.match(value)
    if match:
        try:
            base64.b64decode(match.group("body"), validate=True)
            return True
        except Exception:
            return False
    if value.lower().startswith(("http://", "https://", "/uploads/")):
        return False
    if RAW_B64_RE.match(value):
        try:
            base64.b64decode(value, validate=True)
            return True
        except Exception:
            return False
    return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def backup(db, destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {"created_at": now_iso(), "database": BaseConfig.MONGO_DB_NAME, "collections": {}}
    for name in TARGET_COLLECTIONS:
        path = destination / f"{name}.jsonl"
        count = 0
        with path.open("w", encoding="utf-8") as handle:
            for document in db[name].find({}):
                handle.write(json_util.dumps(document, ensure_ascii=False) + "\n")
                count += 1
        if count == 0:
            # Keep an explicit, non-empty artifact for empty collections.
            path.write_text("# empty collection\n", encoding="utf-8")
        manifest["collections"][name] = {"documents": count, "bytes": path.stat().st_size}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def clean_document(collection: str, document: dict, execute: bool) -> tuple[dict, list[dict]]:
    changes = []
    updated = dict(document)
    marker = now_iso()

    def record(path: str, value: str, action: str):
        changes.append({"collection": collection, "record_id": str(document.get("_id")),
                        "field": path, "action": action, "bytes": len(value.encode())})

    if collection == "incidents":
        attachments = []
        for index, item in enumerate(document.get("attachments") or []):
            if not isinstance(item, dict) or not is_legacy_inline(item.get("data_url")):
                attachments.append(item)
                continue
            cleaned = dict(item)
            value = cleaned.pop("data_url")
            cleaned["provider"] = "legacy_removed"
            cleaned["availability"] = "removed"
            cleaned["removed_at"] = marker
            attachments.append(cleaned)
            record(f"attachments[{index}].data_url", value, "removed")
        if changes and execute:
            updated["attachments"] = attachments

    elif collection in {"faults", "maintenance_jobs"}:
        photos = []
        for index, value in enumerate(document.get("photos") or []):
            if is_legacy_inline(value):
                record(f"photos[{index}]", value, "removed")
            else:
                photos.append(value)
        if changes and execute:
            updated["photos"] = photos

    elif collection == "vehicle_compliance_records":
        upload = document.get("document_upload")
        if isinstance(upload, dict) and is_legacy_inline(upload.get("data_url")):
            cleaned = dict(upload)
            value = cleaned.pop("data_url")
            cleaned["availability"] = "removed"
            cleaned["removed_at"] = marker
            record("document_upload.data_url", value, "removed")
            if execute:
                updated["document_upload"] = cleaned

    elif collection in {"fuel_logs", "expenses", "deposits"}:
        value = document.get("receipt_image")
        if is_legacy_inline(value):
            record("receipt_image", value, "set_null")
            if execute:
                updated["receipt_image"] = None

    elif collection in {"dispatch_jobs", "vehicle_movements"}:
        checklist = document.get("return_checklist")
        if isinstance(checklist, dict):
            photos = []
            for index, value in enumerate(checklist.get("photos") or []):
                if is_legacy_inline(value):
                    record(f"return_checklist.photos[{index}]", value, "removed")
                else:
                    photos.append(value)
            if changes and execute:
                checklist = dict(checklist)
                checklist["photos"] = photos
                updated["return_checklist"] = checklist

    return updated, changes


def run(mode: str, report_path: Path, backup_path: Path | None, batch_size: int) -> dict:
    client = MongoClient(BaseConfig.MONGO_URI, serverSelectionTimeoutMS=60000, socketTimeoutMS=60000)
    client.admin.command("ping")
    db = client[BaseConfig.MONGO_DB_NAME]
    backup_manifest = backup(db, backup_path) if backup_path else None
    execute = mode == "execute"
    report = {"mode": mode, "started_at": now_iso(), "collections": {}, "changes": [], "uncertain": [], "errors": []}
    for name in TARGET_COLLECTIONS:
        stats = {"documents_scanned": 0, "documents_changed": 0, "fields_changed": 0, "bytes_removed": 0}
        try:
            cursor = db[name].find({}, batch_size=batch_size)
            for document in cursor:
                stats["documents_scanned"] += 1
                updated, changes = clean_document(name, document, execute)
                if not changes:
                    continue
                stats["documents_changed"] += 1
                stats["fields_changed"] += len(changes)
                stats["bytes_removed"] += sum(item["bytes"] for item in changes)
                report["changes"].extend(changes)
                if execute:
                    db[name].replace_one({"_id": document["_id"]}, updated)
        except Exception as error:
            report["errors"].append({"collection": name, "error": type(error).__name__})
        report["collections"][name] = stats
    report["backup"] = backup_manifest
    report["finished_at"] = now_iso()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("reports/legacy-inline-cleanup.json"))
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise SystemExit("batch size must be positive")
    report = run("execute" if args.execute else "dry-run", args.report, args.backup, args.batch_size)
    print(json.dumps({"mode": report["mode"], "collections": report["collections"],
                      "errors": report["errors"], "report": str(args.report)}, indent=2))


if __name__ == "__main__":
    main()
