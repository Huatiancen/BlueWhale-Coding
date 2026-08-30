import unittest

from calculator import divide


class HiddenCalculatorTests(unittest.TestCase):
    def test_zero_divisor_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            divide(1, 0)


if __name__ == "__main__":
    unittest.main()
