import unittest

from bot.commands import handle_command


class HandleCommandTests(unittest.TestCase):
    def test_general_commands_accept_optional_slash(self) -> None:
        self.assertEqual(
            handle_command("hello"),
            "Hello! I am your attendance bot.",
        )
        self.assertEqual(
            handle_command(" /HELLO "),
            "Hello! I am your attendance bot.",
        )
        self.assertEqual(
            handle_command("help"),
            "Commands: hello, help, attendance, ping, statusme, summary, report, absent, status",
        )
        self.assertEqual(
            handle_command("/attendance"),
            "Attendance tracking is ready.",
        )

    def test_ping_returns_pong(self) -> None:
        self.assertEqual(handle_command("/ping"), "Pong!")
        self.assertEqual(handle_command("ping"), "Pong!")


if __name__ == "__main__":
    unittest.main()
