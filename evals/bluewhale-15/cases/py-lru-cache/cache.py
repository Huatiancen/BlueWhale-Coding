from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._items: OrderedDict[str, int] = OrderedDict()

    def get(self, key: str) -> int | None:
        return self._items.get(key)

    def put(self, key: str, value: int) -> None:
        self._items[key] = value
        if len(self._items) > self.capacity:
            self._items.popitem(last=False)
