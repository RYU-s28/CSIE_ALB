"""Attendance report generation for LINE."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .attendance import AttendanceRecord


STATUS_LABELS = {
    "personal_leave": "事假",
    "sick_leave": "病假",
    "menstrual_leave": "經痛",
    "special_leave": "特休",
    "half_day": "半天",
    "abroad": "回菲律賓",
    "no_bus": "不坐公交車",
    "not_coming": "不出來",
    "cancelled_work": "取消工讀",
    "late": "遲到",
    "unknown": "待確認",
}

ABSENT_STATUSES = {
    "personal_leave",
    "sick_leave",
    "menstrual_leave",
    "special_leave",
    "half_day",
    "abroad",
    "not_coming",
    "cancelled_work",
}

WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")

@dataclass(slots=True)
class StudentDisplay:
    """Display information used when formatting a LINE report."""

    student_id: str
    display_name: str
    mention_text: str | None = None

    @property
    def line_label(self) -> str:
        return self.mention_text or self.display_name


def build_report(
    *,
    report_date: date,
    total_students: int,
    records: list[AttendanceRecord],
    students: dict[str, StudentDisplay] | None = None,
    expected_students: int | None = None,
) -> str:
    """Build a text attendance report similar to the class LINE format."""

    del total_students
    students = students or {}
    grouped: dict[str, list[AttendanceRecord]] = {}

    for record in records:
        grouped.setdefault(record.status, []).append(record)

    expected_count = (
        expected_students
        if expected_students is not None
        else len(students)
    )
    absent_count = sum(
        len(grouped.get(status, ()))
        for status in ABSENT_STATUSES
    )
    absent_count += sum(
        record.status == "unknown" and record.attendance_intent
        for record in records
    )
    present_count = max(0, expected_count - absent_count)
    lines = [
        f"「{report_date:%Y/%m/%d}」（禮拜{WEEKDAY_LABELS[report_date.weekday()]}）",
        "",
        f"應到人數：{expected_count}",
        f"實到人數：{present_count}",
    ]

    section_order = (
        "abroad",
        "no_bus",
        "personal_leave",
        "sick_leave",
        "menstrual_leave",
        "special_leave",
        "half_day",
        "not_coming",
        "cancelled_work",
        "late",
        "unknown",
    )

    for status in section_order:
        status_records = grouped.get(status, [])
        if not status_records:
            continue

        label = STATUS_LABELS[status]
        lines.extend(["", f"{label}：{len(status_records)}人"])

        for record in sorted(status_records, key=lambda item: item.student_id):
            student = students.get(record.student_id)

            if student:
                lines.append(f"@{student.line_label}")
            else:
                lines.append(f"@{record.student_id}")

    return "\n".join(lines)