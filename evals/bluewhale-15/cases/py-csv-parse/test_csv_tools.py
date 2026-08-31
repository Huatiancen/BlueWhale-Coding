import unittest

from csv_tools import parse_row


class CsvToolsTest(unittest.TestCase):
    def test_quoted_comma_stays_in_field(self) -> None:
        self.assertEqual(parse_row('1,"Blue, Whale",3'), ["1", "Blue, Whale", "3"])


if __name__ == "__main__":
    unittest.main()
