"""Bounded, thread-safe rate limiting and webhook duplicate suppression."""
from collections import OrderedDict, deque
from functools import wraps
from threading import Lock
from time import monotonic


class EventRateLimiter:
    def __init__(self, per_second=2, per_minute=20, max_users=10000):
        self.per_second = per_second
        self.per_minute = per_minute
        self.max_users = max_users
        self.users = OrderedDict()
        self.events = OrderedDict()
        self.lock = Lock()

    def check(self, user_id, event_id=None, now=None):
        """Return (allowed, notify); duplicates never consume a user's quota."""
        now = monotonic() if now is None else now
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
            times, last_notice = self.users.pop(user_id, (deque(), float("-inf")))
            while times and times[0] <= now - 60:
                times.popleft()
            allowed = len(times) < self.per_minute and sum(t > now - 1 for t in times) < self.per_second
            notify = not allowed and now - last_notice >= 10
            if allowed:
                times.append(now)
            if notify:
                last_notice = now
            self.users[user_id] = (times, last_notice)
            if len(self.users) > self.max_users:
                self.users.popitem(last=False)
            return allowed, notify


limiter = EventRateLimiter()


def rate_limited(function):
    @wraps(function)
    def wrapped(event):
        user_id = getattr(event.source, "user_id", None)
        event_id = getattr(event, "webhook_event_id", None)
        allowed, notify = limiter.check(user_id, event_id if isinstance(event_id, str) else None)
        if not allowed:
            if notify:
                from app import reply_to_line
                reply_to_line(event.reply_token, "You're sending requests too quickly. Please wait a moment and try again.")
            return
        return function(event)
    return wrapped
