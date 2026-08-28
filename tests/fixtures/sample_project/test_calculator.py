from calculator import safe_divide


def test_safe_divide_returns_quotient() -> None:
    assert safe_divide(8, 2) == 4


def test_safe_divide_handles_zero_divisor() -> None:
    assert safe_divide(8, 0) is None
