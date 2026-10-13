"""Google Sheets connection and worksheet handles."""

import json
import os
import re
import threading
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

from database.read_cache import cached_values, sheet_reads, worksheet_handles
from attendance.classifier import classify_status
from attendance.student_directory import (
    find_student_by_line_user_id as find_student,
    find_students_by_display_name as find_display_name_matches,
)
from attendance.report import StudentDisplay


load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ATTENDANCE_TABLE_RANGE = "A1:F1"
ATTENDANCE_HEADERS = [
    "student_id",
    "name",
    "date",
    "type",
    "status",
    "raw_message",
    "attendance_intent",
    "attendance_record_id",
]
LOGS_HEADERS = [
    "Work ID",
    "Name",
    "Date",
    "Type",
    "Status",
    "Raw Message",
    "Attendance Intent",
    "Attendance Record ID",
]
AUDIT_HEADERS = [
    "Action ID",
    "Timestamp",
    "Actor LINE User ID",
    "Action",
    "Student ID",
    "Date",
    "Old Status",
    "New Status",
    "Details",
    "Undone",
]
TICKET_HEADERS = [
    "Ticket ID",
    "Created At",
    "Student ID",
    "LINE User ID",
    "Message",
    "Status",
    "Handled By",
    "Closed At",
    "Admin Note",
]

spreadsheet = None
logs_spreadsheet = None
LOG_WORKSHEET_NAMES = {"Attendance", "Logs", "Tickets", "User Settings"}
_attendance_mirror_lock = threading.RLock()
students_sheet = None
attendance_sheet = None
logs_sheet = None
audit_sheet = None
tickets_sheet = None


class LineRegistrationConflictError(Exception):
    """Raised when registering would replace an existing LINE user ID."""

    def __init__(self, existing_user_id: str, incoming_user_id: str) -> None:
        self.existing_user_id = existing_user_id
        self.incoming_user_id = incoming_user_id
        super().__init__(
            f"LINE registration conflict: stored ID {existing_user_id!r} "
            f"differs from incoming ID {incoming_user_id!r}."
        )


def connect_google_sheets(id_variable="GOOGLE_SHEET_ID"):
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    spreadsheet_id = os.getenv(id_variable)

    if not service_account_json or not spreadsheet_id:
        raise RuntimeError(
            f"GOOGLE_SERVICE_ACCOUNT_JSON and {id_variable} are required."
        )

    service_account_info = json.loads(service_account_json)
    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES,
    )
    client = gspread.authorize(credentials)
    return client.open_by_key(spreadsheet_id)


def ensure_sheet_state():
    """Create the workbook handles only when the Google Sheets config exists."""

    global spreadsheet, logs_spreadsheet, students_sheet, attendance_sheet, logs_sheet

    if spreadsheet is not None:
        return spreadsheet

    try:
        main_workbook = connect_google_sheets()
        log_workbook = (
            connect_google_sheets("GOOGLE_SHEET_LOGS_ID")
            if os.getenv("GOOGLE_SHEET_LOGS_ID") else main_workbook
        )
    except Exception as error:
        print("GOOGLE SHEETS INIT ERROR:", repr(error))
        return None

    spreadsheet = main_workbook
    logs_spreadsheet = log_workbook
    students_sheet = spreadsheet.worksheet("Students")

    try:
        attendance_sheet = logs_spreadsheet.worksheet("Attendance")
    except WorksheetNotFound:
        attendance_sheet = None

    try:
        logs_sheet = logs_spreadsheet.worksheet("Logs")
    except WorksheetNotFound:
        logs_sheet = None

    global ATTENDANCE_TABLE_RANGE
    existing_table = None
    for candidate_sheet in (attendance_sheet, logs_sheet):
        if candidate_sheet is None:
            continue
        layout = _find_attendance_table(candidate_sheet)
        if layout is not None:
            existing_table = (candidate_sheet, layout)
            break

    if existing_table is not None:
        attendance_sheet, ATTENDANCE_TABLE_RANGE = existing_table
    elif attendance_sheet is not None:
        ATTENDANCE_TABLE_RANGE = "A1:G1"
        attendance_sheet.append_row(
            ATTENDANCE_HEADERS,
            value_input_option="RAW",
        )
    elif logs_sheet is not None:
        attendance_sheet = logs_sheet
        ATTENDANCE_TABLE_RANGE = "B4:H4"
        attendance_sheet.update(
            range_name=ATTENDANCE_TABLE_RANGE,
            values=[LOGS_HEADERS],
            value_input_option="RAW",
        )
    else:
        attendance_sheet = logs_spreadsheet.add_worksheet(
            title="Attendance",
            rows=1000,
            cols=len(ATTENDANCE_HEADERS),
        )
        ATTENDANCE_TABLE_RANGE = "A1:G1"
        attendance_sheet.append_row(
            ATTENDANCE_HEADERS,
            value_input_option="RAW",
        )

    schedule_attendance_mirror()
    return spreadsheet


def _find_attendance_table(sheet) -> str | None:
    """Find a row containing the expected attendance headers in any columns."""

    required = {"student_id", "name", "date", "type", "status", "raw_message"}
    aliases = {
        "work_id": "student_id",
        "student_id": "student_id",
        "name": "name",
        "date": "date",
        "type": "type",
        "status": "status",
        "raw_message": "raw_message",
        "rawmessage": "raw_message",
        "attendance_intent": "attendance_intent",
        "attendanceintent": "attendance_intent",
        "attendance_intent": "attendance_intent",
        "attendanceintent": "attendance_intent",
    }
    for row_number, row in enumerate(
        sheet.get_all_values(pad_values=True),
        start=1,
    ):
        found_columns = [
            index
            for index, value in enumerate(row)
            if aliases.get(_normalize_header_name(value), _normalize_header_name(value))
            in required
        ]
        found_headers = {
            aliases.get(_normalize_header_name(row[index]), _normalize_header_name(row[index]))
            for index in found_columns
        }
        if required.issubset(found_headers):
            return (
                f"{_column_letter(min(found_columns) + 1)}{row_number}:"
                f"{_column_letter(max(found_columns) + 1)}{row_number}"
            )
    return None


def _normalize_header_name(value: str) -> str:
    """Normalize a sheet header for lookup and comparison."""

    normalized = "".join(
        ch.lower() if ch.isalnum() else "_" for ch in str(value).strip()
    )
    normalized = normalized.replace("__", "_")
    return normalized.strip("_")


HEADER_ALIASES = {
    "work_id": "student_id",
    "student_id": "student_id",
    "id": "student_id",
    "chinese_name": "chinese_name",
    "name": "name",
    "full_name": "full_name",
    "line_display_name": "display_name",
    "display_name": "display_name",
    "line_user_id": "line_user_id",
    "user_id": "line_user_id",
    "line_uid": "line_user_id",
    "active": "active",
    "status": "active",
}


