"""Google Sheets connection and worksheet handles."""

import json
import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

from attendance.student_directory import (
    find_student_by_line_user_id as find_student,
    find_student_by_name as find_student_name,
)


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


def find_student_by_line_user_id(line_user_id: str) -> dict[str, str] | None:
    """Find the roster row associated with a LINE user ID."""

    if ensure_sheet_state() is None or students_sheet is None:
        return None

    return find_student(students_sheet.get_all_records(), line_user_id)


def find_student_by_display_name(display_name: str) -> dict[str, str] | None:
    """Find one active roster entry by exact LINE display name."""

    if ensure_sheet_state() is None or students_sheet is None:
        return None

    return find_student_name(students_sheet.get_all_records(), display_name)


def ensure_attendance_sheet():
    """Return the writable attendance sheet or None if Google Sheets is not ready."""

    ensure_sheet_state()
    return attendance_sheet