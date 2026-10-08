import unittest

from bot.line_ui import welcome_message


class WelcomeMessageTests(unittest.TestCase):
    def test_welcome_message_has_flex_card_and_working_postback_actions(self) -> None:
        message = welcome_message()
        serialized = message.to_dict()

        self.assertEqual(serialized["type"], "flex")
        self.assertEqual(
            serialized["contents"]["header"]["contents"][0]["text"],
            "CSIE Attendance Bot",
        )
        quick_replies = serialized["quickReply"]["items"]
        self.assertEqual(
            [item["action"]["label"] for item in quick_replies],
            ["My Status", "Help", "Contact Admin"],
        )
        self.assertEqual(
            [item["action"]["data"] for item in quick_replies],
            ["action=statusme", "action=help", "action=contact"],
        )