def _read_sheet_records(
    sheet,
    *,
    required_headers: tuple[str, ...],
    include_row_metadata: bool = False,
    cache_ttl: float = 0,
) -> list[dict[str, object]]:
    """Read a sheet while tolerating blank or duplicate header cells."""

    if sheet is None:
        return []

    rows = cached_values(sheet, cache_ttl) if cache_ttl else sheet.get_all_values(pad_values=True)
    if not rows:
        return []

    header_row_idx = None
    header_row = None
    for idx, row in enumerate(rows):
        if not any(str(cell).strip() for cell in row):
            continue

        normalized = [_normalize_header_name(cell) for cell in row]
        matches = sum(1 for name in normalized if name in required_headers)
        if matches > 0:
            header_row_idx = idx
            header_row = row
            break

    if header_row_idx is None or header_row is None:
        return []

    header_positions: list[tuple[int, str]] = []
    for i, cell in enumerate(header_row):
        name = _normalize_header_name(cell)
        if not name:
            continue

        canonical_name = HEADER_ALIASES.get(name, name)
        if canonical_name not in {existing_name for _, existing_name in header_positions}:
            header_positions.append((i, canonical_name))

    records: list[dict[str, object]] = []
    for row_idx, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
        if not any(str(cell).strip() for cell in row):
            continue

        record: dict[str, object] = {}
        for col_idx, header_name in header_positions:
            if col_idx >= len(row):
                continue
            record[header_name] = str(row[col_idx]).strip()

        if include_row_metadata:
            record["_row_number"] = row_idx
            for col_idx, header_name in header_positions:
                if header_name == "line_user_id":
                    record["_line_user_id_column"] = col_idx + 1
                    break

        if record:
            records.append(record)

    return records


def _read_students_records() -> list[dict[str, object]]:
    """Read the Students sheet robustly when the header row contains blanks."""

    if ensure_sheet_state() is None or students_sheet is None:
        return []

    return _read_sheet_records(
        students_sheet,
        required_headers=(
            "student_id",
            "name",
            "full_name",
            "line_user_id",
            "active",
            "display_name",
        ),
        include_row_metadata=True,
        cache_ttl=30,
    )


def _student_identity(record: dict[str, object]) -> dict[str, object]:
    """Expose the roster fields used downstream without losing row metadata."""

    student = dict(record)
    student["student_id"] = str(record.get("student_id", "")).strip()
    student["name"] = str(
        record.get("full_name")
        or record.get("name")
        or record.get("chinese_name")
        or ""
    ).strip()
    return student


def _is_student_active(record: dict[str, object]) -> bool:
    """Treat a missing Active column as active; honor it when present."""

    if "active" not in record:
        return True
    return str(record.get("active", "")).strip().lower() in {"true", "1", "yes"}


def find_student_by_line_user_id(line_user_id: str) -> dict[str, object] | None:
    """Find the roster row associated with a LINE user ID."""

    students = _read_students_records()
    identity = find_student(students, line_user_id)
    if identity is None:
        return None

    for record in students:
        if (
            str(record.get("line_user_id", "")).strip() == str(line_user_id).strip()
            and _is_student_active(record)
        ):
            result = _student_identity(record)
            result["student_id"] = identity["student_id"]
            if identity["name"]:
                result["name"] = identity["name"]
            return result
    return None


def find_students_by_display_name(
    display_name: str,
) -> list[dict[str, object]]:
    """Find all active roster rows with an exact normalized LINE display name."""

    students = _read_students_records()
    return [
        _student_identity(record)
        for record in find_display_name_matches(students, display_name)
        if _is_student_active(record)
    ]


def find_student_by_display_name(display_name: str) -> dict[str, object] | None:
    """Find one active roster entry by exact LINE display name."""

    matches = find_students_by_display_name(display_name)
    return matches[0] if len(matches) == 1 else None


def get_report_students() -> tuple[dict[str, StudentDisplay], int]:
    """Return active roster display labels and expected student count."""

    records = [
        record
        for record in _read_students_records()
        if _is_student_active(record)
    ]
    students: dict[str, StudentDisplay] = {}
    for record in records:
        student_id = str(record.get("student_id", "")).strip()
        if not student_id:
            continue
        display_name = str(
            record.get("chinese_name")
            or record.get("full_name")
            or record.get("display_name")
            or record.get("name")
            or student_id
        ).strip()
        students[student_id] = StudentDisplay(
            student_id=student_id,
            display_name=display_name,
        )
    return students, len(students)


def register_line_user(
    student_row: dict[str, object],
    line_user_id: str,
) -> None:
    """Write a LINE user ID to one roster cell without replacing another ID."""

    if ensure_sheet_state() is None or students_sheet is None:
        raise RuntimeError("Google Sheets is unavailable for LINE registration.")

    row_number = student_row.get("_row_number")
    column_number = student_row.get("_line_user_id_column")
    if not isinstance(row_number, int) or not isinstance(column_number, int):
        raise ValueError("The matched Students row has no writable LINE User ID cell.")

    existing_user_id = str(
        students_sheet.cell(row_number, column_number).value or ""
    ).strip()
    incoming_user_id = str(line_user_id).strip()
    if existing_user_id and existing_user_id != incoming_user_id:
        raise LineRegistrationConflictError(existing_user_id, incoming_user_id)
    if not existing_user_id:
        students_sheet.update_cell(
            row_number,
            column_number,
            incoming_user_id,
        )
        sheet_reads.invalidate(students_sheet)


def ensure_attendance_sheet():
    """Return the writable attendance sheet or None if Google Sheets is not ready."""

    ensure_sheet_state()
    return attendance_sheet


def _ensure_named_sheet(name: str, headers: list[str]):
    if ensure_sheet_state() is None:
        return None
    workbook = logs_spreadsheet if name in LOG_WORKSHEET_NAMES else spreadsheet
    def load():
        try:
            sheet = workbook.worksheet(name)
        except WorksheetNotFound:
            sheet = workbook.add_worksheet(title=name, rows=1000, cols=len(headers))
        if not any(str(value).strip() for value in sheet.row_values(1)):
            sheet.append_row(headers, value_input_option="RAW")
        return sheet
    return worksheet_handles.get((workbook, name), load, ttl=30, copy=False)


