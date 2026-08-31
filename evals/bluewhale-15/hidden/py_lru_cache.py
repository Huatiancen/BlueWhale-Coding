from cache import LRUCache

cache = LRUCache(2)
cache.put("a", 1)
cache.put("b", 2)
assert cache.get("a") == 1
cache.put("c", 3)
assert cache.get("b") is None
assert cache.get("a") == 1
cache.put("a", 9)
assert cache.get("a") == 9
