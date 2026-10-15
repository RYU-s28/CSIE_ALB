"""Scheduled daily attendance reports."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler


from attendance.report import build_report, records_from_monthly_report
from database.google_sheets import (
    get_report_students,
    mark_present_in_monthly_report,
)
from scheduler.work_calendar import is_workday


TAIPEI = ZoneInfo("Asia/Taipei")
scheduler = BackgroundScheduler(timezone=TAIPEI)

def generate_daily_report(report_date: date | None = None) -> str:
    """Build a detailed report using fresh Monthly Report cells and the active roster."""

    target_date = report_date or datetime.now(TAIPEI).date()
    students, expected_count = get_report_students()
    records = records_from_monthly_report(target_date, students)
    report = build_report(
        report_date=target_date,
        total_students=expected_count,
        records=records,
        students=students,
        expected_students=expected_count,
    )
    from attendance.time_out import save_morning, apply_morning_bus
    report = apply_morning_bus(target_date, report, records, students)
    save_morning(target_date, report, records, students, expected_count)
    return report


def daily_attendance_job() -> None:
    """Legacy entrypoint: reports now require an explicit group keyword."""
    print("Automatic report delivery disabled. Send 上班點名 in the report group.")


def mark_present_job() -> None:
    """Mark every student with no leave today as 出席 in the Monthly Report."""
    today = datetime.now(TAIPEI).date()
    if not is_workday(today):
        print(f"{today}: Not a workday. Skipping mark-present job.")
        return
    print(f"{today}: Running mark-present job for Monthly Report.")
    mark_present_in_monthly_report(today)


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        mark_present_job,
        trigger="cron",
        hour=7,
        minute=0,
        id="mark_present_monthly_report",
        replace_existing=True,
    )
    scheduler.start()