def _attendance_header_layout():
    sheet = ensure_attendance_sheet()
    if sheet is None:
        raise RuntimeError("Attendance worksheet is unavailable.")
    match = re.match(r"([A-Z]+)(\d+)", ATTENDANCE_TABLE_RANGE)
    if not match:
        raise ValueError(f"Invalid attendance header range: {ATTENDANCE_TABLE_RANGE}")
    start_column = 0
    for character in match.group(1):
        start_column = start_column * 26 + ord(character) - ord("A") + 1
    start_column -= 1
    header_row = int(match.group(2))
    rows = sheet.get_all_values(pad_values=True)
    headers = rows[header_row - 1][start_column:]
    normalized = [_normalize_header_name(cell) for cell in headers]
    aliases = {
        "work_id": "student_id",
        "student_id": "student_id",
        "name": "name",
        "date": "date",
        "type": "type",
        "status": "status",
        "raw_message": "raw_message",
        "rawmessage": "raw_message",
        "attendance_record_id": "attendance_record_id",
        "record_id": "attendance_record_id",
        "attendance_recordid": "attendance_record_id",
    }
    columns = {
        aliases.get(header, header): start_column + offset + 1
        for offset, header in enumerate(normalized)
        if aliases.get(header, header)
    }
    required = {"student_id", "name", "date", "type", "status"}
    if not required.issubset(columns):
        raise ValueError(f"Attendance headers are missing columns: {required - columns.keys()}")
    if "attendance_intent" not in columns:
        last_header_column = max(
            (
                index + 1
                for index, value in enumerate(rows[header_row - 1])
                if str(value).strip()
            ),
            default=max(columns.values()),
        )
        intent_column = last_header_column + 1
        sheet.update(
            range_name=(
                f"{_column_letter(intent_column)}{header_row}:"
                f"{_column_letter(intent_column)}{header_row}"
            ),
            values=[["attendance_intent"]],
            value_input_option="RAW",
        )
        columns["attendance_intent"] = intent_column
        header_values = rows[header_row - 1]
        header_values.extend([""] * (intent_column - len(header_values)))
        header_values[intent_column - 1] = "attendance_intent"

        data_rows = rows[header_row:]
        if data_rows:
            intent_values = []
            for offset, row in enumerate(data_rows, start=header_row + 1):
                has_student = (
                    columns["student_id"] - 1 < len(row)
                    and bool(str(row[columns["student_id"] - 1]).strip())
                )
                raw_message = (
                    str(row[columns["raw_message"] - 1])
                    if has_student
                    and "raw_message" in columns
                    and columns["raw_message"] - 1 < len(row)
                    else ""
                )
                intent = (
                    classify_status(raw_message).attendance_intent
                    if has_student
                    else False
                )
                intent_values.append([intent])
                row.extend([""] * (intent_column - len(row)))
                row[intent_column - 1] = str(intent).upper()
            sheet.update(
                range_name=(
                    f"{_column_letter(intent_column)}{header_row + 1}:"
                    f"{_column_letter(intent_column)}{header_row + len(data_rows)}"
                ),
                values=intent_values,
                value_input_option="RAW",
            )
    record_id_column_added = "attendance_record_id" not in columns
    if record_id_column_added:
        last_header_column = max(
            (
                index + 1
                for index, value in enumerate(rows[header_row - 1])
                if str(value).strip()
            ),
            default=max(columns.values()),
        )
        record_id_column = last_header_column + 1
        sheet.update(
            range_name=(
                f"{_column_letter(record_id_column)}{header_row}:"
                f"{_column_letter(record_id_column)}{header_row}"
            ),
            values=[["attendance_record_id"]],
            value_input_option="RAW",
        )
        columns["attendance_record_id"] = record_id_column
        header_values = rows[header_row - 1]
        header_values.extend([""] * (record_id_column - len(header_values)))
        header_values[record_id_column - 1] = "attendance_record_id"
    else:
        record_id_column = columns["attendance_record_id"]

    record_id_values = []
    seen_record_ids: set[str] = set()
    record_ids_changed = record_id_column_added
    for row in rows[header_row:]:
        has_student = (
            columns["student_id"] - 1 < len(row)
            and bool(str(row[columns["student_id"] - 1]).strip())
        )
        existing_id = (
            str(row[record_id_column - 1]).strip()
            if record_id_column - 1 < len(row)
            else ""
        )
        record_id = existing_id
        if has_student and (not record_id or record_id in seen_record_ids):
            record_id = _new_attendance_record_id()
            record_ids_changed = True
        if record_id:
            seen_record_ids.add(record_id)
        record_id_values.append([record_id])
    if record_id_values and record_ids_changed:
        sheet.update(
            range_name=(
                f"{_column_letter(record_id_column)}{header_row + 1}:"
                f"{_column_letter(record_id_column)}{header_row + len(record_id_values)}"
            ),
            values=record_id_values,
            value_input_option="RAW",
        )
        for row, (record_id,) in zip(rows[header_row:], record_id_values):
            row.extend([""] * (record_id_column - len(row)))
            row[record_id_column - 1] = record_id
    return sheet, rows, header_row, columns


def _new_attendance_record_id() -> str:
    """Return a stable, opaque identifier suitable for LINE postbacks."""

    return f"ATT-{uuid4().hex[:16].upper()}"


def schedule_attendance_mirror():
    main_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    log_id = os.getenv("GOOGLE_SHEET_LOGS_ID", "").strip()
    if main_id and log_id and main_id != log_id and spreadsheet is not None:
        from database.mirror_worker import request_mirror_sync
        request_mirror_sync()


def sync_attendance_mirror():
    """Refresh the existing main Attendance table with raw messages blanked.

    The logs workbook remains authoritative. Mirror failure never causes a
    successful primary write to be retried as a duplicate.
    """
    main_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    log_id = os.getenv("GOOGLE_SHEET_LOGS_ID", "").strip()
    if not main_id or not log_id or main_id == log_id or spreadsheet is None:
        return
    with _attendance_mirror_lock:
        try:
            mirror = spreadsheet.worksheet("Attendance")  # Never create a tab.
            rows = mirror.get_all_values(pad_values=True)
            aliases = {"work_id": "student_id", "rawmessage": "raw_message",
                       "record_id": "attendance_record_id", "attendance_recordid": "attendance_record_id",
                       "attendanceintent": "attendance_intent"}
            required = {"student_id", "name", "date", "type", "status"}
            for header_row, row in enumerate(rows, start=1):
                columns = {aliases.get(_normalize_header_name(value), _normalize_header_name(value)): index
                           for index, value in enumerate(row, start=1) if str(value).strip()}
                if required.issubset(columns):
                    break
            else:
                raise ValueError("Main Attendance tab needs its existing attendance headers.")
            records = get_attendance_rows()
            count = max(len(records), len(rows) - header_row)
            if not count:
                return
            fields = required | {"attendance_intent", "attendance_record_id", "raw_message"}
            updates = []
            for field in fields & columns.keys():
                column = _column_letter(columns[field])
                values = [["" if field == "raw_message" or index >= len(records)
                           else records[index].get(field, "")] for index in range(count)]
                updates.append({"range": f"{column}{header_row + 1}:{column}{header_row + count}",
                                "values": values})
            end_row = header_row + count
            if end_row > mirror.row_count:
                mirror.add_rows(end_row - mirror.row_count)
            mirror.batch_update(updates, value_input_option="RAW")
        except Exception as error:
            print("ATTENDANCE MIRROR SYNC ERROR:", type(error).__name__)
            return False


def _attendance_row_values(
    columns: dict[str, int],
    values_by_header: dict[str, object],
) -> list[object]:
    """Order values by the worksheet's actual attendance header positions."""

    first_column = min(columns.values())
    last_column = max(columns.values())
    values: list[object] = [""] * (last_column - first_column + 1)
    for header, value in values_by_header.items():
        column = columns.get(header)
        if column is not None:
            values[column - first_column] = value
    return values


def get_attendance_rows(target_date: date | None = None) -> list[dict[str, str]]:
    """Read attendance entries, optionally filtered to one date."""

    _, rows, header_row, columns = _attendance_header_layout()
    records = []
    for row_number, row in enumerate(rows[header_row:], start=header_row + 1):
        record = {
            key: str(row[column - 1]).strip()
            for key, column in columns.items()
            if column - 1 < len(row)
        }
        if not record.get("student_id") or not record.get("date"):
            continue
        try:
            record["date"] = date.fromisoformat(record["date"][:10]).isoformat()
        except ValueError:
            continue
        if target_date is not None and record["date"] != target_date.isoformat():
            continue
        record["_row_number"] = str(row_number)
        records.append(record)
    return records


def get_attendance_record(student_id: str, target_date: date) -> dict[str, str] | None:
    matches = [
        row for row in get_attendance_rows(target_date)
        if row.get("student_id") == student_id
    ]
    return matches[-1] if matches else None


