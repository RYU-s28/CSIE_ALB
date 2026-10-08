import unittest

from bot.line_ui import welcome_message
from ui.leave_confirmation import (
    leave_confirmation_message,
    withdrawal_confirmation_message,
)


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

    def test_leave_confirmation_card_uses_persisted_data_and_postbacks(self) -> None:
        message = leave_confirmation_message(
            student_name="Sample Student",
            leave_date="2026/10/08",
            category="半天",
            record_id="ATT-00182",
        ).to_dict()

        self.assertEqual(message["type"], "flex")
        bubble = message["contents"]
        self.assertIn("半天 · Half Day", str(bubble))
        self.assertIn("ATT-00182", str(bubble))
        footer_contents = bubble["footer"]["contents"]
        buttons = [item for item in footer_contents if item["type"] == "button"]
        self.assertEqual(
            [button["action"]["data"] for button in buttons],
            [
                "action=status&record_id=ATT-00182",
                "action=correction&record_id=ATT-00182",
                "action=withdraw&record_id=ATT-00182",
            ],
        )

    def test_pending_card_is_not_confirmed_and_cannot_be_withdrawn(self) -> None:
        message = leave_confirmation_message(
            student_name="Sample Student",
            leave_date="2026/10/08",
            category="待確認",
            record_id="ATT-00182",
            confirmed=False,
            withdrawable=False,
        ).to_dict()

        serialized = str(message["contents"])
        self.assertIn("Pending", serialized)
        self.assertNotIn("Confirm", serialized)
        actions = [
            item["action"]["data"]
            for item in message["contents"]["footer"]["contents"]
            if item["type"] == "button"
        ]
        self.assertEqual(len(actions), 2)
        self.assertFalse(any("withdraw" in action for action in actions))

    def test_withdrawal_card_has_explicit_confirmation_postback(self) -> None:
        message = withdrawal_confirmation_message(
            category="病假",
            leave_date="2026/10/08",
            record_id="ATT-00182",
            confirmation_data="action=confirm_withdraw&record_id=ATT-00182",
        ).to_dict()

        buttons = message["contents"]["footer"]["contents"]
        self.assertEqual(
            buttons[0]["action"]["data"],
            "action=confirm_withdraw&record_id=ATT-00182",
        )
