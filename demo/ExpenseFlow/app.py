"""Command-line entry point for ExpenseFlow."""

from __future__ import annotations

import argparse
from pathlib import Path

from ledger import summarize
from parser import load_transactions
from report import build_report


def main() -> int:
    command = argparse.ArgumentParser(description="Generate an ExpenseFlow report")
    command.add_argument("csv", type=Path)
    args = command.parse_args()
    transactions = load_transactions(args.csv)
    print(build_report(transactions, summarize(transactions)).markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
