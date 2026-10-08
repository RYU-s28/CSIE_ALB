import os
import unittest
from datetime import date, timedelta
from unittest import mock

from attendance.attendance import AttendanceTracker
from bot import commands
from bot.commands import handle_command, normalize_command


class HandleCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = AttendanceTracker()

    def test_public_hello_lists_only_student_commands(self) -> None:
        response = handle_command(".hello", self.tracker)
        self.assertIn(".statusme [date]", response)
        self.assertIn(".clear [date]", response)
        self.assertIn(".ticket <message>", response)
        self.assertNotIn(".report", response)

    def test_normalize_command_ignores_arguments_and_dot_prefix(self) -> None:
        self.assertEqual(normalize_command(".statusme tomorrow"), "statusme")
        self.assertEqual(normalize_command("/hello"), "hello")

    def test_ordinary_messages_with_apostrophes_are_not_parsed_as_commands(self) -> None:
        for text in (
            "I can't work tomorrow because im not feeling well",
            "I'm having period cramps. I won't work this afternoon.",
            "That's not a command",
        ):
            with self.subTest(text=text):
                self.assertIsNone(handle_command(text, self.tracker, "Ustudent"))

    def test_removed_public_commands_are_not_handled(self) -> None:
        for text in (".help", ".absent", ".attendance"):
            with self.subTest(text=text):
                response = handle_command(text, self.tracker, "Ustudent")
                self.assertIn("removed", response)
        self.assertIn(
            "admin",
            handle_command(".ping", self.tracker, "Ustudent").lower(),
        )

    def test_admin_commands_require_permanent_user_id_allowlist(self) -> None:
        with mock.patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin,Uother"}):
            self.assertEqual(
                handle_command(".ping", self.tracker, "Uadmin"),
                "Pong! Attendance bot is online.",
            )
            self.assertIn(
                "administrators only",
                handle_command(".ping", self.tracker, "Ustudent"),
            )

    def test_admin_id_parser_handles_quoted_csv_and_environment_assignment(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"ADMIN_LINE_USER_IDS": 'ADMIN_LINE_USER_IDS="Uadmin, Usecond"'},
        ):
            self.assertEqual(commands._admin_ids(), {"Uadmin", "Usecond"})
            self.assertEqual(
                handle_command(".ping", self.tracker, "Uadmin"),
                "Pong! Attendance bot is online.",
            )

    def test_admin_match_trims_incoming_line_id_and_admin_help_routes_first(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"ADMIN_LINE_USER_IDS": "Uad570f7ac10f300ae23c2cd0a613719d"},
        ):
            self.assertTrue(
                commands.is_admin_user(" Uad570f7ac10f300ae23c2cd0a613719d ")
            )
            response = handle_command(
                ".help",
                self.tracker,
                "Uad570f7ac10f300ae23c2cd0a613719d",
            )

        self.assertIn(".adminhelp", response)
        self.assertNotIn("public command has been removed", response)

    def test_missing_admin_variable_returns_deployment_hint(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            response = handle_command(".ping", self.tracker, "Uadmin")

        self.assertIn("not configured in this running bot", response)

    def test_statusme_reads_student_record_by_id_and_date(self) -> None:
        with mock.patch.object(
            commands.google_sheets,
            "get_attendance_record",
            return_value={"type": "病假"},
        ) as get_record:
            response = handle_command(
                ".statusme 2026-10-10",
                self.tracker,
                "U123",
                student_id="S1",
            )

        self.assertEqual(response, "2026-10-10: 病假")
        get_record.assert_called_once_with("S1", date(2026, 10, 10))

    def test_student_clear_withdraws_only_own_future_leave(self) -> None:
        with (
            mock.patch.object(commands, "_today", return_value=date(2026, 10, 6)),
            mock.patch.object(
                commands.google_sheets,
                "delete_attendance_record",
                return_value={"old_status": "病假", "action_id": "ABCD"},
            ) as delete_record,
        ):
            response = handle_command(
                ".clear tomorrow",
                self.tracker,
                "U123",
                student_id="S1",
            )
        self.assertIn("2026-10-07", response)
        delete_record.assert_called_once_with(
            "S1",
            date(2026, 10, 7),
            "U123",
            leave_only=True,
        )

    def test_student_clear_does_not_allow_past_dates(self) -> None:
        with mock.patch.object(commands, "_today", return_value=date(2026, 10, 6)):
            response = handle_command(
                ".clear 2026-10-05",
                self.tracker,
                "U123",
                student_id="S1",
            )
        self.assertIn("only withdraw today's or a future", response)

    def test_set_upserts_using_student_id_status_alias_and_date(self) -> None:
        student = {"student_id": "S1", "name": "杜榮瑪"}
        with (
            mock.patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}),
            mock.patch.object(
                commands.google_sheets,
                "find_student_by_id",
                return_value=student,
            ),
            mock.patch.object(
                commands.google_sheets,
                "upsert_attendance_record",
                return_value={"old_status": "病假", "action_id": "A1"},
            ) as upsert,
            mock.patch.object(commands, "_today", return_value=date(2026, 10, 6)),
        ):
            response = handle_command(
                '.set S1 personal 2026-10-10',
                self.tracker,
                "Uadmin",
            )
        self.assertIn("病假 → 事假", response)
        upsert.assert_called_once_with(
            "S1", "杜榮瑪", date(2026, 10, 10), "事假", "Uadmin",
        )

    def test_quoted_student_name_and_ambiguous_name_safe_error(self) -> None:
        with (
            mock.patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}),
            mock.patch.object(
                commands.google_sheets,
                "find_student_by_id",
                return_value=None,
            ) as find_student,
        ):
            response = handle_command(
                '.set "杜 榮瑪" sick',
                self.tracker,
                "Uadmin",
            )
        self.assertIn("ambiguous", response)
        find_student.assert_called_once_with("杜 榮瑪")

    def test_range_applies_only_work_calendar_dates(self) -> None:
        student = {"student_id": "S1", "name": "杜榮瑪"}
        with (
            mock.patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}),
            mock.patch.object(
                commands.google_sheets,
                "find_student_by_id",
                return_value=student,
            ),
            mock.patch.object(
                commands.google_sheets,
                "upsert_attendance_record",
            ) as upsert,
            mock.patch.object(
                commands,
                "is_workday",
                side_effect=lambda day: day.weekday() in {2, 3, 4, 5, 6},
            ),
        ):
            response = handle_command(
                ".range S1 sick 2026-10-06 2026-10-11",
                self.tracker,
                "Uadmin",
            )

        self.assertIn("Workdays affected: 5", response)
        self.assertEqual(upsert.call_count, 5)
        audit_groups = {
            call.kwargs["audit_details"]
            for call in upsert.call_args_list
        }
        self.assertEqual(len(audit_groups), 1)
        self.assertTrue(next(iter(audit_groups)).startswith("range:"))

    def test_admin_undo_formats_all_restored_range_dates(self) -> None:
        with (
            mock.patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}),
            mock.patch.object(
                commands.google_sheets,
                "undo_last_attendance_action",
                return_value={
                    "records": (
                        '[{"student_id":"S1","date":"2026-10-10",'
                        '"new_status":"病假","old_status":""}]'
                    )
                },
            ) as undo,
        ):
            response = handle_command(".undo", self.tracker, "Uadmin")

        self.assertIn("S1 / 2026-10-10", response)
        self.assertIn("病假 → no record", response)
        undo.assert_called_once_with("Uadmin")

    def test_admin_summary_and_report_date_dispatch(self) -> None:
        with (
            mock.patch.dict(os.environ, {"ADMIN_LINE_USER_IDS": "Uadmin"}),
            mock.patch.object(
                commands,
                "_report_data",
                return_value="formatted report",
            ) as report_data,
        ):
            self.assertEqual(
                handle_command(".summary tomorrow", self.tracker, "Uadmin"),
                "formatted report",
            )
            report_data.assert_called_once_with(
                commands._today() + timedelta(days=1),
                summary=True,
            )

    def test_summary_is_compact_and_counts_unique_sheet_attendance(self) -> None:
        with (
            mock.patch.object(
                commands.google_sheets,
                "get_report_students",
                return_value=({}, 12),
            ),
            mock.patch.object(
                commands.google_sheets,
                "get_attendance_rows",
                return_value=[
                    {"student_id": "S1", "type": "病假"},
                    {"student_id": "S1", "type": "事假"},
                    {"student_id": "S2", "type": "遲到"},
                ],
            ),
        ):
            summary = commands._report_data(date(2026, 10, 10), summary=True)

        self.assertEqual(
            summary,
            "「2026/10/10」（禮拜六）\n\n"
            "應到人數：12\n"
            "實到人數：11\n\n"
            "事假：1人\n"
            "@S1\n\n"
            "遲到：1人\n"
            "@S2",
        )

    def test_student_ticket_creates_a_sheet_ticket(self) -> None:
        with (
            mock.patch.object(
                commands.google_sheets,
                "create_ticket",
                return_value="A014",
            ) as create_ticket,
            mock.patch.object(
                commands.google_sheets,
                "find_student_by_id",
                return_value={"student_id": "S1", "name": "杜榮瑪"},
            ),
        ):
            response = handle_command(
                ".ticket I'm requesting a leave change.",
                self.tracker,
                "U123",
                student_id="S1",
            )
        self.assertIn("Ticket #A014", response)
        create_ticket.assert_called_once_with(
            "S1", "U123", "I'm requesting a leave change.",
        )


if __name__ == "__main__":
    unittest.main()
