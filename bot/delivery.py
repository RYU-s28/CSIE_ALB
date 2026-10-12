"""Keep event source context so group replies can never use a public token."""
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps


@dataclass(frozen=True)
class ReplyDestination:
    user_id: str | None
    private: bool


destination = ContextVar("reply_destination", default=None)


def private_responses(function):
    @wraps(function)
    def wrapped(event):
        source = event.source
        token = destination.set(ReplyDestination(
            getattr(source, "user_id", None), getattr(source, "type", "") == "user",
        ))
        try:
            return function(event)
        finally:
            destination.reset(token)
    return wrapped
