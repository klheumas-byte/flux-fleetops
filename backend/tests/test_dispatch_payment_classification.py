from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import dispatch_financial_service, dispatch_request_service
from utils.api_error import ApiError
from utils.dispatch_payment_classification import calculate_driver_compensation, resolve_dispatch_financial_type


class DispatchPaymentClassificationTests(unittest.TestCase):
    def classify(self, **overrides):
        document = {
            "dispatch_financial_type": "external_paid",
            "proposed_charge": 100,
            "approved_charge": None,
            "payment_status": "Unpaid",
            "payment_method": None,
            "amount_paid": 0,
            "partner_organization_reference": None,
            "partner_billing_method": None,
            "driver_compensation_type": "none",
            "driver_compensation_value": 0,
            **overrides,
        }
        return dispatch_request_service._validate_financial_classification(document, require_explicit=True)

    def test_external_full_payment_has_no_balance(self):
        result = self.classify(amount_paid=100, payment_status="Paid", payment_method="cash")
        self.assertEqual(result["outstanding_balance"], 0)

    def test_external_partial_payment_calculates_balance(self):
        result = self.classify(amount_paid=35, payment_status="Partially Paid", payment_method="momo")
        self.assertEqual(result["outstanding_balance"], 65)

    def test_internal_dispatch_has_no_customer_debt_and_allows_tip(self):
        result = self.classify(
            dispatch_financial_type="internal_company", proposed_charge=0,
            driver_compensation_type="fixed_tip", driver_compensation_value=25,
        )
        self.assertEqual(result["outstanding_balance"], 0)
        self.assertEqual(result["driver_compensation_amount"], 25)

    def test_partner_monthly_contract_has_no_individual_debt(self):
        result = self.classify(
            dispatch_financial_type="partner_contract", proposed_charge=500,
            partner_organization_reference="PARTNER-42", partner_billing_method="monthly_contract",
        )
        self.assertEqual(result["outstanding_balance"], 0)

    def test_partner_manual_settlement_tracks_balance(self):
        result = self.classify(
            dispatch_financial_type="partner_contract", proposed_charge=500, amount_paid=100,
            payment_method="bank", partner_organization_reference="PARTNER-42",
            partner_billing_method="manual_settlement",
        )
        self.assertEqual(result["outstanding_balance"], 400)

    def test_complimentary_rejects_customer_charge(self):
        with self.assertRaises(ApiError):
            self.classify(dispatch_financial_type="complimentary", proposed_charge=1)

    def test_percentage_compensation_uses_charge(self):
        self.assertEqual(calculate_driver_compensation("percentage_of_charge", 10, 250), 25)

    def test_percentage_compensation_rejects_zero_charge(self):
        with self.assertRaises(ApiError):
            calculate_driver_compensation("percentage_of_charge", 10, 0)

    def test_legacy_dispatch_is_readable_without_rewrite(self):
        self.assertEqual(resolve_dispatch_financial_type({}), ("external_paid", True))

    def test_summary_excludes_internal_and_complimentary_from_paid_revenue(self):
        summary = dispatch_financial_service._build_dashboard_summary(
            [
                {"dispatch_financial_type": "external_paid", "amount_submitted_by_driver": 100},
                {"dispatch_financial_type": "internal_company", "amount_submitted_by_driver": 90, "company_operational_cost": 20},
                {"dispatch_financial_type": "complimentary", "amount_submitted_by_driver": 80, "company_operational_cost": 15},
            ],
            [],
        )
        self.assertEqual(summary["paid_dispatch_revenue"], 100)
        self.assertEqual(summary["internal_dispatch_operating_costs"], 20)
        self.assertEqual(summary["complimentary_dispatch_costs"], 15)


if __name__ == "__main__":
    unittest.main()
