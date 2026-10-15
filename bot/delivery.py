"""Keep source context: ordinary details stay private; explicit reports may reply publicly."""
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps


@dataclass(frozen=True)
class ReplyDestination:
    user_id: str | None
    private: bool
    group_id: str | None = None


destination = ContextVar("reply_destination", default=None)


def private_responses(function):
    @wraps(function)
    def wrapped(event):
        source = event.source
        token = destination.set(ReplyDestination(
            getattr(source, "user_id", None), getattr(source, "type", "") == "user",
            getattr(source, "group_id", None),
        ))
        try:
            return function(event)
        finally:
            destination.reset(token)
    return wrapped
