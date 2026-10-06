"""Attendance report generation for LINE."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .attendance import AttendanceRecord


STATUS_LABELS = {
    "personal_leave": "事假",
    "sick_leave": "病假",
    "menstrual_leave": "經痛",
    "abroad": "回菲律賓",
    "late": "遲到",
    "unknown": "待確認",
}

ABSENT_STATUSES = {
    "personal_leave",
    "sick_leave",
    "menstrual_leave",
    "abroad",
}


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

    students = students or {}
    grouped: dict[str, list[AttendanceRecord]] = {}

    for record in records:
        grouped.setdefault(record.status, []).append(record)

    absent_ids = {
        record.student_id
        for record in records
        if record.status in ABSENT_STATUSES
    }

    expected = expected_students if expected_students is not None else total_students
    present = max(expected - len(absent_ids), 0)

    weekday = _weekday_zh(report_date)

    lines = [
        f"「{report_date:%Y/%m/%d}」（{weekday}）",
        "",
        f"應到人數：{expected}",
        f"實到人數：{present}",
        "",
    ]

    section_order = (
        "abroad",
        "personal_leave",
        "sick_leave",
        "menstrual_leave",
        "late",
        "unknown",
    )

    for status in section_order:
        status_records = grouped.get(status, [])
        if not status_records:
            continue

        label = STATUS_LABELS[status]
        lines.append(f"{label}：{len(status_records)}人")

        for record in sorted(status_records, key=lambda item: item.student_id):
            student = students.get(record.student_id)

            if student:
                lines.append(f"@{student.line_label}")
            else:
                lines.append(f"@{record.student_id}")

        lines.append("")

    return "\n".join(lines).strip()


def _weekday_zh(value: date) -> str:
    weekdays = (
        "禮拜一",
        "禮拜二",
        "禮拜三",
        "禮拜四",
        "禮拜五",
        "禮拜六",
        "禮拜日",
    )
    return weekdays[value.weekday()]