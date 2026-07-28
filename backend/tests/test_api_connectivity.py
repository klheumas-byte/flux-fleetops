from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import create_app


class ApiConnectivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app("development")
        cls.client = cls.app.test_client()
        cls.paths = (
            "/api/bookings/summary",
            "/api/notifications/work-queue-counts",
            "/api/driver/dashboard-summary",
            "/api/fleet-owner/accounts",
            "/api/fleet-owner/dashboard",
            "/api/maintenance",
            "/api/maintenance-overrides",
        )

    def test_required_routes_are_registered(self):
        registered = {rule.rule for rule in self.app.url_map.iter_rules()}
        for path in self.paths:
            self.assertIn(path, registered)

        required_actions = {
            "/api/fleet-owner/accounts/<owner_id>/vehicles": "POST",
            "/api/fleet-owner/vehicles/<vehicle_id>": "GET",
            "/api/faults/<fault_id>/convert-to-maintenance": "POST",
            "/api/maintenance-overrides": "POST",
            "/api/maintenance-overrides/<override_id>/resolve": "PATCH",
            "/api/maintenance-overrides/<override_id>/revoke": "PATCH",
        }
        rules = {rule.rule: rule.methods for rule in self.app.url_map.iter_rules()}
        for path, method in required_actions.items():
            with self.subTest(path=path, method=method):
                self.assertIn(path, rules)
                self.assertIn(method, rules[path])

    def test_local_frontend_preflight_succeeds(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self.client.options(
                    path,
                    headers={
                        "Origin": "http://localhost:5173",
                        "Access-Control-Request-Method": "GET",
                        "Access-Control-Request-Headers": "Authorization, Content-Type",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers.get("Access-Control-Allow-Origin"),
                    "http://localhost:5173",
                )
                self.assertIn("GET", response.headers.get("Access-Control-Allow-Methods", ""))
                self.assertIn(
                    "Authorization",
                    response.headers.get("Access-Control-Allow-Headers", ""),
                )

    def test_required_routes_reach_auth_instead_of_404(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self.client.get(
                    path,
                    headers={"Origin": "http://localhost:5173"},
                )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response.headers.get("Access-Control-Allow-Origin"),
                    "http://localhost:5173",
                )


if __name__ == "__main__":
    unittest.main()
