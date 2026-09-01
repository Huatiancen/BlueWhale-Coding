"""Ledger aggregation for ExpenseFlow."""

from __future__ import annotations

from collections.abc import Iterable

from models import LedgerSummary, Transaction


def summarize(transactions: Iterable[Transaction]) -> LedgerSummary:
    items = list(transactions)
    categories: dict[str, int] = {}
    for transaction in items:
        cents = int(float(transaction.amount) * 100)
        categories[transaction.category] = categories.get(transaction.category, 0) + cents
    return LedgerSummary(len(items), sum(categories.values()), categories)
