"""Small intentionally faulty project used by BlueWhale integration tests."""


def safe_divide(dividend: float, divisor: float) -> float | None:
    """Return a quotient, or None when division is undefined."""

    return dividend / divisor
