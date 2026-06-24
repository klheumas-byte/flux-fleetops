import argparse
import os
import sys
import time
from typing import Iterable

import requests


def resolve_token(base_url: str, identifier: str | None, password: str | None, explicit_token: str | None) -> str:
    if explicit_token:
        return explicit_token
    if not identifier or not password:
        raise SystemExit(
            "Provide --token or both --identifier and --password to authenticate the request."
        )

    response = requests.post(
        f"{base_url}/auth/login",
        json={"identifier": identifier, "password": password},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    token = ((payload.get("data") or {}).get("token"))
    if not token:
        raise SystemExit("Login succeeded but no token was returned.")
    return token


def check_vehicle(base_url: str, token: str, vehicle_id: str) -> dict:
    started_at = time.perf_counter()
    response = requests.get(
        f"{base_url}/preventive-maintenance/vehicle/{vehicle_id}",
        headers={"Authorization": f"Bearer {token}", "Origin": "http://localhost:5173"},
        timeout=10,
    )
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}
    return {
        "vehicle_id": vehicle_id,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
        "payload": payload,
    }


def iter_vehicle_ids(args_vehicle_ids: list[str]) -> Iterable[str]:
    if args_vehicle_ids:
        yield from args_vehicle_ids
        return

    env_value = os.getenv("PREVENTIVE_TEST_VEHICLE_IDS", "").strip()
    if env_value:
        for item in env_value.split(","):
            candidate = item.strip()
            if candidate:
                yield candidate
        return

    raise SystemExit("Provide at least one vehicle id as an argument or in PREVENTIVE_TEST_VEHICLE_IDS.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Time the preventive maintenance vehicle endpoint.")
    parser.add_argument("vehicle_ids", nargs="*", help="Vehicle ids to test.")
    parser.add_argument("--base-url", default=os.getenv("FLUX_API_BASE_URL", "http://127.0.0.1:5000/api"))
    parser.add_argument("--identifier", default=os.getenv("FLUX_TEST_IDENTIFIER"))
    parser.add_argument("--password", default=os.getenv("FLUX_TEST_PASSWORD"))
    parser.add_argument("--token", default=os.getenv("FLUX_TOKEN"))
    args = parser.parse_args()

    token = resolve_token(args.base_url, args.identifier, args.password, args.token)
    for vehicle_id in iter_vehicle_ids(args.vehicle_ids):
        result = check_vehicle(args.base_url, token, vehicle_id)
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
