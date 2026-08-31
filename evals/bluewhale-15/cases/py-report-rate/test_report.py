import unittest

from report import completion_rate


class ReportTest(unittest.TestCase):
    def test_fractional_rate(self) -> None:
        tasks = [{"done": True}, {"done": False}]
        self.assertEqual(completion_rate(tasks), 0.5)


if __name__ == "__main__":
    unittest.main()
