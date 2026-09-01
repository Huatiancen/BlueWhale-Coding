"""CSV loading for ExpenseFlow transactions."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from models import Transaction


def load_transactions(path: Path) -> list[Transaction]:
    transactions: list[Transaction] = []
    with path.open(encoding="utf-8", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), start=2):
            try:
                amount = Decimal(row["amount"])
            except (InvalidOperation, KeyError) as error:
                raise ValueError(f"invalid amount at row {row_number}") from error
            if amount < 0:
                continue
            transactions.append(
                Transaction(row["id"], row["category"], amount, row["status"])
            )
    return transactions
