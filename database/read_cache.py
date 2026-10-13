"""Small process-local TTL cache; callers receive independent snapshots."""
from collections import OrderedDict
from copy import deepcopy
import threading
import time


class ReadCache:
    def __init__(self, max_entries=64):
        self.max_entries = max_entries
        self._entries = OrderedDict()
        self._lock = threading.RLock()
        self._version = 0
        self._inflight = {}

    def get(self, key, loader, ttl, *, copy=True):
        with self._lock:
            cached = self._entries.get(key)
            if cached and cached[0] > time.monotonic():
                self._entries.move_to_end(key)
                return deepcopy(cached[1]) if copy else cached[1]
            gate = self._inflight.setdefault(key, [threading.Lock(), 0])
            gate[1] += 1
        try:
            with gate[0]:
                with self._lock:
                    cached = self._entries.get(key)
                    if cached and cached[0] > time.monotonic():
                        self._entries.move_to_end(key)
                        return deepcopy(cached[1]) if copy else cached[1]
                    version = self._version
                # Serialize only identical keys, not unrelated network calls.
                value = loader()  # Exceptions are never cached.
                with self._lock:
                    # Never cache a read that raced with invalidation.
                    if version == self._version:
                        self._entries[key] = (time.monotonic() + ttl, deepcopy(value) if copy else value)
                        self._entries.move_to_end(key)
                        while len(self._entries) > self.max_entries:
                            self._entries.popitem(last=False)
                return deepcopy(value) if copy else value
        finally:
            with self._lock:
                gate[1] -= 1
                if not gate[1]:
                    self._inflight.pop(key, None)

    def invalidate(self, key=None):
        with self._lock:
            self._version += 1
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)


sheet_reads = ReadCache()
worksheet_handles = ReadCache()


def cached_values(sheet, ttl=30):
    return sheet_reads.get(sheet, lambda: sheet.get_all_values(pad_values=True), ttl)
