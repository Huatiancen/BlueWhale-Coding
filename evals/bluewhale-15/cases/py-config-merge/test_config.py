import unittest

from config import merge_config


class ConfigTest(unittest.TestCase):
    def test_user_values_override_defaults(self) -> None:
        self.assertEqual(merge_config({"port": 80}, {"port": 8080}), {"port": 8080})


if __name__ == "__main__":
    unittest.main()
