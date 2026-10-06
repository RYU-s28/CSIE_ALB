import unittest

from attendance.attendance import AttendanceTracker
from bot.commands import handle_command


class HandleCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = AttendanceTracker()

    def test_general_commands_accept_optional_slash(self) -> None:
        self.assertEqual(
            handle_command("hello", self.tracker),
            "Hello! I am your attendance bot.",
        )
        self.assertEqual(
            handle_command(" /HELLO ", self.tracker),
            "Hello! I am your attendance bot.",
        )
        self.assertEqual(
            handle_command("help", self.tracker),
            "Commands: absent, attendance, clear, hello, help, ping, report, status, statusme, summary",
        )
        self.assertEqual(
            handle_command("/attendance", self.tracker),
            "Attendance tracking is ready.",
        )

    def test_ping_returns_pong(self) -> None:
        expected = "Pong! Attendance bot is online ✅"
        self.assertEqual(handle_command("/ping", self.tracker), expected)
        self.assertEqual(handle_command("ping", self.tracker), expected)

    def test_attendance_commands_are_handled(self) -> None:
        commands = {
            "statusme": "No attendance record found for you today.",
            "summary": "Today's Attendance Summary",
            "absent": "No absent students recorded today.",
            "status": "No attendance records stored for today.",
            "clear": "Today's attendance records cleared.",
        }

        for command, expected in commands.items():
            with self.subTest(command=command):
                self.assertIn(
                    expected,
                    handle_command(command, self.tracker, "student-1"),
                )
        self.assertTrue(
            handle_command("report", self.tracker, "student-1")
        )

    def test_unknown_text_is_not_a_command(self) -> None:
        self.assertIsNone(handle_command("I am present", self.tracker))


if __name__ == "__main__":
    unittest.main()
