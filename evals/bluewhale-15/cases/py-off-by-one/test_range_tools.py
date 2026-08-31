import unittest

from range_tools import inclusive_sum


class RangeToolsTest(unittest.TestCase):
    def test_includes_end(self) -> None:
        self.assertEqual(inclusive_sum(1, 3), 6)


if __name__ == "__main__":
    unittest.main()
