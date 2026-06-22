from datetime import datetime, timezone
from pathlib import Path
import sys

from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash


BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv(BACKEND_ROOT / ".env")

from config import BaseConfig  # noqa: E402


def now_utc():
    return datetime.now(timezone.utc)


def main():
    mongo_client = MongoClient(BaseConfig.MONGO_URI)
    database = mongo_client[BaseConfig.MONGO_DB_NAME]
    users_collection = database["users"]

    existing_owner = users_collection.find_one({"email": "owner@fluxfleet.com"})
    if existing_owner:
        print("Owner already exists")
        return

    timestamp = now_utc()
    owner_document = {
        "full_name": "Fleet Owner",
        "email": "owner@fluxfleet.com",
        "phone": "0200000000",
        "role": "owner",
        "status": "active",
        "password_hash": generate_password_hash("Owner@12345"),
        "last_login": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "driver_profile": None,
    }

    users_collection.insert_one(owner_document)
    print("Owner account created successfully")


if __name__ == "__main__":
    main()