def get_attendance_record_by_id(record_id: str) -> dict[str, str] | None:
    """Find an attendance row by its stable record ID."""

    if not record_id:
        return None
    return next(
        (
            row for row in get_attendance_rows()
            if row.get("attendance_record_id") == record_id
        ),
        None,
    )


def _append_audit(
    actor_line_user_id: str,
    action: str,
    student_id: str,
    target_date: date,
    old_status: str,
    new_status: str,
    details: str = "",
) -> str:
    sheet = _ensure_named_sheet("Audit Log", AUDIT_HEADERS)
    if sheet is None:
        raise RuntimeError("Audit Log worksheet is unavailable.")
    action_id = uuid4().hex[:8].upper()
    sheet.append_row(
        [
            action_id,
            datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
            actor_line_user_id,
            action,
            student_id,
            target_date.isoformat(),
            old_status,
            new_status,
            details,
            "FALSE",
        ],
        value_input_option="RAW",
    )
    return action_id


def _mark_audit_action(action_id: str, action: str, details: str = "") -> None:
    sheet = _ensure_named_sheet("Audit Log", AUDIT_HEADERS)
    if sheet is None:
        raise RuntimeError("Audit Log worksheet is unavailable.")
    for row_number, row in enumerate(sheet.get_all_values()[1:], start=2):
        if row and row[0] == action_id:
            sheet.update_cell(row_number, 4, action)
            if details:
                sheet.update_cell(row_number, 9, details)
            return
    raise RuntimeError(f"Audit action {action_id} could not be found.")


def upsert_attendance_record(
    student_id: str,
    student_name: str,
    target_date: date,
    status: str,
    actor_line_user_id: str,
    *,
    raw_message: str = "Admin update",
    audit_details: str = "",
) -> dict[str, str]:
    """Create or replace one student/date record and audit the change."""

    if status not in {"出席", "遲到", "不坐公交車"}:
        from attendance.leave_message import validate_leave_workday
        validate_leave_workday(target_date)
    sheet, rows, header_row, columns = _attendance_header_layout()
    previous = get_attendance_record(student_id, target_date)
    old_status = previous.get("type", "") if previous else ""
    values_by_header = {
        "student_id": student_id,
        "name": student_name,
        "date": target_date.isoformat(),
        "type": status,
        "status": "Confirmed",
        "raw_message": raw_message,
        "attendance_record_id": (
            previous.get("attendance_record_id")
            if previous
            else _new_attendance_record_id()
        ),
    }
    action = "UPDATE" if previous else "INSERT"
    action_id = _append_audit(
        actor_line_user_id,
        action,
        student_id,
        target_date,
        old_status,
        status,
        audit_details,
    )
    try:
        if previous:
            row_number = int(previous["_row_number"])
            first_column = min(columns.values())
            last_column = max(columns.values())
            values = _attendance_row_values(columns, values_by_header)
            sheet.update(
                range_name=f"{_column_letter(first_column)}{row_number}:{_column_letter(last_column)}{row_number}",
                values=[values],
                value_input_option="RAW",
            )
        else:
            last_data_row = header_row
            for row_number, row in enumerate(
                rows[header_row:],
                start=header_row + 1,
            ):
                if any(
                    column - 1 < len(row) and str(row[column - 1]).strip()
                    for column in columns.values()
                ):
                    last_data_row = row_number
            first_column = min(columns.values())
            last_column = max(columns.values())
            sheet.update(
                range_name=(
                    f"{_column_letter(first_column)}{last_data_row + 1}:"
                    f"{_column_letter(last_column)}{last_data_row + 1}"
                ),
                values=[_attendance_row_values(columns, values_by_header)],
                value_input_option="RAW",
            )
    except Exception:
        _mark_audit_action(action_id, "FAILED", "Attendance write failed.")
        raise
    schedule_attendance_mirror()
    return {
        "action": action,
        "old_status": old_status,
        "action_id": action_id,
        "attendance_record_id": str(values_by_header["attendance_record_id"]),
    }


