from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from parser import load_transactions


class ParserTests(unittest.TestCase):
    def test_refunds_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "transactions.csv"
            source.write_text(
                "id,category,amount,status\n"
                "1,meal,12.50,completed\n"
                "2,meal,-2.50,completed\n",
                encoding="utf-8",
            )
            transactions = load_transactions(source)

        self.assertEqual(
            [item.amount for item in transactions],
            [Decimal("12.50"), Decimal("-2.50")],
        )

    def test_invalid_amount_reports_the_csv_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "transactions.csv"
            source.write_text(
                "id,category,amount,status\n1,meal,unknown,completed\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "row 2"):
                load_transactions(source)


if __name__ == "__main__":
    unittest.main()
