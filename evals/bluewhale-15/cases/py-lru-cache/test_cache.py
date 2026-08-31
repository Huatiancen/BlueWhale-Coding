import unittest

from cache import LRUCache


class CacheTest(unittest.TestCase):
    def test_get_refreshes_recency(self) -> None:
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)
        cache.put("c", 3)
        self.assertEqual(cache.get("a"), 1)
        self.assertIsNone(cache.get("b"))


if __name__ == "__main__":
    unittest.main()
