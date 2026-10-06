import unittest
from datetime import date

from attendance.leave_message import (
    LEAVE_TYPE_LABELS,
    parse_attendance_date,
)
from attendance.student_directory import (
    find_student_by_line_user_id,
    find_student_by_name,
)


class LeaveMessageTests(unittest.TestCase):
    def test_tomorrow_is_relative_to_supplied_today(self) -> None:
        self.assertEqual(
            parse_attendance_date(
                "Sick leave tomorrow",
                today=date(2026, 10, 6),
            ),
            date(2026, 10, 7),
        )

    def test_explicit_date_is_parsed(self) -> None:
        self.assertEqual(
            parse_attendance_date(
                "Sick leave 2026-10-07",
                today=date(2026, 10, 6),
            ),
            date(2026, 10, 7),
        )

    def test_sick_leave_uses_sheet_label(self) -> None:
        self.assertEqual(LEAVE_TYPE_LABELS["sick_leave"], "病假")

    def test_line_user_id_returns_roster_identity(self) -> None:
        students = [
            {
                "student_id": 24113328,
                "name": "杜榮瑪",
                "line_user_id": "U123",
                "active": True,
            }
        ]

        self.assertEqual(
            find_student_by_line_user_id(students, "U123"),
            {"student_id": "24113328", "name": "杜榮瑪"},
        )

    def test_inactive_student_is_not_matched(self) -> None:
        students = [
            {
                "student_id": "24113328",
                "name": "杜榮瑪",
                "line_user_id": "U123",
                "active": False,
            }
        ]

        self.assertIsNone(find_student_by_line_user_id(students, "U123"))

    def test_display_name_matches_exactly(self) -> None:
        students = [
            {
                "student_id": "24113328",
                "name": "杜榮瑪",
                "line_user_id": "U123",
                "active": True,
            }
        ]

        self.assertEqual(
            find_student_by_name(students, "杜榮瑪"),
            {"student_id": "24113328", "name": "杜榮瑪"},
        )

    def test_ambiguous_display_name_is_not_matched(self) -> None:
        students = [
            {"student_id": "1", "name": "Same Name", "active": True},
            {"student_id": "2", "name": "Same Name", "active": True},
        ]

        self.assertIsNone(find_student_by_name(students, "Same Name"))


if __name__ == "__main__":
    unittest.main()