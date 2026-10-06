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

    def test_students_parser_handles_blank_prefix_columns(self) -> None:
        import database.google_sheets as google_sheets

        rows = [
            ["", "", "student_id", "name", "line_user_id", "active"],
            ["", "", "24113328", "Alice", "U123", "TRUE"],
            ["", "", "24113329", "Bob", "U999", "FALSE"],
        ]

        result = google_sheets._read_sheet_records(
            type("SheetStub", (), {"get_all_values": lambda self: rows})(),
            required_headers=("student_id", "name", "line_user_id", "active"),
        )

        self.assertEqual(
            result[0],
            {
                "student_id": "24113328",
                "name": "Alice",
                "line_user_id": "U123",
                "active": "TRUE",
            },
        )


if __name__ == "__main__":
    unittest.main()
