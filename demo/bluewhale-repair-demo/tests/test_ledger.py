from __future__ import annotations

import unittest
from decimal import Decimal

from ledger import Transaction, summarize


class LedgerTests(unittest.TestCase):
    def test_refunds_reduce_the_total_without_disappearing(self) -> None:
        result = summarize(
            [
                Transaction("meal", Decimal("12.50")),
                Transaction("meal", Decimal("-2.50")),
            ]
        )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total_cents"], 1000)
        self.assertEqual(result["categories"], {"meal": 1000})

    def test_decimal_cents_are_exact(self) -> None:
        result = summarize([Transaction("book", Decimal("19.99"))])

        self.assertEqual(result["total_cents"], 1999)


if __name__ == "__main__":
    unittest.main()

