import importlib
import os
import unittest
from datetime import date
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
            type("SheetStub", (), {"get_all_values": lambda self, pad_values=False: rows})(),
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
            type("SheetStub", (), {"get_all_values": lambda self, pad_values=False: rows})(),
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

    def test_students_work_id_and_chinese_name_survive_identity_mapping(self) -> None:
        import database.google_sheets as google_sheets

        records = [
            {
                "student_id": "S06516",
                "chinese_name": "杜樂珮",
                "full_name": "Romel R. Duran Jr.",
                "display_name": "杜樂珮RYU",
                "line_user_id": "U123",
            }
        ]
        with mock.patch.object(
            google_sheets,
            "_read_students_records",
            return_value=records,
        ):
            student = google_sheets.find_student_by_line_user_id(" U123 ")

        self.assertEqual(student["student_id"], "S06516")
        self.assertEqual(student["chinese_name"], "杜樂珮")
        self.assertEqual(student["name"], "Romel R. Duran Jr.")

    def test_roster_identity_reads_work_id_from_column_b_with_title_rows(self) -> None:
        import database.google_sheets as google_sheets

        class SheetStub:
            def get_all_values(self, pad_values=False):
                return [
                    ["Attendance roster"],
                    [],
                    [],
                    [
                        "",
                        "Work ID",
                        "Chinese Name",
                        "Full Name",
                        "LINE Display Name",
                        "LINE User ID",
                        "Active",
                    ],
                    [
                        "",
                        "S06677",
                        "杜樂珮",
                        "Romel R. Duran Jr.",
                        "杜樂珮RYU",
                        "Uregistered",
                        "TRUE",
                    ],
                ]

        with (
            mock.patch.object(google_sheets, "students_sheet", SheetStub()),
            mock.patch.object(google_sheets, "ensure_sheet_state", return_value=object()),
        ):
            student = google_sheets.find_student_by_line_user_id("Uregistered")

        self.assertIsNotNone(student)
        self.assertEqual(student["student_id"], "S06677")
        self.assertEqual(student["chinese_name"], "杜樂珮")
        self.assertEqual(student["name"], "Romel R. Duran Jr.")

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

    def test_attendance_append_updates_next_row_under_logs_headers(self) -> None:
        import database.google_sheets as google_sheets

        class SheetStub:
            def __init__(self) -> None:
                self.updated = None
                self.updates = []

            def get_all_values(self, pad_values=False):
                return [
                    [],
                    [],
                    [],
                    ["", "Work ID", "Name", "Date", "Type", "Status", "Raw Message"],
                    [],
                    [],
                    [],
                    ["", "S00001", "Existing Student", "2026-10-05", "病假", "Confirmed", "old"],
                ]

            def update(self, *, range_name, values, value_input_option) -> None:
                self.updated = (range_name, values, value_input_option)
                self.updates.append(self.updated)

        sheet = SheetStub()
        values = [
            "S06516",
            "羅美樂",
            "2026-10-06",
            "病假",
            "Confirmed",
            "Sick leave",
            True,
        ]
        with (
            mock.patch.object(
                google_sheets,
                "ensure_attendance_sheet",
                return_value=sheet,
            ),
            mock.patch.object(
                google_sheets,
                "ATTENDANCE_TABLE_RANGE",
                "B4:G4",
            ),
        ):
            appended = google_sheets.append_attendance_row(values)

        self.assertTrue(appended)
        self.assertEqual(sheet.updated, ("B9:H9", [values], "RAW"))
        self.assertEqual(
            sheet.updates[0],
            ("H4:H4", [["attendance_intent"]], "RAW"),
        )

    def test_attendance_header_scan_finds_legacy_table_position(self) -> None:
        import database.google_sheets as google_sheets

        sheet = type(
            "SheetStub",
            (),
            {
                "get_all_values": lambda self, pad_values=False: [
                    ["Attendance title"],
                    [],
                    [],
                    ["", "Work ID", "Name", "Date", "Type", "Status", "Raw Message"],
                ]
            },
        )()

        self.assertEqual(
            google_sheets._find_attendance_table(sheet),
            "B4:G4",
        )

    def test_legacy_pending_absence_is_backfilled_with_intent(self) -> None:
        import database.google_sheets as google_sheets

        class SheetStub:
            def __init__(self) -> None:
                self.updates = []

            def get_all_values(self, pad_values=False):
                return [
                    ["Work ID", "Name", "Date", "Type", "Status", "Raw Message"],
                    [
                        "S1",
                        "Student One",
                        "2026-10-10",
                        "待確認",
                        "Pending",
                        "I will not be working today because of a migraine",
                    ],
                ]

            def update(self, *, range_name, values, value_input_option):
                self.updates.append((range_name, values, value_input_option))

        sheet = SheetStub()
        with (
            mock.patch.object(google_sheets, "ensure_attendance_sheet", return_value=sheet),
            mock.patch.object(google_sheets, "ATTENDANCE_TABLE_RANGE", "A1:F1"),
        ):
            records = google_sheets.get_attendance_rows(date(2026, 10, 10))

        self.assertEqual(records[0]["attendance_intent"], "TRUE")
        self.assertIn(
            ("G2:G2", [[True]], "RAW"),
            sheet.updates,
        )

    def test_attendance_append_requires_work_id_and_name(self) -> None:
        import database.google_sheets as google_sheets

        with self.assertRaisesRegex(ValueError, "Work ID and student name"):
            google_sheets.append_attendance_row(
                ["", "", "2026-10-06", "病假", "Confirmed", "message"]
            )

    def test_attendance_append_returns_false_when_sheet_is_unavailable(self) -> None:
        import database.google_sheets as google_sheets

        with mock.patch.object(
            google_sheets,
            "ensure_attendance_sheet",
            return_value=None,
        ):
            appended = google_sheets.append_attendance_row(
                ["S1", "Chinese Name", "2026-10-06", "病假", "Confirmed", "message"]
            )

        self.assertFalse(appended)

    def test_report_roster_uses_display_name_and_active_roster_size(self) -> None:
        import database.google_sheets as google_sheets

        records = [
            {
                "student_id": "S1",
                "chinese_name": "華凌智",
                "display_name": "Roster nick",
                "full_name": "Student One",
            },
            {
                "student_id": "S2",
                "chinese_name": "倪瑪芮 HEART",
                "display_name": "倪瑪芮 HEART",
                "full_name": "Student Two",
                "active": "TRUE",
            },
            {
                "student_id": "S3",
                "display_name": "Inactive",
                "active": "FALSE",
            },
        ]
        with mock.patch.object(
            google_sheets,
            "_read_students_records",
            return_value=records,
        ):
            students, expected_count = google_sheets.get_report_students()

        self.assertEqual(expected_count, 2)
        self.assertEqual(students["S1"].display_name, "華凌智")
        self.assertEqual(students["S2"].display_name, "倪瑪芮 HEART")
        self.assertNotIn("S3", students)

    def test_attendance_upsert_updates_one_student_date_row(self) -> None:
        import database.google_sheets as google_sheets

        class SheetStub:
            def __init__(self) -> None:
                self.values = [
                    ["Work ID", "Name", "Date", "Type", "Status", "Raw Message"],
                    ["S1", "Student One", "2026-10-10", "病假", "Confirmed", "old"],
                ]
                self.updated = None

            def get_all_values(self, pad_values=False):
                return self.values

            def update(self, *, range_name, values, value_input_option):
                self.updated = (range_name, values, value_input_option)

        sheet = SheetStub()
        with (
            mock.patch.object(google_sheets, "ensure_attendance_sheet", return_value=sheet),
            mock.patch.object(google_sheets, "ATTENDANCE_TABLE_RANGE", "A1:F1"),
            mock.patch.object(google_sheets, "_append_audit", return_value="ACT1"),
        ):
            result = google_sheets.upsert_attendance_record(
                "S1",
                "Student One",
                date(2026, 10, 10),
                "事假",
                "Uadmin",
            )

        self.assertEqual(result["action"], "UPDATE")
        self.assertEqual(result["old_status"], "病假")
        self.assertEqual(sheet.updated[0], "A2:G2")
        self.assertEqual(sheet.updated[1][0][3], "事假")

    def test_student_leave_removal_is_restricted_to_leave_rows(self) -> None:
        import database.google_sheets as google_sheets

        class SheetStub:
            def get_all_values(self, pad_values=False):
                return [
                    ["Work ID", "Name", "Date", "Type", "Status", "Raw Message"],
                    ["S1", "Student One", "2026-10-10", "遲到", "Confirmed", ""],
                ]

            def update(self, *, range_name, values, value_input_option):
                pass

        with (
            mock.patch.object(google_sheets, "ensure_attendance_sheet", return_value=SheetStub()),
            mock.patch.object(google_sheets, "ATTENDANCE_TABLE_RANGE", "A1:F1"),
        ):
            result = google_sheets.delete_attendance_record(
                "S1",
                date(2026, 10, 10),
                "Ustudent",
                leave_only=True,
            )

        self.assertIsNone(result)

    def test_undo_reverts_every_change_in_a_range_batch(self) -> None:
        import json
        import database.google_sheets as google_sheets

        class AuditSheetStub:
            def __init__(self) -> None:
                self.rows = [
                    google_sheets.AUDIT_HEADERS,
                    [
                        "ACT1", "time", "Uadmin", "UPDATE", "S1",
                        "2026-10-08", "事假", "病假", "range:BATCH1", "FALSE",
                    ],
                    [
                        "ACT2", "time", "Uadmin", "UPDATE", "S1",
                        "2026-10-09", "事假", "病假", "range:BATCH1", "FALSE",
                    ],
                ]

            def get_all_values(self):
                return self.rows

            def update_cell(self, row: int, column: int, value: str) -> None:
                self.rows[row - 1][column - 1] = value

        sheet = AuditSheetStub()

        def record_undo(*args, **kwargs):
            sheet.rows.append(
                [
                    "UNDO1", "time", "Uadmin", "INSERT", args[0],
                    args[2].isoformat(), "", args[3], "Undo", "FALSE",
                ]
            )

        with (
            mock.patch.object(google_sheets, "_ensure_named_sheet", return_value=sheet),
            mock.patch.object(
                google_sheets,
                "find_student_by_id",
                return_value={"student_id": "S1", "name": "Student One"},
            ),
            mock.patch.object(
                google_sheets,
                "upsert_attendance_record",
                side_effect=record_undo,
            ) as upsert,
        ):
            result = google_sheets.undo_last_attendance_action("Uadmin")

        self.assertEqual(len(json.loads(result["records"])), 2)
        self.assertEqual(upsert.call_count, 2)
        self.assertEqual(sheet.rows[1][9], "TRUE")
        self.assertEqual(sheet.rows[2][9], "TRUE")
        self.assertEqual(sheet.rows[3][3], "UNDO")
        self.assertEqual(sheet.rows[4][3], "UNDO")


if __name__ == "__main__":
    unittest.main()
