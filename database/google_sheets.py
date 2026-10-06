"""Google Sheets connection and worksheet handles."""

import json
import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
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
attendance_sheet = spreadsheet.worksheet("Attendance")
work_calendar_sheet = spreadsheet.worksheet("Work Calendar")