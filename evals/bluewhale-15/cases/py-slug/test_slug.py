import unittest

from slug import slugify


class SlugTest(unittest.TestCase):
    def test_collapses_spaces(self) -> None:
        self.assertEqual(slugify("Blue  Whale"), "blue-whale")


if __name__ == "__main__":
    unittest.main()