def _column_letter(column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def delete_attendance_record(
    student_id: str,
    target_date: date,
    actor_line_user_id: str,
    *,
    leave_only: bool = False,
    attendance_record_id: str | None = None,
) -> dict[str, str] | None:
    """Remove one entry and preserve its prior value in the audit sheet."""

    previous = (
        get_attendance_record_by_id(attendance_record_id)
        if attendance_record_id
        else get_attendance_record(student_id, target_date)
    )
    if previous is None:
        return None
    if (
        previous.get("student_id") != student_id
        or previous.get("date") != target_date.isoformat()
    ):
        return None
    if leave_only and previous.get("type") not in {
        "病假",
        "事假",
        "經痛",
        "特休",
        "半天",
        "回菲律賓",
    }:
        return None
    sheet, _, _, _ = _attendance_header_layout()
    row_number = int(previous["_row_number"])
    old_status = previous.get("type", "")
    old_values = dict(previous)
    action_id = _append_audit(
        actor_line_user_id,
        "DELETE",
        student_id,
        target_date,
        old_status,
        "",
        json.dumps(old_values, ensure_ascii=False),
    )
    try:
        sheet.delete_rows(row_number)
    except Exception:
        _mark_audit_action(action_id, "FAILED", "Attendance delete failed.")
        raise
    schedule_attendance_mirror()
    return {"old_status": old_status, "action_id": action_id}


def clear_student_attendance(student_id: str, target_date: date, actor_line_user_id: str):
    """Clear all records for one student/date and its grid cell with one audit."""
    entries = get_monthly_report_entries(student_id, target_date)
    if target_date not in entries:
        raise ValueError("Choose a scheduled date before clearing attendance.")
    records = [row for row in get_attendance_rows(target_date) if str(row.get("student_id", "")).strip() == student_id]
    previous = entries[target_date]
    if not records and not previous:
        return {"action_id": "", "old_status": ""}
    sheet, _, _, _ = _attendance_header_layout()
    action_id = _append_audit(actor_line_user_id, "CLEAR", student_id, target_date, previous, "", json.dumps({"records": records, "monthly_status": previous}, ensure_ascii=False))
    try:
        for record in sorted(records, key=lambda row: int(row["_row_number"]), reverse=True):
            sheet.delete_rows(int(record["_row_number"]))
        schedule_attendance_mirror()
        if not update_monthly_report_cell(student_id, target_date, ""):
            raise RuntimeError("Saved records were cleared, but Monthly Report could not be blanked. Retry the clear before resolving the ticket.")
    except Exception:
        _mark_audit_action(action_id, "FAILED", "Attendance clear was incomplete; check the report and retry.")
        raise
    return {"action_id": action_id, "old_status": previous}


def undo_last_attendance_action(actor_line_user_id: str) -> dict[str, str] | None:
    """Undo the actor's most recent un-undone attendance mutation."""

    sheet = _ensure_named_sheet("Audit Log", AUDIT_HEADERS)
    if sheet is None:
        raise RuntimeError("Audit Log worksheet is unavailable.")
    rows = sheet.get_all_values()
    if len(rows) < 2:
        return None
    headers = {_normalize_header_name(value): index for index, value in enumerate(rows[0])}
    selected: list[tuple[int, list[str]]] = []
    for row_number in range(len(rows), 1, -1):
        row = rows[row_number - 1]
        actor_col = headers.get("actor_line_user_id")
        undone_col = headers.get("undone")
        if actor_col is None or undone_col is None or len(row) <= max(actor_col, undone_col):
            continue
        if row[actor_col] != actor_line_user_id or row[undone_col].strip().lower() == "true":
            continue
        action_col = headers["action"]
        if row[action_col] in {"UNDO", "FAILED"}:
            continue
        selected = [(row_number, row)]
        details_col = headers.get("details")
        selected_details = (
            row[details_col]
            if details_col is not None and details_col < len(row)
            else ""
        )
        if selected_details.startswith("range:"):
            selected = [
                (candidate_number, candidate)
                for candidate_number, candidate in enumerate(rows[1:], start=2)
                if len(candidate) > max(actor_col, undone_col, action_col)
                and candidate[actor_col] == actor_line_user_id
                and candidate[undone_col].strip().lower() != "true"
                and candidate[action_col] not in {"UNDO", "FAILED"}
                and details_col is not None
                and details_col < len(candidate)
                and candidate[details_col] == selected_details
            ]
        break

    if not selected:
        return None

    undone_records: list[dict[str, str]] = []
    for row_number, row in sorted(selected, reverse=True):
        student_col = headers["student_id"]
        date_col = headers["date"]
        old_col = headers["old_status"]
        new_col = headers["new_status"]
        target_date = date.fromisoformat(row[date_col])
        student_id = row[student_col]
        old_status = row[old_col]
        new_status = row[new_col]
        action = row[action_col]
        if action == "CLEAR":
            details_col = headers["details"]
            saved = json.loads(row[details_col])
            for record in saved.get("records", []):
                append_attendance_row([
                    record["student_id"], record["name"], record["date"], record["type"],
                    record.get("status", "Confirmed"), record.get("raw_message", ""),
                    record.get("attendance_intent", ""), record.get("attendance_record_id", ""),
                ])
            if not update_monthly_report_cell(student_id, target_date, saved.get("monthly_status", "")):
                raise RuntimeError("Undo could not restore Monthly Report. Check the sheet before retrying.")
            _append_audit(actor_line_user_id, "UNDO", student_id, target_date, "", old_status, "Undo attendance clear")
        elif old_status:
            student = find_student_by_id(student_id)
            if student is None:
                raise RuntimeError(f"Cannot undo: student {student_id} is not in Students.")
            upsert_attendance_record(
                student_id, student["name"], target_date, old_status,
                actor_line_user_id, raw_message="Undo",
            )
        else:
            delete_attendance_record(student_id, target_date, actor_line_user_id)
        latest_audit = len(sheet.get_all_values())
        if latest_audit > 1:
            sheet.update_cell(latest_audit, action_col + 1, "UNDO")
        sheet.update_cell(row_number, undone_col + 1, "TRUE")
        undone_records.append(
            {
                "student_id": student_id,
                "date": target_date.isoformat(),
                "old_status": old_status,
                "new_status": new_status,
                "action": action,
            }
        )
    return {"records": json.dumps(undone_records, ensure_ascii=False)}


def _student_records() -> list[dict[str, object]]:
    return _read_students_records()


def find_student_by_id(identifier: str) -> dict[str, object] | None:
    """Resolve an exact student ID or a unique exact roster name."""

    normalized = identifier.strip().casefold()
    matches = []
    for record in _student_records():
        candidates = {
            str(record.get("student_id", "")).strip().casefold(),
            str(record.get("full_name", "")).strip().casefold(),
            str(record.get("chinese_name", "")).strip().casefold(),
            str(record.get("display_name", "")).strip().casefold(),
        }
        if normalized in candidates and _is_student_active(record):
            matches.append(_student_identity(record))
    return matches[0] if len(matches) == 1 else None


def find_student_by_line_id(line_user_id: str) -> dict[str, object] | None:
    return find_student_by_line_user_id(line_user_id)


def create_ticket(student_id: str, line_user_id: str, message: str) -> str:
    """Store untrusted ticket text literally; never interpret it as code."""
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        raise ValueError("Ticket messages must contain 1–4000 characters.")
    sheet = _ensure_named_sheet("Tickets", TICKET_HEADERS)
    if sheet is None:
        raise RuntimeError("Tickets worksheet is unavailable.")
    ticket_id = uuid4().hex[:4].upper()
    sheet.append_row(
        [
            ticket_id,
            datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
            student_id,
            line_user_id,
            message,
            "OPEN",
            "",
            "",
            "",
        ],
        value_input_option="RAW",
    )
    return ticket_id


def get_open_tickets() -> list[dict[str, str]]:
    sheet = _ensure_named_sheet("Tickets", TICKET_HEADERS)
    if sheet is None:
        raise RuntimeError("Tickets worksheet is unavailable.")
    rows = sheet.get_all_values()
    return [
        dict(zip(TICKET_HEADERS, row))
        for row in rows[1:]
        if len(row) >= len(TICKET_HEADERS) and row[5].upper() == "OPEN"
    ]


def get_ticket(ticket_id: str) -> dict[str, str] | None:
    sheet = _ensure_named_sheet("Tickets", TICKET_HEADERS)
    if sheet is None:
        raise RuntimeError("Tickets worksheet is unavailable.")
    rows = sheet.get_all_values()
    for row in rows[1:]:
        if row and row[0].casefold() == ticket_id.casefold():
            padded = row + [""] * (len(TICKET_HEADERS) - len(row))
            return dict(zip(TICKET_HEADERS, padded))
    return None


def update_ticket(ticket_id: str, actor_line_user_id: str, *, close: bool, note: str = "") -> bool:
    sheet = _ensure_named_sheet("Tickets", TICKET_HEADERS)
    if sheet is None:
        raise RuntimeError("Tickets worksheet is unavailable.")
    for row_number, row in enumerate(sheet.get_all_values()[1:], start=2):
        if row and row[0].casefold() == ticket_id.casefold():
            if close:
                sheet.update(
                    range_name=f"F{row_number}:I{row_number}",
                    values=[["CLOSED", actor_line_user_id, datetime.now(ZoneInfo("Asia/Taipei")).isoformat(), note]],
                    value_input_option="RAW",
                )
            else:
                sheet.update(
                    range_name=f"F{row_number}:H{row_number}",
                    values=[["OPEN", "", ""]],
                    value_input_option="RAW",
                )
            return True
    return False


def append_attendance_row(values: list[object]) -> str | None:
    """Append attendance under the configured table headers and return its ID."""

    if len(values) not in {6, 7, 8}:
        raise ValueError("Attendance rows must contain six, seven, or eight values.")
    student_id, student_name, day, attendance_type, status, raw_message = values[:6]
    if str(attendance_type) not in {"出席", "遲到", "不坐公交車"}:
        from attendance.leave_message import validate_leave_workday
        validate_leave_workday(date.fromisoformat(str(day)))
    attendance_intent = values[6] if len(values) >= 7 else False
    record_id = str(values[7]).strip() if len(values) == 8 else ""
    record_id = record_id or _new_attendance_record_id()
    if not str(student_id).strip() or not str(student_name).strip():
        raise ValueError("Attendance rows require both Work ID and student name.")

    sheet = ensure_attendance_sheet()
    if sheet is None:
        return None

    _, rows, header_row, columns = _attendance_header_layout()
    ordered_values = _attendance_row_values(
        columns,
        {
            "student_id": student_id,
            "name": student_name,
            "date": day,
            "type": attendance_type,
            "status": status,
            "raw_message": raw_message,
            "attendance_intent": attendance_intent,
            "attendance_record_id": record_id,
        },
    )
    last_data_row = header_row
    for row_number, row in enumerate(
        rows[header_row:],
        start=header_row + 1,
    ):
        if any(
            column - 1 < len(row) and str(row[column - 1]).strip()
            for column in columns.values()
        ):
            last_data_row = row_number
    first_column = min(columns.values())
    last_column = max(columns.values())
    sheet.update(
        range_name=(
            f"{_column_letter(first_column)}{last_data_row + 1}:"
            f"{_column_letter(last_column)}{last_data_row + 1}"
        ),
        values=[ordered_values],
        value_input_option="RAW",
    )
    schedule_attendance_mirror()
    return record_id


# --------------------------------------------------
# Monthly Report sheet
# --------------------------------------------------

MONTHLY_REPORT_SHEET_NAME = "Monthly Report"


def _get_monthly_report_sheet():
    """Return the Monthly Report worksheet, or None if unavailable."""
    if ensure_sheet_state() is None:
        return None
    try:
        return worksheet_handles.get((spreadsheet, MONTHLY_REPORT_SHEET_NAME),
                                     lambda: spreadsheet.worksheet(MONTHLY_REPORT_SHEET_NAME),
                                     ttl=30, copy=False)
    except WorksheetNotFound:
        available = [ws.title for ws in spreadsheet.worksheets()]
        print(
            f"MONTHLY REPORT: tab '{MONTHLY_REPORT_SHEET_NAME}' not found. "
            f"Available tabs: {available}"
        )
        return None


def _cell_as_day(cell_str: str, target_date: date) -> int | None:
    """Return the day number (1-31) if cell_str refers to a day in the
    target month, handling multiple formats gspread may return:

    - Plain integer:           9
    - Day + name (one cell):   9 Fri  (or with a newline between them)
    - Full date MM/DD/YYYY:    10/9/2026
    - Full date YYYY-MM-DD:    2026-10-09
    """
    s = str(cell_str).strip()
    if not s:
        return None

    # Full date formats — try these first before any integer parsing.
    first_line = s.split("\n")[0].strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(first_line, fmt).date()
            if dt.year == target_date.year and dt.month == target_date.month:
                return dt.day
        except ValueError:
            continue

    # Plain integer or "9 Fri" / "9\nFri" — take the leading numeric token.
    first_token = re.split(r"[\s\n]", first_line)[0].strip()
    try:
        d = int(first_token)
        if 1 <= d <= 31:
            return d
    except ValueError:
        pass

    return None


def update_monthly_report_cell(
    student_id: str,
    target_date: date,
    value: str,
) -> bool:
    """Write *value* (leave type or '出席') into the Monthly Report grid.

    Scans the sheet manually for the month header row, then the day-number
    row, then the student row, and writes *value* into the matching cell.
    Verbose debug logs are printed at every step so failures are diagnosable.
    Returns True on success.
    """
    sheet = _get_monthly_report_sheet()
    if sheet is None:
        print("MONTHLY REPORT: worksheet not found — check sheet tab name.")
        return False

    try:
        month_text = target_date.strftime("%B %Y")   # e.g. "October 2026"
        rows = sheet.get_all_values(pad_values=True)  # 0-indexed list

        print(f"MONTHLY REPORT: searching '{month_text}' in {len(rows)} rows.")

        # ---------------------------------------------------------------
        # 1. Find the month-header row (0-based index into `rows`).
        # ---------------------------------------------------------------
        header_row_0 = None
        for r_idx, row in enumerate(rows):
            for cell in row:
                if month_text.lower() in str(cell).strip().lower():
                    header_row_0 = r_idx
                    break
            if header_row_0 is not None:
                break

        if header_row_0 is None:
            for i, row in enumerate(rows[:10]):
                non_empty = [str(c).strip() for c in row if str(c).strip()]
                if non_empty:
                    print(f"  DEBUG row {i + 1}: {non_empty[:6]}")
            print(f"MONTHLY REPORT: '{month_text}' header not found.")
            return False

        print(f"MONTHLY REPORT: header found at row {header_row_0 + 1}.")

        # ---------------------------------------------------------------
        # 2. Find the day-number row in the next 8 rows after the header.
        # ---------------------------------------------------------------
        day_to_col: dict[int, int] = {}
        day_row_0: int | None = None

        for r_idx in range(header_row_0 + 1, min(header_row_0 + 9, len(rows))):
            candidate: dict[int, int] = {}
            for c_idx, cell in enumerate(rows[r_idx]):
                d = _cell_as_day(cell, target_date)
                if d is not None:
                    candidate[d] = c_idx
            print(
                f"  DEBUG row {r_idx + 1}: {len(candidate)} day cols "
                f"{sorted(candidate)[:8]}"
            )
            if len(candidate) >= 5:
                day_to_col = candidate
                day_row_0 = r_idx
                break

        if not day_to_col or day_row_0 is None:
            print(
                f"MONTHLY REPORT: day header row not found in rows "
                f"{header_row_0 + 2}–{header_row_0 + 9}."
            )
            return False

        print(
            f"MONTHLY REPORT: day row at row {day_row_0 + 1}. "
            f"Available days: {sorted(day_to_col)}"
        )

        target_col_0 = day_to_col.get(target_date.day)
        if target_col_0 is None:
            print(
                f"MONTHLY REPORT: day {target_date.day} column not found. "
                f"Available: {sorted(day_to_col)}"
            )
            return False

        # ---------------------------------------------------------------
        # 3. Determine student-ID column (first column left of day cols).
        # ---------------------------------------------------------------
        first_day_col_0 = min(day_to_col.values())
        student_id_col_0 = max(0, first_day_col_0 - 2)
        print(
            f"MONTHLY REPORT: first_day_col={first_day_col_0}, "
            f"target_col={target_col_0}, student_id_col={student_id_col_0}."
        )

        # ---------------------------------------------------------------
        # 4. Find the student row (starting immediately after day header).
        # ---------------------------------------------------------------
        next_month_re = re.compile(
            r"\b(January|February|March|April|May|June|July|"
            r"August|September|October|November|December)\s+\d{4}\b",
            re.IGNORECASE,
        )
        student_row_0: int | None = None
        for r_idx in range(day_row_0 + 1, len(rows)):
            row = rows[r_idx]
            for col_check in range(
                max(0, student_id_col_0 - 1),
                min(student_id_col_0 + 3, len(row)),
            ):
                if str(row[col_check]).strip() == str(student_id).strip():
                    student_row_0 = r_idx
                    break
            if student_row_0 is not None:
                break
            if next_month_re.search(" ".join(str(c) for c in row)):
                print(f"MONTHLY REPORT: hit next month block at row {r_idx + 1}.")
                break

        if student_row_0 is None:
            sample = day_row_0 + 1
            for i, row in enumerate(rows[sample:sample + 5], start=sample + 1):
                non_empty = [str(c).strip() for c in row[:5] if str(c).strip()]
                print(f"  DEBUG student area row {i}: {non_empty}")
            print(
                f"MONTHLY REPORT: student '{student_id}' not found "
                f"(searched col {student_id_col_0} ± neighbours)."
            )
            return False

        # ---------------------------------------------------------------
        # 5. Write (convert 0-based indices → 1-based for Sheets API).
        # ---------------------------------------------------------------
        sheet_row = student_row_0 + 1
        sheet_col = target_col_0 + 1
        sheet_reads.invalidate(sheet)
        sheet.update_cell(sheet_row, sheet_col, value)
        print(
            f"MONTHLY REPORT: wrote {value!r} for '{student_id}' "
            f"on {target_date} → sheet row={sheet_row}, col={sheet_col}."
        )
        sheet_reads.invalidate(sheet)
        return True

    except Exception as error:
        print("MONTHLY REPORT UPDATE ERROR:", repr(error))
        return False


def _monthly_report_layout(target_month: date, *, fresh=False):
    """Read one month block once for both personal and administrator views."""
    sheet = _get_monthly_report_sheet()
    if sheet is None:
        raise RuntimeError("The Monthly Report worksheet is unavailable.")

    if fresh:
        sheet_reads.invalidate(sheet)
    rows = cached_values(sheet, ttl=5)
    month_text = target_month.strftime("%B %Y").casefold()
    month_header_row = next(
        (
            row_index
            for row_index, row in enumerate(rows)
            if any(month_text in str(cell).strip().casefold() for cell in row)
        ),
        None,
    )
    if month_header_row is None:
        raise ValueError(
            f"The Monthly Report has no {target_month:%B %Y} section."
        )

    day_to_col: dict[int, int] = {}
    day_row = None
    for row_index in range(month_header_row + 1, min(month_header_row + 9, len(rows))):
        candidate = {
            day: column
            for column, cell in enumerate(rows[row_index])
            if (day := _cell_as_day(cell, target_month)) is not None
        }
        if len(candidate) >= 5:
            day_to_col = candidate
            day_row = row_index
            break
    if not day_to_col or day_row is None:
        raise ValueError(
            f"The day columns for {target_month:%B %Y} could not be found."
        )

    student_id_col = max(0, min(day_to_col.values()) - 2)
    next_month_re = re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{4}\b",
        re.IGNORECASE,
    )
    end_row = len(rows)
    for row_index in range(day_row + 1, len(rows)):
        if next_month_re.search(" ".join(str(cell) for cell in rows[row_index])):
            end_row = row_index
            break
    return rows[day_row + 1:end_row], day_to_col, student_id_col


