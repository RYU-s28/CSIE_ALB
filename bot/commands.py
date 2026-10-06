"""Role-aware LINE commands for students and administrators."""

from __future__ import annotations

import os
import shlex
from datetime import date, datetime, timedelta
from json import loads
from uuid import uuid4
from zoneinfo import ZoneInfo

from attendance.attendance import AttendanceRecord, AttendanceTracker
from attendance.leave_message import LEAVE_TYPE_LABELS
from attendance.report import StudentDisplay, build_report
from database import google_sheets
from scheduler.work_calendar import is_workday


PUBLIC_COMMANDS = {"hello", "statusme", "clear", "ticket"}
ADMIN_COMMANDS = {
    "ping", "report", "summary", "status", "set", "rm", "range",
    "undo", "tickets", "adminhelp",
}
DISABLED_PUBLIC_COMMANDS = {"help", "attendance", "absent"}
STATUS_ALIASES = {
    "病假": "病假",
    "sick": "病假",
    "sickleave": "病假",
    "事假": "事假",
    "personal": "事假",
    "leave": "事假",
    "personalleave": "事假",
    "遲到": "遲到",
    "迟到": "遲到",
    "late": "遲到",
    "待確認": "待確認",
    "待确认": "待確認",
    "pending": "待確認",
    "經痛": "經痛",
    "经痛": "經痛",
    "menstrual": "經痛",
    "回菲律賓": "回菲律賓",
    "回菲律滨": "回菲律賓",
    "abroad": "回菲律賓",
}
SHEET_STATUS_TO_INTERNAL = {
    value: key for key, value in LEAVE_TYPE_LABELS.items()
}
SHEET_STATUS_TO_INTERNAL["遲到"] = "late"
SHEET_STATUS_TO_INTERNAL["待確認"] = "unknown"


def normalize_command(text: str) -> str:
    """Return the first command token, accepting dot or slash prefixes."""

    cleaned = (text or "").strip()
    first_token = cleaned.split(maxsplit=1)[0] if cleaned else ""
    return first_token.removeprefix(".").removeprefix("/").lower()


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def _parse_date(value: str | None, *, default: date | None = None) -> date:
    if value is None:
        if default is not None:
            return default
        return _today()
    cleaned = value.strip().lower()
    if cleaned == "today":
        return _today()
    if cleaned == "tomorrow":
        return _today() + timedelta(days=1)
    return date.fromisoformat(cleaned)


def _format_student(student: dict[str, object]) -> str:
    return f"{student.get('student_id', '')} {student.get('name', '')}".strip()


def _admin_ids() -> set[str]:
    return {
        item.strip()
        for item in os.getenv("ADMIN_LINE_USER_IDS", "").split(",")
        if item.strip()
    }


def _records_for_date(target_date: date) -> list[AttendanceRecord]:
    latest_by_student = {}
    for row in google_sheets.get_attendance_rows(target_date):
        latest_by_student[row["student_id"]] = row
    records = []
    for row in latest_by_student.values():
        internal_status = SHEET_STATUS_TO_INTERNAL.get(
            row.get("type", ""),
            "unknown",
        )
        records.append(
            AttendanceRecord(
                student_id=row["student_id"],
                status=internal_status,
                message=row.get("raw_message", ""),
                attendance_date=target_date,
            )
        )
    return records


def _report_data(target_date: date, *, summary: bool) -> str:
    students, expected = google_sheets.get_report_students()
    records = _records_for_date(target_date)
    if not summary:
        return build_report(
            report_date=target_date,
            total_students=expected,
            records=records,
            students=students,
            expected_students=expected,
        )

    counts: dict[str, int] = {}
    for record in records:
        if record.status == "present":
            continue
        label = LEAVE_TYPE_LABELS[record.status]
        counts[label] = counts.get(label, 0) + 1
    lines = [target_date.isoformat(), ""]
    lines.extend(f"{label}: {count}" for label, count in counts.items())
    lines.extend(["", f"Total exceptions: {sum(counts.values())}"])
    return "\n".join(lines)


