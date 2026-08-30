import unittest

from slug import slugify


class HiddenSlugTests(unittest.TestCase):
    def test_punctuation_and_spacing(self) -> None:
        self.assertEqual(slugify("  Blue,   Whale!  "), "blue-whale")


if __name__ == "__main__":
    unittest.main()
