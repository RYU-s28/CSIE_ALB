import importlib
import os
import unittest
from types import SimpleNamespace
from unittest import mock


class IdentifyOrRegisterStudentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LINE_CHANNEL_SECRET": "test-secret",
                "LINE_CHANNEL_ACCESS_TOKEN": "test-token",
            },
        ):
            cls.app_module = importlib.import_module("app")

    def setUp(self) -> None:
        self.event = SimpleNamespace(
            source=SimpleNamespace(user_id=" U123 ", group_id="C123"),
        )

    def test_registered_user_id_is_checked_before_profile(self) -> None:
        student = {"student_id": "1", "name": "Student One"}
        with (
            mock.patch.object(
                self.app_module,
                "find_student_by_line_user_id",
                return_value=student,
            ),
            mock.patch.object(self.app_module, "get_line_group_member_profile") as profile,
        ):
            result = self.app_module.identify_or_register_student(self.event)

        self.assertEqual(result.status, "identified")
        self.assertIs(result.student, student)
        profile.assert_not_called()

    def test_unique_display_name_match_registers_line_user(self) -> None:
        student = {
            "student_id": "24113328",
            "name": "Michael Arbor",
            "line_user_id": "",
            "_row_number": 2,
            "_line_user_id_column": 6,
        }
        with (
            mock.patch.object(
                self.app_module,
                "find_student_by_line_user_id",
                return_value=None,
            ),
            mock.patch.object(
                self.app_module,
                "get_line_group_member_profile",
                return_value="MICHAEL(潘伯森)",
            ) as profile,
            mock.patch.object(
                self.app_module,
                "find_students_by_display_name",
                return_value=[student],
            ),
            mock.patch.object(self.app_module, "register_line_user") as register,
        ):
            result = self.app_module.identify_or_register_student(self.event)

        profile.assert_called_once_with("C123", "U123")
        register.assert_called_once_with(student, "U123")
        self.assertEqual(result.status, "registered")
        self.assertEqual(result.student["line_user_id"], "U123")

    def test_ambiguous_or_missing_matches_do_not_register(self) -> None:
        with (
            mock.patch.object(
                self.app_module,
                "find_student_by_line_user_id",
                return_value=None,
            ),
            mock.patch.object(
                self.app_module,
                "get_line_group_member_profile",
                return_value="Shared Name",
            ),
            mock.patch.object(
                self.app_module,
                "find_students_by_display_name",
                return_value=[
                    {"student_id": "1", "name": "First"},
                    {"student_id": "2", "name": "Second"},
                ],
            ),
            mock.patch.object(self.app_module, "register_line_user") as register,
        ):
            result = self.app_module.identify_or_register_student(self.event)
        self.assertEqual(result.status, "ambiguous")
        register.assert_not_called()

        with (
            mock.patch.object(
                self.app_module,
                "find_student_by_line_user_id",
                return_value=None,
            ),
            mock.patch.object(
                self.app_module,
                "get_line_group_member_profile",
                return_value="Shared Name",
            ),
            mock.patch.object(
                self.app_module,
                "find_students_by_display_name",
                return_value=[],
            ),
            mock.patch.object(self.app_module, "register_line_user") as register,
        ):
            result = self.app_module.identify_or_register_student(self.event)
        self.assertEqual(result.status, "unmatched")
        register.assert_not_called()


if __name__ == "__main__":
    unittest.main()
