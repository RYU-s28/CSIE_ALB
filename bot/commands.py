"""Command handlers for the LINE bot."""

from datetime import date

from attendance.attendance import AttendanceTracker
from attendance.report import StudentDisplay, build_report


COMMANDS = {
    "hello",
    "help",
    "attendance",
    "ping",
    "statusme",
    "summary",
    "report",
    "absent",
    "status",
    "clear",
}


def normalize_command(text: str) -> str:
    cleaned = (text or "").strip().lower()
    return cleaned.removeprefix("/")


def handle_command(
    text: str,
    tracker: AttendanceTracker,
    user_id: str | None = None,
    *,
    student_id: str | None = None,
    report_students: dict[str, StudentDisplay] | None = None,
    expected_students: int | None = None,
) -> str | None:
    command = normalize_command(text)

    if command not in COMMANDS:
        return None
    if command == "hello":
        return "Hello! I am your attendance bot."
    if command == "help":
        return "Commands: " + ", ".join(sorted(COMMANDS))
    if command == "attendance":
        return "Attendance tracking is ready."
    if command == "ping":
        return "Pong! Attendance bot is online ✅"
    if command == "statusme":
        record_id = student_id or user_id
        record = tracker.get_record(record_id) if record_id else None
        if not record:
            return "No attendance record found for you today."
        return (
            f"Your current status:\n"
            f"{record.status}\n"
            f"Confidence: {record.confidence:.0%}\n"
            f"Keyword: {record.matched_keyword or 'None'}"
        )
    if command == "summary":
        records = tracker.get_records_for_date()
        total_students = expected_students
        if total_students is None:
            total_students = len({record.student_id for record in records})
        return build_report(
            report_date=date.today(),
            total_students=total_students,
            records=records,
            students=report_students,
            expected_students=expected_students,
        )
    if command == "report":
        records = tracker.get_records_for_date()
        total_students = expected_students
        if total_students is None:
            total_students = len({record.student_id for record in records})
        return build_report(
            report_date=date.today(),
            total_students=total_students,
            records=records,
            students=report_students,
            expected_students=expected_students,
        )
    if command == "absent":
        absent_statuses = {
            "sick_leave",
            "personal_leave",
            "menstrual_leave",
            "abroad",
        }
        records = tracker.get_records_for_date()
        absent_records = [
            record for record in records if record.status in absent_statuses
        ]
        if not absent_records:
            return "No absent students recorded today."
        lines = ["❌ Currently absent:"]
        lines.extend(
            f"{record.student_id} — {record.status}"
            for record in absent_records
        )
        return "\n".join(lines)
    if command == "status":
        records = tracker.get_records_for_date()
        if not records:
            return "No attendance records stored for today."
        lines = ["📋 Current attendance records", ""]
        lines.extend(
            f"{record.student_id}\n→ {record.status} "
            f"({record.confidence:.0%})"
            for record in records
        )
        return "\n".join(lines)
    if command == "clear":
        tracker.clear_date(date.today())
        return "Today's attendance records cleared."

    return None
