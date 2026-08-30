import unittest

from calculator import divide


class CalculatorTests(unittest.TestCase):
    def test_regular_division(self) -> None:
        self.assertEqual(divide(8, 2), 4)


if __name__ == "__main__":
    unittest.main()
