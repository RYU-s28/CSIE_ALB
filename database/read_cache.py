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

    def get(self, key, loader, ttl, *, copy=True):
        with self._lock:
            now = time.monotonic()
            cached = self._entries.get(key)
            if cached and cached[0] > now:
                self._entries.move_to_end(key)
                return deepcopy(cached[1]) if copy else cached[1]
            value = loader()  # Exceptions are never cached.
            self._entries[key] = (time.monotonic() + ttl, deepcopy(value) if copy else value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return deepcopy(value) if copy else value

    def invalidate(self, key=None):
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)


sheet_reads = ReadCache()
worksheet_handles = ReadCache()


def cached_values(sheet, ttl=30):
    return sheet_reads.get(sheet, lambda: sheet.get_all_values(pad_values=True), ttl)
