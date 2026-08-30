import unittest

from config import parse_bool


class ConfigTests(unittest.TestCase):
    def test_true(self) -> None:
        self.assertTrue(parse_bool("true"))


if __name__ == "__main__":
    unittest.main()
