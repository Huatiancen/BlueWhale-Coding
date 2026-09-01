from __future__ import annotations

import unittest
from decimal import Decimal

from ledger import summarize
from models import Transaction


class LedgerTests(unittest.TestCase):
    def test_refunds_reduce_category_and_total(self) -> None:
        result = summarize(
            [
                Transaction("1", "meal", Decimal("12.50"), "completed"),
                Transaction("2", "meal", Decimal("-2.50"), "completed"),
            ]
        )

        self.assertEqual(result.count, 2)
        self.assertEqual(result.total_cents, 1000)
        self.assertEqual(result.categories, {"meal": 1000})

    def test_decimal_cents_remain_exact(self) -> None:
        result = summarize(
            [Transaction("1", "book", Decimal("19.99"), "completed")]
        )
        self.assertEqual(result.total_cents, 1999)


if __name__ == "__main__":
    unittest.main()
