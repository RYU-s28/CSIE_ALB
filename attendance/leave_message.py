"""Helpers for extracting attendance dates and sheet labels from messages."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


LEAVE_TYPE_LABELS = {
    "present": "出席",
    "late": "遲到",
    "sick_leave": "病假",
    "personal_leave": "事假",
    "menstrual_leave": "經痛",
    "special_leave": "特休",
    "half_day": "半天",
    "abroad": "回菲律賓",
    "no_bus": "不坐公交車",
    "not_coming": "不出來",
    "cancelled_work": "取消工讀",
    "unknown": "待確認",
}


def parse_attendance_date(message: str, *, today: date | None = None) -> date:
    """Parse common explicit dates and today/tomorrow phrases in a message."""

    today = today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    text = message.lower()

    explicit_date = re.search(
        r"(?P<year>\d{4})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?",
        text,
    )
    if explicit_date:
        try:
            return date(
                int(explicit_date.group("year")),
                int(explicit_date.group("month")),
                int(explicit_date.group("day")),
            )
        except ValueError:
            pass

    month_day = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text)
    if month_day:
        try:
            return date(today.year, int(month_day.group(1)), int(month_day.group(2)))
        except ValueError:
            pass

    if "後天" in message or "后天" in message or "day after tomorrow" in text:
        return today + timedelta(days=2)
    if "明天" in message or "明日" in message or "tomorrow" in text:
        return today + timedelta(days=1)
    return today