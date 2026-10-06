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


def connect_google_sheets():
    service_account_info = json.loads(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    )
    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES,
    )
    client = gspread.authorize(credentials)
    return client.open_by_key(os.environ["GOOGLE_SHEET_ID"])


spreadsheet = connect_google_sheets()
students_sheet = spreadsheet.worksheet("Students")

try:
    attendance_sheet = spreadsheet.worksheet("Attendance")
except WorksheetNotFound:
    attendance_sheet = spreadsheet.add_worksheet(
        title="Attendance",
        rows=1000,
        cols=len(ATTENDANCE_HEADERS),
    )

if not attendance_sheet.get_all_values():
    attendance_sheet.append_row(
        ATTENDANCE_HEADERS,
        value_input_option="RAW",
    )


def find_student_by_line_user_id(line_user_id: str) -> dict[str, str] | None:
    """Find the roster row associated with a LINE user ID."""

    return find_student(students_sheet.get_all_records(), line_user_id)


def find_student_by_display_name(display_name: str) -> dict[str, str] | None:
    """Find one active roster entry by exact LINE display name."""

    return find_student_name(students_sheet.get_all_records(), display_name)