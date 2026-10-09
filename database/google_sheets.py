"""Google Sheets connection and worksheet handles."""

import json
import os
import re
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

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


def connect_google_sheets():
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")

    if not service_account_json or not spreadsheet_id:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID are required."
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

    global spreadsheet, students_sheet, attendance_sheet, logs_sheet

    if spreadsheet is not None:
        return spreadsheet

    try:
        spreadsheet = connect_google_sheets()
    except Exception as error:
        print("GOOGLE SHEETS INIT ERROR:", repr(error))
        return None

    students_sheet = spreadsheet.worksheet("Students")

    try:
        attendance_sheet = spreadsheet.worksheet("Attendance")
    except WorksheetNotFound:
        attendance_sheet = None

    try:
        logs_sheet = spreadsheet.worksheet("Logs")
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
        attendance_sheet = spreadsheet.add_worksheet(
            title="Attendance",
            rows=1000,
            cols=len(ATTENDANCE_HEADERS),
        )
        ATTENDANCE_TABLE_RANGE = "A1:G1"
        attendance_sheet.append_row(
            ATTENDANCE_HEADERS,
            value_input_option="RAW",
        )

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
) -> list[dict[str, object]]:
    """Read a sheet while tolerating blank or duplicate header cells."""

    if sheet is None:
        return []

    rows = sheet.get_all_values(pad_values=True)
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


def ensure_attendance_sheet():
    """Return the writable attendance sheet or None if Google Sheets is not ready."""

    ensure_sheet_state()
    return attendance_sheet


def _ensure_named_sheet(name: str, headers: list[str]):
    if ensure_sheet_state() is None:
        return None
    try:
        sheet = spreadsheet.worksheet(name)
    except WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=name, rows=1000, cols=len(headers))
    if not any(str(value).strip() for value in sheet.row_values(1)):
        sheet.append_row(headers, value_input_option="RAW")
    return sheet


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
    return {"old_status": old_status, "action_id": action_id}


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
        if old_status:
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


def update_ticket(ticket_id: str, actor_line_user_id: str, *, close: bool) -> bool:
    sheet = _ensure_named_sheet("Tickets", TICKET_HEADERS)
    if sheet is None:
        raise RuntimeError("Tickets worksheet is unavailable.")
    for row_number, row in enumerate(sheet.get_all_values()[1:], start=2):
        if row and row[0].casefold() == ticket_id.casefold():
            if close:
                sheet.update(
                    range_name=f"F{row_number}:H{row_number}",
                    values=[["CLOSED", actor_line_user_id, datetime.now(ZoneInfo("Asia/Taipei")).isoformat()]],
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
        return spreadsheet.worksheet(MONTHLY_REPORT_SHEET_NAME)
    except WorksheetNotFound:
        return None


def _find_month_block(
    rows: list[list[str]],
    target_date: date,
) -> tuple[int, int] | None:
    """Locate the header row and starting column for the given month/year.

    The Monthly Report sheet stacks month blocks vertically.  Each block has
    a merged header cell whose text contains the month name and year (e.g.
    "October 2026").  The day numbers (1–31) appear on the next non-empty row.

    Returns (day_header_row_idx, student_id_col_idx) using 0-based indices,
    or None if the month block is not found.
    """
    month_name = target_date.strftime("%B %Y")  # e.g. "October 2026"
    for row_idx, row in enumerate(rows):
        for cell in row:
            if month_name.lower() in str(cell).strip().lower():
                # Scan forward for the row that contains day numbers 1–31.
                for day_row_idx in range(row_idx + 1, min(row_idx + 6, len(rows))):
                    day_row = rows[day_row_idx]
                    day_numbers = [
                        str(cell).strip()
                        for cell in day_row
                        if str(cell).strip().lstrip("0").isdigit()
                    ]
                    if len(day_numbers) >= 10:  # must have most of the days
                        # Find which column index is the student ID column
                        # (first column before the day numbers that is non-numeric).
                        student_id_col = 0
                        for col_idx, cell in enumerate(day_row):
                            if str(cell).strip().lstrip("0").isdigit():
                                student_id_col = max(0, col_idx - 2)
                                break
                        return day_row_idx, student_id_col
    return None


def update_monthly_report_cell(
    student_id: str,
    target_date: date,
    value: str,
) -> bool:
    """Write a leave type or '出席' into the Monthly Report grid cell.

    Finds the month block for *target_date*, then the student row by matching
    the student ID in the first usable column of that block, then writes
    *value* into the column corresponding to target_date.day.

    Returns True on success, False if the sheet or cell could not be found.
    """
    sheet = _get_monthly_report_sheet()
    if sheet is None:
        print("MONTHLY REPORT: worksheet not found.")
        return False

    try:
        rows = sheet.get_all_values(pad_values=True)
        result = _find_month_block(rows, target_date)
        if result is None:
            print(f"MONTHLY REPORT: month block for {target_date:%B %Y} not found.")
            return False

        day_row_idx, student_id_col = result
        day_row = rows[day_row_idx]

        # Build a mapping from day number → column index (0-based).
        day_to_col: dict[int, int] = {}
        for col_idx, cell in enumerate(day_row):
            stripped = str(cell).strip().lstrip("0")
            if stripped.isdigit():
                day_num = int(stripped) if stripped else int(str(cell).strip())
                if 1 <= day_num <= 31:
                    day_to_col[day_num] = col_idx

        target_col_idx = day_to_col.get(target_date.day)
        if target_col_idx is None:
            print(f"MONTHLY REPORT: day column for day {target_date.day} not found.")
            return False

        # Find the student row — scan rows below the day header.
        student_row_idx = None
        for row_idx in range(day_row_idx + 1, len(rows)):
            cell_val = str(rows[row_idx][student_id_col]).strip()
            if cell_val == str(student_id).strip():
                student_row_idx = row_idx
                break
            # Stop scanning when we hit the next month block header.
            combined = " ".join(str(c).strip() for c in rows[row_idx])
            if re.search(r"\b(January|February|March|April|May|June|July|"
                         r"August|September|October|November|December)\s+\d{4}\b",
                         combined, re.IGNORECASE):
                break

        if student_row_idx is None:
            print(f"MONTHLY REPORT: student {student_id} not found in month block.")
            return False

        # Sheets API uses 1-based row/col numbers.
        sheet_row = student_row_idx + 1
        sheet_col = target_col_idx + 1
        sheet.update_cell(sheet_row, sheet_col, value)
        print(
            f"MONTHLY REPORT: wrote {value!r} for student {student_id} "
            f"on {target_date} (row={sheet_row}, col={sheet_col})."
        )
        return True

    except Exception as error:
        print("MONTHLY REPORT UPDATE ERROR:", repr(error))
        return False


def mark_present_in_monthly_report(target_date: date) -> None:
    """Write '出席' for every active student who has no leave on *target_date*.

    Reads today's attendance rows from the Attendance sheet and skips any
    student that already has a record.  All remaining active students are
    marked as 出席 in the Monthly Report grid.
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
            update_monthly_report_cell(student_id, target_date, "出席")
    except Exception as error:
        print("MARK PRESENT ERROR:", repr(error))