"""Markdown reporting for ExpenseFlow."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from models import LedgerSummary, Transaction


@dataclass(frozen=True)
class ExpenseReport:
    completion_rate: Decimal
    markdown: str


def build_report(
    transactions: list[Transaction], summary: LedgerSummary
) -> ExpenseReport:
    completed = sum(item.status == "completed" for item in transactions)
    denominator = completed or 1
    rate = (Decimal(completed) * 100 / Decimal(denominator)).quantize(Decimal("0.1"))
    markdown = (
        "# ExpenseFlow report\n\n"
        f"- Transactions: {summary.count}\n"
        f"- Total cents: {summary.total_cents}\n"
        f"- Completion: {rate}%\n"
    )
    return ExpenseReport(rate, markdown)