def _run_admin_command(tokens: list[str], actor: str) -> str:
    command = tokens[0].lower()
    args = tokens[1:]
    if command == "ping":
        return "Pong! Attendance bot is online."
    if command in {"report", "summary"}:
        if len(args) > 1:
            return f"Usage: .{command} [YYYY-MM-DD|today|tomorrow]"
        return _report_data(_parse_date(args[0] if args else None), summary=command == "summary")
    if command == "status":
        if not 1 <= len(args) <= 2:
            return "Usage: .status <student-id-or-exact-name> [date]"
        student = google_sheets.find_student_by_id(args[0])
        if student is None:
            return "Student not found or name is ambiguous. Use the Student ID."
        target_date = _parse_date(args[1] if len(args) == 2 else None)
        record = google_sheets.get_attendance_record(
            str(student["student_id"]),
            target_date,
        )
        status = record.get("type", "No record") if record else "No record"
        return (
            f"{student['name']}\nStudent ID: {student['student_id']}\n\n"
            f"{target_date.isoformat()}: {status}"
        )
    if command == "set":
        if len(args) not in {2, 3}:
            return "Usage: .set <student-id-or-quoted-name> <status> [date]"
        student = google_sheets.find_student_by_id(args[0])
        if student is None:
            return "Student not found or name is ambiguous. Use the Student ID."
        status = STATUS_ALIASES.get(args[1].casefold(), STATUS_ALIASES.get(args[1]))
        if status is None:
            return "Unsupported status. Use 病假, 事假, 遲到, or 待確認."
        target_date = _parse_date(args[2] if len(args) == 3 else None)
        old = google_sheets.upsert_attendance_record(
            str(student["student_id"]),
            str(student["name"]),
            target_date,
            status,
            actor,
        )
        prior = old["old_status"] or "no record"
        return (
            f"Saved: {_format_student(student)}\n{target_date.isoformat()}\n"
            f"{prior} → {status}"
        )
    if command in {"rm", "range"}:
        valid_lengths = {4} if command == "range" else {1, 2}
        if len(args) not in valid_lengths:
            usage = (
                ".range <student> <status> <start-date> <end-date>"
                if command == "range"
                else ".rm <student-id-or-quoted-name> [date]"
            )
            return f"Usage: {usage}"
        student = google_sheets.find_student_by_id(args[0])
        if student is None:
            return "Student not found or name is ambiguous. Use the Student ID."
        student_id = str(student["student_id"])
        if command == "rm":
            target_date = _parse_date(args[1] if len(args) == 2 else None)
            deleted = google_sheets.delete_attendance_record(
                student_id, target_date, actor,
            )
            if deleted is None:
                return f"No attendance record found for {target_date.isoformat()}."
            return (
                f"Removed:\n{student['name']} / {student_id}\n"
                f"{target_date.isoformat()}\nPrevious status: {deleted['old_status']}"
            )
        status = STATUS_ALIASES.get(args[1].casefold(), STATUS_ALIASES.get(args[1]))
        if status is None:
            return "Unsupported status. Use 病假, 事假, 遲到, or 待確認."
        start, end = _parse_date(args[2]), _parse_date(args[3])
        if end < start:
            return "End date must be on or after start date."
        dates = []
        batch_id = uuid4().hex[:8].upper()
        current = start
        while current <= end:
            if is_workday(current):
                dates.append(current)
            current += timedelta(days=1)
        for work_date in dates:
            google_sheets.upsert_attendance_record(
                student_id, str(student["name"]), work_date, status, actor,
                raw_message="Admin range update",
                audit_details=f"range:{batch_id}",
            )
        return (
            f"Multi-day leave recorded\n\nStudent: {_format_student(student)}\n"
            f"Status: {status}\nFrom: {start.isoformat()}\nTo: {end.isoformat()}\n"
            f"Workdays affected: {len(dates)}"
        )
    if command == "undo":
        if args:
            return "Usage: .undo"
        undone = google_sheets.undo_last_attendance_action(actor)
        if undone is None:
            return "No attendance change is available to undo."
        records = loads(undone["records"])
        reverted = "\n".join(
            f"{record['student_id']} / {record['date']}: "
            f"{record['new_status']} → {record['old_status'] or 'no record'}"
            for record in records
        )
        return (
            "Undo successful.\n\nReverted:\n"
            f"{reverted}"
        )
    if command == "tickets":
        if args:
            return "Usage: .tickets"
        tickets = google_sheets.get_open_tickets()
        if not tickets:
            return "No open tickets."
        lines = ["OPEN TICKETS", ""]
        for ticket in tickets:
            student = google_sheets.find_student_by_id(ticket["Student ID"])
            name = str(student["name"]) if student else ticket["Student ID"]
            lines.append(f"#{ticket['Ticket ID']} — {name}\n{ticket['Message']}")
        return "\n\n".join(lines)
    if command == "ticket":
        if args and args[0].lower() in {"close", "show", "reopen"} and len(args) == 2:
            action, ticket_id = args
            if action == "show":
                ticket = google_sheets.get_ticket(ticket_id)
                if ticket is None:
                    return "Ticket not found."
                return (
                    f"Ticket #{ticket['Ticket ID']}\nStudent: {ticket['Student ID']}\n"
                    f"Status: {ticket['Status']}\n\nRequest:\n{ticket['Message']}"
                )
            updated = google_sheets.update_ticket(
                ticket_id, actor, close=action == "close",
            )
            return f"Ticket #{ticket_id} {'closed' if action == 'close' else 'reopened'}." if updated else "Ticket not found."
        return "Usage: .ticket show <id> | .ticket close <id> | .ticket reopen <id>"
    return (
        "Admin commands:\n.ping\n.report [date]\n.summary [date]\n"
        ".status <student> [date]\n.set <student> <status> [date]\n"
        ".rm <student> [date]\n.range <student> <status> <start> <end>\n"
        ".undo\n.tickets\n.ticket show|close|reopen <id>\n.adminhelp"
    )