def _entries_for_report_student(rows, day_to_col, student_id_col, student_id, target_month):
    student_row = next((row for row in rows if any(
        str(row[column]).strip() == str(student_id).strip()
        for column in range(max(0, student_id_col - 1), min(student_id_col + 3, len(row)))
    )), None)
    if student_row is None:
        raise ValueError(f"Student {student_id!r} was not found in the {target_month:%B %Y} report.")
    return {
        date(target_month.year, target_month.month, day):
        str(student_row[column]).strip() if column < len(student_row) else ""
        for day, column in day_to_col.items()
    }


def get_monthly_report_entries(student_id: str, target_month: date, *, fresh=False) -> dict[date, str]:
    """Read scheduled dates and cell labels from one monthly report row."""
    rows, day_to_col, student_id_col = _monthly_report_layout(target_month, fresh=fresh)
    return _entries_for_report_student(rows, day_to_col, student_id_col, student_id, target_month)


def get_daily_monthly_report(target_date: date) -> list[dict[str, str]]:
    """Read each active student's daily status from the authoritative grid."""
    students, _ = get_report_students()
    rows, columns, id_col = _monthly_report_layout(target_date)
    statuses = []
    for student_id, student in students.items():
        try:
            entries = _entries_for_report_student(rows, columns, id_col, student_id, target_date)
            status = entries.get(target_date, "Rest Day")
        except ValueError:
            status = "Missing Report Row"
        statuses.append({"student_id": student_id, "name": student.display_name, "type": status})
    return statuses


