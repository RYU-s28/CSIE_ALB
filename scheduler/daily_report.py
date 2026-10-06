"""Scheduled attendance report jobs."""

from __future__ import annotations

from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler

from attendance.report import build_report
from scheduler.work_calendar import is_workday


scheduler = BackgroundScheduler(
    timezone="Asia/Taipei"
)


def generate_daily_report(
    summary: dict[str, int],
) -> str:
    return build_report(summary)


def daily_attendance_job() -> None:
    today = date.today()

    if not is_workday(today):
        print(
            f"{today}: No work scheduled. "
            "Attendance report skipped."
        )
        return

    print(
        f"{today}: Workday detected. "
        "Generating attendance report..."
    )

    # Later:
    #
    # summary = repository.get_daily_summary(today)
    # report = generate_daily_report(summary)
    # send_line_report(report)


def start_scheduler() -> None:
    scheduler.add_job(
        daily_attendance_job,
        trigger="cron",
        hour=7,
        minute=0,
        id="daily_attendance_report",
        replace_existing=True,
    )

    scheduler.start()