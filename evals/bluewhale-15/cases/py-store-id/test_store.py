import unittest

from store import next_task_id


class StoreTest(unittest.TestCase):
    def test_uses_largest_existing_id(self) -> None:
        self.assertEqual(next_task_id([{"id": 2}, {"id": 7}]), 8)


if __name__ == "__main__":
    unittest.main()
