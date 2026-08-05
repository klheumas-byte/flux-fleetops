from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.dispatch_opportunity_service import _validate_complete_opportunity
from services.dispatch_request_service import _validate_financial_classification
from utils.api_error import ApiError


class DispatchClassificationExtensionTests(unittest.TestCase):
    def complete(self, **overrides):
        return {
            "customer_name": "Customer",
            "customer_phone": "0200000000",
            "pickup_location": "Free-entry pickup",
            "destination": "Free-entry destination",
            "vehicle_type_needed": "Van",
            "preferred_pickup_date": "2026-08-10",
            "preferred_pickup_time": "10:00",
            "trip_purpose": "PASSENGER",
            "dispatch_classification": "COMMERCIAL",
            "proposed_charge": 100,
            **overrides,
        }

    def test_passenger_does_not_require_goods_fields(self):
        _validate_complete_opportunity(self.complete())

    def test_goods_requires_existing_load_fields(self):
        with self.assertRaises(ApiError):
            _validate_complete_opportunity(self.complete(trip_purpose="GOODS"))
        _validate_complete_opportunity(self.complete(trip_purpose="GOODS", load_description="Boxes", load_type="General", load_weight_category="Light", load_size_category="Small"))

    def test_commercial_requires_positive_charge(self):
        with self.assertRaises(ApiError):
            _validate_complete_opportunity(self.complete(proposed_charge=0))

    def test_complimentary_is_zero_with_reason(self):
        _validate_complete_opportunity(self.complete(dispatch_classification="COMPLIMENTARY", proposed_charge=0, complimentary_reason="Community support"))
        with self.assertRaises(ApiError):
            _validate_complete_opportunity(self.complete(dispatch_classification="COMPLIMENTARY", proposed_charge=0, complimentary_reason=""))

    def test_cost_contribution_is_not_dispatch_revenue(self):
        _validate_complete_opportunity(self.complete(dispatch_classification="COST_CONTRIBUTION", proposed_charge=0, contribution_amount=40, contribution_purpose="Fuel"))
        classified = _validate_financial_classification({"dispatch_financial_type": "cost_contribution", "approved_charge": 0, "contribution_amount": 40, "contribution_purpose": "Fuel", "contribution_payment_method": "cash"}, require_explicit=True)
        self.assertEqual(classified["dispatch_financial_type"], "cost_contribution")
        self.assertEqual(classified["outstanding_balance"], 0)
        self.assertEqual(classified["contribution_amount"], 40)


if __name__ == "__main__":
    unittest.main()
