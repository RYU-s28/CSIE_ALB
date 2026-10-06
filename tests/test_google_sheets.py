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

    def test_students_parser_preserves_line_registration_cell_location(self) -> None:
        import database.google_sheets as google_sheets

        rows = [
            ["", "Student ID", "Chinese Name", "Full Name", "LINE Display Name", "LINE User ID", "Active"],
            ["", "24113328", "杜榮瑪", "Michael Arbor", "MICHAEL(潘伯森)", "", "TRUE"],
        ]
        records = google_sheets._read_sheet_records(
            type("SheetStub", (), {"get_all_values": lambda self: rows})(),
            required_headers=(
                "student_id",
                "full_name",
                "line_user_id",
                "active",
                "display_name",
            ),
            include_row_metadata=True,
        )

        self.assertEqual(records[0]["student_id"], "24113328")
        self.assertEqual(records[0]["chinese_name"], "杜榮瑪")
        self.assertEqual(records[0]["full_name"], "Michael Arbor")
        self.assertEqual(records[0]["display_name"], "MICHAEL(潘伯森)")
        self.assertEqual(records[0]["_row_number"], 2)
        self.assertEqual(records[0]["_line_user_id_column"], 6)

    def test_registration_updates_only_line_user_id_cell(self) -> None:
        import database.google_sheets as google_sheets

        class SheetStub:
            def __init__(self, existing_user_id: str = "") -> None:
                self.updated = None
                self.existing_user_id = existing_user_id

            def cell(self, row: int, column: int):
                return type(
                    "Cell",
                    (),
                    {"value": self.existing_user_id},
                )()

            def update_cell(self, row: int, column: int, value: str) -> None:
                self.updated = (row, column, value)

        sheet = SheetStub()
        with (
            mock.patch.object(google_sheets, "students_sheet", sheet),
            mock.patch.object(google_sheets, "ensure_sheet_state", return_value=object()),
        ):
            google_sheets.register_line_user(
                {"_row_number": 8, "_line_user_id_column": 6},
                "U123",
            )

        self.assertEqual(sheet.updated, (8, 6, "U123"))

    def test_registration_never_overwrites_an_existing_user_id(self) -> None:
        import database.google_sheets as google_sheets

        class SheetStub:
            def cell(self, row: int, column: int):
                return type("Cell", (), {"value": "U111"})()

            def update_cell(self, row: int, column: int, value: str) -> None:
                raise AssertionError("An existing LINE ID must not be overwritten")

        with (
            mock.patch.object(google_sheets, "students_sheet", SheetStub()),
            mock.patch.object(google_sheets, "ensure_sheet_state", return_value=object()),
        ):
            with self.assertRaises(
                google_sheets.LineRegistrationConflictError
            ) as raised:
                google_sheets.register_line_user(
                    {"_row_number": 8, "_line_user_id_column": 6},
                    "U222",
                )

        self.assertEqual(raised.exception.existing_user_id, "U111")
        self.assertEqual(raised.exception.incoming_user_id, "U222")

    def test_display_name_matches_without_an_active_column(self) -> None:
        import database.google_sheets as google_sheets

        records = [
            {
                "student_id": "S06516",
                "chinese_name": "杜樂珮",
                "full_name": "Romel R. Duran Jr.",
                "display_name": "杜樂珮RYU",
                "line_user_id": "",
                "_row_number": 29,
                "_line_user_id_column": 5,
            }
        ]
        with mock.patch.object(
            google_sheets,
            "_read_students_records",
            return_value=records,
        ):
            matches = google_sheets.find_students_by_display_name("杜樂珮RYU")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["student_id"], "S06516")
        self.assertEqual(matches[0]["_line_user_id_column"], 5)

    def test_explicitly_inactive_student_does_not_match(self) -> None:
        import database.google_sheets as google_sheets

        records = [
            {
                "student_id": "S06516",
                "full_name": "Romel R. Duran Jr.",
                "display_name": "杜樂珮RYU",
                "active": "FALSE",
            }
        ]
        with mock.patch.object(
            google_sheets,
            "_read_students_records",
            return_value=records,
        ):
            matches = google_sheets.find_students_by_display_name("杜樂珮RYU")

        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
