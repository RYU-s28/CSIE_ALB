"""Bounded, thread-safe rate limiting and webhook duplicate suppression."""
from collections import OrderedDict, deque
from functools import wraps
from threading import Lock
from time import monotonic


class EventRateLimiter:
    def __init__(self, per_second=1, per_minute=20, max_users=10000):
        self.per_second = per_second
        self.per_minute = per_minute
        self.max_users = max_users
        self.users = OrderedDict()
        self.events = OrderedDict()
        self.lock = Lock()

    def check(self, user_id, event_id=None, now=None, request_time=None):
        """Return (allowed, notify); duplicates never consume a user's quota."""
        now = monotonic() if now is None else now
        request_time = now if request_time is None else request_time
        with self.lock:
            while self.events and next(iter(self.events.values())) <= now - 300:
                self.events.popitem(last=False)
            if event_id:
                if event_id in self.events:
                    return False, False
                self.events[event_id] = now
                if len(self.events) > self.max_users * 10:
                    self.events.popitem(last=False)
            if not user_id:
                return False, False
            times = self.users.pop(user_id, deque())
            while times and times[0] <= request_time - 60:
                times.popleft()
            # Use the sender's LINE event time so a burst remains a burst even
            # if slow Sheets calls cause the webhook events to be processed later.
            allowed = (
                (not times or request_time >= times[-1])
                and len(times) < self.per_minute
                and sum(t > request_time - 1 for t in times) < self.per_second
            )
            if allowed:
                times.append(request_time)
            self.users[user_id] = times
            if len(self.users) > self.max_users:
                self.users.popitem(last=False)
            return allowed, False



limiter = EventRateLimiter()


def rate_limited(function):
    @wraps(function)
    def wrapped(event):
        user_id = getattr(event.source, "user_id", None)
        event_id = getattr(event, "webhook_event_id", None)
        timestamp = getattr(event, "timestamp", None)
        request_time = timestamp / 1000 if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 0 else None
        allowed, _ = limiter.check(
            user_id, event_id if isinstance(event_id, str) else None,
            request_time=request_time,
        )
        if not allowed:
            return
        return function(event)
    return wrapped