def get_monthly_attendance_counts(
    student_id: str, target_month: date,
) -> tuple[int, int]:
    """Count elapsed paid full days (including 特休) and half days for salary."""
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    values = [
        value.casefold() for day, value in get_monthly_report_entries(student_id, target_month).items()
        if day <= today
    ]
    return (
        sum(value in {"出席", "present", "特休", "annual leave", "special_leave"} for value in values),
        sum(value in {"半天", "half day", "half_day"} for value in values),
    )


def mark_present_in_monthly_report(target_date: date) -> None:
    """Write '出席' for every active student who has no leave on *target_date*.

    Preserve existing Monthly Report values, including manually entered leave.
    Leave log entries also prevent a failed mirror write from becoming present.
    """
    try:
        students, _ = get_report_students()
        leave_student_ids = {
            row["student_id"]
            for row in get_attendance_rows(target_date)
        }
        for student_id in students:
            if student_id in leave_student_ids:
                continue  # already has a leave record — do not overwrite
            entries = get_monthly_report_entries(student_id, target_date)
            if target_date not in entries or entries[target_date]:
                continue
            update_monthly_report_cell(student_id, target_date, "出席")
    except Exception as error:
        print("MARK PRESENT ERROR:", repr(error))


def get_student_tickets(student_id: str) -> list[dict[str, str]]:
    """Retrieve all tickets submitted by or for a student."""
    sheet = _ensure_named_sheet("Tickets", TICKET_HEADERS)
    if sheet is None:
        return []
    rows = sheet.get_all_values()
    student_id_str = str(student_id).strip()
    matching = []
    for row in rows[1:]:
        if len(row) >= 3 and str(row[2]).strip() == student_id_str:
            padded = row + [""] * (len(TICKET_HEADERS) - len(row))
            matching.append(dict(zip(TICKET_HEADERS, padded)))
    matching.sort(key=lambda t: t.get("Created At", ""), reverse=True)
    return matching


def get_student_leave_records(
    student_id: str,
    target_month: date | None = None,
    category: str | None = None,
) -> list[dict[str, str]]:
    """Retrieve leave records for a student, optionally filtered by month or category."""
    all_rows = get_attendance_rows()
    student_id_str = str(student_id).strip()
    month_prefix = target_month.strftime("%Y-%m") if target_month else None
    category_cf = category.casefold().strip() if category else None

    results = []
    for row in all_rows:
        if str(row.get("student_id", "")).strip() != student_id_str:
            continue
        row_type = row.get("type", "").strip()
        if row_type in {"出席", "遲到", "不坐公交車"}:
            continue
        row_date = row.get("date", "")
        if month_prefix and not row_date.startswith(month_prefix):
            continue
        if category_cf:
            if category_cf not in row_type.casefold() and row_type.casefold() not in category_cf:
                continue
        results.append(row)

    results.sort(key=lambda r: r.get("date", ""), reverse=True)
    return results


