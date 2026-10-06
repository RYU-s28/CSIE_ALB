"""Google Sheets connection and worksheet handles."""

import json
import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

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
]
LOGS_HEADERS = ["Work ID", "Name", "Date", "Type", "Status", "Raw Message"]

spreadsheet = None
students_sheet = None
attendance_sheet = None
logs_sheet = None


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

    attendance_values = (
        attendance_sheet.get_all_values()
        if attendance_sheet is not None
        else []
    )
    logs_header = logs_sheet.acell("B4").value if logs_sheet is not None else None

    if attendance_sheet is not None and len(attendance_values) > 1:
        global ATTENDANCE_TABLE_RANGE
        ATTENDANCE_TABLE_RANGE = "A1:F1"
    elif logs_sheet is not None and logs_header:
        attendance_sheet = logs_sheet
        ATTENDANCE_TABLE_RANGE = "B4:G4"
    elif attendance_sheet is not None:
        ATTENDANCE_TABLE_RANGE = "A1:F1"
    elif logs_sheet is not None:
        attendance_sheet = logs_sheet
        ATTENDANCE_TABLE_RANGE = "B4:G4"
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
        ATTENDANCE_TABLE_RANGE = "A1:F1"
        attendance_sheet.append_row(
            ATTENDANCE_HEADERS,
            value_input_option="RAW",
        )

    return spreadsheet


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

    rows = sheet.get_all_values()
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
            result.update(identity)
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
            record.get("display_name")
            or record.get("full_name")
            or record.get("name")
            or record.get("chinese_name")
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


def append_attendance_row(values: list[object]) -> bool:
    """Append attendance under the configured table headers."""

    sheet = ensure_attendance_sheet()
    if sheet is None:
        return False

    sheet.append_row(
        values,
        value_input_option="RAW",
        table_range=ATTENDANCE_TABLE_RANGE,
    )
    return True