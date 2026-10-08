import importlib
import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs


class AttendancePostbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LINE_CHANNEL_SECRET": "test-secret",
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            },
        ):
            cls.app = importlib.import_module("app")

    def _event(self, data: str, *, group_id: str | None = None):
        return SimpleNamespace(
            postback=SimpleNamespace(data=data),
            source=SimpleNamespace(
                user_id="Ustudent",
                group_id=group_id,
                room_id=None,
            ),
            reply_token="reply-token",
        )

    def test_status_postback_checks_owner_and_returns_flex_card(self) -> None:
        record = {
            "student_id": "S1",
            "date": "2026-10-08",
            "type": "病假",
        }
        student = {"student_id": "S1"}
        with (
            mock.patch.object(
                self.app,
                "get_attendance_record_by_id",
                return_value=record,
            ),
            mock.patch.object(
                self.app,
                "find_student_by_line_user_id",
                return_value=student,
            ),
            mock.patch.object(self.app, "reply_to_line") as reply,
        ):
            self.app.handle_postback(
                self._event("action=status&record_id=ATT-0123456789ABCDEF")
            )

        response = reply.call_args.args[1]
        self.assertEqual(response.to_dict()["type"], "flex")

    def test_group_status_postback_pushes_private_card_without_disclosing_status(self) -> None:
        with (
            mock.patch.object(
                self.app,
                "get_attendance_record_by_id",
                return_value={
                    "student_id": "S1",
                    "date": "2026-10-08",
                    "type": "病假",
                },
            ),
            mock.patch.object(
                self.app,
                "find_student_by_line_user_id",
                return_value={"student_id": "S1"},
            ),
            mock.patch.object(self.app, "push_to_line", return_value=True) as push,
            mock.patch.object(self.app, "reply_to_line") as reply,
        ):
            self.app.handle_postback(
                self._event(
                    "action=status&record_id=ATT-0123456789ABCDEF",
                    group_id="Cgroup",
                )
            )

        push.assert_called_once()
        self.assertEqual(push.call_args.args[0], "Ustudent")
        self.assertEqual(push.call_args.args[1].to_dict()["type"], "flex")
        self.assertIn("private message", reply.call_args.args[1])

    def test_confirmed_withdrawal_deletes_only_the_owned_record(self) -> None:
        record_id = "ATT-0123456789ABCDEF"
        today = self.app._today_taipei().isoformat()
        record = {"student_id": "S1", "date": today, "type": "病假"}
        student = {"student_id": "S1"}
        expires = 2_000_000_000
        signature = self.app._withdrawal_signature(record_id, "Ustudent", expires)
        data = (
            f"action=confirm_withdraw&record_id={record_id}"
            f"&expires={expires}&token={signature}"
        )

        with (
            mock.patch.object(
                self.app,
                "get_attendance_record_by_id",
                return_value=record,
            ),
            mock.patch.object(
                self.app,
                "find_student_by_line_user_id",
                return_value=student,
            ),
            mock.patch.object(
                self.app,
                "delete_attendance_record",
                return_value={"old_status": "病假"},
            ) as delete_record,
            mock.patch.object(self.app, "reply_to_line") as reply,
        ):
            self.app.handle_postback(self._event(data))

        delete_record.assert_called_once_with(
            "S1",
            self.app._today_taipei(),
            "Ustudent",
            leave_only=True,
            attendance_record_id=record_id,
        )
        self.assertIn("was withdrawn", reply.call_args.args[1])

    def test_withdrawal_confirmation_card_creates_signed_confirmation(self) -> None:
        record_id = "ATT-0123456789ABCDEF"
        record = {
            "student_id": "S1",
            "date": self.app._today_taipei().isoformat(),
            "type": "病假",
        }
        student = {"student_id": "S1"}
        with (
            mock.patch.object(
                self.app,
                "get_attendance_record_by_id",
                return_value=record,
            ),
            mock.patch.object(
                self.app,
                "find_student_by_line_user_id",
                return_value=student,
            ),
            mock.patch.object(self.app, "reply_to_line") as reply,
        ):
            self.app.handle_postback(
                self._event(f"action=withdraw&record_id={record_id}")
            )

        message = reply.call_args.args[1].to_dict()
        confirm_action = message["contents"]["footer"]["contents"][0]["action"]
        confirm_data = parse_qs(confirm_action["data"])
        self.assertEqual(confirm_data["action"], ["confirm_withdraw"])
        self.assertEqual(confirm_data["record_id"], [record_id])
        self.assertTrue(confirm_data["token"][0])

    def _message_event(self):
        return SimpleNamespace(
            message=SimpleNamespace(text="I am sick today"),
            source=SimpleNamespace(
                user_id="Ustudent",
                group_id="Cgroup",
                room_id=None,
            ),
            reply_token="reply-token",
        )

    def _attendance_record(self):
        return SimpleNamespace(
            student_id="S1",
            status="sick_leave",
            message="I am sick today",
            attendance_date=self.app._today_taipei(),
            confidence=0.95,
            attendance_intent=True,
        )

    def test_saved_leave_sends_flex_confirmation_after_sheet_write(self) -> None:
        analysis = SimpleNamespace(
            intent="LEAVE",
            reasoning="Explicit leave message",
            to_classification_result=lambda: SimpleNamespace(
                status="sick_leave",
            ),
        )
        with (
            mock.patch.object(
                self.app,
                "classify_attendance_message",
                return_value=analysis,
            ),
            mock.patch.object(
                self.app,
                "identify_or_register_student",
                return_value=SimpleNamespace(
                    student={
                        "student_id": "S1",
                        "chinese_name": "Sample Student",
                    }
                ),
            ),
            mock.patch.object(
                self.app.tracker,
                "add_from_message",
                return_value=self._attendance_record(),
            ),
            mock.patch.object(
                self.app,
                "append_attendance_row",
                return_value="ATT-0123456789ABCDEF",
            ) as append_row,
            mock.patch.object(self.app, "reply_to_line") as reply,
        ):
            self.app.handle_message(self._message_event())

        append_row.assert_called_once()
        confirmation = reply.call_args.args[1].to_dict()
        self.assertEqual(confirmation["type"], "flex")
        self.assertIn(
            "ATT-0123456789ABCDEF",
            str(confirmation["contents"]),
        )

    def test_failed_sheet_write_never_sends_green_confirmation_card(self) -> None:
        analysis = SimpleNamespace(
            intent="LEAVE",
            reasoning="Explicit leave message",
            to_classification_result=lambda: SimpleNamespace(
                status="sick_leave",
            ),
        )
        with (
            mock.patch.object(
                self.app,
                "classify_attendance_message",
                return_value=analysis,
            ),
            mock.patch.object(
                self.app,
                "identify_or_register_student",
                return_value=SimpleNamespace(
                    student={
                        "student_id": "S1",
                        "chinese_name": "Sample Student",
                    }
                ),
            ),
            mock.patch.object(
                self.app.tracker,
                "add_from_message",
                return_value=self._attendance_record(),
            ),
            mock.patch.object(self.app, "append_attendance_row", return_value=None),
            mock.patch.object(self.app, "reply_to_line") as reply,
        ):
            self.app.handle_message(self._message_event())

        self.assertIsInstance(reply.call_args.args[1], str)
        self.assertIn("Google Sheets", reply.call_args.args[1])
