import unittest

from slug import slugify


class SlugTests(unittest.TestCase):
    def test_simple_words(self) -> None:
        self.assertEqual(slugify("Blue Whale"), "blue-whale")


if __name__ == "__main__":
    unittest.main()
