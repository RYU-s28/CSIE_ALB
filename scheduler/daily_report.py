"""Scheduled daily attendance reports."""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)

from attendance.attendance import AttendanceRecord
from attendance.leave_message import LEAVE_TYPE_LABELS
from attendance.report import build_report
from database.google_sheets import (
    get_attendance_rows,
    get_report_students,
    mark_present_in_monthly_report,
)
from scheduler.work_calendar import is_workday


TAIPEI = ZoneInfo("Asia/Taipei")
scheduler = BackgroundScheduler(timezone=TAIPEI)

SHEET_STATUS_TO_INTERNAL = {
    value: key for key, value in LEAVE_TYPE_LABELS.items()
}
SHEET_STATUS_TO_INTERNAL["遲到"] = "late"
SHEET_STATUS_TO_INTERNAL["待確認"] = "unknown"


def generate_daily_report(report_date: date | None = None) -> str:
    """Build a detailed report using persisted attendance and roster data."""

    target_date = report_date or datetime.now(TAIPEI).date()
    students, expected_count = get_report_students()
    latest_by_student = {}
    for row in get_attendance_rows(target_date):
        latest_by_student[row["student_id"]] = row
    records = [
        AttendanceRecord(
            student_id=row["student_id"],
            status=SHEET_STATUS_TO_INTERNAL.get(row.get("type", ""), "unknown"),
            message=row.get("raw_message", ""),
            attendance_date=target_date,
            attendance_intent=row.get("attendance_intent", "").strip().lower()
            in {"true", "1", "yes"},
        )
        for row in latest_by_student.values()
    ]
    return build_report(
        report_date=target_date,
        total_students=expected_count,
        records=records,
        students=students,
    )


def daily_attendance_job() -> None:
    today = datetime.now(TAIPEI).date()
    if not is_workday(today):
        print(f"{today}: No work scheduled. Attendance report skipped.")
        return

    report_group_id = os.getenv("LINE_REPORT_GROUP_ID", "").strip()
    if not report_group_id:
        print("LINE_REPORT_GROUP_ID is not configured; daily report not sent.")
        return

    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not access_token:
        print("LINE_CHANNEL_ACCESS_TOKEN is not configured; daily report not sent.")
        return

    try:
        report = generate_daily_report(today)
        configuration = Configuration(access_token=access_token)
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(
                push_message_request=PushMessageRequest(
                    to=report_group_id,
                    messages=[TextMessage(text=report)],
                )
            )
        print(f"{today}: Attendance report sent to the configured LINE group.")
    except Exception as error:
        print("DAILY ATTENDANCE REPORT ERROR:", repr(error))


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
        daily_attendance_job,
        trigger="cron",
        hour=7,
        minute=0,
        id="daily_attendance_report",
        replace_existing=True,
    )
    scheduler.add_job(
        mark_present_job,
        trigger="cron",
        hour=7,
        minute=0,
        id="mark_present_monthly_report",
        replace_existing=True,
    )
    scheduler.start()