def get_student_attendance_summary(
    student_id: str, target_month: date,
) -> dict[str, object]:
    """Calculate MTD attendance solely from the student's Monthly Report grid.

    The report's day columns define the schedule. Blank elapsed cells mean
    present; today's blank cell is pending. Future leave never reduces MTD.
    Missing reports raise an error instead of falling back to leave logs.
    """
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    entries = get_monthly_report_entries(student_id, target_month)
    month_start = target_month.replace(day=1)
    current = month_start == today.replace(day=1)
    future = month_start > today.replace(day=1)
    translations = {
        "出席": "Present", "present": "Present",
        "遲到": "Late", "迟到": "Late", "late": "Late",
        "病假": "Sick Leave", "事假": "Personal Leave",
        "經痛": "Menstrual Leave", "特休": "Annual Leave",
        "annual leave": "Annual Leave", "special_leave": "Annual Leave",
        "半天": "Half Day", "half day": "Half Day", "half_day": "Half Day",
        "回菲律賓": "Abroad", "待確認": "Pending Review",
        "不坐公交車": "No Bus", "不出來": "Absent", "取消工讀": "Cancelled Work",
    }
    today_value = entries.get(today, "").casefold()
    if current:
        today_status = (
            "Rest Day" if today not in entries else
            translations.get(today_value, today_value or "Pending")
        )
    else:
        today_status = "Upcoming" if future else "Completed"
    completed = {
        day: value.casefold() for day, value in entries.items()
        if day < today or (day == today and value and value != "待確認")
    }
    attended = absent = half = late = 0
    for value in completed.values():
        if value in {"半天", "half day", "half_day"}:
            half += 1
        elif value in {"遲到", "迟到", "late"}:
            late += 1
            attended += 1
        elif value in {"", "出席", "present", "不坐公交車", "no bus", "特休", "annual leave", "special_leave"}:
            attended += 1
        else:
            absent += 1
    total = len(entries)
    elapsed = len(completed)
    return {
        "scheduled_days": total,
        "completed_scheduled_workdays": elapsed,
        "remaining_scheduled_workdays": total - elapsed,
        "elapsed_workdays": elapsed,
        "attended_days": attended,
        "absent_days": absent,
        "half_days": half,
        "late_days": late,
        "attendance_pct": round((attended + half * 0.5) / elapsed * 100) if elapsed else None,
        "today_status": today_status,
        "month_label": target_month.strftime("%B %Y"),
    }


def get_work_calendar_schedule(
    start_date: date | None = None,
    days: int = 7,
) -> list[dict[str, object]]:
    """Fetch upcoming schedule from the Work Calendar tab or default to Wed-Sun."""
    from scheduler.work_calendar import is_workday
    from datetime import timedelta
    ensure_sheet_state()
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    start = start_date or today

    calendar_sheet = None
    if spreadsheet is not None:
        for title in ("Work Calendar", "Calendar", "Schedule", "工作日曆"):
            try:
                calendar_sheet = spreadsheet.worksheet(title)
                break
            except WorksheetNotFound:
                pass

    sheet_overrides = {}
    if calendar_sheet is not None:
        try:
            records = calendar_sheet.get_all_values()
            if records and len(records) > 1:
                header = [str(c).strip().lower() for c in records[0]]
                date_col = next((i for i, h in enumerate(header) if "date" in h or "日期" in h), 0)
                type_col = next((i for i, h in enumerate(header) if "type" in h or "status" in h or "類型" in h or "狀態" in h), 1)
                note_col = next((i for i, h in enumerate(header) if "note" in h or "備註" in h or "holiday" in h or "說明" in h), -1)

                for r in records[1:]:
                    if len(r) > date_col:
                        raw_d = str(r[date_col]).strip()
                        try:
                            d_parsed = date.fromisoformat(raw_d[:10])
                            status_val = str(r[type_col]).strip() if len(r) > type_col else ""
                            note_val = str(r[note_col]).strip() if note_col >= 0 and len(r) > note_col else ""
                            sheet_overrides[d_parsed] = (status_val, note_val)
                        except (ValueError, IndexError):
                            pass
        except Exception as error:
            print("WORK CALENDAR READ ERROR:", repr(error))

    schedule_list = []
    for i in range(days):
        day = start + timedelta(days=i)
        if day in sheet_overrides:
            s_type, s_note = sheet_overrides[day]
            is_work = "work" in s_type.lower() or "上班" in s_type or "出勤" in s_type
            display_type = "Workday" if is_work else (s_type if "holiday" in s_type.lower() else "Rest Day")
            note = s_note or ("Scheduled workday" if is_work else "Rest day")
        else:
            is_work = is_workday(day)
            display_type = "Workday" if is_work else "Rest Day"
            note = "Scheduled workday (8 hrs)" if is_work else "Standard rest day"

        schedule_list.append({
            "date": day,
            "date_str": day.strftime("%Y-%m-%d"),
            "formatted_date": day.strftime("%b %d"),
            "weekday_en": day.strftime("%a"),
            "is_workday": is_work,
            "type": display_type,
            "note": note,
        })
    return schedule_list

LANGUAGE_HEADERS = ["LINE User ID", "Language"]


def get_user_language(user_id: str) -> str:
    sheet = _ensure_named_sheet("User Settings", LANGUAGE_HEADERS)
    if sheet is None:
        return "en"
    for row in cached_values(sheet, ttl=30)[1:]:
        if row and row[0] == user_id:
            return row[1] if len(row) > 1 and row[1] in {"en", "zh-TW"} else "en"
    return "en"


def set_user_language(user_id: str, language: str) -> None:
    if language not in {"en", "zh-TW"} or not user_id:
        raise ValueError("Invalid language preference.")
    sheet = _ensure_named_sheet("User Settings", LANGUAGE_HEADERS)
    if sheet is None:
        raise RuntimeError("Google Sheets is unavailable.")
    for index, row in enumerate(sheet.get_all_values()[1:], start=2):
        if row and row[0] == user_id:
            sheet.update_cell(index, 2, language)
            sheet_reads.invalidate(sheet)
            return
    sheet.append_row([user_id, language], value_input_option="RAW")
    sheet_reads.invalidate(sheet)


TERMS_VERSION = "2026-10-12"

AUTHORIZATION_HEADERS = ["LINE User ID", "Student ID", "Authorized At", "Terms Version"]


def save_account_authorization(user_id: str, student_id: str) -> None:
    """Record consent only for the student's already linked LINE account."""
    student = find_student_by_line_user_id(user_id)
    if not student or str(student.get("student_id", "")).strip() != student_id:
        raise ValueError("The LINE account is not linked to this student.")
    sheet = _ensure_named_sheet("Account Authorizations", AUTHORIZATION_HEADERS)
    if sheet is None:
        raise RuntimeError("Google Sheets is unavailable.")
    for row in sheet.get_all_values()[1:]:
        if len(row) >= 4 and row[0] == user_id and row[1] == student_id and row[3] == TERMS_VERSION:
            return  # Retain the original consent timestamp on repeated taps.
    sheet.append_row(
        [user_id, student_id, datetime.now(ZoneInfo("Asia/Taipei")).isoformat(), TERMS_VERSION],
        value_input_option="RAW",
    )


def search_active_students(query: str) -> list[dict[str, object]]:
    """Search IDs and every roster name field without AI or fuzzy identity linking."""
    terms = query.strip().casefold().split()
    if not terms:
        return []
    results = []
    for record in _read_students_records():
        if not _is_student_active(record):
            continue
        haystack = " ".join(str(record.get(key) or "") for key in (
            "student_id", "chinese_name", "full_name", "display_name", "name",
        )).casefold()
        if all(term in haystack for term in terms):
            results.append(_student_identity(record))
    return sorted(results, key=lambda student: (
        str(student["student_id"]).casefold() != query.strip().casefold(), str(student["student_id"]),
    ))
