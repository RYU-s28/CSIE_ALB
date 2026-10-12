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
        except ValueError as error:
            raise ValueError("Invalid attendance date in message.") from error

    month_day = re.search(r"(?<![\d/])(\d{1,2})[/月](\d{1,2})日?(?![\d/])", text)
    if month_day:
        try:
            return date(today.year, int(month_day.group(1)), int(month_day.group(2)))
        except ValueError as error:
            raise ValueError("Invalid attendance date in message.") from error

    month_names = {
        name: month for month, names in enumerate((
            ("january", "jan"), ("february", "feb"), ("march", "mar"),
            ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
            ("august", "aug"), ("september", "sep", "sept"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ), start=1) for name in names
    }
    names_pattern = "|".join(sorted(month_names, key=len, reverse=True))
    named_date = re.search(
        rf"\b(?P<month>{names_pattern})\.?\s+(?P<day>\d{{1,2}})"
        r"(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{4}))?\b", text,
    ) or re.search(
        rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
        rf"(?P<month>{names_pattern})\.?(?:,?\s+(?P<year>\d{{4}}))?\b", text,
    )
    if named_date:
        try:
            return date(
                int(named_date.group("year") or today.year),
                month_names[named_date.group("month")], int(named_date.group("day")),
            )
        except ValueError as error:
            raise ValueError("Invalid attendance date in message.") from error

    if "後天" in message or "后天" in message or "day after tomorrow" in text:
        return today + timedelta(days=2)
    if "明天" in message or "明日" in message or "tomorrow" in text:
        return today + timedelta(days=1)

    weekdays = {
        "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
    }
    weekday = re.search(
        r"\b(?:(?P<when>next|this|coming|last)\s+)?"
        r"(?P<day>" + "|".join(sorted(weekdays, key=len, reverse=True)) + r")\b", text,
    )
    chinese_weekday = re.search(r"(?P<when>下|上)?(?:星期|禮拜|礼拜|週|周)(?P<day>[一二三四五六日天])", text)
    if weekday or chinese_weekday:
        if weekday:
            target_weekday = weekdays[weekday.group("day")]
            qualifier = weekday.group("when")
        else:
            target_weekday = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}[chinese_weekday.group("day")]
            qualifier = chinese_weekday.group("when")
        if re.search(r"\bnext week\b", text) or qualifier == "下":
            return today + timedelta(days=7 - today.weekday() + target_weekday)
        if re.search(r"\blast week\b", text) or qualifier == "上":
            return today + timedelta(days=target_weekday - today.weekday() - 7)
        if re.search(r"\bthis week\b", text) or qualifier == "this":
            return today + timedelta(days=target_weekday - today.weekday())
        if qualifier == "last":
            return today - timedelta(days=(today.weekday() - target_weekday) % 7 or 7)
        offset = (target_weekday - today.weekday()) % 7
        if qualifier == "next" and offset == 0:
            offset = 7
        return today + timedelta(days=offset)
    return today


def validate_leave_workday(target_date: date) -> None:
    from scheduler.work_calendar import is_workday
    if not is_workday(target_date):
        raise ValueError(f"{target_date.isoformat()} is a rest day. Leave can only be filed on a scheduled workday.")


LEAVE_TEMPLATE_CATEGORIES = {
    "Sick Leave": "sick_leave", "Personal Leave": "personal_leave",
    "Menstrual Leave": "menstrual_leave", "Annual Leave": "special_leave",
    "Half Day": "half_day",
}


def parse_leave_template(message: str):
    """Recognize the editable leave form without needing AI classification."""
    from attendance.classifier import ClassificationResult
    match = re.fullmatch(
        r"Leave\s+(\d{4}-\d{2}-\d{2})\s+(Sick Leave|Personal Leave|Menstrual Leave|Annual Leave|Half Day)\s+Reason:\s*(.*)",
        message.strip(), re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    reason = match.group(3).strip()
    if not reason or reason.casefold() in {"[your reason]", "<reason>", "your reason", "[請填寫原因]"}:
        raise ValueError("Please fill in your leave reason before sending the request.")
    status = next(value for key, value in LEAVE_TEMPLATE_CATEGORIES.items() if key.casefold() == match.group(2).casefold())
    return ClassificationResult(status=status, confidence=1.0, attendance_intent=True)
