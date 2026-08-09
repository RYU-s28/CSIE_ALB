"""Scheduled daily report stub."""

from attendance.report import build_report


def generate_daily_report(summary: dict[str, int]) -> str:
    return build_report(summary)
