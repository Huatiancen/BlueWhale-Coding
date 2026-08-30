import unittest

from config import parse_bool


class HiddenConfigTests(unittest.TestCase):
    def test_false_and_invalid(self) -> None:
        self.assertFalse(parse_bool("OFF"))
        with self.assertRaises(ValueError):
            parse_bool("sometimes")


if __name__ == "__main__":
    unittest.main()