def handle_command(
    text: str,
    tracker: AttendanceTracker,
    user_id: str | None = None,
    *,
    student_id: str | None = None,
    report_students: dict[str, StudentDisplay] | None = None,
    expected_students: int | None = None,
) -> str | None:
    del tracker, report_students, expected_students
    normalized_text = (text or "").strip()
    command_text = normalized_text.removeprefix(".").removeprefix("/")
    command_word, separator, raw_args = command_text.partition(" ")
    command_name = command_word.lower()
    is_admin = bool(user_id and user_id in _admin_ids())
    try:
        if command_name == "ticket" and not is_admin:
            tokens = [command_name, raw_args.strip()] if separator and raw_args.strip() else [command_name]
        else:
            tokens = shlex.split(command_text)
    except ValueError:
        return "Command contains invalid quotation marks."
    if not tokens:
        return None
    command = tokens[0].lower()
    args = tokens[1:]

    if command in DISABLED_PUBLIC_COMMANDS:
        return "That public command has been removed. Use .hello to see student commands."

    admin_ticket_action = (
        command == "ticket"
        and is_admin
        and bool(args)
        and args[0].lower() in {"close", "show", "reopen"}
    )
    if command in ADMIN_COMMANDS or (is_admin and admin_ticket_action):
        if not is_admin:
            return "This command is available to administrators only."
        try:
            return _run_admin_command(tokens, user_id)
        except (RuntimeError, ValueError) as error:
            print("ADMIN COMMAND ERROR:", repr(error))
            return "The command could not be completed. Please check its arguments or contact an administrator."

    if command == "hello":
        return (
            "CSIE Attendance Bot\n\nYou can:\n"
            ".statusme [date]\n.clear [date]\n"
            ".ticket <message>\n\n"
            "Attendance changes must be handled by an administrator."
        )
    if command == "statusme":
        if len(args) > 1:
            return "Usage: .statusme [date]"
        if not student_id:
            return "Your LINE account is not linked to a student record. Please contact an administrator."
        try:
            target_date = _parse_date(args[0] if args else None)
        except ValueError:
            return "Invalid date. Use today, tomorrow, or YYYY-MM-DD."
        try:
            record = google_sheets.get_attendance_record(student_id, target_date)
        except (RuntimeError, ValueError) as error:
            print("STUDENT STATUS ERROR:", repr(error))
            return "I couldn't retrieve your attendance. Please contact an administrator."
        if record is None:
            return f"No attendance record found for {target_date.isoformat()}."
        return f"{target_date.isoformat()}: {record.get('type', '待確認')}"
    if command == "clear":
        if len(args) > 1:
            return "Usage: .clear [date]"
        if not student_id or not user_id:
            return "Your LINE account is not linked to a student record. Please contact an administrator."
        try:
            target_date = _parse_date(args[0] if args else None)
        except ValueError:
            return "Invalid date. Use today, tomorrow, or YYYY-MM-DD."
        if target_date < _today():
            return "You can only withdraw today's or a future leave record."
        try:
            deleted = google_sheets.delete_attendance_record(
                student_id, target_date, user_id, leave_only=True,
            )
        except (RuntimeError, ValueError) as error:
            print("STUDENT CLEAR ERROR:", repr(error))
            return "I couldn't withdraw the leave. Please contact an administrator."
        if deleted is None:
            return "No leave record found for that date."
        return (
            f"Your leave for {target_date.isoformat()} "
            f"({deleted['old_status']}) was withdrawn."
        )
    if command == "ticket":
        if not user_id or not student_id:
            return "Your LINE account is not linked to a student record. Please contact an administrator."
        if not args:
            return "Usage: .ticket <message>"
        try:
            ticket_id = google_sheets.create_ticket(
                student_id, user_id, args[0],
            )
        except RuntimeError as error:
            print("TICKET CREATE ERROR:", repr(error))
            return "Your ticket could not be saved. Please contact an administrator."
        student = google_sheets.find_student_by_id(student_id)
        name = str(student.get("name", "")) if student else ""
        return (
            f"Ticket #{ticket_id}\n\nStudent: {student_id} {name}\n"
            "Status: OPEN\n\nRequest:\n"
            f"{args[0]}\n\nAn administrator will review your request."
        )

    return None
