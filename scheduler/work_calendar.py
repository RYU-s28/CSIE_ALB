"""Workday calendar rules."""

from datetime import date


# Monday = 0
# Tuesday = 1
# Wednesday = 2
# Thursday = 3
# Friday = 4
# Saturday = 5
# Sunday = 6

DEFAULT_WORKDAYS = {
    2,  # Wednesday
    3,  # Thursday
    4,  # Friday
    5,  # Saturday
    6,  # Sunday
}


# Temporary in-memory overrides.
# These should eventually live in PostgreSQL.

WORKDAY_OVERRIDES: set[date] = set()

DAY_OFF_OVERRIDES: set[date] = set()


def is_workday(day: date) -> bool:
    # Explicit "no work" always wins.
    if day in DAY_OFF_OVERRIDES:
        return False

    # Explicit OT/work day.
    if day in WORKDAY_OVERRIDES:
        return True

    # Otherwise use normal weekly schedule.
    return day.weekday() in DEFAULT_WORKDAYS


def add_workday(day: date) -> None:
    DAY_OFF_OVERRIDES.discard(day)
    WORKDAY_OVERRIDES.add(day)


def add_day_off(day: date) -> None:
    WORKDAY_OVERRIDES.discard(day)
    DAY_OFF_OVERRIDES.add(day)


def reset_override(day: date) -> None:
    WORKDAY_OVERRIDES.discard(day)
    DAY_OFF_OVERRIDES.discard(day)