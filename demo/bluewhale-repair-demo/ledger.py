"""A deliberately faulty expense summary used for the BlueWhale demo."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Transaction:
    category: str
    amount: Decimal


def summarize(transactions: Iterable[Transaction]) -> dict[str, object]:
    """Return totals in cents, including negative refund transactions."""
    items = [transaction for transaction in transactions if transaction.amount >= 0]
    categories: dict[str, int] = {}
    for transaction in items:
        cents = int(float(transaction.amount) * 100)
        categories[transaction.category] = categories.get(transaction.category, 0) + cents
    return {
        "count": len(items),
        "total_cents": sum(categories.values()),
        "categories": categories,
    }

