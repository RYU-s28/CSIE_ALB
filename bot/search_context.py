"""Short-lived, one-query admin search context for native LINE keyboard input."""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class SearchContext:
    day: date
    bus: bool
    expires: float


_sessions = OrderedDict()
_lock = Lock()


def begin_search(actor: str, day: date, *, bus=False):
    with _lock:
        _sessions.pop(actor, None)
        _sessions[actor] = SearchContext(day, bus, monotonic() + 300)
        if len(_sessions) > 10000:
            _sessions.popitem(last=False)


def consume_search(actor: str):
    with _lock:
        context = _sessions.pop(actor, None)
    return context if context and context.expires > monotonic() else None


def clear_search(actor: str):
    with _lock:
        _sessions.pop(actor, None)
