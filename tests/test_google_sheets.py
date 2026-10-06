import importlib
import os
import unittest
from unittest import mock


class GoogleSheetsLazyInitTests(unittest.TestCase):
    def test_missing_google_config_does_not_crash_import(self) -> None:
        import database.google_sheets as google_sheets

        with mock.patch.dict(os.environ, {}, clear=True):
            for key in (
                "GOOGLE_SERVICE_ACCOUNT_JSON",
                "GOOGLE_SHEET_ID",
            ):
                os.environ.pop(key, None)

            reloaded = importlib.reload(google_sheets)

            self.assertIsNone(reloaded.spreadsheet)
            self.assertIsNone(reloaded.students_sheet)
            self.assertIsNone(reloaded.attendance_sheet)
            self.assertIsNone(reloaded.find_student_by_line_user_id("U123"))
            self.assertIsNone(reloaded.find_student_by_display_name("Alice"))


if __name__ == "__main__":
    unittest.main()
