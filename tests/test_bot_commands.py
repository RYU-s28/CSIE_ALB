import unittest

from bot.commands import handle_command


class HandleCommandTests(unittest.TestCase):
    def test_ping_returns_pong(self) -> None:
        self.assertEqual(handle_command("/ping"), "Pong!")
        self.assertEqual(handle_command("ping"), "Pong!")


if __name__ == "__main__":
    unittest.main()
