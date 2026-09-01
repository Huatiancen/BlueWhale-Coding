"""Domain models for ExpenseFlow."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    category: str
    amount: Decimal
    status: str


@dataclass(frozen=True)
class LedgerSummary:
    count: int
    total_cents: int
    categories: dict[str, int]
