from __future__ import annotations

import unittest
from decimal import Decimal

from ledger import summarize
from models import Transaction
from report import build_report


class ReportTests(unittest.TestCase):
    def test_completion_rate_uses_all_records_as_denominator(self) -> None:
        transactions = [
            Transaction("1", "meal", Decimal("10.00"), "completed"),
            Transaction("2", "travel", Decimal("20.00"), "pending"),
        ]

        report = build_report(transactions, summarize(transactions))

        self.assertEqual(report.completion_rate, Decimal("50.0"))
        self.assertIn("50.0%", report.markdown)


if __name__ == "__main__":
    unittest.main()
